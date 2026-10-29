# Server Cleanup 与 Client `clean`

RCH 有两种作用范围不同的清理机制：**Server Cleanup** 负责 Server 启动时的运行残留清理；**Client `clean`** 是对指定 Client 主动发起的维护命令。它们分别在自己的设备上操作，不会互相清理对方的文件。

两种清理都可能永久删除文件或记录，不能将其当作备份、归档或通用磁盘清理工具。本文分别说明执行时机、清理范围、保留边界以及如何检查结果。

## Server Cleanup：启动时自动清理

### 执行时机与范围

使用 `run_web.py` 启动 Server 时，系统会在启动后安排一次自动清理，默认延迟约 **20 秒**执行。**清理对象以 Server 初始化时捕获的候选记录和路径为准**，而非在执行时重新全盘扫描；因此，服务启动后新产生的数据不应被视为本次清理的目标。每次正常启动会重新形成本次候选范围。

默认启用的清理项目如下：

| 项目 | 清理内容 | 边界 |
| --- | --- | --- |
| `notifications` | 启动时已经保存的 Notification Center 通知记录 | 按启动快照中的通知 ID 删除；启动后新通知不属于该快照 |
| `agent_build_temp` | Server 主机系统临时目录中属于 Agent 构建的临时工作目录 | 仅处理符合 Agent 构建临时目录范围的候选项，不等于删除所有 Agent |
| `agent_transient_outputs` | 由 Update、Bootstrap 生成的临时 Agent 输出及相关元数据 | **不针对普通的用户构建产物**；只清理已登记、来源符合条件的输出 |
| `preview_cache` | Server 侧的文件预览缓存 | 不等于清空 Artifact 正式文件或 Shared Files |
| `upload_tmp` | Server 侧上传暂存目录中的启动前残留 | 不等于清空已保存的正式上传文件 |
| `cleanup_logs` | 之前清理产生的报告文件 | 只处理先前的清理报告；本次新生成的报告会保留 |

Server Cleanup 处理上表的 Server 启动清理候选项，其中包括启动前的通知记录。**Quick History、Activity Center、Pinned Commands、设备身份、管理员凭据及其余 `rch.db` 数据保留。**Client 设备上的临时文件由后面的 `clean` 命令管理。需要留存通知时，应在 Server 重启前导出。

清理项目和启动延迟由 Server 的清理配置决定；更改配置后在下次 Server 启动时生效。

### 完成通知与清理报告

每次执行会汇总清理文件数、目录数、通知等记录数、估算释放空间和错误数，并尝试在以下位置写入独立报告：

```text
<Server Runtime>/cleanup_logs/server_cleanup_<运行编号>.log
```

Server Runtime 默认位于 `backend/runtime/`，也可能由 `RCH_SERVER_RUNTIME_DIR` 指定。报告包含各清理项目的目标路径、已移除条目和错误详情；其独立于 Server 主日志 `server.log`，并非日志轮转备份。

执行完成后，系统会发送 **Server Cleanup Completed** 通知；有错误时会标记为警告。通知实际是否展示还受 Notification Preferences 影响。报告成功写入时，通知可提供 **View Cleanup Log** 入口。报告无法写入时，清理仍可能已执行，应到 Server 主日志检查失败原因，而不能仅凭没有报告就认定未清理。

在 Server 主机上也可以直接查看报告目录：

```bash
ls -lt backend/runtime/cleanup_logs/
```

若 Runtime 位置经过自定义，应使用实际目录。关于 Runtime 位置、日志和通知系统，分别参见 [Server Runtime](server_runtime.md)、[Server / Client Logging](logging.md) 与 [Notifications](sse_notifications.md)。

### 使用注意

- **清理会永久移除目标**。预览缓存可重新生成，但已清理的通知、临时构建文件和上传暂存内容不承诺恢复。
- Server Cleanup **没有交互式逐项确认**。需要保留启动前通知、暂存文件或诊断报告时，应在启动前另行复制；不要指望启动后再从清理目录找回。
- 候选范围来自启动时快照，但不意味着所有候选在清理执行前都不会发生变化。涉及正在上传或构建的任务时，应避免与 Server 重启及自动清理交叠。
- 完成通知显示本次清理的项目统计；Server 磁盘占用应另通过文件系统检查。

## Client `clean`：手动清理指定设备

### 从哪里执行

在 RCH Web 中选择要维护的 **Client**，通过该 Client 的命令入口输入：

```text
clean
```

在 RCH Terminal 中选中目标 Client 后执行 `clean`；文件扫描与清理发生在**该 Client 所在设备**。需要 Client 在线且允许执行对应命令。

默认流程为：扫描可处理的残留 → 显示 **Client Cleanup — Delete Plan** 预览 → 选择类别 → 确认后删除。预览列出类别、目标数、估算大小，并可查看候选路径；**有候选的类别默认全部选中**，不需要清理的类别应主动取消勾选。取消或不选择任何类别，不会执行删除。

如果需要跳过交互式确认，可使用：

```text
clean --no-confirm
```

此模式沿用相同的扫描与安全检查，但**不会弹出预览、会直接执行可自动处理的类别**。它会专门排除 `client_logs`，不自动删除其他 Client 实例的日志；这不表示其余类别只是试运行。命令不支持任意类别名称作为参数，也没有单独的 `--dry-run` 参数。

### 清理类别

Client 的常见临时数据位于目标设备系统临时目录中的 Client temp root 下，按用途分目录。Windows 使用 `rch_client_temp/`；POSIX 使用 `rch_client_temp_u<effective_uid>/`，并以 `0700` 保护根目录，使 root/elevated Client 与普通用户 Client 各自管理自己的临时空间。部分配置中转和 Bundle 数据因功能原因保留在各自原位置。当前命令只扫描当前 Client 所属 temp root，并覆盖以下项目：

| 类别 | 清理什么 | 应特别注意 |
| --- | --- | --- |
| `remote_job_temp` | 远程 Job 的临时脚本与运行中转 | 不应清理正在使用的 Job 文件 |
| `preview_temp` | 图片等预览中转 | 不是正式源文件 |
| `clipboard_temp` | 剪贴板上传中转 | 不等于清空系统剪贴板 |
| `clipboard_helper_temp` | 平台剪贴板辅助脚本残留 | 活动临时文件受保护 |
| `runtime_config_temp` | Runtime Config 保存时遗留的临时中转文件 | **不是 `runtime_config.json` 正式配置** |
| `media_temp` | 截图、摄像头等媒体中转 | 不等于删除用户指定保存的媒体文件 |
| `archive_temp` | 已闲置一段时间的压缩包临时工作目录 | 生成的 ZIP 可能仍有使用价值，预览时须核对 |
| `client_logs` | 非当前 Client 实例、满足候选条件的日志目录 | **仅交互式预览中可选择**；其他空闲实例不一定已退出 |
| `clipboard_staging` | 非 macOS 系统上满足保留时间条件的剪贴板接收暂存 | 仍可能被粘贴或其他流程引用；macOS GUI 用户的暂存位置不在此范围 |
| `watchdog_heartbeats` | 已失效的 Local Heartbeat Watchdog 心跳及相关残留 | 正在使用的心跳不应被清理 |
| `watchdog_sessions` | 已结束的 Process Recovery Watchdog 会话控制目录 | 不能清理仍在运行的监督会话 |
| `bundle_old_releases` | Bundle Releases 中除已识别为当前运行版本以外的目录 | 其他目录即使仍有回退用途，也可能被删除 |
| `bundle_archive_residue` | 下载目录中的 Bundle 压缩包残留 | 不应在更新/下载进行时执行清理 |
| `bundle_extracting_residue`、`bundle_probe_files` | 更新解压中转、就绪探测及启动日志等残留 | 更新尚未完成时应避免清理 |

运行中的 Client 主日志目录不会作为 `client_logs` 候选；**Remote、Local、Process Recovery Watchdog 正在使用的固定日志也不属于可整目录删除的清理类别**。当前 Bundle Release 受保护，但其他 Release 目录可能全部进入候选，不能把“旧 Release”简单理解成“按时间过期的版本”。External Tools 的安装包、实例日志和运行数据不属于本命令清理范围。

### 预览、跳过和执行安全

- **预览与执行分开。** 提交确认后，仅删除预览中批准的类别及扫描到的目标路径。
- 执行前会再次检查目标文件或目录的状态；在预览后已变化、消失或重新变成活动状态的目标会跳过。被保护、不可访问或无法确认安全的项目会保留并显示原因。
- 临时目录使用不同的保留条件：例如归档中转需闲置约 **5 分钟**，非 macOS 剪贴板接收暂存约 **1 小时**；旧日志通常至少 **1 分钟**无更新才成为人工预览候选。**“久未写入”不等于“进程已停止”**。
- `clean --no-confirm` 仍会做检查，但不经人工核对就永久删除其他已符合条件的候选。首次使用、刚完成更新或需要保留排障证据时，优先使用普通 `clean`。
- 结果逐类别显示扫描路径、删除数量、估算释放空间、跳过路径和错误信息；无候选时显示本命令管理范围内没有可清理项目。

### 哪些东西不会被当作普通残留清掉？

`clean` 管理目标 Client 的残留和临时数据。**Server 数据库、Server Agent Output、设备历史和用户指定的文件目录保持不变**；macOS Finder 使用的 Clipboard staging、正在运行的 Watchdog 文件及当前 Client Release 按保护规则保留。

不过，**被清理的旧 Bundle Release、临时 ZIP、旧日志或暂存文件可能无法恢复**。需要用于回滚、下载、粘贴或故障追踪的文件，应在确认前排除相应类别或先做好备份。正在执行 Bundle 更新、远程 Job、文件传输或其他依赖临时文件的任务时，建议暂不运行清理。

Client 文件日志的保存位置见 [Server / Client Logging](logging.md)；Bundle 更新与 Release 管理见 [Client Update](client_update.md)；Watchdog 的运行边界见 [Watchdog](watchdog.md) 与 [Process Recovery Watchdog](process_recovery_watchdog.md)。

## 两种清理如何选择？

| 需求 | 应使用 |
| --- | --- |
| Server 重启后清理旧通知、预览缓存、上传中转、构建临时数据 | **Server Cleanup**：启动时自动执行，不使用 Client `clean` |
| 清理某台 Client 的临时文件、残留日志或不再需要的 Bundle Releases | **Client `clean`**：在目标 Client 命令入口运行，并核对预览 |
| 查看 Server 上一轮自动清理做了什么 | Server Runtime 下的 `cleanup_logs/`，或完成通知中的 **View Cleanup Log** |
| 清理 Server 的正式历史、账号、正式文件或 Client 上的用户数据 | **以上两种机制均不适用**；不要把它们当作通用删除入口 |
