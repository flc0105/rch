# SSE Notifications

RCH Server 先通过 WebEventBus 分发正在发生的业务和连接事件，再从符合条件的事件投影出可持久化的通知记录。前端实时订阅、Notification Center、桌面通知消费者和通知偏好共同围绕这两类对象运行，但并不是每条总线事件都必然产生用户提示。

通用 SSE 流服务于实时交互，专用通知流则使用数据库历史和游标支持回放。理解这个系统时必须将“事件发生”“形成通知记录”“某个消费者决定显示”三个步骤分开，它们有独立的数据模型和丢失边界。

## 运行事件到用户提示的投递链

```text
Client Device Event / Server 各业务模块
                  ↓
          WebEventBus.publish()
                  ├──→ 通用 SSE：/api/stream
                  │       └──→ Web UI 实时更新 / Toast / 交互消息
                  │
                  └──→ NotificationEventProjector
                           ↓ 仅投影符合条件的事件
                       SQLite notifications
                           ↓
                    notification_center_updated
                           ├──→ Web Notification Center
                           └──→ 专用 SSE：/api/notifications/stream
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

`id` 是本次总线发布的事件 ID；`event` 是浏览器 SSE 监听的事件名称；`data` 则是具体业务 Payload。业务来源的 Device Event 还可以在 `data.event_id` 中携带自己的标识，**这两个 ID 不是同一个**。

事件总线使用线程安全的订阅队列，支持两种投递方向：

- **广播事件**：没有指定 `target_tab_id` 时，投递给符合事件类型过滤的所有订阅者。
- **定向事件**：带 `target_tab_id` 时，只投递给同一个标签页 ID 的订阅者，用于前台命令、交互等不应污染其他标签页的消息。

订阅时还可指定 `event_types` 过滤，只接收某一类事件。通知专用流就只订阅 `notification_center_updated`，而通用 Web 流接收当前标签页可见的各类事件。

事件总线的订阅队列存储于 Server 进程内存，不是持久化消息队列。断线后的通用 SSE 不会自动重放整个 WebEventBus 历史；需要可靠恢复时，必须依赖专门持久化的数据模型。

## Watchdog 恢复后的上线通知

仍然使用原有的 `connection_online` 事件和 `connection_online` 通知偏好，不新增事件类型或独立订阅入口。Local Heartbeat Watchdog 检测到心跳过期并拉起新的 Client 时，首次上线事件附带 `recovery_source: "local_watchdog"`；Process Supervisor 检测到 Client PID 消失并拉起新 Client 时，附带 `recovery_source: "process_watchdog"`。Server 只允许这两个已知值进入上线事件；正常启动、Remote HTTP Relaunch 和普通断线重连都不标注恢复来源。

```json
{
  "connection": {"client_id": "client-example", "hostname": "workstation"},
  "recovery_source": "process_watchdog",
  "time": "<online-event-time>"
}
```

前端即时 Toast 与 `NotificationEventProjector` 历史记录均使用原有 **Device Online** 标题。普通上线显示 `workstation is now available`，恢复上线分别追加 ` (recovered by Local Watchdog)` 或 ` (recovered by Process Watchdog)`；通知历史 `context.recovery_source` 仅在已知来源时存在。恢复来源描述实际拉起 Client 的监督者，**不声称确认了崩溃根因**。

该标记随新 Client 的启动环境传递、在 Client 初始化时移出环境，并只用于第一次成功发送的 `info` 握手；以后同进程网络重连不再携带。Server 真正注册连接后才发布上线事件，因此恢复失败、没有上线时不会产生恢复成功通知。Socket 握手没有单独的 Server ACK，若握手已发送却未被 Server 注册，Client 不能获知这一情况；当前实现只保证标记在本地首次成功发送后消费，而非跨网络故障的恰好一次投递。

**本版不支持** Watchdog 在检测到 stale 或进程死亡的当下主动发送故障 SSE，也不增加 Preferences 开关；那是另一个后续功能。

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
| `id` | 通知记录的唯一 ID，通知专用 SSE 以它作为断线续传 Cursor |
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

该对象对应 SSE 的 `notification_center_updated` 事件。删除单条通知时发送 `action: deleted` 和 `id`，清空历史时发送 `action: cleared`，批量清理时发送 `action: pruned` 和被移除的 `ids`。其他浏览器标签页通过它同步 Notification Center，而无需把删除操作重新解释成一条新通知。

## 实时流与可回放通知流

Server 使用标准 `text/event-stream` 响应，事件由 `id`、`event`、`data` 等 SSE 字段组成。两条接口的责任不同。

| 通道 | 用途 | 恢复能力 |
|---|---|---|
| `GET /api/stream?tab_id=...` | 浏览器通用实时事件，包括命令、交互和业务生命周期 | EventSource 自动重连；不提供完整事件历史重放 |
| `GET /api/notifications/stream` | 已持久化通知的专用投递，适合 Desktop Notifier 等消费者 | 支持 `Last-Event-ID` 按通知 ID 回放后续记录 |

两条通道均受 Web 身份验证保护。浏览器依靠已登录的 Web 会话访问通用流；外部 SSE 消费者可以使用服务端支持的 `Authorization: Bearer <API token>`。

### 通用浏览器实时订阅

浏览器打开 `/api/stream?tab_id=<tab_id>` 后，Server 为当前连接创建订阅队列。普通事件的 SSE 格式类似：

```text
id: server-generated-event-id
event: device_event
data: {"client_id":"client-example","kind":"app.process.started","message":"Process started"}

```

空闲约 15 秒时发送 `ping`，保持连接活动。浏览器通过 `EventSource` 监听各类事件，连接断开时由浏览器自动尝试重连。

**通用流返回的 SSE `id` 并不是可靠持久的回放游标。** 当前通用接口不会根据重新连接时的 `Last-Event-ID` 查询原始事件历史。页面启动或重连后，还需要通过对应 HTTP API 获取必要的当前状态或历史信息。

### 带游标的通知订阅

专用接口：

```http
GET /api/notifications/stream
Authorization: Bearer <API token>
Accept: text/event-stream
Last-Event-ID: <之前收到的 notification id>
```

第一次连接如果没有游标，默认**只接收以后新产生的通知**，不会把已有 Notification Center 历史全部推送一遍。消费者应另外请求历史 API，或从新的通知开始维护游标。

已有游标时，Server 使用对应通知的数据库插入位置，按插入顺序回放后续通知，然后继续等待实时事件。游标对应的记录找不到时，发送：

```text
event: reset
data: {"reason":"cursor_not_found","last_event_id":"missing-id"}

```

该行为提示消费者重新确定自己的恢复策略；它并不自动把全部历史重发。

专用流连接时先订阅实时更新，再查询回放，减少重放与实时事件切换时的遗漏；如果相同通知同时出现在回放和实时队列中，会按通知 ID 避免重复投递。空闲约 15 秒时发送 `ping`，并提供 `retry: 3000` SSE 提示。

若某类通知被偏好设置关闭，专用流不会发送 `notification` 事件，而会用相同通知 ID 发送 `cursor` 事件和 `disabled_by_preference` 原因，**仍然推进恢复游标**。这样偏好后来重新启用时，不会因旧游标而把曾经被屏蔽的通知错误重放。

## 浏览器及桌面通知的消费

Web UI 主要订阅通用 `/api/stream`。它在连接打开后监听不同事件名称，并按业务类型生成 Element Plus Toast；另外在加载时调用历史接口，在收到 `notification_center_updated` 时更新 Notification Center 状态。

- **Toast** 是短暂提示，是否弹出由浏览器当前通知偏好决定。
- **Notification Center** 是独立的持久历史视图，支持按 `success` / `info` / `warning` / `error` 查看、删除单条和清空全部。
- **通知 Actions** 允许部分记录提供下载、预览、查看日志或打开相关管理器等操作。只有投影确实生成了 Actions，页面才有相应入口。

当前 Web UI 并不是主要通过专用 Notification Stream 来消费通知；专用接口面向像 RCH Desktop Notifier 这样只关心持久通知的独立消费者。Desktop Notifier 使用 Bearer Token 连接该接口，把 `notification` 投射为操作系统桌面通知，并将最近成功投递的通知 ID 存入本地状态文件以便重连。

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

**偏好控制的是实时展示或投递，不是事件生产与通知入库。** 关闭全局开关或某个分类不会删除已有历史；新产生且符合投影规则的通知仍能保存到 SQLite。Web Toast 在前端依照偏好跳过展示；专用通知流在服务端依照偏好发 `notification` 或 `cursor`。

主要管理接口如下：

| 方法 | 接口 | 用途 |
|---|---|---|
| `GET` | `/api/notifications/preferences` | 读取通知偏好 |
| `PUT` | `/api/notifications/preferences` | 保存全局开关与分类偏好 |
| `GET` | `/api/notifications/history` | 取得完整 Notification Center 历史 |
| `DELETE` | `/api/notifications/history/{notification_id}` | 删除指定通知 |
| `DELETE` | `/api/notifications/history` | 清空通知历史 |
| `GET` | `/api/notifications/stream` | 订阅持久通知的 SSE 流 |

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
| 页面 SSE 断开后漏掉中间事件 | 通用流无完整回放；重新加载相关 HTTP 状态或历史 |
| Desktop Notifier 首次连接不显示旧记录 | 正常：没有游标时专用流只接收后续通知 |
| 专用流发出 `reset` | `Last-Event-ID` 对应通知已不存在；消费者需处理游标失效 |
| 专用流收到 `cursor`，没有系统通知 | 对应通知被偏好关闭，游标仍推进 |
| 通知出现两种 `event_id` | 区分 Device Event ID、WebEventBus ID 和 Notification ID |
| 不同浏览器标签页重复 Toast | 通用事件可广播给多个标签，去重的历史入库不等于 Toast 全局只显示一次 |
| 浏览器收不到指定交互消息 | 检查 `tab_id` 是否一致；定向事件不会广播到其他标签 |
| 通知动作打不开 | 检查 `actions` 是否含有效 URL 或对应前端 Action Handler |
| SSE 请求返回未授权 | 检查 Web 会话或 API Token，专用消费者需正确携带 Bearer Token |

WebEventBus 的订阅队列是内存队列，没有按所有原始事件提供跨重启恢复、持久积压和强制消费确认。通知专用流虽然支持 SQLite 游标回放，但只覆盖**已经入库的通知**；如果投影时没有生成通知，或请求尚未抵达 Server，就没有可以回放的通知记录。

通知偏好不是敏感内容过滤器。`context` 和 `message` 可能包含由业务事件提交的信息，并被保存在 Server 数据库中；生产者应该主动避免携带不必要的敏感数据。通知 History 和 SSE 接口也应维持必要的管理员访问控制。

如需让 Script 或 Background Job 主动产生可进入通知系统的事件，使用 [Device Event Emit](event_emit.md) 所述的 SDK，而不是让 Client 直接调用 Server 内部事件总线。
