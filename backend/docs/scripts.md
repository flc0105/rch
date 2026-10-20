# Scripts — Script Library 与 Client 执行工作流

Script 是由 Server 管理源码、在指定 Client 上执行的 Python 自动化能力。Script Library 提供目录、元数据、编辑与运行入口；命令执行链负责把源码和已解析的参数交给目标设备；Script SDK 使脚本在当前任务上下文中访问本地命令、Server 资源和浏览器交互。它不是在 Server Web 进程里执行 Python，也不是 Background Job 的另一种管理方式。

一个 Script 可以是一次性检查、需要参数的维护流程或包含用户确认的多步操作。执行结束即形成一次命令任务的最终结果；不会像 Background Job 那样注册一个长期存在、可按 Job Key 管理的后台实例。真正需要持续采集、独立停止及 Job 消息历史的任务应使用 [Background Jobs](background_jobs.md)。

## 1. 脚本从存储到执行

Script Library 的权威源是 Server 文件系统中的 Python 文件，根目录是 `backend/server/resources/scripts/`。目录本身是脚本分组结构；目录下的相对路径（去掉 `.py`）就是 Script Name。例如保存为 `ops/health_probe.py` 的文件，通过 `ops/health_probe` 标识，不要求与 Metadata 的 `display_name` 相同。

Script 的一次 Web 执行顺序为：

1. Web 从 Server 获取 Catalog，显示目录、描述、平台与运行参数。
2. 用户选择目标 Client，填入参数并选择结果展示位置。
3. Server 依据相应脚本的 Metadata 转换参数，组织结构化运行请求，把 Script 源码读取出来并构造远程 `script` 类型任务。
4. 如果 Metadata 声明受保护的 Server API 权限，Server 在向 Client 下发时为本次命令签发短期 Script Grant。
5. Client 通过普通前台命令执行上下文执行 Python，回传输出与终态；Server 更新命令任务及关联历史，Web 通过既有消息渠道展示结果。

数据与控制经过不同的边界：浏览器负责操作和表单、Server 持有 Library 与授权上下文、Client 使用本机 Python 环境运行代码。执行内容不会因为放在 Server Script Library 而自动拥有 Server 文件系统或管理员权限。

Script 与 Shell-like、ACMD 都可以进入 Client 的命令执行设施，但 Script 使用单独的 `type=script` 消息和 Python 执行策略；它不把整份脚本当成一条 Shell 字符串解析。顶层 Script 仍占用该 Client 的前台任务执行槽，直到本次任务返回。长时间运行的脚本可能妨碍其他前台命令，应根据业务选择超时与执行模式。

## 2. Library 的组织、管理和元数据

### 源码文件与 Catalog

Server 递归搜索 Script 根目录中的 `.py` 文件，并根据文件本身和源码里的 `SCRIPT_METADATA` 构造 Catalog；目录列表另外由文件系统遍历得到。读取元数据使用 Python AST 的静态字面量提取，而不是为显示列表执行脚本代码。因此 Metadata 应当写成能在源码里直接解析的字典；由运行时函数动态生成的字典不应作为 UI 配置依据。

Web Script Library 提供文件夹树、脚本搜索与选择、源码编辑入口，以及创建、上传、重命名、删除 Script 和目录。上传接口只接受 `.py`；重命名和删除会实际修改 Server 文件系统，删除整个文件夹时也会递归删除内容。Catalog 来自磁盘扫描，不是另存一份可独立编辑的数据库脚本清单。修改文件内容后重新请求 Catalog，即按磁盘中当前源码重新读入元数据；已经提交的执行任务不会因后续编辑而中途替换运行代码。

目录路径会规范化为相对于 Script 根目录的路径；文件的识别名称以该相对路径为准。目录、脚本重命名会影响此后通过原名称查找或 `scripts.run()` 引用的调用方，应同步修改引用关系。

### 声明元数据

以下是一个独立的教学模板，不是项目内现有脚本清单：

```python
SCRIPT_METADATA = {
    "name": "ops/health_probe",
    "display_name": "Health Probe",
    "description": "Check a selected location and report a summary.",
    "category": "operations",
    "tags": ["diagnostics"],
    "platforms": ["mac", "linux", "win"],
    "params": [
        {"name": "target", "label": "Target folder", "type": "remote_folder", "required": True},
        {"name": "limit", "label": "Maximum results", "type": "integer",
         "default": 20, "min": 1, "max": 500},
        {"name": "verbose", "label": "Verbose", "type": "boolean", "default": False},
    ],
}

from client.runtime.sdk import context

folder = kwargs["target"]
limit = kwargs["limit"]
verbose = kwargs["verbose"]
context.progress(f"Checking {folder} (limit={limit}, verbose={verbose})")
print("Finished")
```

`name` 是可选的元数据标识；实际从 Catalog 调用时仍使用脚本文件的相对路径。`display_name`、`description`、`category`、`tags` 主要用于展示。`platforms` 经过通用平台别名规范化，未声明或使用 `*` 表示无平台限定；Web 会根据选中的 Client 平台控制运行按钮、展示兼容平台。不过这属于 Web 侧的支持性筛选，不能被当作脚本代码的跨平台运行保证，轻量终端执行入口也不应假定同样进行了完整的 UI 限制检查。

`api_grants` 也是 Script Metadata 的顶层字段，但它不属于普通业务参数。它声明脚本执行期间希望调用的受保护 Server API，具体签发与边界见后文。

### 参数如何形成并绑定

Script 使用共享 [Parameter Schema](parameter_schema.md)，而不是 ACMD 的命名选项 Schema。当前 Metadata 可声明 `string`、`textarea`、`integer`、`number`、`boolean`、`select` 及远程路径选择类型；`path_list` 还支持保留每一行的 `path` 与 `enabled` 状态，适合让用户在执行前逐项启用/停用路径。`remote_file`、`remote_folder` 返回单个路径字符串；`remote_files`、`remote_folders` 返回路径字符串数组，不会自动变为本地上传文件。Web 的远程路径字段可打开目标设备的 Remote File Picker；在选择器里触发上传时，上传本身还会经过文件传输工作流，不能因为表单里出现了路径就认定文件已经送达。

表单可根据 `required`、`default`、`min`、`max`、`options`、`label` 等配置展示和校验。Server 再通过共享参数解析器做类型转换和必填、范围、下拉枚举检查；不要只依赖浏览器验证。缺失参数可采用 Metadata 默认值，`path_list` 的空数组则是允许的明确选择，不应误当作必须恢复默认列表。

结构化执行把业务参数作为键值对象传递给 Python。脚本既可使用 `kwargs["target"]`，也可以直接使用执行环境注入的 `target` 变量；为避免参数与 SDK、Python 内建名称冲突，建议优先使用 `kwargs`。必要时自行对路径存在性、操作范围和当前文件状态做运行时验证：文件选择器完成的是选值，不替代业务安全检查。

## 3. 提交方式与输出生命周期

### Script Library 的两种展示位置

Script Run 表单可以选择 **Dialog** 或 **Terminal**：

- Dialog 先生成 `run_id`，把运行结果显示在独立弹窗，连续追加收到的文本，结束后根据任务完成消息显示成功、失败或取消；支持复制结果。
- Terminal 在终端插入带 Script 信息的命令块，把普通命令结果、完成状态呈现在终端；该命令块保留 Script Name、路径和提交参数，以便界面后续再次运行。

它们最终都调用 `POST /api/connections/{client_id}/scripts/run`，Server 都会构造同一种 `run_script` 结构化内部调用，最后下发 `type=script`。`presentation` 仅改变前端消费本次输出的方式，不会把脚本切换到另一种 Python 执行策略。

请求体形状如下；其中 `run_id` 是 Dialog 必需、Terminal 可不提供的关联标识：

```json
{
  "script_name": "ops/health_probe",
  "params": {"target": "/tmp", "limit": 20, "verbose": false},
  "presentation": "dialog",
  "run_id": "unique-ui-run-id"
}
```

Server 会给命令任务附加 `script_run`、`script_run_name`、`script_run_id`、`script_run_presentation` 等元数据。Dialog 只消费相同 Client 和 `run_id` 的对应结果；这是**结果路由标识**，不是 Script 的文件身份，也不是权限 Token。提交接口返回任务已创建不等于脚本运行成功，应以后续执行结果及终态为准。

### 终端轻量入口和结构化入口

Server 另有 `exec` 入口，它按文件名称读取 Library 脚本，并将随后按命令行扫描解析的参数交给 Script 执行计划。它适合快速发起一次性脚本执行，但不是 Web 的 Metadata 参数表单：不要假设 `exec` 一定会应用同一套必填表单逻辑、自动构造 Metadata API Grant 或弹出 Script Run Dialog。

`run_script` 则是内部结构化参数入口，Web 正常通过专用 HTTP API 产生对应 Payload；它可以携带用户参数、Script Name 和由受信任 Metadata 得来的 Grant Request。手动构造 Payload 与直接传原始 Python 文本不是一回事，正式界面操作建议使用 Script Library。

普通 Script 运行的输出经过 Python 执行策略收集后回到既有命令结果链。`print()` 可作为标准结果输出；`context.progress()` 在 In-process 且有命令所有者时可显式推送进度文本。当前 Script 默认采用 **collect** 执行调用，不应把 Script 简单等同为逐行 stdout 的真正 Shell Stream。对于输出较大、持续很久的任务，结果何时送达以及能否及时取消，还与执行策略相关。

执行记录属于命令任务生命周期，可与 Command History 的来源、状态、输出限制和 Artifact 关联协作，但 Script Library 本身不自动在数据库中保存每次运行的全部独立 Script Session 对象。

### Script Activity 记录

首批 Activity Center 将 Script Library 的 Run/Run in Terminal 及 Terminal 中的 `exec <script>` 都归为 `kind=script/action=run`。`invocation.input` 保留真实入口，`invocation.target` 保存 Script 名称或路径，`invocation.arguments` 保存 Script Library 的实际参数对象（Terminal `exec` 用 `argv` 表示原始命令行参数）。`resolved.command_type=script` 反映真实 Client Script 协议；不把 Server 侧读取的脚本源码或内部 `run_script __json__:` Base64 传输参数复制进公共 Activity，也不伪造一条 Shell 命令。

Activity 只在 Script 真的被提交给 Client 时创建；单纯列出脚本、查看/编辑元数据或打开目录不会产生记录。Script Cancel 只更新当前 Run Activity 的状态（`cancelling`、`cancelled` 等），不额外制造 `stop` Activity。Details 沿用实际任务结果的输出记录和 Artifact；Quick History 不接收 Script Library 的内部可执行 Payload。

## 4. Python 执行环境与运行上下文

### In-process 与独立子进程

Client 的 `PYTHON_EXECUTION_MODE` 决定当前 Script 使用哪种 Python 执行策略，当前有效值是 `inproc` 和 `subprocess_pipe`，默认配置为 `inproc`，在 Client Runtime Configuration 中的 `PYTHON_EXECUTION_MODE` 配置项选择。当前 Script 的 collect 调用传入 `COMMAND_DEFAULT_STREAM_TIMEOUT`（默认 300 秒）作为超时参数；`subprocess_pipe` 会把有效超时用于等待子进程，`inproc` 的 `exec()` 则不能靠这一参数自动强制中断正在执行的 Python 代码。这与 Job 的 `inproc/subprocess` 模式是不同的配置和执行管理器。

| 特性 | `inproc` | `subprocess_pipe` |
|---|---|---|
| 运行位置 | Client 进程的 Python 解释器 | 同一设备上另启 Python 子进程，通过 stdin 传入启动代码 |
| 标准输出 | 在 Client 进程中收集 `stdout/stderr` | `communicate()` 收集子进程 `stdout/stderr` |
| Client 已导出命令 | 可直接通过 SDK 调用当前命令对象 | 无完整命令对象，不能直接调用导出命令 |
| 取消 | 当前 Python 执行策略声明不支持强制取消 | 子进程可注册终止处理器，支持进程级取消 |
| 隔离 | 与 Client 进程共享解释器及全局运行风险 | Python 进程隔离，仍共享目标机器权限和文件访问范围 |

Subprocess 的源码通过 stdin 送入 Python `-u -`，运行上下文与参数通过序列化数据传入，不需要先在磁盘生成临时 `.py` 脚本。执行过程中异常被捕获并回报，执行结束或取消时处理子进程清理。In-process 的取消策略为 `none`：Web 的取消请求被接受并不意味着能中断 Python 里正在运行或阻塞的任意代码。两种方式均受命令上下文中的超时处理约束，但其可中断能力不同。

脚本主动调用 `sys.exit()`（包括 `sys.exit(0)`）或抛出 `SystemExit`、`KeyboardInterrupt`，在 `inproc` 下会被本次 Script 执行边界捕获并标记为**任务失败**，不会据此退出 Client 主循环；`subprocess_pipe` 下也会作为失败退出子进程（即使退出参数是 0）。普通 Python 异常仍按既有错误输出返回；此前已经产生的 stdout/stderr 尽量保留。脚本如需正常结束，应直接运行到末尾或从入口函数返回，而不是调用 `sys.exit(0)`。`inproc` 并不是进程沙箱：`os._exit()`、原生扩展崩溃、致命信号等仍可能终止 Client；需要隔离此类故障时应选择 `subprocess_pipe` 并核对 SDK 可用性。

**重要：** `subprocess_pipe` 不意味着交互 SDK、导出的 Client 命令和所有只针对 In-process 编写的辅助函数都能保持可用。尤其 `context.confirm()` 等基于正在执行的 Client 上下文的 Web Interaction 应在受支持的 In-process Web Script 中使用。独立进程或嵌套脚本对 SDK 的支持应按具体接口判定，不能仅因可 import 模块就认定全部功能可用。

### 注入的名称与身份

在 In-process Script 内，执行环境包含 `__name__ = '__main__'`、`kwargs`、参数对应的全局名称和 Script SDK 的模块入口。SDK 模块包括 `context`、`command`、`artifact`、`events`、`scripts`、`keychains`、`workspace`、`xt`。部分有 `@desc` 标记的 Client 导出命令还可作为便捷函数被注入；与 Python 内建函数、SDK 名称或保留上下文名称冲突的命令不会覆盖那些名称。

`context` 可读取 `client_id`、`command_id`、`hostname`、`machine_id`、`os_alias`、`os_ver`、`arch`、`system_paths`、`script_name`，也可以 `context.progress(text)` 上报人类可读的执行进度。它们属于本次执行上下文，不应由脚本自行构造虚假的 `client_id` 代替。变量辅助模块 `variables` 当前需要显式导入（如下例）；不要假定它会自动作为未定义的 Python 全局名注入。

```python
from client.runtime.sdk import context, variables

print(context.hostname(), context.os_alias())
print(variables.get("env:HOME"))
print(variables.expand("${path:home}/reports"))
```

变量 SDK 可以读取 `${rch:*}`、`${env:*}`、`${path:*}` 并展开字符串；脚本的普通字符串不会因为包含 `${...}` 就自动通过 Server 命令规划器展开。Subprocess 中部分 RCH 动态值由启动时的 Client 运行上下文预先注入，因而不要把子进程 PID 当成原 Client 进程 PID。

## 5. 在脚本中复用系统能力

Script SDK 的作用是在**当前 Client 的本次任务内**以明确的接口复用已有功能，尽量避免脚本自行拼接 Server URL、管理员凭据或内部消息协议。独立 API 参数清单可参考现有 [Script SDK API](script-sdk.md)；本节解释使用时的行为边界。

### 执行命令、操作文件与共享资源

`command.run_shell()` 在 Client 本机运行 Shell，并返回包含 `returncode`、`stdout`、`stderr` 的结果对象；`command.run_background()` 启动后台 OS 进程，并不把它变成一个可由 Job Manager 管理的 Job；`command.stream_shell()` 提供流式 Shell 执行入口。`command.run_client(name, ...)` 与动态导出命令调用需要 In-process 命令所有者；它们直接调用 Client 导出函数，不会再向 Server 发送第二条前台命令。

`artifact.save(path, ...)` 上传 Client 本地文件并将其注册为 Server Artifact，可设置正式 Artifact 类型与分类；`artifact.list/get/download/find_by_file_name` 用于查询和回取 Artifact，需要对应的 API Grant。上传文件本身不意味着一定进入 Transfer Center：只有另行创建并绑定受管理 `transfer_id` 的流程才具有那一套进度记录。Artifact 的引用、清理和历史关联见 [Artifacts](artifacts.md)。

`workspace` 无需 Grant 即可访问运行上下文提供的系统路径；访问 Server 的 Pinned Paths 则需要 `workspace:read`。`keychains` 允许读取或创建 Server 管理的凭据，需要对应 `keychains:resolve` / `keychains:create`；实际脚本应避免输出凭据明文。`xt` 依照 External Tool Catalog 在 Client 本机解析并运行程序，需要 `external_tools:catalog`，安装状态与执行生命周期由 External Tools 自身处理。`events.emit()` 用于向 Server 上报结构化 Device Event，与 `print()` 日志和临时 UI Interaction 是不同的数据链。

下面展示的是接口协作方式，不依赖项目已有任何一个脚本实例：

```python
SCRIPT_METADATA = {
    "name": "ops/create_report",
    "display_name": "Create Report",
    "platforms": ["*"],
    "params": [
        {"name": "target", "type": "remote_folder", "required": True},
    ],
}

from pathlib import Path
from client.runtime.sdk import context, artifact

report = Path(kwargs["target"]) / "report.txt"
report.write_text("Health check completed\n", encoding="utf-8")
saved = artifact.save(str(report), category="script")
context.progress(f"Saved artifact: {saved.get('artifact_id', '')}")
```

这个示意脚本默认目标路径存在且可写；实际开发时要先确认目标位置和用户授权，并妥善处理权限、已有文件与 I/O 错误。`artifact.save()` 本身不是向浏览器展示确认对话框。

### 在当前执行里调用子脚本

需要复用 Library 内的另一个 Script 时，可使用 `scripts.run(name, params=None, timeout=30)`。它先使用受限的 `scripts:read` 权限从 Server 下载 Script 源码，在**当前 Client 本次执行中同步执行**，返回包含 `ok`、`returncode`、`stdout`、`stderr` 的 `ScriptResult`。`ScriptResult.json()` 只负责把子脚本 stdout 解析为 JSON；不会自动把普通打印内容包装成 JSON。

```python
SCRIPT_METADATA = {
    "name": "ops/parent",
    "api_grants": ["scripts:read"],
    "params": [],
}

from client.runtime.sdk import scripts

result = scripts.run("ops/child", {"mode": "check"})
if not result.ok:
    raise RuntimeError(result.stderr or "Child script failed")
print(result.stdout)
```

子脚本会再次按照自己的 Metadata 解析收到的参数，但**不会按子脚本的 Metadata 重新签发 Script Grant**。它沿用调用者的临时上下文和授权，因此父脚本必须主动声明整个执行链所需的权限。当前实现还检测自调用、嵌套重复调用，并限制嵌套深度（最多 8 层活跃子脚本）。子脚本的标准输出与标准错误被捕获后作为结果返回，通常由父脚本决定打印哪些内容。它不会触发新的 Server `run_script` 任务，也不会形成独立的 Web Script Run Dialog。

子脚本通过 `exec()` 执行的是 Server Library 提供的 Python 源码；这不是隔离沙箱。只有可信脚本适合被这样复用。父脚本同步调用期间同样会受到顶层命令任务的寿命和占用约束。

## 6. Script Grant 与用户交互

### 临时授权如何进入执行上下文

普通 Web 管理员 Session 和管理员 API Token 是浏览器/外部程序的认证体系，不应直接交给脚本。Script 要访问受保护的 Server API 时，在静态 Metadata 中声明 `api_grants`，例如：

```python
SCRIPT_METADATA = {
    "name": "ops/review_and_read",
    "params": [],
    "api_grants": ["interactions:request", "artifacts:list"],
}
```

Web 读取实际 Script Metadata，Server 在构造结构化运行任务时将请求的 Scopes 与 Script Name 一起传到可信命令通道。命令通道依据允许的 Scope 生成一次性随机 Token，与当前 Client、Machine、`command_id` 和 Script Name 绑定；Client 只收到执行所需的短期凭据。SDK 的 HTTP Client 对相应 Server API 自动附带 `X-Script-Grant-Token`，无需脚本手写管理员 Bearer Token。

默认 Grant 有效期为 300 秒，最多使用 100 次；请求中的 TTL/次数不能突破这两个服务端上限。签发时只接受策略允许的 Scope，服务端按 HTTP 方法与路径校验。完成、断开或 Grant 到期、次数耗尽后无法继续使用。它是一种**按 URL/方法授权**的临时能力，不等于针对 Artifact ID、Keychain 名称、远程设备目录的细粒度资源权限，也不限制脚本在本机自行执行 Python/OS 操作。

特别注意：Web 结构化运行会基于 Metadata 创建 Grant Request；终端 `exec` 的轻量执行方式不会自动采取相同的授权请求构造流程。直接在另一个环境启动 Python 文件也不会自动获得 Server Script Grant。如果缺少权限，SDK 应明确报错，而不是建议把管理员 API Token 硬编码进脚本。详细的认证体系与 Script Grant 机制见 [Administrator Authentication](admin-auth.md)。

### 执行中请求浏览器决策

在 Web 发起、In-process 且具备 `interactions:request` Grant 的 Script 中，可以通过 `context.confirm()`、`context.ask()`、`context.select()`、`context.approve_preview()`、`context.select_preview_rows()` 请求浏览器交互。这是一次受任务身份约束的 Interaction Broker 往返，不是 Shell stdin，也不是额外发起一条命令。

```python
SCRIPT_METADATA = {
    "name": "ops/review_action",
    "api_grants": ["interactions:request"],
    "params": [],
}

from client.runtime.sdk import context

plan = {
    "summary": [{"label": "Action", "value": "Review selected files"}],
    "columns": [{"key": "path", "label": "Path"}],
    "rows": [{"path": "/tmp/sample.txt"}],
}

if not context.approve_preview("Proceed with this plan?", plan, timeout=90):
    raise SystemExit("Cancelled by user")

context.progress("Approved; starting the operation")
```

确认或普通 Preview 的拒绝/超时返回 `False`；输入、选择及可勾选 Preview 的拒绝或超时会通过相应异常表达。文本输入支持 `secret=True`，只在浏览器隐藏输入，并不意味着脚本可以安全打印、保存或继续传播该秘密。交互请求的时间上限为 180 秒，页面关闭、任务结束或连接丢失可能使等待的操作失效。

Preview 只返回确认结果或被勾选的行 ID，并不会由 Server 自动执行预览中的计划；脚本必须在用户确认后重新验证要操作的文件或对象。其完整数据模型、Preview 表格和响应语义见 [Interaction Broker](interaction_broker.md)。

## 7. 运行结果、资源归属与可观测性

Script 的任务状态和文本结果属于命令执行通道，Output 可以在 Terminal 或 Script Result Dialog 中消费；它们不等同于脚本上传的 Artifact。需要保存报告、截图或其他二进制文件时，应显式调用 Artifact 上传接口。调用 `events.emit()` 发出业务通知也不会自动将 `stdout` 保存在通知历史。

Script 输出可以是人类可读文本，也可以显式打印 JSON。需要让 Terminal JSON Viewer 识别一段结构化结果时，应保证输出为完整、合法的 JSON；混入调试信息、多行日志或 Python `dict` 的 `repr` 不等于 JSON。`scripts.run(...).json()` 则仅解析子脚本的 stdout，并与浏览器端的 Table/Flat/Raw 展示相互独立。更多规则见 [Structured Command Output](structured_output.md)。

一个 Script 执行完毕后，可通过命令任务关联对应的 Command History Entry；相关历史的具体保留数量、输出截断、删除规则由 Command History 管理。脚本源码本身在 Library 文件系统中持久保存，但 `inproc` 中的 Python 全局执行状态、浏览器当前弹窗、临时 Script Grant 和等待中的 Interaction 都不是可在 Server 重启后恢复的持久脚本会话。

需要注意脚本执行路径的副作用：对 Client 磁盘、进程、网络和外部工具的操作由脚本代码本身控制。Script Grant 的 URL 访问范围不是 Python 沙箱；不要执行未经审查的 Script Library 源码，也不要因为表单完成校验就省略高风险操作前的目标核对。

## 8. Web API、扩展接入与常见边界

### 管理接口与运行接口

Script Library 的 HTTP 管理入口提供目录、文件的读取及修改。重要的是分清**管理脚本源码**和**执行脚本任务**：

| 行为 | HTTP API | 作用 |
|---|---|---|
| 刷新 Catalog | `GET /api/scripts/catalog` | 列出当前文件与目录及静态 Metadata |
| 读取源码 | `GET /api/scripts/download?name=...` | 获取指定 Script Python 文本 |
| 保存源码 | `POST /api/scripts/save` | 按相对名称写入源码 |
| 上传源码文件 | `POST /api/scripts/upload` | 上传 `.py` 到 Server Library |
| 重命名或删除脚本 | `POST /api/scripts/rename`、`DELETE /api/scripts/delete` | 修改服务器中的文件 |
| 管理目录 | `POST /api/scripts/folders`、`POST /api/scripts/folders/rename`、`DELETE /api/scripts/folders` | 创建、重命名或递归删除目录 |
| 在设备上执行 | `POST /api/connections/{client_id}/scripts/run` | 按 Metadata 绑定参数，提交前台 Script 任务 |

Run API 要求 `script_name` 非空、`params` 为对象，并明确提供 `presentation` 为 `dialog` 或 `terminal`；Dialog 还需非空 `run_id`。它校验参数后创建普通 Web 命令任务，并非同步等待整个脚本运行完成的 HTTP 请求。直接通过 API 或新的前端按钮接入时，应复用这些字段与既有 `task_id`/SSE 结果处理，而不是绕开 Script 运行服务私自下发 Python 代码。

当前 Catalog 由 Server 文件系统决定。运行前刷新 Catalog 可获得最新 Metadata；上传和编辑不能保证已经打开的其他浏览器脚本表单自动更新，应根据界面生命周期重新获取数据。修改脚本名称后，旧的终端运行块或其他 Script 的 `scripts.run()` 引用也需要采用新的 Script Name。

### 故障定位的顺序

| 现象 | 首先检查 |
|---|---|
| 看得到脚本但不能 Run | 目标 Client 是否已选中；Metadata `platforms` 是否包含该 Client；脚本是否仍存在于 Catalog |
| 表单参数报错 | `params` 的真实类型、必填/default、数值范围、远程路径单选/多选、`path_list` 的行结构 |
| 提交成功后没有结果 | 前台任务是否仍运行；消息是否匹配 Client/Task；Dialog 的 `run_id` 是否一致 |
| SDK 提示缺少 Grant | 顶层 Script 的静态 Metadata 是否声明所需 Scope；是否使用了正常 Web 结构化运行入口 |
| 子脚本调用失败 | `scripts:read`、Library 相对名称、递归调用限制以及被调脚本的实际参数 |
| 部分 Client 命令或 Interaction 不可用 | Python 执行策略是否为 `inproc`，当前是否有命令所有者和有效交互 Grant |
| 无法取消长时间脚本 | In-process 不支持任意强制中断；Subprocess 的取消也取决于进程控制和清理完成 |
| 输出不是 JSON 表格 | stdout 是否是单一合法 JSON，是否混入进度文本、日志或非 JSON 的 Python 表示 |
| 上传文件后找不到 | Artifact 类型、返回的 `artifact_id`、Client/Command 关联及 Artifact 当前可用性 |

Script 的边界不是“只要是 Python 就能无条件使用全部 Client 能力”。当需要增加功能，应先判断它属于 Library 管理、Metadata 表单、任务执行、SDK、授权，还是特定的文件/监控/Job 生命周期，再接入已有对应服务。这样能保持 Script 的一次性任务语义清晰，也便于沿着真实错误来源排查。
