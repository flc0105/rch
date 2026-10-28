# macOS launchd Service Management

本文说明 RCH Client 在 macOS 上使用 launchd 管理 LaunchAgent 与 LaunchDaemon 的长期运行模型，包括安装位置、launchd domain、目标用户、生命周期动作、plist 参数、权限、日志、Watchdog 协作方式以及常用验收方法。Script Library 的通用执行模型见 [Scripts](scripts.md)；Client 启动形态与 `launch_mode` / `launch_source` 见 [Client Launch Mode](launch_mode.md)。

## 1. 运行模型

RCH 将 LaunchAgent 与 LaunchDaemon 统一交给 `client.runtime.sdk.launchd` 管理。Manager 使用明确的 launchd domain 和 service target，不依赖调用脚本时碰巧所在的 bootstrap context，也不使用旧式 `launchctl load/unload/list` 作为生命周期入口。

默认 label 为：

```text
com.rch.client
```

两类服务的目标如下：

| Kind | Plist 位置 | launchd domain | Service target | 运行身份 |
| --- | --- | --- | --- | --- |
| `agent`, `scope=user` | `<target_home>/Library/LaunchAgents/<label>.plist` | `gui/<uid>` | `gui/<uid>/<label>` | 目标 GUI 用户 |
| `agent`, `scope=global` | `/Library/LaunchAgents/<label>.plist` | `gui/<uid>` | `gui/<uid>/<label>` | 指定目标 GUI 用户 |
| `daemon` | `/Library/LaunchDaemons/<label>.plist` | `system` | `system/<label>` | `root` |

`scope=global` 只改变 LaunchAgent plist 的安装位置；它仍然是用户级 Agent，实际控制时仍绑定一个具体的 `gui/<uid>` domain。LaunchDaemon 才属于 `system` domain。

## 2. 生命周期动作

对外动作固定为六个：

| Action | 行为 |
| --- | --- |
| `install` | 写入或替换 plist。若旧定义当前已加载，先将旧定义从 domain 移除；安装完成后保持 stopped，不自动执行 `start`。 |
| `start` | 要求 plist 已安装；未加载时先 `bootstrap` 到目标 domain，再 `kickstart` 立即启动。 |
| `stop` | 对当前 service 执行 `bootout`，保留 plist。即使 `KeepAlive=true`，也不会因为单纯结束进程而立刻被 launchd 拉起。 |
| `restart` | 已加载时使用 `kickstart -k` 重启；已安装但当前 stopped 时按 `start` 恢复。 |
| `uninstall` | 如有需要先 `bootout`，随后删除 plist。 |
| `status` | 查询 plist 是否存在，并通过目标 service 的 `launchctl print` 状态报告 installed、loaded、running、PID、domain 与 plist path。 |

`loaded` 是状态字段，不是公开动作。`start` 和 `stop` 已经包含注册/移除当前 launchd service 所需的 `bootstrap` / `bootout` 操作。

## 3. Script SDK

Script 可以直接使用统一 SDK：

```python
from client.runtime.sdk import launchd

result = launchd.manage(
    kind=kwargs.get('kind', 'agent'),
    action=kwargs.get('action', 'status'),
    label=kwargs.get('label', launchd.DEFAULT_LAUNCHD_LABEL),
    scope=kwargs.get('scope', 'user'),
    target_user=kwargs.get('target_user') or None,
    keep_alive=kwargs.get('keep_alive', True),
    run_at_load=kwargs.get('run_at_load', True),
)
print(launchd.format_result(result))
```

`kind` 支持 `agent` 与 `daemon`。公开 `action` 只接受：

```text
install
start
stop
restart
uninstall
status
```

如果 Script Metadata 需要一个统一管理表单，建议把 `kind` 暴露为 select，同时保留 `label`、`action`、`keep_alive`、`run_at_load`。`scope` 与 `target_user` 只对 Agent 有意义；Daemon 固定使用 system scope 和 root 身份。

### macOS ACMD 命令

macOS Client 在终端中提供 `acmd launchd`，调用与 Script 相同的 `client.runtime.sdk.launchd`。`action` 和 `kind` 是执行时必须确定的参数：可用前两个位置参数或 `--action`、`--kind` 指定；未填写时由 Interaction Broker 的选择框依次收集。确定后会显示操作预览并要求批准，预览包括服务标签及 `KeepAlive`、`RunAtLoad` 的默认或自定义值，Agent 还会展示 `scope` 与目标用户。可选参数保持脚本相同的默认值，不额外弹出选项表单：

```text
acmd launchd install agent --scope user --keep-alive true
acmd launchd --action start --kind agent
acmd launchd status agent
acmd launchd
acmd launchd restart daemon
acmd launchd uninstall agent --label com.rch.client
acmd launchd status agent --json
acmd launchd status agent --no-confirm
acmd help launchd
```

`--no-confirm` 在 `action` 和 `kind` 都已明确提供时直接执行，跳过全部 Interaction Broker 请求；缺少其中任一项则返回参数错误，避免在无人确认的情况下替用户选择服务操作。取消或拒绝预览时，不调用 launchd SDK。

`action` 可选 `install`、`start`、`stop`、`restart`、`uninstall`、`status`；`kind` 可选 `agent`、`daemon`。其他选项与 Script Schema 的默认值一致：

| 参数 | 默认值 | 适用范围 |
| --- | --- | --- |
| `--label` | `com.rch.client` | Agent / Daemon |
| `--json` | `false` | 输出 SDK 原始结果的 JSON 表示，不改变交互审批 |
| `--keep_alive` / `--keep-alive` | `true` | 安装时写入 KeepAlive |
| `--run_at_load` / `--run-at-load` | `true` | 安装时写入 RunAtLoad |
| `--scope` | `user` | Agent；可选 `user`、`global` |
| `--target_user` / `--target-user` | 空（自动解析 GUI 用户） | Agent |

布尔参数需要明确值，如 `--keep-alive false`。Daemon 使用 system domain 与 root 身份，不使用 Agent 的 `scope`、`target_user`。管理系统级 Daemon / global Agent 需要相应 macOS 权限。`install` 只写入服务定义，启动需要单独执行 `start`。默认输出沿用 SDK 的 Terminal 文本格式，包含操作、目标、Installed、Loaded、Running、PID 和 plist 路径。添加 `--json` 时，命令通过 `StructuredCommandResult` 输出 launchd SDK 的结果对象，并保留布尔值、数字和空值等 JSON 类型；该选项不改变 Preview / Approve 流程。`--json --no-confirm` 同样直接执行并输出 JSON。

## 4. KeepAlive 与 RunAtLoad

`keep_alive` 与 `run_at_load` 分别写入 plist：

```text
KeepAlive
RunAtLoad
```

它们可以独立配置。

- `RunAtLoad=true`：job 被 launchd 加载进目标 domain 时具备启动条件。对 LaunchAgent，常见场景是用户 GUI session 建立并加载 Agent；对 LaunchDaemon，则对应 system job 被加载。
- `KeepAlive=true`：job 在仍由 launchd 管理的情况下退出后，launchd 可以按 plist 策略再次启动它。
- `stop` 使用 `bootout` 将 service 从当前 domain 移除，因此 `KeepAlive=true` 不会抵消明确的停止动作。
- `install` 只建立/更新定义，不代表当前 session 已经 started。

需要立即运行已安装服务时使用 `start`；需要应用同一份 plist 并重启当前实例时使用 `restart`。

## 5. 目标用户与 Home 目录

LaunchDaemon 的 effective user 就是 root，root Home 保持系统账户定义的值，例如 `/var/root`。RCH 不会把 root 的 Home 全局替换成当前桌面用户目录。

LaunchAgent 是面向具体 GUI 用户的操作，Manager 按以下顺序解析 target user：

1. 显式 `target_user`；
2. 当前进程不是 root 时的 effective user；
3. 通过 `sudo` 提权时的 `SUDO_UID` / `SUDO_USER`；
4. 当前 macOS console user。

最终 UID、GID、username 与 Home 从 POSIX account database 取得。无法确定目标 GUI 用户时，要求显式传入 `target_user`，而不是用 `/var/root` 或环境变量 `HOME` 代替。

这套 target-user 解析只服务于“面向哪个用户安装/控制 LaunchAgent”。Client 自己的 runtime config、权限身份与其他普通路径仍按实际运行账户处理。

## 6. Plist 内容与启动上下文

Manager 直接把当前 Client 可执行命令拆成 `ProgramArguments`，不经过 `/bin/sh -c`。同时保存当前 runtime root 为 `WorkingDirectory`，并根据参数写入 `RunAtLoad` 与 `KeepAlive`。

Manager 还会为被 launchd 启动的新 Client 写入标准化环境：

```text
LaunchAgent:
RCH_CLIENT_LAUNCH_MODE=user_service
RCH_CLIENT_LAUNCH_SOURCE=launchagent

LaunchDaemon:
RCH_CLIENT_LAUNCH_MODE=system_service
RCH_CLIENT_LAUNCH_SOURCE=launchdaemon
```

因此 Server Basic Info 与 Connection History 可以稳定显示 `User service (LaunchAgent)` 或 `System service (LaunchDaemon)`，不需要依赖父进程链猜测。完整字段定义与其他启动方式见 [Client Launch Mode](launch_mode.md)。

## 7. 日志与权限

用户 scope (`scope=user`) 的 LaunchAgent 会把 stdout/stderr 日志写到：

```text
<target_home>/Library/Logs/RCH/
```

当前 global Agent (`scope=global`) 的 plist 不额外指定 `StandardOutPath` / `StandardErrorPath`，输出行为由 launchd 的运行环境处理。LaunchDaemon 的 stdout/stderr 日志位于：

```text
/Library/Logs/RCH/
```

用户级 Agent 的日志目录保持目标用户私有。Daemon 与 global Agent 的 plist 安装需要 root；Daemon 的 start/stop/restart 也要求 root Client。用户级 Agent 可以由目标用户自身或 root 管理；跨用户 Agent 管理要求 root。

Client 自己的临时工作区与 launchd 日志目录是两套路径。POSIX Client temp root 按 effective UID 隔离，例如：

```text
/tmp/rch_client_temp_u501/
/tmp/rch_client_temp_u0/
```

实际系统 temp base 可能因 GUI session、cron、root 或其他环境不同而变化；同一 temp base 内仍使用 `_u<effective_uid>` 隔离，避免 root 与普通用户争用同一个 `0700` private 目录。Client 主日志与 temp 目录规则见 [Server / Client Logging](logging.md)。

## 8. launchd 与 Client Watchdog

LaunchAgent / LaunchDaemon 下，launchd 是 Client 唯一的自动生命周期 owner。Client 会抑制以下三类 Watchdog：

- Process Watchdog；
- Local Heartbeat Watchdog；
- Remote HTTP Watchdog。

即使 runtime config 中保存的对应开关为 `true`，当前 launchd Client 的 effective 状态仍为 disabled/suppressed；保存的配置值不会被改写。离开 launchd 后，以 Terminal、IDE 或 Detached 等方式启动的新 Client 会重新按原 runtime config 生效。

这样可以保证：

- `stop` 后不会被 Process Watchdog 重新拉出一个 Detached Client；
- Local Heartbeat 不会在 launchd 之外创建 replacement Client；
- Remote HTTP relaunch/clone 不会形成第二套独立生命周期链；
- `KeepAlive` 的恢复策略只由 launchd 执行。

Web 的 **info → Watchdog** 会显示当前生命周期由 LaunchAgent 或 LaunchDaemon 管理。`watchdog` Feature 为 `true`，相关实现已加载；三个模式的 `set` 开关可以保存配置，当前进程的实际运行状态仍是 suppressed。HTTP Control 的三个按钮保持显示，托管期间不可执行。详细状态字段见 [Watchdog](watchdog.md)。

## 9. 状态检查

Manager 的 `status` 输出至少包括：

```text
Action: status
Kind: agent
Label: com.rch.client
Target: <username> (gui/<uid>)
Installed: yes
Loaded: yes
Running: yes
PID: <pid>
Plist: <path>
```

也可以直接用 `launchctl` 检查目标 service：

```bash
# 当前 GUI 用户的 LaunchAgent
launchctl print "gui/$(id -u)/com.rch.client"

# LaunchDaemon
sudo launchctl print system/com.rch.client
```

对另一个用户的 Agent，将 `$(id -u)` 替换为目标 UID。

`Installed=yes / Loaded=no` 是正常状态，表示 plist 在磁盘上，但当前 service 没有注册在对应 domain；执行 `start` 会完成 bootstrap 并立即 kickstart。

## 10. 实机验收流程

### LaunchAgent

建议按以下顺序验证统一 manager：

1. `kind=agent, action=install, scope=user, target_user=<user>`。
2. `status`：预期 `Installed=yes, Loaded=no, Running=no`。
3. `start`：预期 `Loaded=yes, Running=yes`，并获得 PID。
4. Server Basic Info：预期 `Launch Mode = User service (LaunchAgent)`。
5. `stop`：预期 `Installed=yes, Loaded=no, Running=no`，plist 仍存在。
6. 等待超过 Process Watchdog 的首个恢复退避时间，确认没有 Detached Client 被重新创建。
7. `start` 后再执行 `restart`，预期继续以 LaunchAgent 身份上线。
8. `uninstall`：预期 plist 消失，`Installed=no`。

### LaunchDaemon

在 root/elevated Client 中执行同样流程：

1. `kind=daemon, action=install`；
2. `start`；
3. Basic Info 预期 `System service (LaunchDaemon)`；
4. `stop` 后确认没有其他 Client Watchdog 恢复进程；
5. `restart` / `uninstall` 按需验证。

Daemon plist 应位于：

```text
/Library/LaunchDaemons/com.rch.client.plist
```

### 验证 Watchdog suppression

先在 runtime config 中把 Process、Local、Remote 三个 Watchdog 都设为 enabled，再通过 LaunchAgent 或 LaunchDaemon 启动 Client。预期：

- Watchdog 页面显示 lifecycle managed by LaunchAgent/LaunchDaemon；
- 三个 effective enabled 都为 false/suppressed；
- 系统进程列表中没有该 Client 对应的 `--process-watchdog-worker` 或 `--watchdog-worker`；
- `stop` 后 Client 保持停止，直到再次执行 launchd `start`。

## 11. 常见问题

| 现象 | 检查点 |
| --- | --- |
| plist 已存在但服务没运行 | 先看 `status` 的 Loaded/Running；Installed 与 Loaded 是不同状态，已安装服务用 `start` 激活。 |
| Agent 写到了 `/var/root/Library/LaunchAgents` | 不要用 root 的 `expanduser('~')` 作为目标用户 Home；使用 manager 的 `target_user` 解析。 |
| global Agent 已安装但指定用户没运行 | 确认当前操作针对正确的 `gui/<uid>` domain，并检查该用户是否有可用 GUI session。 |
| Daemon 操作权限失败 | `/Library/LaunchDaemons` 和 system domain 管理要求 root。 |
| `stop` 后又出现 Detached Client | 检查运行中的 Client 是否已经包含 launchd Watchdog suppression；launchd Client 不应启动 Process/Local/Remote Watchdog。 |
| cron/普通用户 Client 报 `/tmp/rch_client_temp` 权限错误 | 新版本使用按 effective UID 隔离的 Client temp root；确认实际运行 Client 已加载该实现，并清理不再使用的旧共享 temp root。 |
| Basic Info 显示 IDE/Detached 而不是 LaunchAgent/Daemon | 检查 plist 是否由当前 manager 生成并带有标准 Launch Mode 环境；也可用 `launchctl print` 确认实际 service target。 |
