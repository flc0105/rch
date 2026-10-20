# Activity Center / Quick History

Activity Center 与 Quick History 服务不同目的：前者保留**实际向 Client 提交的操作事实及结果**，后者仅用于成功执行过的、可复现的用户命令；Pinned Commands 是独立的用户收藏。它们共享 `machine_id` 设备作用域，但 Activity 的删除不重建或覆盖 Quick Recent。现有旧 Execution History 不导入新的 Activity 存储，正式记录从空表开始；不保留双份运行时读写路径。

## 一次操作如何进入 Activity

Server 接收请求时保留原始调用身份，解析 Server Builtin、Alias、History Replay 或 Script Library，得到真实远程执行计划。纯 Server 查询如 `rtt`、`history` 列表、`alias list`、无参数 `exec`、参数校验失败，都**不会**生成 Activity。只有显式可记录的操作已实际交给 Client 命令通道，发送成功后才创建持久记录；发送前允许分配内部关联 ID，以便结果输出、取消和 Artifact 归属，不代表已经执行或持久化。

首批范围是 `command`、`alias`、`script`。Remote Files、Job、Process、External Tool、监控采样、上传、目录浏览及内部 RPC 暂不写 Activity。以后 Job 若接入，正常执行动作使用 `invoke`，停止沿用取消原活动的流程，不额外创建 `stop` Activity。未知普通 Client 命令落到 Shell 是 RCH 原有的**设计特性**，本轮不更改命令分发、解析或 Shell fallback。

同一用户操作只记一条 Activity：`history run 3`、`!3`、`notify shell pwd`、`saveout shell pwd` 以 `invocation.input` 保留外部调用文本，`resolved.command` 保留真正下发的 Client 命令。Alias 保留 Alias 名称/参数，而非把展开文本冒充用户输入。Script Library、`exec <file>` 都是 `kind=script`，实际下发的是脚本协议 `command_type=script`；Activity 不复制整段脚本源码或 Base64 载荷，也不伪造 Shell 命令。

### Activity Record 公共结构

```json
{
  "activity_id": "unique-id",
  "machine_id": "machine-id",
  "client_id": "client-id",
  "kind": "alias",
  "action": "invoke",
  "origin": "web_ui",
  "presentation": "dialog",
  "status": "success",
  "invocation": {"input": "now", "target": "now", "arguments": {}},
  "resolved": {"command_type": "command", "command": "pyexec_collect import datetime;..."},
  "result": {"truncated": false, "output_records": []},
  "created_at": "2026-10-20T10:10:09+08:00",
  "started_at": "2026-10-20T10:10:09+08:00",
  "finished_at": "2026-10-20T10:10:10+08:00",
  "files": []
}
```

字段与含义：`activity_id` 为对外唯一身份；`machine_id` 按设备聚合，`client_id` 区分连接实例；`kind` 为 `command|alias|script`；`action` 为 `command/alias:invoke`、`script:run`；`origin` 为 `web_terminal|web_ui|web_api|cli`；`presentation` 为 `dialog|terminal|inline|none`。实际 Web Terminal HTTP 请求按 `web_terminal` 标记，Web API 只有明确提供程序调用身份时才能标为 `web_api`，不能单凭 HTTP 传输认定。

`invocation.input` 是用户真实调用形式，`target` 是可选的 Alias 或 Script 业务身份，`arguments` 是结构化参数（普通 Shell 命令不做强行解析）；`resolved.command_type` 是实际派发类型；只在适合保存真实命令文本时提供 `resolved.command`。Script 实际源码属于执行传输，不复制到持久 Activity。`result` 只存 `truncated` 和原有 `output_records`，输出摘要从记录即时计算而非新增持久字段。`files` 仍是独立的 Artifact 引用数组。`task_id` 只用于内部运行时，不是 Activity 公共字段。

状态：`running`、`cancelling`、`success`、`error`、`cancelled`、`interrupted`、`timed_out`。运行中可通过既有任务 Cancel 请求进入 `cancelling`，但并不自动成为最终 `cancelled`；明确超时或连接中断可单独归类，不能把所有无法证明成功的情况都写成成功。将来 Job 可能使用 `stopping/stopped`，本版不接入。Script Cancel 只更新原 `run` Activity，不单独新增 Stop 记录。Errors 筛选匹配 `error/cancelled/interrupted/timed_out`。没有明确执行证据的 `pending` 只表示内部提交准备，不在“已派发后才持久化”的第一版中制造额外记录。

### 输出与 Artifact

单次 Activity 存储最多 **256 条**输出记录、**65,536 字符**。超额文本不继续保存，`result.truncated=true`；详情仍显示已保存的序号、状态、文本和时间。文件由 Client 命令 ID 回挂到对应 Activity；输出和 Artifact 的生命周期相互独立，因此历史中有文件引用不保证文件永久可下载。系统不会把命令输出和执行内容当作没有存储上限的审计日志。

## Quick History 与 Pin

Quick Recent 只记录**成功完成且适合重放**的手动 Web Terminal / CLI 命令。失败、取消、中断、超时，以及 Quick Action / Script Library UI 自动提交的结构化调用都不更新 Recent。相同 `machine_id + command` 去重，最多保留最近 100 条不同命令；重复成功增加 `use_count`，所以该计数表示成功重放/执行的次数，而不是所有尝试数。`history run N` 成功后更新被重放的真实命令（而不是文字 `history run N`）；`!N` 同理。用户手动 Pin 的命令不因之后一次失败而删除，也不依赖 Activity 是否存在。

Quick History 页面继续支持 Use、双击回填、Pin / Unpin、Pin Up / Down 和动态数字索引。**仅隐藏** Status 和 Last Used 的 UI，底层必要字段不删除。Use 将命令填入 Terminal 输入框，不会直接执行。

Pin 顺序由独立的 `pinned_commands` 表持久管理：Pinned 项优先显示，然后是排除重复项的 Recent；整体结果重排从 1 开始的索引。最新一次 Pin 不受 Recent 的 100 条容量限制。Quick History 的 Clear 同时清空 Activity 和 Recent，保留手动 Pin；删除单条 Activity 不修改 Quick / Pin。

## 回放与 Server 命令边界

`history` 和 `history clear` 是纯 Server 命令，不记 Activity；`history` 的可回放索引使用 Quick History 快照并跳过 `history run N` / `!N` 元命令，重新从 1 编号；`history run <index>` / `!<index>` 会根据当前机器 Quick History 的动态索引查找真实可执行文本，再按照正常命令解析和 Client 派发链执行。索引随 Pin 排序、Recent 变化而变动，不是稳定 ID，重放前应核对列表。重放的外层 `invocation.input` 保留原文，`resolved.command` 保留实际发出的命令，类型由实际计划决定。

`notify`、`saveout` 等 Server 包装命令如果执行了 Client 子命令，只产生一条 Activity，外层包装文本留在 `invocation.input`，实际命令留在 `resolved.command`。`exec <name>` 由 Server 读取 Script 文件并向 Client 下发 Script 类型，不是普通 `command`。`rtt`、Alias 定义列表、脚本目录浏览等未下发 Client 的 Server 操作不记录。

## 查询、删除和界面

Activity Center 保留原有两行式列表，第一行 Lucide 类型图标、`Kind · 实际操作摘要`、状态图标（长命令单行省略），第二行日期时间与必要的计算摘要；右侧箭头或整行打开原 Details。列表不提供 Use 或 Delete；Delete 按钮在 Details 中。Details 的 Kind 与 Action 独立显示单词标签；Invocation、Resolved 卡片单行省略，点击后弹窗查看完整值，原始命令文本不截断；Activity 过滤栏固定、列表独立滚动。原有输出记录排序、文件预览/下载和删除确认保留。类型筛选为 All / Command / Alias / Script；Errors 筛选使用 Server 端过滤，并和 `limit/cursor/query` 一起作用于分页与 `total_count`。默认 50 条，最大 200 条；同一时间按 `activity_id` 继续稳定排序。

查询 API 沿用现有机器作用域路径，Activity 项目通过新 Schema 返回，不再返回旧 `entry_id`、`source`、`raw_command`、顶层 `output_records/output_summary/output_truncated`。客户端关联执行所需的临时 ID 不属于公开记录。

## 归档范围和其他收藏数据

### 记录策略所覆盖的执行

统一 Activity 写入依据是显式受支持的用户操作上下文 + 真实向 Client 派发，而不是字符串黑名单。纯 Server 管理、目录浏览、Remote Files、Job/Process Control 及内部监控均不在第一版。不是所有业务请求都会有 Activity，因此缺少 Activity 不代表客户端从未接受某次内部请求。

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
| DELETE | `/api/machines/{machine_id}/command-history` | 清空该机器的 Activity 和 Recent，保留 Pin |

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
| 执行过命令，却没有 Activity | 先确认是否实际派发 Client，且属于首批三类可记录操作 |
| Quick 里没有旧命令 | 失败执行不写入 Recent，或已超过最近 100 条不同命令上限 |
| Quick 出现 Pin 但看不到之前输出 | Pin 只保存轻量快照，不复制完整 `output_records` |
| Clear 后仍看到部分命令 | Pinned Commands 独立保留 |
| `!2` 执行了意料之外的命令 | 动态索引因新执行或 Pin 排序发生变化 |
| 执行详情输出不完整 | 超出 256 段或 65,536 字符存储上限 |
| 详情中的文件不能下载 | 关联 Artifact 已不可用；历史只保存引用 |
| 切换 Client 后仍能看到历史 | 历史主要按 `machine_id` 归属 |
| 只能看到某台机器的历史 | Web History 查询按机器身份，而不是跨所有设备的全局列表 |

Activity Center 会保存调用文本、可记录的实际命令及部分执行输出，当前没有针对密码、Token 或其他敏感字符串的通用自动脱敏功能。避免直接把凭据拼进命令行；否则它们可能出现在历史、执行详情和其他可访问的命令记录中。

历史记录的持久化不等于命令输出和关联文件会永久完整可用。Recent 有数量上限，Activity 的输出明细有大小上限，Artifact 另有自己的生命周期；排查问题时应分别核对这三者。
