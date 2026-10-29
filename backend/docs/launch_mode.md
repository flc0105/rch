# Client Launch Mode

本文定义 RCH Client 的启动/运行形态字段 `launch_mode` 与 `launch_source`，说明判定规则、Server 展示与历史存储方式，并提供 macOS、Linux、Windows 上的实机测试方法。launchd 的安装、启动、停止与权限模型见 [macOS launchd Service Management](launchd.md)。

## 1. 字段语义

`launch_mode` 表示 Client 当前 OS 进程属于哪一种**外部运行形态**。它不记录某个 RCH 内部动作名。

`launch_source` 保存该形态下可识别的具体宿主、Shell、IDE 或系统服务管理器。

例如：

```text
launch_mode=ide
launch_source=pycharm
```

UI 显示：

```text
IDE (PyCharm)
```

RCH 的 `spawn_instance`、`relaunch_instance`、update、Watchdog recovery 等属于“为什么创建了新进程”的内部动作，不进入 `launch_mode`。如果这些动作最终创建的是独立后台进程，新 Client 统一记录为 `detached`。

普通 Client 命令可通过 `${rch:launch_mode}` 读取标准运行形态，通过 `${rch:launch_detail}` 读取具体宿主信息。变量名使用 `launch_detail`；当前握手和会话快照继续使用 `launch_source` 字段保存同一份细节。完整变量清单见 [RCH Variables](variables.md)。

## 2. 标准 Launch Mode

当前标准 mode 固定为八类：

| `launch_mode` | UI | 含义 | 常见 `launch_source` |
| --- | --- | --- | --- |
| `terminal` | Terminal | 由交互式终端直接运行 | `zsh`, `bash`, `cmd`, `powershell`, `pwsh` |
| `terminal_background` | Terminal background | 仍由 Shell 直接启动，但当前是后台/非交互运行 | `zsh`, `bash`, `powershell` |
| `ide` | IDE | IDE 或受支持的 IDE-like host 直接启动 | `pycharm`, `pythonista` |
| `detached` | Detached | 独立 session/process group 或无控制台的独立后台进程 | `new_session`, `detached_process` |
| `user_service` | User service | 用户级服务管理器托管 | `launchagent`, `systemd_user` |
| `system_service` | System service | 系统级服务管理器托管 | `launchdaemon`, `systemd`, `windows_service` |
| `scheduled` | Scheduled | 调度器启动 | `cron`, `schtasks` |
| `unknown` | Unknown | 当前进程形态无法可靠归入以上类别 | 空 |

当前前端会把 source 格式化为更适合阅读的名称，例如：

```text
Terminal (zsh)
Terminal background (PowerShell)
IDE (PyCharm)
Detached (new session)
User service (LaunchAgent)
System service (LaunchDaemon)
Scheduled (cron)
Scheduled (Task Scheduler)
```

## 3. 判定时机与生命周期

Launch Mode 在 Client 进程生命周期内采集一次并缓存。Socket 断线、重连、Heartbeat 或页面刷新不会重新判定。

这样可以避免父进程退出或进程被系统重新收养后，同一个 Client 的 Launch Mode 在运行期间改变。新的 OS 进程会重新形成自己的 Launch Mode 快照。

Handshake 顶层上报：

```json
{
  "launch_mode": "user_service",
  "launch_source": "launchagent"
}
```

Server 会把这两个字段用于：

- 在线 Connection 的 **Basic Info → Launch Mode**；
- Recent Device / 当前连接摘要；
- Connection History 的会话快照与详情显示。

Connection History 使用既有 `connection_sessions.snapshot_json` 保存这两个独立字段，不需要额外数据库列。旧历史记录没有字段时显示 `Unknown`。握手其它字段见 [Client Handshake & Capability Discovery](client_handshake.md)，历史快照结构见 [RCH Database](rch_database.md)。

## 4. 判定优先级

检测目标是运行形态，不是命令行文本。`argv` 只能说明当前 Python 执行了哪个脚本，通常无法区分 Terminal、PyCharm、launchd 或 Detached。

当前判定按以下优先级工作：

1. **显式标准化环境**：RCH 自己明确知道最终进程形态时，使用 `RCH_CLIENT_LAUNCH_MODE` / `RCH_CLIENT_LAUNCH_SOURCE`。
2. **iOS/Pythonista**：记录为 `ide / pythonista`。
3. **Scheduler / Service manager**：cron、Task Scheduler、systemd、LaunchAgent/LaunchDaemon、Windows Service 优先于中间 Shell。
4. **POSIX 独立 session**：没有交互 TTY 且当前进程是 session leader 时，记录为 `detached / new_session`。
5. **直接 Shell**：识别 zsh/bash/sh/fish/CMD/PowerShell 等直接父进程，再根据 TTY、前台进程组或 Windows console 判断 Terminal / Terminal background。
6. **IDE**：识别 PyCharm / pydevd / JetBrains 环境。
7. **剩余交互式 TTY**：记录为 `terminal`，source 可为空。
8. **Windows 无控制台剩余进程**：记录为 `detached / detached_process`。
9. 其他情况：`unknown`。

Service/Scheduler 检测会查看进程祖先链，因此 `cron → sh -c → python` 仍能归为 `Scheduled (cron)`。Shell 分类只认**直接父 Shell**，这样 PyCharm 内置 Terminal 会显示 Terminal，而 PyCharm Run/Debug 会显示 IDE。

## 5. RCH 自己创建的新 Client

普通 Duplicate/Restart 与 SSH Bootstrap 等路径创建独立 Client，并显式传递 detached 形态：

- POSIX：`start_new_session=True`，记录 `detached / new_session`；
- Windows：独立后台进程，记录 `detached / detached_process`。

启动环境中显式传递标准化形态；短生命周期 Bootstrap 退出后，即使 Client 被 PID 1 收养，仍保留 `detached / new_session`。环境里不传 `spawn_instance`、`relaunch_instance` 等内部动作名。因此即使原 Client 来自 `IDE (PyCharm)`，新建的独立 Client 仍显示 `Detached (...)`。

macOS `spawn_elevated_instance --detached` 也通过短生命周期提权 bootstrap 创建真正的 new-session root Client，最终显示 `Detached (new session)`。默认不带 `--detached` 的 elevated 启动保留原调用链，Launch Mode 按其真实宿主环境判定。

LaunchAgent / LaunchDaemon 由统一 launchd manager 显式写入 `user_service/launchagent` 或 `system_service/launchdaemon`；详见 [macOS launchd Service Management](launchd.md)。

## 6. 测试准备

下面的命令用于**实机验证 Launch Mode**。执行前建议：

1. 停掉不相关的 RCH Client，或者记录本次测试 Client 的 PID/client_id，避免多实例看混；
2. 将 `<RCH_ROOT>` 替换为项目根目录；
3. 将 `<PYTHON>` 替换为当前实际 Python，例如 macOS framework Python 或 Windows `python.exe`；
4. 每次新进程上线后，在 **Connection Info → Basic Info → Launch Mode** 查看当前值；
5. 结束测试后再到 Connection History 查看对应会话是否保存相同 mode/source。

## 7. macOS 测试

### 7.1 Terminal

```bash
cd <RCH_ROOT>
<PYTHON> backend/rchclient.py
```

预期通常为：

```text
Terminal (zsh)
```

使用 bash/fish 等 Shell 时 source 会相应变化。

### 7.2 Terminal background

普通 Shell 后台任务：

```bash
cd <RCH_ROOT>
<PYTHON> backend/rchclient.py &
```

或者：

```bash
cd <RCH_ROOT>
nohup <PYTHON> backend/rchclient.py </dev/null >/tmp/rch-bg.log 2>&1 &
```

保持启动它的 Terminal/Shell 存活并尽快查看结果。预期：

```text
Terminal background (zsh)
```

这里的标准类别是 `terminal_background`，不会把具体命令名 `nohup` 保存成 source。

### 7.3 PyCharm Run / Debug

在 PyCharm 中创建普通 Python Run/Debug Configuration，目标脚本设为：

```text
<RCH_ROOT>/backend/rchclient.py
```

预期：

```text
IDE (PyCharm)
```

反向测试：在 PyCharm 的内置 Terminal 中手动执行同一 Python 命令，预期仍是 `Terminal (zsh)`，因为直接宿主是 Shell。

### 7.4 Detached

最直接的项目内测试是对现有在线 Client 使用 **Duplicate connection** 或 **Restart connection**。新进程预期：

```text
Detached (new session)
```

Elevated 独立实例可以执行：

```text
spawn_elevated_instance --detached
```

预期 root Client 同样为 `Detached (new session)`；关闭原 IDE/Terminal 后，新 PID 应继续存在。

### 7.5 LaunchAgent

优先使用统一 [launchd manager](launchd.md)：

```text
kind=agent
scope=user
target_user=<user>
action=install
```

随后：

```text
action=start
```

预期：

```text
User service (LaunchAgent)
```

可在目标用户会话中验证 service：

```bash
launchctl print "gui/$(id -u)/com.rch.client"
```

使用自定义 label 时替换 `com.rch.client`。

### 7.6 LaunchDaemon

在 root/elevated Client 中通过统一 manager：

```text
kind=daemon
action=install
```

再执行：

```text
action=start
```

预期：

```text
System service (LaunchDaemon)
```

系统侧检查：

```bash
sudo launchctl print system/com.rch.client
```

LaunchAgent / LaunchDaemon 下 Client 的 Process Recovery Watchdog、Local Heartbeat Watchdog 与 Remote Control Watchdog 都被抑制，生命周期只由 launchd 管理。

### 7.7 cron / Scheduled

编辑当前用户 crontab：

```bash
crontab -e
```

临时加入一行：

```cron
* * * * * cd <RCH_ROOT> && <PYTHON> backend/rchclient.py >>/tmp/rch-cron.log 2>&1
```

等待第一次上线，预期：

```text
Scheduled (cron)
```

验证完成后立即从 `crontab -e` 删除该行，避免每分钟继续创建实例。

POSIX Client temp root 按 effective UID 隔离；如果仍看到旧版 `/tmp/rch_client_temp` 的跨用户权限错误，先确认正在运行的 Client 已更新到 UID 隔离实现。

### 7.8 Unknown

下面的 wrapper 保持自己存活，直接创建一个无 TTY、但**不建立新 session**的 Client；它不属于已知 Shell、IDE、service 或 scheduler：

```bash
cd <RCH_ROOT>
<PYTHON> -c 'import subprocess,sys; f=open("/tmp/rch-unknown.log","ab"); subprocess.run([sys.executable,"backend/rchclient.py"],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=False)'
```

预期：

```text
Unknown
```

## 8. Linux 测试

### Terminal / Terminal background / Detached / cron

Linux 的 Terminal、后台 Shell 与 cron 可以直接复用上一节对应命令。RCH 创建的 new-session Client 预期 `Detached (new session)`。

### systemd --user

将 Client 作为当前用户的 systemd user service 运行，预期：

```text
User service (systemd --user)
```

检测器通过 systemd 进程形态和 `INVOCATION_ID` 识别 systemd job。普通 Terminal 即使祖先链最终回到 systemd user manager，只要直接父进程仍是 Shell，就保持 Terminal 分类。

### system systemd

系统级 unit 直接运行 Client，预期：

```text
System service (systemd)
```

## 9. Windows 测试

### 9.1 CMD

```cmd
cd /d <RCH_ROOT>
<PYTHON> backend\rchclient.py
```

预期：

```text
Terminal (CMD)
```

### 9.2 PowerShell

```powershell
Set-Location <RCH_ROOT>
& <PYTHON> backend\rchclient.py
```

预期：

```text
Terminal (PowerShell)
```

### 9.3 Terminal background

在保持当前 PowerShell 窗口存活的情况下，用无控制台 Python 启动：

```powershell
$Py = (Get-Command pythonw.exe).Source
Start-Process $Py -ArgumentList '<RCH_ROOT>\backend\rchclient.py' -WorkingDirectory '<RCH_ROOT>'
```

在父 PowerShell 仍存在时，预期：

```text
Terminal background (PowerShell)
```

如果父 Shell 已退出，后续进程树信息可能不同，因此此项测试应在启动后立即查看。

### 9.4 PyCharm

通过 PyCharm Run/Debug Configuration 运行 `backend\rchclient.py`：

```text
IDE (PyCharm)
```

PyCharm 内置 Terminal 中手动运行则应显示 Terminal，而不是 IDE。

### 9.5 Detached

使用 RCH **Duplicate connection / Restart connection** 创建新 Client，预期：

```text
Detached (detached process)
```

这也是 Windows 上验证标准 detached helper 最稳定的方式。

### 9.6 Task Scheduler

先创建一次性任务，再手动运行。下面示例在 CMD 中执行；替换真实 Python 与项目路径：

```cmd
schtasks /Create /TN RCHLaunchModeTest /TR "\"C:\Path\Python312\python.exe\" \"C:\Path\rch\backend\rchclient.py\"" /SC ONCE /ST 23:59 /F
schtasks /Run /TN RCHLaunchModeTest
```

预期：

```text
Scheduled (Task Scheduler)
```

测试结束：

```cmd
schtasks /Delete /TN RCHLaunchModeTest /F
```

### 9.7 Windows Service

Client 由真正的 Windows Service/SCM 运行时，进程祖先可识别为 `services.exe`，预期：

```text
System service (Windows Service)
```

普通 Python 脚本本身不实现 Windows Service 协议；测试时应使用项目实际部署的 Service wrapper 或受支持的 Windows Service 宿主。

## 10. iOS / Pythonista

Pythonista Client 统一记录为：

```text
IDE (Pythonista)
```

该分类用于表达当前 Client 的宿主环境，不代表 Pythonista 具备完整桌面系统进程/服务能力。平台能力边界见 [iOS / Pythonista](ios_pythonista.md)。

## 11. 排障

| 现象 | 检查方式 |
| --- | --- |
| PyCharm Run 显示 Terminal | 查看是不是实际从 PyCharm 内置 Terminal 手动启动；直接父进程为 Shell 时分类就是 Terminal。 |
| Duplicate/Restart 后仍显示 IDE | 新 Client 应使用标准 detached 环境；检查运行代码是否已包含 detached launch marker。 |
| LaunchAgent/Daemon 显示 IDE/Unknown | 用统一 launchd manager 安装，检查 plist 的 Launch Mode 环境，并用 `launchctl print` 确认真实 service target。 |
| cron 显示 Terminal background | 检查进程祖先中是否还能识别 cron/crond；scheduler 检测应优先于中间 `sh -c`。 |
| 同一 Client 重连后分类没有变化 | 这是预期行为；Launch Mode 是进程级快照，不是每次网络连接重新采集。 |
| History 中旧记录显示 Unknown | 旧会话快照没有 `launch_mode/launch_source` 时不会回填推断。 |
| 无法区分具体第三方 launcher | 保持 `Unknown` 比根据相似 argv 猜测更准确；新增正式 source 前应先有稳定外部特征。 |
