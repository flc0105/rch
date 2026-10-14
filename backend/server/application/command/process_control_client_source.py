"""Client-side process inspector for opt-in, approved RCH builtins.

Runs as a one-off Client Python script; signals are never sent by the Server host.
Only explicitly captured identities can be terminated after approval.
"""

PROCESS_CONTROL_SOURCE = r'''
import json
import os
import socket

MARKER = '__RCH_PROCESS_CONTROL_RESULT__:'


def run():
    import psutil

    action = str(kwargs.get('action') or '')
    pid = kwargs.get('pid')
    name = str(kwargs.get('name') or '').strip()
    port = kwargs.get('port')

    def safe(getter, default=None):
        try:
            return getter()
        except (psutil.Error, OSError, ValueError):
            return default

    def ports_for(proc):
        values = []
        for conn in safe(lambda: proc.net_connections(kind='inet'), []) or []:
            addr = conn.laddr
            if not addr or not getattr(addr, 'port', None):
                continue
            if conn.status != psutil.CONN_LISTEN and conn.type != socket.SOCK_DGRAM:
                continue
            values.append({'port': int(addr.port), 'address': str(addr.ip),
                           'protocol': 'udp' if conn.type == socket.SOCK_DGRAM else 'tcp'})
        return sorted(values, key=lambda x: (x['port'], x['protocol'], x['address']))

    def detail(proc):
        with proc.oneshot():
            return {
                'pid': proc.pid, 'ppid': safe(proc.ppid),
                'name': safe(proc.name, ''), 'user': safe(proc.username, ''),
                'exec_path': safe(proc.exe, ''), 'cmdline': safe(proc.cmdline, []),
                'cwd': safe(proc.cwd, ''), 'status': safe(proc.status, ''),
                'created_at': proc.create_time(), 'memory_rss': safe(lambda: proc.memory_info().rss, 0),
                'threads': safe(proc.num_threads), 'listening': ports_for(proc),
            }

    if action == 'inspect':
        if pid is not None:
            candidates = [psutil.Process(int(pid))]
        elif port is not None:
            wanted = int(port)
            if not (1 <= wanted <= 65535):
                raise ValueError('Port out of range')
            ids = set()
            for conn in psutil.net_connections(kind='inet'):
                addr = conn.laddr
                if conn.pid and addr and getattr(addr, 'port', None) == wanted and (
                    conn.status == psutil.CONN_LISTEN or conn.type == socket.SOCK_DGRAM
                ):
                    ids.add(conn.pid)
            candidates = [psutil.Process(i) for i in sorted(ids)]
        elif name:
            candidates = [proc for proc in psutil.process_iter(['name'])
                          if (proc.info['name'] or '').casefold() == name.casefold()]
        else:
            raise ValueError('PID, name or port required')
        rows = []
        for proc in candidates:
            try:
                entry = detail(proc)
                if port is not None and int(port) not in [x['port'] for x in entry['listening']]:
                    continue
                if name and (entry['name'] or '').casefold() != name.casefold():
                    continue
                rows.append(entry)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return {'processes': rows}

    if action == 'terminate':
        pid = int(pid)
        if pid <= 1 or pid == os.getpid():
            raise ValueError('Protected process PID')
        proc = psutil.Process(pid)
        captured = float(kwargs['created_at'])
        if abs(proc.create_time() - captured) > 0.00001:
            raise ValueError('Process identity changed since preview; refusing signal')
        if safe(proc.name, '') != kwargs.get('expected_name'):
            raise ValueError('Process name changed since preview; refusing signal')
        if safe(proc.exe, '') != kwargs.get('expected_exe'):
            raise ValueError('Executable changed since preview; refusing signal')
        if port is not None and int(port) not in [x['port'] for x in ports_for(proc)]:
            raise ValueError('Process no longer owns the previewed listening port')
        if kwargs.get('force') is True:
            proc.kill()
        else:
            proc.terminate()
        return {'sent': True, 'pid': pid, 'signal': 'SIGKILL' if kwargs.get('force') else 'SIGTERM'}
    raise ValueError('Unknown process control action')


try:
    result = run()
    print(MARKER + json.dumps({'ok': True, 'data': result}, ensure_ascii=False), flush=True)
except Exception as exc:
    print(MARKER + json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), flush=True)
'''
