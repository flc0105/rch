"""Installed once outside Releases as the stable launchd ProgramArguments entry."""
import json
import os
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: launcher.py JOB_STATE_PATH')
    with open(sys.argv[1], encoding='utf-8') as handle:
        config = json.load(handle)
    script = os.path.abspath(config['script'])
    if not os.path.isfile(script):
        raise FileNotFoundError(f'Installed Client release missing: {script}')
    environment = os.environ.copy()
    environment.update(config.get('update_environment') or {})
    os.chdir(os.path.dirname(script))
    os.execve(sys.executable, [sys.executable, script, *config.get('args', [])], environment)


if __name__ == '__main__':
    main()
