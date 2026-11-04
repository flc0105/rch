#!/usr/bin/env python3
"""Remote RCH operator console (HTTP command API + WebSocket events).

Only the Server interprets RCH commands. This program implements the console
navigation and the transport needed to receive their live output.
"""

import argparse
import getpass
import json
import os
import queue
import sys
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RchCliError(Exception):
    pass


def endpoint_urls(base_url, websocket_url=''):
    parsed = urlsplit(str(base_url or '').strip().rstrip('/'))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise RchCliError('Use an HTTP(S) server root such as https://host:8085')
    try:
        http_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError as exc:
        raise RchCliError('Invalid HTTP port') from exc
    http_root = urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
    if websocket_url:
        ws = urlsplit(websocket_url)
        if ws.scheme not in ('ws', 'wss') or not ws.hostname or ws.username or ws.fragment:
            raise RchCliError('WebSocket override must be a ws:// or wss:// URL')
        if parsed.scheme == 'https' and ws.scheme != 'wss':
            raise RchCliError('HTTPS requires an encrypted wss:// event connection')
        return http_root, websocket_url
    if http_port >= 65535:
        raise RchCliError('HTTP port is too high to derive its WebSocket port')
    hostname = parsed.hostname
    if ':' in hostname:
        hostname = '[' + hostname + ']'
    ws_host = f'{hostname}:{http_port + 1}'
    return http_root, urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', ws_host, '/ws/events', '', ''))


class NoCredentialRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None  # Never forward the admin bearer token to another URL.


class RchApi:
    def __init__(self, root, token, timeout=12):
        self.root = root.rstrip('/')
        self.token = token
        self.timeout = timeout
        self.opener = build_opener(NoCredentialRedirects())

    def request(self, method, path, payload=None, extra_headers=None):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        headers.update(extra_headers or {})
        # Only the exact RCH root is accepted by endpoint_urls; paths stay local.
        request = Request(self.root + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            try:
                result = json.loads(exc.read().decode('utf-8'))
                message = result.get('message') or exc.reason
            except (ValueError, AttributeError):
                message = exc.reason
            raise RchCliError(f'HTTP {exc.code}: {message}') from exc
        except (URLError, OSError, ValueError) as exc:
            raise RchCliError(f'HTTP request failed: {exc}') from exc
        if not isinstance(result, dict) or result.get('code') != 0:
            message = result.get('message') if isinstance(result, dict) else 'Invalid API response'
            raise RchCliError(str(message or 'API error'))
        return result.get('data')

    def connections(self):
        return self.request('GET', '/api/connections') or []

    def submit(self, client_id, command, tab_id):
        # Same X-Tab-Id as the WS subscription, so the Server routes output here.
        path = '/api/connections/' + quote(client_id, safe='') + '/command'
        result = self.request('POST', path, {'command': command}, {
            'X-Tab-Id': tab_id, 'X-RCH-Command-Source': 'rch_cli',
        })
        if not isinstance(result, dict) or not result.get('task_id'):
            raise RchCliError('Server did not return a task_id')
        return result

    def command_candidates(self, client_id):
        path = '/api/connections/' + quote(client_id, safe='') + '/command-candidates'
        data = self.request('GET', path)
        return data if isinstance(data, list) else []

    def completions(self, client_id, raw_input, cursor_position=None):
        path = '/api/connections/' + quote(client_id, safe='') + '/command-completions'
        data = self.request('POST', path, {
            'raw_input': raw_input,
            'cursor_position': len(raw_input) if cursor_position is None else cursor_position,
            'max_results': 30,
        })
        return data.get('items', []) if isinstance(data, dict) else []

    def task(self, client_id):
        return self.request('GET', '/api/connections/' + quote(client_id, safe='') + '/task')

    def history_entry(self, machine_id, entry_id):
        return self.request('GET', '/api/machines/' + quote(machine_id, safe='') + '/command-history/full/' + quote(entry_id, safe=''))

    def cancel(self, task_id):
        return self.request('POST', '/api/tasks/' + quote(task_id, safe='') + '/cancel', {})

    def pending_interactions(self, tab_id):
        return self.request('GET', '/api/interactions/pending?tab_id=' + quote(tab_id, safe='')) or {}

    def answer_interaction(self, interaction_id, approved, value=None):
        return self.request('POST', '/api/interactions/' + quote(interaction_id, safe='') + '/answer',
                            {'approved': bool(approved), 'value': value})


class EventReceiver:
    """Background WebSocket reader; the foreground thread owns console output."""

    def __init__(self, url, token, tab_id):
        separator = '&' if '?' in url else '?'
        self.url = url + separator + 'tab_id=' + quote(tab_id, safe='')
        self.token = token
        self.events = queue.Queue(maxsize=4096)
        self.ready = threading.Event()
        self.stop_requested = threading.Event()
        self.thread = None
        self.socket = None
        self.last_error = ''

    def _offer(self, item):
        try:
            self.events.put_nowait(item)
        except queue.Full:
            # History reconciliation takes over if the reader outruns the terminal.
            while True:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    break
            self.events.put_nowait({'event': '_overflow'})

    def start(self, timeout=10):
        try:
            from websockets.sync.client import connect  # noqa: F401
        except ImportError as exc:
            raise RchCliError('Install websockets>=14 in this Python environment') from exc
        self.thread = threading.Thread(target=self._run, name='RCH-CLI-events', daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout):
            error = self.last_error
            self.close()
            raise RchCliError('WebSocket did not connect' + (': ' + error if error else ''))

    def _run(self):
        try:
            from websockets.sync.client import connect
        except ImportError:
            self.last_error = 'Install websockets>=14 in this Python environment'
            return
        delay = 1
        while not self.stop_requested.is_set():
            was_ready = False
            try:
                with connect(self.url, additional_headers={'Authorization': 'Bearer ' + self.token},
                             open_timeout=8, close_timeout=2, max_size=16 * 1024 * 1024) as ws:
                    self.socket = ws
                    was_ready = True
                    self.ready.set()
                    self._offer({'event': '_connected'})
                    delay = 1
                    for raw in ws:
                        if self.stop_requested.is_set():
                            break
                        if not isinstance(raw, str):
                            continue
                        try:
                            item = json.loads(raw)
                            if isinstance(item, dict):
                                self._offer(item)
                        except ValueError:
                            continue
            except Exception as exc:
                if not self.stop_requested.is_set():
                    self.last_error = f'{type(exc).__name__}: {exc}'
            finally:
                self.socket = None
                self.ready.clear()
                if was_ready and not self.stop_requested.is_set():
                    self._offer({'event': '_disconnected'})
            if self.stop_requested.wait(delay):
                break
            delay = min(delay * 2, 8)

    def close(self):
        self.stop_requested.set()
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=3)


class RemoteConsole:
    # ANSI codes match the local Server Console's status=0 red/error convention.
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    def __init__(self, api, receiver, tab_id, output=None, reader=None, color=None, ws_url=''):
        self.api = api
        self.receiver = receiver
        self.tab_id = tab_id
        self.ws_url = ws_url
        self.output = output or sys.stdout
        self.reader = reader or input
        self.selected = None
        self.last_was_newline = True
        mode = (color or os.environ.get('RCH_COLOR', 'auto')).lower()
        if mode not in ('auto', 'always', 'never'):
            raise RchCliError('RCH_COLOR must be auto, always or never')
        self.ios_console = None
        if mode != 'never' and sys.platform == 'ios' and self.output is sys.stdout:
            try:
                import console  # Pythonista's native text color API.
                self.ios_console = console
            except ImportError:
                pass
        if self.ios_console is not None:
            self.color_backend = 'pythonista'
        elif sys.platform != 'ios' and (mode == 'always' or (mode == 'auto' and getattr(self.output, 'isatty', lambda: False)())):
            self.color_backend = 'ansi'
        else:
            self.color_backend = 'none'
        self.color = self.color_backend != 'none'
        self.unfinished_cancel = None
        self.completion_draft = None
        self._readline = None

    def write(self, message, color=None):
        # Pythonista's console rejects NUL in text; show it visibly instead.
        raw = str(message).replace('\x00', '\\0')
        if color and self.color_backend == 'pythonista':
            rgb = {
                self.BLUE: (0.35, 0.55, 1.0), self.CYAN: (0.0, 0.75, 0.9),
                self.GREEN: (0.1, 0.75, 0.25), self.YELLOW: (0.95, 0.68, 0.15),
                self.RED: (1.0, 0.2, 0.2),
            }.get(color)
            if rgb:
                self.ios_console.set_color(*rgb)
            try:
                self.output.write(raw)
                self.output.flush()  # Flush while Pythonista's native color is active.
            finally:
                if rgb:
                    self.ios_console.set_color()
        elif color and self.color_backend == 'ansi':
            self.output.write(self.style(raw, color))
        else:
            self.output.write(raw)
        self.output.flush()
        self.last_was_newline = raw.endswith('\n')

    def read_console_input(self, prompt, *, secret=False):
        """Read text without letting a NUL from a console backend kill the REPL."""
        try:
            value = getpass.getpass(prompt) if secret else self.reader(prompt)
        except ValueError as exc:
            if 'embedded null character' not in str(exc).lower():
                raise
            raise RchCliError('Invalid console input (NUL character); re-enter the text') from exc
        if isinstance(value, str) and '\x00' in value:
            raise RchCliError('Invalid console input (NUL character); re-enter the text')
        return value

    def style(self, text, color):
        raw = str(text)
        if self.color_backend != 'ansi':
            return raw
        if raw.endswith('\n'):
            return color + raw[:-1] + self.RESET + '\n'
        return color + raw + self.RESET

    def result_record(self, message, status=1):
        """Print one command output record, preserving embedded line breaks.

        The Client's stream reader removes trailing newlines before sending a
        record. Treat each record as a line, without doubling existing breaks.
        """
        text = str(message or '')
        if text:
            rendered = text if text.endswith(('\n', '\r')) else text + '\n'
            self.write(rendered, color=self.RED if status == 0 else None)

    def line(self, message='', color=None):
        if not self.last_was_newline:
            self.write('\n')
        self.write(str(message) + '\n', color=color)

    def active_connections(self):
        items = self.api.connections()
        if not isinstance(items, list):
            raise RchCliError('Invalid connections payload')
        return [item for item in items if isinstance(item, dict) and item.get('connection_state') == 'online']

    @staticmethod
    def display_name(item):
        return str(item.get('machine_alias') or item.get('hostname') or item.get('client_id') or '?')

    def list_connections(self):
        connections = self.active_connections()
        if not connections:
            self.line('No active sessions')
            return
        for index, item in enumerate(connections):
            self.line(f'{index:>3}  {self.display_name(item):<24} {item.get("os_alias") or "?":<8} '
                      f'{item.get("integrity") or "-":<10} {item.get("client_id") or ""}')

    def status(self):
        connections = self.active_connections()
        self.line(f'Online: {len(connections)}')
        if connections:
            latest = max(connections, key=lambda x: str(x.get('connected_at') or ''))
            self.line('Latest: ' + self.display_name(latest) + ' [' + str(latest.get('client_id') or '') + ']')

    def select(self, selector):
        connections = self.active_connections()
        if not connections:
            raise RchCliError('No active session available')
        if selector in ('q', 'last'):
            selected = max(connections, key=lambda x: str(x.get('connected_at') or ''))
        elif selector.isdecimal():
            index = int(selector)
            if index >= len(connections):
                raise RchCliError('Not a valid selection')
            selected = connections[index]
        else:
            selected = next((item for item in connections if item.get('client_id') == selector), None)
            if selected is None:
                raise RchCliError('Not a valid selection')
        self.selected = selected
        self.line('Opened ' + self.display_name(selected) + ' [' + selected['client_id'] + ']')

    def finish_line(self, status):
        name = str(status or 'completed').capitalize()
        color = self.GREEN if name == 'Success' else self.YELLOW if name in ('Cancelled', 'Cancelling') else self.RED
        self.line('[' + name + ']', color=color)

    def _recover(self, client_id, machine_id, entry_id, seen, *, print_result=True):
        if not entry_id or not machine_id:
            return None
        try:
            entry = self.api.history_entry(machine_id, entry_id)
        except RchCliError:
            return None
        if not isinstance(entry, dict) or entry.get('client_id') != client_id or not entry.get('finished_at'):
            return None
        if print_result:
            records = (entry.get('result') or {}).get('output_records') or []
            for record in records[seen:]:
                self.result_record(record.get('text'), record.get('status', 1))
            if (entry.get('result') or {}).get('truncated'):
                self.line('[History output truncated; earlier live output may be incomplete]')
            self.finish_line(entry.get('status') or 'completed')
        return 0 if entry.get('status') == 'success' else (130 if entry.get('status') == 'cancelled' else 1)

    def _check_completed(self, client_id, machine_id, task_id, entry_id, seen):
        try:
            snapshot = self.api.task(client_id)
        except RchCliError:
            snapshot = None
        if isinstance(snapshot, dict) and snapshot.get('task_id') == task_id and snapshot.get('state') in ('Running', 'Cancelling'):
            return None
        # A command with no foreground guard may still be running when the
        # snapshot is Idle. Only a finished, exact History entry confirms it.
        return self._recover(client_id, machine_id, entry_id, seen)

    def completion_candidates(self, raw_input):
        text = str(raw_input or '')
        if not self.selected:
            commands = ('help', 'list', 'ls', 'l', 'status', 'st', 'last', 'q',
                        'select ', 'use ', 's ', 'open ', 'clear', 'cls', 'exit', 'quit')
            return [{'insert_text': item, 'title': item} for item in commands
                    if item.startswith(text.lower())]

        client_id = self.selected['client_id']
        query = text.strip().lower()
        catalog = self.api.command_candidates(client_id)
        result = []
        seen = set()

        def add(candidate):
            value = str(candidate.get('insert_text') or candidate.get('name') or '').strip()
            if value and value.lower().startswith(query) and value.lower() not in seen:
                seen.add(value.lower())
                result.append({**candidate, 'insert_text': value,
                               'title': str(candidate.get('title') or value),
                               'description': str(candidate.get('description') or candidate.get('help') or '')})

        # Like the Web command bar: first-token suggestions come from the
        # command catalog, not the context-specific command-completions API.
        for item in catalog:
            if isinstance(item, dict):
                add(item)
        if ' ' in text or text.lstrip().startswith('!'):
            for item in self.api.completions(client_id, text):
                if isinstance(item, dict):
                    add(item)
        return result[:50]

    @staticmethod
    def _completion_text(item):
        """Use the Server's full insert_text, with a directory separator for browsing."""
        value = str(item.get('insert_text') or '')
        metadata = item.get('metadata') or {}
        is_dir = (item.get('kind') == 'directory'
                  or (isinstance(metadata, dict) and metadata.get('isDir') is True))
        if is_dir and value and not value.endswith(('/', '\\')):
            path = value.rsplit(' ', 1)[-1]
            value += '\\' if '\\' in path and '/' not in path else '/'
        return value

    def show_completions(self, raw_input):
        items = self.completion_candidates(raw_input)
        if not items:
            self.line('No completions' if self.selected else 'Select a Client first to complete remote commands')
            return
        for index, item in enumerate(items, 1):
            full = self._completion_text(item)
            # A filesystem completion already includes its command prefix;
            # suppress that repeated prefix only in the *display*.
            label = full
            if ' ' in raw_input:
                prefix = raw_input.split(' ', 1)[0] + ' '
                if full.startswith(prefix):
                    label = full[len(prefix):]
            description = str(item.get('description') or item.get('help') or '')
            if item.get('kind') == 'directory':
                description = 'directory'
            elif item.get('kind') == 'file':
                description = 'file'
            self.line(f'  {index:>2}. {label}' + (f'  — {description}' if description else ''))
        try:
            choice = self.read_console_input('Choose number (Enter cancels): ').strip()
        except (KeyboardInterrupt, EOFError):
            self.line('^C')
            return
        if not choice:
            return
        if not choice.isdecimal() or not 1 <= int(choice) <= len(items):
            self.line('Invalid selection; draft unchanged', color=self.YELLOW)
            return
        completed = self._completion_text(items[int(choice) - 1])
        if '\x00' in completed:
            self.line('Invalid completion (NUL character)', color=self.RED)
            return
        self.completion_draft = completed
        self.line('Selected: ' + self.completion_draft)
        self.line('Next input appends to this command; Enter runs it, :complete browses further, :clear discards.')

    def _install_readline_completion(self):
        # Pythonista has no readline; system terminals may use GNU or macOS libedit.
        if self.reader is not input:
            return None
        try:
            import readline
            old_completer = readline.get_completer()
            old_delims = readline.get_completer_delims()
        except (ImportError, AttributeError):
            return None
        cache = []

        def complete(text, state):
            if state == 0:
                cache.clear()
                raw = readline.get_line_buffer()
                end = readline.get_endidx()
                if end != len(raw):
                    return None
                # Server insert_text contains the whole command. Readline/libedit
                # replaces only its active span, which may begin after `download `.
                # Return that span's replacement, not the command prefix twice.
                try:
                    begin = readline.get_begidx()
                except AttributeError:
                    begin = 0
                if not isinstance(begin, int) or begin < 0 or begin > end:
                    begin = 0
                if text and raw[begin:end] != text and raw.endswith(text):
                    # Some libedit builds report different word boundaries.
                    begin = end - len(text)
                elif not text and begin == 0 and raw.endswith((' ', '\t')):
                    begin = end  # Empty active word after an argument separator.
                prefix = raw[:begin]
                try:
                    for item in self.completion_candidates(raw):
                        full = self._completion_text(item)
                        if full.startswith(prefix):
                            cache.append(full[begin:])
                except RchCliError:
                    return None
            return cache[state] if state < len(cache) else None

        readline.set_completer_delims('')
        readline.set_completer(complete)
        backend = str(getattr(readline, 'backend', '') or '').lower()
        if backend in ('editline', 'libedit') or (not backend and 'libedit' in (readline.__doc__ or '').lower()):
            readline.parse_and_bind('bind ^I rl_complete')
        else:
            readline.parse_and_bind('tab: complete')
        self._readline = readline

        def restore():
            self._readline = None
            readline.set_completer(old_completer)
            readline.set_completer_delims(old_delims)
        return restore

    def _repl_prompt(self, name, color):
        label = name + '> '
        if self.color_backend == 'ansi' and self._readline is not None:
            # Readline must not count color escapes as printable prompt columns.
            return '\001' + color + '\002' + label + '\001' + self.RESET + '\002'
        return self.style(label, color)

    def _read_repl_input(self, prompt, draft):
        if not draft or self._readline is None:
            return self.read_console_input(prompt), False
        readline = self._readline

        def prefill():
            readline.insert_text(draft)

        # Keep the draft in the editable input buffer, not in the prompt:
        # Up/Down and cursor movement must replace or edit the actual line.
        readline.set_startup_hook(prefill)
        try:
            return self.read_console_input(prompt), True
        finally:
            readline.set_startup_hook(None)

    def _render_preview(self, preview):
        if not isinstance(preview, dict):
            return
        for item in preview.get('summary') or []:
            self.line(f"  {item.get('label', '')}: {item.get('value', '')}")
        columns = preview.get('columns') or []
        rows = preview.get('rows') or []
        if columns and rows:
            names = [str(c.get('key') or '') for c in columns]
            self.line('  ' + ' | '.join(str(c.get('label') or c.get('key') or '')[:25] for c in columns))
            for row in rows[:15]:
                self.line('  ' + ' | '.join(str(row.get(key) or '')[:32] for key in names))
            if len(rows) > 15:
                self.line(f'  ... {len(rows) - 15} more rows')
        for item in preview.get('details') or []:
            self.line(f"  {item.get('title', '')}: {item.get('content', '')}")
        for item in preview.get('row_details') or []:
            self.line(f"  {item.get('row_id', '')}: {item.get('content', '')}")
        for item in preview.get('switches') or []:
            self.line(f"  {item.get('label') or item.get('key')}: {item.get('default', False)} (default)")
        if preview.get('notice'):
            self.line(str(preview['notice']))
        if 'row_ids' in preview:
            self.line('Approval selects all listed rows.')

    def _handle_interaction(self, item):
        try:
            return self._answer_interaction_prompt(item)
        except RchCliError as exc:
            self.line('[Interaction input invalid: ' + str(exc) + '; retry when prompted]', color=self.RED)
            return False

    def _answer_interaction_prompt(self, item):
        kind = str(item.get('kind') or '')
        interaction_id = str(item.get('interaction_id') or '')
        self.line(str(item.get('title') or 'Interaction') + ': ' + str(item.get('message') or ''))
        if kind == 'preview':
            preview = item.get('preview') or {}
            self._render_preview(preview)
            approved = self.read_console_input('Approve preview? [y/N] ').strip().lower() in ('y', 'yes')
            value = None
            if approved and (preview.get('switches') or 'row_ids' in preview):
                value = {str(s['key']): bool(s.get('default', False)) for s in preview.get('switches') or []}
                if 'row_ids' in preview:
                    value['selected_rows'] = list(preview['row_ids'])
        elif kind == 'confirm':
            approved = self.read_console_input('Approve? [y/N] ').strip().lower() in ('y', 'yes')
            value = None
        elif kind == 'select':
            choices = item.get('options') or []
            for idx, value in enumerate(choices, start=1):
                self.line(f'{idx}: {value}')
            raw = self.read_console_input('Select number (blank rejects): ').strip()
            approved = raw.isdecimal() and 1 <= int(raw) <= len(choices)
            value = choices[int(raw) - 1] if approved else None
        elif kind in ('input', 'secret'):
            value = self.read_console_input('Value: ', secret=(kind == 'secret'))
            approved = True
        else:
            self.line('[Unsupported interaction; not approved]')
            return
        try:
            self.api.answer_interaction(interaction_id, approved, value)
        except RchCliError as exc:
            self.line('[Interaction answer rejected: ' + str(exc) + ']', color=self.RED)
            return False
        return True

    def execute(self, command):
        client = self.selected
        if self.unfinished_cancel and self.unfinished_cancel[0] == client['client_id']:
            try:
                snapshot = self.api.task(client['client_id'])
            except RchCliError as exc:
                raise RchCliError('Unable to verify previous cancelled command: ' + str(exc)) from exc
            if isinstance(snapshot, dict) and snapshot.get('task_id') == self.unfinished_cancel[1] and snapshot.get('state') in ('Running', 'Cancelling'):
                raise RchCliError('Previous command is still running/cancelling; wait before submitting another')
            self.unfinished_cancel = None
        client_id = client['client_id']
        machine_id = str(client.get('machine_id') or '')
        if not self.receiver.ready.wait(8):
            raise RchCliError('Event WebSocket is disconnected; command not submitted')
        # Flush older broadcast and task events before submitting a new task.
        while True:
            try:
                self.receiver.events.get_nowait()
            except queue.Empty:
                break
        response = self.api.submit(client_id, command, self.tab_id)
        task_id = str(response['task_id'])
        history_id = str(response.get('history_entry_id') or '')
        seen = 0
        degraded = False
        last_check = time.monotonic()
        has_activity = False
        handled_interactions = set()
        last_interaction_check = time.monotonic() - 3
        cancelling = False
        cancel_deadline = None
        while True:
            try:
                try:
                    event = self.receiver.events.get(timeout=1)
                except queue.Empty:
                    event = {}
                event_type = event.get('event')
                payload = event.get('data') or {}
                if event_type in ('_disconnected', '_overflow'):
                    degraded = True
                    self.line('[Event stream interrupted; recovering remaining output from History]')
                elif event_type == '_connected':
                    # After a reconnect, the completion may already be persisted.
                    if degraded:
                        result = self._check_completed(client_id, machine_id, task_id, history_id, seen)
                        if result is not None:
                            return result
                        try:
                            pending = self.api.pending_interactions(self.tab_id)
                            for item in pending.get('items', []):
                                if item.get('task_id') == task_id and item.get('interaction_id') not in handled_interactions:
                                    if self._handle_interaction(item):
                                        handled_interactions.add(item.get('interaction_id'))
                        except RchCliError:
                            pass
                elif event_type == 'interaction_requested' and payload.get('task_id') == task_id:
                    if payload.get('interaction_id') not in handled_interactions:
                        if self._handle_interaction(payload):
                            handled_interactions.add(payload.get('interaction_id'))
                elif event_type == 'command_result' and payload.get('task_id') == task_id:
                    has_activity = True
                    if not degraded:
                        self.result_record(payload.get('text'), payload.get('status', 1))
                        seen += 1
                elif event_type == 'command_complete' and payload.get('task_id') == task_id:
                    if degraded:
                        recovered = self._recover(client_id, machine_id, history_id, seen)
                        if recovered is not None:
                            return recovered
                        self.line('[Completed; full output could not be restored from History]')
                    else:
                        self.finish_line(payload.get('status') or ('success' if payload.get('success') else 'error'))
                    self.unfinished_cancel = None
                    return 0 if payload.get('success') else (130 if payload.get('cancelled') else 1)
                if time.monotonic() - last_interaction_check >= 3:
                    last_interaction_check = time.monotonic()
                    try:
                        pending = self.api.pending_interactions(self.tab_id)
                        for item in pending.get('items', []):
                            if item.get('task_id') == task_id and item.get('interaction_id') not in handled_interactions:
                                if self._handle_interaction(item):
                                    handled_interactions.add(item.get('interaction_id'))
                    except RchCliError:
                        pass  # Event-driven delivery remains the primary path.
                if cancelling and time.monotonic() >= cancel_deadline:
                    self.unfinished_cancel = (client_id, task_id)
                    self.line('[Cancel still unconfirmed; task may still be running]', color=self.YELLOW)
                    return 130
                # The server may finish a very short command before its HTTP POST returns,
                # or a notification can be lost during subscribe/reconnect. Reconcile at
                # most once per 3s initially, then once per 15s while waiting for output.
                interval = 15 if has_activity else 3
                if time.monotonic() - last_check >= interval:
                    last_check = time.monotonic()
                    result = self._check_completed(client_id, machine_id, task_id, history_id, seen)
                    if result is not None:
                        return result
            except KeyboardInterrupt:
                self.line('^C')
                if cancelling:
                    self.unfinished_cancel = (client_id, task_id)
                    self.line('[Still cancelling; final state unconfirmed]', color=self.YELLOW)
                    return 130
                try:
                    self.api.cancel(task_id)
                    cancelling = True
                    cancel_deadline = time.monotonic() + 12
                    self.line('[Cancelling; waiting for task completion]', color=self.YELLOW)
                except RchCliError as exc:
                    self.line('[Cancel rejected: ' + str(exc) + '; waiting for task completion]', color=self.RED)

    def print_root_help(self):
        self.line('')
        self.line('RCH Server Console', color=self.CYAN)
        self.line('  Command                 Description')
        self.line('  ' + '─' * 57)
        for command, description in (
            ('help, h, ?', 'Show this help'),
            ('list, ls, l', 'List online Clients'),
            ('status, st', 'Connection summary'),
            ('q, last', 'Open latest online Client'),
            ('<index>', 'Open Client by list index'),
            ('select/use/s/open <id>', 'Open by index or Client ID'),
            ('clear, cls', 'Clear screen'),
            ('exit, quit', 'Close this CLI'),
        ):
            self.line(f'  {command:<23} {description}')
        self.line('')
        self.line('Client session', color=self.CYAN)
        self.line('  bg, exit                Return to server>')
        self.line('  :complete <input>       Choose a completion; :complete again continues draft')
        self.line('  :clear                  Discard a completion draft')
        self.line('  :pty [shell]           Remote PTY (macOS/Linux; Ctrl+] then q closes)')
        self.line('  Tab                     Complete input (when readline is available)')
        self.line('  Ctrl+C                  Request task cancellation, wait for final state')
        self.line('  Other commands          Executed by RCH Server')
        self.line('')

    def repl(self):
        self.line('Connected to RCH Server. Type help for console commands.')
        restore = self._install_readline_completion()
        try:
            while True:
                name = self.display_name(self.selected) if self.selected else 'server'
                prompt_color = self.GREEN if self.selected else self.CYAN
                draft = self.completion_draft or ''
                if self.color_backend == 'pythonista':
                    self.write(name + '> ', color=prompt_color)
                    if draft:
                        self.write(draft)
                    prompt = ''
                else:
                    prompt = self._repl_prompt(name, prompt_color)
                    if self._readline is None:
                        prompt += draft
                try:
                    raw, editable_draft = self._read_repl_input(prompt, draft)
                except RchCliError as exc:
                    self.line('Error: ' + str(exc), color=self.RED)
                    continue
                except EOFError:
                    self.line()
                    break
                except KeyboardInterrupt:
                    self.line('^C')
                    continue
                raw_text = str(raw or '')
                local_command = raw_text.strip()
                # With readline the draft was inserted into the editable buffer.
                # Typing :complete or :clear after it keeps the picker shortcuts.
                if editable_draft and draft and local_command in (draft + ':complete', draft + ':clear'):
                    local_command = local_command[len(draft):]
                    raw_text = local_command
                try:
                    if local_command == ':clear':
                        self.completion_draft = None
                        continue
                    if local_command == ':complete' or local_command.startswith(':complete '):
                        query = raw_text.strip('\n\r').lstrip()[len(':complete'):].lstrip()
                        self.show_completions(query or draft)
                        continue
                    command = (draft + raw_text).strip() if draft and not editable_draft else local_command
                    if not command:
                        continue
                    if '\x00' in command:
                        raise RchCliError('Invalid command (NUL character); re-enter the text')
                    self.completion_draft = None
                    if self.selected:
                        if command == ':pty' or command.startswith(':pty '):
                            if os.name != 'posix' or sys.platform == 'ios':
                                raise RchCliError('PTY requires a macOS/Linux system terminal')
                            from rchcli_pty import RchPtyError, parse_pty_options, run_pty
                            try:
                                shell = parse_pty_options(command[5:].strip())
                                run_pty(self.api, self.selected['client_id'], self.ws_url,
                                        shell=shell)
                            except RchPtyError as exc:
                                self.line('PTY: ' + str(exc), color=self.RED)
                            else:
                                self.line('[PTY closed]')
                            continue
                        if command in ('bg', 'exit'):
                            self.selected = None
                            continue
                        self.execute(command)
                        continue
                    parts = command.split()
                    head = parts[0].lower()
                    if head in ('exit', 'quit'):
                        break
                    if head in ('help', 'h', '?'):
                        self.print_root_help()
                    elif head in ('list', 'ls', 'l') and len(parts) == 1:
                        self.list_connections()
                    elif head in ('status', 'st') and len(parts) == 1:
                        self.status()
                    elif head in ('last', 'q') and len(parts) == 1:
                        self.select('last')
                    elif head in ('select', 'use', 's', 'open') and len(parts) == 2:
                        self.select(parts[1])
                    elif len(parts) == 1 and head.isdecimal():
                        self.select(head)
                    elif head in ('clear', 'cls') and len(parts) == 1:
                        if self.ios_console is not None:
                            self.ios_console.clear()
                        elif self.color_backend == 'ansi':
                            self.write('\033[2J\033[H')
                        else:
                            self.line('\n' * 30)
                    else:
                        self.line('Unknown console command; type help (Server builtins require selecting a Client)', color=self.RED)
                except RchCliError as exc:
                    self.line('Error: ' + str(exc), color=self.RED)
        finally:
            if restore:
                restore()


def main(argv=None):
    parser = argparse.ArgumentParser(description='RCH remote operator console')
    parser.add_argument('--url', default=os.environ.get('RCH_SERVER_URL', ''),
                        help='RCH HTTP URL, e.g. http://host:8085 (or RCH_SERVER_URL)')
    parser.add_argument('--ws-url', default=os.environ.get('RCH_WS_URL', ''),
                        help='Override WS URL for a reverse proxy (or RCH_WS_URL)')
    parser.add_argument('--timeout', type=float, default=12, help='HTTP request timeout in seconds')
    parser.add_argument('--color', choices=['auto', 'always', 'never'], default=os.environ.get('RCH_COLOR', 'auto'),
                        help='ANSI color mode (or RCH_COLOR)')
    args = parser.parse_args(argv)
    try:
        if not args.url:
            if not sys.stdin.isatty():
                raise RchCliError('Specify --url or RCH_SERVER_URL')
            args.url = input('RCH Server HTTP URL: ').strip()
        if not args.url:
            raise RchCliError('Server URL is required')
        if not (0 < args.timeout <= 300):
            raise RchCliError('--timeout must be between 0 and 300 seconds')
        http_url, ws_url = endpoint_urls(args.url, args.ws_url)
        token = os.environ.get('RCH_API_TOKEN', '').strip()
        if not token:
            if not sys.stdin.isatty():
                raise RchCliError('Set RCH_API_TOKEN for non-interactive use')
            token = getpass.getpass('RCH admin API token: ').strip()
        if not token:
            raise RchCliError('Administrator API token is required')
        api = RchApi(http_url, token, timeout=args.timeout)
        api.connections()  # Detect auth and HTTP reachability before opening WS.
        tab_id = 'rchcli-' + uuid.uuid4().hex
        receiver = EventReceiver(ws_url, token, tab_id)
        try:
            receiver.start()
            # /ws/events currently has no explicit subscribed ACK. Allow its
            # server-side subscriber registration to complete before requests.
            time.sleep(0.1)
            RemoteConsole(api, receiver, tab_id, color=args.color, ws_url=ws_url).repl()
        finally:
            receiver.close()
        return 0
    except (RchCliError, KeyboardInterrupt) as exc:
        print(('Error: ' + str(exc)) if str(exc) else 'Interrupted', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
