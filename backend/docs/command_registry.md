# Command Registry & Extension Development

RCH 的命令扩展并不是“在某个表里添加名字”就完成。一个可使用的命令必须同时满足：**目标执行端有可调用的处理器、输入能够路由到该处理器、其运行契约与结果格式一致**。是否在帮助和补全中可见，则属于另一层能力发现。开发时应先确定命令应由 Server 处理，还是交给所选 Client 执行；在 Client 内部，还要区分普通 `command` 与结构化 `acmd` 两套注册方式。

本文以扩展开发为主，解释如何从一个方法接入到 Terminal 和 Web。现有命令如何运行、ACMD 全套参数语法及浏览器的候选交互，分别见 [Command Execution Pipeline](command_execution.md)、[Shell-like Commands](shell_like_commands.md)、[ACMD](acmd.md) 和 [Autocomplete](autocomplete.md)；这些机制不在这里重新逐项展开。

## 一、选择正确的命令入口

不同入口的“注册”含义不同，不能只根据终端里看到的文本形式判断。

| 需求 | 承载位置 | 定义与发现 | 执行路径 |
|---|---|---|---|
| 对所选 Client 执行一个通常接受文本参数的操作 | Client 普通命令 | 导出方法、`@shell_command`、平台命令对象的继承链 | `command` → Client `ShellCommandRunner` |
| 对输入参数做声明式校验与类型转换 | Client 结构化命令 | `@argument_command` + `ArgumentCommandSpec`，`ArgumentCommandRegistry` 收集 | `acmd` → `ArgumentCommandRunner` |
| 在 Server 上处理别名、历史、流程编排或 Web 控制 | Server Builtin | `ServerCommandRegistry` 显式声明主命令/子命令/Handler，运行时只允许注册名称 | Server `CommandExecutor` 优先处理 Builtin |
| 将现有操作配置成一个快捷别名 | Alias | Server 的别名存储与解析器 | 解析别名后转成远程计划 |
| 运行存放在 Server Script Library 的 Python Script | Script | Script Library / Metadata | Script 请求与 Python 执行策略 |

普通 Client 命令不要求为每个参数声明 `ArgumentOptionSpec`。未命中普通导出命令时，当前 Client 的普通命令 Runner 会走托管的 Shell 后备执行；**ACMD 查找失败则直接报不支持，不会落到 Shell**。Server Builtin、Alias、Client 普通命令、ACMD 的优先级由 Server 执行规划决定，不由 Web 候选列表决定。

典型路径：

```text
Web Terminal / Server CLI
  └─ Server CommandExecutor.process_command()
       ├─ 命中显式 Server Command Registry → Server Builtin
       └─ CommandPlanner
            ├─ acmd 前缀 → 结构化负载，Socket type=acmd
            ├─ 已配置 Alias → 展开到远程命令计划
            └─ 普通输入 → 远程 command 文本
                   ↓
             Client CommandExecutor
              ├─ ArgumentCommandRunner → ArgumentCommandRegistry
              └─ ShellCommandRunner → @shell_command 导出方法 / 托管 Shell
```

这描述的是普通命令入口；PTY、Monitor、Clipboard 等独立消息与会话服务不应为了“在终端里有个命令名”被塞进同一注册表。

## 二、普通 Client 命令怎样被导出

### 两套命令入口与运行时宿主

`CommandCatalog` 根据本机 `get_local_identity().os_alias` 选择 `client/commands/runtime/hosts.py` 中的当前平台宿主。Shell 命令声明位于 `client/commands/shell/common/` 与 `client/commands/shell/platform/`；ACMD 声明位于 `client/commands/acmd/common/` 与 `client/commands/acmd/platform/`。两种声明分别使用 `@shell_command` 和 `@argument_command`，由同一运行时宿主绑定执行上下文，但分别交给 Shell Runner 和 ACMD Registry 执行。

命令开发者可以直接在分组类中声明方法，也可以在 `standalone/` 中为独立命令建立模块，并在分组类中**显式挂载函数对象**（如 `getinfo = getinfo_command`）。这两种写法使用同一套命令元数据与执行方式。平台可用性由宿主继承关系及 `@shell_command(platforms=...)` 共同约束。ACMD `ArgumentCommandSpec` 与注册方法放在同一个模块顶部，不需要另外查找 Specs 文件。

完整的公共操作继续调用既有 Service；无复用需求的命令可把其实现留在独立命令文件内。额外的命令注册类不是必要条件。

### `@shell_command` 是导出契约

普通命令使用 `core.utils.decorator.desc`：

```python
from client.commands.shell.decorators import shell_command

class ShellDiagnosticsCommands:
    @shell_command('Show a concise diagnostic message', group='session')
    def diagnostic_note(self, arg=''):
        text = str(arg or '').strip()
        if not text:
            return 0, 'Usage: diagnostic_note <text>'
        return 1, f'Diagnostic: {text}'
```

这是新增扩展的示意代码。可把方法写入已有的 `shell/common/` 分组类，或者将独立文件中的函数挂载到对应分组类。当前运行时宿主需实际继承该分组类，Client 重启加载后才会生效。

`@shell_command(description, group='general', suggest=True, *, output='collect', interaction=False, completion=None, platforms=None)` 将元数据挂在方法上：

- `help`：导出识别和帮助描述。**缺少 `@shell_command` 的普通方法不会作为普通 Client 命令被 ShellCommandRunner 分派**，哪怕它恰好是 public method。
- `group`：Server `help client` 分组及 Command Manifest 的分类；不会单独决定权限或平台。
- `platforms`：允许的 Client 平台（`mac` / `win` / `linux` / `ios`），缺省支持全部平台；不支持的平台不会导出或执行。
- `suggest`：控制是否出现在默认帮助/候选展示中。`suggest=False` 不会禁止执行，Manifest 中仍可能包含该项，由展示层过滤。
- `interaction`：标记通常可能请求 Web 交互，用于 Manifest 提示，不控制命令执行权限。
- `completion`：可选的最小 `CompletionSpec(provider, kinds)`，声明命令参数由哪个 Client Completion Provider 处理及允许的候选类别；不复制命令名、参数位置或运行时路径。

普通 Runner 的调用约定是：先通过项目解析器分离首个命令名称及其余文本；然后以方法签名决定调用 `handler()` 还是 `handler(arg)`。因此普通命令更适合无参或**单段原始参数文本**；多值、可验证的选项建议使用 ACMD。命令返回一般为 `(status, result)`，其中 `1` 表示成功、`0` 表示失败；其他输出约定需与执行链保持一致。中间流式结果应复用执行 Scope 的 `emit_chunk(message)`、`emit_progress(message, level=None)`；仅在直接管理终态的流式方法中调用 `emit_completed(status="success"|"error"|...)`。一次性函数继续返回 `(status, result)`，由执行入口生成唯一 completed；禁止主动发完 completed 又返回新的结果导致重复终态。显式 progress.level 支持 info/success/warning/error，由 Server 公共 Renderer 投影标记；不得在 Client 字符串里预先拼 Marker，也不得自行创建 Web SSE 事件。

### 运行上下文与能力约束

命令实例由 `CommandExecutor` 绑定本次 `command_id`、`execution_context` 和命令运行时。开发一个可能阻塞的命令时，不能只给方法加个名字就宣称它可取消：执行方法应按需使用 `_checkpoint()`、`_set_timeout()`、`_set_cancel_policy()`、`_register_cancel_handler()` 和 `_register_cleanup_handler()`，并确保调用的 Service 处理同一生命周期。取消与超时的最终语义见 [Command Execution Pipeline](command_execution.md)。

如果业务希望返回机器可读对象，可以按命令执行器的结构化结果约定返回值；默认渲染和 `json` 输出模式见 [Structured Output](structured_output.md)。是否需要 Web 输入表单或文件选择器，不由 `@shell_command` 自动生成。

## 三、注册一个带参数规格的 ACMD

普通命令之外，结构化 ACMD 由 `ArgumentCommandRegistry` 管理。其参数规格和校验与 Server Builtin 共用 `core/commands`，但命令注册与执行仍由各自所属层负责。它在 Client 当前平台命令对象上扫描带有 `argument_command_name` 的方法，并保存 `handler + spec`；`@argument_command` 的职责是标记方法，最终能否加载仍取决于方法是否属于当前平台命令类。

例如定义一个只回显参数、便于验证接入的扩展示意：

```python
from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec

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

Server 命令入口由 `server.application.command.server_builtin_registry.SERVER_COMMAND_REGISTRY` 显式注册；`BuiltinCommandHandler.resolve_builtin_command()` 只接受注册名称，未命中则交由 Planner 保持 ACMD、Alias、Client 普通命令和 **未知命令 Shell 回退**的原有机制。不能靠 `hasattr()` 将辅助方法误当用户 Builtin。

Server Builtin 的 `group` 统一默认 `server`，每个主命令不再指定 `script/alias/job/history/control/external_tool` 等独立 Group；Manifest 继续输出 `group=server`，供 Client / Server 来源区分。

新增主命令在 Server Registry 声明 `name/description/handler`；固定子命令可在 `SubcommandSpec.subcommands` 继续声明下一层。Registry 使用共享 `CommandLineResolver` 沿已声明路径逐层匹配到叶子，再按该叶子的 `ArgumentCommandSpec` 校验参数。Resolver 保留 Token 原文 Span，使 RawTail 与 fallback 叶子收到原有参数文本。`xt instance status`、`xt package install` 等动作以及静态 Help/补全都来自此注册定义；`xt exec run <exec-name> ...` 是正式 RawTail 叶子；`xt exec <exec-name> ...` 通过同组声明的 fallback_subcommand=run 作为简写，原生参数不进入管理命令的选项解析。Job、Script 和 XT Instance 统一使用 `-- --key value` 传递业务参数；位置参数和对应长选项使用同一字段。Alias 模板等真正需要保留原文的命令继续使用 RawTail，业务执行仍由所属 Support / Service 处理。

Registry 同时产生 Server Manifest、`help` 和静态子命令补全候选。命令节点和 RawTail 叶子可使用 `CompletionSpec(provider, kinds)` 声明补全来源；结构化参数在 `ArgumentOptionSpec.completion` 声明，`_option()` 及子命令辅助构造函数原样透传。Server 本机文件系统补全使用声明的 `filesystem` Provider 与文件/目录类别，XT 的静态路径和 Help 目标通过同一递归树生成，动态候选由 Schema 指向的命名 Provider 查询；Server Registry 先确定叶子路径、当前参数和原文 Span，`CommandLineResolver` 处理位置参数、命名选项及 RawTail 边界，Provider 不再解析业务命令文字。`configuration` / `jobs` / `scripts` / `xt` 分别负责自己的实时数据查询；Script Catalog 统一扫描磁盘，XT Catalog 提供公开平台/架构筛选，Job 采用既有活跃状态定义。Info → Commands 保留原有的单列命令卡片；在 Command List 标题处切换 Client / Server，并可在当前来源内按命令名称或描述搜索。Client 模式先按 Group 名称（不区分大小写），同组再按命令名称排序；Server 模式只显示一级 Builtin，不展示冗余的 Group 行，子命令不伪装成独立顶层命令。Server `help` 聚合已注册的 Server 主命令与当前 Client Manifest，并按 Group 显示标题的字母顺序（组内命令名也按字母顺序）列出 Client 的 `[Shell]`、`[File]`、`[Session]`、`[Acmd]` 等分组及说明。它**不会展开动态 Alias 名称和命令内容**；`help alias` 只解释 `alias` 管理命令的用法。`help server/client/alias/script` 可查询对应命令帮助。需要动态内容时使用既有补全 Provider，例如 `script exec <path>` 与 `job start <name>`；不重复手写另一份静态菜单。普通 Client 命令 Manifest 的 `@shell_command` 与 `suggest` 行为保持原样。

`alias` 的 `list/set/unset` 与其他 Server Builtin 一样使用类型化 Invocation、注册表参数校验及统一 Result Envelope；`set` 的首个 `=` 只用于分隔不透明模板正文，由 Alias 业务层处理，不将模板里的选项当成 Builtin 参数。

当前聚合的一级命令包括 `alias`（默认生效列表、`list/set/unset`）、`job`（`list/start/ps/status/stop/stop-all`）、`script`（`list/view/exec`）、`xt`（`exec/package/module/instance/help`；Exec 使用 `xt exec <name>`）、`history`（默认 Quick 列表、`clear/run`）及原有 `notify/saveout/gopin/rtt/httpctl/upload`。`exec` 和 `run_script` **不作为独立 Server 顶级命令**：Terminal 使用 `script exec <name> [--execution_mode MODE] [--output_mode MODE] -- --key VALUE ...`，Script Library UI 直接提交 Web Script Task，Server 两端共用 Script Metadata 参数校验，均发送 `control(domain=script, action=run)`。

测试用的 `interaction_*` 演示命令已从 Client 注册类和源码中移除，真实的 Interaction Broker、Script SDK 授权与进程预览命令依然保留。Server 的 `disconnect` Builtin 及其专用处理器已经删除；Client 会话控制命令与现有 Web 连接管理接口未改变。Builtin 的 `description` 只写简短说明，不能将 `<usage> | <description>` 的格式拼入描述；参数用法由独立 `usage`/子命令规格承担。默认 `gopin` 列表只显示保存名称与路径，不再打印机器 ID，持久化隔离仍按机器 ID 完成。

Client 的 `CommandCatalog` 通过 `inspect.getmembers()` 收集当前平台命令对象中带 `help` 属性的方法，生成 `command_manifest`（含 `name/help/group/suggest`），并附加 `ArgumentCommandRegistry.get_manifest_payload()` 的 ACMD 条目。Manifest 在 Client 构造 `info` 握手时提交，Server 的 `SessionInfo` 保存该连接的快照；**不是 Web 打开命令面板时实时从 Client 重新扫描 Python 方法**。

Web 通过 `GET /api/connections/{client_id}/command-candidates` 获取候选，`WebCommandCatalogApi` 汇合当前 Client 的 Manifest 与 Server Builtin/Alias 命令，按候选插入文本 `name` 去重，再进行排序。用户能在候选列表里看见一个名称，只能说明它出现在此清单，不能替代执行权限、平台可用性或参数合法性的验证；反过来，`suggest=False` 的命令可以执行但不作为普通提示展示。

上下文自动补全又是独立机制：`POST /api/connections/{client_id}/command-completions` 由 Server `ServerCommandCompletionService` 的 Provider Registry 响应；需要 Client 文件系统等数据时，Server 通过独立 `type: completion` 消息请求 Client，并使用现有 PendingResults 按 request ID 关联 Result Envelope。该请求不走命令执行、Control、Foreground、Activity 或 History 路径。Client 命令的 CompletionSpec 通过 `command_manifest` 握手传递；Shell-like 使用 `@shell_command(..., completion=...)`，ACMD 在 `ArgumentOptionSpec.completion` 声明。**新增普通命令不等于自动获得参数补全**：静态 Server 子命令仍来自 Registry，动态参数需要显式 CompletionSpec 或相应 Server Provider。输入框选中候选后只是填充命令，不代表执行。详细规则请参阅 [Autocomplete](autocomplete.md)。

开发者可依次检查三个现象：

- `help client` 是否显示：取决于平台方法是否存在、`@shell_command` 是否导出，以及 `suggest`。
- 命令候选 API 是否返回：取决于连接握手里的 Client Manifest 是否更新，以及 Server Registry 是否声明。
- 输入参数时是否继续提示：取决于独立的 Completion Provider 和前端路由，而不是 `help` 描述本身。

## 六、受保护能力与执行策略如何接入

普通 Client 命令和 ACMD 均可在当前 Web Task 中使用 Interaction Broker，使用连接建立时发放的会话凭证，不需要逐命令声明 Scope。`@confirm` 仍负责命令确认，`--no-confirm` 跳过该确认；`@shell_command(..., interaction=True)` 只用于 Manifest 显示提示，不参与访问权限判断。

涉及 `CommandInteractions`、预览、Secret 输入、批准/拒绝时，详细使用和应答边界参阅 [Interaction Broker](interaction_broker.md)；Script SDK 的 Client API 路由由 [Client Session API](client_session_api.md) 说明；Command、ACMD 和 Script 共用 Client Session Token。

取消与超时同样需要对应执行逻辑真正支持。`ShellCommandRunner` 会先应用方法上 `command_timeout` / `command_cancel_mode` 等策略元数据，再调用该方法或 Shell；中断检查点与注册的取消处理器需要由实现自身正确执行。对会读写外部文件、启动子进程或调用 HTTP 的新功能，必须验证取消发生在执行前、执行中以及失败清理阶段时的实际效果。安全敏感操作的鉴权与确认不能仅依赖命令是否出现在补全列表。

## 七、从添加方法到可用的验收链

以下顺序用于新命令开发，不是要求每个命令都具备 ACMD、交互弹窗和自动补全。

1. **确定归属**：操作应在 Server 还是目标 Client 上执行？是普通单参数、结构化 ACMD，还是 Script？确认不会与已有 Server Builtin 或 Alias 冲突。
2. **编写业务层**：在已有的 Domain Service 中复用文件、系统和进程能力，避免将复杂逻辑堆进命令入口；明确返回状态、异常、输出和副作用。
3. **注册在正确平台**：普通命令检查 `@shell_command` 与当前平台宿主加载的分组/平台命令类；ACMD 检查 `@argument_command`、就近 Spec、实际平台宿主与 Registry。Server Builtin 检查 Handler 和对应 Support Service。
4. **核对执行契约**：检查参数文本或结构化对象、回传状态、`command_id` 绑定、超时和取消；涉及 HTTP Client API 时核对 Client Session Token 和中央路由白名单；交互检查当前 Web Task。
5. **验证发现**：在新建或重新连接的 Client 会话上查 `help`、`command_manifest`、`command-candidates`；需要参数补全才扩展 Completion Provider。
6. **跑边界测试**：覆盖无效参数、未知命令、未支持平台、无效 Client Session Token、取消/超时、Session 断开、重复调用；验证主线执行结果与 Web Task/History 正常关联。

排查现象时可以按位置定位：

| 现象 | 优先检查 |
|---|---|
| 方法存在但输入后落到 Shell | 方法是否实际属于加载的命令类；是否有 `@shell_command` 生成的 `help` 元数据；输入的命令名称是否正确 |
| 终端 `help` 有命令，Web 下拉看不到 | `suggest` 是否为 `False`；握手快照是否更新；前端是否过滤；候选模板是否有效 |
| ACMD 显示“not supported on this platform” | `@argument_command` 是否被实际平台继承；名称与注册表是否一致；Registry 是否已构建 |
| ACMD 报缺参、未知选项或类型错误 | `ArgumentCommandSpec` / Validator；不要去修改 Server Shell 解析器绕过校验 |
| Server Builtin 看起来变成远程命令 | `BuiltinCommandHandler` 上是否存在同名可调用方法；是否只配置了候选模板 |
| 命令能执行但不出现文件路径建议 | 是否有对应 Completion Provider 与前端参数上下文；普通注册不会自动生成 |
| 交互请求无权或超时 | 是否声明必要 Scope、Server 是否能从可信方法找到定义、当前 Task/Tab 是否有效 |

关键实现入口：`client/commands/runtime/catalog.py`、`client/commands/runtime/hosts.py`、`client/commands/shell/decorators.py`、`client/commands/acmd/registry.py`、`server/application/command/{executor,command_planner,builtin_command_handler}.py`、`server/application/web/command_catalog_api.py`。这些路径相对于 `backend/`。

### 终端命令目录的平台可见性

`script list`（含 `--json`）和 `job list`（含 `--json`）只列出适合当前连接 Client 平台的条目。只读取 Script/Job Metadata 中显式声明的 `platforms`（可使用 `common` / `all` 等通配声明）；**没有声明或声明为空时不进入终端列表与补全**，不再根据 `mac/win/linux/ios/common` 目录名兜底。`script exec` 与 Script Library UI 的显式执行并不被该**列表筛选**拦截，显式指定其他平台文件依旧可以执行。

Terminal 的 `script exec` 路径候选和 `job start` Job 名称候选复用相同的可见性判断；Script Library 和 Background Jobs Web Catalog 不使用该 CLI 筛选，原有 UI 数据范围不改变。


## 当前 Client 可见命令命名与分组

四平台 `getinfo [-a|--all] [--json]` 经 Shell Common 显式挂载同一个 Standalone 命令，返回有序平铺 `StructuredCommandResult`。命令入口按系统、硬件、进程及平台信息顺序组合字段；默认只采集轻量字段，`--all` 将详细诊断信息插入对应位置。公共字段包括 `kernel`、`rch_build_ver`、`rch_build_revision`，Apple 系统代号／设备型号／iOS 芯片名称使用 `core/device/apple_model_names.json` 的本地映射。平台独有字段与默认／详细字段分别维护。

iOS 的命令可见性由 `iOSCommands` 的实际导出方法和 ACMD Registry 决定。平台类会屏蔽不适用于 Pythonista 的继承命令，并将设备命令归入 `device` 分组（`clipboard_read`、`clipboard_write`、`get_location`、`speak`、`list_contacts`、`list_reminders`），将 `clear_console`、`keep_awake` 归入 `console`；`acmd ps/kill` 不在 iOS 注册。iOS 的 `getinfo` 和基于 Pythonista 系统接口的 `uptime` 均归入 `system` 命令组。`list_reminders` 和 `list_contacts` 无需参数，直接输出 JSON。原先的文件预览、分享、上传、打开链接和退出 App 入口归入 Script Library 的 `ios/console`。


ZIP 创建与解压使用四平台 Common ACMD 的 `acmd zip`、`acmd unzip` Standalone 注册，复用 Remote Files 的 `ArchiveService`；两者接受位置路径或 `--path`。ZIP/UNZIP 默认返回一条包含文件数、可读大小、耗时及目标路径的简洁文本，仅 `-v/--verbose` 输出逐文件进度。ZIP 权限拒绝时默认停止，显式 `--skip-unreadable` 才允许跳过并显示警告和部分归档提示；UNZIP 保留 `--conflict` 及 `--merge`／`--skip` 简写。两条命令不提供 `--json`；Remote Files Browser 原有调用行为不变。Shell-like 不再导出 `zip_dir` / `unzip`。

普通 Client 命令的可见名称直接来自 `@shell_command` 修饰的方法名，`group`
决定 Manifest、Client Help 和 Info → Commands 的分类。重命名后不保留旧名称兼容入口。
本次分组使用 `shell`（`cd`、`pwd`）、`execution`（`shell`、`shell_stream`、
`shell_bg`、`run_bg`、`pyexec`、`pyexec_stream`）、`file`（`file_shred`）、
`session`（`var`、`kill_instance`、`reexec_instance`、`relaunch_instance`、`spawn_instance`）、
`runtime`（`watchdog`、`set`）、`maintenance`（`clean`、`update`）、
`transfer`（`download`）、`automation`（`keyboard_send`）、
`media`（`screenshot`、`webcam_snap`）、`privilege`（`run_elevated`、
`spawn_elevated_instance`、`is_elevated`）、
`system`（`getinfo`、`idletime`、`getuid`、`getpid`、`uptime`、`userenum`）。`ip` 已不再注册为 Client 命令。

Server → Client 文件传输统一使用 `transfer_start` / `transfer_update`，由 TransferManager 执行，不注册内部传输命令。
iOS 专属 `clipboard_read` / `clipboard_write` 和其他设备命令统一使用 `device` 分组；
内部 `acmd` 和 Structured Payload 命令按原有执行流程运行。

Client 生命周期的 `relaunch_instance` 仍调用原有新建进程再退出逻辑；
`reexec_instance` 仅在 macOS/Linux 注册，使用 `os.execv()` 替换当前进程。
Windows 不注册 `reexec_instance`，重启使用 `relaunch_instance`。macOS 和 Windows 的
`run_elevated` 保留各自平台原有执行策略；macOS 与 Windows 均提供 `spawn_elevated_instance`，由系统权限确认后启动一个额外的高权限 Client 实例。Windows 可使用 `spawn_elevated_instance --detached` 经 UAC 由 Python 启动器创建无控制台的 detached elevated Client；macOS 可使用 `spawn_elevated_instance --detached`，由提权 bootstrap 创建独立 session 的后台 root Client 后退出；不带该参数时保留原有启动生命周期。这两个平台的提权命令默认通过 `@confirm` 请求交互；显式 `--no-confirm` 仅跳过 RCH Interaction Broker，不会绕过操作系统授权弹窗。


## Log Viewer (Client file tail)

Toolbox → Log Viewer opens without selecting a path. The user selects a remote Client
text file through the existing RemoteFilePicker. External Tools instance stdout
paths and Info → Watchdog log paths open the same viewer directly.

The Client Device Monitor `log_file` channel uses `options.path` and a 250 ms
sampling interval. It reads bounded incremental UTF-8 chunks through the shared
`core.utils.log_reader.read_text_log_chunk` cursor reader, handles rotation/truncation, and transmits
updates through the existing `monitor_snapshot` → Server EventBus → SSE path.
No foreground RCH command or External Tools log polling endpoint is used.
A Server-side file source can be added later; v1 has no Server file picker or
System Events implementation.

The viewer's Clear View clears browser display only. External Tools' existing
**Clear Logs** operation still explicitly clears stopped instance log files.

## 命令 Manifest 元数据

Client 普通命令的 `@shell_command` 可以声明 `output='collect'|'stream'`、`interaction=True|False`，并保留 `help/group/suggest`。取消能力由现有 `@cancel_policy('none'|'cooperative'|'process')` 声明，命令执行时仍可根据具体执行模式更新当前取消策略。`@cancel_policy`、`@timeout`、`@confirm` 仍各自定义实际执行行为。命令扫描器统一提取 `name/kind/source/help/group/suggest/cancel_policy/timeout/confirmation/interaction/output`；ACMD 注册表也生成相同字段。每个可补全的 ACMD 条目使用真实插入文本作为 `name`，隐藏命令不加入握手清单。

Manifest 的取消与 Timeout 信息反映命令默认声明；实际执行中的取消策略以运行态为准。带有 `confirmation: true` 的命令由 `@confirm` 请求 Interaction Broker 确认；所有这类命令均接受 `--no-confirm`。`interaction.may_request` 是当前命令声明的“可能请求交互”提示，不表示每次执行都会产生弹窗。
