# File Transfer

RCH 将传输任务控制与文件字节处理分开。普通 Web/API 请求通过基础 HTTP 服务传递操作和元数据；独立传输服务面向较大的文件 Body；Python Client 的 HTTP Strategy 决定上传和下载如何分块、怎样报告字节进度以及是否能够响应取消。只有绑定了 Transfer 身份的操作才进入受管理的进度生命周期。

因此，传输链路上的“使用哪个端口”“采用哪个客户端策略”“Transfer Center 是否显示进度”是三个独立问题。浏览器向远程设备上传时还会经历 Server 暂存和 Client 拉取两个阶段，进度与取消状态必须按实际阶段解释。

## 文件数据与控制消息的完整链路

Server 默认提供三种网络入口：Socket 端口 `9999` 用于 Client 控制消息与状态回报，Web 端口 `8085` 用于浏览器、业务 API 和 Artifact 访问，文件端口 `8086` 用于独立 HTTP 传输。这里的端口是默认值而非硬编码协议；文件端口总是 `RCH_WEB_PORT + 1`，且启动时会检查它与 Socket 端口有无冲突。

文件数据在项目中有几条主要路径：

```text
远程文件下载 / 预览 / 打包下载
    Browser --控制请求: 8085--> Server
    Server  --transfer_start: Socket--> Client
    Client  --文件 POST: 8086--> Server Artifact
    Server  --API 响应 / 后续浏览器下载: 8085--> Browser

Remote Files 上传到设备
    Browser --创建 Transfer: 8085--> Server
    Browser --原始文件 POST: 8086--> Server 临时文件
    Server  --transfer_start: Socket--> Client
    Client  --暂存文件 GET: 8086--> Client 目标目录

已有 Artifact / Server 暂存文件下发
    Browser --控制请求: 8085--> Server
    Server  --transfer_start: Socket--> Client
    Client  --文件 GET: 8086--> Client 目标目录
```

以上三条是受管理的典型流向。它们之外还有 Client 命令主动上传、Script / Job Artifact 上传、剪贴板和截图上传，以及浏览器直接下载 Artifact 等路径。**方向、传输端口、使用的客户端策略、是否创建 Transfer，必须分别判断**；不能因为都叫“上传”就推断它们走相同的执行链。

下载远程目录时，Client 可以先在本地创建 ZIP，再把 ZIP 当作普通文件上送；预览则可能先生成适合预览的临时图像。打包和预处理期间可能还不知道最终传输字节数，因此一开始不一定能显示确定的进度百分比。

## 基础 Web 服务与独立文件通道

### 为什么分离数据通道

`8085` 由 Uvicorn 提供 ASGI 服务，内部挂载 FastAPI 和 Flask 业务接口（通过 `WSGIMiddleware`）；它处理日常 UI、认证会话、命令调度、目录操作、任务查询以及浏览器对 Artifact 的访问。

`8086` 是由 Werkzeug 直接启动、线程化运行的独立 Flask 文件服务，不经过 `8085` 的 ASGI/WSGI 桥接。将大文件请求体从基础 Web 链路中分离，可以避免该包装层对大文件数据的额外处理；独立服务也针对浏览器分段上传采用流式读取与落盘。**这是实现上的隔离与优化目标，不是对吞吐速度或内存占用的无条件保证。**

8086 当前对外暴露三类文件入口：普通 Artifact multipart 上传、暂存文件下载，以及使用一次性 Token 的浏览器传输内容上传。8085 仍保留同名的普通上传与暂存下载兼容入口，不能认为所有文件路由已从 8085 删除。

### 文件操作实际使用的 HTTP 入口

下表区分**控制/元数据请求**和**真正搬运文件字节的请求**。这里的「是否追踪」指能否生成 Transfer Center 所需的独立 `transfer_id`，不是说该功能没有自己的执行日志。

| 场景 | 8085 负责 | 文件字节实际走向 | Transfer Center |
| --- | --- | --- | --- |
| Remote Files 浏览、搜索、创建/删除/重命名、文本读取与保存 | 业务 API、命令调度和结构化内容 | 不走独立大文件 HTTP 搬运 | 不为这些操作自动创建 Transfer |
| Remote Files 下载单文件、下载 ZIP、生成预览 | 提交、等待和返回业务结果 | Python Client → 8086 → Server Artifact | 创建并追踪 |
| Remote Files 上传文件到设备 | 创建任务、获得 Token、提交后续任务 | Browser → 8086 暂存；Client 从 8086 拉取 | 两阶段共享一条记录 |
| 已有 Artifact / Server 文件发送给 Client | 任务控制、元数据 | Client 从 8086 获取文件 | 受管理的下发操作可追踪 |
| 浏览器下载 Artifact、访问 Raw / Preview | Artifact 查询与 HTTP 文件响应 | Server → Browser 经 8085 | 该次浏览器下载不自动创建新 Transfer |
| 普通 Python Client 终端文件命令 | 原有命令 Socket 链路 | 传输服务 URL 通常指向 8086 | 只有显式绑定 `transfer_id` 时才有独立追踪 |
| Script SDK / Background Job 通用 Artifact 上传 | 上报、记录及文件关联 | 通用 Python API 的文件上传 URL 指向 8086 | 不会仅因使用 8086 就自动进入 Transfer Center |
| Python Client 剪贴板文件上报 | 控制与业务状态 | 上传 URL 指向 8086 | 不自动创建 Transfer |
| Web ScreenView 截图、浏览器上传 Artifact 或剪贴板内容 | Web 文件/业务 API | 仍可使用 8085 的上传入口 | 不自动创建 Transfer |

这里要特别区分两点。首先，Remote Files 里浏览器上传使用的是 **`POST /api/transfers/browser-upload` 创建任务（8085）+ 8086 的原始 HTTP Body 上传**，不是旧 Web multipart 文件上传入口。其次，Script / Job 通用上传即便走 8086，其 `requests files=...` 方式仍可能使用 multipart 缓存；**文件端口不是 `cancelable` 策略的同义词**。

常用的路由边界如下：

| 服务 | 接口 | 用途 |
| --- | --- | --- |
| 8085 | `GET /api/transfers` | 查询 Active / Recent |
| 8085 | `POST /api/transfers/browser-upload` | 创建浏览器上传任务并返回 Token、8086 目标地址 |
| 8085 | `POST /api/transfers/{transfer_id}/cancel` | 请求取消 |
| 8085 | `PATCH /api/transfers/{transfer_id}/browser-upload` | 浏览器阶段异常或进度更新 |
| 8085 | `DELETE /api/transfers/{transfer_id}`、`DELETE /api/transfers/recent` | 删除或清理最近记录 |
| 8085 | `/api/connections/{client_id}/remote-files/...` | 远程文件的控制操作 |
| 8085 | `/api/artifacts/{artifact_id}/download`、`/raw`、`/preview` | 浏览器访问已生成的 Artifact |
| 8086 | `POST /api/transfers/browser-upload/{transfer_id}/content` | Browser 以 Token 上传原始文件字节 |
| 8086 | `POST /api/files/upload` | Client 上传并注册 Artifact |
| 8086 | `GET /api/upload-tmp/{temp_id}/{filename}` | Client 下载 Server 暂存文件 |

8085 还保留 `/api/files/upload`、`/api/upload-tmp/...` 兼容路由，不能仅凭 URL 路径判断请求实际到达哪个端口；必须结合发起请求时构造的 Base URL。Python Client 的普通 API Base URL 与 `FILE_TRANSFER_BASE_URL` 分开配置。对相对文件传输路径，后者指向 Web 端口加一；若调用方传入的是完整 HTTP URL，则按该 URL 使用，不强制改写端口。

部署时仅允许访问 8085 并不等于文件操作可用：使用 8086 的 Browser 和 Client 都需要能连接这一额外端口。浏览器上传通过当前页面 URL 替换端口构造 8086 地址，因此反向代理、TLS、跨域及防火墙配置也必须覆盖这条路径。

## 客户端的字节处理机制

`HTTP_TRANSFER_MODE` 是 Python Client 的运行时配置，当前源码默认值为 `legacy`；运行时配置可以覆盖默认值。代码中的正式拼写是 **`cancelable`**，不是 `cancellable`。策略由 HTTP File Transfer Service 选择，负责改变**上传/下载的客户端数据处理方式**，不会让 8085 自动升级为 8086，也不会让所有使用 8086 的调用都自动支持取消。

| 行为 | `legacy` | `cancelable` |
| --- | --- | --- |
| 上传请求体 | `requests.post(files=..., data=...)` | 自定义 multipart 流，逐块读取文件 |
| 大文件上传内存 | multipart 构造可能缓存完整请求体 | 不要求将完整文件加载进内存 |
| 上传字节进度 | 不提供逐块进度回调 | 提供逐块进度回调 |
| 下载 | `stream=True`、`iter_content()` 写盘 | 流式下载并检查取消 |
| 下载进度 | 支持按收到的字节更新 | 支持按收到的字节更新 |
| 运行中取消 | 不支持 | 通过执行上下文协作取消并清理网络资源 |
| 适用场景 | 兼容和实现简单 | 尤其适合大文件上传及需要取消的任务 |

### 兼容模式的上传缓存边界

Legacy 上传使用 `requests` 的标准 multipart `files=...`。由于该路径可能在内存中缓存完整 multipart Body，代码明确拒绝**文件大小超过 1 GiB** 的 Legacy 上传，并提示切换 `cancelable`。该限制是 Client 策略上的保护，不是 8086 服务的全局上限。

Legacy 下载使用 `stream=True` 和 `iter_content()`，一边收取数据块一边写到目标文件，所以没有等价的 1 GiB 下载限制。它可以上报下载字节进度，但不会提供正在执行的可靠取消支持。

### 流式读写与协作取消

Cancelable 上传构造 multipart 的头部、文件内容及尾部，在 `read()` 中分段返回；每次读取文件会检查执行上下文的取消状态并调用进度回调。上传 Session 和流对象都注册了取消/清理处理器。下载同样以块为单位读取，在接收和写入过程中检查取消请求。

这使大文件上传不必把文件整体读入 Python 内存，并能根据已读取的文件字节提供进度；上传回调反映的是 Client 侧读取和交付给 HTTP 请求流的字节，不是远端持久化写盘后的逐块确认。不过，“收到取消请求”“网络连接关闭”“远程写入终止”和“任务最终变为 `cancelled`”仍是不同时间点。阻塞在底层网络 I/O 时，不应承诺 Cancel 按钮能够瞬间终止操作。

### 缓冲区及网络空闲约束

同一套传输策略还读取以下配置：

| 配置 | 当前默认值及意义 |
| --- | --- |
| `HTTP_TRANSFER_MODE` | `legacy`；可选 `legacy` / `cancelable` |
| `HTTP_TRANSFER_BUFFER_SIZE` | 1 MiB，允许 64 KiB 至 16 MiB |
| `HTTP_TRANSFER_IDLE_TIMEOUT_ENABLED` | `True` |
| `HTTP_TRANSFER_IDLE_TIMEOUT_SECONDS` | 21,600 秒，即 6 小时 |

Idle Timeout 用于网络读写长时间不推进的情况，**不是整个文件传输从开始到结束的总时长上限**。设置成更大的值并不解决无法访问 8086、权限不足或目标磁盘空间不足等问题。Server 的通用 HTTP 上传请求体上限为 10 GiB；这个服务端上限与 Legacy 的 1 GiB 客户端保护相互独立。

## 上传、下发及中转阶段

### 远程文件任务和前台命令

Web 远程文件下载、预览、压缩下载和受管理的下发任务通过 Socket 发送 `transfer_start`，由 Client 的独立 `ClientTransferManager` 启动 Worker。该 Worker 具有独立执行上下文、HTTP 策略和取消处理，不绑定普通 `command_id`，因此**不需要占用 Shell-like 命令的前台执行槽直到文件传完**。Server 根据 `transfer_id` 等待任务最终状态，而不是从终端输出文本中猜测上传是否成功或解析 Artifact ID。

与此相对，既有终端文件命令仍遵循自己的命令执行与输出机制，虽然也可以复用相同的 HTTP 传输服务。普通 Client API、Script 和 Job 的上传则有自己的执行入口：并非所有文件操作都会通过 `ClientTransferManager`。

### 浏览器到远程设备的两段搬运

浏览器向远程设备传文件时，Server 先通过 8085 创建一条方向为 `server_to_client` 的 Transfer，返回 `transfer_id`、8086 端口、内容路径和一次性上传 Token。Browser 再使用 `XMLHttpRequest` 将文件的**原始字节流**直接 POST 给 8086；不需要让基础 Web API 先接收一整份 multipart 文件。

8086 验证并消费 Token 后，按约 1 MiB 的块大小读取请求体、写入 Server 临时文件，并约每 250 毫秒同步一次进度；收到全部字节还会检查是否与声明长度一致。Server 随后提交受管理的下发任务，通知 Client 从 8086 暂存下载端点拉取文件并保存至目标目录。

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

开始第二段时，Server 会 `reset_progress()`：清零传输字节、速率和 ETA，重新设置阶段的总大小。**Transfer Center 的百分比是当前阶段的进度，不是浏览器上传与设备下载两段工作量的累计百分比。** 因此切换到下一阶段时进度条可以重新从零开始。

Client → Server 的路径也有 `preparing`、`staging`（上送文件字节）与 `finalizing`（确认 HTTP/Artifact 结果）等阶段。目录打包在准备阶段可能暂时没有确定的总字节数；上传完成后，Server 注册 Artifact，返回与该 Transfer 对应的 `artifact_id`。上传成功只代表文件已到达 Server；浏览器随后下载 Artifact 是另一次独立 HTTP 响应。

## Transfer Activity 与进度职责

Transfer Center 管理内存中的实时速度、进度、取消和最近任务；Activity Center 只为用户明确发起的上传/下载维护一条持久执行事实。Remote Browser / Remote File Picker 上传和 Remote Browser / Clipboard 下载均以真实 `transfer_id` 关联 Activity。Browser→Server 上传完成只是中间阶段；只有 Server→Client 写盘完成才将 Activity 标记成功。进度变化不重复写 Activity；失败、取消和重启后中断分别使用现有 `error`、`cancelled` 和 `interrupted` 状态。

终端 Server Builtin `upload` 在受管理 Transfer 创建时认领其原始历史 ID，不把内部 `receive_file` 或临时 URL 当作用户命令；终端 Client `download` 与 `screenshot` 一样保留普通 Command Activity，Artifact 继续沿用既有命令通道关联；不会额外创建 Transfer Activity 或虚构 `transfer_id`。预览、后台 Job/Script 中转和已生成 Artifact 的本地浏览器下载不自动进入 Transfer Activity。

## 传输状态与实时进度的建模

### 传输记录的字段和阶段

Transfer 是由 Server `TransferService` 管理的一份状态记录，不是新 HTTP 协议，也不承载文件字节。受管理任务创建时得到唯一 `transfer_id`；上传、下载、暂停取消的相关业务逻辑围绕这个 ID 更新状态。实际文件字节仍由各自的 HTTP 请求传输。

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

### 从 HTTP / Socket 到 SSE 的进度传播

Python Client 的受管理任务在 HTTP Worker 内调用进度回调，并通过**Socket 的 `transfer_update` 消息**回报 Server；状态信息不混在命令 stdout/stderr 中。对于 Browser → Server 第一段，进度由 8086 的文件接收循环直接更新 Server 的 `TransferService`，不经过 Client Socket。

Server 根据收到的进度字节数计算完成比例，对速率采用平滑计算，并在可用时推算 ETA；因此百分比是该阶段工作进度，而不是端到端文件完整性校验。进度上报通常做约 250 毫秒节流，完成点仍会被单独报告。发布 `transfer_updated` SSE 后，Web 订阅者刷新 Transfer Center；`file_transfer_lifecycle` 则提供开始、结束和失败等生命周期通知，二者服务不同目的。

`GET /api/transfers` 提供初始状态，之后由 SSE 维持实时更新。Web 的 Transfer Center 分为 **Active** 和 **Recent**：Active 显示文件、方向、当前阶段、进度条、已完成字节、速度、ETA 和 Cancel；Recent 显示已完成、失败或取消的任务，并允许删除记录或清空最近记录。

当 `progress_supported=false`，或者缺少有效 `total_bytes` 时，界面显示不确定进度而不是假造一个百分比。例如 Legacy 上传可能正在正常运行但无法报告逐块上传字节；目录打包也可能尚未知道最终 ZIP 大小。**没有百分比不等于任务没有执行。**

### 任务记录与 Artifact 的不同生命周期

当前 `TransferService` 使用 Server 内存字典管理 Active/Recent，不将传输记录持久化到 SQLite。终态记录最多保留最近 **50 条**，Server 重启不会从数据库恢复原 Transfer Center 列表。

Artifact 文件及其注册记录是另一条存储生命周期。清理最近 Transfer 只清理进度记录，**不自动删除已生成的 Artifact，也不会删除目标设备上的文件**。同样，直接在浏览器下载 Artifact 并不自动创建一条新的 Transfer 记录。

## 取消请求的传递及访问约束

### 取消怎样抵达工作线程

Cancel 由 Web 请求发往 8085 的 `POST /api/transfers/{transfer_id}/cancel`。Server 首先核对任务仍为 Active，以及当前的 `cancel_supported`。如果任务已结束或策略明确不支持取消，请求会被拒绝；不能把按钮点击当作最终取消确认。

对浏览器上传到 Server 的第一段，Server 设置对应的取消事件，并将 Transfer 标为取消；8086 分块接收循环会检查该事件，停止后清理临时文件和上传运行状态。此时不需要向目标 Client 发送取消指令，因为 Client 尚未开始下载。

对 Client 正在执行的文件传输，Server 通过 Socket 下发 `transfer_cancel`；`ClientTransferManager` 向 Worker 的独立执行上下文请求取消。Cancelable 策略通过取消检查和资源清理尝试中断 HTTP 请求，**实际 Worker 报告 `cancelled` 才代表运行端处理完取消**。Server 可以先显示 `cancelling` 阶段；这不等于任务已经结束。

同一条浏览器两阶段任务在不同阶段可拥有不同能力：第一段由 Server 上传循环提供取消，第二段则取决于 Client 当前选择的 `legacy` 或 `cancelable`。Client 启动后会用实际策略更新 `cancel_supported`；Legacy 模式下通常会关闭第二阶段的 Cancel。终态后的删除、Clear Recent 和取消正在运行的传输是三种不同操作。

### 任务接口及通道保护

Web 端的 `tab_id` 用于把 Transfer 关联到发起的浏览器标签，并使 `transfer_updated` 等 SSE 消息可以按标签定向发送。它不是文件传输身份认证的替代品。Web 的控制 API 应由基础 Web 认证与授权层保护。

8086 是一条独立的 HTTP 服务，不应假设它自动继承 8085 的会话鉴权。浏览器原始文件上传依靠创建任务时签发的一次性随机 Token，客户端在 `X-RCH-Transfer-Token` 中提交；Token 在成功验证后即被消费，不能无限次复用。普通 Artifact 上传与暂存下载的 8086 路由则没有沿用这套 Token 流程，因此**端口的网络可达范围、反向代理规则和额外访问控制都是实际部署边界**。

8086 是默认文件端口，而不是一个永远固定不变的数字。Server 如果将 `RCH_WEB_PORT` 修改为其他值，Client 配置、Browser 直连地址、代理和防火墙应同时按“Web 端口 + 1”保持一致。传输服务拒绝超出 HTTP 请求上限的上传时也不会自动降级改走旧 8085。

### 部署与异常定位

**正常的大文件 Remote Files 上传**，优先确保浏览器到 Server 8086 以及目标 Client 到 Server 8086 双向可达；浏览器端上传成功只代表第一阶段暂存完成，仍需观察后续 Client 下载阶段。若文件很大且需要实时上传字节进度或可取消性，应检查 Client 的 `HTTP_TRANSFER_MODE` 是否设置为 `cancelable`。`legacy` 是默认的兼容方案，不会因为换成 8086 就拥有流式上传和取消能力。

| 现象 | 核查重点 |
| --- | --- |
| 页面及目录列表正常，但文件上传失败 | 8085 可用并不证明浏览器或 Client 能访问 8086；检查专用端口、URL、TLS 和反向代理 |
| Browser 上传成功，但文件没出现在设备上 | 继续检查 Transfer 的 `preparing` / `transferring` 阶段、Client 连接、目标目录与磁盘权限 |
| 大于 1 GiB 的 Client 上传被拒绝 | 检查 Legacy 的客户端保护；这不表示 Server 只有 1 GiB 容量 |
| 上传没有百分比，下载却能显示 | Legacy 上传无逐块进度；Legacy 下载使用流式接收可回报进度 |
| Cancel 不可点击 | 任务当前阶段可能声明 `cancel_supported=false`；检查 Client 策略和具体阶段 |
| 点击 Cancel 后尚未完全停止 | 取消请求与 Worker 最终退出不同步，等待 `cancelled` 或最终错误状态 |
| Transfer 百分比从头开始 | Browser 上传结束后进入 Client 下载，进度按新阶段重置 |
| ZIP 创建阶段没有进度百分比 | 压缩还在准备最终文件，总长度暂不可用 |
| Transfer Center 记录消失 | Recent 有 50 条限制且仅存内存；清理或 Server 重启不影响已保存 Artifact |
| 某次 Script、Clipboard 或 Web 下载没有 Transfer 记录 | 并非所有文件 HTTP 请求都会建立 `transfer_id` |

需要把性能调优、文件传输管理和文件资产管理作为三个独立问题看待。端口分离避免数据走不适合大文件的 HTTP 包装层；`cancelable` 改变 Python Client 的字节处理和中断能力；Transfer Center 提供可观察性与控制；Artifact 负责文件保存、预览和后续下载。**没有任何一层能够单独替代另外三层。**

远程文件浏览、编辑和路径管理的业务细节见 `remote_files.md`；Artifact 的生成与展示则遵循各自功能模块的文档。这里专注文件字节传输、进度及取消，不把每个历史命令或已有模块列成清单。

### 普通 `download` 命令的参数与输出边界

`download <file>` 是 Client 的终端文件上传（设备到 Server Artifact），不是 Remote Files 的文件浏览命令。无参数立即返回 `Usage: download <file>`，不会把空路径解析成当前工作目录；目录输入仍返回明确的 `Not a file` 错误。该命令执行过程中发送的正常 Socket 结果应与已登记的命令 ID 关联，不得因为极快返回而意外显示成 `[Background]`。是否能取消正在进行的 HTTP 字节传输仍取决于 `HTTP_TRANSFER_MODE`；不能将普通任务的取消能力等同于传输取消。
