# Client Builds and Updates

RCH 使用两种不同的身份描述 Client：`build_version` 标识一次可分发的构建产物，`client_revision` 标识参与 Client 运行的源码内容。Server 可以直接比较在线 Client 与当前源码的 Revision，决定是否提示更新；真正执行更新时，才构建并分发新的 Python Source Bundle。**发现源码差异、生成安装包和替换运行中的 Client，是三个独立阶段。**

这条工作流涉及 Server Agent Builder、Client 握手、连接状态服务、Web Terminal 和 Client 自更新命令。下面按源码从构建到运行、再到新旧 Client 交接的顺序说明。首次部署所用的 One-liners、Python / PowerShell Bootstrap 和 Go Loader 另见 [Client Bootstrap 与首次部署](bootstrap.md)。

## 构建产物与源码身份

Server 的 Agent Builder 为每次构建生成独立的 `build_id`，形式为本地时间戳 `YYYYMMDD_HHMMSS` 加 8 位十六进制随机后缀。它再结合构建类型产生 `build_version`，并记录在产物元数据中。**即使源码相同，每次构建也产生独立的 Build Version。** Client 是否需要更新由源码 Revision 判断。

Python Source Bundle 的下载文件名为 `rchclient_python_YYYYMMDD_HHMMSS_XXXXXXXX.zip`；对应 `build_version` 为 `python_YYYYMMDD_HHMMSS_XXXXXXXX`。构建版本用于 Release 目录和共享 Bundle 的定位。多个独立 Client 进程可以运行同一构建版本；连接实例使用各自的 Client ID。

`client_revision` 则由 `build_client_revision_manifest()` 计算。它遍历构成 Python Client Bundle 的运行代码根：`client/`、`core/`、`tunnel/` 和 `rchclient.py`，按确定顺序把相对路径、分隔符与文件内容纳入 SHA-256，取前 **16 个十六进制字符**作为整体 Revision。按需提供文件级差异数据：

| 字段 | 表示内容 | 用途 |
| --- | --- | --- |
| `client_revision` | 整个 Client 源码集合的内容指纹 | 判断当前 Client 与 Server 源码是否一致 |
| 文件级 Revision 明细（按需查询） | 相对文件路径对应的文件内容指纹 | 精确展示新增、删除和修改的源码文件 |
| `build_version` | 某次构建产物身份，源码开发运行时通常为 `dev` | 定位构建、Release 和客户端的交付来源 |

Revision 对指定的 Client 源码文件计算指纹，覆盖范围见上文；计算时排除 `client/config`、`__pycache__`、虚拟环境、构建缓存，以及 `.pyc` 等非源码内容。因此，仅修改 Client 的 Server 地址、Profile 或其配置模块，不一定改变 Revision；反过来，增加、删除或修改被纳入范围的运行代码文件会改变指纹。文件差异比较使用路径和文件内容的实际指纹，并不依赖 Git 工作区或提交记录。

### 构建时注入与源码启动

生成 Python Bundle 时，Server 将目标 Socket 地址、Web 地址及端口、连接模式、Bind 监听接口和端口、`build_version`、Revision 和文件指纹写入 `client/config/profiles/agent.json`，保留源码配置解析器以支持参数覆盖。计算 Revision 的依据是 **Server 原始 Client 源码**，不是把构建后注入的不同连接参数再重新算作代码变化。Bundle 随后压缩并交付，Client 在握手时读取这些值。

在源码/IDE 环境中直接运行 Client，配置 Profile 通常给出 `build_version=dev`，没有预先注入的 `CLIENT_SOURCE_REVISION`。这种情况下 Client 首次构造握手信息时在本地计算源码指纹，并在当前进程内缓存，同时保留轻量文件状态快照以支持运行时源码改动的差异显示。文件内容哈希明细在打开差异时才计算。**编辑本地源码后，已经运行的进程不会自动重新计算指纹或热加载代码**；应重新启动对应源码进程以重新生成握手信息。

Bind 模式的 `update` 在准备好新 Bundle 后先将交接提示发送给 Server，随后结束旧 Client 与当前会话，由一次性交接进程启动新版并验证监听成功。操作者在 Server 手动 Connect 到新版，不需要先单独执行 Disconnect。`spawn_instance`、`spawn_elevated_instance` 和 `relaunch_instance` 的同端口启动限制仍按现有规则执行，详见 [Connection Lifecycle](connection_lifecycle.md)。

## Server 如何生成和保存可部署 Client

Server 的 Agent Builder 是统一构建入口。Web Agent Builder、Bootstrap / Go Loader 的部署流程以及已连接 Python Client 的 `update`，都通过构建服务生成产物；本篇涉及的运行中更新**固定请求 `builder: "python"`**，与用户此前在构建界面选择过哪一种输出无关。

一次 Bundle 构建可以按以下请求发起，地址和端口需替换成实际部署环境：

```http
POST /api/agent/build
Content-Type: application/json
```

```json
{
  "builder": "python",
  "target_os": "",
  "server_host": "192.0.2.10",
  "server_port": 9999,
  "server_web_scheme": "http",
  "server_web_host": "192.0.2.10",
  "web_port": 8085,
  "source": "update"
}
```

Reverse Update 的构建请求携带当前 Client 的传输类型和 TLS 证书指纹，由 Server 选择并验证匹配的 Listener；Bind Update 则携带当前 `connection_mode`、`bind_host` 和 `bind_port`，构建保持相同监听配置的 Source Bundle。两种模式都复用 Server Agent Builder，不增加 Server 主动拨号逻辑。
Server 在临时工作目录复制 Bundle 所需源码，注入 Client 配置后打包，再把构建结果复制到 `SERVER_RUNTIME_DIR/agent_output/`（默认 `backend/runtime/agent_output/`）。构建元数据保存在 Server 的 `runtime/rch.db` 的 `agent_outputs` 表中，包括构建时间、Build Version、Builder、Listener ID、构建时名称快照、系统和架构、连接参数及请求来源等信息。文件大小根据磁盘实体计算。构建成功会发布 `agent_build_lifecycle` 事件（`completed`），失败则发布 `error`。

`POST /api/agent/build` 的 Bundle 响应提供 `builder`、`file_name`、`build_version`、`download_url` 以及服务端对实际 ZIP 计算的 `sha256`。Client 按构建元数据中的 Builder 类型确认下载的是 Python Source Bundle，文件名只作安全路径校验；下载内容仍需通过 SHA-256 与安全解压校验。产物下载通过 **Web/API 端口**上的 `GET /api/agent/download/{filename}` 完成，不经过文件传输专线的 8086。构建产物可以通过 `/api/agent/outputs` 查看，并通过相应删除接口移除；删除某个 Server 构建产物，不会卸载已安装在远程设备上的 Release。

这里的产物元数据与 Client 运行时的源码指纹不是同一份数据：构建记录用 Build Version 和文件名定位下载物，Revision 会被注入 Python Bundle 并随 Client 握手报告。即使 Server 不主动构建新产物，也能用当前磁盘的源码 Revision 判断已连接 Client 是否落后。

## 在线连接怎样判断是否需要更新

Python Client 建立 TCP 连接后，在 `info` 握手中发送 `build_version` 和 `client_revision`。Server 使用整体 Revision 判断是否需要更新；查看差异时再向当前 Client 查询文件级摘要。源码运行态在此时计算文件明细；已构建 Bundle 可以复用构建期间保存的明细。

Server 对**在线连接**把握手 Revision 与本机当前源码 Revision 比较：两者都存在且一致时为 `current`，两者都存在但不同为 `outdated`，任何一方缺失时为 `unknown`。状态由源码指纹比较确定。即使新的构建产物名称不同，只要源码指纹相同，仍可以是 `current`。

设备列表请求会为当前在线会话附带 `client_revision_state`。连接详情需要精确差异时，可以查询：

```http
GET /api/connections/{client_id}/revision-status
```

该接口**每次查询时重新扫描 Server 当前磁盘中的 Client 源码**，不依赖仅在 Server 启动时计算的一份缓存；无需先生成 Bundle，也无需为了检测源码变化重启 Server。示例响应的业务数据形状如下：

```json
{
  "client_id": "目标连接ID",
  "state": "outdated",
  "current_revision": "客户端报告的Revision",
  "server_revision": "当前服务端Revision",
  "changed_files_available": true,
  "changed_files": [
    {"path": "client/example.py", "change": "modified"}
  ]
}
```

上面的路径与 Revision 都是字段示意，不代表仓库中存在该文件。`changed_files` 通过查询时取得的 Client 文件指纹与 Server 当前集合比较；对于源码/IDE 启动的 Client，还结合启动时采集的文件状态识别运行后源码编辑，`change` 区分 `added`、`removed`、`modified`。如果 Client 无法提供文件明细，仍可能根据整体 Revision 判断 `outdated`，但 `changed_files_available` 为 `false`，详情无法列出逐文件差异。

连接状态也是判断的前提：设备不处于 Online 时，列表不继续展示在线更新判定；直接查询上述接口也会按离线分支返回（包含 `stale` 的情况），而不是用最近设备缓存中的旧信息推测最新源码状况。连接健康状态另见 [Connection Lifecycle](connection_lifecycle.md)。

Web 会在设备列表对 `outdated` 的在线设备显示更新标记，并在选中设备时按需请求详细差异。Terminal 的提示会结合 `build_version` 区分操作：已安装的构建版可以建议输入 `update` 并查看 Details；`dev` 环境建议从 IDE / 源码重启。**更新提示不会自动下载、安装或执行远程命令**，需要操作者明确发起。

## 正在运行的 Client 怎样完成交接

远程 `update` 是 Python Client 的普通命令。它从 Server Agent Builder 取得 Python Source Bundle，先校验构建 API 返回的 SHA-256，再安全解压到独立临时目录并发布到共享 `releases/<build_version>/`。已有完整的同名 Release 可以直接复用，残缺目录会拒绝覆盖。下载暂存 ZIP 在发布结束后移除。

### 普通桌面进程

- **Reverse（macOS、Linux、Windows）：** 旧 Client 保持在线；启动新版 Client；新版收到 Server 分发的 Session Token 后经本机认证通道报告就绪，核对新 PID、源码 Revision 并检查短暂存活时间；成功后旧 Client 才退出。新进程失败时旧进程继续运行。`update --observe` 保留旧实例，并将新进程的标准输出和错误写入独立日志；Terminal 在本次命令的常规结果动作区提供 **View Log** 与 **Kill Instance**，供用户确认新 Client 状态后结束旧实例。新 Client 注册失败时旧实例仍在线，可以查看启动日志。
- **Bind（macOS、Linux、Windows）：** 旧 Client 完成安装后启动一次性本机交接进程；先发送完整的准备结果，再在命令执行结束后上报会话结束并退出。交接进程等旧进程结束、端口释放后启动新版；新版 `listen()` 成功后报告就绪并核验 PID、Revision 和短暂存活时间。旧会话已经随旧进程退出，用户在 Server 手动 Connect。候选启动失败时，交接进程保留启动输出并尝试恢复旧版；只有旧版重新通过监听就绪验收，才报告恢复成功。Bind 无法同时保留新旧监听实例，因为新旧进程不能同时监听同一端口。 在 macOS/Linux 等 POSIX 系统中，Bind Listener 允许重用处于 TCP `TIME_WAIT` 的旧本地地址，但仍不允许多个活动的 Bind Listener 同时监听同一地址和端口；Windows 继续使用独占监听语义。

就绪消息使用仅在当前 Update 存在的认证回环通道；Bind 不通过测试连接占用原监听端口。普通进程直接启动构建目录中的 `rchclient.py`，无需永久实例 ID 或固定 Launcher。

### macOS launchd

当前 Launch Context 确认 Client 属于真实运行中的 LaunchAgent / LaunchDaemon 后，Update 通过该 job 本身执行一次性交接。首次接管时将原 plist 的启动命令改成位于共享 Bundle 根目录的固定 Launcher，同时保留其他 job 配置；后续更新只修改**该 job 专属的版本指向**，不再重写 plist。由 launchd 启动候选，Reverse 以 Session Token 验收，Bind 以监听成功验收；失败时恢复旧入口并重新启动服务。单独启动的普通进程不会使用这个 Launcher。

Linux systemd 和 Windows Service / Task Scheduler 的自动服务交接不受支持，Update 在构建前明确返回错误。其他 Windows/Linux 普通进程仍支持自动更新。

### iOS / Pythonista

在 iOS 上，Update 完成构建、SHA-256 校验和 Release 发布后，报告新版入口路径，提示操作者在 Pythonista 手动运行。没有桌面进程交接。

### 成功与故障结果

Reverse 的 `Updated` 表示新进程已取得 Server Session Token 并通过存活检查；Bind 和 launchd 在旧命令连接结束前报告的是**Bundle 已准备、交接已开始**，最后结果在一次性交接日志中记录。Bind 的候选进程及回退进程输出同样记录在交接日志中。普通 Reverse 失败会终止新候选并保留旧实例；Bind/launchd 失败执行恢复旧版。系统崩溃或交接进程被强制杀死时，恢复旧版需人工检查并重新启动原入口。原有 Watchdog 在旧进程退出前停止，更新候选在确认成功后才启用监督。

`update --observe` 仅支持普通桌面 Reverse（不包括 launchd 托管及 iOS）。普通 `update` 仍在新版通过就绪验收后自动结束旧实例。`--observe` 的日志由旧 Client 的 Device Monitor 通过既有 Log Viewer 读取，旧实例被 Kill 后不再继续读取。`update` 不修改当前 Server BindConnector、底层连接循环或 Clean 规则。

## Release 的布局与维护

桌面平台将更新内容放在当前用户主目录下：

```text
~/client_bundle/
├── downloads/
│   └── rchclient_python_<build_id>.zip
└── releases/
    └── python_<build_id>/
        ├── rchclient.py
        ├── client/
        └── core/
```

这里的 `<build_id>` 由实际构建结果提供，而不是手动填写的固定 Release 版本。iOS 的对应根目录在 `~/Documents/client_bundle/`。首次部署的 Bootstrap / Go Loader 还可能管理 `runtimes/python-embed/`，但 Client 自更新只处理新的 Source Bundle 和运行进程，不会借此重装整个 Python 环境。

更新不会因为新版本启动成功就自动清空先前 Release。现在由统一的 `clean`
处理 Client 临时残留、过期 Release 子目录、Bundle ZIP 和更新探测文件。
普通 `clean` 先扫描候选路径，再用一个可多选的 Preview 展示类别、目标数量及大小，
**默认全选**；用户可以取消任意类别。`clean --no-confirm` 不使用 Interaction
Broker，直接执行同一套清理扫描计划，供纯 CLI 调用。现有清理类别及新增的临时残留类别继续完整扫描，
命令输出逐项列出每个类别、检查过的目录、候选路径及跳过项；空类别也会输出
`(empty)`，而不是只显示 `Nothing to clean`。清理后移除空临时目录。

Release 清理不再要求 Client 从默认 Bundle 路径启动：如果当前不在
`releases/` 目录下，清理其中全部非保护子目录；如果正从某个 Release
运行，必须保留该 Release，删除其他子目录。不会根据目录是否含有
`rchclient.py` 放宽或缩小本次 Release 删除范围。所有已扫描路径在
执行前还会进行文件身份检查；扫描后已变化的目标不会删除。

Client 临时目录保持扁平分类：Windows 使用 `<系统临时目录>/rch_client_temp/<category>/`；
POSIX 使用 `<系统临时目录>/rch_client_temp_u<effective_uid>/<category>/`。POSIX 根目录按
effective UID 隔离并保持 `0700`，因此普通用户 Client 与 root/elevated Client 不再争用同一组
私有日志、Watchdog 和中转目录。`clean` 只扫描当前 Client 所属 UID 的具体类别，不会将
`client_logs`、`watchdog_logs`、
`watchdog_heartbeats` 等目录误认为旧的嵌套会话目录。除原有临时目录外，
可选清理类别还包括：

- `archive_temp`：列出至少 5 分钟没有写入的归档中转目录；这里可能保存仍需下载的 ZIP，人工预览时应检查。
- `client_logs`：列出超过 1 分钟没有写入的其他 Client 日志实例目录；不产生额外 PID/owner 文件，始终保留当前进程的日志目录。仅凭文件未更新不能确认其他 Client 已退出，因此 `clean --no-confirm` 不会删除此类日志；手动 `clean` 可在 Preview 中决定是否清理。
- `clipboard_staging`：非 macOS 平台超过 1 小时未写入的接收暂存目录；macOS 的 GUI 用户剪贴板目录仍然不参与清理。
- `watchdog_heartbeats`：超过 1 分钟未更新且归属 PID 已退出的 Local 心跳及遗留中转文件。
- `watchdog_sessions`：超过 1 分钟未更新、且独立监督进程确认已退出的 Process Recovery Watchdog 控制会话目录。

上述新类别均适用 Preview 身份签名检查；执行前还会重新判断活动保护条件。
`client_logs` 仅能确认当前进程的日志路径，不能保证其他 Client 没有在空闲运行；
因此 `clean --no-confirm` 不自动删除 `client_logs`，此类日志需要手动预览确认。
Watchdog 的**正在使用的固定日志**不纳入整目录清理，避免中断诊断写入。
Runtime Config 的原子中转仍在配置同目录，Bundle 更新目录遵守原保护规则，
External Tools 的安装、日志及实例目录不属于此命令的清理范围。

清理仅针对 **目标 Client** 的残留与 Release，不包含 Server 端
Agent Output 或其他构建产物。删除不可恢复，应在批准 Preview 前
检查每个类别的目标列表。

## 运行和排查中的关键判断

一台 Client 的 Build Version 变化但 Revision 不变，通常只说明重新构建了同一份源码；Revision 变了才说明参与指纹计算的源码内容发生差异。反之，只改连接参数或 Profile，可能改变构建配置，却不会改变 Client 源码指纹，不能用 Revision 代替所有配置的一致性检查。

遇到更新提示没有出现时，先确认目标设备当前是否真正 Online、Client 是否提交了 `client_revision`、是否在源码模式下尚未重启，以及 Server 当前是否运行在预期的源码目录。若整体 Revision 不同却没有逐文件差异，检查当前 Client 的文件级摘要查询是否成功，以及源码文件是否可用。整体 Revision 来自当前连接，明细由用户查询触发。

更新失败可按请求构建、下载、解压、启动与交接的实际阶段定位：构建依赖 Server 的构建能力与源码文件；下载依赖目标 Client 对其配置的 Web 地址及端口的访问；新 Release 启动还依赖目标系统的 Python 解释器、所需第三方依赖及 TCP 或 mTLS/TCP 连接地址可达。安装验证需要同时检查 HTTP 下载端口与 Client 的 TCP Socket 连接端口。Update Bundle 沿用 Client 配置的连接地址、端口和 Web 地址；FRP/NAT 转发后的访问端口不需要与 Server 本地监听端口一致。TCP Update 不要求匹配唯一 Listener；TLS/TCP Update 仍需匹配 Server 的证书指纹。

Reverse 的注册超时、Bind 的监听失败和交接超时均有明确错误状态。新版启动健康检查覆盖交接时刻；长时间运行期间的连接波动仍由 Client 原有生命周期处理。

`POST /api/agent/build` 与产物下载目前允许匿名请求，部署时需要把构建服务的网络暴露面作为独立运维边界考虑；构建和下载接口需要单独纳入部署网络访问控制。需要人工下载、安装或维护原始构建产物时，按 [Client Bootstrap 与首次部署](bootstrap.md) 的入口和安装方式处理；需要理解执行期间的任务取消与超时，则参阅 [Shell-like Commands](shell_like_commands.md)。

## Process Recovery Watchdog 更新交接

启用 [Process Recovery Watchdog](process_recovery_watchdog.md) 时，更新候选在就绪与 PID 校验完成前不会建立新的进程恢复监督链；成功验收后才启动相应 Watchdog。普通 Reverse 更新失败保留旧进程与原监督链；普通 Bind 及 launchd 更新时先停旧监督，再由新 Client 或服务管理器接管。`update --observe` 保留原 Client 的监督链。
