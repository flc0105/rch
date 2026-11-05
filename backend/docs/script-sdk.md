# Script SDK API

## 基本用法

脚本中可以直接导入 SDK 模块：

```python
from client.runtime.sdk import artifact, command, context, keychains, scripts, workspace, xt
```

Client SDK 使用当前连接统一的 **Client Session Token** 调用允许的 Server API。无须在 `SCRIPT_METADATA` 声明权限或为单次 Script 获取临时凭证。客户端的 HTTP 方法/路径白名单统一在 [Client Session Token & Client HTTP API](client_session_api.md) 中维护。

## `context`

`context` 读取当前脚本运行上下文，不需要额外的 HTTP 授权声明。

```python
from client.runtime.sdk import context

print("client_id =", context.client_id())
print("command_id =", context.command_id())
print("hostname =", context.hostname())
print("machine_id =", context.machine_id())
print("arch =", context.arch())
print("script_name =", context.script_name())

print("os_type =", context.os_type())
print("os_alias =", context.os_alias())
print("os_ver =", context.os_ver())

print("system_paths =", context.system_paths())
```

常用 API：

| API | 返回 |
|---|---|
| `context.client_id()` | 当前 client id |
| `context.command_id()` | 当前 command id |
| `context.hostname()` | 当前主机名 |
| `context.machine_id()` | 当前 machine id |
| `context.arch()` | 当前 CPU 架构 |
| `context.script_name()` | 当前脚本名 |
| `context.os_type()` | OS 类型/显示名 |
| `context.os_alias()` | OS alias |
| `context.os_ver()` | OS 版本 |
| `context.system_paths()` | 当前 client 握手上报的系统路径 |
| `context.progress(message, status=1)` | 将脚本进度实时发到当前执行输出流（无运行上下文时打印） |

兼容 API：

```python
context.get_client_id()
context.get_command_id()
context.get_hostname()
context.get_machine_id()
context.get_os_type()
context.get_os_alias()
context.get_os_ver()
context.get_arch()
context.get_script_name()
context.get_system_paths()
context.get_script_context()
context.get_client_session_token()
```

## `command`

`command` 用于在当前 client 执行 shell 或调用已导出的 client command，不需要额外的 HTTP 授权声明。

```python
from client.runtime.sdk import command

result = command.run_shell("whoami")
print("returncode =", result.returncode)
print("stdout =", result.stdout)
print("stderr =", result.stderr)
print("ok =", result.ok)

proc = command.run_background("python app.py")
print("pid =", proc.pid)

stream_result = command.stream_shell("ping 127.0.0.1", timeout=5)
print("returncode =", stream_result.returncode)
```

常用 API：

| API | 说明 |
|---|---|
| `command.run_shell(command, wait=True, background=False, mode='', stream=False, timeout=None)` | 执行 shell 命令 |
| `command.run_background(command)` | 后台执行 shell 命令 |
| `command.stream_shell(command, timeout=None)` | 流式执行 shell 命令 |
| `command.run_client(name, *args, **kwargs)` | 调用当前 client 已导出的命令 |
| `command.<client_command>(*args, **kwargs)` | 动态调用 client command，例如 `command.screenshot()` |

返回对象：

```python
result.returncode
result.stdout
result.stderr
result.ok
result.text
```

## `artifact`

`artifact` 用于上传、查询、解析和下载 artifact。

```python
SCRIPT_METADATA = {
    "display_name": "Artifact Example",
    "params": [],
}

from client.runtime.sdk import artifact

saved = artifact.save("/tmp/a.txt", type="shared_files", category="script")
print("saved =", saved)

items = artifact.list(type="shared_files")
print("items =", items)

matched = artifact.find_by_file_name("a.txt", type="shared_files")
print("matched =", matched)

meta = artifact.get(saved["artifact_id"], type="shared_files")
print("meta =", meta)

path = artifact.download(saved["artifact_id"], type="shared_files", target_path="/tmp")
print("downloaded_path =", path)
```

常用 API：

| API | API access | 说明                |
|---|---|-------------------|
| `artifact.save(path, type='files', category='script', extra=None, timeout=None)` | 独立上传入口 | 上传本地文件            |
| `artifact.list(type='', machine_id='')` | Client Session Token | 查询 artifacts      |
| `artifact.get(ref, type='shared_files')` | Client Session Token | 解析 artifact 元数据   |
| `artifact.download(ref, type='shared_files', target_path='', timeout=None)` | `artifacts:list` + `artifacts:download` | 下载 artifact       |
| `artifact.find_by_file_name(file_name, type='', machine_id='', exact=True)` | Client Session Token | 按文件名查找 artifacts  |

支持的 `type`：

```python
"files"
"previews"
"shared_files"
"command_output"
```

## `scripts` — 复用 Script Library 脚本

Client 使用当前连接的 Session Token 读取 Script Library 源代码；此 SDK 调用不负责修改脚本。在当前 Client 的同一次脚本执行中同步运行子脚本，不提交第二条远程命令。

```python
SCRIPT_METADATA = {
    "name": "macos/backup/example",
    "platforms": ["macos"],
    "params": [],
}
from client.runtime.sdk import scripts, context

context.progress("Preparing bookmarks...")
result = scripts.run("common/browser/get_chromium_bookmarks", {"browser": "chrome"})
if result.ok:
    bookmarks = result.json()  # 解析子脚本 stdout 中的 JSON
    print("bookmarks", len(bookmarks))
else:
    print("failed", result.stderr)
```

| API | 作用 |
|---|---|
| `scripts.run(name, params=None, timeout=30)` | 同步执行当前 Server Script Library 的脚本，返回 `ScriptResult` |
| `ScriptResult.ok`, `.returncode` | 执行是否成功 / 退出状态 |
| `ScriptResult.stdout`, `.stderr`, `.text` | 子脚本输出；可直接保存到文件 |
| `ScriptResult.json()` | 解析 stdout 为 JSON，格式无效会抛异常 |

子脚本与调用方使用同一个 Client Session Token，不需要另外申请权限。子脚本在当前进程执行，适用于可信的 Script Library 代码；不要调用不可信的脚本。该调用捕获子脚本的 stdout/stderr；父脚本可通过 `context.progress()` 输出实时进度。

## `keychains`

`keychains` 用于创建和读取当前机器或 Server Shared Keychains。

```python
SCRIPT_METADATA = {
    "display_name": "Keychains Example",
    "params": [],
}

from client.runtime.sdk import keychains

keychains.create_secret("api_token", "token-value")
secret = keychains.get_secret("api_token")
print("secret =", secret.getvalue())

keychains.create_login("demo_login", "admin", "password")
login = keychains.get_login("demo_login")
print("username =", login.username)
print("password =", login.password.getvalue())

keychains.create_secret("shared_token", "shared-value", scope="shared")
shared_secret = keychains.get_secret("shared_token", scope="shared")
print("shared_secret =", shared_secret.getvalue())
```

常用 API：

| API | API access | 说明 |
|---|---|---|
| `keychains.create_secret(name, value='', scope='machine', note='')` | Client Session Token | 创建 secret |
| `keychains.create_login(name, username, password='', scope='machine', site='', note='')` | Client Session Token | 创建 login |
| `keychains.get_secret(name, scope='machine', machine_id='')` | Client Session Token | 读取 secret |
| `keychains.get_login(name, scope='machine', machine_id='')` | Client Session Token | 读取 login |
| `keychains.get_keychain(name, kind='', scope='machine', machine_id='')` | Client Session Token | 读取 keychain 原始数据 |

说明：

- `create_secret/create_login` 不暴露 `machine_id` 参数。
- 默认 `scope='machine'` 表示当前 client 对应的 machine。
- `scope='shared'` 表示 shared scope。

## `xt`

`xt` 用于在当前 client 执行 external tool。它只支持当前 client，不暴露 `client_id`。

```python
SCRIPT_METADATA = {
    "display_name": "External Tool Example",
    "params": [],
}

from client.runtime.sdk import xt

ffmpeg = xt.tool("ffmpeg")

print("ffmpeg.is_installed =", ffmpeg.is_installed)
print("ffmpeg.which() =", ffmpeg.which())

result = ffmpeg("-version")
print("returncode =", result.returncode)
print("stdout =", result.stdout)
print("stderr =", result.stderr)

result = xt.ffmpeg("-version")
print("ok =", result.ok)
```

常用 API：

| API | API access | 说明 |
|---|---|---|
| `xt.tool(exec_name)` | Client Session Token | 获取 external tool handle |
| `xt.run(exec_name, raw_args='', timeout=None, cwd='')` | Client Session Token | 执行 external tool |
| `xt.is_installed(exec_name)` | Client Session Token | 判断是否已安装 |
| `xt.which(exec_name)` | Client Session Token | 获取可执行文件路径 |
| `xt.<exec_name>(raw_args='', timeout=None, cwd='')` | Client Session Token | 快捷执行，例如 `xt.ffmpeg('-version')` |
| `xt.<exec_name>.is_installed` | Client Session Token | 快捷判断安装状态 |

返回对象：

```python
result.exec_name
result.command
result.returncode
result.stdout
result.stderr
result.executable
result.ok
result.text
```

未安装时执行会抛出友好异常：

```text
ScriptSdkExternalToolError: External tool is not installed for current client: ffmpeg.
```

## `workspace`

`workspace` 分两类能力：

1. `system_paths`：来自 client 握手上下文，不需要额外的 HTTP 授权声明。
2. pinned paths：来自 Server API，需要 `workspace:read`。

```python
from client.runtime.sdk import workspace

print("home =", workspace.home())
print("desktop =", workspace.desktop())
print("downloads =", workspace.downloads())
print("temp =", workspace.temp())
print("system_paths =", workspace.system_paths())
```

系统路径 API：

| API | API access | 说明 |
|---|---|---|
| `workspace.system_paths()` | 不需要 | 返回当前 client 系统路径 |
| `workspace.root()` | 不需要 | root 路径 |
| `workspace.home()` | 不需要 | home 路径 |
| `workspace.desktop()` | 不需要 | desktop 路径 |
| `workspace.documents()` | 不需要 | documents 路径 |
| `workspace.downloads()` | 不需要 | downloads 路径 |
| `workspace.temp()` | 不需要 | temp 路径 |
| `workspace.executable()` | 不需要 | 当前可执行文件路径 |
| `workspace.icloud()` | 不需要 | iCloud 路径，可能为空 |

pinned paths API：

```python
SCRIPT_METADATA = {
    "display_name": "Workspace Example",
    "params": [],
}

from client.runtime.sdk import workspace

items = workspace.list()
paths = workspace.as_dict()

print("items =", items)
print("paths =", paths)
print("pics =", workspace.path("pics"))
```

| API | API access | 说明 |
|---|---|---|
| `workspace.list()` | Client Session Token | 返回当前 client 的 pinned paths 列表 |
| `workspace.as_dict()` | Client Session Token | 返回 `{display_name: path}` |
| `workspace.get(display_name, default='')` | Client Session Token | 按 display name 获取 pinned path |
| `workspace.path(display_name, default='')` | Client Session Token | `workspace.get()` 的别名 |

## 完整示例

```python
SCRIPT_METADATA = {
    "display_name": "Script SDK Smoke Test",
    "params": [],
}

from client.runtime.sdk import context, workspace, xt, keychains

print("client_id =", context.client_id())
print("machine_id =", context.machine_id())
print("os =", context.os_alias(), context.os_ver())

print("desktop =", workspace.desktop())
print("pinned_paths =", workspace.as_dict())

print("ffmpeg installed =", xt.ffmpeg.is_installed)

secret = keychains.get_secret("test_secret")
print("secret =", secret.getvalue())
```


## Execution interaction (Web Script, inproc)

Client scripts can request browser confirmation and text input through the active Web foreground task. No per-script API permission is needed; the Client Session Token authenticates the HTTP request. This is not shell stdin.

```python
SCRIPT_METADATA = {
    "name": "mac/recon/interaction_example",
    "display_name": "Interaction Example",
    "platforms": ["mac"],
    "params": [],
}

if not context.confirm("Perform the example operation?", timeout=90):
    raise SystemExit("Not approved")
label = context.ask("Enter a label:", timeout=90)
print("Approved operation:", label)
```

`context.confirm()` returns `False` on reject or timeout, and only returns `True` after explicit approval. `context.ask()` returns user text (including an empty string) or raises `ScriptSdkInteractionError` on reject/timeout. The input response travels over a separate authenticated control request and never becomes a new foreground Command. `context.ask(secret=True)` masks the browser input; do not print or persist secrets. Each request is limited to 180 seconds. The Server holds no durable paused-execution state; Server restarts invalidate pending interactions.

Ordinary Client commands can invoke the same Interaction Broker through `CommandInteractions(self)` when authorized; no demo commands are registered.


### Execution interactions: Select and Secret

Scripts running in a Web foreground task may use:

```python
mode = context.select('Choose mode', ['Preview', 'Execute'])
secret = context.ask('Enter secret', secret=True)
if mode == 'Execute' and context.confirm('Continue?'):
    # Use the secret in memory; do not print or store it.
    print('Approved')
```

Selections are restricted to the offered strings. Secret values are returned only
to the running Client script, never in a UI SSE event. Normal command/script
execution remains unchanged unless the new APIs are explicitly called.

### Structured Preview → Approval

Use `context.approve_preview()` for **structured execution plans** rather than adding a table to a text-only `context.confirm()` prompt. It requires an active Web foreground task and Client session. It displays an Element Plus summary, table and collapsible details; only explicit approval returns `True`.

```python
from client.runtime.sdk import context

plan = {
    'summary': [
        {'label': 'Files', 'value': '12'},
        {'label': 'Total size', 'value': '64 MiB'},
    ],
    'columns': [{'key': 'path', 'label': 'Path'}, {'key': 'size', 'label': 'Size'}],
    'rows': [
        {'path': 'Documents', 'size': '18 MiB'},
        {'path': 'Projects', 'size': '46 MiB'},
    ],
    'details': [{'title': 'Full scan details', 'content': 'The exact previewed entries...'}],
    'notice': 'Please review the scanned entries before continuing.',
}
if not context.approve_preview('Execute this plan?', plan, title='Backup preview', timeout=180):
    raise SystemExit('Not approved')
# Execute only the validated plan; verify targets have not changed.
```

Authorized Client commands use `CommandInteractions(self).approve_preview(message, plan, title=...)` with the same data format. The Script `mac/recon/personal_mac_backup_preview` provides a real preview use case.

Client commands, ACMD, scripts and jobs use the same Client Session Token. Interaction also checks the current Web foreground task.

Presentation constraints: `summary` up to 16 label/value entries; `columns` up to 8 `{key,label}` pairs; `rows` up to 100 dictionaries keyed by declared column keys; `details` up to 16 `{title,content}` entries. All values are plain strings, not HTML. Only the preview UI changes: existing `confirm`, `ask`, `select`, and `secret` remain unchanged. Reject/timeout returns `False`. A preview approves a request, **not** a persistent server-side plan: the caller must verify its own actual targets before executing.

### Selectable Preview rows (opt-in)

Existing `context.approve_preview()` plans remain unchanged. Add `row_ids` only when
users should check/uncheck table rows; IDs must be unique, stable strings matching
the 1–100 visible rows. By default all rows are checked. The response contains only
selected IDs; scripts must use them to filter their own plan.

```python
plan = {
    'columns': [{'key': 'item', 'label': 'Item'}],
    'rows': [{'item': 'A'}, {'item': 'B'}],
    'row_ids': ['a', 'b'],
}
try:
    selected_ids = context.select_preview_rows('Choose items:', plan)
except ScriptSdkInteractionError:
    return  # rejected, expired, or cancelled
# [] means approved with no rows checked. This call changes no files.
```

Client Command Registry code can call
`CommandInteractions(self).select_preview_rows(message, plan, title=...)`;
Server Builtin commands can call `self.interactions.select_preview_rows(...)`.
The normal boolean-only Preview and existing switches still work without changes.

### Preview row details (opt-in)

To show a text file list inside an expandable table row, supply `row_details` alongside
`row_ids`. Each detail references an existing ID and contains plain text, not HTML:

```python
plan = {
    'columns': [{'key': 'item', 'label': 'Item'}],
    'rows': [{'item': 'Cache'}, {'item': 'Logs'}],
    'row_ids': ['cache', 'logs'],
    'row_details': [
        {'row_id': 'cache', 'content': 'Cache/file1\nCache/file2'},
        {'row_id': 'logs', 'content': 'Logs/service.log'},
    ],
}
selected = context.select_preview_rows('Choose items:', plan)
```

`row_details` is optional and may contain a subset of the provided rows (up to
100 entries, each with at most 4,000 characters). The existing top-level `details`
section remains available for unrelated information and warnings. Without
`row_details`, the table is rendered exactly as before. Expanding a row only
shows information; it does not change the selected row IDs or approval result.

For read-only expansion of a **single intermediate directory-level `*`** (e.g.
`~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/*/msg/file`),
use `from client.runtime.sdk.path_patterns import expand_directory_pattern`.
This returns existing directories without following symlinks. It performs **no**
deletions; a caller must separately scan, preview and validate targets before acting.
The Cleanup and Backup scripts do not yet call this helper.

Client process termination is now a single registered **ACMD** `acmd kill` (the
Process Manager UI keeps its internal `kill_process <pid>` path):

- `acmd kill` asks for `pid` / `name` / `port`, then the matching value, then shows
  one selectable Preview with all matched processes checked initially.
- `acmd kill --pid 1234` / `--name python` / `--port 8080` skip target entry and
  show that same Preview. Matching names and ports select **all** corresponding PIDs.
- `-9`, `-f`, `--force` initialize the Preview Force switch to ON, but the user's
  final selection determines `SIGTERM` vs `SIGKILL`.
- `--no-confirm` requires an explicit target, never opens Interaction Broker
  controls, and sends the chosen signal without preview. It also works from
  Server CLI without a Web interaction task.
- `acmd ps` lists Client processes; `--pid`, `--name`, `--port` filter it.
  `--json` returns structured rows without actions. Add `--with-actions`
  to include optional `_actions` entries for `acmd kill` in JSON output.

Client commands use the existing Client Session Token when invoking an interactive Web task. Process identity and
port ownership are verified again before signalling, including in `--no-confirm`.
The public `kill_proc`, `kill_port`, `pkill` and `pgrep` commands are removed.
The Web UI's `kill_process` handler remains unchanged.

For previews requiring optional boolean choices, add `switches: [{"key": "force", "label": "Force termination", "description": "...", "default": false}]` to the Preview schema. When no switches are requested, existing `approve_preview()` behavior and its boolean return remain unchanged; with switches, the Broker validates the explicitly offered boolean keys before returning them to the requesting Client command.

Mac backup scripts remain separately callable:
`mac/recon/personal_mac_backup` (direct),
`mac/recon/personal_mac_backup_preview_simple` (plain confirmation), and
`mac/recon/personal_mac_backup_preview` (structured approval).
