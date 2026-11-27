# File Transfer

RCH 将传输任务控制与文件字节处理分开。普通 Web/API 请求通过基础 HTTP 服务传递操作和元数据；大文件请求体由直接运行的 Flask/Werkzeug HTTP 服务处理；Python Client 的 File Transfer Mode 决定上传和下载如何分块、怎样报告字节进度以及是否能够响应取消。只有绑定了 Transfer 身份的操作才进入受管理的进度生命周期。

因此，传输链路上的“使用哪个端口”“采用哪个客户端策略”“Transfer Center 是否显示进度”是三个独立问题。浏览器向远程设备上传时还会经历 Server 暂存和 Client 拉取两个阶段，进度与取消状态必须按实际阶段解释。

## 文件数据与控制消息的完整链路

Server 默认提供三种网络入口：Socket 端口 `9999` 用于 Client 命令和心跳；HTTP 端口 `8085` 直接由 Flask/Werkzeug 处理 Web、API 和 HTTP 文件传输；WebSocket 端口 `8086` 处理 PTY、Screen 和浏览器实时通知。WS 端口是 `RCH_WEB_PORT + 1`，文件传输不使用 WS 端口；受管理的 TCP 模式复用主会话监听端口。

文件数据在项目中有几条主要路径：

```text
远程文件下载 / 预览 / 打包下载
    Browser --控制请求: 8085--> Server
    Server  --transfer_start: Socket--> Client
    Client  --HTTP POST 或独立 TCP--> Server Artifact
    Server  --API 响应 / 后续浏览器下载: 8085--> Browser

Remote Files 上传到设备
    Browser --创建 Transfer: 8085--> Server
    Browser --原始文件 POST: 8085--> Server 临时文件
    Server  --transfer_start: Socket--> Client
    Server  --HTTP GET 响应或独立 TCP--> Client 目标目录

已有 Artifact / Server 暂存文件下发
    Browser --控制请求: 8085--> Server
    Server  --transfer_start: Socket--> Client
    Server  --HTTP GET 响应或独立 TCP--> Client 目标目录
```

以上三条是受管理的典型流向。它们之外还有 Client 命令主动上传、Script / Job Artifact 上传、剪贴板和截图上传，以及浏览器直接下载 Artifact 等路径。**方向、传输端口、使用的客户端策略、是否创建 Transfer，必须分别判断**；不能因为都叫“上传”就推断它们走相同的执行链。

下载远程目录时，Client 可以先在本地创建 ZIP，再把 ZIP 当作普通文件上送；预览则可能先生成适合预览的临时图像。打包和预处理期间可能还不知道最终传输字节数，因此一开始不一定能显示确定的进度百分比。

## 同一个原生 Flask HTTP 服务上的文件通道

### 直接流式处理

`8085` 由 Flask/Werkzeug 提供。HTTP 文件上传、暂存下载、Artifact 下载与普通 Web API 都在这条原生 HTTP 通道上。浏览器原始上传按 `DEFAULT_HTTP_TRANSFER_BUFFER_SIZE` 分块读取 `request.stream`、直接写入暂存文件；普通文件接口沿用现有 Client HTTP Strategy 和分块下载实现。

`8086` 专用于 WebSocket，文件内容不经过该端口。两个服务共享 RCH Server 的业务对象，但有独立监听与连接资源；并发大文件任务的实际性能需要通过同环境吞吐和 API 延迟测试验收。

### 文件操作实际使用的 HTTP 入口

下表区分**控制/元数据请求**和**真正搬运文件字节的请求**。这里的「是否追踪」指能否生成 Transfer Center 所需的独立 `transfer_id`，不是说该功能没有自己的执行日志。

| 场景 | 8085 负责 | 文件字节实际走向 | Transfer Center |
| --- | --- | --- | --- |
| Remote Files 浏览、搜索、创建/删除/重命名、文本读取与保存 | 业务 API、命令调度和结构化内容 | 不走独立大文件 HTTP 搬运 | 不为这些操作自动创建 Transfer |
| Remote Files 下载单文件、下载 ZIP、生成预览 | 提交、等待和返回业务结果 | Python Client → HTTP 或独立 TCP → Server Artifact | 创建并追踪 |
| Remote Files 上传文件到设备 | 创建任务、获得 Token、提交后续任务 | Browser → 8085 暂存；Server 经 HTTP 或独立 TCP 下发 | 两阶段共享一条记录 |
| 已有 Artifact / Server 文件发送给 Client | 任务控制、元数据 | Server 经 HTTP 或独立 TCP 下发 | 受管理的下发操作可追踪 |
| 浏览器下载 Artifact、访问 Raw / Preview | Artifact 查询与 HTTP 文件响应 | Server → Browser 经 8085 | 该次浏览器下载不自动创建新 Transfer |
| 普通 Python Client 终端文件命令 | 原有命令 Socket 链路 | 传输服务 URL 通常指向 8085 | 只有显式绑定 `transfer_id` 时才有独立追踪 |
| Script SDK / Background Job 通用 Artifact 上传 | 上报、记录及文件关联 | 通用 Python API 的文件上传 URL 指向 8085 | 不会仅因使用 8085 就自动进入 Transfer Center |
| Python Client 剪贴板文件上报 | 控制与业务状态 | 上传 URL 指向 8085 | 不自动创建 Transfer |
| Web ScreenView 截图、浏览器上传 Artifact 或剪贴板内容 | Web 文件/业务 API | 仍可使用 8085 的上传入口 | 不自动创建 Transfer |

这里要特别区分两点。首先，Remote Files 里浏览器上传使用的是 **`POST /api/transfers/browser-upload` 创建任务（8085）+ 8085 的原始 HTTP Body 上传**，不是旧 Web multipart 文件上传入口。其次，Script / Job 通用上传即便走 8085，其 `requests files=...` 方式仍可能使用 multipart 缓存；**文件处理策略不是 `http_streaming` 策略的同义词**。

常用的路由边界如下：

| 服务 | 接口 | 用途 |
| --- | --- | --- |
| 8085 | `GET /api/transfers?limit=20&offset=0&machine_id=...` | 查询 Active 和 SQL 分页 Recent；`machine_id` 可选，通过会话历史匹配；返回 `recent_total` |
| 8085 | `POST /api/transfers/browser-upload` | 创建独立文件 Transfer，返回 Token、8085 同源目标地址；批次成员可携带 `batch_id` |
| 8085 | `POST /api/transfers/browser-upload-batch/start`、`/finalize` | Drag Upload 批次父记录的创建与提交结束；不改变单文件上传接口 |
| 8085 | `GET /api/transfers/batches/{batch_id}/items` | 按 Batch 查看子文件原生进度与错误 |
| 8085 | `POST /api/transfers/{transfer_id}/cancel` | 请求取消 |
| 8085 | `GET /api/transfers/{transfer_id}/browser-upload`、`PATCH /api/transfers/{transfer_id}/browser-upload` | 当前标签页查询浏览器上传状态、报告浏览器阶段异常或进度 |
| 8085 | `DELETE /api/transfers/{transfer_id}`、`DELETE /api/transfers/recent?machine_id=...` | 删除单条历史；按可选机器筛选条件清理终态记录，省略筛选则清理全部 |
| 8085 | `/api/connections/{client_id}/remote-files/...` | 远程文件的控制操作 |
| 8085 | `/api/artifacts/{artifact_id}/download`、`/raw`、`/preview` | 浏览器访问已生成的 Artifact |
| 8085 | `POST /api/transfers/browser-upload/{transfer_id}/content` | Browser 以 Token 上传原始文件字节 |
| 8085 | `POST /api/files/upload` | Client 上传并注册 Artifact |
| 8085 | `GET /api/upload-tmp/{temp_id}/{filename}` | Client 下载 Server 暂存文件 |

这几类 HTTP 文件接口与普通 Web API 均由 8085 的直接 Flask 服务处理。`FILE_TRANSFER_BASE_URL` 与 `UPLOAD_BASE_URL` 指向同一 Server HTTP 端口。浏览器上传地址从 Web 页面同源构造，不需要单独配置文件端口、跨源 CORS 或额外的文件 HTTP 监听。

## 客户端的字节处理机制

`FILE_TRANSFER_MODE` 是 Python Client 的运行时配置，默认 `http_streaming`。受管理的 Transfer 在启动时固定模式；运行中的配置变更只影响新任务。

| 行为 | `http_simple` | `http_streaming` | `tcp_streaming` |
| --- | --- | --- | --- |
| 文件字节承载 | HTTP multipart / 下载 | HTTP 流式 multipart / 下载 | 独立 TCP 数据连接 |
| 上传逐块进度 | 不支持 | 支持 | 支持 |
| 下载逐块进度 | 支持 | 支持 | 支持 |
| 运行中取消 | 不支持 | 协作取消 | 协作取消并关闭数据连接 |
| 上传大小限制 | Client 1 GiB 保护 | Server HTTP 请求上限 | Server 文件字节上限 |

TCP 模式仅作用于 Remote Files 和其他明确进入受管理 Transfer 的 Server 与 Client 间受支持的文件搬运，包括文件、ZIP、预览和文件下发。浏览器上传暂存、Artifact 下载仍使用原 HTTP 接口。内置 `download`、`acmd clipboard_read --download`、`screenshot`、`webcam_snap`，以及 Clipboard 图片 Get 和已暂存图片/文件 Send 同样进入受管理 Transfer。Script SDK、Job 及任意 URL HTTP 下载不改为 TCP；选择 `tcp_streaming` 时，原策略控制的 HTTP 调用仍使用 HTTP 流式策略。Go Client 支持 `http_streaming` 和 `tcp_streaming`；具体范围见 [Go Client File Transfers](go_file_transfers.md)。

每个 TCP 任务使用一条独立数据 Socket，Bind 由 Server 拨入 Client 的原监听端口，Reverse 由 Client 连接原 Server 监听端口，Bind 与 Reverse 均沿用主连接的 TCP 或 mTLS 传输与身份认证方式。数据连接使用现有 Session Token 与 Transfer ID 关联，不建立第二个 Client Session。主连接继续承载控制与进度。接收端按声明长度流式落盘并检查 SHA-256，成功提交文件或 Artifact 后才确认完成；取消、失败或断线清理未提交的临时文件。TCP 流不在任务中途回退为 HTTP。

### HTTP Simple 的上传缓存边界

HTTP Simple 上传使用 `requests` 的标准 multipart `files=...`。由于该路径可能在内存中缓存完整 multipart Body，代码明确拒绝**文件大小超过 1 GiB** 的 HTTP Simple 上传，并提示切换 `http_streaming`。该限制是 Client 策略上的保护，不是 8085 服务的全局上限。

HTTP Simple 下载使用 `stream=True` 和 `iter_content()`，一边收取数据块一边写到目标文件，所以没有等价的 1 GiB 下载限制。它可以上报下载字节进度，但不会提供正在执行的可靠取消支持。

### 流式读写与协作取消

HTTP Streaming 上传构造 multipart 的头部、文件内容及尾部，在 `read()` 中分段返回；每次读取文件会检查执行上下文的取消状态并调用进度回调。上传 Session 和流对象都注册了取消/清理处理器。下载同样以块为单位读取，在接收和写入过程中检查取消请求。

这使大文件上传不必把文件整体读入 Python 内存，并能根据已读取的文件字节提供进度；上传回调反映的是 Client 侧读取和交付给 HTTP 请求流的字节，不是远端持久化写盘后的逐块确认。不过，“收到取消请求”“网络连接关闭”“远程写入终止”和“任务最终变为 `cancelled`”仍是不同时间点。阻塞在底层网络 I/O 时，不应承诺 Cancel 按钮能够瞬间终止操作。

### 缓冲区及网络空闲约束

同一套传输策略还读取以下配置：

| 配置 | 当前默认值及意义 |
| --- | --- |
| `FILE_TRANSFER_MODE` | `http_streaming`；可选 `http_simple` / `http_streaming` / `tcp_streaming` |
| `HTTP_TRANSFER_BUFFER_SIZE` | 1 MiB，允许 64 KiB 至 16 MiB |

HTTP Simple 上传与下载使用内部固定的 Requests 网络超时：连接等待 15 秒、单次网络读取等待 120 秒（接收到数据后重新计时），不暴露运行时配置。HTTP Streaming 保持原有请求行为，通过执行上下文协作取消。Server 的通用 HTTP 上传请求体上限为 10 GiB；这个服务端上限与 HTTP Simple 的 1 GiB 客户端保护相互独立。

### 浏览器上传的接收配额与请求恢复

Remote 浏览器原始上传、受管理的本地文件暂存和 Shared 批量 multipart 接收共用 Server 进程内的接收额度。Remote 暂存直到专属临时目录清理才释放；Shared 在解析 multipart 之前占用额度并在请求文件关闭后释放。配额限制声明的接收字节与并发暂存，不等价于文件系统总容量或所有 Artifact 的存储配额。

| 环境变量 | 默认值 | 约束 |
| --- | --- | --- |
| `RCH_WEB_UPLOAD_STAGING_MAX_BYTES` | 20 GiB | 全局在途暂存预算（配置值为字节数） |
| `RCH_WEB_UPLOAD_STAGING_MAX_SLOTS` | 12 | 全局暂存/接收槽位 |
| `RCH_WEB_UPLOAD_STAGING_MAX_DEVICE_SLOTS` | 4 | 同一目标设备的 Remote 浏览器暂存槽位 |

同一活动批次的相同计划、同一标签页的相同文件注册身份可在控制请求响应丢失时恢复原注册；不同计划或参数不允许覆盖原身份。一次性上传 Token 不重复消费，未使用的凭据在后续查询、注册或消费时检查五分钟期限。浏览器原始文件请求响应不明确时查询原 Transfer 状态，不自动重发字节，也不覆盖 Server 已接手的终态。上述恢复仅适用于当前 Server 进程保留的运行状态，不提供跨重启续传或持久化重试。

## 上传、下发及中转阶段

### 远程文件任务和前台命令

Web 远程文件下载、预览、压缩下载和受管理的下发任务通过 Socket 发送 `transfer_start`，由 Client 的独立 `ClientTransferManager` 启动 Worker。该 Worker 具有独立执行上下文、HTTP 策略和取消处理，不绑定普通 `command_id`，因此**不需要占用 Shell-like 命令的前台执行槽直到文件传完**。Server 根据 `transfer_id` 等待任务最终状态，而不是从终端输出文本中猜测上传是否成功或解析 Artifact ID。

内置文件命令和 Clipboard Control 在原执行上下文内通过 `transfer_register` 登记文件传输，Server 确认请求仍有效后才允许搬运文件。它们不另开一个命令 Worker，保留命令输出、Activity 和原有剪贴板操作的生命周期。Transfer Center 记录每次文件搬运；取消该传输会请求取消所属命令或 Control。Clipboard Send 多文件逐项传输，全部成功后才进行原生剪贴板写入；单文件传输完成不代表整个剪贴板操作已完成。普通 Client API、Script 和 Job 的上传仍有自己的执行入口。

### 批次上传的持久化与终端呈现

Remote Files 单文件 **Upload** 保持原有任务和传输链路，任务显示为 `[Remote Upload] filename`，不再使用貌似命令的 `upload filename`。**Drag Upload** 选中一个普通文件时使用同一单文件上传链路；多文件或包含目录时采用独立的 Web 批次编排：Server 创建 `transfer_batches` 父记录，成员仍调用原有浏览器上传 Transfer API，并在 `transfer_records.batch_id` 持久化归属。父级记录批次身份、目标位置、预期文件数、提交结束和最终状态，并对应一次 Upload Task；每个文件仍有自己的 Transfer ID、SSE 进度、失败和取消能力。**不新增 Client 上传命令或数据协议**。

单文件和批次共用 Upload Task 生命周期；上传业务持有文件参数、队列及取消处理器，通用任务只负责执行事件和任务生命周期。一次批次由一个 Task 调度，逐个执行原生 Transfer，并最多缓存一个待下发文件。Terminal 使用任务原生完成事件。父任务持有规范化文件计划，成员注册时校验序号、文件名、目标、字节数及策略。仅无目录且全部预期成员结束时自动关闭；包含目录的批次必须确认目录准备结果，部分提交必须显式结束或由超时收尾；客户端断开、取消或浏览器提交超时也会关闭未完成批次；未确认的目录不能计为已完成。单文件和批次成员在长时间无传输状态更新时请求取消并按实际已知结果收尾，失败后应先核对目标再重试。父级结束必须等待已提交文件全部进入终态，只有这个结果会触发一条 `file_transfer_batch_finished` 汇总通知。`transfer_updated` 和 `file_transfer_lifecycle` 仍按文件发出，不会因批次汇总而丢失传输进度。

Transfer Center 的 Active / Recent 以单文件或 Batch 父级为行；Recent 的 SQL 分页按父记录计数，重启后仍能从 SQLite 还原批次。Batch 的 Details 打开独立的 Batch Progress 弹窗，Transfer Info 保留整体属性；File Transfers 列表实时展示各子文件相对路径、当前阶段、百分比、字节数及错误，并支持搜索及状态筛选；支持批次整体取消与成员原有取消入口。当前批次总体百分比按**已完成文件数量**计算，不能把 Browser→Server 和 Server→Client 两段重置的字节进度简单相加。同时显示已完成文件字节与已知计划总字节；计划缺失时仅显示已登记字节，不把部分登记的文件误作完整批次。即使某些文件未成功提交，父级也会保留不完整状态和已经完成的成员信息。

**数据库更新：**旧 `rch.db` 须在关闭 Server 后显式升级：为 `transfer_records` 新增 `batch_id` 字段，并新建 `transfer_batches` 及对应索引；Server 不在启动时自动修改既有表结构。具体 SQL 与字段以 `server/persistence/rch_database.py` 的当前规范 Schema 为准。运行在远端设备上的 `pyexec` 不能代替 Server 本地数据库迁移。

### 浏览器到远程设备的两段搬运

浏览器向远程设备传文件时，Server 先通过 8085 创建一条方向为 `server_to_client` 的 Transfer，返回 `transfer_id`、同源内容路径和一次性上传 Token。Browser 再使用 `XMLHttpRequest` 将文件的**原始字节流**直接 POST 给 8085；不需要让基础 Web API 先接收一整份 multipart 文件。

8085 验证并消费 Token 后，按约 1 MiB 的块大小读取请求体、写入 Server 临时文件，并约每 250 毫秒同步一次进度；收到全部字节还会检查是否与声明长度一致。Server 随后提交受管理的下发任务，通知 Client 从 8085 暂存下载端点拉取文件并保存至目标目录。

同一条 Transfer 会先后经历：

```text
uploading_to_server   Browser → Server，读取和写入原始文件
        ↓
preparing             文件暂存完成，准备目标设备下发
        ↓
transferring          Client 从 Server 拉取并写入本地
        ↓
completed             客户端完成下载并报告结果
```

开始第二段时，Server 会 `reset_progress()`：清零传输字节、速率和 ETA，重新设置阶段的总大小。**Transfer Center 的百分比显示当前阶段的进度**；多阶段传输在切换阶段后重新从零计算。 因此切换到下一阶段时进度条可以重新从零开始。

Client → Server 的路径也有 `preparing`、`staging`（上送文件字节）与 `finalizing`（确认 HTTP/Artifact 结果）等阶段。目录打包在准备阶段可能暂时没有确定的总字节数；上传完成后，Server 注册 Artifact，返回与该 Transfer 对应的 `artifact_id`。上传成功只代表文件已到达 Server；浏览器随后下载 Artifact 是另一次独立 HTTP 响应。

## Transfer Activity 与进度职责

Transfer Center 在内存中管理实时速度、进度和取消，并将传输起始与终态事实保存到 Server 的 `rch.db`；Activity Center 只为用户明确发起的上传/下载维护一条持久执行事实。Remote Browser / Remote File Picker 上传和 Remote Browser / Clipboard 下载均以真实 `transfer_id` 关联 Activity。Browser→Server 上传完成只是中间阶段；只有 Server→Client 写盘完成才将 Activity 标记成功。进度变化不重复写 Activity；失败、取消和重启后中断分别使用现有 `error`、`cancelled` 和 `interrupted` 状态。

终端 Server Builtin `upload` 在受管理 Transfer 创建时认领其原始历史 ID，不把 Transfer 内部请求或临时 URL 当作用户命令；终端 Client `download` 与 `screenshot` 一样保留普通 Command Activity，Artifact 继续沿用既有命令通道关联；不会额外创建 Transfer Activity 或虚构 `transfer_id`。预览、后台 Job/Script 中转和已生成 Artifact 的本地浏览器下载不自动进入 Transfer Activity。

## 传输状态与实时进度的建模

### 传输记录的字段和阶段

Transfer 是由 Server `TransferService` 管理的一份状态记录，不是新 HTTP 协议，也不承载文件字节。受管理任务创建时得到唯一 `transfer_id`；上传、下载、暂停取消的相关业务逻辑围绕这个 ID 更新状态。实际文件字节由所选 HTTP 模式或独立 TCP 数据连接传输。

记录包含设备标识、方向、文件名、源和目的路径、浏览器 `tab_id`、`state`、`stage`、文件大小、已完成字节、进度支持标志、取消支持标志、速率、ETA、关联 Artifact、错误信息和时间戳。典型记录可以简化为：

```json
{
  "transfer_id": "运行时生成的传输ID",
  "client_id": "目标设备连接ID",
  "direction": "server_to_client",
  "state": "running",
  "stage": "transferring",
  "total_bytes": 104857600,
  "transferred_bytes": 41943040,
  "percent": 40.0,
  "progress_supported": true,
  "cancel_supported": true,
  "speed_bytes_per_sec": 0,
  "eta_seconds": null,
  "artifact_id": ""
}
```

这里的速率和 ETA 只用于展示，示例中的 `0` 与 `null` 表示尚无可靠估计；状态、字节和支持标志才是 UI 行为的重要依据。

`state` 主要区别 `running`、`completed`、`failed`、`cancelled`；`stage` 进一步说明是正在浏览器上传、准备、上送 Server、下载至设备、完成确认还是取消中。实际显示可以保留 Stage 的原义，而不能把 `running` 直接翻译成“正在上传”：它也可能在压缩、暂存或等待其他阶段。

Web Remote Upload 的终端块由前台显示 `[Remote Upload]` 起始标题和执行结束状态；上传字节数、路径、传输阶段及实时进度在 Transfer 记录中查看。成功传输只产生执行终态，不再将暂存成功、完成提示、路径与大小额外写成终端输出行。CLI `upload` 仍通过同一传输终态生成一条简短的操作反馈；失败和取消保留各自的终态及错误说明。

### 从 HTTP / Socket 到 WebSocket 的进度传播

Python Client 的受管理任务在独立 Worker 或当前命令/Control 内调用进度回调，并通过**Socket 的 `transfer_update` 消息**回报 Server；状态信息不混在命令 stdout/stderr 中。对于 Browser → Server 第一段，进度由 Browser Upload 业务服务通过 `TransferService` 更新；HTTP 层仅接收令牌与原始流。浏览器上传服务管理一次性 Grant、批次幂等、暂存文件与提交收尾，上传任务服务接管已暂存文件。

Server 根据收到的进度字节数计算完成比例，对速率采用平滑计算，并在可用时推算 ETA；因此百分比是该阶段工作进度，而不是端到端文件完整性校验。进度上报通常做约 250 毫秒节流，完成点仍会被单独报告。发布 `transfer_updated` WebSocket 后，Web 订阅者刷新 Transfer Center；`file_transfer_lifecycle` 则提供开始、结束和失败等生命周期通知，二者服务不同目的。

传输完成通知默认提供 Open Transfers；当方向是 `client_to_server`、状态 `completed` 且关联了 `artifact_id` 时，还提供 Open Artifacts 与 Download（到浏览器）。它们分别打开现有 Artifact Dialog、调用现有下载地址，不新增 Transfer 任务；其他方向、取消、失败或未产生 Artifact 的通知保持原来的操作。通知的显示仍受 WebSocket 通知偏好控制。

`GET /api/transfers?limit=20&offset=0` 从 SQLite 每次只查询 20 条历史，返回 `recent_total`；后续使用 `offset=20/40/...` 加载更多，绝不是返回全量后在浏览器截取。可附加 `machine_id` 按连接历史关联的机器筛选。Active 仍来自内存并遵守当前标签页隔离，之后由 WebSocket 维持实时进度。Transfer Center 分为 **Active** 和 **Recent**：Active 显示文件名、方向、当前阶段、进度条、字节数、速度、ETA 和 Cancel；Recent 保存全部已完成、失败、取消或重启中断的传输，不做固定条数裁剪。列表仅显示文件名、方向和状态；每条的 More 菜单提供 Info（文件大小、完成时间、源与目标路径、错误及 Artifact 引用）和 Delete。成功的 `client_to_server` 传输若有 `artifact_id`，还提供 Preview 和 Download（浏览器下载），与传输完成 WebSocket 通知使用相同的资格条件；反方向上传不提供这两个操作。Clear Recent 默认手动清空全部历史；选择 Machine Filter 时只清理该设备关联会话的终态记录，其他设备及活动传输不受影响。前台受管理传输的 `Upload started` / `Download started` 等小 Toast 提供 `Open Transfers` 链接，直接打开现有 Transfer Center；这与 WebSocket 生命周期通知的按钮无关。Remote Files / Remote File Picker 的 `Upload started` 在浏览器向 Server 开始发送文件时出现，不再等待 Server 暂存完成；下载提示时机保持不变。

当 `progress_supported=false`，或者缺少有效 `total_bytes` 时，界面显示不确定进度而不是假造一个百分比。例如 HTTP Simple 上传可能正在正常运行但无法报告逐块上传字节；目录打包也可能尚未知道最终 ZIP 大小。此时应查看任务状态与已传输字节，而非依靠百分比判断。

### 任务记录与 Artifact 的不同生命周期

Transfer Center 使用 `rch.db` 的 `transfer_records` 保存简要历史事实：创建时插入起始状态，结束时更新最终状态、路径、大小、实际字节、时间、错误及 Artifact ID。中途进度、速度、ETA、取消控制和临时 `metadata` 仍只在内存中；不对每个进度分片写 SQLite。重启后，未完成的旧记录标为 `interrupted` 并记录结束时间；历史记录可在新浏览器标签页查看，但活动进度及 WebSocket 仍按原 `tab_id` 隔离。只有用户通过 Delete/Clear Recent 手动移除记录；删除记录不影响 Artifact 或目标文件。

Artifact 文件及其注册记录是另一条存储生命周期。清理最近 Transfer 只清理进度记录，**不自动删除已生成的 Artifact，也不会删除目标设备上的文件**。同样，直接在浏览器下载 Artifact 并不自动创建一条新的 Transfer 记录。

## 取消请求的传递及访问约束

### 取消怎样抵达工作线程

Cancel 由 Web 请求发往 8085 的 `POST /api/transfers/{transfer_id}/cancel`。Server 首先核对任务仍为 Active，以及当前的 `cancel_supported`。如果任务已结束或策略明确不支持取消，请求会被拒绝；不能把按钮点击当作最终取消确认。

对浏览器上传到 Server 的第一段，Server 设置对应的取消事件，并将 Transfer 标为取消；8085 分块接收循环会检查该事件，停止后清理临时文件和上传运行状态。Server 接受取消后，发起上传的同一浏览器标签页还会中止对应的独立 XHR，使等待上传结果的界面及时恢复按钮，并保留取消终态（不再补报上传失败）。此时不需要向目标 Client 发送取消指令，因为 Client 尚未开始下载。

对 Client 正在执行的文件传输，Server 通过 Socket 下发 `transfer_cancel`；`ClientTransferManager` 向 Worker 的独立执行上下文或内置命令/Clipboard 的现有执行上下文请求取消。HTTP Streaming 通过取消检查和资源清理尝试中断 HTTP 请求，Worker 报告 `cancelled` 表示运行端处理完取消。Server 可以先显示 `cancelling` 阶段。

TCP 模式收到取消请求后，由 Client 的取消上下文中断数据连接；Server 等待主通道终态，重复取消请求不会提前结束任务。若取消发生在 Server 接收文件的最终登记之前，Server 停止提交并清理暂存文件；已进入不可逆提交的任务以实际提交结果为准。若 Artifact 已登记而 Transfer 终态持久化失败，Server 尝试撤销本次新建的 Artifact，不发布成功创建事件。

同一条浏览器两阶段任务在不同阶段可拥有不同能力：第一段由 Server 上传循环提供取消，第二段则取决于 Client 当前选择的 `http_simple`、`http_streaming` 或 `tcp_streaming`。Client 启动后会用实际策略更新 `cancel_supported`；HTTP Simple 模式下通常会关闭第二阶段的 Cancel。终态后的删除、Clear Recent 和取消正在运行的传输是三种不同操作。

### 任务接口及通道保护

Web 端的 `tab_id` 用于把正在运行的 Transfer 关联到发起的浏览器标签，并使 `transfer_updated` 等 WebSocket 消息可以按标签定向发送；已结束的持久历史在同一登录 Server 下跨标签页可见。它不是文件传输身份认证的替代品。Web 的控制 API 应由基础 Web 认证与授权层保护。

文件传输 HTTP 接口直接运行在 8085。浏览器原始文件上传通过创建任务时签发的一次性随机 Token 授权，并在 `X-RCH-Transfer-Token` 中提交；Client Artifact 上传及暂存文件下载继续使用既有权限与传输校验机制。默认 8086 仅接受 WebSocket 连接，需向浏览器开放；Client 文件流量无需连接 8086。

### 部署与异常定位

**正常的大文件 Remote Files 上传**，优先确保浏览器到 Server 8085 以及HTTP 模式下目标 Client 到 Server 8085 可达；TCP 模式下原 TCP 或 mTLS 监听端口可达；浏览器端上传成功只代表第一阶段暂存完成，仍需观察后续 Client 下载阶段。若文件很大且需要实时上传字节进度或可取消性，应检查 Client 的 `FILE_TRANSFER_MODE` 是否设置为 `http_streaming` 或 `tcp_streaming`。`http_simple` 不提供流式上传和取消能力。

| 现象 | 核查重点 |
| --- | --- |
| 页面及目录列表正常，但文件上传失败 | 检查 HTTP 上传路径、大小限制、一次性 Grant、Server 暂存目录权限与 Client 所用的 8085 Base URL |
| Browser 上传成功，但文件没出现在设备上 | 继续检查 Transfer 的 `preparing` / `transferring` 阶段、Client 连接、目标目录与磁盘权限 |
| 大于 1 GiB 的 Client 上传被拒绝 | 检查 HTTP Simple 的客户端保护；这不表示 Server 只有 1 GiB 容量 |
| 上传没有百分比，下载却能显示 | HTTP Simple 上传无逐块进度；HTTP Simple 下载使用流式接收可回报进度 |
| Cancel 不可点击 | 任务当前阶段可能声明 `cancel_supported=false`；检查 Client 策略和具体阶段 |
| 点击 Cancel 后尚未完全停止 | 取消请求与 Worker 最终退出不同步，等待 `cancelled` 或最终错误状态 |
| Transfer 百分比从头开始 | Browser 上传结束后进入 Client 下载，进度按新阶段重置 |
| ZIP 创建阶段没有进度百分比 | 压缩还在准备最终文件，总长度暂不可用 |
| Transfer Center 记录消失 | 检查是否被手动删除或清空；传输历史持久化在 `rch.db`，Server 重启不应删除记录，也不影响已保存 Artifact |
| 某次 Script、纯文本 Clipboard 或浏览器 Artifact 下载没有 Transfer 记录 | 并非所有文件 HTTP 请求都会建立 `transfer_id` |

需要把性能调优、文件传输管理和文件资产管理作为三个独立问题看待。直接 Flask/Werkzeug 的分块数据通道避开 ASGI/WSGI 桥接；`http_streaming` 改变 Python Client 的字节处理和中断能力；Transfer Center 提供可观察性与控制；Artifact 负责文件保存、预览和后续下载。**没有任何一层能够单独替代另外三层。**

远程文件浏览、编辑和路径管理的业务细节见 `remote_files.md`；Artifact 的生成与展示则遵循各自功能模块的文档。这里专注文件字节传输、进度及取消，不把每个历史命令或已有模块列成清单。

### `download`

`download <file>` 是 Client 的终端文件上传（设备到 Server Artifact），不是 Remote Files 的文件浏览命令。无参数立即返回 `Usage: download <file>`，不会把空路径解析成当前工作目录；目录输入仍返回明确的 `Not a file` 错误。该命令执行过程中发送的正常 Socket 结果应与已登记的命令 ID 关联，不得因为极快返回而意外显示成 `[Background]`。是否能取消正在进行的 HTTP 字节传输仍取决于 `FILE_TRANSFER_MODE`；不能将普通任务的取消能力等同于传输取消。
