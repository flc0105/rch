# Connection Lifecycle

RCH 使用持续存在的 TCP Client Session 承载命令与运行时消息，并通过周期性 Heartbeat 观察会话是否仍能正常响应。设备列表中的 `online`、`stale`、`offline` 既反映 Socket 会话是否被关闭，也反映最近一次心跳回复的新鲜度；连接历史则独立记录每一段会话的起止时间，并按会话显示 Activity 执行摘要。它们相关，但不是一份状态数据的不同名称。

Server 负责建立和移除会话、发送心跳、计算 RTT、维护设备快照与连接历史；Python / Go Client 负责连接、回复和重新拨号；Web 通过 API 与 WebSocket 接收会话信息，再根据当前时间更新设备展示状态。下面按照这一条链路说明各部分怎样协作，以及需要调整时应修改什么。

## 从握手到活动会话

Client 连接 Server 的 TCP Socket（默认端口 `9999`），建立传输后发送包含 `client_id`、设备标识、系统信息、工作目录及命令能力的握手信息。Server 接收该信息，创建 `ClientSession`，并以 `client_id` 登记在活动连接管理器中。`client_id` 表示一次 Client 实例身份；`machine_id` 用于将不同实例关联到同一台设备，不能用两者互相替代。

成功注册时，Session 会初始化 `connected_at`、`last_seen_at`，并将 `disconnected_at` 清空。随后 Server 写入最近设备快照及会话历史，并发布 `connection_online`。所以第一次心跳尚未往返时，新会话也可以处于 Online；建立连接不是必须先等待一个 Heartbeat 才被 Web 看见。

```text
Client ── TCP connect / handshake ──→ Server Socket
                                        │
                                        ├─ 建立 ClientSession / 登记 client_id
                                        ├─ 初始化 connected_at、last_seen_at
                                        ├─ 保存设备快照与连接历史
                                        └─ connection_online ──→ Web WebSocket
```

活动会话和持久化设备资料是两个层次。连接管理器保存当前 Server 进程中的 Session；最近设备存储则保存设备的历史身份和快照。断线设备可以继续显示在最近设备列表中，其 Socket 已从活动会话中移除。

## 心跳驱动的活跃度判断

Server 的心跳线程对当前已登记的 Session 逐个发送 `heartbeat`，默认每 **30 秒**进行一轮。单条消息包括服务器生成的消息 ID 和发送时间戳：

```json
{
  "type": "heartbeat",
  "id": 123,
  "ts": "2026-10-16T10:00:00.000000"
}
```

Python Client 在消息路由中立即回复 `heartbeat_ack`，携带相同的 ID、原样返回的服务器时间戳，以及 Client 时间、当前工作目录：

```json
{
  "type": "heartbeat_ack",
  "id": 123,
  "server_ts": "2026-10-16T10:00:00.000000",
  "client_ts": 1792144800.0,
  "cwd": "/home/user"
}
```

这是一组用于解释字段的示例值。Client 的 Heartbeat 处理属于 Immediate Message，不进入普通 `command`、`script`、`acmd` 的延迟命令队列；长时间执行普通命令原则上不应阻止收包线程立即答复心跳。Server 处理 ACK 时更新工作目录、`last_seen_at`、`last_heartbeat_ack_at`，触发最近设备与会话历史更新，并通过 `connection_heartbeat` 通知 Web。

### 会话存在与心跳新鲜度

实时设备状态采用以下判定顺序：

| 状态 | 形成条件 | 代表什么 |
| --- | --- | --- |
| `online` | 会话尚未标记断开，且最近响应时间不超过阈值；刚连接且无有效响应时间时也按在线处理 | 会话仍被管理，心跳资料尚属新鲜 |
| `stale` | 会话尚未标记断开，但距离 `last_seen_at` 已超过 **45 秒** | Server 尚未确认 Socket 关闭，心跳回复已不新鲜 |
| `offline` | Session 已记录断开，或展示的是无活动会话的最近设备快照 | 当前没有可用的对应活动会话 |

**Stale** 表示最近 ACK 超过 45 秒未更新，Server 继续保持原有 TCP Socket；接收层发现连接关闭或应用显式移除会话时，才进入 Offline 清理流程。对于半开连接，列表会持续显示 Stale，直至传输层发现错误或执行关闭操作。

45 秒衡量的是**距上一次有效 ACK 的时间**，不是距上一次发送 Heartbeat 的时间。假设第 0 秒收到 ACK，第 30 秒发送新 Heartbeat 却没有回复，那么在第 45 秒之后可能判为 Stale；如果随后收到 ACK 且会话没有断开，会恢复 Online。状态恰好跨越阈值时，前端的计时刷新还可能产生额外的显示延迟。

`last_seen_at` 在当前 Server Session 中由**连接注册**和**Heartbeat ACK**更新，不应把任意命令输出、WebSocket Ping 或浏览器 API 成功请求解释为设备 Heartbeat 的延续。

## RTT 与连接诊断数据

Server 发送 Heartbeat 时记录 `last_heartbeat_sent_at` 及当前消息 ID。收到包含 `server_ts` 的 ACK 后，用服务器当前时间减去该时间戳，得到毫秒数，并以非负数保存到 `last_rtt_ms`：

```text
RTT (ms) = max(0, Server 收到 ACK 时间 - 原 Heartbeat 的 Server 发送时间)
```

它是 **Server↔Client Socket Heartbeat 的应用层往返耗时**，包含消息收发和 Client 响应处理；不是浏览器到 8085 的 HTTP 耗时，也不是严格隔离处理时间的网络 Ping。数值只在能解析 `server_ts` 时刷新；没有得到新 RTT 的情况下，原有数值可能留在 Session 中，因此应结合最近 ACK 时间判断其是否仍有参考价值。

用于观察连接的核心字段可以通过设备详情与连接 Payload 读取：

| 字段 | 含义 |
| --- | --- |
| `connected_at` | 本次 Session 注册时间 |
| `disconnected_at` | 本次 Session 记录的关闭时间；活动会话通常为空 |
| `last_seen_at` | 注册或最近 Heartbeat ACK 的 Server 时间 |
| `last_heartbeat_sent_at` | Server 最近发送心跳的时间 |
| `last_heartbeat_ack_at` | Server 最近处理心跳 ACK 的时间 |
| `last_rtt_ms` | 最近一次成功计算的心跳往返毫秒数 |
| `stale_after_seconds` | 当前 Server 提供给 Web 的过期判定阈值 |
| `connection_state` | Server 根据会话关闭时间与最近响应计算的三态 |

内建 `rtt` 命令可以直接读取当前会话的心跳诊断数据，例如：

```text
rtt --json
```

它输出连接与心跳字段的结构化结果。**该命令的 `connection_state` 只根据是否已连接、是否记录断开返回 `online` / `offline` / `unknown`，不执行 Web 的 Stale 判断**。因此出现“设备卡片显示 Stale，但 `rtt` 输出 Online”的情况，并不必然代表两份心跳数据不同。

Python Client 会回传 `server_ts`。当前 Go Client 的 Heartbeat ACK 则返回 ID、Client 时间及工作目录，但**不回传 `server_ts`**，Server 仍可更新该会话的最近 ACK 时间，不过不会凭这条 ACK 计算新的 RTT。当前 RTT 处理也没有对 ACK ID 与在途 Heartbeat ID 建立严格的一一对应检查，不适合作为精密性能测量基准。

设备列表使用连接的 `client_revision_state` 在过期时显示小型 `clock-alert` 图标；`integrity` 为 High、System、Protected 或 Root 时显示 `shield-plus` 图标。两者仅在线时显示，且保留原有设备名称和状态布局。

## Web 如何持续更新连接状态

浏览器首先通过 `GET /api/connections` 取得当前活动会话和最近设备快照。之后使用通用 WebSocket `/ws/events` 接收 Server 推送的状态变化：

```text
Server ConnectionManager
       │
       ├── GET /api/connections ──→ 初始列表
       │
       └── WebEventBus
              ├── connection_online     → 插入或更新设备
              ├── connection_heartbeat  → 更新 ACK 时间、RTT、工作目录等
              └── connection_offline    → 标记离线并清理前台活跃任务
```

Web 不是单纯显示最后收到的一份 `connection_state`。它在本地以 `statusNowTick` 每 **30 秒**推动一次状态重算：先尊重明确的 Offline / 断开标记，再把当前时间与 `last_seen_at` 比较，阈值优先使用 Server 返回的 `stale_after_seconds`（缺失时回退为 45 秒）。因此不需要一条专门的 `connection_stale` WebSocket 事件，设备卡片也能在心跳不再更新时转为 Stale。但由于计时刷新不是逐秒运行，UI 变化可能晚于精确阈值。

界面还有一项优先条件：对于**没有被明确标记为 Offline**、且携带 `is_transfer_active` 标记的连接，当前前端状态计算会优先展示 Online。因此判断异常时，应区分 Server 返回的 `connection_state` 和浏览器最终计算出的显示状态，不要只依据颜色认定 Socket 是否健康。

上线与离线会产生 `connection_online` / `connection_offline` 事件，并可进入通知系统。`connection_offline` payload 同时携带本次连接的 `termination_reason`，前端离线通知直接显示该原因。Stale 由最近心跳时间计算，在确认 Socket 关闭时才发布 Offline 生命周期事件。浏览器 WebSocket 流使用独立的保活链路，Client Socket 的心跳与状态由 Server 单独管理。

## Terminal Connection Context

Terminal 输入栏下方可以显示一行连接上下文标签，用于快速查看当前设备的状态与基础信息。通过 **Settings → Connection Context** 搜索并选择 Basic Info 字段，调整展示顺序后保存；字段选择是 Server 全局偏好，对当前实例管理的所有设备生效。未选择字段时不显示标签行。

标签值从当前连接快照读取，并复用 Connection Info 的状态、最近响应时间、RTT、时间和启动模式格式化规则。可选字段包括 Status、Hostname、Address、Client ID、OS 信息、Manufacturer、Model、Integrity、Build Version、Client Revision、Machine ID、Fingerprint Basis、Last Seen、Connected At、Disconnected At、RTT、Working Directory、PID、Process Name、Launch Command、Launch Mode、Client Log、Username 和 Python Version。连接切换后，标签内容随当前连接更新。

可选 **Task** 显示当前 Client 前台执行状态：`Idle`、`Running`、`Cancelling`。该状态来自 Server 的执行槽，浏览器通过 WebSocket 事件更新，并在首次订阅、重新连接及切换设备时读取权威快照，因此重开标签页或刷新后仍可恢复；Basic Info 的 Task 字段采用相同状态。Terminal 在已有前台任务占用时以输出警告行显示 `[ Details ]` 链接，展示执行信息和适用的取消操作。

字段选择保存在 `settings` 表的 `terminal_context_preferences` 命名空间中，字段 ID 按用户选择顺序保存。`GET /api/terminal/context-preferences` 读取当前选择，`PUT /api/terminal/context-preferences` 保存选择，数据结构为 `{"field_ids": ["integrity", "pid"]}`。该偏好只决定显示哪些信息，不改变 Client 上报的数据或连接生命周期状态。

## 连接丢失后的清理、重连和历史留存

Server 的 Session 收包循环在捕获 Socket 错误时进入会话关闭处理：标记 `disconnected_at`，将最近设备标为离线，结束持久会话历史，撤销相应的临时授权，并通知 PTY、ScreenView、Clipboard、Monitor、Transfer 等子系统清理与该 Client 关联的运行态。随后发布 `connection_offline`，唤醒等待中的命令处理，最终从 `ConnectionManager` 移除 Session。

这是一组**连接关闭的副作用**，不是“达到 Stale 阈值”会执行的操作。如果只是心跳不新鲜而 Socket 未报告断开，不能假定所有相关任务都已经完成清理。

Python Client 在连接丢失时会停止接收 Worker、对旧 Socket 执行 `shutdown` 并关闭它，处理相关后台任务并重建连接运行态，然后重新拨号、握手、启动接收 Worker。默认失败重试间隔为 **5 秒**；如果重新握手失败，也会继续尝试。同一个 Python Client 进程使用自己的 `client_id` 重新连接；重启或另开 Client 进程则有新的实例身份。Go Client 也会在 TCP 拨号失败后等待约 5 秒再次尝试，并在接收连接发生错误后重建 Session。

### Python Client 半开 TCP 自愈

Server 正常每 **30 秒**发送一次 Heartbeat。Python Client 接收 Worker 会记录最近一次**完整入站消息**的本地单调时钟时间；在连接已建立后，如果连续 **120 秒**没有收到任何完整消息，主循环视为接收链路失活并触发普通断线恢复。正常命令执行、PTY 和后台任务不会使这项检测自动暂停；收到任意完整 Server 消息都会刷新计时。客户端不会向 Server 新增轮询请求。

失活时会关闭旧 Socket、停止并收束旧接收 Worker，再走现有断线运行态清理、重拨号和握手流程。这个检测可以处理 macOS 休眠恢复后 TCP 在系统中仍显示 `ESTABLISHED`、但应用层已经不收消息的情况；本机网络恢复和 Server 可达后，同一 Client 进程会使用原有 `client_id` 再次上线。它不需要 Remote Control Watchdog，也不会自动重启 Client 进程。正常失联期间的 Job、PTY、Screen、Monitor 和 Transfer 依旧按已有连接丢失语义清理。

复现与回归（在项目 `backend` 目录执行，不连接真实 RCH Server）：

```bash
PYTHONPATH=. python3 -m pytest -q tests/connection/test_client_socket_recovery.py
```

测试使用本机回环的真实 TCP Socket，保留建立状态而故意不发送任何数据；缩短**测试实例自身**的失活阈值，验证超时、Heartbeat 重置、`shutdown` 唤醒阻塞 `recv`、握手失败再次重试和旧接收线程退出。生产代码默认阈值仍为 120 秒。

### 最近设备与连接历史

RCH 将当前 Session、最近设备和历史会话分别管理：

- **当前 Session** 是 Server 进程内存中的活动 Socket，按 `client_id` 识别。
- **最近设备** 保留 `machine_id` 关联的机器快照、别名等信息。没有活动 Session 的设备仍可以作为 Offline 条目出现在设备列表；有当前会话的机器不会再额外叠加同一机器的离线快照。
- **连接历史** 持久化在 `runtime/rch.db` 的 `connection_sessions` 中，记录各 `machine_id` / `client_id` 会话的连接、断开、最后响应时间和持续时间，并可关联对应的 Activity 数量与执行摘要。

Connection History 在桌面端以表格展示会话，手机端改为卡片。卡片保留连接状态、Client ID、上线/离线时间、持续时间和 Activity 数量；展开 Details 可查看主机、系统、用户、Integrity、启动模式、结束原因及 Activity 记录，并可继续加载后续 Activity。两种布局使用同一会话数据和活动查询。展开详情按需加载 Activity；历史顶部 Refresh 会重新读取会话并保留已展开的 Activity。HTTP Control 入队成功时立即显示操作反馈；交付超时、失败以及可选的领取调试信息通过 Notification Center 的 WebSocket 事件显示通知弹窗，统一受 Notification Preferences 的 Watchdog 开关控制。

### Connection History 的结束原因

Connection History 的列表在主动结束时显示 **Offline**，在连接丢失、传输错误、超时、协议截断或 Client 异常时显示 **Interrupted**。Server 启动后核对出的旧会话仍使用 Interrupted。展开记录后，**Termination** 在一个字段中显示既有结束原因文案，命令或错误摘要非空时追加括号详情；可用的 traceback 保留原文。`connection_sessions.termination_reason` 和 `termination_detail_json` 分别保存分类和详情。

| Termination cause | Connection History 状态 | 采集条件 |
| --- | --- | --- |
| Server requested disconnect | Offline | Web Disconnect、Server 控制台 `kill`、远程 `kill_instance`、`httpctl kill`，详情保存实际执行入口或命令 |
| Client exit / Client restart / Client update | Offline | Python Client 退出、重启或完成更新时上报结束；有操作命令时写入详情 |
| Connection lost | Interrupted | Socket 在报文边界处收到 TCP EOF |
| Transport error / Timeout | Interrupted | Server 捕获 Socket 传输异常或超时，详情包含错误摘要及可取得的堆栈 |
| Unexpected disconnect | Interrupted | 连接在协议帧传输途中中止，或关闭时缺少明确结束报告 |
| Client error | Interrupted | Client 终止性异常上报错误摘要与堆栈 |

设备断电、系统强制终止和网络中断由 Server 捕获的 Socket 现象归类。详情显示该连接实际收到的诊断信息。



### 连接结束原因测试验证

以下操作使用**隔离的桌面测试 Server 和 Python Client**；在 Web 的 RCH Terminal 中执行 `pyexec` 时，先设置：

```text
set PYTHON_EXECUTION_MODE inproc
```

执行 `os.abort()`、`os._exit()` 会直接结束目标 Client 进程。每组测试后重启 Client，打开 **Toolbox → Connection History**，查找刚退出实例对应的 `client_id`。测试环境关闭会自动重新启动 Client 的 Watchdog，避免新的会话刷新历史记录。

| 场景 | 在 RCH Terminal 执行的命令 | 预期状态 / 原因 |
| --- | --- | --- |
| 强制崩溃 | `pyexec import os; os.abort()` | Interrupted；通常为 Connection lost，具体按 Server 收到的 FIN/RST 确定 |
| 连接正常半关闭（EOF） | 见下方命令 | Interrupted / Connection lost |
| TCP RST | 见下方命令 | Interrupted / Transport error |
| 截断协议帧 | 见下方命令 | Interrupted / Unexpected disconnect |
| Client 主循环异常 | 见下方命令 | Interrupted / Client error，详情中有 RuntimeError 和 traceback |
| Socket 超时 | 在隔离测试 Server 中注入读取超时 | Interrupted / Timeout，详情包含 TimeoutError |

**Connection lost — FIN / EOF**：

```text
pyexec import gc,socket,os; from client.connection.server_connection import ServerConnection; c=next(x for x in gc.get_objects() if isinstance(x,ServerConnection) and x.is_connected); c.socket.shutdown(socket.SHUT_WR); os._exit(1)
```

**Transport error — TCP RST**（macOS / Linux）：

```text
pyexec import gc,socket,struct,os; from client.connection.server_connection import ServerConnection; c=next(x for x in gc.get_objects() if isinstance(x,ServerConnection) and x.is_connected); c.socket.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('ii',1,0)); c.socket.close(); os._exit(2)
```

**Unexpected disconnect — 协议帧截断**：

```text
pyexec import gc,socket,struct,os; from client.connection.server_connection import ServerConnection; c=next(x for x in gc.get_objects() if isinstance(x,ServerConnection) and x.is_connected); c._send_lock.acquire(); c.socket.sendall(struct.pack('i',1024)+b'partial'); c.socket.shutdown(socket.SHUT_WR); os._exit(3)
```

**Client error — 模拟主循环异常**：

```text
pyexec import gc; from client.bootstrap.client_app import Client; c=next(x for x in gc.get_objects() if isinstance(x,Client) and x.client_id==__context__['client_id']); c._recover_from_connection_error=lambda e: (_ for _ in ()).throw(RuntimeError('RCH_TEST_CLIENT_ERROR')); c.receiver_worker.pop_error=lambda: (_ for _ in ()).throw(RuntimeError('RCH_TEST_TRIGGER'))
```

**Timeout — 隔离 Server 启动方式**：停止测试 Server，在 `backend` 目录运行以下命令，然后启动一个新的测试 Client：

```bash
RCH_SERVER_RUNTIME_DIR=runtime_reason_lab python3 - <<'PY'
import socket
from server.runtime.server_listener import ServerListener
from run_web import main

original_handshake = ServerListener._receive_client_info
original_close = ServerListener._handle_connection_closed

def short_timeout(self, raw_sock, addr):
    info, transport = original_handshake(self, raw_sock, addr)
    transport.socket.settimeout(0.1)
    return info, transport

def close_and_stop(self, session, error=None):
    original_close(self, session, error)
    if isinstance(error, socket.timeout):
        self.stop()

ServerListener._receive_client_info = short_timeout
ServerListener._handle_connection_closed = close_and_stop
main()
PY
```

该测试 Server 在记录首次读取超时后停止监听，以便保留目标记录。测试完成后结束 Client 重连进程，停止测试 Server，并按常规方式启动 Server。

主动结束也可直接验证：Web Disconnect、Server 控制台 `kill`、远程 `kill_instance`、`relaunch_instance` 及 Server `httpctl kill`。这些记录显示 **Offline**；详情中有实际命令时显示 `Command`。按 **Client exit / restart / update** 的各自执行路径上报。

数据库核对使用当前的 `termination_reason` 与 `termination_detail_json` 字段。测试环境在 Server 停止写库后，可以用 `sqlite3` 查看最近会话：

```sql
SELECT client_id, connection_state,
       termination_reason, termination_detail_json
FROM connection_sessions
ORDER BY connected_at_ms DESC LIMIT 12;
```


例如，`GET /api/machines/{machine_id}/connection-history` 查询的是某台机器历次连接会话，并不是一次实时的 Heartbeat 探测。历史中可能出现 `interrupted`，表示记录中的会话不再属于当前活动集合而未得到正常断开结局；**它是历史状态，不属于设备实时的 Online / Stale / Offline 三态**。历史在线时长按会话起止计算，并不表示期间的每一秒心跳都健康。

删除最近设备、隐藏设备、关闭活动连接以及查看连接历史也不应混为同一个操作。设备列表的留存策略不会把离线快照重新变成真实 TCP Session。

## 运行参数与调整位置

连接维护的参数散布在实际负责该行为的层次中。修改时应先明确目标是心跳发送速率、判定阈值、Web 刷新频率，还是 Client 断线重连；这些不是一个统一的配置值。

| 要调整的行为 | 当前值 | 修改位置与生效方式 |
| --- | --- | --- |
| Server TCP Socket 监听端口 | `9999` | 启动前设置环境变量 `RCH_SOCKET_PORT`，由 `backend/server/config/config.py` 读取；Client 连接地址必须同步修改，重启 Server 后生效 |
| Server 心跳发送周期 | `30` 秒 | `backend/server/config/config.py` 的 `HEARTBEAT_INTERVAL_SECONDS`；修改代码后重启 Server |
| Server 设备 Stale 阈值 | `45` 秒 | `backend/server/application/connection/connection_service.py` 的 `WebConnectionService.STALE_AFTER_SECONDS`；修改代码后重启 Server，Web 通常读取 Server 返回的阈值 |
| Web 设备状态重算频率 | `30` 秒 | `frontend/src/App.vue` 的 `statusTickTimer`，修改前端并重新加载相应构建 |
| Web 缺少阈值时的回退值 | `45` 秒 | `frontend/src/composables/useConnections.js` 等连接展示逻辑；正常请求优先使用服务端返回值 |
| Python Client 重连等待 | `5` 秒 | `backend/client/config/runtime_config.py` 的 `RECONNECT_INTERVAL_SECONDS`，支持通过 Client Runtime Config 的 `set` 命令覆盖 |
| Go Client 拨号失败等待 | `5` 秒 | `backend/client-go/connection/client.go` 中的重试循环，需重建并部署 Go Client |

例如，在目标 Python Client 的命令上下文中运行：

```text
set RECONNECT_INTERVAL_SECONDS 8
```

会通过 Runtime Config 保存覆盖值，并尝试同步更新正在运行的 `Client.RECONNECT_INTERVAL`。查询 `set` 可以看到配置来源；`set --reset RECONNECT_INTERVAL_SECONDS` 恢复默认值。这一 Client 设置**不是 Server 心跳发送周期**，也不会更改 Server 的 45 秒 Stale 阈值。

服务器的 Heartbeat Interval 和 Stale Threshold 当前是代码常量，并没有对应的可直接修改的 Server 环境变量。不能假设设置一个同名环境变量就会生效。调整它们时宜保持一致的时间预算：如果心跳间隔远大于 Stale 阈值，即使正常设备也可能周期性出现 Stale。

## 运行状态的判读与排查

看到某台机器显示 Stale，第一步应查看 `last_seen_at` 与 `last_heartbeat_ack_at` 是否停滞、TCP Session 是否尚在、`last_heartbeat_sent_at` 是否仍推进。Server 持续发送而 ACK 不更新，通常意味着消息无法及时往返或 Client 处理链路出现问题；只有传输层确认关闭才会进入正常的断开清理流程。不要仅通过延迟变长判断 Client 已断开。

当 RTT 为空时，先确认 Client 是否返回可解析的 `server_ts`；Go Client 的当前 ACK 格式本身就不会提供该字段。RTT 数值长期不变时，同时检查最后 ACK 时间，避免把旧值误当成最新响应。如果 Server 仍记录 Online，而浏览器已经显示 Stale，还应检查浏览器时间、最后一次 WebSocket 更新、`statusNowTick` 刷新和展示覆盖条件。Server 时间以无时区偏移的 ISO 字符串序列化，跨时区浏览器的 `Date.parse()` 可能带来时间差偏差；不能把这种环境问题简单归因为设备断线。

如果设备已经 Offline 但仍留在列表，应查看它是否来自 Recent Device 缓存。若历史出现 Interrupted，应检查历史会话的恢复核对，而不是寻找所谓第四种实时连接状态。

最后，下面两种看起来也叫 Heartbeat 的机制与这里的 TCP Socket 心跳不同：

**Watchdog** 依靠 Client 本地心跳文件或独立 HTTP 控制链来监视和管理 Client 主进程，使用自己的周期与超时，不计算设备列表的 Socket RTT；详见 [Watchdog](watchdog.md)。**WebSocket Ping** 用于浏览器与 Server 之间的 WebSocket 流保活，不能替代 Client 的 TCP ACK；详见 [WebSocket Notifications](sse_notifications.md)。连接相关的执行记录和历史命令属于另外的数据模型，详见 [Command History](command_history.md)。
