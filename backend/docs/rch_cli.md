# RCH Remote CLI

`rchcli.py` is a standalone Python operator console that connects to an existing RCH Server. It runs on Windows, macOS and Linux with Python **3.9+** and the `websockets>=14` package. It does not import RCH Server or Agent modules and does not start a listening service.

## Install and connect

Install the one runtime dependency with the same Python interpreter used to run the CLI:

```bash
python3 -m pip install 'websockets>=14'
```

Set the administrator API Token from the Server Web account's **Authorization Info**. The token is used for both HTTP calls and the WebSocket connection. On macOS/Linux:

```bash
export RCH_API_TOKEN='your-admin-api-token'
python3 backend/rchcli.py --url http://YOUR_SERVER:8085
```

On Windows PowerShell:

```powershell
$env:RCH_API_TOKEN = 'your-admin-api-token'
python backend/rchcli.py --url http://YOUR_SERVER:8085
```

`RCH_SERVER_URL` can replace `--url`. When launched in an interactive terminal without a URL or Token, the script prompts for them (the Token input is hidden). The direct CLI does not save the Token. To avoid a shell-history credential leak, do not put the Token directly in a CLI argument.

The WebSocket endpoint is derived from the configured HTTP port: `http://host:9090` connects to `ws://host:9091/ws/events`. The same rule works for HTTPS/WSS. If HTTP and WebSocket are exposed through different reverse proxy addresses, provide `--ws-url wss://host/ws/events` (or `RCH_WS_URL`). The Server's HTTP and event endpoints must be reachable from this machine. Use HTTPS/WSS or a trusted VPN when accessing RCH remotely; HTTP/WS sends the administrative Token in cleartext on the network.

### Run from a Python editor without repeated prompts

Put `start_rchcli.py` beside the **current v1.49+** `rchcli.py`, and edit the three constants at the top of `start_rchcli.py` once: `RCH_HTTP_URL`, `RCH_ADMIN_TOKEN`, and optional `RCH_EVENTS_WS_URL`. Then simply run **`start_rchcli.py`** in Pythonista or any normal Python environment. Neither URL nor Token is requested again. WebSocket still uses the HTTP port plus one unless overridden.

The launcher executes the neighboring `rchcli.py` by its actual file path instead of `import rchcli`, preventing older same-name Python modules from being loaded. It does not modify RCH Server or its command protocol.

**Security:** This quick-development configuration stores an admin Token in plaintext in the local launcher. Do not commit or share your configured copy. If a Token appears in a screenshot or terminal log, revoke it and create a new one. Keep using HTTPS/WSS or a trusted VPN when connecting from outside your network.

## Operator commands

```text
server> list
  0  MacBook-Air     mac     medium    <client_id>
  1  Win-PC          win     elevated  <client_id>
server> 0
Opened MacBook-Air [<client_id>]
MacBook-Air> whoami
flc
[Success]
MacBook-Air> bg
server> q
Opened Win-PC [<client_id>]
Win-PC> help
... output interpreted by RCH Server ...
Win-PC> exit
server> quit
```

At `server>`:

| Command | Action |
| --- | --- |
| `list`, `ls`, `l` | Show online Client instances |
| `status`, `st` | Show online count and latest connection |
| `q`, `last` | Open the most recently connected online instance |
| `0`, `select 0`, `s 0`, `use 0`, `open 0` | Select by list index |
| `open <client_id>` | Select by exact online Client ID |
| `clear`, `cls` | Clear this terminal display |
| `help`, `h`, `?` | Show the formatted local navigation help |
| `:complete <input>` | Numbered completion picker; choose an item to build a command draft |
| `:complete` | Complete the current draft again (browse deeper into a directory) |
| `:clear` | Discard the current draft without executing anything |
| `exit`, `quit` | Exit this CLI only; the RCH Server remains running |

At the selected Client prompt, `bg` or `exit` returns to `server>`. **All other commands are sent as raw text to the Server's existing Web command endpoint**. The Server alone interprets Server Builtins, Aliases, ACMD, Scripts and Client commands. This operator console does not re-implement their parsers. A command executes serially in the foreground and streams its output into the CLI. In terminals with Python `readline`, press **Tab** to apply command candidates. The local `:complete <input>` command works with simple `input()` environments (including mobile script consoles). It shows numbered candidates and lets you choose one, **without executing it**. The selected full command is retained as a draft visible in the next prompt. Type a suffix to append it or press Enter to execute the complete draft. To browse further into a selected directory, type `:complete` again; directory candidates include a trailing path separator. Type `:clear` to discard a draft. Press Enter at the candidate-number prompt to leave it unchanged. The displayed candidate names omit repeated leading command words, but the Server's `insert_text` remains intact when submitted. At `server>`, completion covers local navigation commands; select a Client first to complete `getinfo`, `acmd`, and other remote commands. In a Client session, the CLI uses the same two endpoints as the Web command bar: `GET /api/connections/{client_id}/command-candidates` for command names and `POST /api/connections/{client_id}/command-completions` for contextual subcommands, parameters and paths. The Server owns both catalogs.

Pythonista does not expose standard `readline`/`curses` to scripts, so its built-in editor/console Tab suggestion is not a programmable `readline` completer for `input()`. Use the numbered `:complete` flow there. Likewise, iOS app stop controls and keyboard interrupts do not promise the same semantics as terminal SIGINT; forcibly stopping the script may leave a remote task running. The CLI cannot guarantee remote cancellation if the host terminates it instead of delivering a catchable `KeyboardInterrupt`.

`Ctrl+C` during execution, in a host that delivers `KeyboardInterrupt` to this script, requests cancellation using the existing task API. The CLI continues to receive events and waits for the task's confirmed final status (`cancelled`, `success`, or `error`). After 12 seconds without confirmation, the CLI explicitly reports the unconfirmed state; before sending another command to the same Client it checks whether the earlier task is still active. Cancellation availability depends on the command policy.

Broker interactions (`confirm`, `input`, `secret`, `select`, `preview`) work through the existing tab-scoped interaction endpoints. `preview` displays summary, rows, details and notices as plain text, then asks **y/N**; previews with optional switches use their defined defaults, and approval of a selectable-row preview selects all offered rows. Use **n** to reject. Missed interaction events can be recovered from the pending-interactions endpoint during a command. A console that cannot hide secret input should not be used to enter sensitive values. The local Server console's filesystem commands (`cd`, `pwd`) and Server process `kill`/`exit` semantics are intentionally **not** mirrored as remote root-console commands; existing Server APIs have different responsibilities. One-shot `exec` mode is reserved for a later version and can reuse the same HTTP submission / WebSocket result pipeline.

## Remote PTY on macOS and Linux

In a normal macOS Terminal/iTerm2 or Linux terminal, select an online Client and enter `:pty` to open its interactive remote shell. `:pty /bin/bash` selects a specific shell (the path must exist on the *remote* device). On a Unix target Agent, Bash and Zsh open as interactive login shells, loading login profiles such as `~/.zprofile` for PATH setup. This mode uses the existing Server PTY API and dedicated WebSocket channel; the target Unix Agent must include the PTY backend with login-shell and clean-EOF handling. It works with Unix or Windows target Agents, provided the target Agent already supports remote PTY.

```text
server> 0
MacBook-Air> :pty
$ vim README.md
# ...interactive full-screen Vim...
# Ctrl+] then q closes the PTY and returns to MacBook-Air>
```

For mobile terminal emulators that report more columns than their screen can display, use `:pty --cols 60` to cap the remote PTY width (or `:pty /bin/zsh --cols 60`). This also affects column-formatted commands such as `ls`; run `ls -1` to inspect exact full filenames. The cap applies during window resizing; smaller actual widths are still respected.

The local terminal enters Unix raw mode while the session is open, forwards keystrokes and control sequences unchanged, renders remote ANSI/VT output, and synchronizes terminal size changes. **Ctrl+C is sent to the remote process**; it does not invoke the ordinary RCH task-cancellation API in PTY mode. To leave the PTY, press **Ctrl+]**, then **q**. To send a literal Ctrl+] to Vim, press **Ctrl+]**, then **]**. `:pty` is a local CLI command, not a Server Builtin or an Agent command.

The CLI restores the local terminal attributes and normal display on exit, remote close, or connection error. PTY WebSocket disconnect closes the remote PTY session under the existing Server lifecycle: sessions cannot be detached and later reattached. The existing remote PTY Server implementation decodes Client output as UTF-8 per chunk, so an occasional Unicode replacement character is possible when a multibyte character is split between chunks.

This mode needs both local stdin and stdout connected to a real TTY; script consoles such as Pythonista and non-interactive pipes cannot supply the required raw keyboard/VT screen. Windows as the *operator's local system* is reserved for a separate implementation. The existing `websockets>=14` CLI dependency is sufficient.

## Protocol, streaming and recovery

The CLI calls `GET /api/connections` to locate online instances. For selected commands it establishes an authenticated `WS /ws/events?tab_id=...` subscription first, then submits the **unchanged** command text using `POST /api/connections/<client_id>/command` and `X-Tab-Id` with that same unique identifier, plus `X-RCH-Command-Source: rch_cli` to distinguish Activity History Source from Web Terminal. It associates streamed `command_result` and `command_complete` messages by `task_id`, including responses that arrive before the HTTP POST returns. Activity History for newly submitted CLI commands uses `rch_cli` when the Server has the matching source-routing support; normal Web Terminal commands remain `web_terminal`. Previously stored Activity records are retained unchanged. The CLI has only one outstanding foreground command per process. Each streamed output record is displayed on its own line unless it already contains a newline or carriage return; exact-History recovery uses the same display formatting. Output records carrying `status=0` are displayed in red, matching the local Server Console. The root and selected-Client prompts use distinct colors, as do final command statuses. System terminals use ANSI colors. Pythonista's output console uses its native `console.set_color()` API, so ANSI escape codes do not appear in the Pythonista transcript. Set `RCH_COLOR=always` or `RCH_COLOR=never` (alternatively `--color`) to control color output.

If the event socket disconnects, it automatically reconnects and uses the existing `GET /api/connections/<client_id>/task` and exact `GET /api/machines/<machine_id>/command-history/full/<history_entry_id>` APIs to reconcile completed tasks. While a stream is interrupted, the CLI suppresses later partial chunks and restores the remaining saved output from that exact History entry to avoid duplicate segments. History limits output to **64 KiB / 256 records per execution**. A command for which no execution history is stored cannot have dropped output reliably replayed without new Server support; the CLI does not guess the result from an unrelated entry.

`/ws/events` currently has no positive subscription ACK and does not replay missed events. The CLI allows its subscription to initialize before submitting and reconciles state after quiet periods/reconnections. If the output cannot be recovered, the running command can be interrupted with Ctrl+C. WS reconnection is event-driven; the CLI does not repeatedly query history when it is not executing a command.

## Local verification

From the project root:

```bash
python3 -m unittest -v backend/tests/test_rchcli_remote.py
```

On a running authorized RCH Server (with matching Server code installed and restarted): use `list`, select an online Client, run short `whoami` and a streaming command such as `shell_stream` with appropriate arguments, test `bg`, select another Client and verify `exit` leaves the Server running. Test `:complete acmd ` and Tab where available; run a preview-requiring command and approve or reject in the CLI; run a cancellable streaming command and check that Ctrl+C waits for the terminal status. Verify newly created CLI Activity has origin `rch_cli`, and Web Terminal Activity still has origin `web_terminal`; this requires the matching Server source-routing patch to be deployed and running. During an active stream, temporarily interrupt the CLI's WS network path and verify exact-History recovery. Validate remote access via HTTPS/WSS and a non-default Web port separately.
