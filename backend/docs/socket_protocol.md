# Client–Server Socket Protocol

RCH 的 Client 与 Server 通过一条持续存在的 TCP 连接交换控制消息。连接建立后先传输 `info` 握手；之后远程命令、只读补全查询、取消、心跳、PTY、屏幕画面、剪贴板、设备监控及传输任务的控制信息，都复用这条连接上的 JSON 消息协议。Server 将 Client 发送的消息分派到正在等待的命令或特定会话服务，Web 再通过 HTTP API 与 SSE 使用这些能力。

**Socket 消息、Web Task、SSE 事件是三层不同概念。** Socket 协议解决 Server 与 Client 之间如何封包、收发和识别消息；Web Task 管理由浏览器发起的一次执行；SSE 把结果推送给浏览器。文件传输的实际字节内容还有独立的 HTTP 或 TCP 数据连接，不经这条 JSON Socket 连续搬运。

Bind TCP 改变拨号方向：Python Client 在配置的地址监听，Server 通过设备栏 More 的主动连接操作向目标 IP 和端口建立 TCP 连接，首条应用消息仍是 **Client 发出的 `info`**。Server 调用现有 `SessionAcceptor.accept_session()`，继续使用原帧格式与结果事件。当前 Bind 使用普通 TCP。Server 完成会话注册后先发送原有 `client_session_token`，然后向 Bind Client 发送一次 `session_config`（`server_web_base_url`），随后发布上线事件。Reverse 只接收原有 Session Token，不改变 Web URL。Bind Client 将该 URL 作为当前会话的 Web API origin，断开时失效；新连接重新获得公告。

## 1. 一条 TCP 连接中的消息

Python Client 建立连接后立即发送一次 `info`。Server 读取第一条消息并登记 `ClientSession`，然后为该 Session 启动接收线程。双方后续在同一条 TCP 流上连续传输完整的消息帧，不需要为每条命令重新建立 TCP 连接。

```text
Browser                         Server                              Client
   |                              |                                   |
   |-- HTTP: submit command ----->|                                   |
   |                              |-- TCP: command(id, text) -------->|
   |                              |<-- TCP: result(id, chunk) --------|
   |<-- SSE: command_result ------|                                   |
   |                              |<-- TCP: result(id, completed) --------|
   |<-- SSE: command_complete ----|                                   |
   |                              |                                   |
   |-- HTTP: open monitor ------->|-- TCP: monitor_open(session_id) -->|
   |                              |<-- TCP: monitor_opened ------------|
   |                              |<-- TCP: monitor_snapshot ----------|
   |<-- SSE: monitor snapshot ----|                                   |
```

首帧由 `backend/server/runtime/server_listener.py` 的 `_receive_client_info()` 接收：Server 对新连接临时设置 **5 秒 Socket 接收超时**，读取并解析第一帧后恢复阻塞模式；失败则关闭新 Socket，不登记成功会话。这不是后续所有消息的通用 5 秒超时，也不是连接保活周期。Server 的活动连接以 `client_id` 寻址；握手字段的解释参见 [Client Handshake & Capability Discovery](client_handshake.md)。

### 帧编码

共享 Python 封包实现位于 `backend/core/protocol/rchsocket.py`，类 `RCHSocket`：

```python
encoded = json.dumps(message).encode()  # UTF-8 JSON
header = struct.pack('i', len(encoded))   # 原生格式的有符号 int
socket.sendall(header)
socket.sendall(encoded)
```

在接收端，先使用 `struct.calcsize('i')` 确定头长度，读取完整长度头，解出消息体字节数，按给定长度循环 `recv()`，最后 `json.loads()` 还原消息对象。项目当前常见部署平台上头部为 **4 字节**，但 `'i'` 没有显式指定网络字节序，其编码按 Python `struct` 的**本机字节序与对齐规则**解释。

```text
┌───────────────────────┬───────────────────────────────────┐
│ length: native int    │ JSON body: UTF-8 bytes           │
│ Python 通常为 4 bytes │ 恰好 length 个字节                │
└───────────────────────┴───────────────────────────────────┘
```

例如消息 `{"type":"heartbeat","id":7,"ts":"..."}` 先序列化为 JSON 字节，再把**字节长度**写入帧头。长度是 UTF-8 编码后的字节数，不是 Python 字符串的字符数。TCP 不保留应用层“消息边界”：一次 `recv()` 可能只拿到一段头或消息体，因此 `_recv_exactly()` 会持续读取直到满足长度。Socket 在读取期间关闭时，函数分别报 `Connection closed`（尚未取得任何预期字节）或 `Connection aborted`（读取一部分后终止）。

Python `send()` 有 `_send_lock`（`RLock`）保护整个头部及正文的发送，确保本连接多线程生产消息时，两个逻辑帧不会在 Python 发送路径上彼此穿插。**这是帧发送互斥，不保证网络送达、远端业务成功或应用层重试。** 消息没有统一的压缩字段、协议版本协商、CRC/签名、长度上限校验或逐帧 ACK 机制。发送的结构是 JSON Dictionary；截图与 PTY 数据需要先转换为适合 JSON 的文本表示。

## 2. 接收线程与消息处理顺序

同一条 Socket 上存在多种用途的消息，最关键的是**接收动作与耗时命令执行分离**。否则 Client 执行一个长期任务时便无法及时处理心跳、取消和交互输入。

### Python Client：立即处理与延后执行

Python Client 的 `ClientReceiverWorker` 在后台线程持续调用 `ServerConnection.recv_message()`，接收后交给 `ClientInboundMessageDispatcher` 按 `type` 分类：

| 分类 | 当前处理方式 | 典型消息 |
|---|---|---|
| Immediate | 在接收线程进入 `ClientInboundMessageRouter`；具体管理器可以再启动自己的后台工作线程 | `completion`、`heartbeat`、`cancel`、PTY 控制、Screen 控制、Monitor 控制、Transfer 控制 |
| Deferred | 放入 `pending_message_queue`，交由 `Client.wait()` 的主执行循环取出 | `command`、`acmd`、Foreground Control |
| Independent | 按 Action 注册到独立工作池，接收线程只提交，不等待业务完成 | Clipboard、Remote Files、Configuration get、Watchdog status、Job ps/status、Process kill |
| 未识别 | 调度器不作处理 | 未注册的 `type` |

Deferred 消息使用 `queue.Queue`。`Client.wait()` 通过 `recv_command(timeout=0.5)` 取出一条，调用命令执行器处理，再以 `send_result()` 回传（或由命令执行中的输出方法陆续回传）。这一路径使常规前台命令按 Client 执行循环串行处理，并与 Server 对同一连接的前台任务占槽机制配合；它**不意味着** PTY、监控和屏幕采集会占用同一个待执行队列。

Immediate 消息**直接由接收路径处理，不进入普通命令队列**。`completion` 是只读短请求，Handler 直接调用本地 Provider 并返回 Result，不进入 `Client.wait()`。如果某个立即处理的 Handler 自己执行耗时同步操作，依然可能拖慢下一帧的读取。扩展消息时应把真正耗时的工作交给管理器或合适的执行线程。

### Server：每个连接一条接收处理路径

Server 为已登记的 `ClientSession` 启动一个 daemon 接收线程（`ServerListener.connection_handler`）。该线程反复 `session.recv_message()`，由 `ServerInboundMessageDispatcher` 只接纳已注册的 Client → Server 消息，再交给 `ServerInboundMessageRouter`。Server 的这条消息路径**不通过 Client 端那种 Deferred 命令队列**；它主要消费结果、心跳 ACK 和长期会话通知。

Server Session 在 `ClientSessionContext` 中注册各业务服务的回调，例如 PTY、Screen、Monitor、Clipboard 和 Transfer。收到消息时，Router 从消息取出关联 ID 和正文，将它交给对应服务；服务再决定状态维护、事件发布及 Web 订阅者的通知。

```text
Python Client 收到 Server 消息                   Server 收到 Client 消息
     Socket recv()                                    Socket recv()
          |                                                |
   ClientInboundDispatcher                        ServerInboundDispatcher
          |                                                |
    +-----+-----------+                                    +--- Router
    |                 |                                         |
 Immediate          Deferred                             +------+-------+
    |                 |                                  result/ACK    会话消息
    v                 v                                      |             |
 Router          Pending Queue                          Result Queue    Callback
    |                 |                                                    |
 Heartbeat /       Client.wait()                                     PTY / Screen /
 Cancel / PTY      Command Executor                                 Monitor / ...
 / Monitor / ...       |
                      v
                 result frame
```

## 3. 独立 Completion 查询

`completion` 是与 `command`、`control` 同级的只读查询消息，不是用户命令，也不是 Control Action。它使用独立 request ID 和 Result Envelope 关联，不进入普通命令队列，不占 Foreground，不创建 Activity 或 History。

`cursor_position` 使用输入框 `selectionStart` 对应的 UTF-16 code unit 偏移。Server 先读取当前 Session 的握手 `command_manifest`：Shell-like 命令条目带一个 CompletionSpec；ACMD 条目带去重后的 CompletionSpec 列表。若当前命令/ACMD 声明了补全，Server 才发送 Completion 请求。Web Common Ops、RCHCLI 本地 `edit` 和显式 `@@` 可通过现有 HTTP 补全入口提供相同的两字段 override。

请求示例：

```json
{
  "type": "completion",
  "id": 22,
  "raw_input": "acmd sqlite_query --db /tmp/",
  "cursor_position": 28,
  "max_results": 50
}
```

需要 override 时，可附加且只附加这两个 Spec 字段：

```json
{
  "type": "completion",
  "id": 23,
  "raw_input": "cat /tmp/",
  "cursor_position": 9,
  "max_results": 50,
  "completion": {"provider": "filesystem", "kinds": ["file", "directory"]}
}
```

Python Client 与 Go Client 都立即处理 `completion`，由本地 Provider Registry 按 `provider` 选择实现。当前只有 `filesystem` Provider；它统一枚举文件和目录，再按 `kinds` 过滤。ACMD 参数定位使用 Client 本地既有参数 Schema，不在 CompletionSpec 中重复保存参数名或位置。

响应复用既有 Result Envelope：

```json
{
  "type": "result",
  "id": 22,
  "event_type": "completed",
  "status": "success",
  "message": "",
  "data": {"items": []}
}
```

`items: []` 是合法的成功空结果；Provider/路径错误使用 `status: error`。Server 通过 `PendingResults` 按 request ID 等待，不调用 `run_foreground_json_command()`，也不创建命令执行绑定。请求超时后清理 pending entry，迟到结果因 ID 不再待处理而被丢弃。

## 4. 普通命令的请求、输出与结束

普通执行的 Socket 消息以**该连接的 `command_id`**（消息中的整数 `id`）关联。它由 `ClientSessionCommandChannel.generate_message_id()` 为该 Session 自增产生，和浏览器创建的 `task_id`、持久化历史的 `history_entry_id` 都不同；新的 Socket Session 有自己的计数器。

Server → Client 示例：

```json
{"type":"command","id":18,"text":"pwd"}
```

Script 使用 `control(domain=script, action=run)`，payload 包含 `script_name`、`source`、`params`、`execution_mode`、`output_mode`；`acmd` 仍使用 `extra`。普通命令和 Script 的自由文本输出仍作为 `message` 传递，不解析其中看似 JSON 的内容；显式 `context.emit(data)` 独立产生结构化 `chunk`。Client 返回的取消/超时原因统一归入最终 `completed.status`。

Result Envelope 是同一个按请求 ID 关联的事件流：`started`（可由 Server 发起）、`progress`（进度更新）、`chunk`（实际输出）、`completed`（唯一终态）。所有消息都使用 `type=result`、`id` 与 `event_type`；`message` 为可读文本，`data` 可为 JSON 对象或数组，`references` 可选。`progress` 可以携带可选 `level`，只支持 `info/success/warning/error`；不填就不追加任何 Output Marker。Server 统一投影 `[*]/[+]/[!]/[-]` 可见文字，原始 `message` 无标记。`chunk` 不允许 `level`。**只有 `completed` 才携带最终字符串 `status`**：`success/partial/error/cancelled/timed_out/interrupted`。Socket Result 不含 `display`、`shape` 或 `eof`；终端如何呈现由业务调用位置和公共 Renderer 决定。

Control 可以在 `completed` 中同时携带 `message` 与原始业务 `data`。Terminal 的操作反馈选择 `message`；查询由调用方选 Table、Flat 或 Grouped，Text/`--json` 使用同一份终端字段投影；Web 可以直接消费完整业务 `data`。例如 `config list` 的 Text/JSON 均只含 `group/key/value/default` 四列，Web GET 仍使用编辑控件所需的配置元数据。普通命令与 Script 的文本输出不强制结构化；这两类只统一 Result 事件外壳和生命周期。

一次性业务请求统一使用 Control：

| Domain | Action | Payload / Result.data |
| --- | --- | --- |
| configuration | get | `{}` 或 `{"include_hidden":true}` → 当前配置的 `store_path`、`items` |
| configuration | set | `{"key":"SCRIPT_DEFAULT_OUTPUT_MODE","value":"stream"}` → 更新后的配置及 change；CLI 文本值带 `value_format: "text"` |
| configuration | reset | `{"key":"SCRIPT_DEFAULT_OUTPUT_MODE"}` 或 `{"all":true}` → 恢复后的配置 |
| watchdog | status | `{}` → 当前 Watchdog 状态对象 |
| process | kill | `{"pid":1234}` → `completed.message`（不另存重复的业务 data） |
| session | disconnect | `{}` → Client 立即关闭自己的连接；该控制动作独立执行，连接关闭可先于 Result 终态 |

Configuration 的值使用 JSON 原生标量，CLI `set` 与 Web 共用配置校验、覆盖存储和运行时副作用；查询 Script 默认模式不绑定 Script Activity。Watchdog 查询复用既有状态对象，进程/App 实时列表与详情继续走 Device Monitor。Go 支持 Configuration；Watchdog 和 Process UI 仍按现有能力声明限制。Server → Client 文件传输无论从 Web 还是 Terminal 发起，均走 Transfer 协议，不占用 Client 命令执行槽。

Client → Server 单次完成示例：

```json
{"type":"result","id":18,"event_type":"completed","status":"success","message":"/home/user\n","cwd":"/home/user"}
```

流式执行可先返回 `result(event_type=progress/chunk)`，最后恰好一条 `result(event_type=completed, status=...)`。Server 以请求 ID 分发完整 JSON 事件；**仅 `completed` 结束该请求**。后续重复终态、迟到帧不得进入其他请求；断线或超时需要由 Server 的执行边界标记终态。内部旧执行器的 `(status, result)` 与队列结束标记只是应用层适配，不代表 Socket 上仍有第二种 `eof` 终态。`cwd` 可同步 Server Session 当前目录。

同一会话的 Foreground 与 Independent 可以无序交错回包；每个 ID 仍只有一个结果通道。Foreground 保持单一执行槽，Independent 不是任意前台命令并发。

### 取消确认与最终执行结果

取消控制本身使用一条独立消息：

```json
{"type":"cancel","id":19,"target_id":18}
```

其中 `id=19` 是取消请求的消息 ID，`target_id=18` 才是被取消的命令。Python Client 立即进入 `cancel_command()`，回应 `cancel_ack`，携带 `target_id`、`accepted`、`state`、`message`、`cwd`、`client_ts` 等字段。根据执行器回调，还可能后续再报告 `stopped` 或 `completed` 终态。

**`accepted` 表示 Client 已接收取消请求。** Server 收到 `cancel_ack` 时，会依据 `target_id` 更新当前前台任务的取消状态；实际输出、收尾及前台槽释放依然要走命令生命周期。`cancel_ack.id` 不用于普通结果队首匹配。详见 [Command Execution Pipeline](command_execution.md)。

## 5. 不同用途的长会话消息

PTY、Screen、Monitor 等业务并不借用前台命令的 `command_id` 来标识自己的完整会话，而使用各自的 Session ID。Server 可以在同一 Client TCP 连接内与普通命令并行发送控制帧；Client 管理器负责会话线程、资源和停止信号。

| 消息族 | Server → Client | Client → Server | 主要关联字段 |
|---|---|---|---|
| 心跳 | `heartbeat` | `heartbeat_ack` | `id`、`ts`、`server_ts`、`client_ts` |
| PTY | `pty_open`、`pty_input`、`pty_resize`、`pty_close` | `pty_opened`、`pty_output`、`pty_closed`、`pty_error` | `pty_session_id` |
| Screen | `screen_open`、`screen_config`、`screen_close`、`screen_input` | `screen_opened`、`screen_frame`、`screen_closed`、`screen_error`、`screen_input_error` | `screen_session_id` |
| Clipboard | `control/clipboard/get`、`control/clipboard/set` | `result` | `id` |
| Monitor | `monitor_open`、`monitor_config`、`monitor_close` | `monitor_opened`、`monitor_snapshot`、`monitor_error`、`monitor_closed` | `monitor_session_id` |
| Transfer | `transfer_start`、`transfer_cancel`、`transfer_register` 确认 | `transfer_update`、`transfer_register` 请求 | `transfer_id` |

这些族的共同特点是：**各消息有其业务相关的 ID，不能用 Socket `id` 或 Web `task_id` 一概替代**。它们以 JSON Dictionary 为承载，但字段约束、资源回收和前端订阅策略分别由对应业务服务定义；协议层不会自动发现全部会话，也不会替每个会话设置统一的超时或持久化历史。

### 心跳：同一连接上的应用层探活

Server 定期为各 Client Session 生成消息 ID，发送带 `ts` 的 `heartbeat`。Python Client 收到后直接回 `heartbeat_ack`，回填请求 `id`、`server_ts`，并报告当前 `client_ts` 与 `cwd`。Server 由 ACK 更新时间、工作目录和 RTT 统计，再向上层发布心跳状态。它是**应用层心跳**，不是 TCP Keepalive 或重发确认；一次 ACK 不代表其他业务消息已经执行完毕。

### PTY 与 Screen 的流数据

PTY 输入和窗口尺寸调整用独立消息控制，其 `pty_output.data` 在 Client 侧由二进制终端输出做 Base64 编码后写入 JSON；Server 交给对应 PTY Session 服务，不放进普通命令的结果队列。Screen 的 `screen_frame.data` 同样以 Base64 编码画面字节，并同时携带宽高、序号及可能的帧/补丁信息，服务再解释增量画面。**Base64 是 JSON 承载方式，不是传输加密。**

这两个能力包含持续的数据生产者，即便所有数据走同一 TCP 连接，也不能把它们理解为一条永不结束的普通 `result` 消息。参见 [PTY](pty.md)、[Screen View](screenview.md)。

### Monitor、Clipboard 与 Transfer

Device Monitor 通过 `monitor_open/config/close` 控制订阅，Client 按频道发送 `monitor_snapshot`，随附 `seq`、`channel`、`collected_at`。Clipboard 的显式读写使用 `control/clipboard/get|set` 和对应请求 ID 的 Result；Transfer 则用 `transfer_start/cancel/update` 维护任务进度、错误和终态。尤其要区分：**文件上传/下载的实际内容走独立 HTTP 或 TCP 数据连接**，Socket 主要协调执行和反馈 `transfer_update`，不是在这里追加一个二进制 `file`/`rdy` 流。参见 [Device Monitor](device_monitor.md)、[Clipboard](clipboard.md)、[File Transfer](file_transfer.md)。

内置命令或 Clipboard Control 需要搬运文件时，可使用 `transfer_register` 携带当前请求 ID、Transfer ID、方向、文件名及所选模式，在同一主连接上获得确认。Server 只允许当前活动请求登记；Clipboard 下发的来源必须是该请求已暂存的文件。登记后继续使用现有 Transfer 进度和取消消息，不新增文件 Worker。

受管理的 TCP 文件任务通过 `transfer_update.metadata.file_transfer_mode` 确认实际模式。Bind 任务准备好接入辅助连接时，通过 `transfer_update.data_ready` 通知 Server；Reverse 由 Client 主动建立辅助连接。辅助 Socket 的首帧为 `transfer_data`，包含 `transfer_id` 与当前 Session Token；经原监听入口分流后不登记为主会话。后续控制帧采用网络字节序四字节长度与 JSON，文件内容按声明长度发送原始字节，随后发送 SHA-256 校验信息，接收端完成提交后确认。进度、取消及任务终态仍使用原主连接。


## 6. 消息从业务服务到浏览器的边界

收到 Client 数据后，Server 的处理流程是 `ClientSession.recv_message()` → `ServerInboundMessageDispatcher` → `ServerInboundMessageRouter` → 对应的业务服务回调。不同消息的上层去向不相同：

- 普通 `result` 进入当前命令的等待队列，Web Task 再发布分段 `command_result` 与最终 `command_complete` SSE。
- PTY、Screen、Monitor、Clipboard、Transfer 由各自服务处理其 Session 状态，按对应 Web 路由和浏览器 Tab 的订阅关系发布 SSE 或查询结果。
- `heartbeat_ack` 更新会话健康状态，并可通知连接状态订阅者；`cancel_ack` 更新前台任务取消状态。

对浏览器而言，HTTP 用于申请和配置动作，SSE 用于接收事件，**都不是让浏览器直接持有 Python Client 的 TCP Socket**。相反，Server 负责把多个浏览器发起的操作映射到目标 `client_id` 的 TCP Session，并在具体业务下执行授权、队列或资源约束。

## 7. 断线、异常与协议边界

### 连接断开后发生什么

Python Client 接收线程遇到 Socket 异常时记录错误，由外层 `Client.wait()` 检查并启动恢复：停止旧接收线程、关闭旧 Socket、清理旧连接相关运行时和后台会话、构造新的 `ServerConnection`、重新连接并发送新的 `info`。在**同一个 Client 进程**内保留原 `client_id`；重建连接后得到新的 Socket 和新的运行态。它不是简单地在旧的 `RCHSocket` 上重新 `connect()`。

Server 接收线程遇到 `socket.error` 后执行连接关闭处理，通知 Web 侧服务、向当前 `message_queue` 放入终止项 `(0, None, 1)` 以唤醒等待者，再从 `ConnectionManager` 移除该会话。如果业务清理回调出错，Server 仍会在 `finally` 尝试移除会话。与之不同，接收处理中的其他异常目前被记录，并在短暂暂停后继续循环；不要假定**任意**协议错误都会立即强制断开。

已经发送但尚未确认执行结果的业务指令，不能因为 TCP 发生重连就自动断言“未执行”或“执行成功”；现有通用协议层没有连接恢复后的应用消息重放、持久消息序列号和恰好一次执行保证。是否需要重试必须依据具体命令/任务的幂等性与上层状态判断。

### 开发者必须注意的约束

1. **字节序**：Python `struct 'i'` 使用原生字节序，没有将传输格式固定为跨平台统一的网络字节序；跨不同字节序平台时不能仅靠当前机器上的成功连接判断协议兼容。
2. **长度校验**：当前 Python 解码端没有显式设置消息体最大长度。新接入不可信网络时，应把内存占用和异常长度视为需要额外保护的风险，而不是当作已经由协议解决。
3. **完整写入和并发写入**：Python 发送通过 `sendall` 和实例锁实现；这防止本连接多个线程生成的逻辑帧交错，但不提供对端确认或重发保证。
4. **连接机密性与身份**：`RCHSocket` 代码只是普通 TCP+JSON，没有内置 TLS 加密、消息签名或 Client 证书校验；握手的身份字段由 Client 自报。实际外部访问保护必须由部署边界或明确的上层安全机制提供，不能把 Machine Fingerprint 当认证凭据。
5. **消息有效性**：基础 Router 根据 `type` 字符串选择方法，未识别类型通常被忽略；不存在统一 JSON Schema 验证或应用协议版本协商。Server Listener 目前将解包后的首帧交给会话构造路径，并没有在该入口显式断言 `type == "info"`；因此 `info` 是当前 Client 的发送约定，而不能把“首帧正确标识为 `info`”当作已经由底层强制校验的安全保证。新增字段应由对应 Handler 验证类型、取值和授权，不要仅因能够解包就执行敏感操作。
6. **流控与积压**：Socket 多业务复用，Client Deferred 队列和 Server 结果队列都可能积压；目前底层没有通用 per-channel 优先级、配额、ACK 或背压控制。屏幕、监控等高频数据应由自己的业务层限制频率、帧体和生命周期。

## 8. 增加一种 Socket 业务消息

接入一个需要跨 Server/Client 双向通信的新功能时，先明确**消息归属和任务模型**：一次前台命令采用 `command`/`result` 管道；独立持续会话应使用专属 Session ID，并有明确打开、更新、结束和异常信号。随后按以下路径完成对接：

1. 在 `backend/core/protocol/message_types.py` 确定消息名称，并在 `BaseMessageRouter` 中为请求与响应增加分派入口。
2. 若由 Server 发起，更新 Python Client 的 `ClientInboundMessageDispatcher` 分类：耗时独占的命令交给 Deferred；心跳、控制类与只读 `completion` 查询由 Immediate 路由。Completion Handler 只读调用 Provider 并回 Result，不得转入命令/Control 执行路径。
3. 在 `ClientInboundMessageRouter` 或相应 Client 管理器处理请求，构造带有 `type` 和正确业务 ID 的回包；多线程回包通过现有 Python `ServerConnection.send()` 发送。
4. 在 Server 的 `ServerInboundMessageDispatcher` 注册允许接收的回包类型，实现 `ServerInboundMessageRouter` Handler，再在 `ClientSessionContext` 与应用服务中建立回调、状态更新与资源清理。
5. Web 功能通过 Server API 发起操作，通过对应 SSE/状态接口接收结果。完成断线、中断、重复请求、迟到响应、错误消息及并发资源的检查。

例如，如果新增一条长时间运行的订阅会话，不应临时把 `command_id` 当作其永久 Session ID：前台命令完成后，Server 会清掉当前命令的结果等待及部分授权绑定，长期订阅需要它自己的生命周期。Socket 协议会负责封包，**不会替业务保证关闭、订阅权限或客户端断线后的资源释放**。

相关实现入口：`backend/core/protocol/rchsocket.py`、`message_router_base.py`、`message_types.py`；`backend/server/runtime/server_listener.py`、`backend/server/connection/`；`backend/client/connection/` 与 `backend/client/bootstrap/`。讨论用户发起的执行任务可读 [Command Execution Pipeline](command_execution.md)；具体持续会话参见对应功能文档。

## 附录：Go Client（非主要维护路径）

下面仅记录该独立实现与上文 Python Client 协议的边界，不作为主要协议流程的前置条件或功能清单。

**连接传输。** Go Client 根据构建时注入的 `SERVER_TRANSPORT` 选择 `tcp`（默认）或 `tls_tcp`；TLS/TCP 使用与 Python Client 相同的 Server 证书 SHA-256 指纹校验，在 TLS 握手成功并验证指纹后发送 RCH 握手。证书指纹由所选 Listener 的构建配置注入。

**帧实现。** `backend/client-go/protocol/ratsocket.go` 也使用“4 字节长度头 + JSON 消息体”，但长度头采用 `binary.LittleEndian`、`uint32`，接收通过 `io.ReadFull`。Python 侧使用原生格式有符号整数长度头；两者在常见 little-endian 机器上可以互通，不代表已经实现跨任意字节序的统一封包协议。Go 的 `Send()` 分别用一次 `conn.Write()` 发送头和正文，已使用发送互斥锁，尚未实现短写补发循环；该接收端也未显式规定最大消息长度。

**消息范围。** `backend/client-go/handler/router.go` 支持 `heartbeat`、`completion`、`command` 与按请求 ID 的取消 `cancel`；可取消命令及 `shell_stream` 能分段返回 `result(event_type=chunk)`，结束时返回 `result(event_type=completed)`。Remote Files、Script 与 Configuration 使用各自的 Control Manager；Script 通过外部 Python 执行，支持 subprocess_pipe 的 collect/stream 两种输出。ACMD、PTY、Screen、Clipboard、Monitor 等能力仍按 Client 实际实现和能力声明决定。Heartbeat ACK 包含 `server_ts`、`client_ts` 和当前工作目录，Server 可用原始 `server_ts` 计算 RTT。

如需维护这一独立实现，应分别核对 `backend/client-go/protocol/ratsocket.go`、`connection/client.go` 和 `handler/router.go`，而不把这些实现差异混入 Python Client 功能开发步骤。


### Control 执行策略

Control 的 Domain、Action 和调度策略采用统一的协议定义。Client 在组装业务 Manager 时绑定各 Action 的处理器、必要的请求准备及取消能力。通用调度层只消费注册结果，不解释业务 Payload；Server 依据同一 Action 契约确定调度策略，不允许调用方修改策略。Foreground 继续使用单一前台槽；Independent 请求使用有容量限制的独立工作池，与 Foreground 共用按 ID 关联的 Result 和执行上下文。Clipboard get/set、Remote Files 全部 Action、Configuration get、Watchdog status、Job ps/status、Process kill、Session disconnect 为 Independent；Job start/stop/stop_all、Configuration set/reset、Script run 为 Foreground。调度表按 Domain 与 Action 显式声明；Go 的支持范围内使用相同策略。Independent 不改变已登记的 Activity 记录策略。Server 在发送前登记 ID，按 ID 分发输出与唯一 `completed`；超时、断线清理等待者，迟到帧不得串入其他请求。取消沿用 target_id 和 cancel_ack，只有实际停止才是 stopped。

Control Action 目录的 `ActivityPolicy` 与 `ExecutionPolicy` 独立。最终 `Result(event_type=completed)` 的 `status` 决定 Activity 终态；`progress/chunk` 不会因其文字或中间整数状态被当作最终失败。Remote Files 批量执行任一项失败时 `completed.status` 为 `partial`（已有项目成功）或 `error`（无项目成功），成功时为 `success`；复制/移动结果才保留 Web 实际读取的 `succeeded/failed`；删除只返回完整可见 `message`，不重复上传 `total/skipped/errors` 统计字段。

## Optional TCP forwarding

The optional TCP Tunnel maps a listening port on one RCH device to a TCP
service accessible from the other device. Each instance selects `expose_on`
as `client` or `server` independently of the main RCH Bind/Reverse connection
mode. A standard Tunnel Control request starts or stops the mapping; actual
byte traffic is carried by separate TCP control/data connections, not the RCH
JSON frame transport.

The `expose_on` setting selects only the local listening socket. Extra Tunnel
TCP connections are dialled in the same direction as the already established
RCH session and reach the same TCP/TLS listener address and port, regardless of
where a mapping listens. A removable listener handler is registered on demand
and de-registered after the last mapping stops. No Tunnel parsing or bridging
runs in the normal RCH handshake while Tunnel is idle. A separately authenticated
TCP data connection is paired with each accepted forwarded TCP stream by
`stream_id`. Tunnel bytes never enter the established RCH session socket.

Tunnel managers are process-scoped: disconnecting and reconnecting an RCH
session leaves existing Tunnel connections intact. Saved instances retain
configuration in the Server database and can be restarted manually. Token
registration, network reachability and operating instructions
are documented in [tunnel.md](tunnel.md).
