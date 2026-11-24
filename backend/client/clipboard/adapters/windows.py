import io
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager

from PIL import Image
from client.runtime.temp_workspace import make_client_temp_file, cleanup_temp_path


_PACKAGED_FILE_CLIPBOARD_HELPER_SOURCE = r'''import ctypes
import os
import struct
import sys


CF_HDROP = 15
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


def _raise_last_error(message):
    error = ctypes.get_last_error()
    if error:
        raise OSError(error, f'{message}: {ctypes.FormatError(error)}')
    raise RuntimeError(message)


def main():
    paths = [os.path.abspath(path) for path in sys.argv[1:] if path]
    if not paths:
        raise ValueError('No clipboard files were provided')

    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f'Clipboard file does not exist: {path}')

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    user32.CreateWindowExW.argtypes = [
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_int

    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    hwnd = user32.CreateWindowExW(
        0,
        'STATIC',
        'RCH Clipboard File Helper',
        0,
        0,
        0,
        0,
        0,
        None,
        None,
        kernel32.GetModuleHandleW(None),
        None,
    )
    if not hwnd:
        _raise_last_error('Failed to create clipboard owner window')

    file_list = ('\x00'.join(paths) + '\x00\x00').encode('utf-16le')
    dropfiles = struct.pack('<IiiII', 20, 0, 0, 0, 1)
    payload = dropfiles + file_list

    hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(payload))
    if not hglobal:
        _raise_last_error('Failed to allocate CF_HDROP memory')

    clipboard_owns_memory = False
    try:
        target = kernel32.GlobalLock(hglobal)
        if not target:
            _raise_last_error('Failed to lock CF_HDROP memory')
        try:
            ctypes.memmove(target, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(hglobal)

        if not user32.OpenClipboard(hwnd):
            _raise_last_error('Failed to open Windows clipboard')
        try:
            if not user32.EmptyClipboard():
                _raise_last_error('Failed to empty Windows clipboard')

            if not user32.SetClipboardData(CF_HDROP, hglobal):
                _raise_last_error('Failed to set CF_HDROP clipboard data')
            clipboard_owns_memory = True
        finally:
            user32.CloseClipboard()
    finally:
        if not clipboard_owns_memory:
            kernel32.GlobalFree(hglobal)


if __name__ == '__main__':
    main()
'''


class WindowsClipboardAdapter:
    def get_capabilities(self) -> dict:
        return {'text': True, 'image': True, 'files': True}

    def _imports(self):
        import win32api
        import win32clipboard
        import win32con
        import win32gui
        return win32api, win32clipboard, win32con, win32gui

    def get_snapshot(self) -> dict:
        _, win32clipboard, win32con, _ = self._imports()
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                paths = [str(item) for item in (win32clipboard.GetClipboardData(win32con.CF_HDROP) or [])]
                paths = [path for path in paths if path and os.path.exists(path)]
                if paths:
                    return {'kind': 'files', 'paths': paths}

            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                dib = win32clipboard.GetClipboardData(win32con.CF_DIB)
                if dib:
                    bmp_header = self._build_bmp_header(dib)
                    image = Image.open(io.BytesIO(bmp_header + dib))
                    output = io.BytesIO()
                    image.save(output, format='PNG')
                    return {
                        'kind': 'image',
                        'data': output.getvalue(),
                        'format': 'png',
                        'width': int(image.width),
                        'height': int(image.height),
                    }

            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return {'kind': 'text', 'text': str(text or '')}

            return {'kind': 'empty'}
        finally:
            win32clipboard.CloseClipboard()

    def clear(self):
        with self._open_clipboard_for_write():
            pass

    def set_text(self, text: str):
        with self._open_clipboard_for_write() as (win32clipboard, win32con):
            win32clipboard.SetClipboardText(
                str(text or ''),
                win32con.CF_UNICODETEXT,
            )

    def set_image(self, image_path: str):
        image = Image.open(image_path).convert('RGB')
        output = io.BytesIO()
        image.save(output, format='BMP')
        dib = output.getvalue()[14:]

        with self._open_clipboard_for_write() as (win32clipboard, win32con):
            win32clipboard.SetClipboardData(win32con.CF_DIB, dib)

    def set_files(self, paths: list[str]):
        file_paths = [os.path.abspath(path) for path in paths if path]
        if not file_paths:
            raise ValueError('No clipboard files were provided')

        for path in file_paths:
            if not os.path.exists(path):
                raise FileNotFoundError(f'Clipboard file does not exist: {path}')

        command, helper_path, remove_helper = self._prepare_file_clipboard_helper()
        try:
            result = subprocess.run(
                [*command, helper_path, *file_paths],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Windows file clipboard helper timed out') from exc
        finally:
            if remove_helper:
                cleanup_temp_path(helper_path)

        if result.returncode != 0:
            message = (result.stderr or result.stdout or '').strip()
            raise RuntimeError(message or 'Failed to write files to Windows clipboard')

    def _prepare_file_clipboard_helper(self) -> tuple[list[str], str, bool]:
        if not getattr(sys, 'frozen', False):
            # 源码运行直接执行项目里的固定 helper，不产生临时脚本。
            helper_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'windows_file_clipboard_helper.py',
            )
            if not os.path.isfile(helper_path):
                raise RuntimeError(f'Windows clipboard helper not found: {helper_path}')
            return [os.path.realpath(sys.executable)], helper_path, False

        # 打包模式才动态生成 helper，并交给系统 Python 执行。
        python_executable = shutil.which('python.exe') or shutil.which('python3.exe')
        command = [python_executable] if python_executable else []
        if not command:
            py_launcher = shutil.which('py.exe')
            if py_launcher:
                command = [py_launcher, '-3']
        if not command:
            raise RuntimeError(
                'Python 3 is required for Windows file clipboard in packaged mode'
            )

        helper_fd, helper_path = make_client_temp_file(
            'clipboard_helper_temp',
            prefix='windows_',
            suffix='.py',
        )
        try:
            with os.fdopen(helper_fd, 'w', encoding='utf-8') as helper_file:
                helper_file.write(_PACKAGED_FILE_CLIPBOARD_HELPER_SOURCE)
        except Exception:
            try:
                cleanup_temp_path(helper_path)
            except OSError:
                pass
            raise

        return command, helper_path, True

    @contextmanager
    def _open_clipboard_for_write(self):
        win32api, win32clipboard, win32con, win32gui = self._imports()
        owner_hwnd = win32gui.CreateWindowEx(
            0,
            'STATIC',
            'RCH Clipboard Owner',
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            win32api.GetModuleHandle(None),
            None,
        )

        try:
            win32clipboard.OpenClipboard(owner_hwnd)
            try:
                win32clipboard.EmptyClipboard()
                yield win32clipboard, win32con
            finally:
                win32clipboard.CloseClipboard()
        finally:
            win32gui.DestroyWindow(owner_hwnd)

    @staticmethod
    def _build_bmp_header(dib: bytes) -> bytes:
        header_size = int.from_bytes(dib[0:4], 'little') if len(dib) >= 4 else 40
        bit_count = int.from_bytes(dib[14:16], 'little') if len(dib) >= 16 else 24
        colors_used = int.from_bytes(dib[32:36], 'little') if len(dib) >= 36 else 0
        if colors_used:
            color_table_size = colors_used * 4
        elif bit_count <= 8:
            color_table_size = (1 << bit_count) * 4
        else:
            color_table_size = 0
        pixel_offset = 14 + header_size + color_table_size
        file_size = 14 + len(dib)
        return (
            b'BM'
            + file_size.to_bytes(4, 'little')
            + b'\x00\x00\x00\x00'
            + pixel_offset.to_bytes(4, 'little')
        )
