# WebSocket Events and Notifications

RCH Server 通过 WebEventBus 分发业务与连接事件，并从符合通知规则的事件生成持久通知记录。前端实时订阅、Notification Center、桌面通知消费者与通知偏好分别消费对应的事件或通知数据。

通用 WebSocket 事件流服务于实时交互，专用通知 WebSocket 流则使用数据库历史和游标支持回放。理解这个系统时必须将“事件发生”“形成通知记录”“某个消费者决定显示”三个步骤分开，它们有独立的数据模型和丢失边界。

Web 页面在 `ws://<host>:8086/ws/events?tab_id=<tab_id>` 上订阅消息；启用 HTTPS 时使用 `wss://`。每条消息是一个 JSON 对象：`{"id":"…","event":"connection_online","data":{…}}`，业务事件名、payload 与 Event Bus 内部保持一致。Server 在接入时验证与原 HTTP 管理员会话一致的 Session Cookie 或管理员 Bearer Token、浏览器来源；连接断开即释放订阅，队列积压时关闭连接并要求恢复权威状态。通用消息不做历史重放，Task 在连接建立和重连时从 HTTP 快照恢复，漏掉的终态输出由精确 Activity ID 补取。

专用 `/ws/notifications?last_event_id=<cursor>` 按 SQLite 通知历史继续回放，`notification`、`cursor`、`reset` 事件均通过 JSON `event/data/id` 字段发送。独立的 Desktop Notifier 消费端须先完成 WebSocket 协议迁移再升级 Server；旧的 HTTP SSE `/api/notifications/stream` 已移除。

## 运行事件到用户提示的投递链

```text
Client Device Event / Server 各业务模块
                  ↓
          WebEventBus.publish()
                  ├──→ 通用 WebSocket：/ws/events?tab_id=<tab_id>
                  │       └──→ Web UI 实时更新 / Toast / 交互消息
                  │
                  └──→ NotificationEventProjector
                           ↓ 仅投影符合条件的事件
                       SQLite notifications
                           ↓
                    notification_center_updated
                           ├──→ Web Notification Center
                           └──→ 专用 WebSocket：/ws/notifications?last_event_id=<cursor>
                                    └──→ Desktop Notifier 等消费者
```

Server 在发布实时事件时，先尝试完成通知投影和数据库持久化，再向实时订阅者分发原始事件；如果新增了通知，还会广播 `notification_center_updated`。因此持久化不依赖浏览器是否在线、是否成功处理 Toast。

WebEventBus 同时承担其他实时协作消息，例如交互请求、前台命令状态等。不能把它当成“全部事件永久保存”的数据库：**数据库保存的是符合投影规则的通知，而非总线上经过的所有原始事件**。

## 实时事件总线及订阅关系

Server 内部功能通过 `publish(event_type, payload)` 发出事件，例如：

```python
web_event_bus.publish('connection_online', {
    'connection': {'client_id': 'client-example', 'hostname': 'workstation'},
})
```

上例表达事件总线的调用方式，并不是要求开发者直接在 Script SDK 中取得 Server 的事件总线对象。Client Script / Job 上报自定义业务事件时，使用 [Device Event Emit](event_emit.md) 的 `events.emit()` 即可。

### 总线事件的数据边界

WebEventBus 发布时生成一份临时事件对象：

```json
{
  "id": "server-generated-event-id",
  "event": "device_event",
  "data": {
    "client_id": "client-example",
    "kind": "app.process.started",
    "message": "Process started"
  }
}
```

`id` 是本次总线发布的事件 ID；`event` 是浏览器事件监听的名称；`data` 则是具体业务 Payload。业务来源的 Device Event 还可以在 `data.event_id` 中携带自己的标识，**这两个 ID 不是同一个**。

事件总线通过 `asyncio.Queue`、跨线程 `call_soon_threadsafe` 进行异步订阅和投递，支持两种投递方向：

- **广播事件**：没有指定 `target_tab_id` 时，投递给符合事件类型过滤的所有订阅者。
- **定向事件**：带 `target_tab_id` 时，只投递给同一个标签页 ID 的订阅者，用于前台命令、交互等不应污染其他标签页的消息。

订阅时还可指定 `event_types` 过滤，只接收某一类事件。通知专用流就只订阅 `notification_center_updated`，而通用 Web 流接收当前标签页可见的各类事件。

事件总线的订阅队列存储于 Server 进程内存，不是持久化消息队列。断线后的通用 WebSocket 不会自动重放整个 WebEventBus 历史；需要可靠恢复时，必须依赖专门持久化的数据模型。

前台 Task 是实时运行态，不进行通知持久化。`foreground_task_changed` 广播中的 `task` 是当前会话状态快照，所有标签页均可直接使用；事件丢失后由浏览器在 WebSocket 连接建立及重连时调用已有的连接 Task 查询接口重新同步。其他同步命令来源也在共用执行槽上发出相同事件，避免用周期性 HTTP 轮询补漏。

## Watchdog 恢复后的上线通知

仍然使用原有的 `connection_online` 事件和 `connection_online` 通知偏好，不新增事件类型或独立订阅入口。Local Heartbeat Watchdog 检测到心跳过期并拉起新的 Client 时，首次上线事件附带 `recovery_source: "local_heartbeat_watchdog"`；Process Recovery Watchdog 检测到 Client PID 消失并拉起新 Client 时，附带 `recovery_source: "process_recovery_watchdog"`。Server 只允许这两个已知值进入上线事件；正常启动、Remote HTTP Relaunch 和普通断线重连都不标注恢复来源。

```json
{
  "connection": {"client_id": "client-example", "hostname": "workstation"},
  "recovery_source": "process_recovery_watchdog",
  "time": "<online-event-time>"
}
```

前端即时 Toast 与 `NotificationEventProjector` 历史记录均使用原有 **Device Online** 标题。普通上线显示 `workstation is now available`，恢复上线分别追加 ` (recovered by Local Heartbeat Watchdog)` 或 ` (recovered by Process Recovery Watchdog)`；通知历史 `context.recovery_source` 仅在已知来源时存在。恢复来源描述实际拉起 Client 的监督者，**不声称确认了崩溃根因**。

该标记随新 Client 的启动环境传递、在 Client 初始化时移出环境，并只用于第一次成功发送的 `info` 握手；以后同进程网络重连不再携带。Server 真正注册连接后才发布上线事件，因此恢复失败、没有上线时不会产生恢复成功通知。Socket 握手没有单独的 Server ACK，若握手已发送却未被 Server 注册，Client 不能获知这一情况；当前实现只保证标记在本地首次成功发送后消费，而非跨网络故障的恰好一次投递。

## 持久化通知的形成

`NotificationEventProjector` 从 WebEventBus 的事件类型中选择符合条件的项目，构造通知记录并写入 SQLite。它处理 Device Event、设备上下线、Artifact、文件传输、Background Job、PTY、ScreenView、External Tool、构建和清理等生命周期事件。

**事件类型符合支持范围，还不保证一定生成通知。** 例如文件传输和 External Tool 只针对规定的生命周期阶段映射；没有匹配阶段的中间状态不会自动新增通知。交互请求、通知偏好变化和通知中心自身的更新事件也不会递归变成新通知。

### 通知存储模型

一条已经持久化的通知结构如下，字段值为示例：

```json
{
  "id": "notification-id",
  "event_id": "web-event-id",
  "notification_key": "device_event",
  "type": "info",
  "title": "Device Event",
  "message": "workstation · Process started",
  "shown_at": "2026-10-16T09:00:00Z",
  "context": {
    "client_id": "client-example",
    "kind": "app.process.started",
    "data": {"pid": 12345}
  },
  "actions": []
}
```

| 字段 | 含义 |
|---|---|
| `id` | 通知记录的唯一 ID，通知专用 WebSocket 以它作为断线续传 Cursor |
| `event_id` | 生成本条通知的 WebEventBus 事件 ID，用于通知写入去重 |
| `notification_key` | 通知偏好对应的分类键，例如 `device_event` 或 `pty_error` |
| `type` | 通知级别：`success`、`warning`、`error`、`info` |
| `title` / `message` | 已生成的展示标题和正文 |
| `shown_at` | 通知写入时的时间字符串 |
| `context` | 事件相关的客户端、资源和状态信息 |
| `actions` | 可选的操作入口，例如下载文件、查看日志或打开管理窗口 |

三个 ID 要分开理解：`data.event_id` 是 Client 的 Device Event ID；`event_id` 是 Server 的总线事件 ID；`id` 是通知历史自身的记录 ID。Notification Center 根据总线 `event_id` 去重，不是简单地根据业务 `kind` 或通知文字去重。

通知保存在 Server 的 `runtime/rch.db` 中的 `notifications` 表，包含 `context_json`、`actions_json` 等字段。写入历史时还会规范化标题、消息长度和通知类型。读取历史按展示时间倒序返回，供 Notification Center 展示。

### 可见历史的变化事件

当新通知入库成功，Server 还会广播：

```json
{
  "action": "added",
  "notification": {
    "id": "notification-id",
    "notification_key": "device_event",
    "title": "Device Event",
    "message": "workstation · Process started",
    "type": "info",
    "context": {},
    "actions": []
  }
}
```

该对象对应 WebSocket 的 `notification_center_updated` 事件。删除单条通知时发送 `action: deleted` 和 `id`，清空历史时发送 `action: cleared`，批量清理时发送 `action: pruned` 和被移除的 `ids`。其他浏览器标签页通过它同步 Notification Center，而无需把删除操作重新解释成一条新通知。

## 实时流与可回放通知流

WebSocket 帧发送 JSON 消息 `{ "id": "...", "event": "...", "data": { ... } }`。所有服务端推送均保持原有业务事件名和 payload，浏览器按 `event` 路由到对应处理器。

| WebSocket 端点（8086） | 用途 | 恢复能力 |
|---|---|---|
| `/ws/events?tab_id=<tab_id>` | 浏览器任务、连接、交互和其他业务事件 | 客户端自动重连，连接成功后 GET 当前 Task 状态；通用事件没有完整重放 |
| `/ws/notifications?last_event_id=<cursor>` | 持久通知投递，供独立客户端使用 | 根据 SQLite 通知 ID 重放后续记录，`notification/cursor/reset` 可推进游标 |

两条 WS 通道使用与 8085 Web API 相同的管理员会话 Cookie 或 `Authorization: Bearer <API token>`。浏览器 Origin 仅允许与 Web HTTP 服务相同的主机/端口（另支持本地 Vite 开发端口）。无有效凭据时连接关闭。

### 通用浏览器事件订阅

连接后，Server 为当前 `tab_id` 创建异步有界队列。全局事件广播，带 `target_tab_id` 的事件仅投递到指定页签。跨线程生产者通过事件循环线程安全调度发送，不为每条 WebSocket 分配一个长期等待的 HTTP 工作线程。缓冲溢出时关闭该连接，客户端从 HTTP API 恢复权威状态。15 秒内没有业务消息时发送 `ping` JSON 事件。

例如一条设备业务事件：

```json
{"id":"server-generated-id","event":"device_event","data":{"client_id":"client-example","kind":"app.process.started","message":"Process started"}}
```

Web UI 初始化或 WS 重连后查询当前 Task 快照；已结束但漏掉 `command_complete` 的前台命令使用精确的 `history_entry_id` 读取 Activity，恢复遗漏的输出并收敛 Run/Cancel 状态。通用流的 `id` 不能作为完整活动记录游标。

### 带游标的通知订阅

外部通知消费者建立 WebSocket 握手时提供管理员 Bearer Token，例如连接 `ws://host:8086/ws/notifications?last_event_id=<id>`。无游标时只订阅之后的新通知；有游标时，Server 从 SQLite 回放之后的通知，随后转入实时投递。游标不存在时发送：

```json
{"event":"reset","data":{"reason":"cursor_not_found","last_event_id":"missing-id"}}
```

如果通知被用户偏好禁用，发送 `cursor` 而不是 `notification`，仍推进通知 ID。回放和实时交叉出现的同一通知根据 ID 去重。空闲时发送 `ping`，重连策略由消费者自己管理。旧 HTTP SSE `/api/notifications/stream` 不再提供，外部 Desktop Notifier 客户端需要升级为 WebSocket 连接协议。

## 浏览器及桌面通知的消费

Web UI 主要订阅通用 `/ws/events`。它在连接打开后监听不同事件名称，并按业务类型生成 Element Plus Toast；另外在加载时调用历史接口，在收到 `notification_center_updated` 时更新 Notification Center 状态。

- **Toast** 是短暂提示，是否弹出由浏览器当前通知偏好决定。
- **Notification Center** 是独立的持久历史视图，支持按 `success` / `info` / `warning` / `error` 查看、删除单条，以及清空全部或仅清空当前筛选类型。
- **通知 Actions** 允许部分记录提供下载、预览、查看日志或打开相关管理器等操作。只有投影确实生成了 Actions，页面才有相应入口。

当前 Web UI 并不是主要通过专用 Notification Stream 来消费通知；专用接口面向像 RCH Desktop Notifier 这样只关心持久通知的独立消费者。升级后的 Desktop Notifier 使用 Bearer Token 建立 WebSocket 连接，将 `notification` 投射为操作系统桌面通知，并将最近成功投递的通知 ID 存入本地状态文件以便重连。

现有 Desktop Notifier 以 macOS 为主要目标，Windows 通知后端尚未完成真实 Windows 主机验证，不能据此宣称每个平台都具有相同的可靠性。它自身的配置、通知后端与桌面 UI 操作见该组件独立说明。

通知级别、动作和 Toast 时长由各业务的展示规则决定。没有一个“自动将任意总线事件显示为系统通知”的通用保证。

## 投递偏好和历史管理

Notification Preferences 存在 Server 的 `runtime/rch.db` 中，通过 `settings` 的 `notification_preferences` Namespace 存储。它们包含总开关 `enabled`，以及一个按 `notification_key` 分类的 `events` 对象。

例如：

```json
{
  "version": 1,
  "enabled": true,
  "events": {
    "connection_online": true,
    "device_event": true,
    "file_transfer_started": false,
    "file_transfer_error": true
  }
}
```

此示例只展示部分分类；Server 保存时会以当前定义的偏好项补齐完整结构。当前支持哪些偏好 Key 以实际设置界面的选项和接口返回为准，不需要在功能文档维护一份会随模块变化的完整常量列表。

**通知偏好控制实时展示和投递**；事件生产与通知入库继续按各自规则执行。 关闭全局开关或某个分类不会删除已有历史；新产生且符合投影规则的通知仍能保存到 SQLite。Web Toast 在前端依照偏好跳过展示；专用通知流在服务端依照偏好发 `notification` 或 `cursor`。

主要管理接口如下：

| 方法 | 接口 | 用途 |
|---|---|---|
| `GET` | `/api/notifications/preferences` | 读取通知偏好 |
| `PUT` | `/api/notifications/preferences` | 保存全局开关与分类偏好 |
| `GET` | `/api/notifications/history` | 取得完整 Notification Center 历史 |
| `DELETE` | `/api/notifications/history/{notification_id}` | 删除指定通知 |
| `DELETE` | `/api/notifications/history` | 清空通知历史；传入 `?type=success`（也支持 `info`、`warning`、`error`） 时只清理对应类型 |
| WebSocket | `ws://<host>:8086/ws/notifications` | 订阅持久通知（支持 `last_event_id` 游标） |

在已有 Web 登录会话或有效 API Token 的情况下，可按以下方式读取历史：

```bash
SERVER_URL='http://127.0.0.1:8085'
API_TOKEN='替换为 Server 配置的有效 API Token'

curl -sS "$SERVER_URL/api/notifications/history" \
  -H "Authorization: Bearer $API_TOKEN"
```

返回格式为标准 API 响应，其中 `data.notifications` 是保存的通知数组。该接口读取的历史与实时 Toast 偏好不同，即使某种 Toast 被关闭，已经持久化的对应记录仍可出现。

更新偏好可使用 `PUT`：

```bash
curl -sS -X PUT "$SERVER_URL/api/notifications/preferences" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"events":{"device_event":false}}'
```

该请求按服务端归一化规则保存完整偏好。未提交的分类会使用当前默认值，**不是自动保留此前同一对象中未传的所有自定义开关**。Web 偏好修改后还会发布 `notification_preferences_updated`，供其他浏览器标签页同步。

通知 History 的删除和清空操作同样会广播 `notification_center_updated`，使已打开的页面刷新对应记录。删除通知不等于撤回此前已经显示的 Toast，也不会撤回一个已经由独立 Desktop Notifier 投递到操作系统的提醒。

## 一致性、重连和数据安全

| 现象 | 实际行为与处理 |
|---|---|
| Browser 能接收实时事件，但 Notification Center 没记录 | 检查该事件是否属于投影支持范围，以及是否满足具体生命周期条件 |
| 关闭 Toast 后，历史仍有通知 | 正常：持久化和显示偏好分离 |
| 页面 WebSocket 断开后漏掉中间事件 | 通用流无完整回放；重新加载相关 HTTP 状态或历史 |
| Desktop Notifier 首次连接不显示旧记录 | 正常：没有游标时专用流只接收后续通知 |
| 专用流发出 `reset` | `last_event_id` 对应通知已不存在；消费者需处理游标失效 |
| 专用流收到 `cursor`，没有系统通知 | 对应通知被偏好关闭，游标仍推进 |
| 通知出现两种 `event_id` | 区分 Device Event ID、WebEventBus ID 和 Notification ID |
| 不同浏览器标签页重复 Toast | 通用事件可广播给多个标签，去重的历史入库不等于 Toast 全局只显示一次 |
| 浏览器收不到指定交互消息 | 检查 `tab_id` 是否一致；定向事件不会广播到其他标签 |
| 通知动作打不开 | 检查 `actions` 是否含有效 URL 或对应前端 Action Handler |
| WebSocket 请求返回未授权 | 检查 Web 会话或 API Token，专用消费者需正确携带 Bearer Token |

WebEventBus 的订阅队列是内存队列，没有按所有原始事件提供跨重启恢复、持久积压和强制消费确认。通知专用流虽然支持 SQLite 游标回放，但只覆盖**已经入库的通知**；如果投影时没有生成通知，或请求尚未抵达 Server，就没有可以回放的通知记录。

通知偏好不是敏感内容过滤器。`context` 和 `message` 可能包含由业务事件提交的信息，并被保存在 Server 数据库中；生产者应该主动避免携带不必要的敏感数据。通知 History 和 WebSocket 接口也应维持必要的管理员访问控制。

如需让 Script 或 Background Job 主动产生可进入通知系统的事件，使用 [Device Event Emit](event_emit.md) 所述的 SDK，而不是让 Client 直接调用 Server 内部事件总线。
