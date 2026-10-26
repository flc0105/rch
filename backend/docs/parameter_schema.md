# Runtime Parameter Schema

RCH 的 Script、Background Job 和 External Tool 通过 Metadata 声明运行参数，并将字段契约交给前端输入控件和后端类型转换层共同使用。Schema 定义参数的形状、默认值与约束；具体运行弹窗、执行模式与生命周期仍由所属功能管理。

字段规范化和 Runtime 转换是这套设计的核心：相同类型在不同入口应尽可能表达相同数据，但“共享字段渲染”不等于整张业务表单或所有业务提交行为完全一致。理解参数问题时，应区分声明、前端编辑值、网络 Payload 和最终运行时取值。

## 参数契约的生产与消费

一份参数定义可以在不同运行入口得到一致的字段含义。例如：

```json
{
  "name": "port",
  "label": "Listen Port",
  "type": "integer",
  "required": true,
  "default": 8080,
  "min": 1,
  "max": 65535,
  "description": "Port used by the service"
}
```

Web 表单将它显示为标题为 **Listen Port** 的数字输入框，初始值为 `8080`，并展示必要的说明与取值范围。提交到运行时后，该值按整数处理，而不是保留为未经校验的任意文本。

完整链路可概括为：

```text
Script / Job / External Tool Metadata
            ↓
       params 参数清单
            ↓
    参数名称和类型规范化
            ↓
   各业务初始化 paramForm
            ↓
  共用字段组件渲染输入控件
            ↓
  各业务构建并提交 params
            ↓
  共享参数类型转换和校验核心
            ↓
   对应业务执行 / 管理生命周期
```

统一层和业务层的职责如下：

| 能力 | 当前实现方式 |
|---|---|
| 参数类型、别名和字段规范化 | 三者共用 |
| 单个参数对应的输入控件 | 三者共用 |
| 单选、数字和远程路径的通用转换规则 | 三者共用 |
| Remote File Picker | 三者复用 |
| 整张表单的排列、操作按钮及运行选项 | 各业务分别维护 |
| 初始值、Preset 应用和提交前检查 | 各业务分别维护 |
| 最终执行及生命周期 | Script、Job、External Tool 各自独立 |

因此，新增一个已有类型的参数通常只需要扩展 Metadata；但新增一种全新的参数类型，不能仅凭增加一个 `type` 名称就期待自动拥有专用控件和完整校验。

## 可序列化的字段定义

参数统一声明在 `params` 数组中。每项以 `name` 为标识，并使用 `type` 指定输入控件和最终数据类型。例如：

```json
{
  "params": [
    {
      "name": "mode",
      "label": "Execution Mode",
      "type": "select",
      "required": true,
      "default": "safe",
      "options": ["fast", "safe"],
      "description": "Select the execution mode"
    },
    {
      "name": "count",
      "label": "Count",
      "type": "integer",
      "default": 3,
      "min": 1,
      "max": 100
    },
    {
      "name": "output_dir",
      "label": "Output Directory",
      "type": "remote_folder",
      "required": true
    }
  ]
}
```

### 字段类型及规范化

当前共有十种常规参数类型：

| `type` | Web 输入方式 | 运行时数据 |
|---|---|---|
| `string` | 单行文本框 | 字符串 |
| `textarea` | 多行文本框 | 字符串 |
| `integer` | 数字输入框 | 整数 |
| `number` | 数字输入框 | 浮点数 |
| `boolean` | Switch 开关 | 布尔值 |
| `select` | 单选下拉框 | 允许的选项值对应的字符串 |
| `remote_file` | 单路径展示 + Browse | 单个文件路径字符串 |
| `remote_files` | 多路径展示 + Browse | 文件路径字符串数组 |
| `remote_folder` | 单路径展示 + Browse | 单个目录路径字符串 |
| `remote_folders` | 多路径展示 + Browse | 目录路径字符串数组 |

规范化时允许以下类型别名：

| 别名 | 统一类型 |
|---|---|
| `int` | `integer` |
| `float` | `number` |
| `str` | `string` |
| `bool` | `boolean` |
| `text`、`multiline` | `textarea` |

类型名称在规范化时会去除两端空白并转为小写；未声明 `type` 时默认使用 `string`。除此以外还有特殊的 `path_list`，用于带启用开关的可编辑路径行，详见第三节。

### 约束与可选字段

| 属性 | 说明 |
|---|---|
| `name` | 参数标识，作为提交对象的 Key；缺失或空白名称的定义会被跳过 |
| `label` | 界面显示名，省略时采用 `name` |
| `type` | 参数类型，省略时为 `string` |
| `required` | 是否必填，默认 `false` |
| `default` | 默认值，未提供时规范化结果为 `null` |
| `description` | 输入框说明文字，默认为空 |
| `min` / `max` | 数值上下限，对 `integer`、`number` 的转换结果进行检查 |
| `options` | `select` 允许值列表，非列表/元组输入规范化为空列表 |
| `multiple` | Remote Picker 是否采用多选；远程多路径类型默认启用 |
| `selection_mode` | Remote Picker 的 `file` / `folder` 选择模式 |
| `initial_path` | Remote Picker 初次打开时参考的目录 |
| `rows` | `textarea` 的显示行数，未设置或无效时显示 6 行 |

规范化过程中会修剪 `name`、`label`、`description`，补充通用默认属性，将 `select.options` 规范为列表，并保留原定义中的其他扩展字段。扩展字段被保留**不代表**共用渲染或校验机制一定认识它。

例如，`min` / `max` 不是 `string` 的长度约束；`allow_empty` 即使出现在某些 Metadata 中，也没有对应的共享空值校验分支。`options` 是普通选项数组，而不是支持标签与值分别配置的通用选项对象结构。

### Metadata 中的嵌套布局

Script 和 Job 使用 Python 字典，External Tool 使用 JSON，`params` 内部仍是同一种字段规范。声明时应选择规范化后的正式类型名称，并为需要在 UI 中使用的参数提供清楚的 `label` 和 `description`。

`required`、`default` 和用户主动输入空值之间存在不同处理路径，不能简单理解成“必填永远不得使用默认值”：当参数缺失而存在非 `null` 默认值时，共享解析器会先选择默认值，再执行类型转换。

## 前端控件与远程选择器

### 字段控件的生成

Web 端使用同一个参数字段组件，根据 `type` 选择 Element Plus 控件。它接收参数定义和当前值，向父表单发出数值变更或 Browse 请求，本身不执行 Script、Job 或 External Tool。

字段行为包括：

- `boolean` 显示 Switch，更新布尔值。
- `select` 显示带 `options` 的单选下拉框；界面可清空选择。
- `integer` / `number` 使用数字输入控件，读取 `min` / `max`。
- `textarea` 使用多行输入框；普通类型使用单行文本框。
- `remote_*` 显示只读路径和 Browse，路径由 Remote File Picker 返回。
- 参数下方展示说明、必填提示、默认值及数值范围；无说明时显示通用占位文字。

各业务维护一个按参数名索引的表单对象，例如：

```json
{
  "mode": "safe",
  "count": 3,
  "output_dir": "/tmp/output"
}
```

用户修改控件后，字段组件把新值发回父表单。父表单决定何时验证、怎样构建最终 `params`，以及提交到哪个运行接口。

### 目录与文件的远程选择

四种 `remote_*` 类型共用同一个远程路径选择体验。单数类型返回**一个字符串**，复数类型返回**字符串数组**：

```json
{
  "source_file": "/tmp/a.txt",
  "source_files": ["/tmp/a.txt", "/tmp/b.txt"],
  "output_dir": "/tmp/output",
  "output_dirs": ["/tmp/out-a", "/tmp/out-b"]
}
```

`selection_mode` 可以显式指定 `file` 或 `folder`；不提供时根据路径类型推导。`initial_path` 提供初始目录；单目录参数已有值时，也可能优先以当前选中目录作为打开位置。

`multiple` 控制的是 Picker 的选择行为，不负责改变后端参数类型。例如，给 `remote_file` 写入 `multiple: true`，界面可以尝试多选，但后端仍按**单个路径**进行校验；因此应直接使用 `remote_files`，而不是靠 `multiple` 将单路径类型改造成数组类型。

### 可编辑路径集合

`path_list` 主要面向 Script Run 中需要逐行启停的路径集合，不属于上表十种常规远程路径类型。它支持增加、删除路径行，以及为每一行切换 `enabled`：

```json
[
  {"path": "/data/projects", "enabled": true},
  {"path": "/data/archive", "enabled": false}
]
```

与 `remote_files` 不同，`path_list` 保留了每行的启用状态，禁用条目不会被简单丢弃。后端要求列表中每一项都是包含字符串 `path` 的对象，`enabled` 必须是布尔值；缺少 `enabled` 时默认 `true`。每行路径字符串会去除首尾空白，空路径行不会被自动删除。

Script 表单允许用户删除全部行并提交空列表，表示当前确实没有路径行，而不是请求重新载入默认值。它与 Remote Picker 的多文件选择不是同一种数据结构，也不应互相转换。

## 执行入口如何使用同一契约

### 脚本调用时的绑定

Script 在 Python Metadata 中声明 `params`，例如：

```python
SCRIPT_METADATA = {
    "name": "convert_images",
    "display_name": "Convert Images",
    "params": [
        {"name": "quality", "type": "integer", "default": 85, "min": 1, "max": 100},
        {"name": "files", "type": "remote_files", "required": True},
    ],
}
```

Script Library 读取静态 Metadata 后构建参数表单。用户选择 Run in Dialog 或 Run in Terminal，再通过以下接口提交脚本名称、参数及执行展示信息：

```http
POST /api/connections/{client_id}/scripts/run
```

Run in Dialog / Terminal 决定执行结果如何显示，不属于共享 `params` 字段类型。Script 的 Metadata 通过静态 Python 语法树读取，因此应使用可直接解析的字面量字典；不能假定通过函数调用动态生成的 Metadata 能被自动识别。

Script 运行链会在派发运行请求前处理参数规范化与验证，未提供默认值的非必填参数通常不强制加入结果对象。

### Job 参数与进程策略的解耦

Job 通过 `JOB_METADATA` 声明参数，同时保留 Job 专属的 `execution` 配置：

```python
JOB_METADATA = {
    "name": "sample_job",
    "execution": {
        "default": "subprocess",
        "allowed": ["inproc", "subprocess"],
    },
    "params": [
        {"name": "interval", "type": "integer", "default": 10, "min": 1},
        {"name": "directory", "type": "remote_folder", "required": True},
    ],
}
```

Job 启动表单复用共享参数字段，同时展示 In-process 和 Subprocess 的执行模式选项。该模式有独立的允许值和默认值规则，不应在 `params` 中伪装成普通业务参数。

```http
POST /api/connections/{client_id}/background-jobs/start
Content-Type: application/json
```

```json
{
  "job_name": "sample_job",
  "execution_mode": "subprocess",
  "params": {
    "interval": 10,
    "directory": "/tmp/input"
  }
}
```

Job 的 Web 请求由 Server 转交给 Client，Client 在实际启动 Job 的处理链中完成参数解析。它与 Script 使用同一个类型转换核心，但验证发生的位置不完全相同。Job 的生命周期、运行状态、停止方式也不由参数字段组件管理。

### External Tool 的运行配置

External Tool 使用 JSON Metadata。参数可以声明在 Package 层或 Module 层；某个 Module 运行时会按顺序组合两组参数：

```json
{
  "id": "example-package",
  "params": [
    {"name": "verbose", "type": "boolean", "default": false}
  ],
  "modules": [
    {
      "id": "server",
      "execution": "daemon",
      "params": [
        {"name": "port", "type": "integer", "default": 8080}
      ]
    }
  ]
}
```

上例仅展示参数组织片段；完整的 External Tool Package 还需要满足其独立的平台包、可执行程序等 Metadata 要求。

Package 参数与 Module 参数是**列表拼接**，不是按参数名进行智能覆盖。如果两个层级使用相同 `name`，当前没有专门的同名冲突合并策略，声明时应保持参数名唯一。

External Tool 还支持保存和应用参数 Preset。Preset 只保存表单值，不会修改参数 Schema：打开运行对话框先初始化默认值，再用所选 Preset 中的同名参数覆盖。Launcher、Preview Command、Daemon 和 Oneshot 则属于 External Tool 自己的启动能力；其中 Preview Command 会让后端依据参数和命令模板生成准备执行的命令，不是通用字段渲染功能。

External Tool 同样使用共享后端解析器，但会对缺失的非必填参数采用专属策略，详见第五、六节。

## 从提交值到运行参数的转换

共享后端先规范化参数定义，再逐项决定使用用户值还是默认值，最后转换数据类型并检查约束。例如：

```json
{
  "mode": "safe",
  "count": "5",
  "enabled": "true",
  "files": ["/tmp/a", "/tmp/b"]
}
```

根据对应声明解析后：

```json
{
  "mode": "safe",
  "count": 5,
  "enabled": true,
  "files": ["/tmp/a", "/tmp/b"]
}
```

主要规则如下：

| 类型或条件 | 处理方式 |
|---|---|
| `integer` | 按整数转换；非整数格式报错，再检查上下限 |
| `number` | 转换为浮点数，再检查上下限 |
| `boolean` | 接受布尔值，以及 `1` / `true` / `yes` / `on`、`0` / `false` / `no` / `off` 等字符串（不区分大小写） |
| `select` | 转为字符串；有非空 `options` 时必须匹配其中一项 |
| `string` / `textarea` | 转为字符串；正常内容中的空格与换行保留 |
| `remote_file` / `remote_folder` | 拒绝数组，转换为修剪后的单个路径字符串 |
| `remote_files` / `remote_folders` | 要求数组，忽略其中转换后为空的路径项 |
| `path_list` | 要求路径行对象数组，校验 `path` 和 `enabled` 的数据类型 |
| `required` | 没有值且没有可用默认值时拒绝，错误文案按业务区分 |
| `default` | 未提交、`null` 或空字符串等缺失情况，优先使用非 `null` 默认值 |

多路径参数必须使用真正的 JSON 数组：

```json
["/tmp/a", "/tmp/b"]
```

以下都不属于合法的 `remote_files` / `remote_folders` 传参方式：

```text
/tmp/a,/tmp/b
["/tmp/a", "/tmp/b"]    ← 整段作为字符串提交
```

此外，共享校验对两个边界有明确行为。

**必填的多路径参数：** `[]` 会被视为缺失；提交非空数组后，路径项会经过字符串转换、修剪和空条目过滤。因此业务仍需留意数组中实际有效路径是否满足自身要求，不能把它等同于远程路径一定存在或可访问。

**未声明的参数：** 当前解析器会将提交对象中不属于已解析字段的其他 Key 保留进结果；如果没有任何参数定义，则通常直接保留原参数字典。因此这套 Schema 并非一个禁止所有额外字段的严格对象白名单验证器。业务的访问控制、参数安全与命令渲染仍应独立处理。

对没有默认值的非必填参数，Script / Job 通常省略；External Tool 则通过共享解析器的 `include_missing` 策略填入空值：多路径和 `path_list` 用 `[]`，其他类型用 `""`。此区别会影响后续命令模板如何读取缺失字段。

## 共享组件以外的业务差异

### 字段初值和提交校验

虽然控件相同，三类表单的控制逻辑仍分开维护。

| 情况 | Script / Job | External Tool |
|---|---|---|
| 默认值初始化 | 按自身 Metadata 与参数类型初始化 | 先构建 Module 默认值，可再应用 Preset |
| 数字与 Select | 前端主动处理部分转换和校验 | 前端处理必要检查，其余更多依赖后端 |
| 必填空值 | 前端执行部分必填判断 | 检查 `""`、`undefined`、`null` 等空值 |
| 必填的空路径数组 | 前端与后端有相应校验 | 前端可能放行，后端仍会拒绝 |
| 缺失的选填参数 | 通常省略 | 后端可补空字符串或空数组 |

这里最典型的差异是 `required: true` 的 `remote_files`：后端将 `[]` 视为缺失，但 External Tool 前端当前主要检查字符串空值和 `null`，可能让空数组进入提交过程，随后由后端报错。它不意味着空数组在 Schema 中变成了合法的必填值。

### 省略参数与显式清空

“没有填写”和“主动清空输入框”并没有一套在三种表单里都完全相同的独立语义。用户清空有默认值的输入框后，Script / Job 在构建参数时可能恢复默认值；External Tool 前端可能提交空值，随后又由后端按共用规则决定是否回退默认值。

因此，如果业务确实需要表达“用户明确选择空字符串，与未提供参数不同”，当前通用 Schema 并没有完善的专门标记。设计该类参数时，应先核对具体运行入口的行为，而不是假设所有表单都能区分这两种意图。

### 扩展约束的应用范围

当前方案是项目自己的运行参数规范，**不是完整的标准 JSON Schema 实现**。未提供通用的字段联动、嵌套对象编辑、动态选项来源、通用多选下拉或任意新类型自动注册能力。

未知类型在规范化阶段一般会保留名称，前端可能回退为普通文本框，后端也可能按字符串处理。这种回退行为不能视作该类型已被正式支持。扩展参数能力时，需要同步考虑 Metadata 规则、前端控件、默认值、转换规则和相关执行入口，不能只新增 `type` 字符串。

同样，字段定义中出现 `allow_empty` 等额外属性，并不代表共享校验器会自动实施对应约束；需要以当前明确实现的规则为准。

## 扩展字段时的约束与诊断

### 声明稳定的运行参数

新参数优先使用十种通用类型，并遵循以下实践：

1. 使用稳定且不重复的 `name`，将它作为脚本、Job 或命令模板读取参数的唯一标识。
2. 提供人类可读的 `label`、明确的 `description`；必填项写明 `required`，有合理默认值时写明 `default`。
3. 数值参数使用 `min` / `max`，枚举参数使用 `select` 和 `options`，避免依赖自由文本再自行判断。
4. 远程路径按单数/复数选择对应类型；复数始终使用数组，不引入 CSV 或序列化字符串作为另一套输入形式。
5. 执行模式、Preset、展示位置、生命周期等应属于各业务的独立配置，不塞进共享字段 Schema 伪装为普通参数。
6. 调整参数后分别检查其目标业务的默认值、表单提交、后端转换与运行结果，特别是空值和必填多路径。

例如一个需要指定处理模式、输出目录和若干源文件的功能，可以声明：

```json
{
  "params": [
    {"name": "mode", "label": "Mode", "type": "select", "options": ["fast", "safe"], "default": "safe"},
    {"name": "sources", "label": "Source Files", "type": "remote_files", "required": true},
    {"name": "output", "label": "Output Folder", "type": "remote_folder", "required": true}
  ]
}
```

用户选择后，运行参数保持结构化格式：

```json
{
  "mode": "safe",
  "sources": ["/tmp/a.txt", "/tmp/b.txt"],
  "output": "/tmp/output"
}
```

### 类型不匹配时的定位

| 现象 | 判断方向 |
|---|---|
| 新参数没有显示 | 检查 `params` 是否位于对应业务的正确 Metadata 层级、`name` 是否有效，以及 Metadata 是否成功读取 |
| 参数类型变成普通文本框 | 检查 `type` 是否属于正式支持集合或别名 |
| Select 无选项或提交报错 | 检查 `options` 是否为有效数组，提交值是否在允许范围内 |
| 必填字段填了值仍报错 | 检查前端值类型、默认值处理，以及提交后的实际 JSON 结构 |
| 多文件参数被拒绝 | 检查是否提交了路径数组，而不是 CSV 或 JSON 数组字符串 |
| Picker 能多选但后端不接受 | 检查 Schema 是否错误地使用 `remote_file` 加 `multiple: true` |
| 清空输入后又出现默认值 | 对照具体业务的前端提交器和后端默认值处理 |
| External Tool 页面允许提交空数组但启动失败 | 后端统一校验仍会拒绝缺失的必填多路径参数 |
| 不认识的参数也进入运行时 | 当前解析器保留未声明 Key，不负责严格对象白名单过滤 |
| `path_list` 丢失启用信息 | 检查是否误把路径行对象数组当成普通多路径字符串数组 |

这套共享能力的边界是：**参数字段的定义与转换尽可能一致，业务执行和完整表单流程保持各自职责。** 使用同一套 Schema 能减少重复定义，但不能替代针对 Script、Job、External Tool 各自执行行为的验证。
