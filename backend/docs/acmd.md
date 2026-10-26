# ACMD — Argument Commands

ACMD 将终端输入解析为可验证的参数对象，再交给目标 Client 已注册的 Argument Command Handler。命令名称、参数类型、短别名、位置索引和帮助文本都来自客户端注册契约；Server 只负责识别入口并建立参数负载，不代替客户端做最终类型校验。

这种机制与普通 Shell-like Command 共享 Client 的执行通道，却使用独立的命令注册、验证和 Help 体系。理解其运行过程，应沿着输入解析、Schema 约束、注册查找和结果返回的顺序阅读，而不是记住一份随平台变化的命令总表。

## 解析入口与派发路径

执行流程如下：

```text
Web Terminal / Server CLI：acmd <name> ...
                 ↓
Server：识别 acmd 前缀、命令分词与初步参数提取
                 ↓
Client 连接：acmd 消息 + 结构化 Payload
                 ↓
Client：按当前平台查 Command Registry
                 ↓
有注册及参数定义 → 别名/位置参数处理 → 校验与类型转换
                 ↓
调用命令 Handler → 返回状态与结果
```

例如：

```text
acmd ps --name python --json
```

Server 会生成类似如下的负载：

```json
{
  "name": "ps",
  "args": {
    "name": "python",
    "json": true
  },
  "raw": "acmd ps --name python --json"
}
```

这里的 `args` 只是 Server 完成文本解析后的参数，不能视为已通过类型验证的最终值。Client 收到后才读取 `ps` 所定义的参数规则；例如布尔 Flag 转换、整数转换等均在 Client 侧完成。

`acmd` 走独立的 `acmd` 协议消息类型，不使用普通 `command` 的字符串分派，也不会在找不到处理器时交给系统 Shell。命令是否可执行，取决于目标 Client 的操作系统平台和当前注册内容。

## Process ACMD：Kill 与 PS

普通 Process Manager UI 仍通过 `kill_process <pid>` 处理按钮操作。
Terminal / Server CLI 提供统一的 ACMD 命令：

```text
acmd kill
acmd kill --pid 1234
acmd kill --name python --force
acmd kill --port 8080 -9
acmd kill --pid 1234 --no-confirm
acmd ps
acmd ps --pid 1234 --json
acmd ps --name python --json
acmd ps --port 8080 --json
acmd ps --port 8080 --json --with-actions
```

- `acmd kill` 无目标时先通过 Interaction Broker 询问 `pid/name/port`
  和目标值，再 Preview。指定目标时直接 Preview 所有匹配 PID，
  可取消单条勾选；Force 初始状态由 `-9/-f/--force` 决定。
- `--no-confirm` 必须指定目标，不发起任何交互。`--force` 仅决定使用
  `SIGKILL`，未指定时使用 `SIGTERM`。不从未确认的自由文本猜目标。
- `acmd ps` 支持 `--pid/--name/--port`；普通输出及 `--json` 默认只含
  进程信息。仅指定 `--json --with-actions` 才在每行添加 `_actions`，例如
  `[{"label":"Kill","command":"acmd kill --pid 1234"}]`。
  `--with-actions` 是通用的可选行操作开关名，文本输出不渲染 Actions。
- `kill_proc / kill_port / pkill / pgrep` 不再是注册的 Client 命令。
- 进程选择和发信号都在 Client 执行。不预设 PID 白名单或进程保护名单；
  操作系统权限仍决定实际信号是否成功。对 PID 创建时间、名称、可执行
  文件和端口归属进行重检，拒绝预览后身份发生变化的进程。服务器下发的 Interaction
  Grant 仅授予显式注册需要交互的 ACMD；无确认模式不请求 Grant。

## 从输入文本构造参数对象

基本形式：

```text
acmd <command> [--key value] [--key=value] [--flag] [positional...]
```

实际可用的 Key 由每个命令自己声明，不能将其中一个命令的选项推广成所有 ACMD 的全局选项。

### 命名参数、位置参数与短别名

当前 `ps` 的例子：

```text
acmd ps --name python
acmd ps --name=python
acmd ps -n python
```

这三种写法都用于按进程名称过滤；`-n` 是该命令为 `name` 声明的短别名，并非所有命令通用的 `-n` 选项。

位置参数只有在命令为具体选项声明了位置索引时才生效。例如：

```text
acmd netstat 443
```

当前会将第一个位置参数对应到 `port`，相当于传入 `--port 443`。如果要显式将后续 Token 归入位置参数区域，可以使用 `--` 分隔符；它不会自动让未声明的位置参数变成合法选项。遇到未知或多余参数，应以具体命令的验证结果为准。

带空格的参数值需要正确引用：

```text
acmd ps --name "Visual Studio Code"
```

Server 使用 `shlex` 解析这类命令文本，不等同于直接把文本交给 Windows CMD 或 Unix Shell。Shell 特有的变量展开、管道和重定向，也不会自动发生在结构化参数中。

### Flag 与有值布尔参数

例如：

```text
acmd ps --json
acmd ps --json=false
```

当前 `ps` 声明了名为 `json` 的 Flag，因此省略值表示 `true`；显式传值则进行布尔转换。Flag 接受 `true/false`、`yes/no`、`on/off`、`1/0` 等形式。`--json` 不是 ACMD 的全局能力，只有具体命令声明后才可用。

普通布尔选项（`bool`）与 Flag（`flag`）不同：`bool` 需要提供可转换的值，`flag` 才允许只写选项名称。对于短别名或不以 `--` 开头的 Token，Server 可能先将其放入位置参数列表，Client 再按当前命令的 Schema 识别，因此最终以 Client 校验结果为准。

## 命令契约与参数验证

ACMD 维护自己的命令定义和参数规格，与 Script / Job / External Tool 的 [共享运行参数 Schema](parameter_schema.md) **不是同一套数据结构**，虽然二者都提供类型转换和默认值。

一个结构化命令的参数定义形式如下（示意而非实际已注册命令）：

```python
ArgumentCommandSpec(
    name='example',
    description='Example structured command',
    options=[
        ArgumentOptionSpec(
            name='target',
            option_type='str',
            required=True,
            allow_empty=False,
            help_text='Target name',
        ),
        ArgumentOptionSpec(
            name='count',
            option_type='int',
            default=3,
            alias='c',
            help_text='Number of attempts',
        ),
    ],
)
```

### 参数属性与类型

| 属性 | 含义 |
|---|---|
| `name` | 参数的正式名称 |
| `option_type` | 期望值的类型 |
| `required` | 是否必须提供；若有非空缺失默认值可以使用默认值 |
| `default` | 未提供时使用的值 |
| `allow_empty` | 字符串参数是否允许空文本 |
| `alias` | 单字符短别名 |
| `positional_index` | 允许映射到的零基位置参数序号 |
| `help_text` | 参数的帮助描述 |

当前类型包括 `str`、`int`、`float`、`bool`、`flag`。`str` 转成字符串；`int` 和 `float` 做数值转换；`bool` 要求提供可识别的真假值；`flag` 允许直接写出选项名代表 `true`。

一个命令的 `ArgumentCommandSpec` 还可以包含 `description` 和 `examples`，用于帮助信息生成。定义了 `required`、`default` 不代表有全局数值范围、枚举选项、文件路径存在性等业务约束；这些通常需要具体处理器自己判断。

### 验证行为

Client 接收到负载后，先把短别名归一化为正式名称，并识别可从位置参数中提取的选项，然后完成未知选项检查、必填/默认值处理、类型转换和空字符串检查。验证失败会返回错误，**不会进入相应处理器**。

例如：

```text
acmd ps --pid not-a-number
```

当前 `pid` 声明为整数，因而会提示它必须是整数；同样，未声明的命名选项会得到 Unknown option 错误。可选参数未提交时会取定义的默认值（包括 `None`），而非一律拼出空字符串。

重复参数也需要注意：Server 的初步解析以字典承载长选项，重复相同名称可能由后值覆盖前值；但 Client 在短别名和正式名称同时指向同一选项等情况下会拒绝重复。当前并不是所有文本形式都采用同一套重复检测。

位置参数方面，规范中声明了 `positional_index` 才会自动映射对应位置；在共用验证器中，未被消费的位置参数仍可能以 `_args` 留给处理器，因此“通过 Schema 类型校验”不代表任意额外位置值都会被统一拒绝。

## 注册表及平台可用性

ACMD 不是由 Server 维护固定命令清单。目标 Client 加载当前平台的命令对象后，收集显式注册的命令名称、参数规格及 Handler，生成本机的 Command Registry。

注册关系的典型形式是：

```python
@argument_command('example', spec=EXAMPLE_SPEC)
def _acmd_example(self, args_dict, payload=None):
    ...
```

这段只是演示处理器与 Schema 如何绑定，并不表示系统当前有 `example` 这个命令。Handler 收到的是已归一化的参数字典，并可根据签名接收完整 Payload；它通常返回 `(status, result)`，其中 `1` 代表成功，`0` 代表失败。

不同平台加载不同注册对象，因此 Windows、macOS、Linux、iOS 的可用 ACMD 可以不同；公共处理能力也要由具体平台注册后才会出现在对应 Client 中。未注册名称不会退回 Shell，通常会返回：

```text
acmd command not supported on this platform: <name>
```

注册表负责参数验证、帮助和分派；Handler 则负责真正的操作、业务规则和结果呈现。结构化输入**不等于**结构化输出：处理器可以返回文本、表格或其自行支持的 JSON 格式，没有统一要求所有 ACMD 的结果都是 JSON。

## 可发现性与自描述接口

由于命令可能随平台和项目版本发生增删，**实际可用命令以当前 Client 动态注册表为准**，不建议使用固定命令清单作为长期文档。

在 Client 命令通道输入：

```text
acmd help
```

可以列出当前已注册的结构化命令和简要描述。想查看某个命令的参数、默认值和示例，例如：

```text
acmd help ps
```

也可以使用该命令的帮助 Flag：

```text
acmd ps --help
```

这些帮助内容由对应参数规格生成，展示 Usage、Options、参数类型、必填性、默认值、位置参数以及配置的 Examples；无需在每个处理器里自行维护一份人工帮助字符串。只有具体命令提供 Schema，才能生成完整的参数帮助。

Client 在连接握手时生成 `command_manifest`，其中加入 `acmd` 注册项和帮助候选，Web Terminal 使用它进行自动补全。典型候选数据：

```json
{
  "name": "acmd ps",
  "template": "acmd ps",
  "help": "Show running processes",
  "group": "acmd",
  "suggest": true,
  "source": "client"
}
```

Manifest 提供的是**当前连接的建议入口**，不是一整套动态参数 Form Rendering。浏览器仍需使用文本框输入参数，详细参数以 `acmd help <command>` 输出为准。连接之后如果 Client 注册情况变化，浏览器补全不保证立刻反映，需要重新获取新的连接握手信息。

## 执行环境和控制边界

Server 在收到 `acmd` 前缀后先生成结构化 Payload，再通过现有 Client 消息连接发送 `acmd` 消息；Client 由独立 Runner 调用 Registry。其执行仍绑定本次 `command_id`、取消与超时上下文，结果沿普通远程命令结果通道回传，Web 可以通过任务事件和 SSE 展示。

在 Web Terminal 发起的前台 ACMD 仍会受到 Client 前台任务占用约束。它不是能够绕过主执行槽的独立控制通道，也不提供 PTY 那样的持续交互输入会话。

取消与超时属于**协作式执行控制**：上下文可以记录取消请求并调用已注册的清理处理器，但 Registry 不会对任意 Handler 自动实现持续中断。如果 Handler 进入长时间阻塞调用而没有检查取消状态，不能保证发出取消后立即停止。ACMD 本身也不默认启动外部 Shell；命令 Handler 如何访问系统资源取决于它的实现及 Client 权限。

与普通 Shell-like 命令还有一个关键区别：**ACMD 参数不经过 Client 普通命令的 `${rch:*}`、`${env:*}`、`${path:*}` 自动插值链**。例如：

```text
acmd ps --pid ${rch:pid}
```

不能期待 `pid` 自动替换成 Client PID。Server 先把文本保留为字符串参数，Client 的整数校验会因无法转换而失败。需要变量支持时，不应直接套用 Shell-like 的插值规则；相关机制见 [RCH Variables](variables.md)。

## 调用失败时如何定位问题

| 现象 | 机制与处理方式 |
|---|---|
| 命令在某台机器可用，另一台不支持 | 平台注册不同，先使用 `acmd help` 确认目标 Client |
| 提示 Unsupported / Not found | 名称未在当前 Registry 中注册，ACMD 不回退到 Shell |
| `Missing required option` | 必填项没有提供，也没有可用默认值 |
| `Unknown option` | 选项未在当前命令 Schema 中声明，检查 `acmd help <command>` |
| 整数/浮点/布尔转换失败 | 输入无法转换成指定 `option_type` |
| 短别名与长名称重复报错 | 两种写法指向同一选项，避免同一请求中重复传递 |
| 参数带空格被拆开 | 使用引号，注意 `shlex` 分词与目标系统 Shell 不同 |
| 变量占位符没有展开 | ACMD 不应用普通 `command` 的自动变量替换 |
| 命令长时间不响应取消 | Handler 可能没有在长循环或阻塞操作中及时检查取消 |
| 自动补全没有新命令 | Manifest 来源于 Client 当前连接提供的注册信息 |

ACMD 的长期使用方式是先通过 `acmd help` 了解当前平台的命令，再通过 `acmd help <command>` 查阅具体参数，并使用少量有代表性的示例理解语法。文档不把当前 Registry 的内容冻结成产品契约，以免未来增删命令时出现过期说明。
