# Process Watchdog — Client 进程意外死亡后复活

`process_watchdog` 是与现有 **Local Heartbeat Watchdog** 和 **Remote HTTP Watchdog** 独立的进程监督功能。它仅检测 Client **操作系统进程是否死亡**，不使用 Local 心跳文件，也不把 Socket 断开等同于进程崩溃。即使 Server 暂时不可访问，只要 Client 进程存活，它也不会触发重启。

## 启用与控制

默认 `PROCESS_WATCHDOG_ENABLED = False`，在 `client/config/runtime_config.py` 声明。运行中的 Client 可通过 `set PROCESS_WATCHDOG_ENABLED true` 启用、`set PROCESS_WATCHDOG_ENABLED false` 关闭；设置按项目现有 runtime_config 覆盖文件持久化。建议先在非关键设备验证，再远程开启。运行时切换本开关会刷新现有 Remote/Local 控制 Worker 的启动环境，以便它正确区分主动退出；监控逻辑和检测依据仍然完全独立。

开启后，Client 在建立连接之前启动单独的 `--process-watchdog-worker` 进程。Worker 使用 `psutil` 对 PID 和创建时间进行联合检查，区分 PID 复用及僵尸进程。正常情况下只保留一条监督链：Client 死亡后，原 Worker 按 3、10、30、60、120、最高 300 秒的退避间隔重启 Client；运行至少 300 秒视为恢复稳定，重置连续失败计数。Worker 持续重试，不因达到失败次数而永久放弃。

复活后的 Client 继承内部监督会话标记并复用原 Worker，不再次创建 Worker。单独 `spawn_instance`、`clone` 或 `reset` 创建的新实例**不继承**原监督会话，会独立建立自己的监督链。`reexec` 仍在同一 PID 内执行，监督会话保留。

单独的轮转日志存储于运行时配置目录下的 `process_watchdog.log`（包括 `.1`、`.2` 备份）。Worker 的临时控制目录只用于本次监督会话，不承载业务数据。

## 有意关闭、重启和更新

- `kill_connection`、本机 `KeyboardInterrupt` 以及 Remote HTTP `kill` 在退出前明确停止 Process Watchdog，不会因为主动关闭而自动复活。
- `reset` 与 Remote HTTP `relaunch` 先建立独立新 Client，再停止旧实例的监督链；新实例自己负责保护。
- `reexec` 沿用原 PID 与监督关系；意外失败则由 Supervisor 尝试恢复。
- `update` 下载并启动的新 Client 在 **PID/握手就绪验证完成前不启用** Process Watchdog。旧 Client 确认验收后通过临时 `.accepted` 标记激活新 Client，再等待 `.adopted` 确认。只有验收通过才能交接。`--keep-old` 保留旧监督链；普通更新退出旧 Client 前停止旧监督链。

注意：如果用户在系统层直接 `kill -9` 或强制结束 Client，Supervisor 无法辨别人工操作还是意外死亡，默认视为异常并复活。要永久停止 Client，请先禁用 Process Watchdog，或使用正式生命周期命令。

## 功能边界

- 只覆盖 **Worker 已成功启动之后** 的 Client 死亡；不承诺 Supervisor 自身死亡、系统重启、系统级清理或注销后的自动恢复。更高级持久化应使用系统服务管理器（launchd/systemd/Windows Service），不在此模块中实现。
- 不判断 Client 主线程或 Socket 接收线程是否卡死；这属于连接恢复或 Local Heartbeat Watchdog 的范围。
- 强制进程退出可能导致运行中的 Script/Job 中断；新 Client 是新的进程、`client_id` 与连接会话，不恢复原任务内存状态。
- 仅在支持独立后台进程和 `psutil` 的桌面平台使用（macOS、Linux、Windows）。iOS/Pythonista 不保证支持。
- Supervisor 是可靠性手段而不是防篡改沙箱：具有同等本机权限的代码仍可以终止它、修改配置或关闭监督。
