# Server Cleanup 与 Client `clean`

RCH 有两种作用范围不同的清理机制：**Server Cleanup** 负责 Server 本机的手动及启动自动清理；**Client `clean`** 是对指定 Client 主动发起的维护命令。它们分别在自己的设备上操作，不会互相清理对方的文件。

两种清理都可能永久删除文件或记录，不能将其当作备份、归档或通用磁盘清理工具。本文分别说明执行时机、清理范围、保留边界以及如何检查结果。

## Server Cleanup：Server 本机维护

打开 **Settings → Maintenance → Server Maintenance → Clean…**。外层显示符合条件的文件逻辑大小及关联记录数。清理对话框采用固定高度，标题、标签页、汇总及底部操作区保持稳定，分类明细和策略列表在内部滚动。Clean Now 支持刷新扫描、展开类别、查看文件及目录内容、按类别或候选项勾选；临时目录作为一个完整候选项。通知等纯数据库记录只计条目，不计可释放文件大小。确认后永久删除选中的候选；运行中可停止尚未开始的项目，已处理项目保留执行结果。清理完成后可查看释放空间估算、跳过、未处理、失败数量及报告。

### 清理范围

| 类别 | 清理内容与保留条件 |
| --- | --- |
| Agent Build Temp | 当前 Runtime 下上一实例残留的 `agent_build_tmp/agent_build_*` 构建工作目录 |
| Transient Agent Outputs | 上一实例 Update / Bootstrap 登记的临时产物；本次运行中用于下载的产物、普通用户构建保留 |
| Preview Cache | 上一实例预览缓存，本次运行打开或保存的预览保留 |
| Upload Temporary Files | 上一实例 `web_files/artifacts/upload_tmp/` 残留目录；活动 reservation 保留 |
| Cleanup Logs | 已完成的清理报告 |
| Notifications | 通知记录；按条目明确选择，启动自动清理默认关闭 |
| Server Rotated Logs | `server.log.1` 至 `.5` 中至少一天未更新的轮转备份；当前 `server.log` 保留 |
| Go Loader Logs | `logs/go_loader_YYYYMMDD-HH.log` 中至少一天未更新的非当前小时文件 |
| TCP Transfer Residue | 上一实例 Artifact 对象分片目录中的 `.rch-transfer-*` 中转残留 |
| Bootstrap Temporary Files | 上一实例 `bootstrap_tmp/bootstrap_*.py`、`*.ps1` 残留 |
| Orphan Artifact Files | 上一实例对象存储中路径与 ID 一致、没有任何 Catalog 记录的文件；仅人工确认清理 |

Server Runtime 由单个 Server 实例独占使用。构建和 Bootstrap 临时目录位于 Runtime 内，系统通用临时目录中无法确认归属的旧文件不进入清理计划。当前实例新产生的预览、上传中转、构建及 TCP/Bootstrap 临时数据由所属功能负责正常收尾，异常残留在下一次 Server 启动后可清理。扫描发现 Catalog 中记录对应文件缺失时只报告数量，保留元数据供进一步检查。Shared Files、Saved Files、正常 Agent 输出、账号、密钥、设备身份、正式文档、Activity / Command / Job / Connection / Transfer History 及数据库本体保留。

扫描产生短期服务端计划，执行只接受计划中已选的候选 ID，并重新校验文件身份、路径、修改时间及所属服务的活动保护条件。新增、变化、已消失或受保护的候选会跳过；目录只删除扫描时已列入的文件及仍为空的目录。符号链接、硬链接和特殊文件不进入删除流程。文件大小是逻辑字节数，实际磁盘释放量可能因文件系统而异。

### Auto Cleanup

同一对话框中的 Auto Cleanup 保存启动开关、类别选择和保留天数。默认开启，Server 启动后约 20 秒执行一次。构建工作目录、临时产物、预览、上传暂存、TCP 和 Bootstrap 残留默认启用；清理报告默认保留 7 天。轮转日志、Go Loader 日志及通知记录可手动启用自动保留策略，默认关闭。孤立 Artifact 文件只能人工选择。手动清理、启动清理和数据库优化共用互斥执行机制；Restart / Shutdown 获准后不再接受新的清理或优化任务，尚未开始的启动清理也不再运行。设置在下次启动时生效。

### 完成通知与清理报告

报告路径为 `<Server Runtime>/cleanup_logs/server_cleanup_<运行编号>.log`，独立于 Server 主日志。清理结束发送 **Server Cleanup Completed** 通知，报告可通过 **View Cleanup Log** 查看。报告包含各类别、实际处理的文件与记录、估算释放大小、跳过、未处理及错误详情。通知展示受 Notification Preferences 控制。

### Optimize Database

**Settings → Maintenance → Optimize Database** 是与 Cleanup、Restart、Shutdown 平级的独立入口。数据库记录删除后，SQLite 通常保留空闲页供后续写入复用。该入口显示数据库文件、WAL、可复用页和磁盘剩余大小，并可手动执行 SQLite `VACUUM` 和 WAL checkpoint 来回收磁盘空间。优化保留已有记录，执行前检查剩余空间和数据库完整性；数据库忙时返回错误或报告 checkpoint 尚未完成。建议在 Server 空闲时执行，SQLite 写入可能短时等待。自动 Cleanup 不运行数据库优化。

## Client `clean`：手动清理指定设备

### 从哪里执行

在 RCH Web 中选择要维护的 **Client**，通过该 Client 的命令入口输入：

```text
clean
```

在 RCH Terminal 中选中目标 Client 后执行 `clean`；文件扫描与清理发生在**该 Client 所在设备**。需要 Client 在线且允许执行对应命令。

默认流程为：扫描可处理的残留 → 显示 **Client Cleanup — Delete Plan** 预览 → 选择类别 → 确认后删除。扫描与实际清理分开汇报；预览按清理目录汇总文件数、目录数和估算大小，不逐个列出文件。**有候选的类别默认全部选中**，不需要清理的类别应主动取消勾选。拒绝或取消确认不会执行删除。

如果需要跳过交互式确认，可使用：

```text
clean --no-confirm
```

此模式沿用相同的扫描与安全检查，但**不会弹出预览、会直接执行可自动处理的类别**。它会专门排除 `client_logs`，不自动删除其他 Client 实例的日志；这不表示其余类别只是试运行。命令不支持任意类别名称作为参数，也没有单独的 `--dry-run` 参数。

### 清理类别

Client 的常见临时数据位于目标设备系统临时目录中的 Client temp root 下，按用途分目录。Windows 使用 `rch_client_temp/`；POSIX 使用 `rch_client_temp_u<effective_uid>/`，并以 `0700` 保护根目录，使 root/elevated Client 与普通用户 Client 各自管理自己的临时空间。部分配置中转和 Bundle 数据因功能原因保留在各自原位置。普通临时类别只扫描当前 Client 所属的 temp root；配置中转和 Bundle 类别只扫描对应功能实际使用的目录与文件名。不会扫描当前管理范围之外的系统临时文件。清理项目包括：

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
| `bundle_old_releases` | Bundle Releases 中除当前运行版本及解压中转之外的目录 | 其他目录即使仍有回退用途，也可能被删除 |
| `bundle_archive_residue` | 下载目录中的 Bundle 压缩包残留 | 不应在更新/下载进行时执行清理 |
| `bundle_extracting_residue`、`bundle_probe_files` | 更新解压中转、就绪探测及启动日志等残留 | 更新尚未完成时应避免清理 |

运行中的 Client 主日志目录不会作为 `client_logs` 候选；**Remote、Local、Process Recovery Watchdog 正在使用的固定日志也不属于可整目录删除的清理类别**。当前 Bundle Release 受保护，但其他 Release 目录可能全部进入候选，不能把“旧 Release”简单理解成“按时间过期的版本”。External Tools 的安装包、实例日志和运行数据不属于本命令清理范围。

### 预览、跳过和执行安全

- **预览与执行分开。** 提交确认后，仅删除预览中批准的类别及扫描到的目标路径。
- 执行前会再次检查目标文件或目录的状态；在预览后已变化、消失或重新变成活动状态的目标会跳过。被保护、不可访问或无法确认安全的项目会保留，不会为了完成清理而强行删除。
- 临时目录使用不同的保留条件：例如归档中转需闲置约 **5 分钟**，非 macOS 剪贴板接收暂存约 **1 小时**；旧日志通常至少 **1 分钟**无更新才成为人工预览候选。**“久未写入”不等于“进程已停止”**。
- `clean --no-confirm` 仍会做检查，但不经人工核对就永久删除其他已符合条件的候选。首次使用、刚完成更新或需要保留排障证据时，优先使用普通 `clean`。
- 扫描阶段按目录汇报候选文件数、目录数和估算大小；进入预览前会提示正在等待用户确认。批准后，清理阶段再按目录汇报实际删除结果，不逐个输出文件路径。
- 扫描失败时输出路径和原因，跳过未能完整扫描的目标。其余扫描成功的目标可以进入预览并继续清理，包括同一类别里的其他目录。
- 最终 `completed` 汇总删除数量、释放空间和失败情况。有成功删除同时存在扫描或删除错误时为 `partial`。存在错误且没有删除任何目标时为 `error`。
- 无候选时显示本命令管理范围内没有可清理项目。

### 哪些东西不会被当作普通残留清掉？

`clean` 管理目标 Client 的残留和临时数据。**Server 数据库、Server Agent Output、设备历史和用户指定的文件目录保持不变**；macOS Finder 使用的 Clipboard staging、正在运行的 Watchdog 文件及当前 Client Release 按保护规则保留。

不过，**被清理的旧 Bundle Release、临时 ZIP、旧日志或暂存文件可能无法恢复**。需要用于回滚、下载、粘贴或故障追踪的文件，应在确认前排除相应类别或先做好备份。正在执行 Bundle 更新、远程 Job、文件传输或其他依赖临时文件的任务时，建议暂不运行清理。

Client 文件日志的保存位置见 [Server / Client Logging](logging.md)；Bundle 更新与 Release 管理见 [Client Update](client_update.md)；Watchdog 的运行边界见 [Watchdog](watchdog.md) 与 [Process Recovery Watchdog](process_recovery_watchdog.md)。

## 两种清理如何选择？

| 需求 | 应使用 |
| --- | --- |
| Server 重启后清理预览缓存、上传中转、构建临时数据 | **Server Cleanup**：Settings → Maintenance，手动或启动自动执行 |
| 清理某台 Client 的临时文件、残留日志或不再需要的 Bundle Releases | **Client `clean`**：在目标 Client 命令入口运行，并核对预览 |
| 查看 Server 上一轮自动清理做了什么 | Server Runtime 下的 `cleanup_logs/`，或完成通知中的 **View Cleanup Log** |
| 清理 Server 的正式历史、账号、正式文件或 Client 上的用户数据 | **以上两种机制均不适用**；不要把它们当作通用删除入口 |
