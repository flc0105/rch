# Process Watchdog — Client 进程意外死亡后复活

`process_watchdog` 是与现有 **Local Heartbeat Watchdog** 和 **Remote HTTP Watchdog** 独立的进程监督功能。它仅检测 Client **操作系统进程是否死亡**，不使用 Local 心跳文件，也不把 Socket 断开等同于进程崩溃。即使 Server 暂时不可访问，只要 Client 进程存活，它也不会触发重启。

## 启用与控制

默认 `PROCESS_WATCHDOG_ENABLED = False`，在 `client/config/runtime_config.py` 声明。运行中的 Client 可通过 `set PROCESS_WATCHDOG_ENABLED true` 启用、`set PROCESS_WATCHDOG_ENABLED false` 关闭；设置按项目现有 runtime_config 覆盖文件持久化。建议先在非关键设备验证，再远程开启。运行时切换本开关会刷新现有 Remote/Local 控制 Worker 的启动环境，以便它正确区分主动退出；监控逻辑和检测依据仍然完全独立。

开启后，Client 在建立连接之前启动单独的 `--process-watchdog-worker` 进程。Worker 使用 `psutil` 的进程身份标识（PID 加内部启动标识）区分 PID 复用及僵尸进程；在 macOS/Linux 上使用不受 NTP 校时影响的单调启动时间。正常情况下只保留一条监督链：Client 死亡后，原 Worker 按 3、10、30、60、120、最高 300 秒的退避间隔重启 Client；运行至少 300 秒视为恢复稳定，重置连续失败计数。Worker 持续重试，不因达到失败次数而永久放弃。

复活后的 Client 继承内部监督会话标记并复用原 Worker，不再次创建 Worker。单独 `spawn_instance`、`clone` 或 `reset` 创建的新实例**不继承**原监督会话，会独立建立自己的监督链。`reexec` 仍在同一 PID 内执行，监督会话保留。

单独的轮转日志存储于 Client 外部运行时配置目录下 `logs/process_watchdog.log`（包括 `.1`、`.2` 备份）。Remote HTTP 和 Local Heartbeat 的日志也统一使用同一 `logs/` 目录，各自保留独立日志文件。Worker 的临时控制目录只用于本次监督会话，不承载业务数据。

## 有意关闭、重启和更新

- `kill_connection`、本机 `KeyboardInterrupt` 以及 Remote HTTP `kill` 在退出前明确停止 Process Watchdog，不会因为主动关闭而自动复活。
- `reset` 与 Remote HTTP `relaunch` 先建立独立新 Client，再停止旧实例的监督链；新实例自己负责保护。
- `reexec` 沿用原 PID 与监督关系；意外失败则由 Supervisor 尝试恢复。
- `update` 下载并启动的新 Client 在 **PID/握手就绪验证完成前不启用** Process Watchdog。旧 Client 确认验收后通过临时 `.accepted` 标记激活新 Client，再等待 `.adopted` 确认。只有验收通过才能交接。`--keep-old` 保留旧监督链；普通更新退出旧 Client 前停止旧监督链。

注意：如果用户在系统层直接 `kill -9` 或强制结束 Client，Supervisor 无法辨别人工操作还是意外死亡，默认视为异常并复活。要永久停止 Client，请先禁用 Process Watchdog，或使用正式生命周期命令。

## 与另外两种 Watchdog 的设计差异

| Watchdog | 判断依据与负责场景 | 运行组件 | 发现故障后的动作 |
| --- | --- | --- | --- |
| Remote HTTP | 周期向 Server Web 轮询待执行的 `kill`、`relaunch`、`clone` 指令；不是健康探测 | 与 Local 共用的 `ClientWatchdogProcess` Worker | 收到指令后按动作控制进程 |
| Local Heartbeat | Client 内的 `LocalWatchdogHeartbeatFeeder` 线程写时间戳，Worker 检查文件是否超过超时阈值；目标是“进程尚在但心跳停了” | Client 心跳线程 + Remote/Local 共用 Worker | 心跳超时后尝试 `relaunch` |
| Process | 操作系统进程是否还活着；目标是“Client 进程已经消失” | 独立的 `--process-watchdog-worker` Supervisor | 退避后重建 Client，并继续监控新 PID |

Remote/Local 由 `client/watchdog/client_guard_manager.py` 管理，实际共享 `client/watchdog/watchdog_process.py` 创建的 Worker；Process 由 `client/watchdog/process_watchdog.py` 中的 `ProcessWatchdogManager` 和独立 `run_process_supervisor()` 管理。三个功能的配置、故障依据和生命周期相互独立，状态查询才把它们组合展示。Remote/Local 的 Worker 遇到原 Client 消失会结束监控，**只有 Process Supervisor 会在 Client 消失后继续运行并尝试复活**。

### Process 存活扫描的真实实现

Process Supervisor **不遍历系统全部进程**，也不读取 Local 心跳文件。每次探测只针对当前受监控的单个 PID 调用 `psutil.Process(pid)`：

1. 读取 `psutil.Process(pid)._ident[1]` 并与 Supervisor 保存的启动标识比较，防止 PID 复用。psutil 7.2.2 在 macOS/Linux 使用单调启动时间；这里不再使用会被系统时钟/NTP 校正影响的 `create_time()` 墙上时钟时间戳，也不通过扩大时间容差规避问题。
2. 检查 `process.is_running()`，再检查 `process.status() != psutil.STATUS_ZOMBIE`，排除已经退出的僵尸进程。
3. 找不到 PID（`psutil.NoSuchProcess`）视为死亡；权限不足、OS 读取错误、暂时无法取得身份标识时保守地按存活处理。进程身份确实不同才认作 PID 被复用。
4. 首次死亡判定先复查一次，经过原有崩溃退避后、真正启动替代 Client **之前再核查一次**；如果旧 PID 仍然正常，取消此次恢复，不生成重复 Client，也不累计失败次数。异常日志记录检测原因与取消恢复的情况。
5. 每次成功启动新的 Client 都记录其新 PID 和稳定启动标识，继续监控；若新生进程标识暂时不可读，则在子进程确认仍存活时重试读取，不把未知标识当作死亡。

`_alive()` 和 `run_process_supervisor()` 均位于 `backend/client/watchdog/process_watchdog.py`。这是一条**进程级**监督链：Socket 断开、Server 离线、主线程卡住但 PID 尚存，不会单凭这些现象触发复活。反过来，即使 `os.abort()`、`os._exit()` 等导致 Client 在没有 Python 清理回调的情况下死亡，也可以被独立 Supervisor 检测到（前提是 Supervisor 自身仍活着）。

### 探测频率、崩溃退避与修改方式

| 时间项 | 当前实现 | 含义与调整方式 |
| --- | --- | --- |
| `_POLL_INTERVAL` | **0.5 秒** | Client 正常存活时，Supervisor 两次 PID 探测之间的休眠时间；也用于退避等待期间检查停止标志。源码常量，不是 `set` 配置 |
| `_RETRY_DELAYS` | **3、10、30、60、120、300 秒** | 第 1 至第 6 次及以后的连续失败，分别等待相应时长再尝试启动新 Client；不是 PID 探测间隔 |
| `_STABLE_SECONDS` | **300 秒** | 上一代 Client 若连续存活至少 300 秒，下一次异常死亡重新按第 1 次失败计算退避 |
| `_STOP_TIMEOUT` | **3 秒** | 主动停止时等待 Supervisor 停止确认的最长时间；不是扫描周期 |

更改 PID 扫描周期的方式：编辑 `backend/client/watchdog/process_watchdog.py` 的 `_POLL_INTERVAL = 0.5`，例如更改为 `1.0` 表示约每 1 秒探测一次。然后重新部署修改后的 Client 源码（打包运行时需要重新构建程序），**重新启动 Client 及其独立 Supervisor** 才会载入新常量。这个设置目前没有独立的 runtime_config 配置项，不能通过 `set PROCESS_WATCHDOG_...` 在线修改扫描周期；`set PROCESS_WATCHDOG_ENABLED true/false` 只能启停功能，不能更改常量。

改变 `_POLL_INTERVAL` 影响的是故障被发现的速度与轮询开销，而非重启退避时间。实际检测可能因操作系统调度等稍有延迟；探测到死亡后仍需经过 `_RETRY_DELAYS` 的等待。使用 `watchdog --json` 可以通过 `process_watchdog.poll_interval_seconds` 查看**运行中 Client 所加载代码里的配置值**，它不是某个 PID 的实时测量结果。若已部署不同代码版本，必须以实际运行实例与其日志为准。

### 状态查询与 Web 管理

`watchdog` 和 `watchdog --json` 使用统一的两层结构：`client` 保存主进程身份，三个模块分别位于 `remote_watchdog`、`local_watchdog`、`process_watchdog`。Process 状态字段包括：

- `process_watchdog.enabled`：启用状态。
- `process_watchdog.supervisor_pid`、`process_watchdog.supervisor_alive`：独立 Supervisor 的 PID 和存活状态；不是 Remote/Local 共用 Worker 的 PID。
- `process_watchdog.poll_interval_seconds`：代码指定的进程探测间隔，单位秒。
- `process_watchdog.log_path`：实际进程监督日志路径。

完整字段和 JSON 实例参见 [Watchdog 状态说明](watchdog.md#状态字段的含义)。Web 连接详情的 **info → Watchdog** 仍将 **Process recovery** 独占一行，Remote control / Local recovery 在下方双列排列；独立开关、运行状态、PID、诊断路径及底部 HTTP Control 操作全部保留。三个开关通过既有运行时配置命令分别设置；HTTP Control 按钮仍只属于 Remote HTTP Watchdog。

## 功能边界

- 只覆盖 **Worker 已成功启动之后** 的 Client 死亡；不承诺 Supervisor 自身死亡、系统重启、系统级清理或注销后的自动恢复。更高级持久化应使用系统服务管理器（launchd/systemd/Windows Service），不在此模块中实现。
- 不判断 Client 主线程或 Socket 接收线程是否卡死；这属于连接恢复或 Local Heartbeat Watchdog 的范围。
- 强制进程退出可能导致运行中的 Script/Job 中断；新 Client 是新的进程、`client_id` 与连接会话，不恢复原任务内存状态。
- 仅在支持独立后台进程和 `psutil` 的桌面平台使用（macOS、Linux、Windows）。iOS/Pythonista 不保证支持。
- Supervisor 是可靠性手段而不是防篡改沙箱：具有同等本机权限的代码仍可以终止它、修改配置或关闭监督。

## 恢复后上线通知

Supervisor 检测到 Client 进程死亡，按原有退避策略启动下一代 Client 时，仅向子进程传递一次性 `RCH_CLIENT_RECOVERY_SOURCE=process_watchdog`。Client 首次成功握手后，Server 继续发布原有 `connection_online`，对应即时提示与历史记录显示 `recovered by Process Watchdog`。它不负责故障发生时另发 SSE；没有恢复成功上线时也没有新的上线通知。独立启动、普通网络重连、主动退出、更新与 Remote Relaunch 不应被误标为 Process 恢复。
