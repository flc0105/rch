# Server / Client Logging

RCH 的 Server 与 Client 都保留原有的控制台日志输出，同时尝试保存便于诊断的本地日志文件。两端的日志**写在各自运行的设备上**，保存位置、失败处理和生命周期不同；Server 的 Runtime 日志不等于 Client 的远程日志，也不等于浏览器中的命令历史。

本文说明主进程日志的用途、实际保存位置、轮转及日常查看方式。远程文件查看操作见 [Log Viewer](log_viewer.md)；独立监督进程的行为见 [Watchdog](watchdog.md) 与 [Process Recovery Watchdog](process_recovery_watchdog.md)。

## Server 主日志

通过 `run_web.py` 启动的 Web Server 会保留标准输出/标准错误上的原有日志，并在 **Server Runtime 目录**维护一份 `server.log`。默认位置是 `backend/runtime/server.log`，不随启动时所在的工作目录改变。

| 项目 | 行为 |
| --- | --- |
| 日志位置 | `<Server Runtime>/server.log` |
| 轮转方式 | 单个文件约 10 MiB 时按大小轮转 |
| 保留数量 | 当前文件 + 最多 5 个备份（`.1` ～ `.5`） |
| 记录范围 | 项目 Python Logging、Uvicorn 服务和 HTTP Access Log，以及正常传递到统一日志系统的其他记录 |
| 启动失败处理 | 无法创建或打开 Server 日志文件时，启动会报错，避免静默丢失预期的持久日志 |

日志备份按轮转顺序编号。普通轮转空间上限约为 **60 MiB**，但这不包括 `nohup` 等启动工具另行保存的输出文件，也不包括 Server 的其他数据和日志目录。

Runtime 路径可以在启动前通过 `RCH_SERVER_RUNTIME_DIR` 指定；绝对路径直接使用，相对路径基于 `backend/` 解析。该目录还保存数据库、凭据与其他运行数据，调整路径前应同时考虑这些文件，详见 [Server Runtime](server_runtime.md)。

### 启动与查看

从 `backend/` 目录运行：

```bash
python3 run_web.py
```

后台启动且不额外生成 `nohup.out`（不保留独立的原始 stdout/stderr）：

```bash
nohup python3 run_web.py > /dev/null 2>&1 < /dev/null &
```

这两种启动方式都会由 Server 自行写入 `server.log`。使用 `launchctl`、systemd 或自定义重定向时，日志文件同样独立于终端输出目标。

在 Server 机器上持续查看：

```bash
tail -n 100 -F runtime/server.log
```

轮转会替换当前文件，使用 `tail -F` 可以持续按文件名跟踪；若指定了其他 Runtime 路径，应改为实际日志路径。

**记录边界：** 文件保存的是经过 Python Logging 的记录，不会自动复制每个原始 `print()`、子进程直接写出的内容，或文件日志初始化之前发生的异常。将 stdout/stderr 丢弃后，这些未接入日志系统的输出也会丢失。日志轮转由单个 Server 进程负责；不应让多个独立 Server 实例同时向同一路径轮转写入。

## Client 主日志

Client 正常启动时，会为**每个进程实例**建立一份可轮转的主日志；断线重连不会另外创建一份，同一设备上启动另一个 Client 进程则使用独立目录。文件位于**运行 Client 的那台设备**，不是 Server 的 `runtime/`。

以 `T` 表示 Client 设备上的系统临时目录（由操作系统和运行环境决定），`R` 表示 Client temp root。Windows 的 `R` 为 `T/rch_client_temp`；POSIX 的 `R` 为 `T/rch_client_temp_u<effective_uid>`：

```text
R/client_logs/client_<实例目录>/client.log
R/client_logs/client_<实例目录>/client.log.1
...
R/client_logs/client_<实例目录>/client.log.5
```

POSIX 的 UID 后缀和 `0700` 根目录用于隔离 root/elevated 与普通用户实例，避免一个账户创建的私有目录阻止另一个账户启动 Client。

| 项目 | 行为 |
| --- | --- |
| 主日志 | 每个 Client 进程单独一个 `client.log` |
| 轮转方式 | 单文件约 10 MiB，保留最多 5 个备份 |
| 记录范围 | 能传递到 Python 主日志系统的 Client 日志记录，包含每次连接发送的完整 `info` 握手 JSON |
| 文件日志不可用 | Client **继续启动与连接**，只向 stdout 简短报告；路径不会作为有效日志位置上报 |
| 保存期限 | 系统临时目录可能被操作系统清理；不应当作永久审计记录 |

Client 在发送 `info` 握手时通过现有 `console_logger` 记录完整 JSON；该记录在控制台出现一次，并写入正常安装的主日志文件。断线重连后重新握手时会再次记录，内容包括 Client 身份、系统信息、Command / Feature / Variable Manifest 和路径快照。

Client 不承诺自动捕获所有 `print()`、独立子进程 stdout/stderr，或日志初始化前的异常。普通 Client 主日志也**不包括三个 Watchdog 的专用日志**，这些监督模块有独立的输出文件。

### 在 Web 中找到正在运行的 Client 日志

1. 在设备列表中选择一个在线 Client。
2. 打开 **Connection Info → Basic Info**，找到 **Client Log**；这里显示 Client 在建立连接时上报的实际绝对路径。
3. 从 **Toolbox → Log Viewer** 打开查看器。若没有指定其他日志，且当前选中的是在线 Client，会默认读取这份 Client 主日志。
4. 若 **Client Log** 显示 `-` 或 Log Viewer 没有自动选择文件，确认 Client 在线、文件日志可用；仍可用 **Browse** 手动选取目标 Client 上其他可访问的日志文件。

由于不同系统的临时目录不相同，**以 Basic Info 提供的路径为准**，不要在 Server 机器上套用本机 `/tmp` 路径去寻找 Client 的文件。连接信息是握手时的快照；Client 重启后应重新查看新连接的路径。详情见 [Client Handshake](client_handshake.md)。

### Watchdog 与其他单独日志

三个 Watchdog 的诊断日志统一位于目标 Client 的：

```text
R/watchdog_logs/client_remote_control_watchdog.log
R/watchdog_logs/client_local_heartbeat_watchdog.log
R/watchdog_logs/process_recovery_watchdog.log
```

Remote Control Watchdog / Local Heartbeat Watchdog 使用独立文件日志；Process Recovery Watchdog 的日志按约 **2 MiB** 轮转并保留 **2 个备份**。这些日志不因主日志轮转而被合并或覆盖。Web 连接详情中的 **Watchdog** 区域提供各自路径及相应的查看入口。

External Tools 的安装及运行日志也独立保存在目标 Client 的工具数据目录；具体位置可受安装和运行配置影响，参见 [External Tools](external_tools.md)。

### 保留、清理与安全

- Server `server.log` 的容量受轮转限制；系统 Runtime 目录仍应纳入正常的磁盘空间监控和备份策略。
- Client 的 `client_logs` 在临时目录中，**不会因为断线而自动删除**。`clean` 的交互式 Preview 可以列出符合条件的其他实例日志，但不能仅凭一段时间无新日志就认定其进程已经停止；自动确认的清理不会直接删除这些实例日志。详见 [Client Update / Cleanup](client_update.md)。
- 不要在 Client 正在运行或 Log Viewer 正在查看时直接清空其当前日志文件或删除正在写入的目录。需要留存诊断证据时，应先复制到受控位置，再考虑清理。
- 日志可能记录请求路径、命令、异常信息或本地文件路径。应限制日志文件和备份的读取权限；分享前检查并移除敏感内容。

## 出现问题时先看哪里

| 现象 | 优先检查 |
| --- | --- |
| Server 已启动，但找不到 `server.log` | 确认实际 `RCH_SERVER_RUNTIME_DIR`、启动用户对 Runtime 目录的写入权限，以及是否通过 `run_web.py` 启动 |
| `nohup` 后没有任何日志 | 查看 `runtime/server.log`；如需追踪初始化前的原始错误，不应同时丢弃 stdout/stderr |
| Client 有终端输出但没有 **Client Log** 路径 | 检查 Client 启动时是否提示文件日志不可用、系统临时目录权限，以及连接信息是否已刷新 |
| Log Viewer 不显示新内容 | 核对目标 Client 在线状态、正在选择的日志文件、Streaming 状态及文件是否仍存在；见 [Log Viewer](log_viewer.md) |
| 查不到 Watchdog 的日志 | 到连接详情的 Watchdog 区域使用其专用路径；不要只查看 Client 主日志 |
