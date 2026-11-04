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

1. **iOS/Pythonista**：记录为 `ide / pythonista`。
2. **Scheduler / Service manager**：cron、Task Scheduler 根据实际进程宿主识别；macOS 通过运行中的 launchd 作业和 PID 验证；Linux 将当前进程的 cgroup 所属 `.service` unit 与 `systemctl show` 的 `ActiveState=active`、`MainPID` 精确核对；Windows 将当前 PID 与运行中的 SCM 服务注册信息匹配。
3. **POSIX 独立 session**：没有交互 TTY 且当前进程是 session leader 时，记录为 `detached / new_session`。
4. **直接 Shell**：识别 zsh/bash/sh/fish/CMD/PowerShell 等直接父进程，根据控制终端或前台进程组判断。Windows 先通过 `GetConsoleProcessList` 核实当前进程是否附着控制台，再检查标准流是否可交互。继承的控制台句柄和 `GetConsoleWindow()` 都不能单独证明 Terminal；没有控制台附着的 Shell 子进程归为 Detached。
5. **IDE**：识别 PyCharm / pydevd / JetBrains 环境。
6. **剩余交互式 TTY**：记录为 `terminal`，source 可为空。
7. **Windows 无控制台剩余进程**：记录为 `detached / detached_process`。
8. **macOS 无控制终端**：在没有已验证服务、Shell 或 IDE 宿主时，若系统报告没有控制终端则归为 `detached`。其他情况为 `unknown`。

Service/Scheduler 检测会查看进程祖先链，因此 `cron → sh -c → python` 仍能归为 `Scheduled (cron)`。Shell 分类只认**直接父 Shell**，这样 PyCharm 内置 Terminal 会显示 Terminal，而 PyCharm Run/Debug 会显示 IDE。

## 5. RCH 自己创建的新 Client

普通 Duplicate/Restart 与 SSH Bootstrap 等路径创建独立 Client：

- POSIX：`start_new_session=True`，记录 `detached / new_session`；
- Windows：使用 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` 创建独立后台进程，记录 `detached / detached_process`；PowerShell One-liner 也经短生命周期 Python 启动器使用同一组进程标志。

各平台均根据进程与服务管理器的实际状态确认 Launch Mode。macOS 的短生命周期 Bootstrap 退出、Client 被 `launchd` 收养后，仍按它自己的 session/控制终端状态归类。原 Client 即使来自 `IDE (PyCharm)`，采用 `start_new_session=True` 启动的新 Client 也按实际新会话显示 `Detached`。

macOS `spawn_elevated_instance` 经系统管理员授权后，由 root shell 执行 `get_executable_path()` 提供的原始 Client 启动命令；不会向 Client 追加内部 bootstrap 参数。命令返回**新 Client 的实际 PID**；如果管理员取消授权、启动失败或 Client 立即退出，则返回错误详情。启动时保留原有命令行参数，包括 `--profile tls-local` 等连接配置，TLS 校验沿用对应 profile。`--detached` 使用新 Session，预期显示 `Detached (new session)`；默认模式不强制新建 Session，Launch Mode 按实际进程状态判定。返回 PID 表示已启动 Client 进程；Server 上线状态仍需单独核实。

在 macOS 实机测试时，先运行 `spawn_elevated_instance`，再用 `ps -o pid,ppid,user,command -p <PID>` 验证返回的 PID 确实属于 root Python Client（不是 `osascript`）。可进一步用 `acmd ps --pid <PID>` 检查进程，并在 Server 设备列表中确认新实例使用目标 Listener 上线。如果命令报告启动失败，查看其错误输出；若新进程启动后没有上线，查看回执中给出的 root Client 启动 stderr 日志路径。

LaunchAgent / LaunchDaemon 的判定读取当前 launchd 作业的实际 PID 和类型，安装的 plist 无需写入启动模式标记。详见 [macOS launchd Service Management](launchd.md)。

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

检测器读取 `/proc/<pid>/cgroup` 所属的 systemd `.service` unit，要求 `systemctl --user show <unit>` 的 `MainPID` 为当前 Client PID 且 `ActiveState=active`。一般终端和服务启动的其他子进程不会因为父进程是 systemd 或继承 `INVOCATION_ID` 而误判为用户服务。

### system systemd

系统级 unit 直接运行 Client，且 `systemctl show <unit>` 的 `MainPID` 为 Client PID、`ActiveState=active` 时，预期：

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

### 9.3 无控制台后台进程

在保持当前 PowerShell 窗口存活的情况下，用无控制台 Python 启动：

```powershell
$Py = (Get-Command pythonw.exe).Source
Start-Process $Py -ArgumentList '<RCH_ROOT>\backend\rchclient.py' -WorkingDirectory '<RCH_ROOT>'
```

预期：

```text
Detached (detached process)
```

`pythonw.exe` 不提供交互控制台；PowerShell 中直接执行 `python.exe`，仍按 9.2 验证 Terminal 模式。

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

### 9.5.1 Windows elevated background launch

`spawn_elevated_instance --detached` 经 Windows UAC 授权后，由短生命周期 Python 启动器以 `DETACHED_PROCESS` 创建无控制台的 elevated Client，复用原 Client 启动参数并返回新进程的 PID；启动失败时返回错误及日志路径。新 Client 在握手时报告 `Detached (detached process)`。不带参数的 `spawn_elevated_instance` 仍按原行为启动可见控制台。此方式需要本机可用的 Python 解释器；`--no-confirm` 仅跳过 RCH 的交互确认，仍需 Windows UAC 授权。在 Session 0 或无可交互桌面的环境中应使用适当的系统服务启动方式。

### 9.6 Task Scheduler

现代 Windows 的 Task Scheduler 可能通过运行 Schedule 服务的 `svchost.exe` 启动程序，也可能经过 `taskeng.exe` / `taskhostw.exe`。RCH 检查这些实际调度宿主，以及 `Schedule` 服务的 PID；如果进程关系已消失、无法确认调度宿主，就按当前进程的控制台状态分类。每个 Client 在启动时采样一次，改变任务定义后需启动新进程才能更新。


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

Client 的 PID 与 Windows Service Control Manager 当前运行的服务 PID 一致时，预期：

```text
System service (Windows Service)
```

普通 Python 脚本本身不实现 Windows Service 协议；测试时应使用将 **Client 进程本身** 注册为服务 PID 的服务宿主。若服务 wrapper 另行派生 Python 子进程、SCM 登记的 PID 仍属于 wrapper，则 Python Client 按自身进程状态分类。

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
| Duplicate/Restart 后仍显示 IDE | 检查新 Client 是否真正独立启动（POSIX `start_new_session=True`），以及 session ID 与进程 PID。 |
| LaunchAgent/Daemon 显示 IDE/Unknown | 运行 `launchctl list` 核对当前 Client PID 对应的作业，再以 `launchctl print gui/<uid>/<label>`、`user/<uid>/<label>` 或 `system/<label>` 核对 `state`、`pid` 和 `type`。 |
| cron 显示 Terminal background | 检查进程祖先中是否还能识别 cron/crond；scheduler 检测应优先于中间 `sh -c`。 |
| 同一 Client 重连后分类没有变化 | 这是预期行为；Launch Mode 是进程级快照，不是每次网络连接重新采集。 |
| History 中旧记录显示 Unknown | 旧会话快照没有 `launch_mode/launch_source` 时不会回填推断。 |
| 无法区分具体第三方 launcher | 保持 `Unknown` 比根据相似 argv 猜测更准确；新增正式 source 前应先有稳定外部特征。 |
