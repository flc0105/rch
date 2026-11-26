# ACMD — Argument Commands

ACMD 将终端输入解析为可验证的参数对象，再交给目标 Client 已注册的 Argument Command Handler。命令名称、参数类型、短别名、位置索引和帮助文本都来自客户端注册契约；Server 负责 ACMD 路由与参数传输；Client 统一解析 `--format/-f/--json`，按现有 Spec 校验业务参数，并返回本次结果的原始数据与所选展示方式。

这种机制与普通 Shell-like Command 共享 Client 的执行通道，却使用独立的命令注册、验证和 Help 体系。理解其运行过程，应沿着输入解析、Schema 约束、注册查找和结果返回的顺序阅读，而不是记住一份随平台变化的命令总表。

## 解析入口与派发路径

执行流程如下：

```text
Web Terminal / Server CLI：acmd <name> ...
                 ↓
Server：识别 acmd 并将完整命令和参数交给目标 Client
                 ↓
Client 连接：acmd 消息 + 结构化 Payload
                 ↓
Client：按当前平台查 Command Registry
                 ↓
Client：对参数中的 RCH Variables 展开（目标 Client 的当前值）
                 ↓
有注册及参数定义 → 别名/位置参数处理 → 业务参数及展示选项校验与类型转换
                 ↓
调用命令 Handler → 返回原生 data 或 message，按本次结果声明 presentation
                 ↓
Server：按 Result.presentation 渲染终端文字并保留原始结果
```

例如：

```text
acmd ps --name python --json
acmd ps --pid ${rch:pid} --json
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

Server 保留输入命令原文，`extra.args` 也包含 `--json` 或 `--format/-f` 对应的参数。Client 在注册表中统一解析展示选项；Handler 继续只接收业务参数。业务参数仍按原有 Spec 完成别名、布尔值和整数转换。

`acmd` 走独立的 `acmd` 协议消息类型，不使用普通 `command` 的字符串分派，也不会在找不到处理器时交给系统 Shell。命令是否可执行，取决于目标 Client 的操作系统平台和当前注册内容。

ACMD 的正式命令注册入口放在 `client/commands/acmd/common/` 或 `client/commands/acmd/platform/`。每条命令只定义一份 `ArgumentCommandSpec` 和一份带 `@argument_command` 的模块函数。复杂命令可将 Spec 和实现一起放在 `acmd/standalone/` 独立文件，再由所属 Common / Platform 模块的 `register_commands(registry)` 显式注册；仅导入 Standalone 不会增加命令。Catalog 只加载当前平台对应的归属模块并调用其注册入口。`platforms` 控制 Common 命令的支持范围，Platform 模块负责专属归属。

## 文件查找、下载和检查

Python Client 的 Windows、macOS、Linux、iOS 都注册以下命令：

- `acmd find [path] --keyword <value>` 从当前目录或指定目录递归搜索文件和目录名。普通关键词按子串匹配，`*.jpg`、`img_*.png` 等通配符按完整名称匹配，两种模式均忽略大小写。终端里给通配符加引号。
- `acmd wget <url> [-o <path>]` 下载 HTTP、HTTPS 或 FTP URL。默认保存到 Client 当前目录，可指定输出文件或目录。未指定文件名时优先采用响应给出的文件名，再取最终 URL 路径，最后使用 `download.bin`。下载期间显示简短进度，成功后显示可读大小和实际路径。只有完整下载才会替换目标文件。
- `acmd sqlite_query --db <path> --query <sql>` 只读查询 SQLite，支持 `--json`。`acmd image_info <path>` 读取图片元数据，使用 Client 内的 Pillow，也支持 `--json`。
- `acmd python_packages [--loaded/-l | --import <module-or-distribution>] [--filter <keyword>] [--format/-f <layout>]` 查询当前 Client 的 Python 环境。默认显示已安装发行包名（Lines）；`-l` 显示当前解释器已加载模块所对应的发行包名（Lines），`--filter` 按发行包名匹配。Table、Records 和 JSON 使用同一份含版本号的发行包记录；Lines 仅显示发行包名。`--import` 保持原模块/发行包导入检查行为，会执行 Python 模块顶层代码，详情支持 Flat/KV/JSON。
- `acmd archive_peek <path> [--limit <count>] [--json]` 只读显示 ZIP/TAR 的目录树。ZIP 与 Remote Files 复用预览读取和树构造。默认预览 50 个归档条目，`--limit` 可指定 1–5000。JSON 给出归档名称、格式化大小和目录树，只有截断时输出 `truncated: true`。

## 本机提示框与通知

Windows、macOS 和 iOS 的 `acmd msgbox` 和 `acmd notify` 共用 `--message <text>` 和可选的 `--title <text>`。消息显示在目标 Client 的本机图形会话或 Pythonista 中。系统通知权限与专注模式影响通知的可见性。Windows 在将请求交给本机通知队列后即完成命令，终端可继续执行下一条。`alert`、`tree`、`head`、`tail` 仍由 iOS 入口注册。

## Process ACMD：Kill 与 PS

以下进程管理 ACMD 注册于 Windows、macOS 和 Linux Client；iOS / Pythonista 不注册 `acmd ps` 或 `acmd kill`。

Process Manager UI 使用 `control/process/kill`，传入结构化 PID；ACMD `kill` 保持交互审批入口。
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

`acmd zip` 与 `acmd unzip` 是四平台共用的 Standalone 文件命令，只在 ACMD Common 注册。路径可以写成位置参数 `<path>` 或 `--path <value>`。`acmd zip` 默认把压缩包保存在源路径的父目录；`--dest/-d` 指定现有输出目录，`--name/-n` 指定文件名（未带 `.zip` 时自动补齐）。已存在的 ZIP 不会被覆盖，ZIP 也不能创建在正在归档的目录内部。正常完成时只输出文件数、可读大小、耗时和压缩包路径；`--verbose/-v` 才发送逐文件进度。

不可读的 ZIP 输入默认报出具体路径并终止，不保留半成品。显式 `--skip-unreadable` 才允许跳过权限拒绝的文件或目录，终端会提示每一项跳过原因，结果会标记为部分归档并显示跳过数；所有文件均不可读时仍失败。

`acmd unzip` 默认解压到当前工作目录，可用 `--dest/-d` 指定现有目录。原有冲突策略 `--conflict stop/skip/keep_both/merge/replace` 保持不变；`--merge` 和 `--skip` 是对应策略的快捷参数，且不能同时使用多个冲突选项。成功时只显示文件数、可读大小、耗时和解压路径；目标已存在且选择跳过时显示简短跳过提示；`--verbose/-v` 才显示逐文件进度。解压继续执行安全路径、条目与大小检查，并通过暂存区提交。归档命令默认只输出简洁文本；它们的纯消息结果不因展示选项变成结构化数据。Remote Files Browser 仍使用共享归档服务的原有调用方式。两条命令的参数详情见 `acmd zip --help`／`acmd unzip --help`。

`acmd netstat` 在 Windows、macOS、Linux 上查看 TCP/UDP 连接，默认显示全部可读取的连接。可用 `--port 443`（或位置参数 `443`）按本地／远端端口过滤，`--status LISTENING`（或 `-l`）仅看监听状态，`--protocol tcp`（或 `-t`）、`--protocol udp`（或 `-u`）按协议过滤。支持组合条件，如 `acmd netstat -l -t --port 443 --json`；监听状态同时识别系统返回的 `LISTEN` 与 `LISTENING`。`-t` 和 `-u` 不能同时指定，`--json` 保持原有结构化表格输出。

`acmd ifconfig` 在 Windows、macOS、Linux、iOS 上提供相同的 `name/ip/mac` 默认表格，
沿用原有的常用网卡筛选。`--all/-a` 展示全部网卡并增加 `virtual`（虚拟网卡状态）
及 `enabled`（启用状态）列；无法可靠识别虚拟类型时显示 `unknown`。
`--interface/-i` 精确匹配网卡名，可与 `--all`、`--json` 组合；`--help/-h` 查看参数。
桌面端使用 psutil，iOS 使用系统 `getifaddrs`。

- `acmd kill` 无目标时先通过 Interaction Broker 询问 `pid/name/port`
  和目标值，再 Preview。指定目标时直接 Preview 所有匹配 PID，
  可取消单条勾选；Force 初始状态由 `-9/--force` 决定。
- `--no-confirm` 必须指定目标，不发起任何交互。`--force` 仅决定使用
  `SIGKILL`，未指定时使用 `SIGTERM`。不从未确认的自由文本猜目标。
- `acmd ps` 支持 `--pid/--name/--port`；进程数据始终保留 `pid / ppid / name / username / status` 五个字段。指定 `--with-actions` 时，在结果级 `view.actions` 中声明一次 Kill 模板；默认不附加 `view`。操作按钮由 JSON Viewer 展示，Terminal 表格和数据字段不变。

- 进程选择和发信号都在 Client 执行。不预设 PID 白名单或进程保护名单；
  操作系统权限仍决定实际信号是否成功。对 PID 创建时间、名称、可执行
  文件和端口归属进行重检，拒绝预览后身份发生变化的进程。
  当前连接的 Client Session Token 允许 ACMD 使用 Interaction；`--no-confirm` 不发起交互。

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

`--json` 与 `--format json` 等价，`--json=false` 使用本次结果默认方式。`--format/-f/--json` 在 Client ACMD Registry 中统一解析；`-f` 始终表示 `--format`，`acmd kill` 使用 `-9/--force`。Client 按本次结构化结果支持的布局校验选择，不兼容时返回英文错误。业务 Flag 保持 `true/false`、`yes/no`、`on/off`、`1/0` 转换。

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

ACMD 的正式命令表由目标 Client 当前平台的 Common / Platform 模块显式注册，Server 不维护固定 Client 命令清单。注册时直接从装饰函数读取名称、唯一 Spec 和 Handler，Registry 负责平台筛选、参数验证、Help 与执行分派。

注册关系的典型形式是：

```python
@argument_command('example', spec=EXAMPLE_SPEC)
def example(context, args_dict, payload=None):
    ...

def register_commands(registry):
    registry.register(example)
```

这段只是演示处理器与 Schema 如何绑定，并不表示系统当前有 `example` 这个命令。Handler 收到的是已归一化的参数字典，并可根据签名接收完整 Payload；它通常返回 `(status, result)`，其中 `1` 代表成功，`0` 代表失败。

不同平台加载各自的归属模块，因此 Windows、macOS、Linux、iOS 的可用 ACMD 可以不同；Common 中声明的平台范围同样参与筛选。未注册名称不会退回 Shell，通常会返回：

```text
acmd command not supported on this platform: <name>
```

注册表负责业务参数验证、帮助和分派；Handler 负责实际操作和本次结果的数据语义。普通反馈仍返回状态与 `message`；结构化查询返回原生 `data` 及结果级 `presentation`（`source/default`、可选 `requested` 和必要字段映射）。`formats` 仅用于 Client 本地检查本次结构化结果，不经 Result Wire 发送。Server 和 Activity 都从 Result 的 `presentation` 渲染，History 只保存原始 Result。

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
  "help": "Show running processes",
  "group": "acmd",
  "suggest": true,
  "source": "client"
}
```

Manifest 提供的是**当前连接的建议入口**，不是一整套动态参数 Form Rendering。浏览器仍需使用文本框输入参数，详细参数以 `acmd help <command>` 输出为准。连接之后如果 Client 注册情况变化，浏览器补全不保证立刻反映，需要重新获取新的连接握手信息。

## 执行环境和控制边界

Server 在识别 `acmd` 后发送原始命令文本及结构化参数，包含 `--format/-f/--json`；Client 由独立 Runner 调用 Registry，统一识别格式并校验业务参数，仍绑定本次 `command_id`、取消与超时上下文。结构化结果成功产生后，Registry 检查本次格式是否适用；不适用则返回英文错误，不自动改用其他格式。失败或纯消息结果直接显示 `message`。Result 的 `presentation.requested/default` 供 Server 和 Activity 通过同一个 Core Renderer 生成文字，Web 由现有任务事件与 WebSocket 展示。

在 Web Terminal 发起的前台 ACMD 仍会受到 Client 前台任务占用约束。它不是能够绕过主执行槽的独立控制通道，也不提供 PTY 那样的持续交互输入会话。

取消与超时属于**协作式执行控制**：上下文可以记录取消请求并调用已注册的清理处理器，但 Registry 不会对任意 Handler 自动实现持续中断。如果 Handler 进入长时间阻塞调用而没有检查取消状态，不能保证发出取消后立即停止。ACMD 本身也不默认启动外部 Shell；命令 Handler 如何访问系统资源取决于它的实现及 Client 权限。

ACMD 的参数在 Client 侧完成 RCH Variables 展开，随后才按参数 Schema 做类型转换。例如：

```text
acmd ps --pid ${rch:pid}
acmd kill --pid ${rch:pid}
```

这两条命令的 `pid` 都在目标 Client 上解析为当前主进程 PID，再进行整数校验。所有字符串选项和位置参数都支持 `${rch:*}`、`${env:*}`、`${path:*}`、`${var:*}`；解析失败时命令停止执行。命令名称与参数名称不会被插值，Script 代码仍需使用 Variables SDK。详见 [RCH Variables](variables.md)。

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


## 结构化查询格式

Client ACMD Registry 统一接受 `--format/-f/--json`，每条命令的 `ArgumentCommandSpec` 只描述业务参数。`ps/netstat/ifconfig/drives` 的结果声明支持 `table/records/json`；`python_packages` 根据实际查询结果分别支持安装列表 `lines/table/records/json`、已加载发行包 `lines/table/records/json`、模块详情 `flat/kv/json`。`launchd` 的默认反馈是 `message`，同时可显式请求 `flat/kv/json`；`archive_peek` 默认树状消息，可选 JSON 归档数据。这些是每一次 Result 的能力声明，而非固定命令级白名单。Client 在生成结构化结果后检查选定布局；不适用时以英文 `message` 报错，Result 仍保留这次查询得到的 `data` 和 `presentation` 供 History 记录及 Result JSON 查看。格式名称本身不合法时，仍由通用 Validator 在执行前拒绝。没有选择时使用本次结果的默认呈现。`acmd ps --json --with-actions` 将 Kill 声明为表级 `view.actions` 模板，业务数据仍为原生进程记录；Raw JSON 与终端文本格式不依赖动作元数据。

`acmd ps --json --with-actions` 的 Kill 模板设置 `refresh: true`：确认 Kill 并执行成功后，JSON Viewer 使用原 `ps` 查询重取进程列表。`confirm` 未声明时默认要求确认。刷新只改变当前 Viewer，不修改历史 Result。

### JSON Viewer 的结果级 View

ACMD 的结构化 Result 可以附带 `view`。它与负责终端文字布局的 `presentation` 并列：`titleField` 指定 Card 标题字段，`columns` 可为主表字段配置 `width` 或 `minWidth`（像素），`details` 将字段显示在可展开详情中；`actions` 是整张表共用的行操作模板，命令中的 `{field}` 引用当前行的原始字段值。Viewer 复用现有的执行确认、Terminal/New Dialog 和成功刷新功能；确认缺省开启，刷新缺省关闭。桌面默认 Table、可切换 Card；移动端默认 Card，前两项操作直接显示，余下操作进入 More。原生业务 `data` 不承载重复的逐行动作定义。
