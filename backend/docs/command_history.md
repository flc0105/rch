# Command History

Command History 连接命令输入、执行生命周期与长期复用。Server 为受记录策略覆盖的执行建立独立条目，保存受限的输出和文件引用；Quick History 在这些记录上提供按命令去重的近期视图；Pinned Commands 则以另一份持久记录保留用户明确收藏的命令及排序。

Web 输入框回填和终端重放是两个不同的操作：前者仅供修改后提交，后者通过当前索引重新进入执行链。历史按设备身份归属，因此同一机器重新连接并不清空记录，但执行输出、临时 Artifact 与收藏快照仍各有独立的保存边界。

## 一次命令如何进入历史系统

系统把命令历史分成三个彼此关联但独立存储的部分：

| 部分 | 保存内容 | 主要用途 | 保留规则 |
|---|---|---|---|
| **Execution History** | 每次被记录的命令执行、生命周期、有限输出、文件引用 | 查看运行过程与执行结果 | 不按命令去重；需明确删除或清空 |
| **Quick History / Recent** | 每条不同命令的最新执行及使用统计 | 快速查找、回填、重放 | 按 `machine_id + command` 去重，每台机器最近 100 条不同命令 |
| **Pinned Commands** | 固定命令、手动排序和轻量执行快照 | 长期保留常用命令 | 独立存储，不受 Recent 100 条限制；Clear History 不删除 Pin |

```text
Web Terminal / Server CLI
        │ 用户提交命令
        ▼
命令历史记录策略
        │ 符合记录条件
        ├──→ Execution History：建立一次独立执行记录
        │         │ 追加输出、状态、Artifact 引用
        │         ▼
        └──→ Quick History：更新该命令的最近使用记录
                  ▲
                  │ 展示时合并（而非同一张表）
          Pinned Commands：固定顺序、独立快照
```

开始执行时，Server 根据集中记录策略判断是否建立历史条目。被记录的命令会生成 `entry_id`，先以 `running` 状态写入 Execution History，同时更新对应 Recent；执行过程中的输出、关联文件和最终状态继续更新该条执行记录。

**不是项目内部的每一次操作都会进入 Command History。** 远程文件操作、某些任务控制和内部结构化命令会被记录策略过滤。因此这里所说的 Execution History，是对*已纳入记录范围的命令执行*逐次保留明细，不是全系统所有操作的审计日志。

### 设备归属与连接身份

`machine_id` 标识设备，Quick History、Pinned Commands 和历史查询均以它为主要范围。Execution History 还保留 `client_id`、主机名和连接地址，用于识别一次执行所使用的具体 Client 实例。相同 `machine_id` 下的不同 Client 连接会共享历史视图，但各条执行记录仍能区分来自哪个连接。

`command` 是当前执行对应的实际命令文本；`raw_command` 保存该执行最初提交的命令形式。两者通常一致，在 History Replay 等特殊操作里可能不同。

## 近期复用与固定收藏的存储

### 近期命令如何去重

Quick History 按命令文本去重，而不是按执行次数列出所有重复项。例如顺序执行：

```text
shell echo hello
shell pwd
shell echo hello
```

Execution History 会新增三条不同的执行记录；Quick History 则保留两条不同命令，最近再次运行的 `shell echo hello` 排在较前位置。

Recent 中保存最后一次执行的 `last_entry_id`、最后使用时间 `last_used_at`、`use_count` 和最新执行快照。当同一命令再次运行，使用次数增加，并将 Recent 指向新的执行。Recent 达到 100 条不同命令后，最早使用的条目会被裁剪，**不会因此删除对应的 Execution History**。

Quick History 会优先展示 Pinned Commands，再展示没有被 Pin 的 Recent。Pinned 命令会从普通 Recent 展示部分去重，避免同一个命令出现两次。整个结果统一分配从 1 开始的动态 `index`，供 History Replay 使用。

### 收藏引用的排序和快照

在 Command History 的 Quick History 页签中，用户可以通过星形操作 Pin 或 Unpin 一条命令。已固定的命令可以使用 Move Up / Move Down 调整顺序；第一项不能继续上移，最后一项不能继续下移。

Pin 保存以下信息：

| 数据 | 作用 |
|---|---|
| `command` | 收藏的命令文本 |
| `pinned_at` | 固定时间 |
| `pin_order` | 用户定义的展示顺序 |
| `snapshot` | 固定时关联执行的部分状态、工作目录、输出统计和文件引用 |

Pin 不会复制完整的 `output_records`。展示固定命令时，如果存在该命令的最新 Execution 记录，优先使用其状态与统计；没有对应执行记录时，才使用固定时保留的快照。因此清空历史后 Pin 仍可见，但以前的完整执行输出不再存在。

Pinned Commands 的存储不依赖 Recent 的 100 条限制。Unpin 只解除收藏，**不删除该命令的历史执行记录**。如果命令还在 Recent 中，它可以继续作为普通最近命令显示；如果早已超出 Recent 上限，Unpin 后就可能不再出现在 Quick History。

## 独立执行条目的形成

Execution History 为每次纳入记录策略的执行分配独立 `entry_id`，相同命令多次执行也各自保存。一次记录的大致生命周期如下：

1. 创建记录：写入命令文本、来源、机器与连接身份、初始工作目录，状态为 `running`。
2. 执行期间：逐次追加输出片段，更新输出计数和更新时间；产生关联 Artifact 时保存文件引用。
3. 执行完成：根据实际结果将状态设为 `success` 或 `error`，保存结束时间及最终工作目录。
4. 历史查询：返回这些字段，同时重新判断相关文件当前是否仍可用。

以下仅展示常用字段，实际返回对象还包含其他统计与生命周期时间：

```json
{
  "entry_id": "example-entry-id",
  "machine_id": "example-machine-id",
  "client_id": "example-client-id",
  "command": "shell echo hello",
  "raw_command": "shell echo hello",
  "source": "web",
  "status": "success",
  "created_at": "<record-created-at>",
  "started_at": "<record-started-at>",
  "finished_at": "<record-finished-at>",
  "cwd_start": "/home/user",
  "cwd_end": "/home/user",
  "output_chunk_count": 1,
  "output_line_count": 1,
  "output_char_count": 5,
  "output_truncated": false,
  "output_records": [
    {"seq": 1, "status": 1, "text": "hello", "eof": 1, "created_at": "<chunk-created-at>"}
  ],
  "files": []
}
```

这些时间字段由 Server 在写记录时产生，不应将没有时区偏移的时间文本自动理解为浏览器或 Client 所在时区。

### 分段输出记录及截断

每个 `output_records` 条目都保留片段序号 `seq`、片段状态 `status`、文本 `text`、结束标记 `eof` 和时间 `created_at`。执行级别还汇总输出片段数、文本字符数和行数，供详情页展示。

单次执行的输出明细保存上限是 **256 段、65,536 个字符**。达到上限后，系统不再完整保留超额文本，但继续增加输出统计；记录会标记 `output_truncated=true`。空文本的 EOF 消息可以计入输出统计，但不会为它单独保存一条空文本记录。

因此执行详情可能显示一条执行已经完成、统计输出很多，但历史中只能看到前面保存的部分内容。**Execution History 不是无限容量的终端输出归档。** Quick History 进一步只展示简短摘要，而不返回完整输出片段。

### 文件关联与资产状态

命令执行期间上传到 Server 的 Artifact 可以借助执行 `command_id` 与对应 History `entry_id` 的绑定写入 `files`。History 记录的是文件引用与元数据，而不是把文件二进制内容放进 SQLite 的历史记录中。

详情窗口会展示相关文件，并按当前 Artifact 状态提供适用的 Preview 或 Download 操作。即使历史中仍有文件记录，Artifact 本体被清理、移动或不再可访问时，下载也可能失败。删除执行历史不会自动删除对应的 Artifact 本体。

## 从历史中恢复和重新执行

History 有两种不同的复用方式：**Web 界面的 Use 只回填命令，终端 Replay 则立即执行命令**。

### 输入框复用

在 Quick History 或 Execution History 选择 Use，或者通过对应的双击操作复用命令，界面会关闭历史窗口，将 `command` 填入 Terminal 输入框。用户可以修改文本，然后再手动提交；Use 本身不会启动新的执行。

这适合复用参数较长的命令，尤其是在再次运行前需要替换目标路径或其他值时。

### 命令重放的寻址语义

在选定 Client 的终端中输入：

```text
history
```

Server 会列出当前机器的 Quick History，每条命令带一个动态索引。要立即执行索引为 2 的命令，使用：

```text
history run 2
```

也可以使用简写：

```text
!2
```

两种方式都会找到索引对应的真实命令，并通过命令执行流程重新运行它。**Replay 不是预览，也不是仅把命令粘贴到输入框。**

索引受 Pin 顺序及 Recent 变化影响；执行新命令或调整固定顺序后，`2` 可能指向另一条命令。若对执行目标有严格要求，应先运行 `history` 核对列表，再按当前索引执行。

History Replay 本身属于允许记录的操作，但新建执行条目中的 `command` 会被改写为实际重放的命令，避免历史被重复的 `history run 2` 等元命令污染。`raw_command` 可保留最初提交的 Replay 文本，区分请求形式和真实执行内容。`history`、`history clear` 这类纯查询/管理命令则不会被当作普通执行写入历史。

终端补全也支持 `history` 及 `!<index>`，候选来自当前机器的 Quick History，而非固定的命令列表。索引同样只对当前状态有效。

## 查询视图与记录清理

Command History 对话框有 **Quick History** 和 **Execution History** 两个页签。Quick 适合搜索、固定和回填；Execution 适合查看每一次执行、打开输出详情及删除指定记录。

| 操作 | Quick History | Execution History |
|---|---|---|
| 按命令文本搜索 | 浏览器对已加载条目进行匹配 | Server 对历史记录查询 |
| Use（回填输入框） | 支持 | 支持 |
| Pin / Unpin / 调整顺序 | 支持 | 不在本页操作 |
| 查看执行输出与关联文件 | 只展示摘要与引用 | 支持详细记录 |
| 删除单条执行 | 不提供 | 支持 |
| 分页 | 最近条目一次加载 | Cursor 分页，支持 Load More |

Quick 的搜索是对当前加载的命令文本做不区分大小写的子字符串过滤。Execution 的搜索查询交给 Server，只根据命令文本匹配；当前没有完整的状态、来源或日期范围组合筛选。

Execution History 默认每次加载 **50 条**，API 最大允许 **200 条**。结果包含 `items`、`total_count`、`has_more`、`next_cursor`；按执行开始时间倒序排列，相同时间再用 `entry_id` 稳定排序。点击 Load More 会带着上次的 `next_cursor` 获取下一页，不是通过页号跳转。

### 历史清空与单项删除

不同操作的实际影响范围如下：

| 操作 | Execution History | 普通 Recent | Pinned Commands |
|---|---|---|---|
| 删除单条 Execution | 仅删除指定 `entry_id` | 为对应命令使用剩余最近执行重建；没有剩余执行时删除其 Recent | 不变 |
| Clear History | 清空该机器的全部 Execution | 同时清空 | **保留** |
| Unpin | 不变 | 不变 | 删除对应 Pin |

在 Web UI 执行 Clear 之前，会显示明确提示：当前设备的命令历史将被清空，但 Pinned Commands 保留。终端还可以运行：

```text
history clear
```

它清空当前机器的 Execution History 和 Recent，不清空 Pin。由于作用域是 `machine_id`，同一机器的多个 Client 连接实例对应的执行记录会一起受影响。

删除单条 Execution 只清理那条记录；系统会根据该命令剩余的执行重建最近状态。Pin 仍保留，因此 Quick History 可能继续显示该命令，但完整执行详情已不再可用。

**Clear / Delete 不负责清理相关 Artifact 文件**，而且清空操作本身没有一键撤销机制；操作前应确认选择的是正确的机器身份。

## 归档范围和其他收藏数据

### 记录策略所覆盖的执行

记录策略是统一的前置判断，不是直接把每一次 API 或 Client 消息都保存成用户命令。它会依据命令文本、命令类型和任务类型，过滤只服务于内部管理的操作。

例如 `history`、`history clear` 是不记录的历史元命令；`history run <index>` 和 `!<index>` 则需要保留这次真实的重新执行，但把执行条目关联到被重放的命令。以结构化 JSON 参数运行的某些内部命令、Remote Files、进程管理、Job 控制及特定文件传输任务也会被过滤。

这使执行历史更偏向用户有意发起的命令，而不是混入大量文件列表刷新、后台状态轮询或内部控制请求。因而**没有找到某项操作的 Execution History，不必然表示它没有运行**，还需考虑记录策略是否允许保存。

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

Machine Connection History、Recent Devices 和 Notification History 也分别有自己的数据模型及管理目的，不属于 Command History 的 Execution/Recent/Pin 三套记录。

## API 以及历史数据的安全边界

Command History 的 Web API 以机器 ID 为范围，并使用 Web 的常规身份验证。主要接口如下：

| 方法 | 接口 | 行为 |
|---|---|---|
| GET | `/api/machines/{machine_id}/command-history` | 读取合并 Pin 和 Recent 的 Quick History |
| GET | `/api/machines/{machine_id}/command-history/full` | 查询 Execution History，支持 `limit`、`cursor`、`query` |
| POST | `/api/machines/{machine_id}/command-history/pin` | Pin / Unpin 命令 |
| POST | `/api/machines/{machine_id}/command-history/pin/move` | 按 `up` / `down` 调整 Pin 顺序 |
| DELETE | `/api/machines/{machine_id}/command-history/full/{entry_id}` | 删除指定执行记录 |
| DELETE | `/api/machines/{machine_id}/command-history` | 清空该机器的 Execution 和 Recent，保留 Pin |

例如，读取 Execution History 时，可以使用：

```http
GET /api/machines/{machine_id}/command-history/full?limit=50&query=shell
```

它返回最近匹配命令文本中 `shell` 的 50 条执行记录；若 `has_more=true`，下一次查询在保持同一个 `query` 的同时附带响应中的 `next_cursor`。

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
| 执行过命令，却没有 History | 先检查是否属于集中记录策略过滤的操作 |
| Quick 里没有旧命令 | 可能超过最近 100 条不同命令的上限；Execution 记录可能仍在 |
| Quick 出现 Pin 但看不到之前输出 | Pin 只保存轻量快照，不复制完整 `output_records` |
| Clear 后仍看到部分命令 | Pinned Commands 独立保留 |
| `!2` 执行了意料之外的命令 | 动态索引因新执行或 Pin 排序发生变化 |
| 执行详情输出不完整 | 超出 256 段或 65,536 字符存储上限 |
| 详情中的文件不能下载 | 关联 Artifact 已不可用；历史只保存引用 |
| 切换 Client 后仍能看到历史 | 历史主要按 `machine_id` 归属 |
| 只能看到某台机器的历史 | Web History 查询按机器身份，而不是跨所有设备的全局列表 |

Command History 会保存命令文本及部分执行输出，当前没有针对密码、Token 或其他敏感字符串的通用自动脱敏功能。避免直接把凭据拼进命令行；否则它们可能出现在历史、执行详情和其他可访问的命令记录中。

历史记录的持久化不等于命令输出和关联文件会永久完整可用。Recent 有数量上限，Execution 的输出明细有大小上限，Artifact 另有自己的生命周期；排查问题时应分别核对这三者。
