# Client Handshake & Capability Discovery

RCH 的 Client 与 Server 建立 TCP 连接后，需要完成一件比“上线通知”更基础的工作：让 Server 知道**当前这条连接是谁、运行在哪个环境、带有哪些命令和变量提示信息、能够在哪里操作文件，以及它对应哪份 Client 构建源码**。Python Client 把这组资料放进首次发送的 `info` 消息；Server 将其保存为当前 `ClientSession` 的会话信息，再分别提供给设备列表、命令输入栏、Connection Info、版本检查等功能。

握手是**连接开始时的一次性状态快照和能力声明**，不是周期性系统监控，也不是单独的设备认证协议。后续心跳只更新最近响应和部分运行状态；动态命令补全、运行配置查询、远程文件操作依然有各自独立的请求链路。理解这个边界，才能准确判断新命令为什么未出现在候选列表、设备详情为什么保留旧路径，以及重连之后哪些信息会刷新。

## 1. 连接建立时的消息交接

Python Client 初始化时先创建 `Client` 对象，为这个进程实例生成 `client_id`，初始化连接对象及其执行环境。随后 `connect()` 按顺序执行：

1. 根据 Client Profile 中的 `server_host`、`server_port` 连接 Server Socket；连接失败则按重连间隔重试，并重建连接对象。
2. TCP 建立后，由 `ClientInfoBuilder` 收集本地身份、当前平台的命令清单、变量提示、系统路径、构建信息与运行配置。
3. 使用 Socket 协议发送一条 `type: "info"` 的 JSON 消息，消息的 `id` 为当前 Client 实例的 `client_id`。
4. Client 本地将连接标记为已连接，再启动接收工作线程。这里的 `mark_connected()` 是本地状态更新，**不是收到 Server 的独立握手确认帧**。
5. Server 的监听线程读取新 Socket 的第一条消息，建立 `ClientSession` 并放入活动连接管理器，记录设备/连接历史，发布 `connection_online`；随后另启线程持续接收该连接的消息。

普通 Client Socket 默认连接 **9999** 端口，实际目标由 Client Profile 决定。这条通信不经过 8085 的 Web API，也不经过 8086 的独立文件传输服务。底层使用 `RCHSocket`：先写入以 `struct` 格式 `i` 表示的消息体字节长度，再写 UTF-8 JSON；Server 用同样的方式读取。长度头的本机字节序和整数尺寸来自当前 Python `struct` 约定，不应擅自把它描述为固定网络大端头。

Server 在等待第一条消息时，将被接受的 Socket 设置为 **5 秒接收超时**，接收结束后恢复原来的阻塞模式。超时应用于底层 `recv` 操作，而不是一个可以保证覆盖所有分片累计耗时的全程握手截止时间。无法正常读取或解析初始 JSON 时，Server 关闭该 Socket，不注册会话。注册成功后，新连接会立即拥有 `connected_at` 和初始 `last_seen_at`，不需要等第一轮 Heartbeat ACK 才出现在 Online 列表中。

握手本身不包含完整的命令执行结果、实时 CPU 占用、进程运行时间或 RTT；这些属于其他数据来源。TCP 接通、第一条 `info` 已发送、Server 已注册活动会话，也应被视为三个相继发生、但不完全等价的状态。

## 2. 会话身份与环境快照

Python Client 的握手不只是操作系统名称。`ClientInfoBuilder.build()` 生成一个包含以下几组字段的字典：

| 信息类别 | 实际字段 | 用途与取值时机 |
| --- | --- | --- |
| 当前连接身份 | `id`、`hostname`、`machine_id`、`machine_fingerprint_basis` | 区分活动 Client 实例与机器身份；来自当前进程的本地身份快照 |
| 系统和硬件 | `os_type`、`os_alias`、`os_full`、`os_name`、`os_ver`、`arch`、`manufacturer`、`model` | 展示平台、架构和设备资料，供 UI 判断或呈现 |
| 进程与权限 | `process_id`、`launch_command`、`username`、`process_name`、`integrity`、`cwd`、`python_ver` | 说明 Client 进程当时如何运行、具有何种权限及初始工作目录 |
| 构建与源码身份 | `build_version`、`client_revision`、`client_revision_parts`、`client_revision_files` | 标记构建产物，比较 Client 与 Server 的源码内容 |
| 运行能力与配置快照 | `http_transfer_mode`、`python_execution_mode`、`remote_watchdog_enabled`、`local_watchdog_enabled` | 表示 Client 启动时采用的相关运行配置值 |
| 提示与路径 | `command_manifest`、`variable_manifest`、`system_paths` | 提供命令候选、变量提示和 Client 端已知路径 |

`id` 是每个 Python `Client` 对象初始化时创建的 UUID v4；它代表 Client 进程实例，不是主机名或 `machine_id`。同一个对象因网络异常重连会继续使用原 `client_id`，进程重新启动则通常产生新值。`machine_id` 来自规范化机器特征的 SHA-256 指纹，特征不变时可以跨进程重启复现；它不会随着 `client_id` 每次重建而重新随机分配。完整的字段采集、指纹算法与设备库存归属见 [Device Identity & Inventory](./device_identity.md)。

`process_id`、`username`、`process_name`、`launch_command`、`cwd` 等描述的是**创建这份握手信息那一刻**。普通平台的用户和进程名由 `psutil` 查询；iOS 使用平台专用的进程信息方法；查询失败时可能返回空字符串。客户端不会因为进程经过几小时后 CPU、运行时长或环境信息改变，就不断发送新的 `info` 消息。

`integrity` 由 Client 权限探测逻辑计算，不是对 Server 授予的权限。`python_execution_mode` 和传输模式表示 Client 当前配置，不构成“此 Client 支持所有 Web 功能”的通用能力证明。界面如需展示某个实时可执行状态，应调用相应的运行时 API，而不是反复读取握手快照。

### 消息结构示意

以下是**按字段类别裁剪的合成示例**，用于说明顶层层次；`command_manifest` 和 `variable_manifest` 中的条目为语法示例，不代表项目当前注册命令清单：

```json
{
  "type": "info",
  "id": "f4e77bb6-a1f8-4e83-b2fe-e5f32e2f2b40",
  "hostname": "demo-host",
  "machine_id": "<machine-sha256>",
  "os_alias": "linux",
  "cwd": "/home/demo",
  "integrity": "user",
  "build_version": "dev",
  "client_revision": "<source-revision>",
  "command_manifest": [
    {"name": "example", "help": "Illustrative entry", "group": "general", "suggest": true}
  ],
  "variable_manifest": [
    {"namespace": "env", "name": "NAME", "template": "${env:NAME}", "dynamic": true, "candidates": ["HOME"]}
  ],
  "system_paths": {"home": "/home/demo", "temp": "/tmp"}
}
```

真实 Python Client 还会附带其他上述字段。不要将这里的省略值或示例名字视为协议标准值。完整载荷应以当前 Client `ClientInfoBuilder` 组装结果为准。

## 3. 能力如何被发现和声明

RCH 的能力发现并非 Server 在每次 Web 打开下拉框时扫描 Client 对象。Python Client 在构建握手时，通过其执行器与命令注册体系组装两份独立的 Manifest，并另行采集系统路径。这些信息最终挂在**这一条 ClientSession** 上；不同平台、不同 Client 构建可以提交不同结果。

### 命令注册表形成的 Command Manifest

Client 先取得当前平台的命令对象，然后检查拥有 `help` 装饰属性的可导出方法，为其生成候选记录，常见字段是：

| 字段 | 含义 |
| --- | --- |
| `name` | 命令名称或入口名称 |
| `help` | 简短帮助文本 |
| `group` | 用于命令候选的展示分组，缺省为 `general` |
| `suggest` | 是否建议在通常的帮助/提示 UI 中显示 |
| `template` | 可选的输入模板；未提供时 Server 使用 `name` |
| `source` | 可选的候选来源；Server 在缺省时按 Client 来源处理 |

结构化参数命令通过其注册表添加额外的 Manifest 条目，通常带有完整输入模板。最终命令 Manifest 会按 `group`、`name` 排序。普通命令中设置 `suggest=False` 的条目**不会因此失去执行能力**；它是提示/展示属性，而不是 Server 对该命令作出的权限授权决定。

`command_manifest` 是当前 Client 声明出来的**候选描述数据**。它不包含执行命令所需的一切状态，也不保证所有后续调用都会成功：执行器仍须完成真正的命令解析、参数验证、平台判断和权限/交互流程。完整的命令候选合并、参数级补全和前端接收行为见 [Terminal Autocomplete](./autocomplete.md)；命令执行方式见 [Shell-like Commands](./shell_like_commands.md) 与 [ACMD](./acmd.md)。

### 变量清单描述“可以怎样写”，不预先替换数值

`variable_manifest` 由 Command 执行器的 Variable Resolver 生成。当前机制为命令输入支持三个命名空间：

- `rch`：Client 运行态、身份或命令上下文等内置变量；每项附带模板及简短描述。
- `path`：Client 常用系统目录的命名变量；候选名称来自变量注册配置。
- `env`：提供 `${env:NAME}` 模板，并在构建 Manifest 时列出 Client **当前进程环境变量的名称**作为候选。

这里的关键区别是：Manifest **不携带环境变量的值**。`${env:...}` 在实际执行命令时由 Client 读取进程环境；`rch` 和 `path` 变量也由执行时的 Provider 求值。握手时提供 `env` 候选键，只为了让浏览器在输入阶段能够提示可能的名称，并不代表这些值会被传送给 Server。

由于变量名是在握手时采集的，如果进程环境在同一条连接中改变，Web 可能暂时保留旧候选；但执行时的 `${env:...}` 会依据 Client 当下读取的环境求值。这种“输入时名称快照”和“执行时数值解析”是两种不同的时间语义。参见 [Variables](./variables.md)。

### System Paths 是路径快照，不是远程目录扫描器

`system_paths` 在握手时调用 Client 的 `get_system_paths()` 生成，结果为路径名到该 Client 本地路径的字典。它包含操作系统根目录、用户目录、桌面/文档/下载、临时目录、执行文件目录等逻辑位置，并可能包含平台特有路径。

Server 保存的是这一刻的**路径字典**。它既不代表相应目录此刻一定存在，也不会替代 Remote Files 的文件列表与权限检查。远程浏览目录、判断文件类型、路径补全等依赖专门的 Client 操作；在更换用户环境或工作目录后，也不能仅靠此缓存推导真实可访问路径。`GET /api/connections/{client_id}/system-paths` 从当前 ClientSession 的已保存字段返回该字典，本身不是向 Client 重新发送一次系统路径采集请求。

Manifest 构建采用局部容错：如果读取命令列表或变量清单的过程抛出异常，`ClientInfoBuilder` 会将相应字段设为空列表，仍然构造其他握手信息。因此**设备在线不等于它一定上报了全部命令/变量提示**；需要区分“能力声明为空”与“TCP 未连接”。

## 4. Server 如何把握手变成可用的连接

Server 监听线程把初始 JSON 与接受连接时得到的来源地址结合，交由 Web Connection Service 构造 `ClientSession`。`SessionInfo.from_dict()` 将标准字段转为会话属性，对 `client_revision_parts` 和 `client_revision_files` 等对象字段做基本的类型归一化；其余未在标准字段集合中的键放进 `extras`。例如 Python 的 `process_id`、`variable_manifest` 和传输模式，以及 Go 的 `go_version`，会沿这个扩展字段通道保存。

标准字段与扩展字段的区别会影响后续读取方式，但它们均属于当前会话的握手资料。Server 并不依靠 `SessionInfo` 自动探测远端能力：未上报的字段会使用默认值或空集合，不能由此推断远端实际运行了哪些功能。

注册过程完成后，Server 通过 `client_id` 管理在线 `ClientSession`，绑定命令历史、Artifact、临时 Script Grant、PTY、Screen View、Clipboard、Monitor 和 Transfer 的会话回调；设置初始连接时间和最近活跃时间；按 `machine_id` 更新最近设备缓存与连接历史；最后发布 `connection_online` SSE。Server 不会因为握手带来了 `machine_id` 就用它替代 `client_id` 定位执行目标：同一台机器上可能同时运行多条 Client 连接。

对外查询时，**完整会话信息、设备列表摘要和专用能力 API 并不是同一份 JSON**：

| Web 入口 | 读到的握手数据及用途 |
| --- | --- |
| `GET /api/connections` | 活跃连接和最近离线设备；展示身份、平台、运行模式、Build/Revision、变量 Manifest 及在线状态等序列化摘要 |
| `GET /api/connections/{client_id}/command-candidates` | 从活动 Session 的 `command_manifest` 获取 Client 候选，再与 Server 命令候选合并、按模板去重、排序 |
| `GET /api/connections/{client_id}/system-paths` | 直接返回活动 Session 在握手时保存的 `system_paths` 字典 |
| `GET /api/connections/{client_id}/revision-status` | 读取 Client 所报 Revision，并与 Server 当前计算的源码 Manifest 比较，按需计算文件差异 |

尤其不要假设 `/api/connections` 直接返回整个 `command_manifest` 或 `system_paths`；当前连接摘要的序列化字段里**没有**这两个字段。Terminal 需要候选时另外调用 Command Candidates API，Connection Info 显示变量提示则直接读取摘要里的 `variable_manifest`。Browser 还可能在切换设备、历史固定命令变化等时重新合并自己的候选列表，但这不等于 Client 重新执行了握手。

部分字段还会经过 Server 派生加工：例如 `client_revision_state` 根据活动连接状态及 Server 计算的当前源码 Revision 判定，不是 Client 直接在握手里声明的状态；`machine_alias`、隐藏偏好、分组来源于 Server 持久化数据，也不是 Client 上报的硬件能力。最近离线设备依靠此前保存的快照仍可出现在列表中，但已经没有可读取实时命令 Manifest 的活动 Socket 会话。

## 5. Build Identity 与能力版本的关系

Python Client 握手同时传递 `build_version` 和 `client_revision`，但两者回答不同问题：

- `build_version`：这次 Client 构建产物的标识，源码模式通常为 `dev`；它不用于推断代码内容的新旧大小顺序。
- `client_revision`：纳入 Revision 计算范围的 Client 源码内容指纹；`client_revision_parts` 是分段指纹，`client_revision_files` 是文件级摘要，用于细化差异展示。

预构建 Bundle 可以把源码指纹及明细注入 Client 配置；源码模式在本地构建 Revision Manifest 并缓存。Server 查询时计算自己的当前源码指纹，比较相等时标记 `current`，不等时标记 `outdated`，缺乏可比 Revision 时为 `unknown`。这不是依赖某个自增版本号，也不是 Client 与 Server 建立连接前协商的协议版本。

更新检测能够说明已上报的 Client 源码身份与 Server 当前源码是否一致，但**不能由 Revision 相同证明所有运行功能都已正常初始化**。Command Manifest 是否完整、Client 平台是否支持某个 API、所需权限是否具备，仍须各自判断。完整构建和安全切换进程的说明见 [Client Builds and Updates](./client_update.md)。

## 6. 重连与能力更新

### 同一进程重连

Python Client 的接收循环在发生 Socket 错误或其他连接异常后，会停止接收线程、清理与旧连接关联的运行态及后台任务，重建 Socket/执行上下文，重新建立连接并发送新的 `info`。此过程沿用当前 `Client` 对象的 `client_id`，但会重新组装 `command_manifest`、`variable_manifest`、`system_paths`、运行模式等字段。机器身份通过进程内 `LocalIdentity` 缓存获取；源码 Revision Manifest 也可能复用进程内或构建时注入的数据，因此不能笼统地说“每次重连所有内容都从磁盘与硬件重扫一遍”。

当前实现没有单独的、可以在现有 Socket 连接中推送全量 `command_manifest` 或 `system_paths` 的通用 Capability Refresh 消息。若新增命令注册仅改变了运行中的执行器而未发生重连，Server 已保存的能力声明可能仍是旧快照；重新获取 Web 的候选 API 只会再次读取那份 Server 会话信息。修改后是否需要重新启动 Client，取决于命令注册与模块加载本身能否在运行进程内发生变化。

Heartbeat 更新连接的最近活跃信息、RTT 和可能的当前工作目录，却不会替换整份 `SessionInfo` 中的 Manifest。连接因错误关闭后，Server 在活动连接管理器移除会话，并按 `machine_id` 保留最近设备快照、更新历史和发布离线事件。新进程上线通常获得新的 `client_id`，但相同机器特征下仍可归入原来的设备身份。详见 [Connection Lifecycle](./connection_lifecycle.md)。

## 7. 扩展与运行边界

接入新的 Client 能力时，先确认它究竟属于**连接开始即可稳定描述的能力**，还是需要在执行时探测的动态状态。前者可以进入握手 Manifest；后者应通过自己的运行时命令、HTTP API 或监控 Session 获取，避免让设备列表中的缓存值冒充最新结果。

新增命令需要既有注册体系可以发现其导出方法或结构化参数声明，然后由 Client 在握手中生成候选。只增加前端展示名称而不实现执行器，不会产生可执行命令；只实现 Client 处理器却未进入命令 Manifest，也不会自然出现在 Server 的命令候选中。对新增变量，除了在 Resolver 注册可执行时求值的 Provider，还要确保 `variable_manifest` 能描述其名称与模板。对平台能力的判断，则应使用实际发送字段和后续 API 结果，而不是手写另一份永久支持清单。

### 安全与可信度

`machine_id` 是 Client 自报的设备标识；`command_manifest`、进程权限、主机名和路径也由 Client 组织并上报，不构成远端可信硬件证明。`info` 里的 Machine Fingerprint Basis 可能包含系统原生标识，`system_paths` 可能暴露用户名或目录结构，环境变量 Manifest 则会披露环境变量**名称**；这些数据应按设备敏感信息处理。源文件中的握手发送和接收流程没有一个独立的 Client Token Challenge/Response 校验步骤，不能因为 Web API 有 Session/API Token 认证就认定 TCP 握手完成了同样的身份认证。

当前 Server 主要依赖首包 JSON 解析和 `SessionInfo` 的基本字段映射，而不是一个对全部必填字段、类型、Manifest 结构和 `type=info` 进行严格协商的协议版本检查。握手没有提供的字段可能取默认值；`ConnectionManager` 对缺失 `client_id` 的连接还维护单独的匿名会话集合。它们意味着接入新 Client 时应主动验证必要字段与接口能力，不能把“成功连接”当作“客户端已完整上报全部能力”。

### 常见现象及定位

| 现象 | 应检查的环节 |
| --- | --- |
| Socket 可连接，但设备没有正常注册 | 第一帧 JSON/长度头是否有效；首帧读取超时；Server 是否进入 Session 注册路径 |
| Client Online，但没有本平台的命令候选 | `command_manifest` 是否构建成功；命令是否导出且注册；是否连接到新的进程/会话；前端候选是否重新加载 |
| 补全提示中没有刚设置的环境变量名称 | 变量名候选来自上次握手时的环境快照；与执行时实时读取的值不是同一阶段 |
| 系统路径看起来不符当前运行环境 | `system_paths` 是握手缓存；确认当前 Client 进程的用户/环境和最近一次连接时间 |
| Client 在线但更新状态 Unknown | 是否实际提交了 `client_revision`，以及 Server 是否能计算对应 Revision |
| 同机重启后设备归属改变 | 核对 `machine_id` 的指纹输入是否变化；设备归并不是仅按主机名进行 |
| 刷新浏览器后部分能力仍不出现 | 浏览器刷新不等于重新握手；区分 Server Session 中的旧快照与新 Client 注册 |

相关详细参考：[Device Identity & Inventory](./device_identity.md)、[Terminal Autocomplete](./autocomplete.md)、[Variables](./variables.md)、[Client Builds and Updates](./client_update.md)、[Connection Lifecycle](./connection_lifecycle.md) 与 [Administrator Authentication](./admin-auth.md)。

## 附录：Go Client（非主要维护路径）

这一独立实现只用于解释连接能力边界，不属于上文 Python Client 握手工作流。它在 TCP 连接后同样发送 `type: "info"`，并在同一进程的重新连接间沿用 Client ID，但当前上报内容较少：

- 基础字段包括 `id`、`os_type`、`os_ver`、`hostname`、`cwd`、`integrity`、`go_version` 和 `build_version`。
- `command_manifest` 来自其自身的命令执行器；没有上报 `variable_manifest`。
- `system_paths` 当前为空列表，Server 将其归一为空字典。
- 没有上报 Python Client 使用的 `machine_id`、`machine_fingerprint_basis`、`client_revision` 及其源码指纹明细。

因此，该实现即使在线，也不能直接视为具备本篇介绍的完整机器归并、变量提示和源码 Revision 检测能力。相关代码位于 `backend/client-go/`；上文的功能开发与故障判断默认针对 Python Client。
