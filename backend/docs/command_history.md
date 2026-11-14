# Activity Center / Quick History

Activity Center 与 Quick History 服务不同目的：前者保留**实际向 Client 提交的操作事实及结果**，后者保存手动终端命令的最近一次执行状态，失败命令也可以重试；Pinned Commands 是独立的用户收藏。它们共享 `machine_id` 设备作用域，但 Activity 的删除不重建或覆盖 Quick Recent。Activity 存储是当前活动事实的唯一数据源。

## Activity 的统一协调边界

Activity 只有一个生命周期所有者：`ActivityCoordinator`，负责操作意图、Client 实际派发确认、持久化、结果写入及最终状态。唯一的持久化实现仍为 `HistoryWriteService`，Quick History 与 Pin 保持独立。Control 的 `kind` 直接使用协议 Domain，`action` 使用协议 Action；其他生命周期保留各自操作类型。展示摘要由 Activity 投影统一构建。

系统只通过**两种事件适配方式**接入：

- `CommandDispatchAdapter`：普通命令、Alias、全部 Control Domain 及尚未迁移的 External Tool。Control 记录资格来自 Action 的 ActivityPolicy，业务入口只提供必要展示元数据，通用命令通道在消息成功交付传输层后确认派发；最终 Result/EOF 结束记录。
- `LifecycleAdapter`：PTY、Screen View、Transfer，以及已登记 Artifact 对当前命令的关联。监听明确的 Session/Request/Transfer ID 和 Client 回执；早到回执、重复 Close、断线和超时仅更新原有 Activity。文件上传在 Browser→Server 暂存阶段不记 Activity，Client 转交确认后才创建。

Application 装配层提供语义绑定，API 负责转发业务请求，业务会话服务负责运行状态，Client 传输层只负责发送和接收。**这些层不负责创建或结束 Activity，也不持有历史 ID 状态机**。Activity 记录失败不可反向阻断已经有效的业务操作；未发生 Client 派发的操作不得生成持久记录。Server 重启后遗留的 `running` Activity 统一结束为 `interrupted`，不建立额外表或协议兼容层。

## 一次操作如何进入 Activity

Server 接收请求时保留原始调用身份，解析 Server Builtin、Alias、History Replay 或 Script Library，得到真实远程执行计划。纯 Server 查询如 `rtt`、`history` 列表、`alias list`、无参数 `script`（等同 `script list`）、参数校验失败，都**不会**生成 Activity。只有显式可记录的操作已实际交给 Client 命令通道，发送成功后才创建持久记录；发送前允许分配内部关联 ID，以便结果输出、取消和 Artifact 归属，不代表已经执行或持久化。

记录类型包括 `command`、`alias`、`transfer`、`external_tool`、`pty`、`screen_view` 与所有 Control Domain（`script`、`remote_files`、`job`、`clipboard`、`configuration`、`process`、`watchdog`）。Control Action 默认 ALWAYS 记录；OPTIONAL 由 Server 设置决定（默认关闭）。文件传输仍归 `transfer`，Job 运行事件及监控采样不是独立 Control 请求。未知普通 Client 命令落到 Shell 的原有设计保持不变。

同一用户操作至多记一条 Activity：`notify shell pwd`、`saveout shell pwd` 以 `invocation.command` 保留外部调用文本，`resolved` 保留真正下发的 Client 命令。`history run N` 和 `!N` 不写入 Quick，但只要回放实际向 Client 派发了命令，就创建一条 Activity：`invocation.command` 保留外层回放写法，`resolved` 保留实际派发的命令类型和内容。未成功派发则不落 Activity。Alias 保留原始命令（UI 调用不填写 Invocation），原有 Alias 名称保留在展示摘要。Script Library、`script exec <file>` 都是 `kind=script`，实际下发 `control(domain=script, action=run)`；Resolved 保存完整实际下发请求，包括脚本源码。

Remote Files 的修改操作使用 `kind=remote_files`，统一记录为 `create_directory`、`delete_paths`、`rename_path`、`paste_paths`、`create_archive`、`extract_archive`、`save_file`。每次用户操作（包括批量处理）只创建一条 Activity。UI 调用的 Invocation 为空；Resolved 保存实际下发的完整请求，包括路径及保存正文。批量任务的 Client 终态明确表达失败事实，结构化报告保留成功数与失败项；部分成功或全部失败为 `error`，并在输出中保留数量和失败原因。 `inspect` 是调用参数，遵循所属 Action 的记录策略，不在记录层特判。

### Transfer 操作记录

用户主动发起的 Remote Files Upload、Remote File Picker Upload、Remote Files 文件/ZIP Download、Clipboard 远程文件/目录 Download 及终端 Server Builtin `upload`，使用 `kind=transfer`、`action=upload_files|download_files`；入口身份保存在 `origin`。单个受管理 `transfer_id` 只创建一条 Activity；Output Records 只存可见完成说明，临时调试用的 `result_events` 保留 `started`、按十个百分点节流的 `progress` 和唯一 `completed`，并受现有记录大小上限约束。文件字节仍经专用 Transfer/HTTP 通道，`result_events` 只是 Activity 投影而非另一份文件传输。终态 `completed/failed/cancelled` 对应 `success/error/cancelled`。Browser 上传有 Browser→Server 和 Server→Client 两阶段，必须在 Client 完成写盘后才是 `success`。Server 重新启动时，旧的未完成 Transfer Activity 变为 `interrupted`，不假定传输成功。

终端 `upload` 是 Server Builtin；当真实 Transfer 建立时认领原终端提交的 Activity ID，不额外生成 Command Activity，并保留 Quick 最近命令。终端 `download` 是与 `screenshot` 相同的普通 Client 命令，按 `kind=command`、`action=invoke` 正常记录，保留实际派发、输出及 Artifact 关联；不会为了文件内容经 HTTP 上传而改变 Activity 类型或虚构 Transfer Center `transfer_id`。纯文件预览、内部 Job/Script 上传和浏览器下载已生成 Artifact 的 HTTP 请求不自动产生 Transfer Activity。

Transfer Activity 的 Resolved 保存实际下发的传输启动请求，Invocation 仅保存原始命令（UI 为空）。References 关联实际生成的 Server Artifact；文件本体仍由文件传输服务管理。清空 Transfer Center 的 Recent 与删除 Activity 相互独立。

### PTY、Screen View、Clipboard 与 Process 操作

PTY 和 Screen View 使用生命周期适配器；Clipboard 和 Process 使用 Control 请求适配器。均在真实派发后开始记录，业务服务不持有 Activity ID 或持久化事务。

PTY 与 Screen View 每个远端会话只记录一条 `kind=pty|screen_view, action=session` Activity。真正派发 Open 后创建记录，Client 的 `opened` 回执进入 Output Records，记录在会话期间保持 `running`；终止后的结果进入 Output Records，同一条记录写入 `finished_at` 和最终状态。主动 Close、自动关闭与 PTY 切换 Shell 都结束原会话；切换 Shell 会为新会话建立新 Activity，旧会话的结束原因是 `shell_switched`。进程自然退出、网络断开、服务端重启、启动失败分别依实际结果写入结束原因及 `success/interrupted/error`。WebSocket 自动清理、重复 Close 不增加第二条 Activity。键盘输入、Resize、帧、FPS/Quality、Screen Control 输入不产生独立记录。

Clipboard 的用户写入操作使用 `kind=clipboard` 与 `action=set`。实际格式、文本、文件信息等保存在完整的 Control 请求 Resolved 中。Server 确认已派发 Client 后开始记录，收到对应终态 Result 才完成；失败和超时保留对应状态。Capabilities、Get 使用 OPTIONAL 策略，默认不记录；Get 文件的实际传输仍使用既有 Transfer Activity。

Process Manager 主动终止单个进程或应用时使用 `kind=process, action=kill`，`target_type` 区分 Process/App，实际 PID 随请求保存在 Resolved；进程／应用名称用于原有展示摘要。独立 Control 请求的执行结果决定 `success/error`；执行协调层统一负责 Activity 的创建和收尾，Process 业务入口只下发 Kill。内部进程查询及普通 Terminal 命令仍按原记录规则执行，不额外生成 Process Activity。

### Activity Record 公共结构

```json
{
  "activity_id": "unique-id",
  "machine_id": "machine-id",
  "client_id": "client-id",
  "kind": "alias",
  "action": "invoke",
  "origin": "web_terminal",
  "presentation": "terminal",
  "status": "success",
  "invocation": {"command": "now"},
  "resolved": {"type": "command", "id": 1, "text": "pyexec import datetime;..."},
  "summary": "now",
  "result": {"output_records": []},
  "created_at": "2026-10-20T10:10:09+08:00",
  "started_at": "2026-10-20T10:10:09+08:00",
  "finished_at": "2026-10-20T10:10:10+08:00",
  "references": [],
  "files": []
}
```

字段与含义：`activity_id` 为对外唯一身份；`machine_id` 按设备聚合，`client_id` 区分连接实例；`kind` 为 `command|alias|script|remote_files|transfer|external_tool|job|pty|screen_view|clipboard|process|configuration|watchdog`；`action` 为 `command/alias:invoke`、`script:run`；`origin` 为 `web_terminal|web_ui|web_api|cli`；`presentation` 为 `dialog|terminal|inline|none`。实际 Web Terminal HTTP 请求按 `web_terminal` 标记，Web API 只有明确提供程序调用身份时才能标为 `web_api`，不能单凭 HTTP 传输认定。

`invocation.command` 是入口的原始命令；UI 直接操作的 Invocation 为 `{}`。`resolved` 保存实际发送的完整逻辑消息，发送成功后确认，不对字段进行业务裁剪或改写。`summary` 仅用于原有列表标题。`result.output_records` 保存过程输出及实际返回值，只有超过容量时才写入 `truncated=true`。`references` 保存明确的 Artifact、Job 关联；API 的 `files` 是从 Artifact References 得到的展示视图，供原有 Produced Files 使用。`task_id` 与输出所有权只用于内部运行时。

状态：`running`、`cancelling`、`success`、`error`、`cancelled`、`interrupted`、`timed_out`。运行中的任务收到 Cancel 请求后进入 `cancelling`，最终状态由执行结果决定；明确超时或连接中断可单独归类，不能把所有无法证明成功的情况都写成成功。将来 Job 可能使用 `stopping/stopped`，本版不接入。Script Cancel 只更新原 `run` Activity，不单独新增 Stop 记录。Errors 筛选匹配 `error/cancelled/interrupted/timed_out`。没有明确执行证据的 `pending` 只表示内部提交准备，不在“已派发后才持久化”的第一版中制造额外记录。

### 输出与 Artifact

单次 Activity 存储最多 **256 条**输出记录、**65,536 字符**。超额文本不继续保存，`result.truncated=true`；详情仍显示已保存的序号、状态、文本和时间。文件由 Client 命令 ID 回挂到对应 Activity；输出和 Artifact 的生命周期相互独立，因此历史中有文件引用不保证文件永久可下载。系统不会把命令输出和执行内容当作没有存储上限的审计日志。

## Quick History 与 Pin

Quick Recent 保存手动 **Web Terminal / CLI** 提交的命令，无论最终为 `success`、`error`、`cancelled`、`interrupted` 或 `timed_out`；失败的命令也可以重试。以 `machine_id + command` 去重，保留最近 100 条不同命令。最近一次完成结果的 `status` 与时间独立保存在 `command_recents`，每次完成增加 `use_count`（执行尝试数），**不依赖 Activity 存在，也不持有 Activity ID**。UI 的 Command 列显示最近一次状态图标，Last Used 仍隐藏。用户手动 Pin 的命令不因后续失败而删除。

不记录的操作在 `server/application/history/quick_history.py` 文件顶部统一声明：`history`/`history clear`/`history run N`/`!N`；Quick Action UI、Script Library UI、Web API、上传、Remote Files、Job、Process、External Tool 内部任务及其他内部任务；Script Library UI 的直接 Script Task（不产生手敲命令）。Replay 只从 Quick 解析命令，不更新 Quick；其真实 Client 派发则按正常执行规则生成 Activity。

Quick History 页面继续支持 Use、双击回填、Pin / Unpin、Pin Up / Down 和动态数字索引。**仅隐藏** Last Used 的 UI；Command 前显示状态图标，底层必要字段不删除。Use 将命令填入 Terminal 输入框，不会直接执行。

Pin 顺序由独立的 `pinned_commands` 表持久管理：Pinned 项优先显示，然后是排除重复项的 Recent；整体结果重排从 1 开始的索引。最新一次 Pin 不受 Recent 的 100 条容量限制。Quick History 的 Clear 只清空 Recent，不影响 Activity 或手动 Pin；删除单条 Activity 不修改 Quick / Pin。History 顶部 Refresh 和 Clear 按当前页签作用：Quick 仅刷新/清理 Quick Recent，搜索时只清理命令文本匹配搜索词的 Recent，Pinned Commands 始终保留；Activity Center 仅刷新/清理 Activity，并使用页面的类型、Errors、搜索词筛选条件确定批量清理范围。确认时须明确显示本次删除范围。

## 回放与 Server 命令边界

`history` 和 `history clear` 是只读/清理 Quick 的纯 Server 命令，不记 Activity 或 Quick；`history` 的可回放索引使用 Quick History 快照并跳过 `history run N` / `!N` 元命令，重新从 1 编号；`history run <index>` / `!<index>` 会根据当前机器 Quick History 的动态索引查找真实可执行文本，再按照正常命令解析和 Client 派发链执行。索引随 Pin 排序、Recent 变化而变动，不是稳定 ID，重放前应核对列表。Replay 不产生 Quick；真实派发且符合记录策略的 Client 执行才产生 Activity，所以回放自身不改变 Quick 索引。未派发或纯 Server 回放不生成 Activity。

`xt` 仍由 Server Builtin 解析、Client 负责本地运行 Exec。`xt`、`xt help`、`xt exec list`（包括 JSON 查询）属于查询，不写 Activity；手动终端输入正常进入 Quick，即使 Server 内部向 Client 查询安装状态或可执行文件路径也不会产生 Activity。`xt package install/uninstall` 与 `xt instance create/start/stop/restart` 在真正派发相应 Client 修改命令后，分别记录一条 `external_tool` 语义 Activity；预检状态查询、未派发的参数错误和已安装／已运行等无变化的请求不落 Activity。`restart` 和 `create --start` 的内部多条修改命令仍归于同一次外层操作；`xt package/module/instance` 的只读列表、状态及日志查询不落 Activity。`xt exec <exec>` 真正派发执行后生成一条 `external_tool · run_exec` Activity；保留终端原始输入、Exec/Package 身份和实际结果，Quick 按普通终端执行规则记录。嵌套的 `external_tool_*` Client RPC 不会独立建 Activity，也不能覆盖外层的语义记录，实际派发消息保存在 Resolved。History 回放查询同样不记录 Activity、且不会重复写 Quick；回放执行仍记一条 `run_exec` Activity 而不重复写 Quick。

`notify`、`saveout` 等 Server 包装命令如果执行了 Client 子命令，只产生一条 Activity，外层包装文本留在 `invocation.command`，实际命令留在 `resolved`。`saveout` 在内层命令完成并成功注册 `command_output` Artifact 后，会沿用原有 History Store 文件关联方法，把 Artifact 引用加到该 Activity 的 References；不复制文件内容，也不凭文件存在推断执行成功。`script exec <name>` 由 Server 读取 Script 文件并向 Client 下发 `control(domain=script, action=run)`，不是普通 `command`。`rtt`、Alias 定义列表、脚本目录浏览等未下发 Client 的 Server 操作不记录。

## 查询、删除和界面

Activity Center 保留原有两行式列表，第一行 Lucide 类型图标、`Kind · 实际操作摘要`、状态图标（长命令单行省略），第二行日期时间与必要的计算摘要（成功执行优先使用 `completed` 事件对应的可见输出：非空、单行且不超过 256 字符时展示原文；多行或超过 256 字符时显示 `Completed`；没有原始 Result 事件的活动沿用 Output Records 的摘要回退。失败、取消、超时和中断继续按原有状态与摘要规则显示 `Failed` 或对应的取消/超时/中断文案，完整内容仍在 Output Records）；右侧箭头或整行打开原 Details。列表不提供 Use 或 Delete；Delete 按钮在 Details 中。History 对话框标题仍为 `History`，第二个页签命名 `Activity Center`。Details 标题固定为 `Activity Detail`，不在标题右侧附加命令名字。Details 将 Kind 与 Action 合为单张 `Action` 卡片，内容为 `kind · action`；Invocation、Resolved 卡片单行省略，点击后弹窗查看完整值，原始命令文本不截断；Activity 过滤栏固定、列表独立滚动。原有输出记录排序、文件预览/下载和删除确认保留。类型筛选包括所有 Control Domain 及 Command / Alias / Transfer / External Tool / PTY / Screen View；Errors 筛选使用 Server 端过滤，并和 `limit/cursor/query` 一起作用于分页与 `total_count`。默认 50 条，最大 200 条；同一时间按 `activity_id` 继续稳定排序。

查询 API 沿用现有机器作用域路径，Activity 项目通过新 Schema 返回，不再返回旧 `entry_id`、`source`、`raw_command`、顶层 `output_records/output_summary/output_truncated`。客户端关联执行所需的临时 ID 不属于公开记录。

## 归档范围和其他收藏数据

### 记录策略所覆盖的执行

Control 的记录依据为 Action 目录的 ActivityPolicy 与实际派发事实。未迁移的 External Tool 继续沿用原有语义适配器、预检及查询规则（见上文 xt 章节）；Job CLI 和 Web Manager 使用 `kind=job`、实际协议 Action。Stop All 保留批量计数；Start 完成后，Job 自身的运行和退出仍由 Job History 负责。Script SDK 的内部调用归属于外层 Script。

### 命令收藏与路径收藏

项目也支持在 Remote Files 中保存常用目录，但它与命令 Pin 是两套数据。

| | Pinned Commands | Pinned Paths |
|---|---|---|
| 收藏对象 | 命令文本 | 远程目录路径及显示名称 |
| 数据存储 | `pinned_commands` | `pinned_paths` |
| 主要入口 | Command History | Remote Files / Quick Jump |
| 用法 | Use、Replay、排序 | 目录跳转、`gopin` |

例如：

```text
gopin logs
```

如果 Remote Files 中已经保存显示名称为 `logs` 的 Pinned Path，该命令可以切换到对应目录。将 `gopin logs` 本身 Pin 到 Command History，仅表示收藏这条命令，**不会自动创建名称为 `logs` 的路径映射**。

Machine Connection History、Recent Devices 和 Notification History 也分别有自己的数据模型及管理目的，不属于 Activity Center、Quick Recent 与 Pin 三套记录。

## API 以及历史数据的安全边界

Activity Center / Quick History 的 Web API 以机器 ID 为范围，并使用 Web 的常规身份验证。主要接口如下：

| 方法 | 接口 | 行为 |
|---|---|---|
| GET | `/api/machines/{machine_id}/command-history` | 读取合并 Pin 和 Recent 的 Quick History |
| GET | `/api/machines/{machine_id}/command-history/full` | 查询 Activity，支持 `limit`、`cursor`、`query`、`kind`、`errors` |
| POST | `/api/machines/{machine_id}/command-history/pin` | Pin / Unpin 命令 |
| POST | `/api/machines/{machine_id}/command-history/pin/move` | 按 `up` / `down` 调整 Pin 顺序 |
| DELETE | `/api/machines/{machine_id}/command-history/full/{activity_id}` | 删除指定 Activity |
| DELETE | `/api/machines/{machine_id}/command-history/full` | 按 `kind`、`errors`、`query` 清理符合条件的 Activity；无筛选时清空该机器全部 Activity，不改变 Quick 和 Pin |
| DELETE | `/api/machines/{machine_id}/command-history` | 仅清理该机器的 Quick Recent，可选 `query` 只清理命令包含搜索词的 Recent；不影响 Activity 与 Pin |

例如，读取 Activity Center 时，可以使用：

```http
GET /api/machines/{machine_id}/command-history/full?limit=50&kind=command&errors=true&query=shell
```

它返回最近同时匹配类型、错误状态和调用/派发文本 `shell` 的最多 50 条 Activity；若 `has_more=true`，下一次查询在保持同一个 `query` 的同时附带响应中的 `next_cursor`。

Pin 一条命令可以提交：

```http
POST /api/machines/{machine_id}/command-history/pin
Content-Type: application/json
```

```json
{
  "command": "shell echo hello",
  "is_pinned": true
}
```

这里提交的是命令文本本身，`is_pinned=false` 表示解除固定。接口返回 `changed` 表示本次是否真的改变了存储状态。调整顺序则提交 `command` 和 `direction`，例如 `"direction": "up"`，只有已固定命令可移动。

### 查询限制及诊断

| 现象 | 原因或处理方式 |
|---|---|
| 执行过命令，却没有 Activity | 先确认是否实际派发 Client，且属于当前 ActivityPolicy 启用的操作 |
| Quick 里没有旧命令 | 非终端或明确排除的操作不写 Recent，或已超过最近 100 条不同命令上限 |
| Quick 出现 Pin 但看不到之前输出 | Pin 只保存轻量快照，不复制完整 `output_records` |
| Clear 后仍看到部分命令 | Pinned Commands 独立保留 |
| `!2` 执行了意料之外的命令 | 动态索引因新执行或 Pin 排序发生变化 |
| 执行详情输出不完整 | 超出 256 段或 65,536 字符存储上限 |
| 详情中的文件不能下载 | 关联 Artifact 已不可用；历史只保存引用 |
| 切换 Client 后仍能看到历史 | 历史主要按 `machine_id` 归属 |
| 只能看到某台机器的历史 | Web History 查询按机器身份，而不是跨所有设备的全局列表 |

Activity Center 会保存原始命令、完整实际请求及受容量限制的执行输出，当前没有针对密码、Token 或其他敏感字符串的通用自动脱敏功能。避免直接把凭据拼进命令行；否则它们可能出现在历史、执行详情和其他可访问的命令记录中。

历史保留策略分别作用于 Quick Recent、Activity 输出和 Artifact：Recent 有数量上限，Activity 输出有大小限制，Artifact 文件按独立的文件生命周期管理。排障时分别检查相应记录与文件。


### Control Activity 记录策略

Control Action 定义同时声明 `ExecutionPolicy` 与 `ActivityPolicy`。`ALWAYS` 为默认，`OPTIONAL` 默认关闭；Server 配置 `RECORD_OPTIONAL_ACTIVITY = True` 开启所有可选查询的记录。配置查询、Job 状态、Watchdog 状态、Clipboard get 与 Remote Files 查询属于 OPTIONAL。混合 Action 的预检与实际执行沿用同一记录策略，`inspect` 仅作为操作参数展示。CLI set/watchdog 与对应 Control 操作使用相同身份和策略（原始命令同时保存在 Invocation 和独立 Quick History），Quick History 仍独立保存真实终端提交。

每次符合记录策略的实际派发 Control 请求使用自己的 Activity ID。请求观察器负责真实输出写入，Terminal 展示不重复写入；所有权是运行时协调信息。最终 Result 的 EOF、状态及结构化取消/超时原因决定最终状态。中间输出只影响展示。记录资格由 ActivityPolicy 决定，记录内容不再按业务筛选。External Tool 仍使用自身业务适配器。
