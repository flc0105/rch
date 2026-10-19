# Client Builds and Updates

RCH 使用两种不同的身份描述 Client：`build_version` 标识一次可分发的构建产物，`client_revision` 标识参与 Client 运行的源码内容。Server 可以直接比较在线 Client 与当前源码的 Revision，决定是否提示更新；真正执行更新时，才构建并分发新的 Python Source Bundle。**发现源码差异、生成安装包和替换运行中的 Client，是三个独立阶段。**

这条工作流涉及 Server Agent Builder、Client 握手、连接状态服务、Web Terminal 和 Client 自更新命令。下面按源码从构建到运行、再到新旧 Client 交接的顺序说明。首次部署所用的 One-liners、Python / PowerShell Bootstrap 和 Go Loader 另见 [Client Bootstrap and Deployment](one_liners_bootstrap.md)。

## 构建产物与源码身份

Server 的 Agent Builder 为每次构建生成独立的 `build_id`，形式为本地时间戳加一段随机 UUID。它再结合构建类型产生 `build_version`，并记录在产物元数据中。**重复构建完全相同的源码，仍会得到不同的 Build Version。** Build Version 不是语义化版本号，也不用于判断某台设备的源码是否过期。

Python Source Bundle 使用统一的命名契约：`rchclient-source-bundle-<build_id>.zip`；对应 `build_version` 是去掉 `.zip` 后的名称。该名称同时用作更新后的 Release 目录名，因而下载文件、解压目录和运行实例所报告的 Build Version 可以互相定位。

`client_revision` 则由 `build_client_revision_manifest()` 计算。它遍历构成 Python Client Bundle 的三个根：`client/`、`core/` 和 `rchclient.py`，按确定顺序把相对路径、分隔符与文件内容纳入 SHA-256，取前 **16 个十六进制字符**作为整体 Revision。实现还可生成两层诊断数据：

| 字段 | 表示内容 | 用途 |
| --- | --- | --- |
| `client_revision` | 整个 Client 源码集合的内容指纹 | 判断当前 Client 与 Server 源码是否一致 |
| `client_revision_parts` | 源码根目录及其直接子项的分组指纹 | 保留较粗粒度的差异定位能力 |
| `client_revision_files` | 相对文件路径对应的文件内容指纹 | 精确展示新增、删除和修改的源码文件 |
| `build_version` | 某次构建产物身份，源码开发运行时通常为 `dev` | 定位构建、Release 和客户端的交付来源 |

Revision 只覆盖上面规定的源码范围，不等于整个仓库、Web 前端或 Server 的 Git 版本。计算时排除 `client/config`、`__pycache__`、虚拟环境、构建缓存，以及 `.pyc` 等非源码内容。因此，仅修改 Client 的 Server 地址、Profile 或其配置模块，不一定改变 Revision；反过来，增加、删除或修改被纳入范围的运行代码文件会改变指纹。文件差异比较使用路径和文件内容的实际指纹，并不依赖 Git 工作区或提交记录。

### 构建时注入与源码启动

生成 Python Bundle 时，Server 将目标 Socket 地址、Web 地址及端口、`build_version`、Revision 和分组/文件指纹写入 Bundle 内的 Client 配置。计算 Revision 的依据是 **Server 原始 Client 源码**，不是把构建后注入的不同连接参数再重新算作代码变化。Bundle 随后压缩并交付，Client 在握手时读取这些值。

在源码/IDE 环境中直接运行 Client，配置 Profile 通常给出 `build_version=dev`，没有预先注入的 `CLIENT_SOURCE_REVISION`。这种情况下 Client 首次构造握手信息时在本地计算源码指纹，并在当前进程内缓存。**编辑本地源码后，已经运行的进程不会自动重新计算指纹或热加载代码**；应重新启动对应源码进程以重新生成握手信息。

Go Client 也会在握手时报告自身的 Build Version，但当前 Go 握手不提供上述 Python 源码 Revision Manifest。因此不能将 Python Source Bundle 的 Revision 检测结果直接解释为 Go 可执行程序的版本判定。

## Server 如何生成和保存可部署 Client

Server 的 Agent Builder 是统一构建入口。Web Agent Builder、Bootstrap / Go Loader 的部署流程以及已连接 Python Client 的 `update`，都通过构建服务生成产物；本篇涉及的运行中更新**固定请求 `builder: "bundle"`**，与用户此前在构建界面选择过哪一种输出无关。

一次 Bundle 构建可以按以下请求发起，地址和端口需替换成实际部署环境：

```http
POST /api/agent/build
Content-Type: application/json
```

```json
{
  "builder": "bundle",
  "target_os": "bundle",
  "server_host": "192.0.2.10",
  "server_port": 9999,
  "server_web_scheme": "http",
  "server_web_host": "192.0.2.10",
  "web_port": 8085,
  "source": "update"
}
```

Server 在临时工作目录复制 Bundle 所需源码，注入 Client 配置后打包，再把构建结果复制到 `SERVER_RUNTIME_DIR/agent_output/`（默认 `backend/runtime/agent_output/`）。同目录下的 `.metadata/<filename>.json` 保存构建时间、Build Version、构建方式、系统和架构、连接参数、请求来源等信息。构建成功会发布 `agent_build_lifecycle` 事件（`completed`），失败则发布 `error`；这些是**构建事件**，不是 Client 已经升级成功的确认。

`POST /api/agent/build` 的 Bundle 响应提供 `file_name`、`build_version`、`download_url` 以及服务端对实际 ZIP 计算的 `sha256`。产物下载通过 **Web/API 端口**上的 `GET /api/agent/download/{filename}` 完成，不经过文件传输专线的 8086。构建产物可以通过 `/api/agent/outputs` 查看，并通过相应删除接口移除；删除某个 Server 构建产物，不会卸载已安装在远程设备上的 Release。

这里的产物元数据与 Client 运行时的源码指纹不是同一份数据：构建记录用 Build Version 和文件名定位下载物，Revision 会被注入 Python Bundle 并随 Client 握手报告。即使 Server 不主动构建新产物，也能用当前磁盘的源码 Revision 判断已连接 Client 是否落后。

## 在线连接怎样判断是否需要更新

Python Client 建立 TCP 连接后，在 `info` 握手中发送 `build_version`、`client_revision`、`client_revision_parts` 和 `client_revision_files`。Server 将这些字段保存在对应 `ClientSession`，同时用于设备信息展示与按需版本检查。

Server 对**在线连接**把握手 Revision 与本机当前源码 Revision 比较：两者都存在且一致时为 `current`，两者都存在但不同为 `outdated`，任何一方缺失时为 `unknown`。这不是比较 Build Version 的字符串大小。即使新的构建产物名称不同，只要源码指纹相同，仍可以是 `current`。

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

上面的路径与 Revision 都是字段示意，不代表仓库中存在该文件。`changed_files` 通过客户端握手时的文件指纹集合与 Server 当前集合的并集求差，`change` 区分 `added`、`removed`、`modified`。如果 Client 没有提交文件指纹，仍可能根据整体 Revision 判断 `outdated`，但 `changed_files_available` 为 `false`，详情无法列出逐文件差异。

连接状态也是判断的前提：设备不处于 Online 时，列表不继续展示在线更新判定；直接查询上述接口也会按离线分支返回（包含 `stale` 的情况），而不是用最近设备缓存中的旧信息推测最新源码状况。连接健康状态另见 [Connection Lifecycle](connection_lifecycle.md)。

Web 会在设备列表对 `outdated` 的在线设备显示更新标记，并在选中设备时按需请求详细差异。Terminal 的提示会结合 `build_version` 区分操作：已安装的构建版可以建议输入 `update` 并查看 Details；`dev` 环境建议从 IDE / 源码重启。**更新提示不会自动下载、安装或执行远程命令**，需要操作者明确发起。

## 正在运行的 Client 怎样完成交接

远程 `update` 是 **Python Client 的普通 Client 命令**。它从当前 Client 发出新的 Bundle 构建请求，下载、准备新 Release，再启动一个新的 Python Client 进程。它采用协作式取消策略，支持可选的 `--keep-old`；该选项只影响完成交接后是否退出原 Client，不影响构建本身。

```text
Web Terminal 提交 update
    ↓
当前 Client 请求 Server 构建 Source Bundle（8085）
    ↓
下载 ZIP 到 downloads/（先写 .part，再原子替换）
    ↓
安全解压至临时目录 → 检查入口脚本 → 发布到 releases/
    ↓
启动独立 Python Client → 新实例建立 TCP 连接并发送握手
    ↓
核对启动标记中的 PID → 短暂检查新进程仍存活
    ↓
默认：原 Client 延迟退出    /    --keep-old：原 Client 保留
```

默认输入 `update`，只有希望两个 Client 实例并存时才使用：

```text
update --keep-old
```

整个下载使用 HTTP 流式读取，先落到 `downloads/<bundle-name>.zip.part`，成功后再替换成 ZIP。下载异常时会移除 `.part`。归档解压会检查路径安全，并先解到独立临时目录；确认其中有 `rchclient.py` 后才发布为最终 Release。对于已经存在且具有入口脚本的同名目录，当前逻辑会直接复用，不会删除可能正在运行的目录。**这里的入口文件检查不等于对安装环境、所有依赖或完整源码做端到端自检。**

### 新旧进程的切换条件

非 iOS 平台启动新的 Python 进程时，将 `--update-ready-file` 交给新进程。新进程完成本地 Socket 连接、发送 `info` 握手后，写入包含 `pid`、`client_id` 和 `client_revision` 的就绪文件。旧 Client 最多等待 **10 秒**，要求标记中的 PID 与自己创建的新进程一致，并继续观察新进程约 **2 秒**，确认它没有立即退出。

就绪文件意味着新进程已经执行到**本地连接与握手发送阶段**；它不是 Server 返回的一份独立“上线审核成功”确认，也不保证之后一直在线。若新进程提前退出或就绪等待超时，原 Client 会报告失败，尝试终止未通过交接的新进程，**不会主动退出旧 Client**。启动异常日志可附在错误信息中，探针文件最后会清理。

就绪确认后，默认先报告执行结果，再短暂延迟、停止当前 Guard Manager、关闭 Socket 并退出原进程；`--keep-old` 跳过这个旧进程退出步骤。因此保留旧实例时，在设备上可能同时看到多个具有不同 `client_id` 的活动连接。与设备身份、连接历史的区别，详见 [Connection Lifecycle](connection_lifecycle.md)。

在 iOS / Pythonista 环境，`update` 完成 Bundle 下载与解压后，只返回新入口脚本的位置，提示重启 Pythonista 并手动运行；它不尝试执行桌面平台的自动新旧进程交接。

### 完整性校验的实际边界

构建 API 对 Bundle 提供 SHA-256，Python / PowerShell Bootstrap 和 Go Loader 在安装前会用它校验下载结果。**当前 Client 的 `update` 下载实现本身没有消费这一 SHA-256 字段进行额外散列校验**；它依赖 HTTP 下载成功、ZIP 可解压与入口脚本检查。不能因为这些流程最终安装到相同的 Release 目录，就认为它们拥有完全相同的下载校验过程。

## Release 的布局与维护

桌面平台将更新内容放在当前用户主目录下：

```text
~/client_bundle/
├── downloads/
│   └── rchclient-source-bundle-<build_id>.zip
└── releases/
    └── rchclient-source-bundle-<build_id>/
        ├── rchclient.py
        ├── client/
        └── core/
```

这里的 `<build_id>` 由实际构建结果提供，而不是手动填写的固定 Release 版本。iOS 的对应根目录在 `~/Documents/client_bundle/`。首次部署的 Bootstrap / Go Loader 还可能管理 `runtimes/python-embed/`，但 Client 自更新只处理新的 Source Bundle 和运行进程，不会借此重装整个 Python 环境。

更新不会因为新版本启动成功就自动清空所有先前 Release。`clean_releases` 可以在当前 Client **确实运行于默认 `releases/` 下的某个有效 Bundle 目录时**执行清理；它保护当前运行目录，删除该目录之外的其他 Release 子目录，并清除 `downloads/` 中匹配 Source Bundle 命名的 ZIP。这个操作会删除其他已安装 Release，因此在并行保留旧 Client、准备回退或管理多个 Release 时，应先确认不再需要那些目录。未从默认 Release 目录运行的 Client 会跳过这项清理。

普通 `clean` 还有其他 Client 临时残留清理职责，不等同于只清除旧 Bundle；不应把 Server 端删除 Agent Output、目标设备清理 Release，以及终止某个仍运行的 Client 当成同一操作。构建产物本身位于 Server 文件系统，Release 位于目标设备用户目录，两边的生命周期独立。

## 运行和排查中的关键判断

一台 Client 的 Build Version 变化但 Revision 不变，通常只说明重新构建了同一份源码；Revision 变了才说明参与指纹计算的源码内容发生差异。反之，只改连接参数或 Profile，可能改变构建配置，却不会改变 Client 源码指纹，不能用 Revision 代替所有配置的一致性检查。

遇到更新提示没有出现时，先确认目标设备当前是否真正 Online、Client 是否提交了 `client_revision`、是否在源码模式下尚未重启，以及 Server 当前是否运行在预期的源码目录。若整体 Revision 不同却没有逐文件差异，检查握手中是否提供了 `client_revision_files`。这些诊断信息都依赖当前连接快照，而不是历史设备缓存。

更新失败可按请求构建、下载、解压、启动与交接的实际阶段定位：构建依赖 Server 的构建能力与源码文件；下载依赖目标 Client 对 8085 Web 端口的访问；新 Release 启动还依赖目标系统的 Python 解释器、所需第三方依赖及 Socket 9999 可达。只有 HTTP Web 服务可达，并不能保证新 Client 可以建立 TCP 连接。连接地址在构建时已注入 Bundle，因此 Server 上生成构建的地址参数必须对目标设备可用。

若新进程没有按时提交就绪标记或在稳定性检查期间退出，旧进程会保留；这属于避免过早关闭旧连接的交接保护，不是原子级自动回滚已解压文件的事务。反之，成功交接后的新进程仍可能在稍后因运行环境或网络问题断开，不能将短暂存活检查解释为长期健康保证。

`POST /api/agent/build` 与产物下载目前允许匿名请求，部署时需要把构建服务的网络暴露面作为独立运维边界考虑；它不等于通过了 Web 管理员登录。需要人工下载、安装或维护原始构建产物时，按 [Client Bootstrap and Deployment](one_liners_bootstrap.md) 的入口和安装方式处理；需要理解执行期间的任务取消与超时，则参阅 [Shell-like Commands](shell_like_commands.md)。

## Process Watchdog 更新交接

启用 [Process Watchdog](process_watchdog.md) 后，更新候选 Client 在 `--update-ready-file` 验证期间不创建进程复活监督链。旧 Client 确认新进程 PID、握手和稳定时间后，写入 `.accepted` 并等待新 Client 的 `.adopted` 确认，再决定是否关闭旧实例。失败候选不会由 Process Watchdog 自动复活。`--keep-old` 时旧实例保留独立监督链；普通更新在旧实例退出前停止其监督链。
