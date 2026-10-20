# Background Jobs

Background Job 的主要对象是一次可追踪的后台运行实例，而不只是保存于 Server 的 Python 模块。模块 Metadata 决定能在哪个平台、以何种模式、使用什么参数启动；Client 创建独立的 Job Runtime；Server 持久化运行状态、消息及文件关联，使 Web 能够在任务结束后继续查看执行过程。

运行实例可能驻留在 Client 进程的线程中，也可能运行于独立 Python 子进程。两条路径具有不同的上下文可用性、停止能力和异常边界。编写 Job 时，应首先把状态报告、资源释放与取消检查作为执行契约的一部分，而不是从某个现有任务照搬循环代码。

## 后台运行的控制平面

一个 Job 从配置到可见运行状态，经过 Server 的模块目录、Client 执行环境和独立的 HTTP 上报通道：

```text
Web Background Jobs / Server 命令
    │ 选择 Module、参数、execution_mode
    ▼
Server · Job Catalog / Background Job Service
    │ 发送专用 job_control 协议消息（不是 Client 命令文本）
    ▼
Client · 下载 Job Python 内容、写入临时目录
    │ 静态解析 Metadata、规范化参数、检查执行模式
    ▼
Client JobManager
    ├── inproc：Client 内的 Job Thread
    └── subprocess：独立 Python 子进程 + 监视线程
    │
    ├── Job status / message → HTTP /api/background-jobs/report
    └── 生成文件 → HTTP Upload → Artifact 关联报告
    ▼
Server · SQLite Job History + WebEventBus
    ▼
Web Jobs / Job Detail · 状态、消息、文件
```

启动或停止控制经由独立的 `job_control` 消息类型进入 Client 的受管理执行路径，但 **Job 开始运行后不持续占用前台命令槽**。长时间运行的任务自行上报消息和状态；Server 通过 SQLite 保存执行记录，再发布 SSE 事件供浏览器刷新。

模块存放在 Server 的 Job 资源目录中。Web 可以创建、编辑、上传或删除 Python 模块；Client 启动时按需从 Server 取得该模块内容，而不是要求用户事先把所有 Job 安装到目标设备上。不过，**Python 第三方依赖仍必须在目标运行环境中可用**，下载模块并不等于自动安装其依赖。

这里涉及三个不同身份：`job_key` 表示具体的 Job 模块名；`job_id` 是每次启动生成的独立 UUID；`client_id` 表示运行这次 Job 的 Client 连接。Server 历史还记录 `machine_id`，因此同一设备重新连接后可以继续查询已保存的 Job 记录。

## 模块声明与运行参数

Job 使用 `JOB_METADATA` 描述用途、支持平台、参数以及执行模式。Catalog 从 Python 源文本中**静态提取 Metadata**，不需要为了展示模块列表而先执行该模块。当前解析器支持模块级 Metadata，也支持 Job 类中声明 Metadata。

Metadata 为静态声明；模块的业务名称、展示名称、适用平台与参数约束均由声明值决定。这些字段会由 Catalog 正规化后交给 Web 进行展示和输入校验，无需为每个任务额外维护一套表单或帮助文本。

`name` 是模块在业务层的标识，`display_name` 和 `description` 用于界面；`platforms` 决定哪些操作系统允许显示为可运行。平台别名在解析时会规范化，例如 `darwin` 对应 `mac`、`windows` 对应 `win`，也支持 `*` 表示不限制平台。平台匹配不负责验证所有运行库或操作系统权限是否具备。

### 字段声明与类型边界

`params` 使用与 Script、External Tool 共享的 Parameter Schema。常见字段包括 `name`、`type`、`label`、`description`、`required`、`default`、`min`、`max` 和下拉选项 `options`。参数类型覆盖 `string`、`textarea`、`integer`、`number`、`boolean`、`select`，也包括 `remote_file`、`remote_files`、`remote_folder`、`remote_folders`。

Web 的 Start 弹窗按 Metadata 生成表单。对于 Remote File / Folder 类型，界面可以调用远程文件选择器；多路径参数最终必须使用 JSON 数组表示，例如 `['/a.txt', '/b.txt']` 对应的实际 JSON 数组，而不是逗号分隔字符串。Client 在运行前再次按 Schema 规范化和校验参数，包括必填项、数字类型、取值范围、Select 选项等。额外提供的参数键也会被保留，因此新 Job 不应假定只有 Schema 声明过的键才可能传入。

运行参数在绑定上下文后由 `get_job_param(name, default)` 读取。

`on_context_bound()` 在 `job_metadata`、`job_params`、Client 身份、执行模式等上下文已绑定后调用。不要在 `__init__()` 中依赖这些上下文字段已经可用。完整字段与类型语义参见 [Parameter Schema](parameter_schema.md)。

### 执行模式协商

`execution.default` 是模块默认模式，`execution.allowed` 是可选模式的硬限制。可用值是 `inproc` 与 `subprocess`。未声明执行限制时，当前默认模式为 `inproc`，两种模式都可被允许；声明只允许 `subprocess` 时，Web 不能再选 `inproc`，Client 也会拒绝不符合限制的请求。

推荐依赖完整 Client Runtime 的 Job 明确允许 `inproc`；不需要这些内部对象的独立任务可以考虑 `subprocess`。模式不是简单的性能选项，选错可能导致运行时对象不可用。

## 进程内和独立进程两条执行链

两种模式都运行 Python Job，但隔离程度与停止能力不同。

| 方面 | `inproc` | `subprocess` |
|---|---|---|
| Job 运行位置 | Client 进程内的线程 | 独立 Python 子进程 |
| 上下文 | 可以访问完整 Client Runtime | 只有有限的代理信息和 SDK 上下文 |
| 出错影响 | 异常或阻塞可能影响 Client | 与 Client 进程有一定隔离 |
| 正常停止 | 调用 `stop()` 并设置 `stop_event` | 向子进程标准输入发送停止命令 |
| 无法协作退出 | 不能安全强杀单个 Python 线程 | 超时后可终止进程或进程树 |
| 常见用途 | 需要 Client 内部管理器的监听任务 | 独立监控、扫描、计算、文件处理 |

### 共享进程中的任务运行

Client 创建 Job 实例后，绑定 Server Socket、命令 ID、参数和身份信息；执行线程进入 SDK 上下文并调用 `run()`。Job 可以直接访问它所绑定的 Client 对象，例如部分既有监听任务会使用 Client Runtime 中的管理器。

停止时，管理器调用 Job 的 `stop()`。Job 基类实现 `request_stop()`，会设置 `stop_event`，并在适当情况下上报 `stopping`。是否能够及时退出，最终取决于 Job 自己是否在等待、轮询或阻塞处检查停止条件。**管理器不会、也不能安全地强杀一个仍在运行的 Python 线程**。

当前 in-process 的通用线程包装会将 `run()` 中未捕获的普通 Python 异常、`SystemExit`（包括 `sys.exit(0)`）及 `KeyboardInterrupt` 转为该 Job 的 `error` 状态和失败消息，并设置停止标记；不会让这些异常继续穿透到 Client 生命周期。模块导入、实例初始化和上下文绑定阶段若出现上述异常，则会转换为启动失败，由原有命令错误路径返回。正常完成的 Job 仍由自身执行 `mark_stopped()`；出现业务错误时仍应在 `finally` 中释放文件、句柄或监听资源，且不要在上报失败后无条件调用 `mark_stopped()` 覆盖错误状态。上述保护不提供进程级隔离：`os._exit()`、原生崩溃或致命信号仍可能终止 Client，必要时选择 `subprocess` 并确认 Job 使用的 API 可在子进程中运行。

### 进程隔离中的工作进程

Client 将 Job 模块位置、`job_id`、`job_key`、参数、`client_id`、`command_id` 等信息写入临时 JSON 上下文文件，再用当前 Python 解释器启动专门的 Job Runner。子进程重新加载模块、创建实例、绑定有限的 Server 代理，并安装 Script SDK 上下文。

此模式仍可使用 `send_to_server()`、HTTP 上传和 `events.emit()` 等不依赖完整 Client Runtime 的能力；但不能假设 `self.server.runtime` 是一个可直接访问内部管理器的对象。依赖它的 Job 应限制为 `inproc`，或先改为独立接口。

Subprocess 的 Stop 分三个阶段：首先通过标准输入发送 `stop`，让 Job 运行 `stop()`；约 **3 秒**未退出则发送进程终止信号；再等待约 **2 秒**后仍未退出则强制终止进程树。Windows 与 POSIX 的实际信号处理有所不同。父进程断开子进程的标准输入时，Runner 也会尝试静默请求停止，避免无主 Job 长期残留。

子进程还会由监视线程收集退出码并上报最终状态。正常退出或已请求停止时可报告 `stopped`；异常退出则报告 `error`。子进程在加载模块、初始化实例、绑定上下文或运行 `run()` 时触发 `SystemExit`、`KeyboardInterrupt`（包括 `sys.exit(0)`），也按失败报告并返回非零退出码；已进入运行状态的任务不会再因异常被 `mark_stopped()` 覆盖错误终态。不能把 Web 已经显示 **Stop request sent** 理解为操作系统里的线程或进程已终止。

## Job 的实现约定

Job 类继承抽象基类 `Job` 并实现 `run()`。运行上下文由管理器绑定；`on_context_bound()` 用于接收绑定后的参数和环境；`stop()` 可以使用基类的 `request_stop()`，也可以在处理自身资源时扩展行为。框架不要求任务一直运行：完成条件达到后可以正常上报结束并退出。

在 `run()` 进入有效工作状态后，调用 `mark_running()` 更新生命周期；需要向管理界面留下可追踪信息时，用 `send_to_server(status, message, eof=0)` 添加消息。处理完成时，调用 `mark_stopped()` 上报终态。`is_running` 和 `stop_event` 既是本地协作状态，也是开发者设计循环与等待方式时需要考虑的信号；遇到取消时，阻塞等待应尽量能被停止事件唤醒。

应把**状态**、**消息**、**文件**和**业务事件**分开使用。`mark_running()` 等方法更新运行状态；`send_to_server()` 写 Job 消息历史；`upload_file_via_http()` 上传文件并在获得 Artifact 信息后报告关联；`events.emit()` 向 Device Event 管线发送结构化业务事件。后两者和 Job 文字输出不相互替代，业务事件协议详见 [Device Event Emit](event_emit.md)。

错误处理也属于 Job 的实现契约。需要让 Server 感知失败时，应明确报告 `error`，并在 `finally` 中清理打开的文件、句柄、监听器或子任务；不要在错误后无条件调用 `mark_stopped()`，以免覆盖失败状态。是否在上报失败后继续抛出异常，应依据选择的执行模式及实际终态处理决定。每次启动都由管理器建立新实例，不应依赖 Job 类中的进程级单例来维持一次运行的状态。

## 模块目录和执行视图

在 **Modules** 中选择 Job，可以看到显示名称、说明、支持平台和参数。Web 支持搜索、平台过滤、New、Upload、Edit、Delete 以及 Start。Start 弹窗自动使用 Metadata 参数 Schema，允许选择 `inproc` / `subprocess`，并禁用模块未声明允许的模式；远程路径参数可使用文件选择器。

**删除 Module 与删除运行记录完全不同。** Module 的编辑和删除操作作用于 Server 上的 Python 文件；已经运行的 Job 历史保存在 Server 数据库，不会因为删除 Module 而自动消失。修改模块也不会把新代码热替换到已经运行中的线程或子进程。

在 **Jobs** 中可以查看已经产生的运行实例，列表显示状态、运行模式、运行时间、消息数和文件数等。Job Detail 展示实际参数、运行消息及关联 Artifact；还可以将详情中的消息保存为 `command_output` 类型、`job_output` 分类的 Artifact，供后续下载或查看。它导出的是 Job 消息记录，并不自动代表子进程 stdout/stderr 的完整抓取。

启动与 Stop 操作由 Server 向目标 Client 发送控制命令。启动接口返回的是本次控制操作的处理结果，真正的 Job 生命周期依赖 Client 后续状态上报；停止结果也只是停止请求已被接受，不能当作 Job 已同步退出。处于 `running` 或 `stopping` 的记录不允许直接 Delete，需要先停止并完成运行。

## 运行状态、消息与文件记录

Job 基类会将运行状态、消息和文件报告分成不同的事件：

| 报告类型 | 主要数据 | 作用 |
|---|---|---|
| `status` | `state`、`status`、`text` | 维护 `running`、`stopping`、`stopped`、`error` 等状态 |
| `message` | `status`、`text`、`eof` | 追加一条带时间和执行身份的消息 |
| `file` | `artifact_id` 等文件快照字段 | 关联 Job 产生的 Artifact |

`send_to_server()` 会把消息包装上 Job 名称、短 ID、线程信息及 `client_id` 后上报。`status` 整数用于消息状态，`eof` 表示对应输出片段是否结束；它们不是 Job 的生命周期字符串状态。Job 发送报告时使用 `POST /api/background-jobs/report`，默认 HTTP 超时 **10 秒**；若没有 Client ID 或上报请求出错，基类当前选择静默返回，因此“本地调用了 send_to_server”不能单独证明 Server 已经存入该条消息。

Server 接收报告后，依据 `job_id` 保存 Job 实例、消息及文件关联，主要数据表为 `background_jobs`、`background_job_messages`、`background_job_files`。持久化后发布 `background_job_status`、`background_job_message`、`background_job_file` 等 WebEventBus 事件。另有 `background_job_lifecycle` 用于若干关键终态和启动状态的通知，不能把每次消息追加都当作生命周期事件。

每次新启动都会创建新的 `job_id`，而同一 Client 的活跃运行实例按 `job_key` 管理。当前代码会阻止同一个 Client 同时再启动相同 Job Key 的另一个活跃实例；已结束的历史记录则可以多次保留。Job 的查询依托 `machine_id` 识别持久设备，并记录每次对应的 `client_id`，所以设备重新连接后历史仍可查询。

**持久化的是 Job 历史，不是运行中的 Python 线程或进程。** Server 启动存储层时会把数据库里仍处于 `running` 或 `stopping` 的记录标记为 `interrupted`；它不会重建中断的运行环境。Client 断线时会静默请求停止本地 Job，因此也不应期待断线后无限期保留原任务运行。

删除一条已结束的 Job 记录主要影响该 Job 的数据库记录、消息及关联关系，不等于自动删除 Server 上的 Artifact 原始文件。Artifact 是否能预览或下载，还取决于它当前是否存在且可访问。

## 运行控制接口与清理

Job 的模块管理、执行查询和运行控制分属不同操作。模块目录与源码下载、保存和删除使用 `/api/jobs/...`；连接下的 Catalog、启动、停止、运行历史和详情通过 `/api/connections/{client_id}/background-jobs/...`；实际运行报告交给 `/api/background-jobs/report`。这些接口的参数分别使用模块名称、连接 ID、`job_key` 或 `job_id`，不能互换。

启动请求的核心字段是 `job_name`、`params` 和 `execution_mode`，停止操作则根据模块运行标识请求目标 Client 停止。在 Web Start API 中，未传 `execution_mode` 时当前路由使用 `inproc`；如果模块只允许 `subprocess`，API 调用方应明确传入该模式。终端启动路径会依据 Job Metadata 解析默认执行模式，因此两种入口的默认行为不可简单视为相同。

终端的 Job 用户入口统一由 **Server Builtin `job`** 提供，不再通过 Client 公开的 `start_job`、`stop_job`、`jobs`、`jobs_ps`、`job_status`、`stop_all_jobs` 命令方法执行。这些旧方法已经移除，Client Manifest/Help 不再列出它们；Client 仍使用 `JobManager` 来执行、停止和上报运行状态。Server Web Job API 使用同一个内部 `job_control` 消息类型，而非旧 Client 命令文本。

| 命令 | 执行位置与语义 |
|---|---|
| `job` / `job list` | Server 查询 Job Catalog，不联系 Client |
| `job start <name> [--mode inproc\|subprocess] [--params '{"key":"value"}']` | Server 验证名称、Metadata 模式限制；Client 下载 Job 并启动运行 |
| `job ps` | Server 向 Client 询问当前运行实例 |
| `job status <name>` | Client 查询 `JobManager` 当前状态 |
| `job stop <name>` | Client 发送停止请求，最终状态仍依赖 Job 本身上报 |
| `job stop-all` | Client 向当前所有运行 Job 发停止请求 |

Server Builtin `job` 的命令候选来自 `SERVER_COMMAND_REGISTRY`，不纳入 Client 命令 Manifest。Job 的执行/控制属于内部请求，不在首批 Command/Alias/Script Activity Center 记录范围内。需要区分 HTTP 请求已接受、前台控制命令已完成和后台 Job 最终状态三个时点。

### 停止请求与异常清理

| 现象 | 应检查的内容 |
|---|---|
| Web 显示 Job 不支持当前设备 | Metadata `platforms` 与当前 Client 平台是否匹配 |
| 启动返回不支持执行模式 | `execution.allowed` 是否包含实际提交的模式，特别是 API 默认 `inproc` |
| `job start` 找不到模块 | Server Catalog 中是否存在该 Job，模块名与请求是否一致 |
| Job 启动后没有消息 | Job 是否调用上报方法、Client 身份是否有效、HTTP 报告是否成功 |
| Job 使用 Subprocess 时访问 Runtime 失败 | 子进程只有有限的 `server` 代理，不能直接访问完整 Client Runtime |
| In-process 的 Stop 很慢 | Job 是否使用长时间阻塞或 `time.sleep()`，有没有及时检查 `stop_event` |
| Subprocess 的 Stop 没有立即完成 | 先协作等待，超时后才逐步终止进程 |
| Server 重启后记录显示 `interrupted` | 数据库保存了历史，不会重建旧运行线程或子进程 |
| Job 文件无法预览或下载 | Artifact 是否依然存在且有有效访问路径 |
| Job Detail 的消息不等于完整 stdout/stderr | Job 记录来自主动的 HTTP 消息上报，而非通用进程输出转储 |

开发 Job 时应明确资源生命周期：启动后什么时候上报 `running`，何时检查停止事件，异常怎样上报，文件和句柄在 `finally` 中如何释放。对于周期性任务，优先用可被 `stop_event` 打断的等待方式；对于一次性长任务，扫描或处理循环也应有取消检查。错误状态与停止状态的最终上报顺序应一致，避免已经报告失败却又被无条件 `mark_stopped()` 覆盖。

Subprocess 只能隔离 Python 任务进程，不能替代操作系统访问控制或自动安装缺失依赖。Job 的动态 Python 模块来自 Server，能在 Client 上执行实际代码，因此编辑、上传和运行权限应与项目的 Web 管理和部署信任边界一起考虑。当前 `/api/background-jobs/report` 允许匿名访问，Server 会据报告内容建立或更新 Job 记录；该路由没有强制把上报方的 `client_id` 与独立身份凭据绑定，部署时应限制不可信网络访问，不宜把请求自带的身份字段当成已完成的强身份认证。

如需细化参数校验、事件通知或 Artifact/JSON 展示，分别参考 [Parameter Schema](parameter_schema.md)、[Device Event Emit](event_emit.md)、[SSE Notifications](sse_notifications.md) 与 [Structured Command Output](structured_output.md)。

### 终端 Job 列表范围

`job`、`job list` 和 `job list --json` 只展示 Metadata `platforms` 对当前设备适用的资源；没写 `platforms` 或声明为空时不显示在终端 Job 列表及补全中，不再读取目录名推断平台。`job start` 的名称补全复用相同的过滤。它只控制 Server 终端命令目录，不收窄 Background Jobs Web 管理 UI Catalog，也不修改 Client 的 JobManager 执行协议。
