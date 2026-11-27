# Scripts — Script Library 与 Client 执行工作流

Script 是由 Server 管理源码、在指定 Client 上执行的 Python 自动化能力。Script Library 提供目录、元数据、编辑与运行入口；命令执行链负责把源码和已解析的参数交给目标设备；Script SDK 使脚本在当前任务上下文中访问本地命令、Server 资源和浏览器交互。脚本源码由 Server 保存，运行任务由目标 Client 执行；长期后台任务另由 [Background Jobs](background_jobs.md) 管理。

一个 Script 可以是一次性检查、需要参数的维护流程或包含用户确认的多步操作。执行结束即形成一次命令任务的最终结果；不会像 Background Job 那样注册一个长期存在、可按 Job Key 管理的后台实例。真正需要持续采集、独立停止及 Job 消息历史的任务应使用 [Background Jobs](background_jobs.md)。

## 1. 脚本从存储到执行

Script Library 的权威源是 Server 文件系统中的 Python 文件，根目录是 `backend/server/resources/scripts/`。目录本身是脚本分组结构；目录下的相对路径（去掉 `.py`）就是 Script Name。例如保存为 `ops/health_probe.py` 的文件，通过 `ops/health_probe` 标识，不要求与 Metadata 的 `display_name` 相同。

Script 的一次 Web 执行顺序为：

1. Web 从 Server 获取 Catalog，显示目录、描述、平台与运行参数。
2. 用户选择目标 Client，填入参数并选择结果展示位置。
3. Server 依据相应脚本的 Metadata 转换参数，组织结构化运行请求，把 Script 源码读取出来并构造远程 `script` 类型任务。
4. Script 使用已连接 Client 的统一 Session Token 调用允许的 Server API。
5. Client 通过普通前台命令执行上下文执行 Python，回传输出与终态；Server 更新命令任务及关联历史，Web 通过既有消息渠道展示结果。

数据与控制经过不同的边界：浏览器负责操作和表单、Server 持有 Library 与授权上下文、Client 使用本机 Python 环境运行代码。执行内容不会因为放在 Server Script Library 而自动拥有 Server 文件系统或管理员权限。

Script 与 Shell-like、ACMD 共用 Client 前台执行基础设施；ScriptManager 使用 `control(domain=script, action=run)` 和现有 Python 执行策略；ScriptManager 直接调用 Python 执行策略，Command Catalog 只在 SDK 显式调用真实 Client 命令时负责解析与执行。顶层 Script 仍占用该 Client 的前台任务执行槽，直到本次任务返回。长时间运行的脚本可能妨碍其他前台命令，应根据业务选择超时与执行模式。

## 2. Library 的组织、管理和元数据

### 源码文件与 Catalog

Server 的 `ScriptCatalogService` 是 Script Library、终端 `script list` 和 `script view/exec` 参数补全共享的目录扫描与 Metadata 来源：递归搜索 Script 根目录中的 `.py` 文件，并根据文件本身和源码里的 `SCRIPT_METADATA` 构造 Catalog；目录列表另外由文件系统遍历得到。读取元数据使用 Python AST 的静态字面量提取，而不是为显示列表执行脚本代码。Metadata 应写成源码里可静态解析的字典，供 UI 构建参数表单。

Web Script Library 提供文件夹树、当前目录的子文件夹和脚本列表、返回上级目录、脚本搜索与选择、源码编辑入口，以及创建、上传、重命名、删除 Script 和目录。上传接口只接受 `.py`；重命名和删除会实际修改 Server 文件系统，删除整个文件夹时也会递归删除内容。Catalog 根据磁盘中的 Script 源文件实时扫描生成。修改文件内容后重新请求 Catalog，即按磁盘中当前源码重新读入元数据；已经提交的执行任务不会因后续编辑而中途替换运行代码。

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

`name` 是可选的元数据标识；实际从 Catalog 调用时仍使用脚本文件的相对路径。`display_name`、`description`、`category`、`tags` 主要用于展示。`platforms` 经过通用平台别名规范化；对 **Web Script Library**，未声明或使用 `*` 表示无平台限定，Web 会根据选中的 Client 平台控制运行按钮与兼容平台展示。**Terminal `script list` / 补全与 Web 不同：未声明平台的脚本不会显示，但显式执行仍不被此筛选阻止。** 这两种列表判断都不能保证脚本在目标系统有完整的运行库或权限。


### 参数如何形成并绑定

Script 使用共享 [Parameter Schema](parameter_schema.md)，而不是 ACMD 的命名选项 Schema。当前 Metadata 可声明 `string`、`password`、`textarea`、`integer`、`number`、`boolean`、`select` 及远程路径选择类型；`path_list` 还支持保留每一行的 `path` 与 `enabled` 状态，适合让用户在执行前逐项启用/停用路径。`remote_file`、`remote_folder` 返回单个路径字符串；`remote_files`、`remote_folders` 返回路径字符串数组，不会自动变为本地上传文件。Web 的远程路径字段可打开目标设备的 Remote File Picker；在选择器里触发上传时，上传本身还会经过文件传输工作流，不能因为表单里出现了路径就认定文件已经送达。

表单可根据 `required`、`default`、`min`、`max`、`options`、`label` 等配置展示和校验。Server 再通过共享参数解析器做类型转换和必填、范围、下拉枚举检查；不要只依赖浏览器验证。缺失参数可采用 Metadata 默认值，`path_list` 的空数组则是允许的明确选择，不应误当作必须恢复默认列表。

密码参数可以声明 `keychain_picker`，让共享字段控件从当前机器或 Server Shared 的 Keychains 选择凭证；Login 可一次绑定 `username` 与 `password`。示例 `examples/keychain_login_picker.py` 展示了这套映射，并输出参数是否收到及密码长度。

结构化执行把业务参数作为键值对象传递给 Python。脚本既可使用 `kwargs["target"]`，也可以直接使用执行环境注入的 `target` 变量；为避免参数与 SDK、Python 内建名称冲突，建议优先使用 `kwargs`。必要时自行对路径存在性、操作范围和当前文件状态做运行时验证：文件选择器完成的是选值，不替代业务安全检查。

## 3. 提交方式与输出生命周期

### Script Library 的两种展示位置

Script Run 表单的 Execution Mode 和 Output Mode 默认折叠，标题显示当前选择，点击可展开或收起。展开后各自显示全部选项；不符合脚本 Schema 或目标 Client 能力的选项禁用。所选模式的说明显示在对应控件下方。

Script Run 表单可以选择 **Dialog** 或 **Terminal**：

- Dialog 先生成 `run_id`，把运行结果显示在独立弹窗，连续追加收到的文本，结束后根据任务完成消息显示成功、失败或取消；支持复制结果。
- Terminal 在终端插入带 Script 信息的命令块，把普通命令结果、完成状态呈现在终端；该命令块保留 Script Name、路径和提交参数，以便界面后续再次运行。

它们最终都调用 `POST /api/connections/{client_id}/scripts/run`，Server 直接创建 Script Web Task；Script Library 与终端 `script exec` 通过相同的 Script Metadata 校验和规范化参数构建 `type=control, domain=script, action=run` 请求。`presentation` 仅决定这次输出送往 Dialog 还是 Terminal，不属于 Client Control Payload，也不作为 Script Activity 的展示字段持久化；它不会切换 Python 执行策略。

请求体形状如下；其中 `run_id` 是 Dialog 必需、Terminal 可不提供的关联标识：

```json
{
  "script_name": "ops/health_probe",
  "params": {"target": "/tmp", "limit": 20, "verbose": false},
  "execution_mode": "inproc",
  "output_mode": "collect",
  "presentation": "dialog",
  "run_id": "unique-ui-run-id"
}
```

Server 会给命令任务附加 `script_run`、`script_run_name`、`script_run_id`、`script_run_presentation` 等元数据。Dialog 只消费相同 Client 和 `run_id` 的对应结果；这是**结果路由标识**，不是 Script 的文件身份，也不是权限 Token。提交 API 返回任务创建状态；脚本完成情况由执行结果事件及终态反馈。

### 终端轻量入口和结构化入口

Server 的 `script exec <name> [--execution_mode MODE] [--output_mode MODE] -- --key VALUE ...` 使用 Server 共用参数解析器把运行选项和 `--` 之后的脚本参数分开，随后与 Script Library Web 表单使用**相同的 Script Metadata 参数校验、默认值和源码加载入口**。Web 不再生成伪造的 `script run` 命令。两端最终发送相同形状的 Control 请求。Web 任务消费提交时已经准备好的源码与参数，不再次加载脚本文件：

```json
{"type":"control","id":49,"domain":"script","action":"run","payload":{"script_name":"ops/health_probe","source":"<Server 提供的脚本源码>","params":{"target":"/tmp","limit":20},"execution_mode":"inproc","output_mode":"collect"}}
```

Server 统一准备 Script Control 的源码、业务参数与已解析的两个运行模式。`execution_mode`、`output_mode` 是独立的 Control 字段，不属于脚本 `params`，Client 不另选默认值。CLI 模式选项必须位于脚本路径之前，路径之后仍是业务参数，例如：

```text
script exec --name ops/health_probe --execution_mode subprocess_pipe --output_mode stream -- --limit 20
```

### 每脚本运行模式 Schema

可选的 `SCRIPT_METADATA.execution` 声明如下；两个子对象分别独立约束执行模式与输出模式：

```python
SCRIPT_METADATA = {
    'name': 'ops/health_probe',
    'execution': {
        'modes': {'allowed': ['inproc', 'subprocess_pipe'], 'default': 'inproc'},
        'output': {'allowed': ['collect', 'stream'], 'default': 'stream'},
    },
    'params': [],
}
```

优先级为：**本次显式选择 → 对应 Schema default → 目标 Client 当前 Configuration/set 值**。允许范围为 Schema allowed 与 Client 实际支持模式的交集。allowed 缺省表示该维度的全部有效枚举；default 必须属于 allowed。若默认值不在交集内，Dialog 不代选，用户须选有效模式；CLI 需显式指定。没有可用值、未知值或非法 Schema 时拒绝运行。`execution` 完全省略时，两个维度直接使用 Client 配置默认值（Python: inproc + collect；Go: subprocess_pipe + collect）。Dialog 打开与提交时读取实时配置，不依赖握手快照；本次选择不修改 Configuration/set。

`collect`：普通 stdout/stderr 在执行结束时汇总返回，取消/超时仍返回已捕获的文本。`stream`：按行、显式 flush 或长行片段即时输出，末尾无换行的片段也保留；stderr 本身不表示失败，最终退出状态才决定成功与否。现有 `context.progress()` 是独立 SDK 进度接口。`context.emit(data)` 发送显式结构化 JSON 输出事件；`context.emit_view(data, view=...)` 还可为同一条数据附带结果级 JSON Viewer 标题、列、详情和 Actions。两者均可与 `print()` 文本按顺序混排。Python Client 的 inproc 使用本次执行上下文，subprocess_pipe 使用本地专用的有序输出通道，而不是在 stdout 插入标记；collect 仅缓冲普通 stdout/stderr，显式 `context.progress(message, level=...)` 仍即时发真正的 progress 事件；stream 的普通输出实时发送。progress 的 level 可选（info/success/warning/error），省略不加任何 Marker；公共 Server 渲染器负责给有 level 的 progress 添加标记，永远不修改 print 文本。两个 Strategy 只返回执行结果，统一执行入口发送唯一终态；超时/取消采用明确的结构化事件。

执行记录属于命令任务生命周期，可与 Command History 的来源、状态、输出限制和 Artifact 关联协作，但 Script Library 本身不自动在数据库中保存每次运行的全部独立 Script Session 对象。

在 Web Terminal 中，从 Script Library 选择 **Run in Terminal** 或重跑终端 Script 区块，会像输入栏提交新命令一样恢复终端尾部跟随；`stream` 模式后续逐行输出沿用现有 Terminal 流与历史存储。选择 **Run** 的独立结果 Dialog 不改变 Terminal 当前滚动位置；用户在运行中主动上翻历史后，仍可暂停自动跟随。

### Script Activity 记录

Activity Center 将 Script Library 的 Run/Run in Terminal 及 Terminal 中的 `script exec <script>` 都归为 `kind=script/action=run`。Terminal 原始命令保存在 Invocation，UI 调用为空对象；Resolved 保存实际发送的完整 `control(domain=script, action=run)` 请求，包括源码、参数和运行模式。

Activity 只在 Script 真的被提交给 Client 时创建；单纯列出脚本、查看/编辑元数据或打开目录不会产生记录。Script Cancel 只更新当前 Run Activity 的状态（`cancelling`、`cancelled` 等），不额外制造 `stop` Activity。Details 沿用实际任务结果的输出记录和 Artifact；Quick History 不接收 Script Library 的内部可执行 Payload。

## 4. Python 执行环境与运行上下文

### macOS LaunchAgent / LaunchDaemon 管理

macOS Script 可以通过 `client.runtime.sdk.launchd` 统一管理 LaunchAgent / LaunchDaemon。公开生命周期动作固定为 `install / start / stop / restart / uninstall / status`，支持统一 label、目标 GUI 用户、`KeepAlive`、`RunAtLoad`、明确的 launchd domain，并与 Client 的 Launch Mode、Watchdog suppression 和 UID 隔离临时目录协作。完整的安装位置、权限、状态语义、SDK 示例、排障与实机验收见 [macOS launchd Service Management](launchd.md)。

### In-process 与独立子进程

`SCRIPT_DEFAULT_EXECUTION_MODE` 是 Script 未明确指定执行模式时的 Client 配置默认值（Python 默认 `inproc`），`SCRIPT_DEFAULT_OUTPUT_MODE` 的默认值为 `collect`。Script 使用本次已解析的模式；普通 `pyexec` / `pyexec_stream` 继续复用默认执行策略，分别收集或流式输出。Script 使用独立的 `SCRIPT_DEFAULT_TIMEOUT`（默认 300 秒），通过 `config set SCRIPT_DEFAULT_TIMEOUT <秒数>` 或 Info → Configuration 设置。`subprocess_pipe` 按该限制等待并终止超时子进程；`inproc` 会在脚本返回后检查是否超时，进程内的 Python `exec()` 无法安全地在执行途中强制中断。这与 Job 的 `inproc/subprocess` 模式是不同的配置和执行管理器。

| 特性 | `inproc` | `subprocess_pipe` |
|---|---|---|
| 运行位置 | Client 进程的 Python 解释器 | 同一设备上另启 Python 子进程，通过 stdin 传入启动代码 |
| 标准输出 | 当前执行上下文捕获 Python stdout/stderr，支持 collect/stream | 合并读取 stdout/stderr 管道，支持 collect/stream |
| Client 已导出命令 | 可直接通过 SDK 调用当前命令对象 | 无完整命令对象，不能直接调用导出命令 |
| 取消 | 当前 Python 执行策略声明不支持强制取消 | 子进程可注册终止处理器，支持进程级取消 |
| 隔离 | 与 Client 进程共享解释器及全局运行风险 | Python 进程隔离，仍共享目标机器权限和文件访问范围 |

Subprocess 的源码通过 stdin 送入 Python `-u -`，运行上下文与参数通过序列化数据传入，不需要先在磁盘生成临时 `.py` 脚本。执行过程中异常被捕获并回报，执行结束或取消时处理子进程清理。In-process 的取消策略为 `none`：Web 不提供强制取消入口，Client 明确拒绝取消请求。In-process 的超时在 Python 返回或支持检查点的 SDK 操作处判定，不能安全地强杀任意 Python 代码。In-process 捕获当前 Python 执行上下文的文本输出，其他线程日志不混入；脚本自行创建的线程和原生文件描述符输出不自动纳入捕获，需完整进程输出隔离时选择 subprocess_pipe。两种方式均受命令上下文中的超时处理约束，但其可中断能力不同。

脚本主动调用 `sys.exit()`（包括 `sys.exit(0)`）或抛出 `SystemExit`、`KeyboardInterrupt`，在 `inproc` 下会被本次 Script 执行边界捕获并标记为**任务失败**，不会据此退出 Client 主循环；`subprocess_pipe` 下也会作为失败退出子进程（即使退出参数是 0）。普通 Python 异常仍按既有错误输出返回；此前已经产生的 stdout/stderr 尽量保留。脚本如需正常结束，应直接运行到末尾或从入口函数返回，而不是调用 `sys.exit(0)`。`inproc` 并不是进程沙箱：`os._exit()`、原生扩展崩溃、致命信号等仍可能终止 Client；需要隔离此类故障时应选择 `subprocess_pipe` 并核对 SDK 可用性。

**重要：** `subprocess_pipe` 不意味着交互 SDK、导出的 Client 命令和所有只针对 In-process 编写的辅助函数都能保持可用。尤其 `context.confirm()` 等基于正在执行的 Client 上下文的 Web Interaction 应在受支持的 In-process Web Script 中使用。独立进程或嵌套脚本对 SDK 的支持应按具体接口判定，不能仅因可 import 模块就认定全部功能可用。

### Go Client：外部 Python 执行

Go Client 使用可选的本机 Python 解释器运行普通 Python Script。仅支持 `subprocess_pipe`，配置默认 `subprocess_pipe + collect`，也可选择 `stream`。收到 Server 下发的 `control(domain=script, action=run)` 消息后，依次在系统 `PATH` 查找解释器：Windows 优先 `python`、再找 `python3`；macOS/Linux 优先 `python3`、再找 `python`。没有找到解释器时，本次 Script 返回明确错误，不会安装 Python 或影响 Go Client 连接。

Web Script Library 保留现有 `SCRIPT_METADATA.params` 表单和 Server 参数校验：Server 根据 Schema 解析 `required`、`default`、类型和选项，再将参数字典通过 `extra` 交给 Go Client。Go 通过独立 Python 子进程执行收到的源码，提供 `kwargs` 及参数同名全局变量，支持常规 `print()`、标准库和目标机器已安装的 Python 包。脚本在目标 Client 工作目录中运行，stdout/stderr 通过已有命令结果通道回传；执行占用前台任务槽，支持取消，默认超时为 300 秒，可以通过 `SCRIPT_DEFAULT_TIMEOUT` 调整。

这一执行环境提供普通 Python 运行能力，不注入 Python Client 的 Script SDK（例如 `context`、`artifact`、`scripts`、`keychains`、`workspace` 和导出的 Client 命令）。依赖这些 SDK 的脚本需选择 Python Client；在 Go Client 上调用时，按实际导入或名称错误反馈。Go Client 可通过 Server `config` 命令及 Info → Configuration 管理运行配置。`SCRIPT_PYTHON_PATH` 默认留空并按系统 `PATH` 查找解释器；填写后直接使用指定路径，无法找到该解释器时报告错误。`SCRIPT_DEFAULT_TIMEOUT` 控制 Script 子进程运行时长（默认 300 秒）。配置写入用户配置目录的 `rchclient/runtime_config_go.json`，重新启动后继续生效。

### 注入的名称与身份

在 In-process Script 内，执行环境包含 `__name__ = '__main__'`、`kwargs`、参数对应的全局名称和 Script SDK 的模块入口。SDK 模块包括 `context`、`command`、`artifact`、`events`、`scripts`、`keychains`、`workspace`、`xt`。部分有 `@shell_command` 标记的 Client 导出命令还可作为便捷函数被注入；与 Python 内建函数、SDK 名称或保留上下文名称冲突的命令不会覆盖那些名称。

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

`artifact.save(path, ...)` 上传 Client 本地文件并将其注册为 Server Artifact，Saved 文件通过 category 归入固定目录，Shared 文件通过 folder 指定共享目录；`artifact.list/get/download/find_by_file_name` 用于查询和回取 Artifact，使用当前 Client Session Token。上传文件本身不意味着一定进入 Transfer Center：只有另行创建并绑定受管理 `transfer_id` 的流程才具有那一套进度记录。Artifact 的引用、清理和历史关联见 [Artifacts](artifacts.md)。

`workspace` 可以读取运行上下文和 Server Pinned Paths；`keychains` 可以访问当前机器与 Shared 凭据，实际脚本应避免输出凭据明文；`xt` 依照 External Tool Catalog 在 Client 本机解析并运行程序，安装状态与执行生命周期由 External Tools 自身处理。`events.emit()` 用于向 Server 上报结构化 Device Event，与 `print()` 日志和临时 UI Interaction 是不同的数据链。

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
saved = artifact.save(str(report), category="script_files")
context.progress(f"Saved artifact: {saved.get('artifact_id', '')}")
```

这个示意脚本默认目标路径存在且可写；实际开发时要先确认目标位置和用户授权，并妥善处理权限、已有文件与 I/O 错误。`artifact.save()` 本身不是向浏览器展示确认对话框。

### 在当前执行里调用子脚本

需要复用 Library 内的另一个 Script 时，可使用 `scripts.run(name, params=None, timeout=30)`。它先使用受限的 `scripts:read` 权限从 Server 下载 Script 源码，在**当前 Client 本次执行中同步执行**，返回包含 `ok`、`returncode`、`stdout`、`stderr` 的 `ScriptResult`。`ScriptResult.json()` 只负责把子脚本 stdout 解析为 JSON；不会自动把普通打印内容包装成 JSON。

```python
SCRIPT_METADATA = {
    "name": "ops/parent",
    "params": [],
}

from client.runtime.sdk import scripts

result = scripts.run("ops/child", {"mode": "check"})
if not result.ok:
    raise RuntimeError(result.stderr or "Child script failed")
print(result.stdout)
```

子脚本会再次按照自己的 Metadata 解析收到的参数，但**复用同一 Client Session Token**，不生成子脚本授权凭证。当前实现还检测自调用、嵌套重复调用，并限制嵌套深度（最多 8 层活跃子脚本）。子脚本的标准输出与标准错误被捕获后作为结果返回，通常由父脚本决定打印哪些内容。它不会触发新的 Server `script run` 任务，也不会形成独立的 Web Script Run Dialog。

子脚本通过 `exec()` 执行的是 Server Library 提供的 Python 源码；这不是隔离沙箱。只有可信脚本适合被这样复用。父脚本同步调用期间同样会受到顶层命令任务的寿命和占用约束。

## 6. Client Session Token 与用户交互

Script、Command 和 Job 复用当前 Client 连接时获得的 Client Session Token，API 方法和路径在 [Client Session Token](client_session_api.md) 的策略文件中集中维护。客户端使用 `ClientApiClient` 时，会自动向 Server API 发送 `X-Client-Session-Token`。管理员 Token 仍只用于 Web 管理员和外部管理程序。

### 执行中请求浏览器决策

在 Web 发起、具有当前 Client 连接和前台命令上下文的 Script 中，可以通过 `context.confirm()`、`context.ask()`、`context.select()`、`context.approve_preview()`、`context.select_preview_rows()` 请求浏览器交互。这是一次受任务身份约束的 Interaction Broker 往返，不是 Shell stdin，也不是额外发起一条命令。

```python
SCRIPT_METADATA = {
    "name": "ops/review_action",
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

Script 输出可以是人类可读文本，也可以显式打印 JSON。需要独立的结构化记录时，Python Client Script 使用 `context.emit(data)`；需要可操作的 Viewer 时使用 `context.emit_view(data, view=...)`。两者都经原有 Result 通道发送可序列化的 JSON 对象/数组，无须把文本与数据拼成一段 JSON；普通 `print()` 与结构化事件可连续出现。Script Result Dialog 的 View JSON 与 Terminal JSON Viewer 均使用这条数据对应的结果级 `view`。一次执行可以发送多条结构化记录：Viewer 优先展示最后一条携带 `view` 的记录及其配对数据；如果没有记录携带 `view`，展示最后一条结构化记录。再次执行 Script 时采用同一规则，普通日志及后续独立 `emit()` 不会覆盖已展示的 Actions。手动打印 JSON 时仍应保证 JSON 块合法。`scripts.run(...).json()` 只解析子脚本 stdout，与 Viewer 的结构化事件相互独立。更多规则见 [Structured Command Output](structured_output.md)。

一个 Script 执行完毕后，可通过命令任务关联对应的 Command History Entry；相关历史的具体保留数量、输出截断、删除规则由 Command History 管理。脚本源码本身在 Library 文件系统中持久保存，但 `inproc` 中的 Python 全局执行状态、浏览器当前弹窗、连接期 Token 和等待中的 Interaction 都不是可在 Server 重启后恢复的持久脚本会话。

需要注意脚本执行路径的副作用：对 Client 磁盘、进程、网络和外部工具的操作由脚本代码本身控制。Client API 的 URL 白名单不是 Python 沙箱；不要执行未经审查的 Script Library 源码，也不要因为表单完成校验就省略高风险操作前的目标核对。

## 8. Web API、扩展接入与常见边界

### 管理接口与运行接口

Script Library 的 HTTP 管理入口提供目录、文件的读取及修改。重要的是分清**管理脚本源码**和**执行脚本任务**：

| 行为 | HTTP API | 作用 |
|---|---|---|
| 刷新 Catalog | `GET /api/scripts/catalog` | 列出当前文件与目录及静态 Metadata |
| 读取源码 | `GET /api/scripts/download?name=...` | 获取指定 Script Python 文本 |
| 保存源码 | `POST /api/scripts/save` | 按相对名称写入源码 |
| 上传源码文件 | `POST /api/scripts/upload` | 上传 `.py` 到 Server Library |
| 重命名或删除脚本 | `POST /api/scripts/rename`、`DELETE /api/scripts/delete` | 修改服务器中的文件；重命名时同步更新已有静态 Script Metadata 的 `name`（不含 `.py`） |
| 管理目录 | `POST /api/scripts/folders`、`POST /api/scripts/folders/rename`、`DELETE /api/scripts/folders` | 创建、重命名或递归删除目录 |
| 在设备上执行 | `POST /api/connections/{client_id}/scripts/run` | 按 Metadata 绑定参数，提交前台 Script 任务 |

Run API 要求 `script_name` 非空、`params` 为对象，并明确提供 `presentation` 为 `dialog` 或 `terminal`；Dialog 还需非空 `run_id`。它校验参数后创建普通 Web 命令任务，并非同步等待整个脚本运行完成的 HTTP 请求。直接通过 API 或新的前端按钮接入时，应复用这些字段与既有 `task_id`/WebSocket 结果处理，而不是绕开 Script 运行服务私自下发 Python 代码。

当前 Catalog 由 Server 文件系统决定。运行前刷新 Catalog 可获得最新 Metadata；上传和编辑不能保证已经打开的其他浏览器脚本表单自动更新，应根据界面生命周期重新获取数据。修改脚本名称后，旧的终端运行块或其他 Script 的 `scripts.run()` 引用也需要采用新的 Script Name。

### 故障定位的顺序

| 现象 | 首先检查 |
|---|---|
| 看得到脚本但不能 Run | 目标 Client 是否已选中；Metadata `platforms` 是否包含该 Client；脚本是否仍存在于 Catalog |
| 表单参数报错 | `params` 的真实类型、必填/default、数值范围、远程路径单选/多选、`path_list` 的行结构 |
| 提交成功后没有结果 | 前台任务是否仍运行；消息是否匹配 Client/Task；Dialog 的 `run_id` 是否一致 |
| SDK 调用 Server API 失败 | Client 是否连接、请求路径是否在 Client API 白名单中 |
| 子脚本调用失败 | `scripts:read`、Library 相对名称、递归调用限制以及被调脚本的实际参数 |
| 部分 Client 命令或 Interaction 不可用 | 当前是否有 Client Session Token、前台命令和对应 Web Task |
| 无法取消长时间脚本 | In-process 不支持任意强制中断；Subprocess 的取消也取决于进程控制和清理完成 |
| 输出不是 JSON 表格 | stdout 是否是单一合法 JSON，是否混入进度文本、日志或非 JSON 的 Python 表示 |
| 上传文件后找不到 | Artifact 类型、返回的 `artifact_id`、Client/Command 关联及 Artifact 当前可用性 |

扩展 Script 能力时，按职责接入 Library 管理、Metadata 表单、执行任务、SDK、授权或专门的文件、监控、Job 服务。这样能保持 Script 的一次性任务语义清晰，也便于沿着真实错误来源排查。


## Server `script` 一级命令（统一入口）

`script` / `script list` 默认每行输出一个 Server Script 相对路径；`script list --format table` 输出包含 `name`、`display_name`、`description` 和 `params`（仅参数名数组）的表格。`script list --json`、`script list --format json` 返回相同字段的完整结构化数组；可用 `--format records` 纵向查看长说明；`script view <name>` 和 `script view --name NAME` 返回 Server 上的脚本源码，严格限制在 Script 根目录。

`script exec <name> [--execution_mode MODE] [--output_mode MODE] -- --key VALUE ...` 使用与 Job 共用的 Server Schema Parser 得到参数对象，Script Library UI 直接提交结构化参数。动态参数值可以以 `--` 开头；也可以使用 `--key=--value` 明确表达该值。两端均按同一份 Script Metadata 规范化，再经 `control(domain=script, action=run)` 执行。Server 不注册独立的 `exec`、`run_script` 或 `script run` 入口，Client 不注册 Script 文本命令；脚本运行所需源码作为受控请求的 `payload.source` 提供。

### 终端列表的平台筛选

`script list` 与 `script list --json` 使用同一份扫描与 Metadata，按连接设备的 `os_alias` 和脚本 `SCRIPT_METADATA.platforms` 过滤；未声明或声明为空时不显示，**不根据目录名推断平台**。补全 `script exec <path>` 复用这份判断。`script exec` 及 Script Library UI 显式指定脚本时依旧能解析完整 Library 路径，不按列表结果限制；Script Library UI 的 Catalog/展示完全不参与这一过滤。

Web Script Library 的目录导航不承担平台筛选职责。左右两侧共用当前目录，右侧可以直接进入子文件夹或返回上级；左侧打开的文件夹图标表示当前目录，展开箭头独立表示树节点的展开状态。桌面与手机端的目录树默认开启，可以通过面包屑旁的侧栏开关随时隐藏或恢复。右侧目录卡片显示包含子目录在内的脚本数量；脚本卡片仅展示标题、标签和单行描述，完整路径与描述可通过悬停查看。顶部面包屑可直接跳转到任一祖先目录，右侧导航同步选中并展开左侧目录树。脚本搜索始终匹配当前目录及全部子目录中的脚本，搜索时仅展示匹配的脚本，左侧目录树与面包屑仍可导航；清空搜索后恢复当前目录的子文件夹和脚本列表。首次打开默认选中 `common` 目录（如存在），否则选中 `root`；关闭后重新打开同一设备时保留用户上次选择的目录，切换目标设备时回到默认目录。目录中的脚本平台适用性始终取决于各脚本的 `SCRIPT_METADATA.platforms`，与目录名无关。

## JSON Viewer 行操作回归脚本

Script Library 的 `test/misc/json_result_actions_probe` 无须准备数据或传入参数，执行后输出当前 Python Client 的 PID、检查时间与四个结果级 `view.actions`。**Run Child + Refresh** 通过正式命令 `script exec test/misc/json_result_actions_update` 运行第二份脚本，成功后重新运行原脚本并更新检查时间；**Run Child (No Refresh)** 执行第二份脚本但保留当前 Viewer，使用 Run Again 可主动刷新；**Run Child + Confirm** 在执行前确认，成功后刷新；**Inspect PID** 展示普通命令 Action。第二份 Script 直接输出成功信息、进程 PID 和执行时间，不需要参数，也不读写测试文件。两个 Script 均可直接从 Script Library 或 Terminal 启动；原 Script 的 JSON Viewer 适用于 inproc/subprocess_pipe 及 collect/stream。
