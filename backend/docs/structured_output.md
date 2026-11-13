# Command Output Rendering

部分 Client 命令通过 `StructuredCommandResult` 将状态与可序列化数据交给统一渲染器，后者决定输出键值文本、文本表格或 JSON。Web Terminal 接收到结果后，还可能从完整 JSON 中识别适合 Table、Flat 或 Raw 的查看方式。因此命令产出格式与浏览器显示模式处于不同层级。

`--json` 只在相应入口确实实现了这个输出选项时生效；结果对象中的 `shape` 和原始 `data` 类型也不是同一概念。选择输出方式前，应分辨调用方是需要机器可读结果还是需要浏览器中的交互式表格。

## 命令返回值和终端展示的边界

```text
命令处理器（Client 内置 / ACMD / Server 内置）
          ↓
组织数据：dict 或 list[dict]
          ↓
StructuredCommandResult → 文本格式化 / JSON 序列化
          ↓
执行状态 + 结果文本 → 正常命令输出通道
          ↓
Web Terminal：显示输出、识别完整 JSON
          ↓
JSON Viewer：Table / Grouped / Flat / Raw
```

结构化结果解决的是**同一份数据如何输出为人类可读文本和可机器处理的 JSON**。例如进程信息可以默认显示为对齐的列，指定 JSON 输出时保留字段和数据类型，让调用方更方便地复制、保存或进一步处理。

Terminal JSON Rendering 是独立的展示层：浏览器检测输出是否为有效 JSON，提供查看操作，打开后依据 JSON 顶层类型选择适合的展示方式。它不反向改变 Client 命令的执行结果，也不为展示向 Server 请求另一份数据。仅当用户在 Table 中明确确认 Result Action 时，才通过原有命令接口提交该 Action 指定的命令。

## Control Result 的展示意图与同源数据

结构化命令的 `StructuredCommandResult.data` 是业务事实的唯一来源。Control 的最终 Result 可以同时含有简短的 `message` 和完整 `data`，由明确的 `display` 指定默认呈现：`message` 为操作反馈句，`data` 为结构化查询视图。`display` 与是否存在 `data` 无关，也不改变用于表示过程与终态的 `event_type`；`shape` 则只控制结构化数据的文本排版，不负责选择默认展示内容。

Job / Configuration 等带 `display` 的完成结果在 Control 内使用同一语义信封，包含执行 `status`、可选 `message` 与按需使用的 `data`。Terminal 按展示意图输出：

| 结果类型 | 默认 text | `--json` |
|---|---|---|
| `display=message`（操作反馈） | `message` | `{"status": "success/error", "message": "..."}` |
| `display=data`（成功查询） | 同一份 `data` 排成表格或键值文本 | 直接序列化 `data`，不附加信封字段 |
| 执行失败 | 具体错误信息 | `{"status": "error", "message": "..."}` |

JSON 中的执行成功与否由内部 Result 的 `status` 决定；成功数据查询的业务字段由 `data` 完整提供，不混入执行级 `status/message`。空数组在 JSON 中仍是 `[]`，文本可使用业务域提供的空列表提示。`--json` 不混入中间进度日志。Job `start/stop/stop_all` 为操作反馈，`ps/status` 为结构化查询；查询成功的 `message` 可为空。SDK 的 `context.emit(data)` 是 `chunk` 事件，直接呈现发出的 JSON 对象/数组。其他未声明此 Result 契约的命令沿用原有输出路径。

Configuration GET 在同一个 Result 的 `data` 中携带完整配置对象，供 Web Configuration 编辑器消费；SET/RESET 返回状态及消息，前端保存后通过 GET 刷新完整编辑 Schema。命令 `set` / `set --json` 从相同的 GET 配置对象提取 `key`、`group`、`value`、`override`、`default_value` 五字段视图。终端两种格式使用这份视图，Web 仍使用完整的配置项 Schema。`set KEY value`、`set --reset KEY`、`set --reset-all` 为操作反馈，支持可选 `--json` 输出状态与消息。

SDK `context.emit(data)` 可以在 Script 的普通文本之间发送一条独立 JSON 对象或数组输出。它保留结构化值，不等同于把 JSON 字符串打印进 stdout，也不代表 Script 已执行完毕。每条显式结构化输出均带有 `event_type=chunk`、`display=data`，与普通 `print()` 输出按执行顺序送出；Activity Output Records 保留其完整 Envelope，结构化内容以格式化 JSON 文本直接显示在输出记录中。该事件适用于 Python Client 的 `inproc` 和 `subprocess_pipe`，两种 Output Mode (`stream` / `collect`) 都支持；collect 等脚本结束后按原顺序回放。

## 结构化返回对象及形状

当前结果模型的名称为 `StructuredCommandResult`，核心属性如下：

| 属性 | 类型 | 作用 |
|---|---|---|
| `status` | `int` | 命令执行状态，与最终文本一起返回；通常 `1` 表示成功、`0` 表示失败 |
| `data` | `dict` 或 `list[dict]` | 需要输出的结构化内容 |
| `shape` | `'dict'`、`'table'` 或 `None` | 记录期望的数据形态 |
| `width` | `int` 或 `None` | 字典采用文本键值布局时的 Key 列宽 |

`shape` 可以明确表示调用方的意图，但**当前渲染器实际上依据 `data` 的 Python 类型选择格式，而不是依据 `shape` 分支**。因此即使写了 `shape='table'`，如果 `data` 是字典，文本模式依然走字典布局。应保持 `shape` 与 `data` 一致，避免给后续使用者造成歧义。

### 映射对象的键值表示

适用于单个对象的状态和属性，例如运行环境、设备信息或 Watchdog 状态。

```python
from core.utils.command_output import StructuredCommandResult

result = StructuredCommandResult(
    status=1,
    data={
        'service': 'worker',
        'running': True,
        'pid': 12345,
    },
    shape='dict',
    width=18,
)
```

默认文本模式使用固定宽度的 Key 列，将值逐项显示。`width` 对这种布局是必需的；如果字典以文本模式渲染却没有提供 `width`，当前渲染器会抛出 `ValueError`。指定 JSON 输出时不需要这个宽度，也不会受其影响。

字典中的值保持为原始 Python 数据用于 JSON 序列化；在文本模式下则直接转换成可显示文本，不执行递归展开。

### 对象集合的列形状

适用于包含多个同类记录的结果，例如进程、网络连接或文件信息。

```python
from core.utils.command_output import StructuredCommandResult

result = StructuredCommandResult(
    status=1,
    data=[
        {'name': 'alpha', 'pid': 1201, 'running': True},
        {'name': 'beta', 'pid': 1202, 'running': False},
    ],
    shape='table',
)
```

默认文本模式以**第一条记录的字段及其顺序**生成列头，然后逐行输出。如果后续记录缺少某个列头字段，该单元格显示为空；如果后续记录增加了第一条没有的字段，这个额外字段不会出现在文本表格中。因此应使各条记录的字段保持一致。

空列表在默认文本模式下显示 `No data to display`；如果选择 JSON，则输出 `[]`。JSON 保留列表的原始对象字段，而不是受到文本表格列头的限制。

## 序列化与文本呈现策略

统一渲染入口为 `render_structured_result(result, output_format='text')`。当传入 `StructuredCommandResult` 时，它将结果转换为通常的 `(status, text)`；如果传入的原本就不是这种结果对象，则直接原样返回。

| 输出模式 | Dict 数据 | List 数据 |
|---|---|---|
| `text`（默认） | 以 `width` 对齐的键值文本 | 根据首行字段生成文本表格 |
| `json` | JSON 对象 | JSON 数组 |

JSON 模式使用 `json.dumps(..., ensure_ascii=False, indent=2)`，因此中文等非 ASCII 字符保留原样，并使用两空格缩进。`status` 仍然作为命令结果状态返回，**不会自动嵌套进 `data` 的 JSON 文本中**。

例如上面的 Dict 在 JSON 模式下输出：

```json
{
  "service": "worker",
  "running": true,
  "pid": 12345
}
```

`--json` 并不是项目所有命令共享的全局参数；它必须由**对应命令入口自身支持**。当前有三种常见处理方式：

- **Client Shell-like 内置命令**：某个内置命令返回 `StructuredCommandResult` 后，普通命令执行器仅在它收到的整个参数字符串恰好为 `json` 或 `--json` 时，将结果渲染为 JSON。例如 `watchdog --json`。不能推断为所有带额外参数的组合都自动识别末尾 `--json`。
- **Server Built-ins**：部分命令通过 `parse_output_format()` 和 `strip_output_format_arg()` 读取并移除**最后一个** `json` / `--json` 参数，再分别生成文本或 JSON。具体是否接受及参数位置仍以该命令的实现和 Help 为准。
- **ACMD**：某些结构化命令将 `json` 声明为 `flag` 选项，经过自己的 Argument Schema 验证后，由处理器调用相同的输出格式化机制。这不意味着所有 ACMD 自动支持 `--json`。

例如，在目标 Client 的终端查询 Watchdog 状态：

```text
watchdog
watchdog --json
```

第一条显示对齐的状态键值；第二条返回同一组状态字段的 JSON，便于通过 JSON Viewer 查看或保存。另一个常见例子是：

```text
acmd ps --name python --json
```

这里 `--json` 是该命令明确声明的 Flag，进程列表会输出 JSON 数组。文档不维护支持 JSON 的固定命令清单，其他命令应以当前 Help 和实际输出为准。

## 在不同命令入口中返回数据

### Client 内建方法返回值

如果一个普通 Client 内置方法需要同时支持文本与 JSON，可以直接返回结果对象，而不必在方法里手工拼接两套输出：

```python
from core.utils.command_output import StructuredCommandResult
from core.utils.decorator import desc

class ExampleCommandMixin:
    @desc('Show example service state', group='system')
    def service_state(self, arg=''):
        return StructuredCommandResult(
            status=1,
            data={
                'name': 'worker',
                'enabled': True,
                'active_sessions': 2,
            },
            shape='dict',
            width=20,
        )
```

这是展示接入方式的示例，不代表项目现在注册了名为 `service_state` 的命令。方法仍需按照正常的 Client 命令导出机制接入对应平台。命令执行器调用方法后统一完成输出转换；`service_state` 显示文本，`service_state --json` 显示 JSON，前提是该命令没有另行将参数用于其他含义。

若返回多条记录，将 `data` 设为 `list[dict]`，`shape` 设为 `table`，不需要提供 `width`。应确保每条记录使用同一组字段，文本列才会完整一致。

### ACMD 及服务器命令结果

ACMD 通过自己的参数定义识别输出模式。例如有 `json` Flag 的处理器可以这样调用通用渲染器：

```python
from core.utils.command_output import StructuredCommandResult, render_structured_result

result = StructuredCommandResult(
    status=1,
    data=[{'pid': 1201, 'name': 'alpha'}],
    shape='table',
)

return render_structured_result(
    result,
    output_format='json' if args_dict.get('json') else 'text',
)
```

该示例只是结果输出部分；要使 `--json` 成为合法 ACMD 选项，还必须在该命令自身的 Argument Schema 中声明 `json` Flag。对于 Server Built-ins，同样可以复用结果模型和渲染器，但需要由该命令自己解析输出格式。**返回结构化结果不等于自动获得所有命令行选项。**

如果命令本身已经返回 `(status, text)`，或者主动生成 JSON 字符串，那么也能正常显示；但它不会被 `StructuredCommandResult` 渲染器再次处理。这种方式适合有独立输出协议的命令，不必强行迁移到同一个结果对象。

## 浏览器的 JSON 视图选择

Web Terminal 将命令输出当作文本接收，并尝试识别其中**完整、可以成功解析的 JSON**。当某组输出被识别为 JSON 时，终端会提供 `[JSON]` 或 `[View JSON]` 操作；点击后打开 JSON Viewer。

JSON Viewer 按 Table → Grouped → Flat → Raw 的顺序选择显示方式。Grouped 仅用于外层多个对象分组均符合条件的 JSON，不递归展开第三层数据。

Script 和 Quick Action 的 **Result Dialog** 与 Terminal 使用相同的 JSON 识别与渲染模型。当输出包含一份完整、合法的 JSON 对象或数组（包括独立的多行 JSON 块）时，Result Dialog 状态与命令行的右侧才显示 **View JSON** 按钮，点击使用同一个 JSON Viewer；普通文本或不完整 JSON 不显示入口。原 Result Dialog 的输出、复制和关闭操作不变。

| View | 触发条件 | 展示方式 |
|---|---|---|
| **Table** | 非空 JSON 数组，元素全部是对象，且各行除可选 `_actions` 外的普通字段集合完全相同，至少存在一个普通字段 | 一行一个对象、一列一个普通字段；可选行级 Actions |
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

如果数组为空、元素不是对象、普通字段集合不同，或首个对象没有普通字段，**不会勉强补列或自动合并不同 Schema**，而是进入 Raw View。`_actions` 是唯一不参与普通字段一致性比较的可选元数据。即使后台文本表格可以按首项字段显示，前端 Table View 仍要求全部记录结构一致，两者规则不同。

### 行级 Result Actions（仅 Table）

Table 中每个对象**可以选择性**提供 `_actions` 数组；没有该字段的行完全不需要添加它，也不需要填 `[]`。这不会修改现有普通字段 Schema：除了 `_actions` 以外，各行普通字段集合仍必须一致。普通 Table 继续保持原样；只有至少一行包含有效 Action 时才显示右侧 `Actions` 列，没有 Action 的行不显示按钮。

```json
[
  {"pid": 123, "name": "python3", "_actions": [{"label": "Inspect", "command": "echo inspecting-123"}]},
  {"pid": 456, "name": "node"},
  {"pid": 789, "name": "other", "_actions": [
    {"label": "One", "command": "echo one"},
    {"label": "Two", "command": "echo two"},
    {"label": "Three", "command": "echo three"}
  ]}
]
```

- `_actions` 仅是可选的行级展示元数据，不是可见数据列、不参与搜索或排序；每条有效 Action 只有 `label`（按钮名）与 `command`（完整的待发送命令）两个必需的非空字符串字段。无效字段项不会变成可执行按钮。
- 每行**前两个**有效操作始终直接显示为小按钮；只有第三个及其后的操作才进入 `More` 下拉菜单。只有 1–2 个操作时不显示 `More`。搜索、排序后，操作始终绑定原始数据行，不依赖行序号。
- 每次点击都**必须先确认**；确认框展示目标 Client 和即将执行的完整命令，并让用户选择 **Terminal** 或 **New Dialog** 输出（默认 Terminal）。只有用户选择 `Run` 才提交，取消不执行。没有可选 `confirm` 开关，也没有自动执行。
- **Terminal**：沿用现有行为，关闭 JSON Viewer，使用普通命令通道提交，命令及后续结果回到 Terminal。**New Dialog**：保持原 JSON Viewer 打开，另外弹出独立结果窗口，显示命令、运行状态、输出和复制操作；输出经同一命令通道执行，再由运行 ID 对应的 SSE 结果写入该窗口，不额外在 Terminal 输出同一条结果。关闭结果窗口不会关闭 JSON Viewer。
- 两种模式都不会覆盖命令输入框中尚未提交的草稿，也继续更新原有任务状态。若用户已切换目标 Client 或当前任务繁忙，不发送到其他设备。
- Viewer 只负责提交 Action 中的**原始命令**，不根据 PID/路径自行添加重新核验、重写命令或其他业务判断。具体命令本身的权限和行为仍由正常 Client 命令执行链负责。
- `_actions` 不依赖内置命令名称、`--json` 标志或 Script 名称；普通 Shell `echo`、Script 输出的完整合法 JSON 数组均由同一 Table 识别逻辑处理。其前提仍是终端成功识别到完整 JSON（不要和非 JSON 的日志混输出）。
- **Copy Raw、Raw View、Save to Artifact** 均保留原始 `_actions` 内容，不因界面隐藏操作列而删改 JSON。

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
- `--json` 不是服务器自动为任何普通 Shell 输出附加的格式选项；由各命令自己决定是否支持。
- 有效 JSON 标量（如单独的字符串或数字）不一定被终端自动识别为 JSON 操作，因为当前识别入口主要匹配对象和数组。
- 表格搜索、列排序和视图切换均在浏览器完成，没有服务端分页、筛选或重新请求格式化的机制。
- 结构化输出与 JSON Viewer 不提供数据真实性保证；实际字段、敏感信息与错误内容仍由执行的命令决定。

### 选择输出格式时的判断

| 现象 | 原因与处理 |
|---|---|
| 输入 `--json` 仍显示普通文本 | 对应命令可能没有支持这个选项，或参数位置不符合其解析规则；先查看该命令的 Help |
| Dict 的文本结果抛出 `width is required for dict output` | `StructuredCommandResult` 的字典文本渲染必须提供 `width` |
| `shape='table'` 却没有得到表格 | 当前依据实际 `data` 类型选择渲染；检查是否传入了 `list[dict]` |
| JSON 数组只能显示 Raw | 数组为空、元素不是对象、首项没有普通字段，或各对象的普通字段集合不一致（可选 `_actions` 不参与比较） |
| Flat 中的子对象没有展开成多层字段 | Flat 仅展现顶层 Key / Value，嵌套值转成 JSON 字符串 |
| Grouped 没有出现 | 必须至少两个外层键，且所有组值都是非空对象；任一组不符合即不选用 Grouped |
| Grouped 组内的 JSON 对象没有展开 | 组内嵌套对象或数组只作为 JSON 字符串显示，不会递归渲染第三层 |
| 输出看起来像 JSON，却没有 View JSON | JSON 不完整、前后混入了其他文本，或未满足终端的分段识别条件 |
| 搜索或排序后复制的内容没有变化 | Copy Raw 和 Save to Artifact 始终使用原始 JSON，而不是当前过滤/排序结果 |
| JSON Viewer 里的字段与默认文本列不同 | 文本表格以首条记录的 Key 建列，JSON 输出保留原始对象，Viewer Table 又要求全部记录字段一致 |

只需要面向终端显示简单结果时，直接返回 `(status, text)` 即可；需要同一组数据提供人类可读文本和 JSON 两种表示时，使用 `StructuredCommandResult` 更合适。Web Terminal 再根据收到的 JSON 形状决定展示方式，两层职责保持独立。

## Web Terminal 操作身份与事件关联

Web Terminal 将一次用户发起的 Command、Script、Quick Action 或上传视为一个带业务身份的操作。操作的 `kind`、`action` 与 `invocation` 沿用 Activity History 的语义；终端块的标题由展示层处理，标题中的 `[Run Script]`、`[Remote Upload]` 和 `[Artifact Send]` 等文字只用于阅读。只有真实 Command 的执行文本才能作为 Shell Command 重跑。

浏览器为每次已确认提交的操作创建临时 `operation_id`，并通过 `X-RCH-Operation-ID` 请求头传给 Server。Server 校验 UUID，随 Web Task 元数据和执行 SSE 回传；浏览器将同一操作的输出、完成状态与 JSON 内容关联到对应终端块。`task_id`、`transfer_id` 和 Activity History ID 继续分别承担执行、传输与历史记录职责，浏览器操作 ID 不写入 Activity History。浏览器上传由 Transfer Center 管理上传阶段，再由 Web Task 报告目标设备传输的最终执行状态。

**Run again** 的可用性由操作携带的 `replay` 执行描述决定：真实 Command 保存命令文本，Script 保存脚本身份和参数，Quick Action 保存别名、平台及实际提交的参数，并由 Quick Action API 重新执行。Remote Upload 和 Artifact Send 不提供通用重跑描述。Block Dropdown、JSON Viewer 均采用相同规则，重跑创建新的操作与任务。已经显示的操作与结果不会因重跑而被覆盖。终端操作起始行的 `> ` 标记保留，用于区分操作开始与完成行；Command 与 Quick Action 的终端执行显示 `$>` 提示符，Script、Remote Upload、Artifact Send 等操作标题显示 `> [XXX]`。SSE 命令结果到达时，如果当前终端已经没有对应操作的起始行，终端会以任务身份补建起始标记，并将后续输出和完成状态归入同一块。Remote Files 与 Remote Folder Picker 上传、Artifact Send 在冲突预检查阶段发生错误时，会显示带起始行及失败结束行的操作块；用户取消冲突选择时不产生执行记录。Folder Picker 经嵌套弹窗转发的操作身份与 Remote Files 一致。Remote Files 的 Set CWD 命令同样使用独立操作 ID 关联任务结果。

执行期间由 Command、Script 或 Quick Action 产生的 Artifact 在带有相同设备和命令 ID 的终端块中显示 `[Preview] 文件名`，位置在 `[Command finished]` 前；每个 Artifact 单独显示一行，单文件同样显示文件名。Artifact 创建事件使用 `source_command_id` 与命令结果中的 `command_id` 关联；即使文件晚于完成事件到达，仍可更新对应块。终端不再写入 `[File Ready]` 行，通知中心与 Artifacts 保持原有访问入口。Remote Files 等独立操作不产生此类终端预览链接。

## JSON Viewer 的 Run Again 与行级操作输出

Terminal 输出块菜单的 **Run again** 适用于真实 Command、携带可重跑脚本身份的 Script，以及保存了别名、平台和参数的 Quick Action。Quick Action 必须通过专用 API 执行，不将可见标题或展开后的命令传给 Shell。Remote Upload 和 Artifact Send 没有通用重放所需的文件上下文，菜单项保持禁用；JSON Viewer 使用同一资格规则。

JSON Viewer 支持对有效来源的 Command、Script 或 Quick Action 使用 **Run Again**，包括 Quick Action Result Dialog 打开的 JSON。发起一次新的执行并在 Terminal 中留下新执行记录。当前 Viewer 不关闭；新任务完成后仅在输出能解析为完整合法 JSON 时替换 Viewer 中展示的数据，否则提示错误并保留原数据显示。此前的 Terminal 历史内容始终不变。

Table 的 `_actions` 继续是可选的行级元数据。用户确认执行命令后，可以选择 Terminal 或 New Dialog：前者使用原终端输出，后者仅在当前前端的结果弹窗显示执行输出，不关闭原 JSON Viewer。两种动作均复用既有 `/api/connections/{client_id}/command` 请求及任务结果 SSE。

Run Again 与行级操作均执行新的任务；仅当前任务的结果用于刷新对应窗口，其他任务的输出不会混入。

## Process Result Actions

`acmd ps --json` 使用 `StructuredCommandResult(status=1, shape='table')`
生成 JSON 进程数组；默认不含 `_actions`。只有显式添加 `--with-actions`
（例如 `acmd ps --port 8080 --json --with-actions`）才为每行生成
`[{"label":"Kill","command":"acmd kill --pid 1234"}]`，交由现有
Terminal JSON Table 操作列显示。文本模式不输出 `_actions` 元数据。
`acmd ps` 的 `--port` 过滤当前监听/占用该端口的进程。无匹配进程沿用
`ps` 原有查询失败结果。
