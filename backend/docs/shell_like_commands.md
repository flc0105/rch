# Shell-like Commands

普通远程命令先在 Server 区分管理入口与目标 Client 执行，再通过 `command` 消息交给 Client。Client 进行运行时变量展开和导出命令查找；匹配到方法时按该方法的原始参数契约执行，否则将命令交给目标系统 Shell。这一路径保留系统 Shell 的灵活性，也保留 Client 内建方法的专门行为。

Shell-like 没有 ACMD 那套全局参数 Schema。命令方法使用装饰器声明帮助、确认、超时和取消策略，前台任务负责输出与终态。调试时应按 Server 解析、Client 方法查找、系统 Shell 回退、执行生命周期的顺序定位，而不应假定每条命令都经过相同的引号与选项解析。

## 普通命令从 Server 到 Client 的路径

普通命令从输入到结果通常经过以下过程：

```text
Web Terminal / Server CLI
          ↓
Server：内置命令判定 → Alias 解析 → 普通远程命令计划
          ↓
Client 连接：command 消息（命令文本、command_id、执行选项）
          ↓
Client：运行时变量展开 → 解析命令名称和剩余参数
          ↓
     已导出的 Client 方法？
        ├─ 是 → 调用对应内置方法
        └─ 否 → 将完整命令交给系统 Shell
          ↓
Client：结果 / 中间输出 → Server → Terminal
```

Server 与 Client 的职责要分开理解。Server 的 `alias`、`history`、`upload`、`httpctl` 等入口属于 **Server Built-ins**，会先在 Server 层处理；不是所有看起来像命令的文本都会直接发往 Client。Alias 解析后产生的远程命令仍使用普通 `command` 消息。没有命中 Server Built-in 或 Alias 时，才走默认远程计划。Server 还会优先识别 `acmd` 并改用专门的结构化消息，详见另一篇文档。

Client 的普通执行路径不需要为每一个系统命令预先注册处理器。例如目标机上的 Shell 可以执行 `echo`、`ls`、`dir` 或其他已安装程序；相反，`cd` 这类需要影响 Client 工作目录的功能可以由内置方法直接处理。

普通命令与 ACMD 都使用 Client 的主要命令处理链，和 Script 一样属于延迟执行的消息；它们不等于另一个独立的后台控制通道。同一 Client 上多个前台 Web 操作还会受到 Server 前台任务忙碌控制的影响。每次执行都拥有独立的命令上下文，记录超时预算、取消策略以及命令结束状态。

## 命令识别及参数传递语义

### 原始参数的保留方式

基本形式为：

```text
<command_name> <raw_arguments>
```

Client 会识别第一个命令名称，并保留后面参数的原始字符串。与 ACMD 不同，通用 Shell-like 入口**不会**自动把 `--name value` 解析成统一的字典，也没有针对每条命令的一套公共字段校验规则。参数如何解释，由匹配的内置方法或目标系统 Shell 决定。

例如：

```text
cd /tmp
```

当当前平台提供 `cd` 内置方法时，操作会直接更新 Client 进程的工作目录。随后执行的命令可受到这次目录切换影响。若在 Shell 中另外执行 `shell cd /tmp`，它只改变临时 Shell 子进程的工作目录，不能用来永久更改 Client 自身的目录。

对于内置命令，当前分发逻辑调用公开的方法：方法需要参数时，将整段 `raw_arguments` 作为一个字符串传入；无参数方法则不传实参。**不会**因为某个方法恰好存在但未导出，就把它当作可调用内置命令。命令名称应使用实际导出的名称；平台和版本不同，内置方法集合也可能不同。

### 落到系统 Shell 的条件

以下示例在目标环境具有相应命令时，可以直接执行：

```text
whoami
```

如果 `whoami` 没有匹配到导出的 Client 内置方法，整条 `whoami` 会回退给目标系统 Shell。需要更明确地指定执行 Shell 内容时，可写：

```text
shell echo "Hello from Client"
```

`Shell` 回退使用的是**目标 Client 所在系统的 Shell**，而不是浏览器或 Server 的 Shell。它遵循目标操作系统的命令语法、引号、变量、管道、重定向以及可执行文件查找规则。Unix 和 Windows 的语法并不一定相同。解析时会保留原始参数字符串，因此不要把它当成通用的 POSIX 命令行转换器。

Server 的命令层同样拥有自己的快捷入口和历史重放。例如 `!<index>` 会由 Server 改写为历史执行请求；这不是发送给远端 Shell 的特殊语法。不同来源的命令在历史中保留各自的提交记录，不能把 Server 命令、Client 内置命令和操作系统 Shell 命令混为一个注册表。

## 客户端内建操作与扩展方式

普通命令的内置方法通过导出描述注册为可执行入口。它们可以处理操作系统调用、文件和进程管理、运行时设置等任务，也可以按需发送中间结果。平台命令基于当前操作系统加载，部分能力只存在于特定平台。

下面只通过几种典型行为说明执行模式，不维护固定的命令清单；实际可用入口始终以目标 Client 的 `help` 输出为准。

| 典型入口 | 行为 | 与其他方式的区别 |
|---|---|---|
| `shell <command>` | 启动一次性 Shell 子进程，收集最终输出 | 使用受管理子进程，可请求取消 |
| `read <command>` | 启动 Shell 子进程，持续推送 stdout/stderr | 使用受管理子进程，可请求取消 |
| `spawn <command>` | 启动后台进程并立即返回 PID | 不等待执行完成，也不提供本次命令的持续取消能力 |
| `cd <path>` | 修改 Client 自己的当前工作目录 | 后续命令可观察到目录变化 |

例如：

```text
shell echo "ready"
```

适合较短、只需最终结果的操作；命令运行期间进程结束后才汇总响应。若需要运行可能持续输出的程序，可以改为：

```text
read ping 127.0.0.1
```

该示例适合观察分段输出，但 `ping` 的参数与退出方式由目标平台决定；长时间运行仍受超时和取消条件限制。这里的 `read` 是**输出流模式**，不是打开可交互的 PTY；其标准输入被关闭，不能像终端那样继续输入内容。

另外：

```text
spawn echo hello
```

会尝试在后台启动命令并报告进程 PID，不代表该命令最终成功完成。后台进程的标准输入、输出和错误输出不会继续由当前命令收集。

Python 执行也有收集输出与流式输出两种入口，其运行模式由 Client 的 Python Runtime Configuration 决定。`inproc` 在当前解释器中执行，不可强制杀停；`subprocess_pipe` 在受管理子进程中运行，支持取消与进程终止。执行策略会在运行时设置相应的取消能力，而不是仅靠命令名称判断。这些入口仍属于普通命令体系，但和 `script` 协议的完整脚本运行流程不是同一件事。

### 导出命令方法

普通命令使用 **Client 命令类的公开方法 + `@desc` 导出**，无需定义 ACMD 的参数 Schema。最简单的形式如下：

```python
from core.utils.decorator import desc

class CommandExampleMixin:
    @desc('Show a short greeting', group='general')
    def greet(self, arg=''):
        name = str(arg or '').strip() or 'world'
        return 1, f'Hello, {name}'
```

将方法放到当前 Client 对应的命令类或现有 Mixin 后，即可被普通命令派发查找。如果新建 Mixin，需要把它加入 `client/commands/common/groups.py` 中的相应公共命令组，让当前平台命令类实际继承该 Mixin。对于只适用于某一平台的功能，应放入该平台命令类。方法名就是命令名，`@desc` 是可导出标记；只有定义了 `help` 元信息的方法才被普通命令派发器视为内置命令。

例如上例可以执行：

```text
greet Alice
```

Client 将剩余的 `Alice` 作为完整字符串 `arg` 传入方法，方法返回 `(1, 'Hello, Alice')`。与 ACMD 不同，这里没有自动解析 `--key value`、默认值或数字类型。使用原始参数的命令应自行检查语法、缺失参数以及业务边界。零参数方法可以写成 `def greet(self)`；分发器会根据方法签名决定是否传入原始参数。

**扩展命令时应优先复用已有公共能力**，需要返回失败时使用 `(0, error_message)`；业务内部异常要按需要处理，不应把参数校验失败默认为成功。新增命令后以连接到目标 Client 的 `help` 或 Web Terminal 实际运行结果检查导出和平台可用性；是否出现在推荐补全还取决于 `suggest`。

### 装饰器与运行控制声明

普通命令目前相关的声明式注解包括以下四种，它们各自负责一项独立行为：

| 注解 | 用途 | 关键参数与行为 |
|---|---|---|
| `@desc(text, group='general', suggest=True, api_grants=())` | **导出命令**，描述帮助文本和补全分类 | `text` 是帮助说明；`group` 用于 Help 分组；`suggest=False` 不进入推荐列表但仍可以执行；`api_grants` 为该命令申请受限 Web API 授权范围 |
| `@confirm(message=None)` | 执行方法体**之前**请求 Web 确认 | 不传参数时生成默认提示；同意才进入原函数，拒绝、超时或没有可用交互时返回失败；自动附加 `interactions:request` Grant 声明 |
| `@timeout(seconds)` | 声明命令默认的正数超时预算 | 请求方指定的有效超时只可缩短预算；这是执行上下文的期限，不保证强制终止任意 Python 代码 |
| `@cancel_policy(mode='none', message='')` | 声明命令可以采用的取消机制 | `none` 不接受取消；`cooperative` 在检查点响应；`process` 用于实际由命令管理的子进程；`message` 是取消不可用等情况的解释文本 |

`@desc` 可以和其他注解组合使用，且 `@confirm` 会保留原方法的帮助及授权元数据，**`@desc` 和 `@confirm` 的上下顺序均可工作**。`@timeout` 与 `@cancel_policy` 只设置方法元信息，由统一执行器在调用前应用；它们不会在函数外包一层自动杀停线程的逻辑。`@confirm` 则是执行前的实际包装，会在未批准时直接阻止方法体执行。

例如，为一个会短暂执行的普通命令指定默认预算和协作取消：

```python
from core.utils.decorator import desc
from client.commands.runtime.interrupts import timeout, cancel_policy

class CommandExampleMixin:
    @desc('Perform a bounded demonstration', group='general')
    @timeout(60)
    @cancel_policy('cooperative', message='The operation must reach a checkpoint')
    def bounded_demo(self, arg=''):
        self._checkpoint()       # 进入可协作取消的检查点
        # 在实际的耗时循环、文件 I/O 阶段也需要继续设置检查点。
        return 1, 'Done'
```

这里的 `60` 秒是命令自身的默认预算。`cooperative` 只是允许取消和检查点生效；如果在耗时循环中从不再次检查，命令仍可能无法及时停止。`process` 也**不是**把任意 Python 方法自动移到新进程执行；只有实际使用受管理子进程及其终止清理机制，才具备对应能力。没有声明时，普通内置方法的取消模式默认为 `none`。

`@argument_command(...)` 属于另一个体系：它注册的是带参数规格的 [ACMD](acmd.md)，不会把该 Handler 自动作为 Shell-like 命令导出。普通命令不需要它。

### 请求用户交互的命令代码

如果只需要“批准后才运行方法体”，直接叠加 `@confirm` 最简洁：

```python
from core.utils.decorator import desc, confirm

class CommandExampleMixin:
    @desc('Show an approved demonstration', group='general')
    @confirm('Continue this harmless demonstration?')
    def approved_demo(self):
        return 1, 'Approved and executed'
```

运行 `approved_demo` 时，系统先通过当前 Web Task 发出确认，只有用户明确批准才调用方法。`@confirm` 自动申请命令交互所需的 `interactions:request` 范围；单独写一个没有 `@desc` 的私有方法不会变成可远程执行的命令。

如果需要自定义文本输入、选择或先展示计划再批准，则在命令内部显式使用 `CommandInteractions`，并在 `@desc` 中声明交互 Grant：

```python
from core.utils.decorator import desc
from client.commands.common.services.interaction_service import (
    CommandInteractions, CommandInteractionError,
)

class CommandExampleMixin:
    @desc('Choose a demonstration label', group='general',
          api_grants=('interactions:request',))
    def choose_label(self, arg=''):
        ui = CommandInteractions(self)
        try:
            label = ui.select('Choose a label:', ['Alpha', 'Beta'], title='Choose')
            if not ui.confirm(f'Use {label}?', title='Confirm label'):
                return 0, 'Not approved'
        except CommandInteractionError as exc:
            return 0, f'Interaction unavailable: {exc}'
        return 1, f'Selected {label}'
```

Server 会从可信的命令定义读取 `api_grants` 并为当前命令生成临时授权；只有 Client 自己声明、但 Server 不认识的命令，不能仅靠上报 Manifest 就获得授权。交互必须绑定正在运行的 Web Task；Server CLI 或脱离 Web 前台任务的调用未必有可回应的页面。输入与 Preview 请求在原命令中等待，不会嵌套执行另一条命令。更完整的 `confirm`、`input`、`secret`、`select`、Preview（含勾选行和开关）、Script 使用方法见 [Interaction Broker](interaction_broker.md)。

### 状态与结果通道

内置方法通常返回成功状态及结果内容；某些支持结构化输出的内置方法可以返回字典或表格，并按自己的规则选择文本或 JSON 表示。部分命令接受 `json` 或 `--json` 作为输出格式参数，例如：

```text
watchdog --json
```

这只是针对**支持该格式的具体命令**的示例，不能把 `--json` 理解成所有普通命令的通用开关。

## 变量展开和附加数据载荷

### 变量替换的发生位置

普通 `command` 消息会在 Client 端进行一次变量展开，支持 `${rch:*}`、`${env:*}`、`${path:*}` 三种命名空间。Server 不负责替换成自己的值。

```text
shell echo ${rch:hostname} ${rch:pid}
```

这会显示目标 Client 的主机名和 PID。也可以将路径变量用于内置方法：

```text
cd ${path:downloads}
```

`cd` 收到的是完整的原始参数字符串，所以路径含空格时通常不需要为它额外添加 Shell 引号；直接添加双引号反而可能把引号当作路径的一部分。若改为 `shell ls "${path:downloads}"`，才是将带引号的文本交给 Shell，由 Shell 解释路径。变量系统只做文本替换，**不是一套自动 Shell 安全转义器**。环境变量值可能包含 Shell 特殊字符，将其拼入将要执行的系统命令时必须考虑命令注入和泄露风险。引用缺失变量、未知命名空间等问题会在派发前报错，后续命令不会执行。

变量完整定义和执行边界见 [RCH Variables](variables.md)。**ACMD 和 Script 不自动走这条普通命令字符串展开链**。

### 附加结构化负载

部分由 Web 发起的远程文件、任务或上传操作，外层仍采用普通命令入口，但内部参数本来是一个对象或列表。为避免用空格拆分复杂 JSON，相关操作会把内容编码成类似下面的单个参数：

```text
__json__:<base64url-encoded-json>
```

接收该格式的专用内置方法会解码并处理原始结构。这不是给所有普通命令开放的一套通用对象 Schema，也不意味着 Shell 本身理解这种格式。日常终端操作无需自行构造这一负载；对应 Web 功能会按既定协议生成。

## 前台任务的输出与终止语义

Client 为每次命令建立带 `command_id` 的独立执行上下文。上下文保存开始时间、有效超时预算、取消事件、取消策略以及清理回调；命令返回或抛出异常后才进入最终完成状态并释放上下文。Server 以相同命令 ID 关联请求、中间输出、最终结果以及取消反馈，Web Terminal 则利用任务事件和 SSE 展示执行过程。

### 超时预算与输出流

普通结果通常包含成功/失败状态与文本。流式命令会多次发送中间结果（`eof=0`），最终才发送结束结果（`eof=1`）。因此已经收到输出，不代表任务已经完成。`spawn` 返回 PID 也仅代表后台进程已启动，不是执行成功的最终证明。

一次性 Shell 的默认超时为 30 秒，流式 Shell 的默认超时为 300 秒；这些默认值来自当前运行配置，也可能被具体命令的默认预算取代。通用 `COMMAND_DEFAULT_TIMEOUT` 是**没有专用预算时的兜底**，默认不设置，并不会覆盖 Shell 自己的 30/300 秒。

一次执行可以通过 Server 的命令消息 `extra` 明确携带 `timeout` 或 `_timeout`。当命令声明了默认预算、且请求同时指定上限时，Client 采用两者中**较短**的有效预算；不能靠请求参数把已声明的较短限制延长。预算按该命令开始执行后的时间计算，执行到受控 I/O 或检查点时才能检测到超时；不能理解为在指定秒数之后强制中断任意 Python 代码。

### 取消请求到实际停止

普通命令的取消策略分为三种，取决于所选执行方法：

| 策略 | 行为 | 使用场景 |
|---|---|---|
| `none` | 不接受取消请求 | 未声明取消能力的普通内置方法默认如此；In-process Python 也使用此策略 |
| `cooperative` | 接受取消请求，需在检查点或可中断 I/O 中响应 | 部分文件操作、安装和清理流程 |
| `process` | 接受取消请求，可通知所管理子进程终止 | `shell`、`read`，以及 Subprocess Python |

每个内置方法可以声明默认执行预算与取消策略；Client 在调用方法之前统一设置这些属性并执行一次中断检查。没有配置策略的内置命令默认是 `none`，不能因为它运行在普通命令链中就假定支持取消。未知命令回退到系统 Shell 时，采用与 `shell` 相同的受管理子进程策略。部分 HTTP 文件传输和 Python 执行则会在实际选定运行策略后，动态确定可取消性。

取消存在明确的先后状态，不能混为一谈：

1. Server 发出请求后可先记录 `requested`，这只表示取消请求已经发送。
2. Client 判断当前操作允许取消后，才通过 `cancel_ack` 确认 `accepted`；不支持的操作会拒绝请求。
3. 命令实际观察到取消并返回后，终态才能成为 `stopped`。如果它没有响应取消却正常执行完毕，终态是 `completed`。

请求被接受不会立刻证明命令已停。受管理 Shell 子进程会在取消或超时时尝试终止；Unix 通常优先处理整个新建进程组，Windows 对所管理的进程执行终止。对于没有检查点的长时间 Python 循环、阻塞调用或已经脱离本次命令的后台 `spawn`，不能承诺立即停止或递归终止所有后代。取消终态与 Watchdog 的强制控制也没有等价关系。

`@confirm` 对应的交互确认是独立机制，用于在执行特定敏感操作前得到操作者许可；确认是否通过和命令是否支持取消、超时预算是多少，是三项不同的问题。命令中的声明式注解和授权接入方式见第三节；Broker 的审批与输入机制见 [Interaction Broker](interaction_broker.md)。

普通命令、ACMD 和 Script 共用前台任务编排时可能发生 Busy 状态。普通命令链不会为每次 Shell 回退自动创建可持续输入的终端会话；需要交互式终端应使用 [PTY](pty.md)。

## 命令发现与 Terminal 反馈

在连接到 Client 的终端中执行：

```text
help
```

可查看当前 Client 导出的命令及说明；Help 按领域分组，也会展示当前平台注册的 ACMD 条目，但不是一个固定、跨平台通用的命令列表。部分内部导出命令可以执行，却故意不进入 Help 的推荐列表。

Client 建立连接时会上报 `command_manifest`，包含导出命令的名称、帮助信息、分组、是否推荐等属性，并追加 ACMD 候选。Web Terminal 将这些信息与 Server Built-ins、Alias、Script、历史记录以及变量候选一起用于自动补全。

因此自动补全列表并不等于一个静态的命令规范，更不代表所有候选都由 Client 执行；同样，某个命令没有作为推荐候选出现，也不一定说明底层不存在对应实现。变量候选来自连接时的定义清单，实际变量值仍在执行时解析。

Web Terminal 可以保存命令历史、展示流式输出，并在收到完整 JSON 对象或对象列表时选择合适的表格/键值展示；是否会出现结构化视图取决于**实际返回的数据内容**，而不是 Shell-like 入口本身自动返回 JSON。

## 运行安全和异常定位

| 现象 | 机制与排查方向 |
|---|---|
| 输入了命令却没有匹配内置方法 | 未命中已导出的名称会回退到系统 Shell；检查它是否为目标系统可执行命令 |
| 同一命令在 Windows 与 Unix 行为不同 | 回退后采用各自 Shell 的语法、环境和命令路径 |
| `cd` 后目录没有变化 | 检查是否执行了 Client 的 `cd`，而非只在临时 Shell 中执行 `cd` |
| `${rch:*}` 展开失败 | 查看变量名称与命名空间；展开失败时命令在派发前中止 |
| 路径带空格报错 | 内置方法收到原始参数，Shell 另行解析引号；不要把两类命令的引号规则混用 |
| `read` 已输出，但任务仍运行 | 中间结果不是最终退出状态；等待最终结果或按当前策略请求取消 |
| `spawn` 返回 PID 后看不到后续输出 | 后台进程脱离本次输出采集，返回 PID 不是完成证明 |
| 取消显示 accepted，但命令仍在运行 | ACK 只表示取消被接受；等待 stopped 或 completed 的真正终态 |
| 超时后命令仍未停止 | 检查是否进入过取消/超时检查点以及是否使用受管理子进程 |
| 终端提示 Busy | 前台命令槽被占用，不是 Shell-like 另有一条绕过主通道的路径 |
| 需要交互输入密码、操作 vim/top | 一次性或流式 Shell 不提供交互式终端，改用 PTY |

内置命令和系统 Shell 都以目标 Client 的执行身份运行，实际可访问范围由操作系统权限和相应方法决定。远程执行不等于限制在一个专用文件系统沙箱内；执行删除、覆盖、进程控制等命令前，应先确认目标和作用范围。
