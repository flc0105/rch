# `rch.db` 数据库详解

`rch.db` 是 RCH Server 使用的 SQLite 持久数据库，保存设备与连接信息、命令和活动历史、通知、偏好、后台 Job 状态等**结构化记录**。日志、Artifact 实体文件和 Client 运行数据分别位于其他存储位置，参见相应章节。前台通过 Server API 读取这些记录；数据库中的列名不必与界面显示文字一一相同，部分列表还会合并实时连接状态、关联记录和文件元数据。

本文以系统实际使用的数据结构为准，逐表列出字段和对应的 Web 功能；表和字段名称保留原始数据库拼写，便于用 SQLite 工具查看。相关功能的完整操作说明可参见 [Server Runtime](server_runtime.md)、[Device Identity](device_identity.md)、[Activity Center / Quick History](command_history.md) 和 [Background Jobs](background_jobs.md)。

## 数据位置、基本概念与范围

默认文件位于 `backend/runtime/rch.db`。Server Runtime 根目录可以在启动前通过 `RCH_SERVER_RUNTIME_DIR` 指定；改变目录意味着 Server 将读取另一份数据库。完整 Runtime 目录及其他持久文件见 [Server Runtime](server_runtime.md)。

- **`machine_id`**：一台逻辑设备的稳定标识。最近设备、分组、Quick History、Activity、Pinned Paths 等以它归属数据。它不是用户名，也不是浏览器访问地址。
- **`client_id`**：某个 Client 运行实例的标识；同一 `machine_id` 下可能有多个 `client_id`。活动连接、连接历史及部分 Job 记录会用它区分实例。
- **时间字段**：`*_at` 通常是文本形式的日期时间；`*_at_ms` 是用于排序或查询的毫秒时间戳。各记录可能采用不同的时间文本格式，不建议直接按文字跨表比较。
- **`*_json`**：SQLite `TEXT` 中存放的 JSON 对象或数组。它们不是另一张可独立更新的关系表；同一业务的固定列通常是筛选、排序或标识所需字段，JSON 保存扩展的业务内容或快照。
- **布尔量**：SQLite 没有独立的布尔列类型，这里通常以整数 `0/1` 保存；展示时由 Server 转成 `false/true`。

正常启动、完成 History 模块初始化后，当前结构共有 **16 张应用表**（不计 SQLite 自己的 `sqlite_sequence` 等内部对象）。其中 `activity_records` 由 History 模块创建；单独初始化 SQLite 数据库、却没有启动 History 时，可能只能看到另外 15 张表。空表是正常情况，不代表对应功能没有实现。

## 业务功能与数据表速查

| 前台功能或管理场景 | 主要数据表 | 保存的内容和作用域 |
| --- | --- | --- |
| Connections、Recently Seen、设备名称/排序/隐藏 | `recent_devices` | 每台设备最近一次汇总状态及视图偏好，按机器归属 |
| Machine Connection History、连接详情 | `connection_sessions` | 连接的上线、下线、持续时间及当时的设备快照 |
| Device Groups | `device_groups`、`device_group_members` | 分组名称与设备所属分组 |
| History → Quick History | `command_recents`、`pinned_commands` | 最近手动命令、调用次数和独立的固定项 |
| History → Activity Center、连接历史中的操作摘要 | `activity_records` | 已记录的操作种类、状态、入参摘要、结果与文件引用 |
| Notification Center | `notifications` | 已保存的通知列表及可用操作 |
| Notification Settings、Toolbar Settings、Toolbox | `settings` | 不同命名空间的全局设置 JSON |
| Remote Files → Pinned Paths | `pinned_paths` | 每台设备收藏的路径名称和路径文本 |
| External Tools → 参数预设 | `external_tool_presets` | 按工具保存的命名参数预设 |
| Background Jobs | `background_jobs`、`background_job_messages`、`background_job_files` | Job 实例状态、输出消息、生成文件的引用 |
| 数据库自身状态 | `schema_migrations` | 已应用的数据库结构记录，不对应前台功能 |
| **旧执行记录结构** | `command_executions` | 当前仍可能存在，但**不是现行 Activity Center 的读取来源** |

以下每组“字段”列举的均为实际数据库列。**主键（PK）**决定记录唯一性；“引用”是业务关联，不一定存在数据库外键约束。

## 设备、连接与分组

### `recent_devices` — 最近设备与显示偏好

**前台对应：** Connections 设备列表、最近设备/离线设备、设备别名、显示顺序以及隐藏设备或某个 Client 实例。记录按设备合并，不能将这里的一行理解成一条正在连接的 Socket。

| 字段 | 含义、前台作用 |
| --- | --- |
| `machine_key`（PK） | 用于稳定查找设备的规范化机器键；通常是 `machine_id` 的小写形式。 |
| `machine_id` | 设备真实逻辑标识；关联其他机器级数据。 |
| `client_id` | 最近一次记录中关联的 Client 实例，不保证该实例此刻在线。 |
| `machine_order` | Connections 设备排列顺序。 |
| `connection_state` | 最近记录的在线/离线状态；正在显示的状态还可能结合实时连接信息。 |
| `last_seen_at` | 最近一次见到设备的时间。 |
| `recent_updated_at` | 最近设备记录的更新时间。 |
| `machine_alias` | 用户为设备设置的显示名称。 |
| `device_hidden_by_machine` | 是否按整台机器隐藏（`0/1`）。 |
| `hidden_client_ids_json` | 按具体 `client_id` 隐藏实例的标记集合。 |
| `snapshot_json` | 最近连接信息和设备属性快照，例如主机名、系统/架构、连接地址等；并非在线状态的唯一依据。 |

**设备操作：**“隐藏”保存列表视图偏好；断开连接使用 Kill Connection；清除最近设备信息使用 Forget。应从对应页面操作，而非直接修改数据库偏好字段。详见 [Device Identity](device_identity.md)。

### `connection_sessions` — 机器连接历史

**前台对应：** Machine Connection History、连接时间线、历史连接详情；对应 Activity 摘要需要再按 `machine_id`、`client_id` 查询 `activity_records`。

| 字段 | 含义、前台作用 |
| --- | --- |
| `machine_id`、`client_id`（联合 PK） | 一台设备中一个 Client 实例的记录定位键。它不是每次网络重连都会新增一行的纯事件流水。 |
| `connected_at`、`connected_at_ms` | 连接开始时间及其毫秒表示；用于时间线显示和排序。 |
| `disconnected_at`、`disconnected_at_ms` | 断开时间及其毫秒表示；未断开时通常为空文本/零值。 |
| `last_seen_at` | 该连接最近一次心跳/被看见的时间。 |
| `duration_ms` | 连接持续时长；在线显示时可以根据当前时间动态计算。 |
| `connection_state` | 保存的连接状态，如在线/离线。 |
| `disconnect_reason` | 原有连接结束标记，继续对应 Connection History 中的 Disconnect / Interrupted 状态展示。 |
| `termination_reason` | 会话终止类别，在 Connection History 中以 **Termination cause** 呈现；Server requested disconnect、Client exit / restart / update、Connection lost、Transport error、Timeout、Unexpected disconnect 和 Client error 各有对应采集路径。 |
| `error_diagnostics_json` | 异常诊断 JSON；出现 Client error、Transport error、Timeout 或协议帧中断时，保存实际错误 `summary` 与可取得的 `traceback`，在 **Error diagnostics** 中展示；正常结束保存空对象。 |
| `tracking_source` | 连接状态记录的来源标记。 |
| `snapshot_json` | 连接阶段的主机、系统、进程、运行方式、Watchdog 配置等快照，支持历史详情展示。 |

**在线连接**由运行中的 Server 管理；数据库表保存历史与快照。管理当前 Socket 应使用 Connections 的对应操作。连接时间线内的操作记录来自 `activity_records`，不是 `connection_sessions` 自己的子列。

### `device_groups` — 分组定义

**前台对应：** Device Groups 的创建、重命名、列表和删除。

| 字段 | 含义、前台作用 |
| --- | --- |
| `group_id`（PK） | 分组内部标识。 |
| `name` | 显示在 Device Groups 中的分组名称；按不区分大小写的方式要求唯一。 |
| `created_at` | 分组创建时间。 |
| `updated_at` | 分组最近更新时间。 |

### `device_group_members` — 设备与分组的对应关系

**前台对应：** 将设备加入、移出或移动到其他分组。

| 字段 | 含义、前台作用 |
| --- | --- |
| `machine_id`（PK） | 被分组管理的设备。每台机器在本表最多对应一个分组。 |
| `group_id` | 所属分组，引用 `device_groups.group_id`。 |

此表对 `device_groups` 使用真正的外键，删除分组会级联删除**成员关系**，而不是级联删除设备、连接历史或命令记录。分组归属与 `recent_devices` 的显示数据也不是同一个字段。

## 命令与操作历史

### `command_recents` — Quick History 的 Recent

**前台对应：** History → **Quick History** 的最近手动命令、使用次数及最近执行状态。只按手动 Terminal / Server CLI 的录入规则增加，不是所有界面操作的全集。

| 字段 | 含义、前台作用 |
| --- | --- |
| `machine_id`、`command`（联合 PK） | 同一机器上的同一命令文本只保留一条最近记录；`command` 是用户输入的命令文本。 |
| `last_used_at`、`last_used_at_ms` | 最后使用时间，列表按最近使用排序。 |
| `use_count` | 该命令累计被记录的次数。 |
| `snapshot_json` | 最近一次执行关联的状态、时间、Client、工作目录和输出统计等摘要。 |

**删除边界：** Clear Quick History 仅处理 `command_recents`；有搜索词时按匹配命令范围删除，不会自动移除固定的命令。Recent 有保留数量限制，不是无限的完整执行审计。

### `pinned_commands` — Quick History 的固定命令

**前台对应：** Quick History 的 Pin / Unpin、上移下移和固定命令重放。

| 字段 | 含义、前台作用 |
| --- | --- |
| `machine_id`、`command`（联合 PK） | 一台设备上的一个固定命令。 |
| `pinned_at` | 固定时间。 |
| `pin_order` | 固定区域的显示顺序。 |
| `snapshot_json` | 固定命令附带的显示快照；Recent 消失时也可以独立保留。 |

**不要混淆：** 此表的 Pin 是 History 命令收藏；工具栏 Quick Actions 的固定入口保存在下文的 `settings`，并非此表。

### `activity_records` — Activity Center 的现行数据

**前台对应：** History → **Activity Center**，支持类型、Errors、搜索、分页和详情；Machine Connection History 的操作摘要同样会读取本表。

| 字段 | 含义、前台作用 |
| --- | --- |
| `activity_id`（PK） | 一次已记录操作的唯一标识，供详情、结果关联和单条删除使用。 |
| `machine_id` | 操作所属设备；页面按选中的机器读取。 |
| `client_id` | 实际派发操作时关联的 Client 实例；可用于连接历史中的操作摘要。 |
| `kind` | 操作分类；前台类型筛选和类型图标依据它。 |
| `action` | 具体动作名称；用于活动标题、摘要和搜索。 |
| `origin` | 操作来源类别，例如来自哪个命令/界面入口。 |
| `presentation` | 活动的展示语义，辅助详情组织内容。 |
| `status` | 当前/最终执行状态，决定成功、失败、取消等状态显示和 Errors 筛选。 |
| `invocation_json` | 用户发起的可记录调用信息，如输入命令或结构化参数；活动详情和搜索会读取它。 |
| `resolved_json` | 服务端解析并实际下发操作的可记录描述；活动详情和搜索会读取它。 |
| `result_json` | 操作结果摘要、受限制保存的输出记录和截断标记等。 |
| `created_at` | 业务活动的创建时间。 |
| `started_at`、`started_at_ms` | 执行开始时间及排序用毫秒值。 |
| `finished_at` | 已结束操作的完成时间；未结束时可为空。 |
| `files_json` | 本次操作产生或关联的 Artifact 文件引用；不是文件二进制内容。 |

`kind` 当前包含 `command`、`alias`、`script`、`remote_files`、`transfer`、`external_tool`、`background_job`。Errors 筛选匹配 `error`、`cancelled`、`interrupted`、`timed_out` 四种状态。搜索同时查动作名以及调用/解析信息的 JSON 文本；分页只是显示方式，按条件 Clear 会删除该机器**所有匹配记录**，不只删除已加载的一页。

**与 Quick History 的关系：** 两者有不同的写入时机和记录规则。删除 Activity 不删除 Quick Recent 或 Pins；清除 Quick Recent 也不删除 Activity。实际录入范围、输出长度限制、敏感信息边界见 [Command History](command_history.md)。

### `command_executions` — 保留的旧执行结构

**前台对应：当前没有直接对应的活动列表。** 这是基础数据库结构里仍然存在的旧命令执行表，但现行 Activity Center 已改用 `activity_records`；不能因为看到 `command_executions` 就认为其中的数据会显示在 Activity Center，也不能把它当成后者的备份。

| 字段 | 含义 |
| --- | --- |
| `entry_id`（PK） | 旧执行记录标识。 |
| `machine_id`、`client_id` | 记录归属的设备和 Client。 |
| `hostname`、`addr` | 当时的主机与连接地址信息。 |
| `command`、`raw_command` | 命令文本与原始命令文本。 |
| `source`、`status` | 来源与记录状态。 |
| `created_at`、`started_at`、`started_at_ms`、`updated_at`、`finished_at` | 旧记录中的生命周期时间。 |
| `cwd_start`、`cwd_end` | 执行前后的工作目录。 |
| `output_line_count`、`output_chunk_count`、`output_char_count`、`output_truncated` | 输出统计与是否截断。 |
| `output_records_json` | 旧执行输出的 JSON 记录。 |
| `files_json` | 旧执行关联的文件引用。 |

它目前仍由基础数据库结构保留，但**不是当前 Web History 的读写主路径**。本文仅说明现状，不把它描述成可通过当前 UI 管理的新功能。

## 通知与界面偏好

### `notifications` — Notification Center 持久通知

**前台对应：** Banner 右侧的 Notification Center、类型筛选、清除全部或清除某一类型，以及通知的操作入口。

| 字段 | 含义、前台作用 |
| --- | --- |
| `id`（PK） | 单条通知 ID；用于去重、定位和删除。 |
| `event_id`（唯一，可为空） | 来源事件的去重标识。 |
| `notification_key` | 通知事件类别键，用于与通知偏好关联。 |
| `type` | 通知级别：`success`、`info`、`warning`、`error`；用于类型过滤和样式。 |
| `title`、`message` | 通知标题与正文。 |
| `shown_at`、`shown_at_ms` | 通知时间及排序用毫秒时间戳。 |
| `context_json` | 通知关联的业务上下文。 |
| `actions_json` | 通知可呈现的操作项描述及目标信息。 |

此表保存 **Server 级**通知历史，通知上下文可以在 `context_json` 携带设备信息；表中没有 `machine_id` 列。通知历史由 Server 持久保存，关闭弹出提醒只调整通知呈现偏好。Server 启动清理可能清理启动前已有通知，见 [Cleanup](cleanup.md)。

### `settings` — 多种全局偏好共用的 JSON 容器

**前台对应：** Terminal Toolbar 的 Toolbar / More 排列、Toolbox 自定义快捷项、Quick Actions 工具栏固定项，以及 Notification Settings 中的通知开关。

| 字段 | 含义、前台作用 |
| --- | --- |
| `namespace`（PK） | 偏好类别名称；每个类别一行，**不是每个开关一行**。 |
| `value_json` | 当前类别的完整设置对象，具体键见下表。 |
| `updated_at_ms` | 该类别最后一次保存的毫秒时间戳。 |

| `namespace` | `value_json` 的主要内容 | 对应界面 |
| --- | --- | --- |
| `toolbar_preferences` | `toolbar`、`more`（工具排序与归属）；`quick_actions_pinned`（按平台及 Alias 固定的 Quick Action）；`toolbox_shortcuts`（Script / Quick Action 资源身份、图标及可选显示名称） | Terminal Toolbar Settings、Toolbox 的 Add / Unpin、Quick Actions 固定项 |
| `notification_preferences` | `enabled`（全局通知投递开关）、`events`（各事件投递开关）及偏好对象中的结构标识 | Notification Settings、桌面通知投递控制 |

这里的设置由 Server 共享，不按 `machine_id` 建独立行。`toolbox_shortcuts` 是快捷入口引用，并不保存 Script 正文或 Alias 定义。`notifications` 保存的是**实际通知历史**，`notification_preferences` 仅决定通知投递偏好；详见 [Toolbox](toolbar_toolbox.md) 和 [SSE Notifications](sse_notifications.md)。浏览器自己的临时选中状态或交互状态，不一定存入 `rch.db`。

## Remote Files 与 External Tools

### `pinned_paths` — Remote Files 收藏路径

**前台对应：** Remote Files 中按设备收藏的常用目录/路径列表。

| 字段 | 含义、前台作用 |
| --- | --- |
| `machine_id`、`display_name`（联合 PK） | 一台设备内唯一的收藏显示名称。 |
| `path` | 对应 Client 侧的目录或文件路径文本。 |
| `created_at` | 收藏创建时间。 |
| `updated_at` | 收藏修改时间。 |

这里保存的只是**路径引用**，不是 Remote Files 的目录内容或文件缓存；收藏项存在，也不保证目标设备当前在线或路径仍存在。详见 [Remote Files](remote_files.md)。

### `external_tool_presets` — External Tools 参数预设

**前台对应：** External Tools 的命名参数预设，便于重复使用同一组运行/安装参数。

| 字段 | 含义、前台作用 |
| --- | --- |
| `preset_id`（PK） | 预设的唯一标识。 |
| `tool_id` | 预设所属的工具身份。 |
| `name` | 用户设置的预设名称；同一工具内不区分大小写地唯一。 |
| `params_json` | 预设中保存的参数对象。 |
| `created_at` | 创建时间。 |
| `updated_at` | 修改时间。 |

本表不存放 External Tool 的可执行文件、安装包、实例进程或完整运行日志；那些使用独立的文件目录和 Client 运行环境。此表也没有 `machine_id` 列，因此预设的归属是**工具**，不是特定设备。详见 [External Tools](external_tools.md)。

## Background Jobs

这三张表共享 `job_id`，但用途不同：`background_jobs` 保存一次 Job 的基本事实与状态；`background_job_messages` 保存该 Job 的输出消息；`background_job_files` 保存该 Job 关联的 Artifact 引用。前台 Job 列表不必每次加载所有消息和文件明细。

### `background_jobs` — Job 运行实例

**前台对应：** Background Jobs 的实例列表、运行状态、启动/结束时间及详情页的基础信息。

| 字段 | 含义、前台作用 |
| --- | --- |
| `job_id`（PK） | 一次 Job 运行实例的唯一 ID，不是 Python 模块文件名。 |
| `machine_id`、`client_id` | 执行设备与 Client 实例；历史按机器归属，并保留实际上报的实例标识。 |
| `hostname`、`addr` | 执行时关联的主机名和地址信息。 |
| `job_name`、`job_key` | Job 名称与用于识别资源的键。 |
| `thread_name` | 运行线程名称等实例信息。 |
| `command_id` | 与命令/任务关联的可选标识，允许为 `NULL`。 |
| `execution_mode` | 执行方式（例如进程内或子进程）。 |
| `state` | Job 当前/最终状态，驱动列表状态显示。 |
| `created_at`、`started_at`、`updated_at`、`finished_at` | 记录创建、开始、更新和结束时间；未开始或未结束时可能为空。 |
| `params_json` | 创建 Job 时的参数对象；源码由独立的 Job 模块文件管理。 |

消息数、文件数和显示摘要从关联记录产生。Job 的历史状态由持久化记录提供，Server 重启后会按恢复规则处理尚处于运行状态的任务。

### `background_job_messages` — Job 消息/输出

**前台对应：** Background Jobs 实例详情中的输出记录、消息流和终止标记。

| 字段 | 含义、前台作用 |
| --- | --- |
| `message_id`（自增 PK） | 每条消息的本地递增序号；用于稳定排序/增量读取。 |
| `job_id` | 关联 `background_jobs.job_id`。 |
| `status` | 消息附带的状态码，用于结果/输出展示。 |
| `text` | 该条输出的文本内容。 |
| `eof` | 是否带有输出结束标记（`0/1`）。 |
| `created_at` | 消息记录的时间。 |

### `background_job_files` — Job 文件关联

**前台对应：** Background Jobs 详情中的生成文件列表及可用下载/预览入口。

| 字段 | 含义、前台作用 |
| --- | --- |
| `association_id`（自增 PK） | Job 与文件关联记录的唯一 ID。 |
| `job_id` | 关联 `background_jobs.job_id`。 |
| `artifact_id` | 被引用的 Artifact 标识；不是存储在 `rch.db` 的文件二进制数据。 |
| `created_at` | 文件关联记录时间。 |
| `snapshot_json` | 文件描述快照，例如原始名称、相对路径、大小及展示链接等；即使 Artifact 注册信息被清理，仍可保留部分历史显示信息。 |

两张子表对 `background_jobs` 都有外键并设置 **`ON DELETE CASCADE`**；删除 Job 主记录会删除关联的消息和文件引用。Artifact 文件与注册元数据位于独立存储，删除本表的文件引用仍会保留 Artifact 实体。详见 [Background Jobs](background_jobs.md) 和 [Artifacts](artifacts.md)。

## 数据库管理表

### `schema_migrations` — 结构初始化记录

**前台对应：无。** 此表供 Server 判断数据库结构是否已初始化到可识别状态，不属于业务记录。

| 字段 | 含义 |
| --- | --- |
| `version`（PK） | 已应用的数据库结构编号。 |
| `applied_at` | 该结构记录的应用时间。 |

`schema_migrations` 记录基础结构的初始化进度。部分业务表由各自模块初始化，因此检查完整表结构可使用 `sqlite_master` 或 `PRAGMA table_info`。

## 表之间如何关联

```text
一台设备 machine_id
├─ recent_devices           设备最近状态、别名、排序、隐藏
├─ connection_sessions      + client_id → 连接历史
├─ device_group_members     → device_groups → 分组名称
├─ command_recents          + command → Quick Recent
├─ pinned_commands          + command → Quick Pins
├─ activity_records         + activity_id → Activity Center
├─ pinned_paths             + display_name → 收藏路径
└─ background_jobs          + job_id → Job 实例
   ├─ background_job_messages → Job 输出
   └─ background_job_files    → Artifact 引用

Server 全局
├─ notifications            通知历史
├─ settings                 工具栏和通知偏好
├─ external_tool_presets    工具参数预设
├─ schema_migrations        数据库结构状态
└─ command_executions       仍保留的旧执行表（非现行 Activity 来源）
```

上述缩进表示**业务关联**，并不都对应 SQLite `FOREIGN KEY`：明确设有外键级联的只有 `device_group_members.group_id`，以及两个 Job 子表的 `job_id`。其他按 `machine_id`、`client_id`、`artifact_id` 的关联主要由业务服务维护；删除父侧记录时不要假设 SQLite 会自动清理所有关联数据。

## 查看、校验与备份

### 只读查看

建议在 Server 不忙时查看数据库，且**不要用 SQL 手动修改记录来代替前台功能操作**。如果本机安装了 `sqlite3` 命令行工具，在 `backend/` 目录可以执行：

```bash
sqlite3 -readonly runtime/rch.db '.tables'
sqlite3 -readonly runtime/rch.db 'PRAGMA table_info(activity_records);'
sqlite3 -readonly runtime/rch.db 'SELECT namespace, updated_at_ms FROM settings;'
sqlite3 -readonly runtime/rch.db 'SELECT type, COUNT(*) FROM notifications GROUP BY type;'
```

使用自定义 Runtime 目录时将 `runtime/rch.db` 替换为真实路径。`PRAGMA table_info(...)` 会列出类型、默认值和主键位置；也可以按表名查看其他 15 张表。SQL 查询示例刻意不打印命令文本、JSON 参数、通知正文等可能包含敏感信息的内容。

### 备份与完整性

RCH 使用 SQLite 的 WAL 模式。运行期间可能同时出现 `rch.db`、`rch.db-wal`、`rch.db-shm`；**不要只在 Server 运行中复制单独的 `rch.db` 就认为取得了一致备份**。更安全的方式是使用 SQLite 的在线 Backup 功能，或在停止 Server 后按一致性要求备份完整 Runtime 数据。

```bash
sqlite3 runtime/rch.db '.backup /path/to/backup/rch.db'
sqlite3 -readonly runtime/rch.db 'PRAGMA integrity_check;'
```

确保备份目标目录预先存在且可写；第二条正常应返回 `ok`。如果没有安装 sqlite3 CLI，可以使用支持 SQLite 在线备份的数据库管理工具。需要完整恢复 RCH 时，还应另行备份 `auth.json`、Artifacts、Documents、Keychains、Agent 构建产物等数据；仅恢复 `rch.db` **无法找回这些文件**。

### 常见误解与数据保护

| 现象或疑问 | 应如何理解 |
| --- | --- |
| 登录后 Connections 仍有离线设备 | `recent_devices` 持久保留最近设备，不是当前 Socket 的实时清单。 |
| Quick History 清空了，Pin 还在 | `command_recents` 和 `pinned_commands` 是独立表。 |
| Activity 列表为空，但数据库有 `command_executions` | 当前 Activity 读 `activity_records`；旧表不是它的自动数据源。 |
| 设备下线后 Connection History 仍可查看 | `connection_sessions` 保存连接生命周期快照。 |
| Notifications 被清空，通知开关仍保留 | `notifications` 与 `settings.notification_preferences` 相互独立。 |
| 删除 Job 的文件关联后磁盘空间没有变化 | `background_job_files` 存的是 Artifact 引用，不是 Artifact 实体文件。 |
| 按机器删除一条记录，其他表的数据还在 | 大部分跨表机器关联不是数据库级联外键，必须按相应业务清理规则操作。 |
| 新数据库里找不到 `activity_records` | 该表是在 History 模块初始化时创建，单独创建基础 SQLite 文件不一定包含它。 |

数据库里可能包含命令文本、传输路径、Job 参数、连接快照以及通知上下文，**应按敏感运行数据保护**。不要把完整 `rch.db`、SQL 导出或包含真实凭据的查询结果直接发到公开渠道。清理范围和自动清理行为详见 [Cleanup](cleanup.md)；相关日志不在这张数据库中，见 [Logging](logging.md)。
