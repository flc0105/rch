import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from core.device.local_identity import get_local_identity


def check_privilege():
    if os.name == 'posix':
        if os.geteuid() == 0:
            if 'SUDO_USER' in os.environ:
                return 'Root (via sudo)'
            return 'Root'
        return 'User'
    if os.name == 'nt':
        from client.commands.platform.utils.win_util import get_integrity_level
        return get_integrity_level()

    return 'N/A'


def wrap_path(path):
    """如果路径包含空格，用双引号包裹"""
    return f'"{path}"' if ' ' in path else path


def get_executable_argv(*, include_runtime_args=True):
    """统一生成当前 Client 的 argv，供 subprocess / execv 直接使用。"""
    argv = [os.path.realpath(sys.executable)]
    if not getattr(sys, 'frozen', False):
        argv.append(os.path.realpath(sys.argv[0]))
    if include_runtime_args:
        argv.extend(sys.argv[1:])
    return argv


def get_executable_path():
    """获取当前 Client 的启动命令，用于 Shell、launchd 和状态展示。

    源码模式包含 Python、脚本及参数；打包模式包含程序及运行参数。
    与 subprocess 使用的 argv 共用同一份来源。
    """
    argv = get_executable_argv()
    if os.name == 'nt':
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def get_runtime_root() -> str:
    """
    获取 RCH Client 运行时根目录。

    - 源码模式：rchclient.py（即当前启动脚本）所在目录
    - 打包模式：当前 Client 可执行文件所在目录
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.realpath(sys.executable))

    script_path = os.path.realpath(sys.argv[0])
    return os.path.dirname(script_path)


def get_executable_path_for_shell():
    """返回 (shell, args) 元组，用于 ShellExecuteW。"""
    argv = get_executable_argv()
    if getattr(sys, 'frozen', False):
        return argv[0], subprocess.list2cmdline(argv[1:]) or None
    return r'c:\windows\system32\cmd.exe', '/c ' + subprocess.list2cmdline(argv)


def get_exec_and_args():
    """返回 (executable, parameters)，用于 ShellExecuteW。

    源码模式：Python 解释器 + 脚本路径和运行参数；
    打包模式：可执行文件 + 运行参数。
    """
    argv = get_executable_argv()
    return argv[0], subprocess.list2cmdline(argv[1:]) or None


def get_system_paths():
    # 获取系统路径
    platform_alias = get_local_identity().os_alias
    system_paths = {}
    if platform_alias == 'win':
        system_paths['root'] = 'C:\\'
    else:
        system_paths['root'] = '/'

    system_paths['home'] = str(Path.home())
    system_paths['desktop'] = str(Path.home() / 'Desktop')
    system_paths['documents'] = str(Path.home() / 'Documents')
    system_paths['downloads'] = str(Path.home() / 'Downloads')

    import tempfile
    system_paths['temp'] = str(tempfile.gettempdir())

    if platform_alias == 'ios':
        from client.commands.platform.utils.ios_util import get_icloud_path, read_info_plist
        system_paths['icloud'] = get_icloud_path(read_info_plist())

    if getattr(sys, 'frozen', False):
        system_paths['executable'] = os.path.dirname(sys.executable)
    else:
        script_path = os.path.realpath(sys.argv[0])
        argv = wrap_path(script_path)
        system_paths['executable'] = os.path.dirname(argv)

    return system_paths



class ScriptArgError(Exception):
    pass



def require_kwarg(kwargs, name, default='', allow_empty=False, error_prefix='[参数异常]'):
    value = kwargs.get(name, default)

    if allow_empty:
        return value

    if value is None:
        print(f'{error_prefix} 缺少必要参数: {name}')
        raise ScriptArgError(f'缺少必要参数: {name}')

    if isinstance(value, str) and not value.strip():
        print(f'{error_prefix} 缺少必要参数: {name}')
        raise ScriptArgError(f'缺少必要参数: {name}')

    return value


def reset(socket):
    spawn_new_instance()
    socket.report_session_end('client_restart', command='relaunch_instance')

    manager = getattr(socket, 'process_recovery_watchdog_manager', None)
    if manager is not None:
        manager.stop()

    try:
        socket.close()
    except Exception:
        pass

    os._exit(0)


def reexec_restart(socket):
    socket.report_session_end('client_restart', command='reexec_instance')

    try:
        socket.close()
    except Exception:
        pass

    launch_cwd = get_runtime_root()
    try:
        os.chdir(launch_cwd)
    except Exception:
        pass

    # Shell 命令不能反向 split 成 argv，尤其是 Windows 含空格路径。
    argv = get_executable_argv()
    os.execv(argv[0], argv)


def spawn_new_instance(*, start_new_session=True, stderr_path=''):
    restart_argv = get_executable_argv()
    launch_cwd = get_runtime_root()

    from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment

    stderr_file = open(stderr_path, 'ab') if stderr_path else None
    popen_kwargs = {
        'cwd': launch_cwd,
        'env': without_process_recovery_watchdog_environment(),
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': stderr_file or subprocess.DEVNULL,
        'close_fds': True,
    }

    try:
        return _spawn_new_instance_process(restart_argv, popen_kwargs, start_new_session)
    finally:
        if stderr_file is not None:
            stderr_file.close()


def _spawn_new_instance_process(restart_argv, popen_kwargs, start_new_session):
    if os.name == 'nt':
        creationflags = 0
        creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        creationflags |= getattr(subprocess, 'DETACHED_PROCESS', 0)

        return subprocess.Popen(
            restart_argv,
            shell=False,
            creationflags=creationflags,
            **popen_kwargs,
        )

    if os.name == 'posix':
        return subprocess.Popen(
            restart_argv,
            shell=False,
            start_new_session=start_new_session,
            **popen_kwargs,
        )

    raise RuntimeError(f'Unsupported os.name: {os.name}')


def ensure_directory(path: str) -> str:
    directory = os.path.abspath(path)
    os.makedirs(directory, exist_ok=True)
    return directory


def get_client_bundle_release_dir() -> str:
    # update 默认 bundle 版本目录
    if get_local_identity().os_alias != 'ios':
        return ensure_directory(os.path.join(str(Path.home()), 'client_bundle', 'releases'))
    else:
        return ensure_directory(os.path.join(str(Path.home()), 'Documents', 'client_bundle', 'releases'))


def get_client_bundle_download_dir() -> str:
    return ensure_directory(os.path.join(os.path.dirname(get_client_bundle_release_dir()), 'downloads'))


def build_bundle_extract_dir(release_dir: str, file_name: str) -> str:
    base_name = os.path.splitext(os.path.basename(file_name))[0] or 'client_bundle'
    return os.path.join(os.path.abspath(release_dir), base_name)



def _resolve_python_command_for_source_bundle() -> list[str]:
    if not getattr(sys, 'frozen', False):
        return [os.path.realpath(sys.executable)]

    candidates = []

    env_python = os.environ.get('PYTHON_EXECUTABLE', '').strip()
    if env_python:
        candidates.append([env_python])

    python3_path = shutil.which('python3')
    if python3_path:
        candidates.append([python3_path])

    python_path = shutil.which('python')
    if python_path:
        candidates.append([python_path])

    py_launcher = shutil.which('py')
    if py_launcher:
        candidates.append([py_launcher, '-3'])

    if not candidates:
        raise RuntimeError('Python interpreter not found; cannot launch source bundle')

    return candidates[0]


def spawn_detached_python_script(script_path: str, cwd: str = '', args=None, stderr_path: str = ''):
    script_path = os.path.abspath(script_path)
    launch_cwd = os.path.abspath(cwd) if cwd else os.path.dirname(script_path)
    command = _resolve_python_command_for_source_bundle() + [script_path]

    if args:
        command.extend(str(item) for item in args)

    stderr_file = None
    if stderr_path:
        stderr_file = open(os.path.abspath(stderr_path), 'ab')

    from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment

    popen_kwargs = {
        'cwd': launch_cwd,
        'env': without_process_recovery_watchdog_environment(),
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': stderr_file or subprocess.DEVNULL,
        'close_fds': True,
        'shell': False,
    }

    try:
        if os.name == 'nt':
            creationflags = 0
            creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            creationflags |= getattr(subprocess, 'DETACHED_PROCESS', 0)
            return subprocess.Popen(command, creationflags=creationflags, **popen_kwargs)

        if os.name == 'posix':
            return subprocess.Popen(command, start_new_session=True, **popen_kwargs)

        raise RuntimeError(f'Unsupported os.name: {os.name}')
    finally:
        if stderr_file is not None:
            stderr_file.close()


def is_process_alive(pid: int) -> bool:
    try:
        pid = int(pid)
    except Exception:
        return False

    if pid <= 0:
        return False

    if os.name == 'nt':
        # Windows 下不能用 os.kill(pid, 0) 探活，否则可能直接终止目标进程
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259

        process_handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not process_handle:
            return False

        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(process_handle)

    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False





def upload_file_via_http(file_source=None, filename=None, upload_url=None, category=None, client_id=None):
    import os
    import requests

    form_data = {
        'artifact_type': 'files',
        'category': category,
        'client_id': client_id,
    }

    close_after = False

    if isinstance(file_source, str):
        file_obj = open(file_source, 'rb')
        close_after = True
        upload_name = filename or os.path.basename(file_source)
    else:
        file_obj = file_source
        upload_name = filename or getattr(file_obj, 'name', None) or 'upload.bin'

    try:
        try:
            file_obj.seek(0)
        except Exception:
            pass

        files = {
            'file': (upload_name, file_obj)
        }

        response = requests.post(
            upload_url,
            files=files,
            data=form_data,
            timeout=30,
        )

        return response

    finally:
        if close_after:
            try:
                file_obj.close()
            except Exception:
                pass
