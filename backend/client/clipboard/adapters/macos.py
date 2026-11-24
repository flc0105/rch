import io
import os
import shutil
import subprocess
import sys

from PIL import Image
from client.runtime.temp_workspace import make_client_temp_file, cleanup_temp_path


_PACKAGED_FILE_CLIPBOARD_HELPER_SOURCE = r'''import os
import sys

from AppKit import NSPasteboard
from Foundation import NSURL


def main():
    paths = [os.path.abspath(path) for path in sys.argv[1:] if path]
    if not paths:
        raise ValueError('No clipboard files were provided')

    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f'Clipboard file does not exist: {path}')

    urls = [NSURL.fileURLWithPath_(path) for path in paths]
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()

    if not pasteboard.writeObjects_(urls):
        raise RuntimeError('Failed to write file URLs to macOS clipboard')


if __name__ == '__main__':
    main()
'''


class MacOSClipboardAdapter:
    def _imports(self):
        from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeString, NSPasteboardTypeTIFF
        from Foundation import NSData, NSURL
        try:
            from AppKit import NSPasteboardURLReadingFileURLsOnlyKey
        except ImportError:
            NSPasteboardURLReadingFileURLsOnlyKey = 'NSPasteboardURLReadingFileURLsOnlyKey'
        return (
            NSPasteboard,
            NSPasteboardTypePNG,
            NSPasteboardTypeString,
            NSPasteboardTypeTIFF,
            NSPasteboardURLReadingFileURLsOnlyKey,
            NSData,
            NSURL,
        )

    def get_capabilities(self) -> dict:
        try:
            self._imports()
            return {'text': True, 'image': True, 'files': True}
        except Exception:
            return {'text': False, 'image': False, 'files': False}

    def get_snapshot(self) -> dict:
        (
            NSPasteboard,
            NSPasteboardTypePNG,
            NSPasteboardTypeString,
            NSPasteboardTypeTIFF,
            NSPasteboardURLReadingFileURLsOnlyKey,
            _,
            NSURL,
        ) = self._imports()
        pasteboard = NSPasteboard.generalPasteboard()

        urls = pasteboard.readObjectsForClasses_options_(
            [NSURL],
            {NSPasteboardURLReadingFileURLsOnlyKey: True},
        ) or []
        paths = []
        for url in urls:
            try:
                path = str(url.path() or '')
            except Exception:
                path = ''
            if path and os.path.exists(path):
                paths.append(path)
        if paths:
            return {'kind': 'files', 'paths': paths}

        data = pasteboard.dataForType_(NSPasteboardTypePNG)
        image_format = 'png'
        if data is None:
            data = pasteboard.dataForType_(NSPasteboardTypeTIFF)
            image_format = 'tiff'
        if data is not None:
            return {'kind': 'image', 'data': bytes(data), 'format': image_format}

        text = pasteboard.stringForType_(NSPasteboardTypeString)
        if text is not None:
            return {'kind': 'text', 'text': str(text)}

        return {'kind': 'empty'}

    def clear(self):
        NSPasteboard, *_ = self._imports()
        NSPasteboard.generalPasteboard().clearContents()

    def set_text(self, text: str):
        NSPasteboard, _, NSPasteboardTypeString, _, _, _, _ = self._imports()
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        if not pasteboard.setString_forType_(str(text or ''), NSPasteboardTypeString):
            raise RuntimeError('Failed to write text to macOS clipboard')

    def set_image(self, image_path: str):
        NSPasteboard, NSPasteboardTypePNG, _, _, _, NSData, _ = self._imports()
        image = Image.open(image_path)
        output = io.BytesIO()
        image.save(output, format='PNG')
        raw = output.getvalue()
        data = NSData.dataWithBytes_length_(raw, len(raw))
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        if not pasteboard.setData_forType_(data, NSPasteboardTypePNG):
            raise RuntimeError('Failed to write image to macOS clipboard')

    def set_files(self, paths: list[str]):
        file_paths = [os.path.abspath(path) for path in paths if path]
        if not file_paths:
            raise ValueError('No clipboard files were provided')

        for path in file_paths:
            if not os.path.exists(path):
                raise FileNotFoundError(f'Clipboard file does not exist: {path}')

        python_executable, helper_path, remove_helper = self._prepare_file_clipboard_helper()

        try:
            result = subprocess.run(
                [python_executable, helper_path, *file_paths],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('macOS file clipboard helper timed out') from exc
        finally:
            if remove_helper:
                cleanup_temp_path(helper_path)

        if result.returncode != 0:
            message = (result.stderr or result.stdout or '').strip()
            raise RuntimeError(message or 'Failed to write file URLs to macOS clipboard')

    def _prepare_file_clipboard_helper(self) -> tuple[str, str, bool]:
        if not getattr(sys, 'frozen', False):
            # 源码运行直接执行项目里的固定 helper，不产生临时脚本。
            helper_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'macos_file_clipboard_helper.py',
            )
            if not os.path.isfile(helper_path):
                raise RuntimeError(f'macOS clipboard helper not found: {helper_path}')

            return os.path.realpath(sys.executable), helper_path, False

        # 打包模式才动态生成 helper，并交给系统 Python 执行。
        python_executable = shutil.which('python3')
        if not python_executable:
            raise RuntimeError(
                'python3 is required for macOS file clipboard in packaged mode'
            )

        helper_fd, helper_path = make_client_temp_file(
            'clipboard_helper_temp',
            prefix='macos_',
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

        return python_executable, helper_path, True