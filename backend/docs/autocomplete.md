# Terminal Command Autocomplete

Terminal 的自动补全将命令发现、当前设备的历史与收藏、Server 管理的数据，以及目标 Client 的运行时上下文汇集到同一个输入框。它不仅补全命令名，还能按正在输入的命令提供脚本、路径、配置项和动态变量等候选。**候选的生成不执行候选所代表的业务命令；只有用户提交输入后才进入正常的命令执行链。**

自动补全并非操作系统 Shell 的通用 Tab Completion。Web Terminal 与 RCHCLI 都向 Server 查询上下文候选；需要目标 Client 文件系统时，Server 通过独立的 `type: completion` 消息请求 Client，不执行隐藏命令，也不占用命令 Foreground、Activity 或 History。Client 命令的路径补全规则来自握手 `command_manifest` 中的命令注解；Web 前端只为非 Client 的 Common Ops 保留一份集中配置。

## 候选从哪里来

输入框有两条相互配合的候选链路：**命令级候选**用于发现可调用的入口，**上下文补全**用于填充已识别命令后面的参数。变量占位符还有一条由前端直接处理的专用分支。

```text
Web Terminal 输入内容
        │
        ├── 光标所在参数使用 @@ ──→ 已登记的本机路径规则或目标 Client 文件系统候选
        │
        ├── 存在尚未闭合的 ${...} ──→ Client Variable Manifest → 变量候选
        │
        ├── 任何命令的参数上下文 ──→ Server Completion Provider（无提供器则返回空候选）
        │                                      │
        │                                      ├── Server 数据：历史、Alias 管理、脚本、路径收藏、External Tools、本机路径
        │                                      └── 需要目标机器时 → Client Completion Provider
        │
        └── 其他输入 ──→ 基础命令候选（Client Manifest + Server Built-ins + Alias）
                                       + 前端常用操作候选 + 已固定的命令历史
```

**基础命令候选**来自 `GET /api/connections/{client_id}/command-candidates`。Client 在建立连接时通过 `command_manifest` 上报导出的 Shell-like 命令和结构化 `acmd` 命令；Server 再合并 Built-in 和当前生效的 Alias。前端只显示允许建议的条目（`suggest !== false`），另外加入少量常用操作和当前设备已经 Pin 的命令历史。Web Terminal 另外加入 **Frontend** 类别的本地 `edit`（用 Monaco 编辑远程文本）和 `clear`（清空终端输出）；这两个操作直接在浏览器处理，候选不会发往 Client。若远端清单恰好有相同名称，本地入口优先。按候选模板文本去重后，**空输入**时按固定分组顺序、组内按命令名称字母顺序展示：`shell → execution → session → system → network → privilege → media → file → automation → transfer → runtime → maintenance → python → acmd → common_ops → frontend → server → alias → Pin Command`。`common_ops` 使用现有命令分组名称，已 Pin 的 History 位于末尾。已输入文字后的匹配及上下文补全仍沿用各自的排序逻辑。

命令 Manifest 由 Client 当前平台支持的命令注册信息生成。`@desc(..., suggest=False)` 可以让内部命令保持可执行、却不进入普通命令发现列表；`acmd` 项来自结构化命令注册表。输入 `acmd` 或尚未完成的子命令前缀（例如 `acmd im`）时，候选直接匹配握手 Manifest 中的完整 ACMD 名称；完整子命令名后输入空格，才进入该命令的参数级补全。Manifest 属于**握手快照**：Client 本地命令注册内容变化后，不能假定已连接浏览器会自动看到更新的 Manifest。顶层列表的别名则来源于 Server 内存中的当前生效定义，而不是一个永久写死在前端的名称列表。

**上下文补全**使用 `POST /api/connections/{client_id}/command-completions`。Server 根据原始输入和当前 Client 的握手 Manifest 决定是否存在 Client 补全声明；需要 Client 动态数据时，通过独立 `type: completion` 消息传递原始输入、光标位置和可选的 CompletionSpec override。Client 返回标准 Result Envelope，`data.items` 使用统一 Candidate 结构。该请求不经过 `command` / `control` 执行路径。

`CompletionSpec` 只有 `provider` 与 `kinds` 两个字段。Shell-like 命令在 `@desc(..., completion=...)` 声明；ACMD 在对应 `ArgumentOptionSpec.completion` 声明，参数名/位置沿用已有参数 Schema，不重复放进 CompletionSpec。当前实现的 Provider 是 `filesystem`，同时查询文件和目录，再由 `kinds` 过滤。Provider Registry 留有后续扩展入口；未来可增加 `shelllike` 等 Provider，但本轮不引入子命令或选项补全。

Server/Client 的 Provider 负责候选生成，浏览器负责缓存、过滤、选择与回填。前端不维护 Client 命令名单；新增 Client 命令的参数补全只需在命令声明处添加 CompletionSpec。非 Client Common Ops 的少量路径规则集中在 `frontend/src/config/commonOps.json`。Server Builtin 的静态子命令仍由 Server Registry 提供，不受本轮 Client CompletionSpec 改造影响。补全查询不是执行 `cd`、`download`、`history run` 或其他候选业务操作本身。

## 历史、收藏和动态资源

### Quick History 与 `!index`

命令历史有三种与输入框有关、但行为不同的用途：

- **Pinned Commands**：基础下拉候选中可直接出现已 Pin 的完整命令文本；普通未 Pin 的 Recent 不会全部作为基础命令候选混入。
- **`history` 上下文**：补全提供 `history run <index>` 形式的候选，说明文字显示索引实际对应的命令。
- **`!<index>` 快捷形式**：输入 `!` 或数字前缀时，Server 基于当前机器的 Quick History 生成快捷重放候选。

`index` 来源于当前机器的 Quick History 展示顺序：Pin 在前，再接未 Pin 的 Recent，并在当前结果上重新分配索引。它不是稳定的数据库主键。收藏顺序或近期执行记录一旦变化，相同数字可能指向另一条命令。候选在选中时只是填入输入框；用户实际提交 `history run <index>` 或 `!<index>` 时，才会重放对应的命令。History Replay 与单纯回填编辑的区别见 [Command History](command_history.md)。

历史数据按 `machine_id` 关联，因此同一台机器的新 Client 连接仍能取得原来的历史和收藏，但前提是 Server 可正确解析当前连接与设备身份。快捷候选不包含全部 Execution History 的逐次输出记录。

### Server 管理的数据

部分补全读取的并不是目标设备的文件系统，而是 Server 当前管理的数据。例如，保存过的远程路径 Quick Jump 名称由当前机器的 Pinned Paths 提供；Alias 管理入口会补全管理动作，但具体 Alias **名称**作为顶层候选由 AliasManager 的有效定义提供，管理动作 Provider 本身不会逐个读取 `aliases.json` 生成名称候选。

Script 的执行候选来自 Server 脚本目录，**只根据 Script Metadata `platforms` 声明**筛选当前设备；没有该声明的脚本不参与 CLI 列表与补全，路径名不作为平台依据。候选在 Server 过滤后直接提供给 Terminal，前端不再根据目录名过滤。此规则不限制显式执行。External Tool 的候选由 Server 的 Exec Catalog 按目标平台和架构筛选，除入口操作外，也可以补充符合目标设备条件的 Exec 名称。运行时配置 `config set/reset` 的参数候选从目标 Client 的 Configuration GET 查询真实配置键。支持位置参数及 `--key` 两种补全写法。`script view/exec` 同样支持名称位置参数和 `--name` 补全。

`job start <name>` 使用符合当前平台的 Job Catalog；`job stop <name>`、`job status <name>` 使用当前设备活跃 Job 实例的 `job_key`；`job logs <name>` 使用当前设备正在运行的 Job 名称，均通过 Web 与 RCH CLI 共用的 Server Completion Provider。

这些动态候选的数量与内容取决于当前设备、Server 配置及 Catalog，而不是一套固定的命令总表。详见 [Aliases and Quick Actions](alias_quick_actions.md)、[Remote Files](remote_files.md) 和 [External Tools](external_tools.md)。

## 文件系统路径补全如何工作

远程路径候选读取目标 Client 文件系统；Server 本机路径候选读取 Server 自身的文件系统。Client filesystem Provider 使用现有路径解析器把输入转换到当前工作目录或明确给出的目标目录，再查询真实目录内容。文件与目录由同一个 Provider 返回，`CompletionSpec.kinds` 决定允许的候选类别；目录候选优先于文件候选，同一类型内按名称排序。

当前路径补全声明：

| 声明位置 / 输入入口 | `kinds` | 归属 |
|---|---|---|
| Client Shell-like `cd` | `directory` | Client 命令注解 |
| Client Shell-like `download` | `file`, `directory` | Client 命令注解 |
| ACMD `image_info.path`、`sqlite_query.db` | `file`, `directory` | ACMD 参数 Schema 注解 |
| Common Ops `rmdir` | `directory` | `commonOps.json` |
| Common Ops `cat`、`file`、`allow_file`、`python3`、`type` | `file`, `directory` | `commonOps.json` |
| `upload` | Server 本机目录和文件 | Server 本机文件系统 Provider（保持原实现） |

Client Shell-like 命令的 `completion` 注解直接进入现有 `command_manifest`；ACMD 只在对应参数上附带补全声明。Server 读取握手快照决定是否发送 completion 请求，Client 再用本地注解确定 Shell-like 命令或 ACMD 当前参数，并调用 `filesystem` Provider。Common Ops 不是 RCH Client 命令，因此 Web 在请求中附带同样的两字段 CompletionSpec override；RCHCLI 的本地 `edit` 也使用相同 override。Server `upload` 仍由 Server 本机文件系统 Provider 处理，不通过 Client Completion 消息。

例如输入 `cd /home/al`，浏览器将完整输入和光标位置发给 Server；Server 根据当前 Client Manifest 确认 `cd` 声明了 filesystem completion，再发送 `completion` 消息。Client 返回 `/home` 下符合 `directory` 的子项；浏览器按现有输入前缀过滤并回填完整命令。`download` 同理，但可选普通文件。ACMD 的命名参数和位置参数由 Client 侧原有参数 Schema 定位，不在前端复制命令名白名单。Windows 路径分隔符 `\` 与盘符根目录继续由现有路径解析处理。输入以目录分隔符结束时，会查询该目录内部的下一层子项。

**路径补全只完成候选路径查找与插入。** 命令选项、参数类型和必填项由对应命令的 Schema 在执行时校验。因此，尤其是结构化 ACMD（例如要求 `--db`、`--query` 等命名参数的命令），路径候选出现并不保证整行命令已经符合其参数要求。用户仍须遵守该命令的实际参数定义。`acmd` 并没有因此获得通用的所有选项、类型或位置参数自动补全；参见 [ACMD](acmd.md)。

已登记命令的**自动路径补全**按命令名后的参数文本和最后一个路径分隔符识别查询目录；它直接使用 Provider 返回的路径文本，含空格或 Shell 特殊字符的参数须按对应命令的语法正确引用。任意参数位置的显式 `@@` 补全提供独立的选择与引用处理，操作方式见下一节。执行目录与路径权限校验仍发生在真正运行命令的时候。

## 显式路径占位符 `@@`

在 Terminal Input 中，`@@` 是统一的文件与目录补全入口。它可放在任意命令、Alias、位置参数或命名参数中，例如 `allow_exec @@`、`myalias @@`、`xxx --path=@@`。默认查询当前选中 Client；已登记的 Server 本机路径入口使用 Server 文件系统，例如 `upload @@/tmp/`。目录在前、文件在后，触屏设备也可以点击候选。

### 从相对路径逐层选择文件

例如要填写当前 Client 工作目录中的 `test/folder/file.txt`，先输入 `allow_exec @@tes`。候选中包含 `test` 目录时，按 **↓** 只进行预览：输入框显示 `allow_exec @@test`，**`@@` 仍在，且不会自动添加 `/`**。此时有两种操作：

- **继续浏览**：直接手动输入 `/`，变成 `allow_exec @@test/`，随后查询并显示 `test/` 内的目录和文件；继续按 ↑ / ↓ 预览下一项，并在需要进入的目录后手动输入 `/`。
- **完成路径插入**：按 **→**，或直接用鼠标／触屏点击候选，才会移除 `@@`，变成 `allow_exec test`。此时可以直接运行使用该目录的命令。如果已确认了一个目录但想继续深入，也可以在它后面手动输入 `/`，继续查找下一层。

```text
allow_exec @@tes
  ↓ 预览 test             → allow_exec @@test
  手动输入 /              → allow_exec @@test/           （查看 test 下的候选）
  ↓ 预览 folder           → allow_exec @@test/folder
  手动输入 /              → allow_exec @@test/folder/    （查看 folder 下的候选）
  ↓ 选择 file.txt         → allow_exec test/folder/file.txt（文件直接完成回填）
```

如果只要 `test` 目录，则从 `allow_exec @@test` 直接按 **→**，得到 `allow_exec test`，不需要输入 `/`。也可以直接点击 `test` 候选完成提交。使用显式相对路径前缀时，从 `@@./tes` 开始。路径由当前 Client 的文件系统补全 Provider 返回，最后的命令是否接受该目录或文件仍按对应命令的参数规则处理。

### 从绝对路径或命名参数开始

macOS / Linux 可输入 `@@/Users/f`，Windows 可输入 `@@C:\Users\`。例如：

```text
myalias --path=@@/Users/f --verbose
  ↓ 预览 flc              → myalias --path=@@/Users/flc --verbose
  手动输入 /              → myalias --path=@@/Users/flc/ --verbose
  ↓ 预览 Desktop          → myalias --path=@@/Users/flc/Desktop --verbose
  手动输入 /              → myalias --path=@@/Users/flc/Desktop/ --verbose
  ↓ 选择 file.txt         → myalias --path=/Users/flc/Desktop/file.txt --verbose
```

选择候选时仅改变光标所在的路径片段；命令、Alias、选项及其余参数保留。路径包含空格时补全会加上必要的引号，方向键预览时将 `@@` 放在引号里面，例如 `myalias --path="@@/Users/My Folder"`。方向键预览的光标在目录路径末尾、结束引号之前，可以直接输入 `/`（Windows 可输入 `\`）继续浏览。

### 键盘和鼠标操作

- **↑ / ↓**：选中目录时预览路径并保留 `@@`；选中文件时直接回填完整路径并移除 `@@`。
- **手动输入 `/`（Windows 也可用 `\`）**：查询预览路径对应目录的下一层候选；每一层均由手动输入分隔符触发，不会自动进入子目录。
- **→**：确认当前预览的目录，移除 `@@`，不执行命令、不自动追加分隔符；文件在选择时已完成回填。直接点击目录或文件候选也会确认，触屏设备使用点击完成选择。
- **Escape**：取消方向键预览并恢复预览前输入。
- **Run / Enter**：执行输入框当前的命令。目录预览需先按 → 或点击候选移除 `@@`；文件选中后已经是可提交的路径。

远程 `@@` 通过 `completion` 消息显式选择 `filesystem` Provider，并同时请求文件和目录；Python Client 与 Go Client 复用当前远程设备的只读路径 Provider。Server 本机 `upload @@` 仍走 Server 本机文件系统 Provider。查询、选择及下一层补全均保持各自文件系统归属。

## 变量占位符补全

输入中出现尚未结束的 `${` 后，Terminal 会优先进入**变量补全模式**，不再把后面的内容交给命令名或路径 Provider。

```text
shell echo ${
shell echo ${rch:
shell echo ${env:HO
shell echo ${path:do
```

输入 `${` 时展示可用命名空间；接受 `${rch:`、`${env:`、`${path:`、`${var:` 等命名空间候选后，继续选择变量名。候选来自连接握手中的 `variable_manifest`：`rch` 描述当前 Client 的运行时/设备属性，`path` 给出常用系统目录，`env` 提供 Client **进程环境**中存在的环境变量名。`var` 提供 `${var:NAME}` 模板，名称由当前连接上的 `var` 命令设置。对于 `env`，候选是在握手时从该 Client 的 `os.environ` 构建的快照，不能把它理解成每一次输入都实时查询环境变量。

变量候选会保留 `${` 前已经输入的整段命令，插入完整的 `${namespace:name}`；命名空间候选继续保留未闭合的 `${namespace:`，以便接着补全变量名。命名空间按前缀筛选，变量名按不区分大小写的包含关系筛选，并倾向优先展示前缀匹配。

**候选插入变量表达式，执行时由 Client 解析当前值。**Script 与 ACMD 不自动使用这条普通命令变量展开链。候选中的环境变量名即使在握手时存在，也可能在执行时已经变化或不存在。参见 [RCH Variables](variables.md)。

## 输入框选择、过滤与缓存

Terminal 的下拉候选按标题文字筛选：优先精确匹配，其次前缀匹配、包含匹配；对于 `script exec` 脚本路径还允许较保守的多词包含匹配。匹配依据是候选插入的命令文本，而不是对描述文本做全文搜索。通过统一结构显示 `help`、来源分组，并在各类候选中保留必要的附加元数据。

交互上，**上下方向键**可以轮流预览候选内容，预览阶段保留原始输入供继续筛选；按**右方向键**提交当前预览文本而不执行，按 **Escape** 恢复进入预览前的输入。点击下拉候选或使用组件选择交互会将文本回填输入框；通过 Run 或 Enter 提交命令才真正发起执行。选择变量命名空间之后，可以继续刷新候选列表以补全下一段。

动态 Provider 的查询经过约 **260 毫秒**防抖，并按目标 Client、机器、当前工作目录、命令及目录上下文缓存；同一上下文下的已缓存结果由前端本地过滤，最多展示 **50 条**动态候选。Client filesystem completion 使用独立消息与 PendingResults 请求关联，不占用 Foreground，因此即使普通命令正在执行，也可以独立查询路径候选。

切换设备、机器身份或工作目录会重置相应缓存。成功提交命令后，输入框关闭补全列表、清空动态缓存并重新加载基础命令及 Pin 历史；这使新执行的历史索引与已更新的 Alias 等信息有机会在下一轮候选中生效。**Server 上的数据变化并不一定主动推动已打开的浏览器补全缓存失效**：例如外部编辑了 Alias 文件、添加脚本、变更配置，可能要重新加载候选、运行相应命令或重新选择设备才能看到变化。

## 扩展补全能力的接入边界

自动补全使用 `CommandCompletionParser`、`CompletionContext` 和统一的 `CompletionCandidate`：候选包括标题 `title`、真正写入输入框的 `insert_text`、说明 `description`、`source`、`group`、`kind`、`priority` 和可选的 `metadata`。序列化后的命令候选统一以 `name` 表示插入文本，以 `title` 表示需要单独展示的标题，以 `help` 表示说明。一个 Provider 只需声明支持哪些命令上下文，并返回候选，不应在查询过程中修改文件、启动任务或执行候选命令。

新增 Client 路径补全时，在 `@desc` 或 ACMD 参数 Schema 上声明最小 CompletionSpec；Server 通过握手 Manifest 识别该声明，Client Completion Service 按 `provider` 选择实现。Common Ops 规则集中维护在 `frontend/src/config/commonOps.json`。新增 Server 本机路径补全仍使用 Server 文件系统 Provider。未来新增 Provider 只需注册实现并使用同一 CompletionSpec 入口；本轮只实现 `filesystem`，不提前引入 Shell-like 子命令/选项 Provider。

相关 HTTP 接口的返回结构如下，候选文本为结构示意：

```json
{
  "context": {
    "raw_input": "cd /tmp/",
    "command_name": "cd",
    "argument_text": "/tmp/",
    "current_token": "/tmp/",
    "cursor_position": 8,
    "max_results": 50,
    "metadata": {"client_id": "<target-client-id>"}
  },
  "items": [
    {
      "name": "cd /tmp/logs",
      "title": "cd /tmp/logs",
      "value": "cd /tmp/logs",
      "insert_text": "cd /tmp/logs",
      "help": "/tmp/logs",
      "group": "filesystem",
      "source": "client_filesystem",
      "kind": "directory",
      "priority": 10,
      "candidatePath": "/tmp/logs",
      "lookupPath": "/tmp",
      "isDir": true
    }
  ]
}
```

Provider 内部按 `priority` 与标题排序、按插入文本去重；某个 Provider 出错时，注册表会跳过它的异常而不让整个候选链崩溃。这保证自动补全保持辅助性：没有候选、远程目录不可访问或完成查询失败，都不应被解释为业务命令一定不可执行。

Client 与 Server 共用 `CommandLineResolver` 处理 Shell-like Token、原文 Span 和 Cursor 位置。Client 使用它按 ACMD 的 `ArgumentOptionSpec` 定位当前参数对应的 CompletionSpec；Server Registry 使用同一 Token 边界逐层匹配已声明的子命令，并将叶子参数原文交给既有参数解析器。候选 Provider 的筛选与业务查询保持各自职责。Resolver 只提供 Shell-like Token 与原文 Span，不解析完整 Shell AST，也不替代执行阶段的参数校验。需要在任意位置选择远程文件或目录时使用 `@@`；真正执行命令时的权限、类型与路径解析规则仍由各自的执行模块决定。


## Server Registry 静态子命令补全

对于 `xt exec`，输入 `xt exec ` 可补全 `list`、`info`、`which` 与当前目标平台 Catalog 提供的公开 Exec 名称；输入 `xt exec info ` 或 `xt exec which ` 可补全对应的 Exec 名称。`xt package` 提供 list/install/uninstall 与 Package 名称候选，`xt module list` 提供 Package 候选，`xt instance` 提供 create/list/start/stop/restart/status/logs 与 Daemon Module 候选。已输入 Exec 名称后，后续原生参数不由 XT 补全器接管。

Server 注册表 `server_builtin_registry.py` 是一级 Builtin 与 `alias/job/script/xt/history/httpctl` 子命令唯一的静态定义来源。统一的递归遍历向普通 Builtin、XT 和 Help 提供静态路径，XT Provider 仅处理 Client 运行时安装、模块、实例及 Exec 等动态候选。Server 本机路径补全依命令节点上的 `CompletionSpec` 选择文件或目录候选；`upload` 的 RawTail 声明两种类型。`RegisteredServerSubcommandCompletionProvider` 从该表生成 `script list/view/exec`、`job list/start/logs/ps/status/stop/stop-all` 等结构；动态 `script exec <path>`、`job start <name>` 仍由专门 Provider 查询当前 Server Catalog。前端 `CommandInputBar` 对任何命令都可查询统一 Server 补全服务；服务端按 Provider 选择是否生成候选，脚本仍由 Metadata 平台信息过滤。`help` 的目标名称与子命令由同一 Server Builtin Registry 生成。

### v34.6 顶层命令与平台筛选边界

Server Registry 的 `script` 是一级命令，来源为 `server`；它不应被当作 `script exec <path>` 的特定平台脚本进行目录筛选。输入 `sc` 应能找到 `script`，选中后再通过上下文 Provider 获取 `list/view/exec/run` 子命令。只有真实 Script 路径候选才进行平台筛选。Job Catalog 的 `job start` 动态候选采用与 CLI `job list` 一致的 Metadata 平台条件。

