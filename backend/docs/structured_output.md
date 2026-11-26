# Command Output Rendering

Server Builtin 与 Client ACMD 共享 Core 结构化结果渲染器：命令产生一次数据，终端按选定布局生成文本，或序列化完整 JSON。Web Terminal 接收到结果后，还可能从完整 JSON 中识别适合 Table、Flat 或 Raw 的查看方式。因此命令产出格式与浏览器显示模式处于不同层级。

Server Builtin 的展示格式由自身 Registry 声明。ACMD 的 `--format/-f/--json` 由 Client Registry 统一解析，实际结果的可用布局在 Client 内部校验。Client 返回本次结果的默认布局、可选的已选格式及必要字段映射，Server 统一渲染。Web JSON Viewer 独立选择交互视图。

## 命令返回值和终端展示的边界

```text
命令处理器（Client ACMD / Server Builtin）
          ↓
组织原生 data；ACMD 额外声明本次 Result 的 presentation
          ↓
Server 按 Result.presentation 调用 Core 布局或 JSON 序列化
          ↓
原始 Result 事件 + 本次可见文本 → 正常命令输出通道
          ↓
Web Terminal：显示输出、识别完整 JSON
          ↓
JSON Viewer：Table / Grouped / Flat / Raw
```

结构化结果解决的是**同一份数据如何输出为人类可读文本和可机器处理的 JSON**。例如进程信息可以默认显示为对齐的列，指定 JSON 输出时保留字段和数据类型，让调用方更方便地复制、保存或进一步处理。

Terminal JSON Rendering 是独立的展示层：浏览器检测输出是否为有效 JSON，提供查看操作，打开后依据 JSON 顶层类型选择适合的展示方式。它不反向改变 Client 命令的执行结果，也不为展示向 Server 请求另一份数据。仅当用户在 Table 中明确确认 Result Action 时，才通过原有命令接口提交该 Action 指定的命令。

## Control Result 的数据与调用方视图

Result Envelope 只描述执行事实，不包含 `display` 或 `shape`。Client/业务层的一份结构化 `data` 可以包含 Web 所需的完整业务字段；**终端调用方**明确选择 Message 或 Data，以及 Flat、Table、Grouped、Numbered List 等文本投影，公共 Renderer 负责排版。Terminal 文本布局仅选择可见列及显示方式，`--json` 总是输出终端查询投影的全部字段；Web 仍可消费完整 Control 数据。

| 终端调用方选择 | 默认 Text | `--json` |
|---|---|---|
| Message（操作反馈） | `message` | `{"status":"success/error","message":"..."}` |
| Data / Table（成功查询） | 同一份终端投影绘制表格 | 序列化该投影数组 |
| Data / Flat（成功查询） | Key / Value | 序列化该投影对象 |
| Data / Grouped（成功查询） | 分组标题和组内 Key / Value | 序列化该投影对象 |
| 失败 | 实际错误 `message` | `status` 与 `message` |

`job start/stop/stop_all` 默认选择 Message，`job ps/status` 分别选择 Table/Flat，`watchdog status` 选择 Grouped；`config list` 默认按配置分组展示；`--format kv` 只显示配置键 `key = value`（分组仅用于 `grouped` 视图）；`--format table` 查看四列数据。空列表是否代表业务失败，由业务状态决定，公共 Renderer 不擅自把 `[]` 判错。

Configuration GET 的 `data` 包含完整配置项（含 Web 编辑需要的描述、选项、类型、可编辑属性等）；Terminal 的 `config list` 和 `config list --json` 都只投影 `group/key/value/default` 四列。Web 直接消费 GET 结果而不用从 Terminal 文本中逆向解析字段；Client GET 不输出不再使用的附加字段。

Server 本地 Builtin 的单次查询/反馈（例如 Job 列表、Script 列表、History、Gopin、RTT、Help、HTTP Control、Saveout）保留 Result Envelope 作为原始事件，命令行同时得到相同的现有文本投影。组合执行和日志流（`history run`、`notify`、`script exec`、`job logs`）透传内部执行事件，由外层执行生命周期负责终态，不额外创建第二个业务完成结果。

`saveout`、`notify`、`history run`、`gopin go` 属于执行包装入口。`history run` 和 `gopin go` 的执行提示是 `chunk`，然后原样转发内层命令输出，内层唯一的 `completed` 决定结果。`notify` 以内层 `completed.status` 形成 Device Event（该通知与命令结果是不同通道），并原样转发命令事件。`saveout` 把内层可见文字保存为 `command_output` Artifact；显式结构化 `data` 且没有现成文字投影时按 JSON 保存。内层执行的最终结果决定 Artifact 元数据中的 `final_status` 和外层保存反馈的完成状态，中间 stderr 或进度不决定最终成功与否。未收到内层终态即结束的协议流标记为 `interrupted`。

普通 Shell-like 命令和 Script 的 `print()`、stdout/stderr 继续作为 `message` 的文本流，不依据文字是否恰似 JSON 进行协议层推断。Script SDK 的 `context.emit(data)` 是明确的结构化 `chunk`，可在文本 `chunk` 之间按原序穿插；这不意味着脚本结束。Activity Detail 的 Result 卡片展示实际收到的 Client Result 对象。Output Records 使用 Server 公共投影生成的可见文本；Activity Detail 额外提供与 Result 记录序号对齐的 `output_texts`，Result JSON 仍是原始 Client Result 事件，不因展示格式改变。活动状态和正文省略提示保存在 Activity 元信息中。

## Result 收集与终态

只有 `progress` 支持**可选**的 `level=info/success/warning/error`；不传则消息完全不加标记。公共 Server 文本投影对显式 level 的 progress 依次生成 `[*]/[+]/[!]/[-]`，并把相同的可见文本提供给 Terminal/RCH CLI/Activity Output Records。Result 原始事件的 `message` 不带生成的 Marker，`chunk`（Shell stdout/stderr、Script print、SDK emit）永远不进行 Marker 自动识别或插入；`completed.status` 是唯一执行终态，不由中间 progress 错误级别推断。

Client/Server Result 的 `event_type` 为 `started / progress / chunk / completed`。仅 `completed` 包含最终 `status`，取值为 `success / partial / error / cancelled / timed_out / interrupted`。Server 的按请求 ID 等待队列保存原始 Result 事件；收到 `completed` 后结束该请求，断线时由 Server 生成 `completed(status=interrupted)`。业务执行器若仍使用整数状态与文本视图，则在消费边界投影，不从中间输出决定最终状态。

同步收集器分别保留最终状态、可见文本和结构化 `data`。`chunk`、`progress`（包括 stderr 警告）可产生可见文字，但不能覆盖最终 `completed.status`。JSON 消费先读取最终事件的原始对象 `data`；普通文本命令可显式输出 JSON 文本（包括暂缓重构的 XT Client 命令），此类文本消费才进行 JSON 解析。结构化 Control 缺少 `data` 时不从格式化文本反推业务对象。

Web Terminal、独立 Result Dialog、Activity 与 RCH CLI 都采用明确的终态。`partial` 单独显示为 Partial；取消、超时和中断分别显示 Cancelled、Timed out、Interrupted。`success` 布尔值只表示完全成功，不能用它反推其他终态。CLI 对完全成功返回退出码 0、部分成功返回 2、取消返回 130，其余失败状态返回 1。

## 统一的文本布局与 JSON 输出

Server Builtin 的 `render_result_payload()` 和 ACMD 在 Server 端的结果呈现适配器共用 Core 布局引擎。ACMD 的 `StructuredCommandResult` 在 Client 端保留原生 `data` 及本次结果级 `presentation`；Shell-like 的既有文本投影仍由 Client 的 Runner 完成。原始数据字段、顺序与类型不会随文字布局变化。文本 Table/Records 默认展示原始业务字段（包括 `_id` 等下划线字段）；需要自定义列名时才声明 `columns`。Viewer 操作只由结果级 `view.actions` 定义。

Server Builtin 的允许格式由 Server Registry 声明；ACMD 的 `--format/-f/--json` 由 Client Registry 统一解析，再根据本次结构化结果内部的 `formats` 检查是否适用。Result Wire 不携带 `formats`，Server 根据 `presentation.requested/default` 渲染。Core Renderer 提供七种文本布局和一种 JSON 序列化格式：

| 布局/格式 | 必需数据和语义 | 不适用情况 |
|---|---|---|
| `lines` | 记录数组，并显式声明单行标识字段 | 没有可识别的显示字段 |
| `table` | 同字段的记录对象数组 | 单个对象，或无法形成一致列的记录 |
| `records` | 记录对象数组，每项逐字段展开 | 单个对象 |
| `kv` | 单个键值对象，或显式声明键和值字段的映射记录数组 | 任意选择前两列的普通记录列表 |
| `grouped` | 分组字典（组内为键值对象），或显式声明分组、键、值字段的映射记录数组 | 普通记录列表；重复分组键会导致信息覆盖 |
| `numbered` | 含有唯一整数编号与对应文本字段的记录数组 | 没有真实编号的列表；不能按显示行重新编号 |
| `flat` | 单个对象，以原固定列宽展示字段和值 | 记录数组；与 `kv` 平级 |
| `json` | 可序列化的完整原始数据 | 始终保留原字段、字段值和数据类型 |

Server Builtin 在参数解析阶段拒绝未声明的布局，例如 `job --format numbered` 和 `job --format kv`。ACMD 在 Client 端对成功生成的结构化结果检查所选布局，不适用则返回英文错误 `message`，同时在同一份失败 Result 中保留已取得的 `data` 和 `presentation`；Terminal 与 Output Records 显示错误消息，Result JSON 和 History 保留数据。格式名称错误仍在执行前由通用 Validator 拒绝。纯消息和业务失败结果直接显示消息。Core Renderer 还会校验必要字段、编号及分组键，不猜测列含义。`--format table` / `-f table` 用于查看完整表格。`--json` 与 `--format json` 等价，不受文本布局或默认展示字段影响。

`FLAT` 是正式的同级布局，旧调用方的 `shape='dict'` 仍由现有渲染器映射到它；`GROUPED` 也继续接受原来的 `grouped_dict` 形状。内置的 `ResultDataShape.NUMBERED_LIST` 保持原有枚举值，命令行参数使用更短的 `numbered`。这些仅是同一布局的内部名称，没有额外协议版本。

### 命令默认布局

| 查询 | 默认文本布局 | 允许的 `--format` 值（均含 `json`） |
|---|---|---|
| `script list`、`job list` | `lines` | `lines`、`table`、`records`、`json` |
| `alias list` | `kv` | `lines`、`kv`、`table`、`records`、`grouped`、`json` |
| `history list` | `numbered` | `numbered`、`table`、`records`、`json` |
| `config list` | `grouped` | `grouped`、`kv`、`table`、`records`、`json` |
| `watchdog` | `grouped` | `grouped`、`json` |
| `xt exec/package/module/instance list` | `lines` | `lines`、`table`、`records`、`json` |
| `gopin list`、`job ps` | `table` | `table`、`records`、`json` |
| `rtt`、`job status`、`xt exec info` | `flat` | `flat`、`kv`、`json` |
| `acmd ps`、`netstat`、`ifconfig`、`drives` | `table` | `table`、`records`、`json` |
| `acmd python_packages` | 已安装发行包和已加载发行包均为 `lines`；导入详情为 `flat` | 列表可选 `table/records/json`（记录保留版本）；详情可选 `flat/kv/json` |
| `acmd launchd` | 原有命令反馈文本 | `flat`、`kv`、`json` |

表格/纵向记录可以声明展示名称（例如 XT 的大写列名），但 JSON 始终使用原始字段名。Server Builtin 的参数由自身 Registry 定义，ACMD 的业务参数由 `ArgumentCommandSpec` 定义，呈现选项在 Client ACMD Registry 统一处理。

### Core 调用方式

```python
from core.utils.command_output import (
    ResultDataShape, StructuredCommandResult,
    resolve_presentation, render_structured_result,
)

output, layout = resolve_presentation(args_dict, ResultDataShape.LINES)
result = StructuredCommandResult(
    status=1,
    data=[{'name': 'alpha', 'description': '说明'}],
    shape=layout,
    line_field='name',
)
return render_structured_result(result, output_format=output)
```

`ResultEnvelope` 保留事件、状态、消息、完整业务数据及引用。ACMD 的 Result Wire 可选附带 `presentation`，说明本次结果来源、默认格式、可选的 `requested` 和必要字段选择；所选格式由 Client 解析后带回，允许格式清单保留在 Client 本地。Server 渲染文字供 Terminal/CLI 使用，Activity 的 Output Records 从相同 Result 重新投影，History 只保存原始 Result JSON。Server Builtin 继续通过 `render_result_payload(..., view='data', shape=layout)` 呈现。

默认文本表格保留原有列宽与续行规则；`records` 更适合手机上阅读长说明。空数组输出原有空列表提示，JSON 输出 `[]`。失败状态继续输出原有错误消息，不受布局选择影响。

## 浏览器的 JSON 视图选择

Web Terminal 将命令输出当作文本接收，并尝试识别其中**完整、可以成功解析的 JSON**。当某组输出被识别为 JSON 时，终端会提供 `[JSON]` 或 `[View JSON]` 操作；点击后打开 JSON Viewer。

JSON Viewer 按 Table → Grouped → Flat → Raw 的顺序选择显示方式。Grouped 仅用于外层多个对象分组均符合条件的 JSON，不递归展开第三层数据。

Script 和 Quick Action 的 **Result Dialog** 与 Terminal 使用相同的 JSON Viewer。Result 携带原生结构化 `data` 时优先使用该数据，并在首次打开、Run Again 刷新时保留同一条 Result 的 `view`（含 Actions、列、标题与详情）；文本结果则识别完整合法的 JSON 对象或数组（包括独立的多行 JSON 块）。有效 JSON 才提供 **View JSON** 入口；普通文本与不完整 JSON 不提供。Result Dialog 原有输出、复制和关闭操作不变。

| View | 触发条件 | 展示方式 |
|---|---|---|
| **Table** | 非空 JSON 数组，元素全部是对象，且各行字段集合完全相同，至少存在一个字段 | 一行一个对象、一列一个字段；结果级 `view.actions` 可提供操作按钮 |
| **Grouped** | 顶层是至少包含 **2 个分组键**的 JSON 对象；**每个**分组值都必须是非空 JSON 对象（不能是数组、`null` 或标量） | 按外层键分组；组名作为标题，每组内部一层 Key / Value 双列展示 |
| **Flat** | JSON 顶层是对象（包括空对象），且未匹配 Grouped | 顶层 Key / Value 列表 |
| **Raw** | 有效 JSON，但不适合 Table、Grouped 或 Flat | 格式化后的完整 JSON 文本 |

**Grouped 严格全量校验**：必须所有顶层成员都符合分组条件，任意一组结构不符就不能进入 Grouped，不会只渲染其中合格的几组。各组的字段集合无需相同。组内字段的值允许 `null`、标量、对象或数组；内部对象和数组只由现有 `JSON.stringify` 转为一段文本，不再展开成第三层组。Grouped 样式参照 Artifact Info / Preview Image Info 的分组标题、间距及双列字段布局。普通混合键值对象仍可由既有 Flat 规则显示，不能据此误认为 Grouped 已匹配。

**Flat 是顶层键值视图，不是将整个嵌套 JSON 递归 flatten 成带点号的路径**。如果顶层对象的值还是对象或数组，该值会被 `JSON.stringify` 转成一段 JSON 文本显示在对应 Value 中。

### 对象集合展示

例如终端完整输出：

```json
[
  {"name": "alpha", "pid": 1201, "active": true},
  {"name": "beta", "pid": 1202, "active": false}
]
```

Viewer 将它显示为 Name、PID、Active 三列（实际表头使用原始字段名），并提供前端搜索和列排序。

- **Search text** 对当前表格各单元格的字符串表示进行不区分大小写的包含匹配，只筛选浏览器视图，不修改原始 JSON。
- 点击列头可以排序。排序会优先识别数字和日期形式的字符串，其余按不区分大小写的文本比较；空值排在非空值后，同值保持原有相对顺序。
- JSON 中的数字和布尔值在表格单元格内转换成展示用字符串；嵌套对象或数组会转换成 JSON 字符串，`null` 显示为空。

数组为空且没有显式 `view.columns`、元素不是对象、字段集合不同，或首个对象没有字段时，进入 Raw View。若空结果提供 `view.columns`，Viewer 可展示带列标题的空表格。前端 Table 要求各行字段集合一致。

### 结果级 View Actions（Table / Card）

结构化 Result 的可选 `view.actions` 为整张表声明行操作模板，按钮按当前行的原始字段绑定 `{field}`，不会往每个 `data` 对象重复写动作。`_actions` 不再有按钮含义；若它存在于普通 JSON 中，按普通数据字段展示。

- 前两项操作直接显示为按钮，第三项及后续操作进入 `More`。桌面 Table 的 Actions 列跟随整张表横向滚动，Card 在卡片内直接排布操作。
- `confirm` 默认 `true`，执行时展示目标 Client 和完整命令，可选择 Terminal 或 New Dialog；显式 `false` 则直接提交。`refresh` 默认 `false`；显式 `true` 仅在操作成功后使用原 Command/Script/Quick Action 重放来源刷新当前 Viewer。
- 操作继续使用原有任务、确认、取消、目标 Client、WebSocket 以及 Run Again 逻辑；刷新不会覆盖历史 Result，也不会修改原始业务数据。
- Shell `echo`、Script `print` 等普通 JSON 文本仍能被识别并查看；它们不具备结果级 `view` 时不生成操作按钮。Script 使用 `context.emit_view(data, view=...)` 一次发出原始数据和结果级 View；Command Action 可填写正式的 `script exec <name> -- --key value` 命令执行另一条 Script。

### 多组键值展示（Grouped）

例如：

```json
{
  "client": {"id": "abc123", "pid": 1201},
  "remote_control_watchdog": {"enabled": true, "interval_seconds": 15},
  "local_heartbeat_watchdog": {"enabled": false, "timeout_seconds": 15},
  "process_recovery_watchdog": {"enabled": true, "supervisor_pid": 1202}
}
```

Viewer 会依输入顺序展示四个标题 `client`、`remote_control_watchdog`、`local_heartbeat_watchdog`、`process_recovery_watchdog`，并在每个标题下直接排列当前组的字段名和值。只有外层存在至少两个键、并且每个键的值均为非空对象时才进入此模式。例如 `{"one": {"pid": 1}, "two": null}` 或 `{"one": {}, "two": {"pid": 2}}` 均不匹配 Grouped，不会对一部分字段单独渲染分组。

如果组内出现 `"details": {"platform": "macOS"}`，它只会作为该组的一行文本值 `{"platform":"macOS"}` 显示；组内数组同理，不继续创建分组。Grouped 与其他可渲染模式一样可以切换 Raw View，并在复制或保存时保留原始 JSON。

### 键值字段展示

例如：

```json
{
  "client_id": "abc123",
  "watchdog_alive": true,
  "detail": {"pid": 1201, "mode": "remote"}
}
```

Viewer 逐项显示 `client_id`、`watchdog_alive`、`detail`。其中 `detail` 作为一条值呈现为 JSON 字符串，而不是自动拆成 `detail.pid` 和 `detail.mode`。`null` 值显示为空，空对象可以进入 Flat View，但没有可展示的条目。

### 原始 JSON 和导出

Raw View 将 JSON 解析后按两空格缩进显示，适合查看完整的嵌套数据。Table、Grouped 和 Flat 模式中可以切换 **Raw View / Render View**，但不支持结构化渲染的 JSON 本来就直接显示 Raw。

Viewer 的操作包括：

- **Copy Raw**：复制原始识别到的 JSON 文本，而不是搜索、排序后的表格内容；必要时使用浏览器的兼容复制方式。
- **Save to Artifact**：将原始 JSON 内容保存为 Server Artifact，同时携带能够取得的来源命令上下文。保存的不是当前屏幕上的 Flat / Grouped / Table 文本。

因此，无论怎样搜索、排序或切换 View，都不会改变原始 JSON 字段和数据顺序；这些操作只是浏览器侧展示。

## 解析条件与复制保存语义

终端的 JSON 识别**不依赖固定命令名、`--json` 标记或结构化结果对象身份**。理论上，普通 Shell 命令、Script 或 Server 命令只要输出符合终端的完整 JSON 识别规则，也能触发 JSON Viewer。

当前主要处理两类输入：

1. 单次追加的文本去掉首尾空白后，完整以 `{...}` 或 `[...]` 包围，并能被 `JSON.parse` 解析。
2. 输出从单独一行 `{` 或 `[` 开始，后续多行逐步积累，括号层级闭合并能整体解析。

多行积累期间，终端会识别命令边界或命令结束/失败标记；如果到边界时还无法解析为一个完整 JSON，就按普通输出文本显示。这个检测是对**显示文本**的启发式处理，不是一个任意字节流的通用增量 JSON 解析器。尤其当 JSON 与其他日志混杂、开头不是单独的 `{` / `[`、或数据被不适当地切分时，可能无法显示 JSON 操作入口。

其他应当区分的行为：

- 后端的 `StructuredCommandResult.shape` 不直接控制前端使用 Table、Grouped 还是 Flat；前端会重新解析收到的 JSON 文本。
- 默认的对齐键值文本或文本表格**不是 JSON**，不会仅因来自结构化结果而触发 JSON Viewer。
- 普通 Shell 输出不由 Server 自动附加 `--json`；ACMD 将 `--format/-f/--json` 原样交给 Client 解析，Server 仅根据 Result 中的选定布局渲染。
- 有效 JSON 标量（如单独的字符串或数字）不一定被终端自动识别为 JSON 操作，因为当前识别入口主要匹配对象和数组。
- 表格搜索、列排序和视图切换均在浏览器完成，没有服务端分页、筛选或重新请求格式化的机制。
- 结构化输出与 JSON Viewer 不提供数据真实性保证；实际字段、敏感信息与错误内容仍由执行的命令决定。

### 选择输出格式时的判断

| 现象 | 原因与处理 |
|---|---|
| 输入 `--json` 仍显示普通文本 | 对应命令可能没有支持这个选项，或参数位置不符合其解析规则；先查看该命令的 Help |
| Dict 的文本结果抛出 `width is required for dict output` | `StructuredCommandResult` 的字典文本渲染必须提供 `width` |
| `--format table` 报布局错误 | 需要记录对象数组 `list[dict]`；单个对象可用 `flat` / `kv` |
| JSON 数组只能显示 Raw | 数组为空且没有 `view.columns`、元素不是对象、首项没有字段，或各对象字段集合不一致 |
| Flat 中的子对象没有展开成多层字段 | Flat 仅展现顶层 Key / Value，嵌套值转成 JSON 字符串 |
| Grouped 没有出现 | 必须至少两个外层键，且所有组值都是非空对象；任一组不符合即不选用 Grouped |
| Grouped 组内的 JSON 对象没有展开 | 组内嵌套对象或数组只作为 JSON 字符串显示，不会递归渲染第三层 |
| 输出看起来像 JSON，却没有 View JSON | JSON 不完整、前后混入了其他文本，或未满足终端的分段识别条件 |
| 搜索或排序后复制的内容没有变化 | Copy Raw 和 Save to Artifact 始终使用原始 JSON，而不是当前过滤/排序结果 |
| JSON Viewer 里的字段与默认文本列不同 | 文本表格以首条记录的 Key 建列，JSON 输出保留原始对象，Viewer Table 又要求全部记录字段一致 |

只需要面向终端显示简单结果时，直接返回 `(status, text)` 即可；需要同一组数据提供人类可读文本和 JSON 两种表示时，使用 `StructuredCommandResult` 更合适。Web Terminal 再根据收到的 JSON 形状决定展示方式，两层职责保持独立。

## Web Terminal 操作身份与事件关联

Web Terminal 将一次用户发起的 Command、Script、Quick Action 或上传视为一个带业务身份的操作。操作的 `kind`、`action` 与 `invocation` 沿用 Activity History 的语义；终端块的标题由展示层处理，标题中的 `[Run Script]`、`[Remote Upload]` 和 `[Artifact Send]` 等文字只用于阅读。只有真实 Command 的执行文本才能作为 Shell Command 重跑。

浏览器为每次已确认提交的操作创建临时 `operation_id`，并通过 `X-RCH-Operation-ID` 请求头传给 Server。Server 校验 UUID，随 Web Task 元数据和执行 WebSocket 回传；浏览器将同一操作的输出、完成状态与 JSON 内容关联到对应终端块。`task_id`、`transfer_id` 和 Activity History ID 继续分别承担执行、传输与历史记录职责，浏览器操作 ID 不写入 Activity History。浏览器上传由 Transfer Center 管理上传阶段，再由 Web Task 报告目标设备传输的最终执行状态。

**Run again** 的可用性由操作携带的 `replay` 执行描述决定：真实 Command 保存命令文本，Script 保存脚本身份和参数，Quick Action 保存别名、平台及实际提交的参数，并由 Quick Action API 重新执行。Remote Upload 和 Artifact Send 不提供通用重跑描述。Block Dropdown、JSON Viewer 均采用相同规则，重跑创建新的操作与任务。已经显示的操作与结果不会因重跑而被覆盖。终端操作起始行的 `> ` 标记保留，用于区分操作开始与完成行；Command 与 Quick Action 的终端执行显示 `$>` 提示符，Script、Remote Upload、Artifact Send 等操作标题显示 `> [XXX]`。WebSocket 命令结果到达时，如果当前终端已经没有对应操作的起始行，终端会以任务身份补建起始标记，并将后续输出和完成状态归入同一块。Remote Files 与 Remote Folder Picker 上传、Artifact Send 在冲突预检查阶段发生错误时，会显示带起始行及失败结束行的操作块；用户取消冲突选择时不产生执行记录。Folder Picker 经嵌套弹窗转发的操作身份与 Remote Files 一致。Remote Files 的 Set CWD 命令同样使用独立操作 ID 关联任务结果。

执行期间由 Command、Script 或 Quick Action 产生的 Artifact 在带有相同设备和命令 ID 的终端块中显示 `[Preview] 文件名`，位置在 `[Command finished]` 前；每个 Artifact 单独显示一行，单文件同样显示文件名。Artifact 创建事件使用 `source_command_id` 与命令结果中的 `command_id` 关联；即使文件晚于完成事件到达，仍可更新对应块。终端不再写入 `[File Ready]` 行，通知中心与 Artifacts 保持原有访问入口。Remote Files 等独立操作不产生此类终端预览链接。

## JSON Viewer 的 Run Again 与结果级操作输出

Terminal 输出块菜单的 **Run again** 适用于真实 Command、携带可重跑脚本身份的 Script，以及保存了别名、平台和参数的 Quick Action。Quick Action 必须通过专用 API 执行，不将可见标题或展开后的命令传给 Shell。Remote Upload 和 Artifact Send 没有通用重放所需的文件上下文，菜单项保持禁用；JSON Viewer 使用同一资格规则。

JSON Viewer 支持对有效来源的 Command、Script 或 Quick Action 使用 **Run Again**，包括 Quick Action Result Dialog 打开的 JSON。发起一次新的执行并在 Terminal 中留下新执行记录。当前 Viewer 不关闭；新任务完成后优先使用原生 Result 数据和关联的 `view` 更新 Viewer；未提供结构化数据时尝试识别完整合法 JSON 块，解析失败则保留原数据显示。此前的 Terminal 历史内容始终不变。

Result 的 `view.actions` 统一描述操作模板；`confirm` 控制二次确认，`refresh` 控制成功后使用原操作重放来源刷新 Viewer。无重放来源时可以执行动作，但不会刷新。Terminal 与 New Dialog 都保持 JSON Viewer 打开，使用既有 `/api/connections/{client_id}/command` 请求和任务结果 WebSocket。

Run Again 与模板操作均执行新的任务；仅当前任务的结果用于刷新对应窗口，其他任务的输出不会混入。一次执行发送多条结构化记录时，优先选择最后一条携带 `view` 的记录和其原始 `data`，否则选择最后一条结构化记录；不跨事件拼接数据与 Actions。动作成功后若配置 `refresh: true`，在刷新期间旧按钮暂停；刷新失败时保留原始结果并提示已过期，直到成功重跑后恢复操作。

## Process Result Actions

`acmd ps` 返回原生进程记录数组，字段与此前相同：`pid / ppid / name / username / status`。不指定 `--with-actions` 时不附加 `view`；指定时在结果级 `view` 声明 Kill 模板与五个原有主表字段，不改动 `data` 的列。Terminal 文本展示遵循 `presentation`；JSON Viewer 按需展示 Kill 操作。`--port` 按当前监听端口筛选进程；使用 `--with-actions` 时若筛选无结果，返回空数组及相同列声明，使刷新后的空表格清楚显示。未带 `--with-actions` 的查询继续采用原有无匹配错误。

### Result JSON 的可选 View 元数据

`view` 是与 `presentation` 并列的可选 Result 字段，仅影响 JSON Viewer：`titleField`、`columns`（`field` 与可选像素 `width/minWidth`）、`details`（展开字段名）、`actions`（整张表共享的操作模板列表）。模板命令中的 `{field}` 由当前行原始数据绑定为单个安全参数值；缺失或无法作为参数表示的值使该操作不可用。字段值中允许普通花括号；仅模板里未解析的占位符会使操作不可用。`confirm` 缺省 `true`，`refresh` 缺省 `false`。原始 `data` 不变；History 仍只保存 Result JSON，Output Records 由 `presentation` 派生文字。JSON Viewer 默认在桌面显示 Table、手机显示 Card；可切换 Table/Card 和 Raw。前两个 Action 直接显示，其余归入 More。脚本 SDK `emit()` 的结构化输出契约不受 `view` 改动影响，Script JSON 文本不携带 `view` 时不提供操作按钮。
