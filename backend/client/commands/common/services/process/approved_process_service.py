"""Process inspection and approved termination for Client shell-like commands.

All process discovery/signalling runs on the connected Client; there is no nested
Server-to-Client script command. Terminal output is plain text; approval payloads
are data rendered by the shared Interaction Broker.
"""
import os
import shlex
import shutil
import signal
import socket
import subprocess

from client.commands.common.services.interaction_service import CommandInteractions


class ProcessApprovalError(RuntimeError):
    pass


class ClientCommandInteractions(CommandInteractions):
    """Process-specific Force switch validation after Broker approval."""

    def approve(self, message, preview):
        result = self.request('preview', message, preview=preview,
                              title='Approve process termination', timeout=120)
        if result.get('status') != 'answered':
            return None
        choice = result.get('value')
        if not isinstance(choice, dict) or type(choice.get('force')) is not bool or set(choice) != {'force'}:
            raise ProcessApprovalError('Invalid Force switch response from approval')
        return choice


def parse_target(text, *, by_port=False):
    """RCH shell-like grammar: <port|pid|name> [-9].

    A trailing -9 sets only the initial Preview Force switch state. The
    approved switch value, not the command text, decides the actual signal.
    """
    parts = shlex.split(str(text or '').strip())
    usage = ('kill_port <port> [-9]' if by_port
             else 'kill_proc <pid|name> [-9]')
    if not (len(parts) == 1 or (len(parts) == 2 and parts[1] == '-9')):
        raise ProcessApprovalError('Usage: ' + usage)
    target = parts[0]
    force_default = len(parts) == 2
    if by_port:
        if not target.isdecimal() or not 1 <= int(target) <= 65535:
            raise ProcessApprovalError('Port must be an integer from 1 to 65535')
        criteria = {'port': int(target)}
    elif target.isdecimal():
        if int(target) <= 1:
            raise ProcessApprovalError('Protected PID')
        criteria = {'pid': int(target)}
    elif target.startswith('-'):
        raise ProcessApprovalError('Expected a PID or process name')
    else:
        criteria = {'name': target}
    if force_default:
        criteria['force'] = True
    return criteria


def _port_owners_via_lsof(port):
    """Bounded, targeted lookup; avoids slow all-system psutil scans on macOS."""
    binary = shutil.which('lsof')
    if not binary:
        return None
    pids = set()
    for selector in (f'-iTCP:{port}', f'-iUDP:{port}'):
        argv = [binary, '-nP', selector, '-Fp']
        if selector.startswith('-iTCP:'):
            argv.insert(-1, '-sTCP:LISTEN')
        try:
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired as exc:
            raise ProcessApprovalError(f'Port {port} lookup exceeded 8 seconds') from exc
        if completed.returncode not in (0, 1):
            raise ProcessApprovalError('lsof could not inspect port ownership: '
                                       + (completed.stderr or '').strip()[:250])
        for line in completed.stdout.splitlines():
            if line.startswith('p') and line[1:].isdigit():
                pids.add(int(line[1:]))
    return pids


def _port_owners(port):
    import psutil
    native = _port_owners_via_lsof(port)
    if native is not None:
        return native
    try:
        connections = psutil.net_connections(kind='inet')
    except (psutil.AccessDenied, OSError) as exc:
        raise ProcessApprovalError(f'Cannot inspect port {port}: {exc}') from exc
    return {int(conn.pid) for conn in connections
            if conn.pid and conn.laddr and conn.laddr.port == port
            and (conn.status == psutil.CONN_LISTEN or conn.type == socket.SOCK_DGRAM)}


def inspect_process(pid, *, known_port=None):
    import psutil
    proc = psutil.Process(pid)
    def safe(method, default):
        try:
            return method()
        except (psutil.Error, OSError, ValueError):
            return default
    with proc.oneshot():
        row = {
            'pid': proc.pid, 'created_at': proc.create_time(),
            'name': safe(proc.name, ''), 'user': safe(proc.username, ''),
            'exec_path': safe(proc.exe, ''), 'cmdline': safe(proc.cmdline, []),
            'cwd': safe(proc.cwd, ''), 'ppid': safe(proc.ppid, 0),
            'status': safe(proc.status, ''), 'memory_rss': safe(lambda: proc.memory_info().rss, 0),
            'threads': safe(proc.num_threads, 0),
        }
    conns = safe(lambda: proc.net_connections(kind='inet'), []) or []
    row['listening'] = [
        {'port': int(c.laddr.port), 'address': str(c.laddr.ip),
         'protocol': 'udp' if c.type == socket.SOCK_DGRAM else 'tcp'}
        for c in conns if c.laddr and getattr(c.laddr, 'port', None)
        and (c.status == psutil.CONN_LISTEN or c.type == socket.SOCK_DGRAM)
    ]
    if known_port and known_port not in {c['port'] for c in row['listening']}:
        # The privileged system socket table may not be visible from proc.net_connections.
        # Ownership is still checked via lsof during lookup and immediately before kill.
        row['listening'].append({'port': known_port, 'address': '(owner verified by lsof)',
                                 'protocol': 'tcp/udp'})
    return row


def find_targets(criteria):
    import psutil
    if 'port' in criteria:
        ids = sorted(_port_owners(criteria['port']))
    elif 'pid' in criteria:
        ids = [criteria['pid']]
    else:
        ids = [proc.pid for proc in psutil.process_iter(['name'])
               if (proc.info.get('name') or '').casefold() == criteria['name'].casefold()]
    if len(ids) > 24:
        raise ProcessApprovalError('More than 24 processes matched; specify a PID')
    rows = []
    for pid in ids:
        try:
            rows.append(inspect_process(pid, known_port=criteria.get('port')))
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            raise ProcessApprovalError(f'Access denied inspecting PID {pid}')
    return rows


def build_preview(row, *, port=None, force_default=False):
    summary = [
        {'label': key, 'value': str(value)} for key, value in (
            ('PID', row['pid']), ('Name', row['name']), ('User', row['user']),
            ('Executable', row['exec_path']),
            ('Initial signal (editable below)', 'SIGKILL' if force_default else 'SIGTERM'),
        )
    ]
    detail_text = '\n'.join([
        f"PID: {row['pid']}", f"Name: {row['name']}", f"User: {row['user']}",
        f"Executable: {row['exec_path']}", f"Command: {row['cmdline']}",
        f"CWD: {row['cwd']}", f"Parent: {row['ppid']}", f"Status: {row['status']}",
        f"Started: {row['created_at']}", f"RSS: {row['memory_rss']}",
        f"Threads: {row['threads']}",
    ])
    return {
        'summary': summary,
        'columns': [{'key': 'protocol', 'label': 'Protocol'},
                    {'key': 'address', 'label': 'Address'},
                    {'key': 'port', 'label': 'Port'}],
        'rows': [{key: str(row_item[key]) for key in ('protocol', 'address', 'port')}
                 for row_item in row['listening'][:100]],
        'details': [{'title': 'Process details', 'content': detail_text}],
        'notice': ('Listening port ownership will be rechecked before termination. '
                   if port else '') + 'Process identity will be rechecked before sending a signal.',
        'switches': [{
            'key': 'force', 'label': 'Force termination (SIGKILL / -9)',
            'description': 'Disabled: SIGTERM. Enabled: immediate SIGKILL; no graceful shutdown.',
            'default': bool(force_default),
        }],
    }


def terminate_verified(row, *, force, port=None):
    import psutil
    pid = int(row['pid'])
    if pid <= 1 or pid == os.getpid():
        raise ProcessApprovalError('Protected PID')
    # PID reuse, binary/name changes and port reassignment all fail closed.
    try:
        proc = psutil.Process(pid)
        if (abs(proc.create_time() - row['created_at']) > 0.00001
                or proc.name() != row['name'] or proc.exe() != row['exec_path']):
            raise ProcessApprovalError('Process identity changed since preview')
        if port is not None and pid not in _port_owners(port):
            raise ProcessApprovalError('The process no longer owns the previewed port')
        # Verify the same PID identity once more immediately before signalling.
        if abs(proc.create_time() - row['created_at']) > 0.00001:
            raise ProcessApprovalError('Process was replaced after approval')
        if force:
            proc.kill()
        else:
            proc.terminate()
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied) as exc:
        raise ProcessApprovalError(f'Process unavailable or access denied: {exc}') from exc
    return 'SIGKILL' if force else 'SIGTERM'
