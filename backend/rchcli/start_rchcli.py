import os
import sys
import runpy

RCH_HTTP_URL = 'http://127.0.0.1:8085'
RCH_ADMIN_TOKEN = 'yO6Fd83abNKbKWj8vVLZkz8Vm2hpkYWD0bwoQyKnY18'

os.environ['RCH_SERVER_URL'] = RCH_HTTP_URL
os.environ['RCH_API_TOKEN'] = RCH_ADMIN_TOKEN

cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rchcli.py')
sys.argv = [cli]
print('Starting RCH CLI...', flush=True)
runpy.run_path(cli, run_name='__main__')
