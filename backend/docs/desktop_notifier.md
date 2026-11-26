# Desktop Notifier：独立桌面通知消费者

Desktop Notifier 位于 `desktop_notifier/`，负责把 RCH 通知投递到操作系统，并在本机维护消费游标。Server 的浏览器通知和持久通知协议见 [WebSocket Events and Notifications](websocket_notifications.md)。

## 联机状态

当前 Server 提供 `/ws/notifications` WebSocket 通知订阅。仓库中的 Desktop Notifier 消费端仍使用 HTTP SSE，因而**当前组合无法接收 Server 实时通知**。本地通知后端可以独立测试；联机需要消费者实现 WebSocket 通知协议。Web Notification Center 与浏览器 Toast 正常使用 Server 的 WebSocket 通道。

## 安装与本机配置

在 macOS 的项目目录执行：

```bash
cd desktop_notifier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --init-config --config ./config.json
```

配置文件格式：

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

`server_url` 和 `token` 必填；管理员 Token 具有管理权限，应作为敏感凭据保存。`RCH_NOTIFIER_SERVER_URL`、`RCH_NOTIFIER_TOKEN`、`RCH_NOTIFIER_BACKEND` 可覆盖对应配置。重连间隔须为正数，初始间隔不得大于最大间隔。`state.json` 位于所选配置文件同级目录，保存最近处理的游标。

## 本地通知验证

```bash
python run.py --config ./config.json --test-notification
```

该命令只测试操作系统通知接口，不连接 Server。macOS 支持 `usernotifications`、`osascript` 及 `auto`（优先 UserNotifications，失败时使用 osascript）。检查系统 Notifications 授权、专注模式及 Python 进程的运行环境。Windows 提供 PowerShell / WinRT Toast 后端，实机验证仍待完成。

常驻程序支持 headless 模式；macOS 还提供 `--tray` 菜单栏模式，用于显示连接状态、测试通知、重新连接和退出。当前联机限制适用于两种模式。
