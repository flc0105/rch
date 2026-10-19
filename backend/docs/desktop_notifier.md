# Desktop Notifier：独立桌面通知消费者

RCH Desktop Notifier 是独立于 Server、浏览器和远程 Python Client 的**本机通知进程**。它以 Bearer Token 连接 Server 的持久通知 SSE 流，按照用户的投递偏好接收通知，把标题和正文交给操作系统的通知接口，并将处理进度保存在本地游标文件中。它既不是远程 Client 的一个命令，也不是浏览器 Notification Center 的替代品。

这篇文档说明独立消费者的部署、运行、交付和故障边界。**哪些业务事件会产生通知、Server 如何投影通知历史、Web Notification Center 如何管理记录**，统一见 [SSE Notifications](sse_notifications.md)；这里不重复列举业务事件类型或历史表结构。

## 1. 从业务事件到操作系统通知

```text
Server 业务/设备事件
      │
      ▼
通知投影与持久化 ────────────→ SQLite 通知历史 ───→ Web Notification Center
      │                                  │
      └── notification_center_updated ───┘
                     │
                     ▼
     GET /api/notifications/stream  （独立、经认证的 SSE）
                     │
                     ▼
             Desktop Notifier
        SSE 解析 → 投递 → 游标落盘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      macOS 后端           Windows 后端
          │                     │
          ▼                     ▼
    系统桌面通知         Windows Toast
```

Server 对 `/api/notifications/stream` 的每个连接注册 `notification_center_updated` 订阅队列，只将新增通知作为可投递项。通知是否实际发给 Desktop Notifier，先由 Server 查询该 `notification_key` 的投递偏好决定；被禁用的通知依然会推进消费者游标。Notifier **不自行从底层设备事件推导通知**，也不订阅浏览器的通用 `/api/stream`。

实际边界：Web UI 的 Toast、Notification Center 的持久历史、桌面系统通知是三个不同的呈现渠道。通知记录被清空，并不会撤回操作系统已经显示的提示；操作系统接受通知也不代表用户已阅读。

## 2. 程序入口、配置和运行模式

`desktop_notifier/run.py` 启动 `rch_notifier.cli.main()`。首次配置、启动和测试是独立操作。项目提供的 Python 依赖中包括 `requests`；macOS 额外需要 PyObjC 的 Cocoa 与 UserNotifications 模块。

在项目目录内使用：

```bash
cd desktop_notifier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --init-config --config ./config.json
```

编辑刚生成的配置文件，把 `server_url` 和 `token` 换成真实值。启动前可先验证本机通知后端：

```bash
python run.py --config ./config.json --test-notification
python run.py --config ./config.json
```

`--test-notification` **不会连接 Server**，仅通过选中的操作系统后端发送一条测试通知后退出；用于区分本地授权问题与网络/SSE 问题。常规模式默认 **headless**，没有状态栏窗口，常驻读取 SSE。macOS 可选：

```bash
python run.py --config ./config.json --tray
```

`--tray` 使用 AppKit 菜单栏主线程事件循环，SSE Runtime 运行于独立后台线程；菜单支持查看连接/重试状态、打开 RCH、测试通知、手动重连和退出。此参数仅支持 macOS；在其他平台请求该模式会返回非零退出码，而不是自动提供对应系统托盘。`--verbose` 可以输出调试日志；`--config` 可以指向任意配置路径。

### 配置文件及覆盖规则

```json
{
  "server_url": "http://192.168.1.20:8085",
  "token": "YOUR_RCH_ADMIN_API_TOKEN",
  "sound": true,
  "backend": "auto",
  "reconnect_initial_seconds": 1,
  "reconnect_max_seconds": 30
}
```

`server_url`、`token` 必填。`backend` 可为 `auto`、`usernotifications`、`osascript`、`windows`；两个重连间隔必须大于零，且初始间隔不得大于最大间隔。`sound` 默认为 `true`。以下环境变量优先于同名 JSON 配置项：

```bash
export RCH_NOTIFIER_SERVER_URL=http://192.168.1.20:8085
export RCH_NOTIFIER_TOKEN=YOUR_RCH_ADMIN_API_TOKEN
export RCH_NOTIFIER_BACKEND=auto
python run.py --config ./config.json
```

三项环境变量只覆盖对应三项配置；声音开关、退避时间仍读取 JSON。默认配置目录在 macOS 为 `~/Library/Application Support/RCH Notifier/config.json`，Windows 为 `%APPDATA%/RCH Notifier/config.json`，其他系统使用 XDG 配置目录（或者 `~/.config/rch-notifier/config.json`）。真正的 `state.json` 总是放在**所选配置文件的同级目录**，不是固定放在项目根目录。

`--init-config` 只创建新的示例配置，已有文件会拒绝覆盖；当配置缺失、JSON 不是对象、必填项缺失、Backend 名称无效或退避参数不合法时，程序会在进入订阅循环前失败。不要把仓库中的示例 Token 当成可用凭据。

## 3. SSE 消费协议：连接、事件类型与游标

### 3.1 建立订阅

`NotificationSseClient.events()` 通过 `requests.Session.get(..., stream=True)` 建立持久 HTTP GET，默认连接/读取超时分别为 10 秒和 70 秒；请求头为：

```http
GET /api/notifications/stream HTTP/1.1
Accept: text/event-stream
Cache-Control: no-cache
Authorization: Bearer YOUR_RCH_ADMIN_API_TOKEN
Last-Event-ID: <optional-last-notification-id>
```

第一次启动还没有本地游标，不发送 `Last-Event-ID`，**只接收之后的新通知**，不会把之前的 Notification Center 历史全量推送到桌面。Server 每 15 秒无业务事件时发送一次 `ping`，以维持长连接。客户端解析 SSE 的 `event`、`id`、多行 `data`、空行帧边界及注释；对 `retry:` 字段不采用 Server 建议值，重连退避由本地配置控制。

### 3.2 Runtime 对事件的确切处理

| SSE event | Desktop Notifier 行为 | 本地游标 |
| --- | --- | --- |
| `notification` | 解析 JSON、提取 `id`、调用系统后端 `notify()` | 后端调用**正常返回后**更新为通知 ID |
| `cursor` | 表示该通知被 Server 投递偏好屏蔽；不显示系统通知 | 使用事件 `id` 推进 |
| `reset` | 表示此前 `Last-Event-ID` 在 Server 历史中已找不到 | 清除本地游标，从后续实时事件继续 |
| `ping` | 保持连接活性 | 不变 |
| 其他事件 | 忽略 | 不变 |

传给后端的 `notification` 是 Server 已归一化的记录字典，至少需要 `id` 才能作为已交付记录处理；系统后端主要使用 `title` 和 `message`。Server 禁用某个 `notification_key` 后发送的 `cursor` **必须被消费者保存**，否则日后重新打开该偏好时，有可能回放本已屏蔽的旧通知。

### 3.3 游标持久化与可恢复程度

`CursorState` 在配置文件同目录维护：

```json
{"last_event_id": "通知记录ID"}
```

更新先写 `state.json.tmp`，再用 `Path.replace()` 替换目标文件，避免部分写入导致结构损坏。读取不到文件、文件损坏、数据结构无效时，游标恢复为空，Notifier 仍能从实时流工作。删除 `state.json` 等于**放弃此前的重放位置**，并不表示从 Server 抓取所有旧通知。

Server 收到有效的 `Last-Event-ID` 时，会从 SQLite 返回游标**之后**的通知记录，然后接续实时队列。订阅早于回放查询注册，因此 Server 用 `replayed_ids` 去除回放与实时窗口的重复 ID。无效游标则发出 `reset`；客户端清理游标，继续等待后续通知，**不会凭空恢复已经被清理的旧记录**。

这是一套“处理后记录进度”的尽力交付模型，**不是端到端严格恰好一次通知**：

- `notify()` 正常返回但状态文件尚未写好就退出，重连可能再次显示同一通知。
- 桌面后端正常返回仅表示系统通知请求被接受/提交；用户是否实际看到不在此协议确认范围内。
- 如果 Desktop Notifier 已离线且 Server 同期删除了游标对应记录，重放将无法覆盖缺失区间。
- 多个 Notifier 各自保存独立的本地游标；Server 不按桌面实例保存“已读”状态。

## 4. 连接状态、断线重试与主动停止

`NotificationStreamRuntime` 始终维护**一个活动的流式 HTTP Response**。成功校验状态码和 `Content-Type: text/event-stream` 后发布 Connected；流结束、网络故障或投递异常则进入重连循环。默认延迟从 1 秒增长到最多 30 秒，延迟随失败增长、成功投递或主动重连重置。菜单栏会展示最近的 Connected/Disconnected 状态和整数秒重试倒计时。

`Reconnect` 并非启动第二个并行订阅：Runtime 设置重连标志，通过关闭/中断当前 Response 唤醒 `iter_lines()`，在前一轮清理后再建立新流。`Quit`、SIGINT/SIGTERM 则触发 `stop()`，关闭流并结束循环；菜单栏主线程还会退出 Cocoa 事件循环、等待工作线程至多 5 秒。依赖 `requests` 内部连接对象的主动中断路径设有降级处理，因此其唤醒速度仍会受具体运行环境影响。

身份验证失败与普通断线不同：SSE 收到 **HTTP 401** 时抛出 `SseAuthenticationError`，Runtime 返回退出码 `2`，**不无限重试一个被明确拒绝的 Token**。其他非成功状态由 `raise_for_status()` 处理，按一般错误进入重试循环。未收到期望的 `text/event-stream`，同样视为协议错误。首次启动配置/后端失败通常返回退出码 `1`，正常退出返回 `0`。

## 5. 桌面通知后端和平台行为

### macOS：UserNotifications 与 osascript

`backend: auto` 先调用 `UserNotifications.framework`，请求系统提醒权限；启用 `sound` 时也请求声音能力。若初始化/授权或后续提交通知失败，自动退回 `/usr/bin/osascript` 的 `display notification`；强制指定 `usernotifications` 则直接暴露失败，不会静默降级。`osascript` 通过**参数**而非直接拼接用户标题/正文进 AppleScript 表达式，降低转义风险。后端自行设置桌面通知的声音，系统设置仍可能屏蔽实际展示。

该工程以脚本运行形态为主：原生通知权限和应用身份的映射受 Python 包装环境影响，没有提供完成签名、公证的正式 `.app` 发布流程。`--tray` 是 Mac 专用 UI；它的状态栏铃铛和连接状态仅表示 Runtime 订阅状态，不是某条通知是否送达的回执。

### Windows：PowerShell Toast

`WindowsNotificationBackend` 通过 `powershell.exe` 创建 Windows Runtime Toast XML，标题/正文经 XML 转义，`sound` 决定默认音效或静音，外部进程设置 15 秒超时。此后端目前是最小实现，源码及现有测试**不能证明已在真实 Windows 桌面环境完整验证**。Windows 支持 Headless，不支持 `--tray`。

其他平台没有可工作的桌面通知后端；配置 `auto` 在不支持的平台会报错。不能把配置路径覆盖多平台误解为通知后端全面支持多平台。

## 6. 安全边界：访问 Token 与敏感信息

专用通知流受 Server 全局 Web Auth Guard 保护，Notifier 发送的是完整的 RCH 管理 API Token，而不是专用只读授权。该 Token 的权限范围超出了“只读取通知”，必须按照高权限凭据保管：

- 尽量用受保护的环境变量或限制文件系统权限存储，不要把真实 Token 写进仓库和共享日志。
- 使用远程 `http://` 时，链路上的 Bearer Token 与通知正文可能以明文形式传输；跨不可信网络应使用受信任的 TLS/反向代理等通道。
- 通知标题和消息可能包含敏感操作信息；桌面系统的通知预览/锁屏策略需要单独配置。
- `Last-Event-ID` 仅用于重放定位，不能作为身份认证或访问授权凭据。

相关 Web 身份认证与 Token 来源见 [Admin Auth](admin-auth.md)；业务通知的生成、用户投递偏好与删除见 [SSE Notifications](sse_notifications.md)。

## 7. 常见问题与调试路径

| 现象 | 优先核对 | 实际行为 |
| --- | --- | --- |
| 本地测试通知失败 | 桌面通知权限、选中的 backend、macOS osascript / Windows PowerShell | 与 Server/SSE 无关，先修复本地后端 |
| CLI 报配置错误 | 配置路径、`server_url`/`token`、退避参数 | 启动前退出，不建立 SSE |
| HTTP 401 后进程退出 | 管理 API Token 是否有效 | 返回退出码 2，不继续重试 |
| 已连接但没有弹窗 | Server 是否形成通知历史、投递偏好是否禁用、操作系统是否允许通知 | SSE 连接成功不保证存在可投递通知 |
| 首次运行看不到旧历史 | `state.json` 是否存在 | 无游标时仅接收后续实时通知，属预期 |
| 重连出现重复提醒 | 本地通知已调用而游标落盘前意外退出 | 无严格恰好一次保证 |
| 收到 `reset` | Server 中游标对应的历史记录是否已删除/清理 | 清空本地游标，从实时通知继续 |
| 菜单栏显示重试倒计时 | Server 可达性、代理长连接、状态码/响应头 | 退避重连，必要时使用菜单 `Reconnect` |
| Windows 发送失败 | PowerShell、系统 Toast API 和运行会话 | 当前尚缺真实 Windows 主机端到端验证 |

扩展本通知器时，优先保持**通知投影由 Server 决定、消费与展示由 Notifier 负责**的边界。新的操作系统后端应实现 `start()`、`notify(notification)` 和 `active_mode`；不要将通用事件总线直接接入桌面，也不要把浏览器 Toast 策略复制到 Notifier 内。新的桌面动作、点击回调或复杂附件展示，目前不属于实际实现的协议承诺。

## 8. 实现定位与验证范围

- 入口及两种运行模式：`desktop_notifier/rch_notifier/cli.py`、`menu_bar_macos.py`。
- 配置/环境覆盖：`desktop_notifier/rch_notifier/config.py`。
- SSE 连接与解析：`desktop_notifier/rch_notifier/sse.py`。
- 运行时生命周期及事件分派：`desktop_notifier/rch_notifier/runtime.py`。
- 本地游标：`desktop_notifier/rch_notifier/state.py`。
- 平台通知后端：`desktop_notifier/rch_notifier/backends/macos.py`、`windows.py`。
- Server 专用投递端点：`backend/server/web/routes/notification_stream.py`；投递偏好与重放由对应 Notification API 提供。

现有 `desktop_notifier/tests/` 测试涵盖 CLI、配置/游标、macOS 菜单栏、SSE 解析和运行循环。本篇以实际源码行为为准；单元测试可以验证协议分流和重连控制，**不等同于真实 macOS 授权、Windows 桌面弹窗、代理或网络故障场景的端到端认证**。
