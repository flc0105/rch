# Command Aliases and Quick Actions

Server Alias 把一个名称映射为可展开的命令模板，并依目标 Client 的平台确定实际采用的定义。模板中的 `<parameter>` 在 Server 层绑定成纯文本，随后进入对应的命令派发链。名称空间、平台覆盖与后续执行入口共同决定最后运行什么。

Quick Actions 基于同一份 Alias 定义提供可编辑的 Web 动作、参数输入和工具栏入口；它不保存第二套执行模板。终端调用与 Web 任务提交可能经过不同的重新解析路径，因此应先理解 Alias 在服务端的查找及展开语义，再使用 Quick Actions 的结果弹窗和终端模式。

## 名称解析在命令链中的位置

Server 启动时建立 AliasManager，读取持久化的 Alias 定义。正常终端命令进入 Server 后，先识别 **Server Built-in**（例如 Alias 管理入口本身）；没有命中时，CommandPlanner 优先识别输入是否以 `acmd` 开头，再尝试将第一个命令词作为 Alias 名称解析；如果也没有命中，就按原始普通命令向 Client 下发。名称命中但参数错误时会返回错误，而不是静默退回 Shell。

Alias 解析只执行一轮：选择当前连接生效的模板，按参数名替换 `<name>`，生成一条 `COMMAND_TYPE_COMMAND` 类型的普通远程命令。Server 在此不会重新识别展开结果是不是另一个 Alias、Server Built-in 或顶层 `acmd`。Client 收到普通命令后才应用 Client 变量展开，并按 **Shell-like Commands** 的规则尝试导出的内置命令；未命中才通过系统 Shell 回退执行。

所以，**Alias 可以定义为普通 Shell-like 命令，包括 Client 导出的命令入口以及普通 Shell 文本；并不限定只能写 `shell ...`。** 但模板内使用的具体 Client 命令仍需在目标平台实际可用。它不是能够重走所有 Server 命令入口的通用宏系统。

Quick Actions 则先以“平台 + 名称”定位**指定的原始定义**，绑定表单参数，再把适当的文本提交给正常 Web Command Task。具体何时保留 Alias 调用、何时提交已展开命令，以及为何可能重走 Server 命令解析，见第七节。

## 平台覆盖与目标设备选择

每份定义由 `platform`、`alias` 和 `command` 确定。当前支持 `common`、`win`、`mac`、`linux`、`ios` 五个作用域：`common` 是共享默认层，其他四层分别是目标客户端操作系统的专用配置。平台识别读取当前连接上报的 `os_alias`，没有该值时读取 `os_type`，再规范化为内部平台名；常见 Windows、macOS、Linux 和 iOS 名称或别名会映射为对应作用域。若上报值无法识别，则按 `common` 处理，不根据当前浏览器所在系统猜测目标平台。

正常终端解析采用 **`common` + 当前目标平台** 的合并视图：先装载共享项，再用当前平台的同名项覆盖。覆盖是按完整 Alias 名称进行的，而不是将两个命令模板拼接。若目标为 Windows，则某个同名定义在 `win` 中存在时优先使用 `win`；连接换成 macOS 后，是否采用 `mac` 专用定义取决于该层是否存在同名项，否则回到 `common`。Linux 和 iOS 的规则相同，即使当前相应作用域暂时没有定义，也依然受支持。

跨平台配置有两种不同的“查看”：

- **解析后的生效视图**只显示当前连接可执行到的每个 Alias，并标明最终来自共享层还是平台层。已被覆盖的共享同名项不会再次占用一行。
- **原始定义视图**按平台分别保留每一项，允许共享层与平台层同名共存，适合编辑和检查覆盖关系；看见某项不代表当前终端会选中它。

Web Quick Actions 的 Current 筛选展示共享层和目标平台层的原始定义，**包括已被覆盖的 `common` 项**；该项会标记 `overridden`，平台定义则为有效项。选择特定平台筛选可以查看其他平台的定义，并可编辑。列表中的 `current_platform`、`default_platforms`、`in_current_scope`、`overridden` 和 `effective` 分别帮助前端决定筛选、标签及是否为当前命令名称的最终解析结果。仅靠 Alias 名称不能唯一确定跨平台定义；编辑、运行、Pin 必须同时保留平台身份。

## 定义存储和状态一致性

Alias 本体由 Server 全局管理，持久化在 `backend/server/resources/aliases.json`，使用按平台分组的 JSON 对象。基本结构如下（名称和模板仅为格式示意，不是项目既有 Alias 清单）：

```json
{
  "common": {
    "sample": "shell echo <message>"
  },
  "win": {},
  "mac": {},
  "linux": {},
  "ios": {}
}
```

同一组内，一个名称只对应一条模板；不同平台组可以出现同名定义。文件不是按机器或连接分别存放的，而是当前 Server 实例共享的配置。管理接口统一以分平台结构写入。读取时过滤空名称和空模板；文件不存在或 JSON 无法解析时，内存别名表会退回空配置。修改配置前应避免让损坏的文件被误当成有效的空配置覆盖。

这里必须区分**磁盘文件与 AliasManager 的内存快照**：

| 触发方式 | 当前行为 |
| --- | --- |
| Server 初始化 | 读取一次 `aliases.json` |
| `alias set`、`alias unset` | 改写当前内存定义，并保存完整 JSON |
| Quick Actions 新增、编辑、删除 | 使用同一个内存定义管理器，并保存 JSON；编辑移动作用域时一次写入 |
| `alias` / `alias resolve`、`alias list` | 查询前主动从磁盘重载，再生成视图 |
| `alias reload` | 显式丢弃当前内存快照，重新从磁盘加载 |
| 打开或刷新 Web Quick Actions 列表 | GET 时主动从磁盘重载，再返回所有平台定义 |
| 普通 Alias 调用 | 使用当前内存定义，**不会每次调用自动读盘** |
| Terminal 普通命令候选查询 | 从当前内存定义生成候选，**不额外自动读盘** |

因此，通过文件编辑器直接修改 JSON 后，推荐先执行 `alias reload` 或进行会触发加载的查询，再运行 Alias。某次 `alias list` 或 Quick Actions GET 本身会刷新同一个 Server 管理器，后续普通调用可能已经看到新值；但**已经在浏览器缓存的补全候选或先前打开的列表不会因此自动重新渲染**，需重新加载对应界面或候选数据。

尤其不要在直接编辑 JSON 后，未经重载就从另一个入口修改 Alias：写入操作按**当前内存快照**保存整份文件，可能把刚才手动编辑、但尚未加载的内容覆盖掉。此处也没有文件系统热监听、按机器分别同步配置，或分布式多 Server 的冲突合并机制。

工具栏 Pin 是另一份数据：记录在 `runtime/rch.db` 的 `settings` 表、`toolbar_preferences` 命名空间下，不写进 `aliases.json`。它保存的只是平台和名称引用，不复制命令模板。两份数据的写入及失败处理也不具备统一事务。

### 写入、删除和查询定义

终端中的 `alias` 是 **Server Built-in**，负责查询及维护 Server 的 JSON 定义，不是远程操作系统的 Shell 内建命令。当前支持 `resolve`、`list`、`set`、`unset` 和 `reload` 五种管理动作；不必先进入客户端 Shell。

直接输入 `alias` 与 `alias resolve` 等效，展示目标连接的 **生效合并视图**；可在末尾加 `--json`（或 `json`）取得同一组结构化数据。`alias list` 则查看**所有平台的原始定义**，可以在命令开头加 `--platform`（简写 `-p`）缩小到一组，末尾加 `--json` 导出 JSON。这里的“所有”是 `alias list` 的默认含义，**当前 CLI 并不接受 `--platform all`**。

创建或覆盖某个平台上的定义，使用 `alias set [--platform 平台] 名称 = 模板文本`；删除用 `alias unset [--platform 平台] 名称`。未写 `--platform` 时，这两个操作都只作用于 `common`，**不会自动删除/修改同名的平台专用定义**。`set` 在所选作用域内同名时是替换；终端写法按第一个 `=` 分隔名称与模板，其后作为模板正文保存，不需要把命令整段重新按 Shell 参数解析。`alias reload` 用于丢弃内存快照并从 JSON 读回。

下面用一个临时自定义名称说明完整管理操作，而不是列举项目现有 Alias：

```text
alias set --platform common sample = shell echo "<message>"
alias resolve --json
alias list --platform common --json
sample "hello world"
alias unset --platform common sample
alias reload
```

其中保存后的 `sample` 调用按模板绑定 `message`，在 Client 侧运行展开的普通命令；`resolve` 与 `list` 的 JSON 都是**查询结果**，不是用 `--json` 改变被保存的模板。管理命令的输出使用 Structured Command Output 的文本表格或 JSON 渲染。

参数位置存在实际限制：`--platform` / `-p` 只在子命令后、被解析文本的开头识别；`list` 的格式后缀应放在末尾，例如 `alias list --platform mac --json`，不能假定所有选项任意换序都等价。`resolve` 不接受额外筛选参数，`reload` 也不接受参数。删除定义使用 `alias unset`。

Server 内建命令会先于 Alias 名称进行识别；顶层 `acmd` 也优先于 Alias 名称。因此应避免使用和已有 Server Built-in 或保留入口冲突的 Alias 名称，否则可能无法从普通终端按 Alias 调用。Alias 新建与改名都经 `AliasManager.MAX_ALIAS_NAME_LENGTH = 32` 统一校验名称长度，超过 32 个字符会拒绝保存，已存在的定义不因校验失败而被覆写；通过 CLI 设置 Alias 时检查名称、模板非空及长度；Web 编辑器还禁止名称含空白字符，建议始终使用无空格名称。

## 模板展开及实参绑定

Alias 模板只识别形如 `<name>` 的占位符，名称须符合 `[A-Za-z_][A-Za-z0-9_-]*`：第一个字符为字母或下划线，其后可包含数字、下划线和短横线。`<path>`、`<client-id>` 是有效占位符；`<two words>`、`<2bad>` 不会当作参数。`</dev/null`、`>` 及重定向文本也不会因为含尖括号就自动被视为占位符。

参数的身份取决于**名称**，不是尖括号出现的次数。系统按模板中**首次出现的唯一参数名**决定位置顺序；同名占位符再次出现时复用第一次绑定的值。例如：

```text
alias set sample = shell echo "<label> -> <path> -> <path>"
sample "Report A" "/tmp/a file"
sample --path="/tmp/a file" --label "Report A"
```

这两种调用绑定的都是 `label="Report A"`、`path="/tmp/a file"`；展开成 `shell echo "Report A -> /tmp/a file -> /tmp/a file"`。这里第二个 `<path>` **不需要第二份参数**。实际命令中的引号由模板作者设计，Alias 本身不会在替换时额外自动引用。

**位置调用**：在别名名称后按照唯一参数首次出现顺序提供值。Server 使用 Python `shlex.split()` 拆分调用文本，带空格的单个值必须正确引用；输入项数量必须刚好匹配，不足或过多都会报错。没有占位符的 Alias 不接收额外参数。由于使用 `shlex`，这里的词法规则并不自动等同于 Windows CMD 或 PowerShell 的原生参数解析。

**命名调用**：第一个参数以 `--` 开头时尝试 `--name value` 或 `--name=value`，名称必须与模板占位符完全一致（包括大小写），可以不按模板出现顺序输入；全部唯一参数都必须提供。未知名、重复名、缺失值以及位置与命名参数混用都会报错。命名调用最终也会归一化成按唯一参数顺序排列的值列表，和位置调用复用同一个字符串替换器。

存在两条实用边界：

- 如果第一个**位置值本身**以 `--` 开头，手动调用可在前面加单独的 `--` 强制位置模式，例如 `sample -- --version other-value`（前提是该模板确有两个参数）。
- 命名模式下，`--name --something` 会被当作缺失值；可以使用 `--name=--something` 明确传入以双短横线开头的字符串。

**Web Quick Actions 的参数表单**根据模板提取同一套唯一参数，每个参数只出现一个文本输入框；按首次出现顺序将字符串数组传给 Server，再由 `resolve_alias_definition()` 替换。Web 调用不使用终端的 `--name` 文本解析；它按所选定义和数组位置绑定。占位符不等于 Parameter Schema：这里没有自动的整数/布尔类型转换、Select、文件选择器、动态默认值或复杂业务校验。Web 表单目前允许输入空字符串，最终目标命令能否接受由实际命令决定。

**安全边界：这是未经上下文转义的文本替换**。系统不自动给文件路径加引号、不转义 Shell 特殊字符，也不知道占位符是在 PowerShell、Shell、Python 字符串还是命令选项中。上面把值放进引号只用于解释绑定规则，并不保证恶意引号或特殊字符安全。对敏感和破坏性操作，应在目标执行层使用适当的参数化或验证机制；不要把 Alias 当成输入净化器。

### 命令入口的第二次解析

这里要分清**输入层**和**执行层**。手动输入 Alias 时，Server 识别的是别名名称，展开结果直接以普通 `command` 类型下发到 Client。Client 先解析 `${rch:*}` 等可用于普通命令的变量，然后尝试查找其平台导出的 Shell-like 命令方法；如果没有对应导出方法，才按原文本走受管理的系统 Shell。因而 Alias 模板可以是一个可用的 Client 命令入口，也可以是普通系统 Shell 文本。写 `shell ...` 是一种明确执行 Shell 的方式，**不是 Alias 唯一支持的写法**。

这也带来不同层级的限制：

| 模板展开后开头是 | 终端直接调用 Alias 的行为 |
| --- | --- |
| Client 已导出的 Shell-like 命令 | Client 将调用相应命令方法，使用该方法自己的参数处理语义 |
| 普通系统命令（非已导出方法） | Client 走 Shell fallback |
| `shell ...` | Client 按其导出的 Shell 命令入口执行 |
| `acmd ...` | **不会**作为顶层 `COMMAND_TYPE_ACMD` 重新封装；它只是普通 `command` 文本 |
| Server Built-in 或另一条 Alias | **不会**回到 Server 执行内建分发或递归展开 |

因此，不应把模板中写入 `acmd ...` 理解成与用户在终端直接输入 `acmd ...` 等价，也不要把 Alias 嵌套或指向 Server Built-in 当成可靠通用能力。

但 **Quick Actions 的提交路径不同**：它会把某个定义展开后的文本交给 Web 任务系统，Web 任务可能从头经过 Server 的命令解析（详见下节）。所以一个以 `acmd` 或 Server Built-in 开头的**展开文本**，在 Quick Actions 的弹窗执行下可能走到该特殊入口，而从终端直接调用 Alias 时却不是这样。这属于当前实现必须了解的行为差异，不是可以依赖的跨入口等价保证。编写 Alias 时，优先采用目标 Client 上明确可执行的 Shell-like / Shell 命令模板。

Client 变量 `${rch:*}`、`${env:*}`、`${path:*}` 与 Alias 的 `<name>` 是两套不同替换语法，且发生在不同层次：Alias 的尖括号替换在 Server 进行；普通 `command` 的变量展开由 Client 执行。Alias 保存阶段不解析这些 Client 变量；最终能否展开，取决于该次实际提交的执行类型和目标 Client 支持情况。不要把这与 ACMD 的参数 Schema 混淆。

## Web 动作的编辑与任务派发

Web Quick Actions 的定义列表基于 Alias JSON，并非单独的 Quick Action 表。选中一个在线 Client 后打开管理弹窗，Server 在列表请求中重新加载 JSON，返回所有平台的原始定义和当前目标的作用域信息。界面默认显示 Current（`common` 加当前平台），也支持手动选择特定平台并按名称或模板文本搜索。New、Edit、Delete 对应 Alias 的新增、更新和删除，跨平台改名/移动时会检查目标作用域同名冲突；删除需要确认，只删除**选中的平台 + 名称**定义。

编辑时填写 Platform、Action name、Command，可顺便启用工具栏 Pin。执行时，如果模板带占位符，先打开按唯一参数生成的文本表单；没有占位符就直接提交。**Run** 会打开独立结果弹窗，**Run in Terminal** 把输入和后续结果放到正常终端显示链。二者都通过常规 Web Command Task 提交，仍受目标连接、前台任务占用、权限与取消约束。

真正需要注意的是这三种**命令提交模式**：

| 情况 | 提交到 Web Task 的文本 | 后果 |
| --- | --- | --- |
| Run（结果弹窗） | 已展开的原始定义命令 | Server 对这条完整命令进行通常的顶层解析 |
| Run in Terminal，选中定义正好是当前生效 Alias | 以 `shlex.join()` 构造的 `名称 + 参数` 调用 | 保留终端输入 Alias 的解析及 Alias 展开提示 |
| Run in Terminal，选中的是跨平台定义或已被覆盖的共享定义 | 该选中定义直接展开后的命令 | 避免同名覆盖导致实际运行到另一条定义，但会重新经过 Server 顶层解析 |

这里的“生效”判断考虑目标 Client 平台和是否被本平台同名项覆盖，而不是只检查这个名称是否存在。结果弹窗即使选择了一个被覆盖的 `common` 项，也会按**选中的那条 `common` 模板**展开，不会偷偷切换到平台覆盖版本。

Web 向任务附带 `quick_action`、`quick_action_run_id`、`quick_action_alias`、`quick_action_platform`、`quick_action_presentation`、显示命令和实际展开命令等 Metadata。返回 `task_id` 用于关联前台任务；SSE 命令输出和完成消息根据这些 Metadata、运行 ID 与展示模式路由到对应结果弹窗或 Terminal。弹窗聚合文本片段、显示 Success / Failed / Cancelled，支持 Copy；它不是独立的 JSON Table Viewer，关闭结果窗口也不等于取消远程命令。

**一个已知的参数边界**：在“生效 Alias + Run in Terminal”路径中，Server 用 `shlex.join()` 生成调用文本，但不会自动给第一个以 `--` 开头的位置值补 Alias 所需的单独 `--`。因此这种值可能被 Alias 误解释为命名参数；对于此类参数，优先使用结果弹窗，或者在手动终端调用中显式写 `--`。复杂跨 Shell 的转义同样需核对最终展开文本，不能只看表单里的原始值。

### Activity 与 Quick History 的区别

Alias 通过 Terminal 输入时，Server 的 AliasManager 展开参数并创建 Client 执行计划；只有实际发送到 Client，才生成一条 `kind=alias/action=invoke` 的 Activity。`invocation.input` 保留输入文本（例如 `now`），`invocation.target` 为 Alias 名称，`resolved.command_type=command`，`resolved.command` 是真正展开并派发的命令。

Quick Actions 的 Dialog / Terminal 两种呈现方式都通过 Metadata 保留选中 Alias 的身份、平台和参数，不能仅根据已展开文本推断是否为 Alias，尤其要正确处理选择被当前平台同名定义覆盖的共享 Alias。两者成功时可形成 Activity，但 **Quick Actions UI 不会额外写入 Quick Recent**；手动 Terminal/CLI 可复现的 Alias 成功执行才进入 Recent。失败、取消、超时不会更新 Recent 或覆盖已有成功快照。Alias 定义管理、列表查询属于 Server 操作，不产生 Activity。

### 工具栏及同步机制

在 Quick Actions 编辑弹窗打开 **Pin to Quick Actions dropdown**，会将该定义的 `{platform, alias}` 引用存入全局 Toolbar Preferences（SQLite）。Pin 不是复制模板，也不是 History 的收藏。Toolbar Layout 的位置/顺序与 Pin 的条目列表是两种配置；工具栏可以在自身的 Toolbar 或 More 位置展示 Quick Actions 入口。

工具栏下拉打开时，会读取保存的 Pin，并重新请求 Quick Actions 定义列表，按平台与名称精确匹配，只呈现 `in_current_scope` 的条目。**被目标平台覆盖的 `common` 定义仍可能出现在工具栏下拉**，因为它依然属于当前作用域；同名项并列时界面加平台标签。不存在、改名或移到其他平台的引用会因无法匹配或当前作用域不符而不显示。点击固定项用结果弹窗方式运行，有参数先填表单。

通过编辑器改名、跨平台移动或删除时，前端会尝试同步迁移/移除旧 Pin，但 Alias JSON 与 SQLite 偏好是两次独立保存：Alias 操作成功而 Pin 更新失败时，界面提示部分成功，不保证自动回滚。普通 Toolbar Settings 保存布局时会尽量保留现有 Pin 列表，避免一次布局修改清空固定命令。

Terminal 的命令候选包含当前有效 Alias 名称，帮助信息标示它来自哪个平台及其模板；`alias` 管理子命令也有专门的自动补全提示。候选生成依赖 Server 当前内存 Alias 表以及浏览器的候选缓存，**不能把补全结果当成磁盘配置实时刷新机制**。定义更新后如候选仍旧，应刷新候选或重新进入相应界面；Quick Actions 列表 GET 才保证在该请求时从 JSON 重新加载。

Web 接口以目标 Client 为上下文，基础路径为 `/api/connections/{client_id}/quick-actions`。GET 读取平台和定义列表；POST 新增；PUT 更新（需要原 `original_platform` 和 `original_alias`）；DELETE 删除。执行为 `POST /api/connections/{client_id}/quick-actions/execute`，请求以 `platform`、`alias` 定位原始定义，`arguments` 是**按占位符首次出现顺序排列的数组**，`presentation` 为 `dialog` 或 `terminal`，还可携带 `run_id`。服务端重新验证目标连接、平台、定义、参数数量及展示方式，并返回 `task_id`、运行 ID、显示命令、展开命令与提交命令等信息。终端 Alias 的命名参数文本格式**不适用于这里的 `arguments` 字段**。

排错时先确认当前目标平台及 `common` 覆盖、所选定义来源，然后区分终端 Alias 还是 Quick Actions 的哪种提交路径。找不到新定义要检查磁盘与内存刷新；参数错误要检查唯一占位符、参数顺序和是否意外进入 `--name` 模式；模板运行异常要检查真实的 Client Shell-like 方法或系统 Shell，以及引号和变量展开。命令执行不成功、前台任务被占用或设备离线，都遵循正常命令链的错误和状态机制，而不是 Quick Actions 提供另一种执行沙箱。
