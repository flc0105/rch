# Watchdog

> 本文主要描述既有 **Remote HTTP / Local Heartbeat Watchdog**；`watchdog` 状态查询和 Web 面板也展示独立的 Process Watchdog，详情请参阅 [Process Watchdog](process_watchdog.md)。

Watchdog Worker 是独立于 Client 主执行流程的进程控制组件。Remote HTTP 模式用于在主命令通道不可用时接受来自 Server 的进程控制请求；Local 模式依靠本机心跳判断 Client 是否失去响应，并按配置尝试恢复。两套控制条件可以单独启用，也可由同一个 Worker 共同承担。

这一机制追踪的是 Client 主进程的可达性和活性，并不等价于业务任务是否健康。理解它需要区分心跳线程、独立 Worker、HTTP 命令队列、进程重新启动和 Server 管理界面各自负责的状态。

## 守护进程与 Client 的运行关系

### Worker 的独立性与生命周期

每次启动 Client 都会生成一个新的 `client_id`。开启任意 Watchdog 模式后，Client 另外启动一个操作系统进程作为 Watchdog Worker，并向它传入原 Client 的 PID、启动命令、工作目录、`client_id`、监控开关与参数。

Worker 不需要通过 Client 的 Socket 命令执行器获取控制命令，因此即使 Client 的主命令通道卡住，Worker 仍可能运行、访问 Server Web 服务并对原 Client 执行进程操作。

```text
                         Server Web
            ┌────────────────────────────────┐
Web 按钮 ────┤  HTTP Control：保存待执行操作   │
HTTP POST ───┤  每个 client_id 一个待取命令槽   │
Server 命令 ─┘              │                 │
            └───────────────┼─────────────────┘
                            │ HTTP GET（取出即删除）
                            ▼
┌───────────────────── Client 设备 ─────────────────────┐
│                                                       │
│  Client 主进程                     Watchdog Worker     │
│  ├─ Socket / 主命令执行            ├─ Remote 轮询     │
│  └─ Local 心跳线程 ──写心跳文件───→ ├─ Local 检查      │
│                                   └─ 进程控制操作    │
│                                                       │
└───────────────────────────────────────────────────────┘
```

Remote 和 Local 的检查由同一个 Worker 循环依次执行：先确认原 Client PID 仍然存在，再检查 Remote，随后检查 Local，最后短暂休眠。循环的基础休眠时间为约 0.5 秒，但 Remote HTTP 请求本身可能等待最多 5 秒，所以 Local 检查不是严格固定间隔的实时调度。

**Worker 不是独立于 Client 生命周期的系统服务。** 它持续监控启动时记录的原 Client PID；当该 PID 已经不存在时，Worker 会退出。这意味着它并不能保证在 Client 完全崩溃或被强制杀死后自动将其拉起。Local 模式针对的主要是进程仍存在、但心跳已停止的情况。

HTTP Control 根据 `client_id` 而不是主机名、`machine_id` 或 PID 定位目标。同一台机器运行多个 Client 时，它们有不同的 `client_id` 和心跳文件。

`relaunch` 和 `clone` 都会启动一个新的 Client 实例，新的实例会生成新的 `client_id`。如果原实例已被替换，应从 Server 的当前连接列表取得新 ID，不能继续使用旧 ID 下发后续指令。

### 进程控制动作的差异

Worker 可执行三种进程操作，作用如下：

**Kill (`kill`)**

Worker 强制终止它所监控的原 Client，并在操作后退出。Linux/macOS 使用 `SIGKILL`；Windows 使用 `taskkill /PID ... /F /T`。该动作不会自动创建新 Client，适合明确需要结束旧实例的场景。

**Relaunch (`relaunch`)**

Worker 使用 Client 启动时保存的启动参数和工作目录，先创建一个新实例，短暂等待约 0.2 秒，然后强制终止旧实例并退出。其目的是替换原 Client，而不是同时长期保留两个实例。

这里的“启动新实例”不等于“新实例已成功连上 Server”。现有操作不会等待 Socket 握手完成，也不提供新 Client 健康确认；若新实例启动后立即失败，原 Client 仍可能已经被终止。

**Clone (`clone`)**

Worker 按相同的启动命令创建额外的 Client 实例，保留原 Client 继续运行，原 Worker 也继续工作。新实例有自己的 `client_id` 和 Watchdog 运行状态。这个操作会增加客户端实例数量，使用前应确认重复运行不会造成业务冲突。

以上操作都在 **Client 所在设备**由 Worker 执行；Server 只负责保存待执行命令。

## 独立 HTTP 控制链

### 命令投递与结果回执

Remote 开启后，Worker 周期性访问：

```http
GET /api/connections/<client_id>/control
```

访问地址由 Client 的 Server Web 连接配置决定，包括 `server_web_scheme`、`server_web_host` 和 `server_web_port`。它访问的是 **Web HTTP 服务**，而不是主 Socket 端口。Worker 使用 HTTP GET，单次请求超时为 5 秒，轮询周期由 `REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS` 决定。

Server 允许通过 Web UI、Server 内置命令或 HTTP POST 提交控制动作：

```http
POST /api/connections/<client_id>/control
Content-Type: application/json
Authorization: Bearer <API_TOKEN>

{"command":"relaunch"}
```

该 POST 负责**入队**，不是直接在 Server 上运行命令。Remote Worker 下一次 GET 时会取得当前动作，随后在 Client 设备上执行。

### HTTP 接口和任务队列

Server 为每个 `client_id` 维护一个内存中的待执行命令槽。入队记录的结构为：

```json
{
  "client_id": "<CLIENT_ID>",
  "command": "relaunch",
  "created_at": "<Server 生成的时间字符串>"
}
```

这套机制有以下行为：

- **同一个客户端最多保留一条未取走的指令。** 如果连续提交 `kill` 和 `clone`，Worker 取走之前后一次提交会覆盖前一次，不是 FIFO 队列。
- **GET 会取走并删除指令。** 不应手工调用上述 GET 来“查看队列”，否则会把指令提前消费，真正的 Worker 可能收不到。
- **POST 返回成功表示已经入队。** 它不能证明 Worker 已收到，更不能证明进程操作成功；当前没有执行回执或 ACK。
- **队列不持久化。** Server 进程重启可能丢失尚未取走的命令；Worker 取走后执行失败也不会自动重新入队。多进程部署之间的内存槽位不共享。

例如，对一个无法响应 Socket 命令的 Client 提交 `relaunch`，HTTP POST 可能立即返回成功，但必须继续观察 Worker 日志以及新旧进程和连接状态，才能知道是否完成替换。

HTTP 控制相关接口及权限如下：

| 接口 | 作用 | 权限 |
| --- | --- | --- |
| `GET /api/httpctl/actions` | 获取 `kill`、`relaunch`、`clone` 的动作名称及描述，用于展示可用操作 | 需认证 |
| `POST /api/connections/<client_id>/control` | 给指定 Client 存入一条待执行动作 | 需认证 |
| `GET /api/connections/<client_id>/control` | Worker 获取并消费当前待执行动作 | 允许匿名访问 |

POST 的请求体使用 `command` 字段，只接受 `kill`、`relaunch`、`clone`，其他动作会被拒绝。服务端在识别动作时会忽略前后空格和大小写。

管理员 API Token 可以通过 `Authorization: Bearer <TOKEN>`、`X-Auth-Token` 或 `X-API-Token` 提交。也支持项目已有的管理员登录 Session 机制。不要将 Token 写入项目文件、提交到版本库，或在共享终端历史中留下明文。

**匿名 GET 是为了让独立 Worker 无需管理员登录即可轮询。** 但这也意味着能访问该地址并知道 `client_id` 的请求方可能提前消费控制命令。应通过网络访问控制限制 Server Web 接口的暴露范围，不能把匿名取命令接口视为安全的公开状态查询服务。

### Server 端管理入口

也可以在 Server 控制台操作：先选中目标 Client 连接，再执行 `httpctl`。该命令会使用当前选中连接的 `client_id`，无需手动填写 ID。

```text
httpctl relaunch
```

这会为当前选中实例安排一次替换操作：Worker 取到命令后启动新的 Client，再终止旧实例。适合尝试恢复主命令通道卡住的 Client；新 Client 上线后需要重新确认其身份和连接状态。

```text
httpctl clone
```

这会要求 Worker 再启动一个 Client，而旧 Client 保持运行。适合需要临时并行实例的情况；因为两个实例可能同时运行任务，不能把它当作无副作用的连通性检查。

```text
httpctl kill
```

这会要求 Worker 强制终止选中的 Client，不自动拉起替代实例。只应在确定可以终止该实例时执行。

Server 控制台命令需要有可选中的目标连接；如果目标已完全离线且无法选中，使用指定 `client_id` 的 HTTP POST 更直接。无论通过哪个入口提交，都适用“每客户端一个命令槽”和“入队不等于执行”的规则。

## 本地心跳与进程恢复

### 心跳失活条件

开启 `LOCAL_WATCHDOG_ENABLED` 后，Client 主进程会启动单独的心跳线程，定期更新系统临时目录中的 JSON 文件。心跳内容示例：

```json
{
  "ts": 1790000000.0,
  "pid": 12345,
  "client_id": "<CLIENT_ID>"
}
```

这里 `ts` 是 Unix 秒级时间戳，`pid` 是 Client 主进程 PID，`client_id` 是当前实例标识。每个实例使用不同的心跳文件名：

```text
<系统临时目录>/client_local_watchdog_heartbeat_<client_id>.json
```

每次写入先生成临时文件，再原子替换正式文件，尽量避免 Worker 在文件写入到一半时读到不完整 JSON。写入失败会记录在 Local 日志中；心跳线程仍会在下一个周期继续尝试写入。

Worker 读取心跳文件中的 `ts`，用当前时间与最后一次心跳时间的差值计算心跳年龄：

```text
heartbeat_age_seconds = max(当前 Unix 时间 - ts, 0)
```

当心跳年龄**严格大于** `LOCAL_WATCHDOG_TIMEOUT_SECONDS`，Worker 会记录超时并尝试执行 `relaunch`：先启动新 Client，再终止旧 Client。

| 心跳状态 | 处理结果 |
| --- | --- |
| 文件不存在 | 跳过本次检查；仅文件缺失不会触发重启 |
| 文件无法读取、JSON 无效或 `ts` 无效 | 跳过或记录错误，不按超时进行恢复 |
| 心跳年龄小于或等于超时阈值 | 视为正常；解除之前的超时触发标记 |
| 心跳年龄大于超时阈值 | 首次检测到持续超时时尝试恢复；不在同一次持续超时期间反复拉起进程 |

### 恢复动作的时间界限

心跳来自 Client 的**独立线程**，并不直接代表业务线程、命令执行器或 Socket 通道工作正常。因此：

- 主命令执行卡住、但心跳线程仍可正常写入时，Local 不会重启；这种情况可以使用 Remote HTTP 控制。
- 整个 Client 被 `SIGSTOP` 暂停时，心跳线程也会停止；只要 Worker 仍在运行，就可能在超时后执行替换。
- Client 被 `SIGKILL` 直接终止时，Worker 先发现原 PID 不存在并退出，不能据此期待 Local 自动复活 Client。
- 若 Remote 与 Local 同时开启，Local 有可能先于人工提交的 HTTP 控制触发替换；进行单一模式的故障演练时应关闭另一模式。

默认心跳发送周期为 5 秒，超时阈值为 15 秒。这里的超时指**从心跳时间戳算起**，不是从故障开始计时 15 秒后保证完成重启。检测时序还受 Worker 检查循环、Remote HTTP 请求等待以及操作系统调度影响。

Local 的心跳间隔下限为 0.5 秒，监控超时下限为 1 秒。实际生效值应通过 `watchdog --json` 查看。

## 运行配置与启停操作

### 控制开关的生效时间

| 配置项 | 默认值 | 含义 | 普通 `set` 修改 |
| --- | --- | --- | --- |
| `REMOTE_HTTP_WATCHDOG_ENABLED` | `false` | 是否启用独立 HTTP 远程控制 | 支持 |
| `REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS` | `15` | Remote HTTP 轮询间隔，单位秒 | 不支持 |
| `LOCAL_WATCHDOG_ENABLED` | `false` | 是否启用本地心跳及超时恢复 | 支持 |
| `LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS` | `5` | Client 写入心跳文件的周期，单位秒 | 不支持 |
| `LOCAL_WATCHDOG_TIMEOUT_SECONDS` | `15` | 心跳超过多少秒未更新时触发恢复 | 不支持 |

两个模式的开关可以从 Client 命令通道用 `set` 在线修改。三个时间参数能够在配置查询中查看，但不对普通的 `set KEY value` 开放；**能被 `set --all` 列出，并不意味着能够直接在线修改**。

运行时配置的差异项保存在外部 `runtime_config.json`。通过 `RUNTIME_CONFIG_PATH` 可以指定文件位置；未指定时使用操作系统对应的默认位置：

| 系统 | 配置位置 |
| --- | --- |
| Windows | `%APPDATA%/rchclient/runtime_config.json` |
| macOS | `~/Library/Application Support/rchclient/runtime_config.json` |
| Linux | `~/.config/rchclient/runtime_config.json` |
| iOS | `~/Documents/.rchclient/runtime_config.json` |

### 操作状态和重置

要**启用 Watchdog**，按需要执行其中一行或两行：

```text
set REMOTE_HTTP_WATCHDOG_ENABLED true
set LOCAL_WATCHDOG_ENABLED true
```

第一行开启独立 Worker 的 Remote HTTP 轮询；第二行开启 Client 心跳线程和 Worker 的 Local 超时检查。只需远程控制时执行第一行，只需本地恢复时执行第二行。更改开关后，Client 会停止原来的 Watchdog 组件，并按新配置重新启动，无需重启整个 Client。Remote 和 Local 同时启用时也只需要一个 Worker。

关闭 Watchdog 时使用相同的配置项，将值设为 `false`：

```text
set REMOTE_HTTP_WATCHDOG_ENABLED false
set LOCAL_WATCHDOG_ENABLED false
```

仅关闭一个模式时，另一个模式仍继续运行；两个模式都关闭后则不再需要独立 Worker。关闭 Local 会停止心跳线程，但已经生成的心跳文件和日志不会自动删除。

查询状态、排查问题时使用：

```text
watchdog
watchdog --json
set --all
```

`watchdog` 返回便于阅读的当前状态；`watchdog --json` 返回同样的结构化状态。顶层按 `client`、`remote_watchdog`、`local_watchdog`、`process_watchdog` 分组，第二层才是各项具体信息，字段不再重复所属 Watchdog 前缀；秒数统一使用 `_seconds`。`set --all` 仍可查看运行时配置，包括不支持普通 `set` 修改的三个 Remote/Local 时间参数；这些查询都不改变配置。

`watchdog` 的**普通文本输出**与 `set` 分组列表一致：每个对象显示为 `[client]`、`[remote_watchdog]`、`[local_watchdog]`、`[process_watchdog]` 标题，下面逐行输出 `字段 = 值`，组之间留空行；不会把第二层对象直接打印成 Python 字典。比如：

```text
[client]
id = example-client
pid = 1234

[remote_watchdog]
enabled = True
worker_pid = 2345
worker_alive = True
...

[local_watchdog]
enabled = True
...

[process_watchdog]
enabled = True
supervisor_pid = 3456
supervisor_alive = True
poll_interval_seconds = 0.5
...
```

以上为显示格式示意，省略号表示未展示的其他字段，实际命令会输出每个分组的全部字段。`watchdog --json` 仍输出下文所示的两层 JSON 对象；文本展示改变不影响字段名称、JSON 结构或 `info → Watchdog` 界面。

Remote 启用后应检查 `remote_watchdog.worker_alive`、`remote_watchdog.worker_pid`、`remote_watchdog.control_url` 和轮询日志；Local 启用后应检查 `local_watchdog.feeder_alive`、心跳文件更新及共用 Worker 状态；Process 启用后应检查 `process_watchdog.supervisor_alive` 和独立 PID。仅有 `enabled=true` 不保证恢复链路已经健康。命令查询仍依赖 Client 主命令通道，命令通道卡住不等于各独立进程必然退出。

需要恢复两个开关的默认值时使用：

```text
set --reset REMOTE_HTTP_WATCHDOG_ENABLED
set --reset LOCAL_WATCHDOG_ENABLED
```

每一行只清除对应开关的运行时覆盖值；当前默认值均为关闭。只需重置一个模式时执行对应一行即可，新的值会立即应用到 Watchdog 组件。

以上 `set` 和 `watchdog` 都是 **Client 命令通道内置命令**，不能直接作为普通操作系统 Shell 命令执行。

## 守护状态与控制台观测

### 状态字段的含义

`watchdog --json` 使用四个顶层对象，每个对象内部只放直接属性，不再有第三层。下列 JSON 仅示意结构（PID、地址、间隔均非当前机器的实测值）：

```json
{
  "client": {
    "id": "example-client",
    "pid": 1234
  },
  "remote_watchdog": {
    "enabled": true,
    "worker_pid": 2345,
    "worker_alive": true,
    "control_url": "https://server.example/api/connections/example-client/control",
    "interval_seconds": 15,
    "log_path": "/tmp/client_remote_watchdog.log"
  },
  "local_watchdog": {
    "enabled": true,
    "worker_pid": 2345,
    "worker_alive": true,
    "heartbeat_interval_seconds": 5,
    "timeout_seconds": 15,
    "heartbeat_file_path": "/tmp/client_local_watchdog_heartbeat_example-client.json",
    "log_path": "/tmp/client_local_watchdog.log",
    "feeder_thread_name": "LocalWatchdogHeartbeatFeeder",
    "feeder_alive": true
  },
  "process_watchdog": {
    "enabled": true,
    "supervisor_pid": 3456,
    "supervisor_alive": true,
    "poll_interval_seconds": 0.5,
    "log_path": "/example/runtime_config/process_watchdog.log"
  }
}
```

| 字段 | 含义 |
| --- | --- |
| `client.id` | 当前 Client 标识，用于 HTTP Control 路由 |
| `client.pid` | Client 主进程 PID |
| `remote_watchdog.enabled` | Remote 开关 |
| `remote_watchdog.worker_pid` / `worker_alive` | Remote/Local 共用 Worker 的 PID 和存活状态 |
| `remote_watchdog.control_url` | Remote HTTP GET 轮询地址 |
| `remote_watchdog.interval_seconds` | Remote HTTP 轮询配置间隔（秒） |
| `remote_watchdog.log_path` | Remote 日志位置 |
| `local_watchdog.enabled` | Local 开关 |
| `local_watchdog.worker_pid` / `worker_alive` | 与 Remote 相同的共用 Worker；不是另一个进程 |
| `local_watchdog.heartbeat_interval_seconds` | Client 心跳写入间隔（秒） |
| `local_watchdog.timeout_seconds` | 心跳超时阈值（秒） |
| `local_watchdog.heartbeat_file_path` | 当前 Client 的心跳文件 |
| `local_watchdog.log_path` | Local 日志位置 |
| `local_watchdog.feeder_thread_name` / `feeder_alive` | 本机心跳线程名称和存活状态 |
| `process_watchdog.enabled` | Process Watchdog 开关 |
| `process_watchdog.supervisor_pid` / `supervisor_alive` | 独立进程复活 Supervisor 的 PID 和存活状态 |
| `process_watchdog.poll_interval_seconds` | Supervisor 正常进程存活探测间隔（秒），当前由源码常量控制 |
| `process_watchdog.log_path` | Process Supervisor 日志位置 |

`worker_alive` 或 `supervisor_alive` 为 `true` 只说明相应进程仍被检测为存活，不意味着网络命令已交付、心跳恢复已完成或新 Client 已连接 Server。状态查询不会将不再使用的扁平字段作为额外兼容输出。Process 扫描算法、修改检查间隔的方法及生命周期边界详见 [Process Watchdog](process_watchdog.md)。

### 浏览器中的控制与显示

在 Web 管理页面的连接详情中打开 **Watchdog** 选项卡，可以分别查看 Process recovery、Remote / Local 的启用状态和监督进程：Process 独占一行，Remote / Local 保持双列（窄屏单列），日志路径在诊断区域。原有底部 HTTP 控制按钮仍专门对应 Remote Worker。

**切换 Remote / Local** 时，Web 服务会经正常 Client 命令通道修改相应配置，并重新初始化 Watchdog。目标 Client 已离线或命令通道不可用时，这类开关操作可能失败。

**点击 Kill / Relaunch / Clone** 时，界面先要求确认，再通过 HTTP Control 将动作放入 Server 待执行槽位。它不直接依赖 Client 当前能否处理普通命令，因此即便状态查询失败，仍可能成功入队；但实际执行必须依靠原有 Remote Worker 持续运行并可访问 Server。

Web 页面提示动作已发送或已入队，只能视为 Server 接受了指令。应通过 Client 进程变化、重新连接情况和 Watchdog 日志确认最终效果。

## 失效模式及恢复路径

Watchdog 使用 Client 设备上的系统临时目录，默认名称如下：

```text
<系统临时目录>/client_remote_watchdog.log
<系统临时目录>/client_local_watchdog.log
<系统临时目录>/client_local_watchdog_heartbeat_<client_id>.json
```

Remote 日志用于查看 HTTP 请求失败、收到远程指令和控制动作；Local 日志用于查看心跳写入失败、超时检测和恢复请求。前两个日志名称不含 `client_id`，同一机器多个实例可能写入同一文件；心跳文件则按 `client_id` 区分。查看多实例日志时，结合记录中的 Client ID 定位目标。

Linux/macOS 上可以使用 `tail -f` 持续观察日志，例如：

```bash
tail -f /tmp/client_remote_watchdog.log
```

这条命令持续打印 Remote 日志新增内容，适合核对 Server 是否已被轮询、动作是否被领取及 HTTP 是否报错。`/tmp` 只是常见示例，实际路径应使用 `watchdog --json` 返回的 `remote_watchdog.log_path`。

```bash
tail -f /tmp/client_local_watchdog.log
```

这条命令用于观察心跳超时与重启请求。实际路径同样以 `local_watchdog.log_path` 为准；只看到超时请求并不意味着新 Client 一定启动成功，还应核实进程与 Server 连接列表。

常见异常可以结合状态字段、日志与进程行为定位：

| 现象 | 先看什么 | 处理方向 |
| --- | --- | --- |
| 已开启 Remote，但没有 Worker PID | `remote_watchdog.worker_pid`、`remote_watchdog.worker_alive`、启动错误 | 确认 Worker 是否成功创建，或配置切换后是否成功重建 |
| HTTP Control 入队成功却没有任何操作 | `remote_watchdog.control_url`、Remote 日志、旧 PID | 检查 Worker 存活、Server Web 可达性，以及命令是否被其他 GET 提前消费 |
| HTTP POST 返回 401 | 请求认证头和 Token | POST 需要管理员权限，不能套用 Worker 匿名 GET 的规则 |
| `watchdog` 查询失败，控制按钮仍能入队 | Client Socket 与 Remote Worker | 查询和控制使用两条通道，分别排查 |
| Local 已开启但没有正常心跳 | `local_watchdog.feeder_alive`、心跳文件时间戳、Local 日志 | 检查心跳线程和文件写入是否正常；缺文件本身不会触发重启 |
| 业务无响应但 Local 不触发 | 心跳 JSON 中的 `ts` 是否继续更新 | 业务线程阻塞时心跳线程可能仍活跃，可使用 Remote 控制 |
| Client 完全退出后没有自动拉起 | 原 PID 和 Worker PID | 原 Client 消失时 Worker 也会退出，Local 不承担进程死亡后的持续守护 |
| Relaunch 后旧 ID 无法再操作 | Server 的当前连接列表 | 新实例具有新的 `client_id`，应重新选择或取得新 ID |
| Remote 与 Local 同时开启时提前重启 | 两套日志、心跳时间戳 | 检查是否是 Local 先检测到超时 |

若 Worker 使用的启动命令、工作目录或环境依赖已经变化，`relaunch` / `clone` 新建的进程也可能启动失败。恢复机制本身不负责自动补齐依赖或修复配置错误。

## 验证守护链路的方法

### 控制请求的验证

以下命令适用于具备操作权限、允许中断的 **Linux/macOS Client**。`curl` 在能访问 Server Web 的终端运行，`kill -STOP` 和 `kill -CONT` 必须在 **Client 所在设备**的 Shell 中运行。Windows 不使用这里的 POSIX 信号命令。

**开始前先在 Client 命令通道执行 `watchdog --json`，记录真实的 `client.id`、`client.pid`、`remote_watchdog.worker_pid`、`remote_watchdog.control_url` 和 `local_watchdog.timeout_seconds`。** 一定要区分 Client 主进程与 Worker PID，暂停主进程时不要误操作 Worker。

使用 `curl` 前，先在能够访问 Server Web 的终端设置地址与目标 Client ID，再交互输入管理员 API Token：

```bash
SERVER_BASE_URL='http://127.0.0.1:8085'
CLIENT_ID='<watchdog --json 中的 client_id>'
read -r -s -p '管理员 API Token: ' ADMIN_API_TOKEN; echo
```

`SERVER_BASE_URL` 是能从执行 `curl` 的机器访问到的 Server **Web HTTP** 地址。`127.0.0.1:8085` 仅适用于 HTTP 服务恰好运行在本机该端口的情况；跨主机测试必须替换为实际 IP/域名和端口。

`CLIENT_ID` 必须是当前目标实例 `client.id` 对应的 `client_id`，不能填写主机名或 PID。`read -s` 用交互输入方式读取管理员 API Token，减少 Token 明文出现在命令行历史中的机会。

先检查 HTTP 服务可访问、Token 能通过认证：

```bash
curl -sS -i \
  -H "Authorization: Bearer ${ADMIN_API_TOKEN}" \
  "${SERVER_BASE_URL}/api/httpctl/actions"
```

这条 GET 仅获取 Server 支持的控制动作，不会消费某个 Client 的待执行命令。`-i` 会输出 HTTP 状态头，便于区分连接失败、认证失败和正常响应。若返回 401，先检查 Token；若连接失败，先检查 Server Web 地址与网络访问。

向指定 Client 提交 HTTP Control 使用同一个 POST 地址。下面以 `clone` 为例：

```bash
curl -sS -i -X POST \
  "${SERVER_BASE_URL}/api/connections/${CLIENT_ID}/control" \
  -H "Authorization: Bearer ${ADMIN_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"command":"clone"}'
```

该命令将 `clone` 写入目标 Client 的待执行槽位。Worker 下一次轮询收到后，会在目标设备上新增一个 Client，原实例保持运行。它适合检查“入队 → 轮询 → 执行”的完整链路，但不是无副作用的 ping：成功后会真的多出一个进程。

请求头中的 Bearer Token 用于通过 POST 鉴权，`Content-Type` 表示 JSON 请求体，`-i` 可看到 HTTP 状态码。正常响应中的 `code=0` 仅表示 Server 已接受命令；实际执行结果还需查看 Remote 日志和新旧进程。

如果希望**替换**当前 Client，将请求体改为：

```json
{"command":"relaunch"}
```

这会先启动新 Client，再强制终止旧 Client。若希望**终止但不重启**，则使用：

```json
{"command":"kill"}
```

三种动作使用同一个 POST 地址，不需要更换 API 路由。发送下一条动作前，应确认上一条已经被 Worker 取走或已完成，避免在单命令槽中覆盖尚未领取的动作。

### 挂起时的恢复条件

暂停 Client，再从 HTTP 远程恢复。这可以验证主进程已经停止执行普通命令时，独立 Worker 仍能从 Server 接收 `relaunch`。

先在 **Client 命令通道**执行：

```text
set LOCAL_WATCHDOG_ENABLED false
set REMOTE_HTTP_WATCHDOG_ENABLED true
watchdog --json
```

第一行关闭 Local，避免本地心跳超时抢先执行重启。第二行启用 Remote。第三行重新查询并确认 `remote_watchdog.enabled=true`、`remote_watchdog.worker_alive=true`，记下**最新**的 `client.pid` 和 `client.id`。不要沿用已经经历过 Relaunch 的旧实例信息。

随后在 **Client 设备的 Shell** 中执行：

```bash
CLIENT_PID=12345
ps -p "$CLIENT_PID" -o pid,ppid,stat,command
kill -STOP "$CLIENT_PID"
ps -p "$CLIENT_PID" -o pid,ppid,stat,command
```

将 `12345` 改为刚查询的真实 `client.pid`。第一条 `ps` 在执行前核对 PID 和命令行，确认确实是要操作的 Client；`kill -STOP` 向这个 PID 发送 `SIGSTOP`，暂停 Client 进程及其线程，而不是终止它；第二条 `ps` 用于观察暂停后的进程状态。独立 Worker 是另一个 PID，因此不会被这条正 PID 的 STOP 命令一起暂停。

当主 Client 处于暂停状态时，在**能访问 Server Web 的另一终端**发送：

```bash
curl -sS -i -X POST \
  "${SERVER_BASE_URL}/api/connections/${CLIENT_ID}/control" \
  -H "Authorization: Bearer ${ADMIN_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"command":"relaunch"}'
```

预期顺序是：Server 接收 `relaunch` → Worker 下一次 Remote 轮询领取命令 → 新 Client 启动 → 旧的暂停 PID 被强制终止 → 新实例以新的 `client_id` 尝试建立连接。可以通过 Remote 日志、`ps` 和 Server 连接列表交叉确认。不要仅因 HTTP 200 就认定恢复成功。

**如果命令未执行，或者决定中止实验，而旧 Client PID 仍存在**，在 Client 设备的 Shell 恢复它：

```bash
kill -CONT "$CLIENT_PID"
```

`SIGCONT` 会使原先被 STOP 的进程恢复运行；如果旧 PID 已因 Relaunch 消失，可能出现 `No such process`，此时应核查新实例，而不是对猜测的 PID 重复操作。注意 `kill -STOP "$CLIENT_PID"` 使用正 PID，不要写成负 PID 以免误作用于进程组。

### 心跳停止的恢复行为

暂停心跳，等待超时后自动替换 Client。这可以验证心跳线程停摆时，Worker 是否会根据超时阈值尝试重新启动 Client，整个过程不需要 HTTP Control。

先在 **Client 命令通道**执行：

```text
set REMOTE_HTTP_WATCHDOG_ENABLED false
set LOCAL_WATCHDOG_ENABLED true
watchdog --json
```

关闭 Remote 用来排除远程控制动作的干扰；启用 Local 会启动心跳线程和 Worker。确认 `local_watchdog.feeder_alive=true`、`local_watchdog.worker_alive=true`，记下 `client.pid`、`local_watchdog.timeout_seconds`、`local_watchdog.heartbeat_file_path` 和 `local_watchdog.log_path`。

在 **Client 设备 Shell** 中执行：

```bash
CLIENT_PID=12345
ps -p "$CLIENT_PID" -o pid,ppid,stat,command
kill -STOP "$CLIENT_PID"
```

这里同样要使用**本次**查询得到的 `client.pid`。暂停后，Client 的心跳线程也停止更新 JSON，但 Worker 仍继续运行。超过心跳超时阈值，并经过 Worker 的下一次检查后，Local 应记录超时并尝试 Relaunch。

观察 `local_watchdog.log_path` 里的超时与恢复记录，同时确认旧 PID 是否终止、新 Client 是否出现。若测试中止或恢复未发生且旧 PID 仍存在，及时执行：

```bash
kill -CONT "$CLIENT_PID"
```

这一步只能说明“进程还存在、但心跳停止”的场景可以被检测；它**不能**证明 `kill -9` 把 Client 完全终止之后仍可自动恢复。

### 测试后的现场清理

实验结束后，如不再需要 Watchdog，在**当前仍在运行的 Client 实例**的命令通道执行：

```text
set REMOTE_HTTP_WATCHDOG_ENABLED false
set LOCAL_WATCHDOG_ENABLED false
watchdog
```

前两行分别关闭 Remote 和 Local；最后一行确认生效状态。若执行了 Relaunch，应该选中新 Client 再运行这些命令，而不是继续操作旧的 `client_id`。

在执行过 HTTP 请求的 Shell 中清除保存的 Token 变量：

```bash
unset ADMIN_API_TOKEN
```

这会从当前 Shell 环境删除该变量；不会撤销 Server 端 Token，也不能清除之前已经记录在外部日志中的凭据。
