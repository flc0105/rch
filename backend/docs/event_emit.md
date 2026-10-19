# Device Events

Device Event 是由 Client 运行中的业务逻辑主动报告给 Server 的结构化事实。Script 和 Background Job 负责判断事件何时发生，并调用 SDK 发送类型、载荷和消息；Server 在接收端规范化字段，随后将它作为 `device_event` 发布到 WebEventBus。

业务事件从生产到展示经过多层处理。发送请求完成与通知生成、SQLite 留存、浏览器 Toast 展示之间不存在一一对应的成功承诺；通知投影和实时消费由独立的通知机制承担。

## 从设备业务逻辑到事件总线

Script / Background Job 在目标 Client 内调用 `events.emit()`，SDK 根据当前执行上下文生成 Device Event，再通过 HTTP POST 向 Server 提交。Server 校验 Client 身份字段、事件类型和数据格式，规范化后通过 `WebEventBus` 发布统一的 `device_event` 事件。

```text
Script / Background Job
    ↓ events.emit(kind, data, message)
Client SDK · 创建 Device Event
    ↓ HTTP POST /api/device-events
Server · 校验、规范化
    ↓ WebEventBus.publish("device_event", ...)
Web 实时订阅者 / NotificationEventProjector
    ↓
Toast、Notification Center、其他事件消费者
```

SDK 使用的是一次 HTTP 请求，**不是 Client 自己保持一个 SSE 连接**。SSE 是 Server 向浏览器或其他通知消费者主动推送事件的下游机制。其他 Server 业务也可以直接发布事件，不需要经过 Device Event 的 HTTP 接口。

Event Emit 与普通命令的执行结果流相互独立：Script / Job 可以在执行过程中多次发送事件，而不是只能在任务退出时上报一次。

## 事件生产者的调用上下文

在 Script SDK 中显式导入 `events`，然后调用：

```python
from client.runtime.sdk import events

events.emit(
    'app.process.started',
    data={
        'pid': 12345,
        'name': 'ExampleApp',
    },
    message='Process started: ExampleApp',
)
```

这条调用将事件类型设为 `app.process.started`，通过 `data` 提供可供其他消费者处理的结构化内容，通过 `message` 提供适合直接展示的描述。`pid`、`name` 只是业务字段，SDK 不会把它们解释成固定的系统事件类型。

Background Job 使用相同的 SDK，例如周期性监视某项条件时，只在条件首次满足或发生状态变化时发送事件：

```python
from client.runtime.sdk import events

# 以下片段可放在 Job 的状态检测逻辑中。
if newly_detected:
    try:
        events.emit(
            'storage.volume.attached',
            data={'mount_point': mount_point},
            message=f'Volume attached: {mount_point}',
        )
    except Exception as exc:
        self.send_to_server(0, f'Event emit failed: {exc}', 0)
```

事件发送是同步 HTTP 调用，网络延迟会影响当前调用线程；SDK 请求超时为 **10 秒**。如果事件只是辅助通知，不应让它意外终止长时间运行的监控任务，通常应像上例一样捕获异常，并由 Job 自己决定重试、记录或忽略。本机制没有自动持久化离线待发队列。

SDK 需要有效的 Script SDK Client 上下文，调用前会取得当前 `client_id`。没有活动上下文时，`events.emit()` 会抛出 `RuntimeError`。它并不是脱离 Client 后仍能使用的通用 Python 日志 API。

### 返回语义与参数契约

| 参数 | 含义 | 行为 |
|---|---|---|
| `kind` | 事件业务类型 | 必填，先去除两侧空白并转为小写 |
| `data` | JSON 对象形式的业务数据 | 可选，默认空对象；不能传列表或普通字符串 |
| `message` | 面向人阅读的摘要 | 可选，转换成字符串并去除两侧空白 |

SDK 返回 Server 的 API 响应对象；HTTP 失败或 API 错误会由 Client 的 HTTP 封装抛出异常。它不是一个包含“用户是否看见通知”信息的回执。

## 线上事件载荷的约束

SDK 自动为每次上报构造类似下面的事件对象。以下 ID、设备名和时间仅为结构示例：

```json
{
  "schema_version": 1,
  "event_id": "e2a75f2604a74f2f8a90e8fd0cc714af",
  "client_id": "client-example",
  "hostname": "workstation",
  "kind": "app.process.started",
  "occurred_at": "2026-10-16T09:00:00Z",
  "source": {
    "type": "job",
    "id": "job-instance-id",
    "name": "process_watcher"
  },
  "data": {
    "pid": 12345,
    "name": "ExampleApp"
  },
  "message": "Process started: ExampleApp"
}
```

| 字段 | 作用 |
|---|---|
| `schema_version` | 当前事件封装使用的版本字段，Server 当前规范化为 `1` |
| `event_id` | Device Event 本身的标识；SDK 为本次上报生成 UUID |
| `client_id` | 事件所属 Client 连接实例 |
| `hostname` | 设备名称；Server 优先使用当前连接会话里的主机名 |
| `kind` | 业务事件类型，例如 `app.process.started` |
| `occurred_at` | 发生时间；SDK 使用 UTC ISO 8601 字符串 |
| `source` | 发出事件的 Script、Job 或其他 SDK 上下文 |
| `data` | 业务自定义 JSON Object |
| `message` | 可读摘要，可省略 |

`source` 由 SDK 根据执行上下文生成，包含 `type`、`id`、`name`。若上下文已有 `source_type`、`source_id`、`source_name`，优先使用这些值；否则结合当前 Script 名称、Job ID 和 Job 名称推导。不需要在每次 `emit()` 时手动组装来源字段。

`data` 应放机器可读的结构化字段，`message` 则保持简洁。不要把整段日志或大量二进制内容直接放入事件；超过服务端限制的事件会被拒绝。

### 事件类型的规范化与验证

Server 会将 `kind` 转换为小写，要求以字母或数字开头，后续只允许小写字母、数字、`_`、`.` 和 `-`，长度最多 **128 字符**。例如 `app.process.started` 合法；包含空格或斜杠的类型不合法。

此外，Server 的约束包括：

- `client_id` 必须存在，并且 Server 能通过它找到目标连接；只写一个不存在的 ID 不会产生有效的 Device Event。
- `data` 必须是对象；缺失或为 `null` 时按 `{}` 处理。
- `source.type` 最长 64 字符，`source.id`、`source.name` 最长 128 字符。
- `event_id` 最多取 128 字符；如未提供，Server 会生成一个。
- `occurred_at` 最多取 64 字符；如未提供，Server 使用当前 UTC 时间。
- `message` 最多保留 1000 字符。
- 规范化事件经 JSON 序列化后的**字符数**不能超过 `64 × 1024`，超限报错。

事件中的时间和来源用于表达业务上下文，并不意味着 Server 对这些字段做了独立的可信时间源或来源真实性验证。

## 接收、校验与发布

SDK 上报使用：

```http
POST /api/device-events
Content-Type: application/json
```

开发时也可以直接构造请求，例如在能够访问 Server 的受控环境中：

```bash
SERVER_URL='http://127.0.0.1:8085'
CLIENT_ID='替换为当前在线的 client_id'

curl -sS -X POST "$SERVER_URL/api/device-events" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CLIENT_ID\",\"kind\":\"app.process.started\",\"data\":{\"pid\":12345},\"message\":\"Process started\"}"
```

此命令向 Server 提交一条 Device Event，并不在远端创建进程。Server 返回标准 API 响应，成功时响应 `data` 是规范化后的事件。需要让设备当前处于在线状态，因为接入逻辑会按 `client_id` 检查连接。

当前该 HTTP 路由允许匿名访问，**请求中的 `client_id` 不能被视为已验证的调用者身份**。Server 主要验证内容格式并核对目标连接，没有在该路由为请求方与 Client 身份建立强制绑定。部署时应结合实际网络边界控制可访问者，不应把接口直接当作经过强身份认证的设备签名通道。

Server 接受事件后统一执行：

```python
web_event_bus.publish('device_event', event)
```

浏览器订阅的 SSE 事件类型始终是 `device_event`；`app.process.started` 是该事件的数据字段 `kind`。两者不是同一层的名称。需要为某种 `kind` 定制通知时，应在通知投影或前端展示规则中明确处理，而不是期待任意新的 `kind` 自动获得专用图标和标题。

事件会发布给在线 SSE 订阅者；Server 中的通知投影还可能把它写成可持久化的 Notification Center 记录。一次上报被成功接收，仅证明它进入了当前 Server 的事件处理流程，不能保证浏览器已经接收、通知偏好允许显示或用户已读。

### 从命令完成记录产生事件

除了 Script SDK，Server 的 `notify` 内置命令也会通过同一条 Device Event 管线发送“命令完成”事件。

```text
notify shell sleep 10
```

该命令先按现有 Client 命令执行机制运行内部的 `shell sleep 10`，保留内部命令原本的输出；执行结束后尝试上报 `command.notify.finished`。生成的 `data` 包含 `status`、`duration_ms` 和 `history_entry_id`，`source.type` 为 `server_builtin`，`source.name` 为 `notify`。

通知系统会把这种特殊 `kind` 映射为 **Command Completed** 或 **Command Failed**。因此它与普通自定义事件在标题和通知级别上有所不同。

`notify` 的上报是附加功能：事件上报失败会记录错误，但不会改变被包装命令本来的执行结果。它依赖内部命令进入正常终态；如果执行途中异常中断、无法形成正常结束流程，不应假设一定会收到完成事件。

Script 或 Job 中主动使用 `events.emit()` 适合发送阶段性、条件触发和业务意义明确的事件；`notify` 更适合在用户需要关注某条终端命令完成情况时使用。

## 事件消费与通知投影的分界

Device Event 经过 Server 后，可以被映射成一条通知。普通事件默认展示为 `Device Event`，消息中包括设备名和 `message`（若没有则使用 `kind`）；`command.notify.finished` 使用特殊的完成/失败展示规则。

与 Device Event 不同，通知记录还包含：

- `notification_key`：通知偏好的分类 Key，Device Event 对应 `device_event`。
- `type`：`info`、`success`、`warning` 或 `error`。
- `title`、`message`：最终展示文字。
- `context`：保留 `client_id`、`kind`、`source`、`data` 等上下文。
- `actions`：可选的操作入口。

这一步由 Server 的通知投影机制决定。项目中设备上线下线、文件传输、PTY、ScreenView、External Tool 等通知也可直接来自 Server 事件总线，而不需要调用 Device Event HTTP API。

Notification Center 历史和实时 Toast 使用独立规则：关闭 `device_event` 的显示偏好，不会让 `events.emit()` 停止发送事件；已经投影的历史记录也不会因为关闭显示而自动删除。具体的存储、偏好、两条 SSE 通道和断线续传见 [SSE Notifications](sse_notifications.md)。

## 可靠性与身份校验边界

| 现象 | 机制与处理 |
|---|---|
| SDK 提示缺少活动上下文 | 必须在带 Client SDK 上下文的 Script / Job 中调用 |
| 提示 `event kind is required` | `kind` 为空或只有空白字符 |
| 提示 `Invalid device event kind` | 检查命名规则和 128 字符长度限制 |
| `data` 类型错误 | 必须传 `dict`，不能直接传列表或文本 |
| 找不到目标 Client | 核对 `client_id`，以及当前 Client 是否在线 |
| 请求超时或 Server 不可访问 | 检查 Client 至 Server 的 HTTP 路径；默认超时 10 秒 |
| 事件被接受却没有 Toast | 检查浏览器 SSE 连接及通知显示偏好；也可能没有在线浏览器 |
| 没有在 Notification Center 找到事件 | 核对是否已投影并写入历史，而非只检查 HTTP 成功 |
| 相同业务事件出现多次 | `events.emit()` 每次产生新的 `event_id`；相同 `kind` / `data` 不会自动去重 |
| `kind` 不同但通知都叫 Device Event | 通用通知投影不会为任意 `kind` 自动生成独立通知标题 |

`events.emit()` 不提供离线可靠队列、重试确认、消费确认或“恰好一次”通知语义。通知系统的 SSE 断线恢复处理的是**已经持久化的通知记录**，并不代替 Client 端离线事件补发。

如事件携带敏感信息，应该只放必要的业务字段。它们可能进入 Server 通知历史、浏览器通知上下文或其他订阅者，不要把凭据、隐私原文、大块日志作为常规 `data` 或 `message` 发送。
