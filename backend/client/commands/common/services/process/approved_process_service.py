"""Process inspection and approved termination for Client shell-like commands.

All process discovery/signalling runs on the connected Client; there is no nested
Server-to-Client script command. Terminal output is plain text; approval payloads
are data rendered by the shared Interaction Broker.
"""
import os
import shutil
import signal
import socket
import subprocess

from client.commands.common.services.interaction_service import CommandInteractions


class ProcessApprovalError(RuntimeError):
    pass


class ClientCommandInteractions(CommandInteractions):
    """Process-specific Force switch validation after Broker approval."""

    def approve_processes(self, message, preview):
        result = self.request('preview', message, preview=preview,
                              title='Approve process termination', timeout=120)
        if result.get('status') != 'answered':
            raise ProcessApprovalError('Approval rejected, expired, or cancelled')
        choice = result.get('value')
        if (not isinstance(choice, dict) or set(choice) != {'force', 'selected_rows'}
                or type(choice['force']) is not bool
                or not isinstance(choice['selected_rows'], list)):
            raise ProcessApprovalError('Invalid process Preview reply')
        ids = choice['selected_rows']
        if (any(not isinstance(item, str) or item not in preview['row_ids'] for item in ids)
                or len(ids) != len(set(ids))):
            raise ProcessApprovalError('Invalid selected process IDs')
        return set(ids), choice['force']


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


def find_targets(criteria, *, preview_limit=None):
    import psutil
    if 'port' in criteria:
        ids = sorted(_port_owners(criteria['port']))
    elif 'pid' in criteria:
        ids = [criteria['pid']]
    else:
        ids = [proc.pid for proc in psutil.process_iter(['name'])
               if (proc.info.get('name') or '').casefold() == criteria['name'].casefold()]
    if preview_limit is not None and len(ids) > preview_limit:
        raise ProcessApprovalError(f'More than {preview_limit} processes matched; narrow the selection')
    rows = []
    for pid in ids:
        try:
            rows.append(inspect_process(pid, known_port=criteria.get('port')))
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            raise ProcessApprovalError(f'Access denied inspecting PID {pid}')
    return rows


def build_multi_preview(rows, *, criteria, force_default=False):
    """One selectable preview for all matched processes (all checked by default)."""
    return {
        'summary': [{'label': 'Matching processes', 'value': str(len(rows))},
                    {'label': 'Lookup', 'value': str(criteria)},
                    {'label': 'Signal', 'value': 'SIGKILL' if force_default else 'SIGTERM'}],
        'columns': [{'key': 'pid', 'label': 'PID'}, {'key': 'name', 'label': 'Name'},
                    {'key': 'user', 'label': 'User'}, {'key': 'exec_path', 'label': 'Executable'}],
        'rows': [{key: str(row.get(key, '')) for key in ('pid','name','user','exec_path')}
                 for row in rows],
        'row_ids': [str(row['pid']) for row in rows],
        'row_details': [{'row_id': str(row['pid']),
                         'content': f"PID: {row['pid']}\nCommand: {row['cmdline']}\nStarted: {row['created_at']}"}
                        for row in rows],
        'switches': [{'key': 'force', 'label': 'Force termination (SIGKILL / -9)',
                      'description': 'OFF: SIGTERM. ON: immediate SIGKILL.',
                      'default': bool(force_default)}],
        'notice': 'All matching processes are selected. Identities are rechecked before termination.',
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
