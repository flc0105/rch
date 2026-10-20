# Command Registry & Extension Development

RCH 的命令扩展并不是“在某个表里添加名字”就完成。一个可使用的命令必须同时满足：**目标执行端有可调用的处理器、输入能够路由到该处理器、其运行契约与结果格式一致**。是否在帮助和补全中可见，则属于另一层能力发现。开发时应先确定命令应由 Server 处理，还是交给所选 Client 执行；在 Client 内部，还要区分普通 `command` 与结构化 `acmd` 两套注册方式。

本文以扩展开发为主，解释如何从一个方法接入到 Terminal 和 Web。现有命令如何运行、ACMD 全套参数语法及浏览器的候选交互，分别见 [Command Execution Pipeline](command_execution.md)、[Shell-like Commands](shell_like_commands.md)、[ACMD](acmd.md) 和 [Autocomplete](autocomplete.md)；这些机制不在这里重新逐项展开。

## 一、选择正确的命令入口

不同入口的“注册”含义不同，不能只根据终端里看到的文本形式判断。

| 需求 | 承载位置 | 定义与发现 | 执行路径 |
|---|---|---|---|
| 对所选 Client 执行一个通常接受文本参数的操作 | Client 普通命令 | 导出方法、`@desc`、平台命令对象的继承链 | `command` → Client `ShellCommandRunner` |
| 对输入参数做声明式校验与类型转换 | Client 结构化命令 | `@argument_command` + `ArgumentCommandSpec`，`ArgumentCommandRegistry` 收集 | `acmd` → `ArgumentCommandRunner` |
| 在 Server 上处理别名、历史、流程编排或 Web 控制 | Server Builtin | `BuiltinCommandHandler` 中的可调用方法；候选模板另行维护 | Server `CommandExecutor` 优先处理 Builtin |
| 将现有操作配置成一个快捷别名 | Alias | Server 的别名存储与解析器 | 解析别名后转成远程计划 |
| 运行存放在 Server Script Library 的 Python Script | Script | Script Library / Metadata | Script 请求与 Python 执行策略 |

普通 Client 命令不要求为每个参数声明 `ArgumentOptionSpec`。未命中普通导出命令时，当前 Client 的普通命令 Runner 会走托管的 Shell 后备执行；**ACMD 查找失败则直接报不支持，不会落到 Shell**。Server Builtin、Alias、Client 普通命令、ACMD 的优先级由 Server 执行规划决定，不由 Web 候选列表决定。

典型路径：

```text
Web Terminal / Server CLI
  └─ Server CommandExecutor.process_command()
       ├─ 命中 BuiltinCommandHandler 的方法 → Server Builtin
       └─ CommandPlanner
            ├─ acmd 前缀 → 结构化负载，Socket type=acmd
            ├─ 已配置 Alias → 展开到远程命令计划
            └─ 普通输入 → 远程 command 文本
                   ↓
             Client CommandExecutor
              ├─ ArgumentCommandRunner → ArgumentCommandRegistry
              └─ ShellCommandRunner → @desc 导出方法 / 托管 Shell
```

这描述的是普通命令入口；PTY、Monitor、Clipboard 等独立消息与会话服务不应为了“在终端里有个命令名”被塞进同一注册表。

### Server `job` 命令和专用 Client Job Control

Job Catalog、终端命令解析和参数模式验证由 Server 管理；新增 Server Builtin `job` 支持 `list/start/stop/ps/status/stop-all`。纯 `job list` 直接查 Server Catalog；其他子命令通过 `job_control` 独立协议类型交给 Client `JobManager` 执行。旧 Client 公开 `start_job`、`stop_job`、`jobs`、`jobs_ps`、`job_status`、`stop_all_jobs` 方法已移除，Client Command Manifest 与 Help 不再列出它们。客户端 Runtime、Web Job API、任务上报及原有 Shell fallback 保持。详见 [Background Jobs](background_jobs.md)。

## 二、普通 Client 命令怎样被导出

### 平台对象和继承链

`CommandCatalog` 根据本机 `get_local_identity().os_alias` 选择对应命令类，并懒加载、缓存实例。当前平台类继承 `CommonCommands`；通用能力经 `CommonShellCommands`、`CommonFileCommands`、`CommonRuntimeCommands` 聚合。平台专有方法可以直接写在对应平台类中。

因此，命令方法即便已经有 `@desc`，如果所在 Mixin 没有进入相应通用命令组，且平台类也没有继承它，执行器仍找不到它。跨平台功能通常放在领域 Mixin 中再接入 `backend/client/commands/common/groups.py`；只在某个平台有意义的功能，放在 `backend/client/commands/platform/` 的对应平台命令类中。复杂操作交给独立 Service，命令方法保留参数解析、执行上下文协调和结果转换。

### `@desc` 是导出契约

普通命令使用 `core.utils.decorator.desc`：

```python
from core.utils.decorator import desc

class CommandDiagnosticsMixin:
    @desc('Show a concise diagnostic message', group='session')
    def diagnostic_note(self, arg=''):
        text = str(arg or '').strip()
        if not text:
            return 0, 'Usage: diagnostic_note <text>'
        return 1, f'Diagnostic: {text}'
```

这是**新增扩展的示意代码**，并非项目已注册的现成命令。接入方式是在适当的 `Common*Commands` 继承列表加入 `CommandDiagnosticsMixin`，或者将方法放入已被继承的现有 Mixin，然后启动加载该命令类的 Client。

`@desc(text, group='general', suggest=True, api_grants=())` 将元数据挂在方法上：

- `help`：导出识别和帮助描述。**缺少 `@desc` 的普通方法不会作为普通 Client 命令被 ShellCommandRunner 分派**，哪怕它恰好是 public method。
- `group`：`help` 分组及 Command Manifest 的分类；不会单独决定权限或平台。
- `suggest`：控制是否出现在默认帮助/候选展示中。`suggest=False` 不会禁止执行，Manifest 中仍可能包含该项，由展示层过滤。
- `api_grants`：普通命令需要调用受授权 Client API 时声明的范围；单凭 Manifest 中的字符串不会让 Server 信任该声明。

普通 Runner 的调用约定是：先通过项目解析器分离首个命令名称及其余文本；然后以方法签名决定调用 `handler()` 还是 `handler(arg)`。因此普通命令更适合无参或**单段原始参数文本**；多值、可验证的选项建议使用 ACMD。命令返回一般为 `(status, result)`，其中 `1` 表示成功、`0` 表示失败；其他输出约定需与执行链保持一致。中间流式结果应复用 `CommandBase` 的 `_send_interim_result()` / `_send_info()` 等方法，并遵守 `command_id` 绑定，而不是自己创建 Web SSE 事件。

### 运行上下文与能力约束

命令实例由 `CommandExecutor` 绑定本次 `command_id`、`execution_context` 和命令运行时。开发一个可能阻塞的命令时，不能只给方法加个名字就宣称它可取消：执行方法应按需使用 `_checkpoint()`、`_set_timeout()`、`_set_cancel_policy()`、`_register_cancel_handler()` 和 `_register_cleanup_handler()`，并确保调用的 Service 处理同一生命周期。取消与超时的最终语义见 [Command Execution Pipeline](command_execution.md)。

如果业务希望返回机器可读对象，可以按命令执行器的结构化结果约定返回值；默认渲染和 `json` 输出模式见 [Structured Output](structured_output.md)。是否需要 Web 输入表单或文件选择器，不由 `@desc` 自动生成。

## 三、注册一个带参数规格的 ACMD

普通命令之外，结构化命令由 `ArgumentCommandRegistry` 管理。它在 Client 当前平台命令对象上扫描带有 `argument_command_name` 的方法，并保存 `handler + spec`；`@argument_command` 的职责是标记方法，最终能否加载仍取决于方法是否属于当前平台命令类。

例如定义一个只回显参数、便于验证接入的扩展示意：

```python
from client.commands.arguments.decorators import argument_command
from client.commands.arguments.models import ArgumentCommandSpec, ArgumentOptionSpec

DIAG_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='diag_example',
    description='Inspect one diagnostic label',
    options=[
        ArgumentOptionSpec(
            name='label', option_type='str', required=True,
            allow_empty=False, positional_index=0,
            help_text='Diagnostic label',
        ),
        ArgumentOptionSpec(
            name='json', option_type='flag', default=False,
            help_text='Request machine-readable presentation',
        ),
    ],
    examples=['acmd diag_example my-service'],
)

# 定义在真正由当前平台命令类继承的方法集合中：
@argument_command('diag_example', spec=DIAG_ARGUMENT_SPEC)
def _acmd_diag_example(self, args_dict, payload=None):
    return 1, {'label': args_dict['label'], 'json': args_dict['json']}
```

以上是注册形态的**示意**，不是一个可直接在文件顶层粘贴使用的完整类定义；装饰的方法应作为对应命令类或其 Mixin 的实例方法，且必须保证业务实现确实符合声明的含义。

实际链路为 `CommandPlanner.parse_argument_command()` 解析文本 → Socket `acmd` 附带 `extra` 参数对象 → Client `ArgumentCommandRunner` → 注册表 → Validator → Handler。`name` 是命令查找键，`ArgumentCommandSpec.name` 应与装饰器名称一致，以免执行和帮助信息描述两个不同名称。Handler 接受已归一化的 `args_dict`，如果定义了两个参数还可以接收原始 `payload`。

Schema 可声明 `str`、`int`、`float`、`bool`、`flag`，以及默认值、必填、空文本、短别名和位置索引。Validator 会处理类型、未知选项和别名冲突，并将失败转为错误结果；Command Help 则从同一份 Spec 生成。具体选项行为、`acmd help`、转义与命名/位置参数的完整使用方法见 [ACMD](acmd.md)，避免在两个文档维护两套相同说明。

需要注意：ACMD 注册表在 `CommandCatalog.get_argument_command_registry()` 第一次调用时建立并缓存。新增 Handler 后，**通常需要启动新的 Client 命令运行时并重新握手**，不能假设动态修改源码、重新打开下拉框就会重建这份 Registry。

## 四、Server Builtin 不是 Client Registry 的一部分

Server 命令入口由 `BuiltinCommandHandler` 提供。`server.application.command.executor.CommandExecutor` 首先检查 `BuiltinCommandHandler.resolve_builtin_command(name, arg)`：如果处理器对象上存在同名可调用方法，就把它当作 Builtin；否则再进入 Planner 的 ACMD、Alias 或默认远程命令路径。因此添加 Server Builtin 时应核对命名冲突，避免无意截获原本要发给 Client 的名字。

Builtin 由具体 Support Service 承担业务，Handler 提供调用入口。新增时通常分成两处：

1. 在 `BuiltinCommandHandler` 增加实际可调用方法，按 Server 命令执行器所消费的结果迭代器约定返回状态和消息；需要分多段输出时逐段 `yield status, message`。
2. 需要出现在 Web 顶层命令候选时，在 `BuiltinCommandHandler.WEB_COMMAND_TEMPLATES` 增加 `name`、`template`、`help`、`source='server'`。**模板只负责展示；单独添加候选不会创建可执行的 Builtin。**

例如一个不产生外部副作用的示意方法：

```python
def server_note(self, arg=''):
    message = str(arg or '').strip()
    if not message:
        yield 0, 'Usage: server_note <text>'
        return
    yield 1, f'Server note: {message}'
```

同名处理方法需要定义在 `BuiltinCommandHandler` 上；这里不展示已有 Builtin 清单。涉及远程操作时，还要调用已经封装好的 Remote Execution Service，不应绕开 Task 生命周期自己直接给 Socket 写命令。Server Builtin 需要用户确认时，可复用 [Interaction Broker](interaction_broker.md) 的 Server 调用方式，而不是把 Client 侧 Grant 套用到 Server Builtin。

## 五、注册与发现为什么分开

Client 的 `CommandIntrospectionMixin` 通过 `inspect.getmembers()` 收集当前平台命令对象中带 `help` 属性的方法，生成 `command_manifest`（含 `name/help/group/suggest`），并附加 `ArgumentCommandRegistry.get_manifest_payload()` 的 ACMD 条目。Manifest 在 Client 构造 `info` 握手时提交，Server 的 `SessionInfo` 保存该连接的快照；**不是 Web 打开命令面板时实时从 Client 重新扫描 Python 方法**。

Web 通过 `GET /api/connections/{client_id}/command-candidates` 获取候选，`WebCommandCatalogApi` 汇合当前 Client 的 Manifest 与 Server Builtin/Alias 模板，按 `template` 去重，再进行排序。用户能在候选列表里看见一个名称，只能说明它出现在此清单，不能替代执行权限、平台可用性或参数合法性的验证；反过来，`suggest=False` 的命令可以执行但不作为普通提示展示。

上下文自动补全又是独立机制：`POST /api/connections/{client_id}/command-completions` 由 Server `ServerCommandCompletionService` 的 Provider Registry 响应；需要远程文件等数据时，再通过 Client 的 `command_completions` 入口，由 `ClientCommandCompletionService` 注册的相应 Provider 收集候选。**新增普通命令不等于自动获得参数补全**：需分别考虑 Server Provider、Client Provider 与前端解析上下文。输入框选中候选后只是填充命令，不代表执行。详细规则请参阅 [Autocomplete](autocomplete.md)。

开发者可依次检查三个现象：

- `help` 是否显示：取决于平台方法是否存在、`@desc` 是否导出，以及 `suggest`。
- 命令候选 API 是否返回：取决于连接握手里的 Manifest 是否更新，以及 Server Builtin 模板是否声明。
- 输入参数时是否继续提示：取决于独立的 Completion Provider 和前端路由，而不是 `help` 描述本身。

## 六、受保护能力与执行策略如何接入

普通 Client 命令通过 `@desc(..., api_grants=('interactions:request',))` 声明所需受保护范围；若只需执行前确认，也可使用 `@confirm`。`@confirm` 和 `@desc` 两种装饰器顺序在当前实现中都能够保留帮助元数据及交互授权要求。实际 Grant 由 Server `ClientSessionCommandChannel.build_command_payload()` 对**可信的本地 `CommonCommands` 或对应平台类的方法注解**进行查找后签发，且仅在命令调用需要该范围时提供。Client 自报的 Manifest 不能凭空增加 Grant。

涉及 `CommandInteractions`、预览、Secret 输入、批准/拒绝时，详细使用和应答边界参阅 [Interaction Broker](interaction_broker.md)；Script 的 Metadata 和 Script SDK 授权则由 [Scripts](scripts.md) 与 [Admin Auth](admin-auth.md) 解释。**普通命令的 `api_grants` 声明并不等于任意 ACMD 或 Shell 文本都会获得同样的授权。**

取消与超时同样需要对应执行逻辑真正支持。`ShellCommandRunner` 会先应用方法上 `command_timeout` / `command_cancel_mode` 等策略元数据，再调用该方法或 Shell；中断检查点与注册的取消处理器需要由实现自身正确执行。对会读写外部文件、启动子进程或调用 HTTP 的新功能，必须验证取消发生在执行前、执行中以及失败清理阶段时的实际效果。安全敏感操作的鉴权与确认不能仅依赖命令是否出现在补全列表。

## 七、从添加方法到可用的验收链

以下顺序用于新命令开发，不是要求每个命令都具备 ACMD、交互弹窗和自动补全。

1. **确定归属**：操作应在 Server 还是目标 Client 上执行？是普通单参数、结构化 ACMD，还是 Script？确认不会与已有 Server Builtin 或 Alias 冲突。
2. **编写业务层**：在已有的 Domain Service 中复用文件、系统和进程能力，避免将复杂逻辑堆进命令入口；明确返回状态、异常、输出和副作用。
3. **注册在正确平台**：普通命令检查 `@desc` 和 Mixin/平台继承链；ACMD 检查 `@argument_command`、Spec、实际平台类与 Registry。Server Builtin 检查 Handler 和对应 Support Service。
4. **核对执行契约**：检查参数文本或结构化对象、回传状态、`command_id` 绑定、超时和取消；需要授权/交互时同时检查 Server 可信元数据及 Grant。
5. **验证发现**：在新建或重新连接的 Client 会话上查 `help`、`command_manifest`、`command-candidates`；需要参数补全才扩展 Completion Provider。
6. **跑边界测试**：覆盖无效参数、未知命令、未支持平台、没有 Grant、取消/超时、Session 断开、重复调用；验证主线执行结果与 Web Task/History 正常关联。

排查现象时可以按位置定位：

| 现象 | 优先检查 |
|---|---|
| 方法存在但输入后落到 Shell | 方法是否实际属于加载的命令类；是否有 `@desc` 生成的 `help` 元数据；输入的命令名称是否正确 |
| 终端 `help` 有命令，Web 下拉看不到 | `suggest` 是否为 `False`；握手快照是否更新；前端是否过滤；候选模板是否有效 |
| ACMD 显示“not supported on this platform” | `@argument_command` 是否被实际平台继承；名称与注册表是否一致；Registry 是否已构建 |
| ACMD 报缺参、未知选项或类型错误 | `ArgumentCommandSpec` / Validator；不要去修改 Server Shell 解析器绕过校验 |
| Server Builtin 看起来变成远程命令 | `BuiltinCommandHandler` 上是否存在同名可调用方法；是否只配置了候选模板 |
| 命令能执行但不出现文件路径建议 | 是否有对应 Completion Provider 与前端参数上下文；普通注册不会自动生成 |
| 交互请求无权或超时 | 是否声明必要 Scope、Server 是否能从可信方法找到定义、当前 Task/Tab 是否有效 |

关键实现入口：`client/commands/runtime/catalog.py`、`client/commands/common/groups.py`、`client/commands/common/mixins/introspection_ops.py`、`core/utils/decorator.py`、`client/commands/arguments/registry.py`、`server/application/command/{executor,command_planner,builtin_command_handler}.py`、`server/application/web/command_catalog_api.py`。这些路径相对于 `backend/`。
