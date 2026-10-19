# RCH Variables

运行时变量的取值发生在目标 Client 上，而非浏览器或 Server 预先替换。普通命令在进入 Client 方法查找及 Shell 执行之前解析 `${namespace:name}`，使相同命令能引用当前设备的进程、环境与路径。Script SDK 另提供以执行上下文为基础的读取接口。

变量值会受进程身份、工作目录、操作系统和所用执行模式影响。其机制是文本展开，不会自动理解 Shell 引号、参数分隔和业务类型，所以需要区分变量解析成功与最终命令安全可执行。

## 目标 Client 的变量替换管线

普通 Client 命令会在**命令派发之前**进行变量展开。例如，在 Web Terminal 中输入：

```text
shell echo ${rch:uid}@${rch:hostname}
```

如果目标 Client 的运行用户名是 `alice`，主机名是 `macbook-pro`，展开后相当于执行：

```text
shell echo alice@macbook-pro
```

执行过程如下：

1. Web Terminal 将包含变量占位符的原始命令发送到 Server；Server 将它交给选中的 Client。
2. Client 在本地识别 `${...}` 占位符，按命名空间读取当前值，并将结果替换到命令字符串中。
3. Client 解析**替换后的完整命令**，优先匹配内置命令；没有匹配时回退到 Shell 执行。
4. 执行结果通过现有连接返回 Server 和 Web Terminal。变量解析出错时，命令会在派发前停止，不会执行尚未解析完成的命令。

当前提供三个命名空间：

| 命名空间 | 用法 | 取值来源 |
|---|---|---|
| `rch` | `${rch:pid}` | Client 的运行时、设备身份、系统和时间信息 |
| `env` | `${env:HOME}` | 目标 Client **进程**的环境变量 |
| `path` | `${path:downloads}` | 目标 Client 上常见系统目录的路径 |

这里的关键在于**取值发生在目标 Client**。当 Server 与 Client 运行在不同操作系统时，`${rch:pid}`、`${env:PATH}` 和 `${path:home}` 都表示目标 Client 的值，不是 Server 或浏览器的值。变量也不是服务端保存的一套用户自定义键值对，而是根据当前执行上下文求得。

普通命令采用自动插值；Python Script 与结构化 `acmd` 使用不同执行链，**不自动对其代码或参数执行同样的字符串替换**。Script 可以通过 SDK 主动读取和展开变量，详见第六节。

## Client 运行时信息的引用

`rch` 命名空间当前包含 **23 个内置变量**。它们统一使用 `${rch:name}` 语法，但各自返回的含义不同。

### 主进程与工作目录字段

| 变量 | 含义 |
|---|---|
| `${rch:exec_path}` | 当前 Client 使用的 Python 解释器或打包程序的可执行路径 |
| `${rch:launch_command}` | 启动当前 Client 的完整命令，包含必要的启动参数 |
| `${rch:runtime}` | Client 的运行根目录 |
| `${rch:pid}` | 当前 Client 进程的 PID |
| `${rch:uid}` | 当前 Client 进程的运行用户名 |
| `${rch:cwd}` | Client 当前工作目录 |
| `${rch:shell}` | 目标系统优先使用的 Shell 路径 |

这几个值容易混淆：

- `exec_path` 表示**可执行程序本身**。在 Python 脚本运行方式下通常是 Python 解释器路径；打包后通常是 Client 程序路径。路径包含空格时，这个变量返回的值会用双引号包裹。
- `launch_command` 表示**启动命令**。通过 Python 脚本启动时包含解释器、启动脚本及原始参数；打包方式下通常是程序的启动路径。它不是单纯的目录，也不一定只有一个可执行文件名。
- `runtime` 表示**运行根目录**：Python 脚本运行方式为 Client 启动脚本所在目录，打包模式为客户端可执行文件所在目录。
- `cwd` 是当前工作目录，可能随着运行中的目录切换而改变，不能当成 `runtime` 的同义词。
- `uid` 返回运行用户名，而非数字形式的 Unix UID；`shell` 会根据系统及可用的 Shell 选择对应路径。

例如：

```text
shell echo ${rch:pid}
shell echo ${rch:cwd}
```

第一条查看当前 Client PID，第二条查看当前工作目录。输出反映命令实际执行时的 Client 状态。

### Client 身份及连接属性

| 变量 | 含义 |
|---|---|
| `${rch:hostname}` | 目标 Client 主机名 |
| `${rch:command_id}` | 当前命令的 ID |
| `${rch:client_id}` | 当前 Client 连接实例 ID |
| `${rch:machine_id}` | 目标设备的机器身份标识 |

`client_id` 与 `machine_id` 不同。前者区分客户端连接实例，重新启动 Client 可能获得新的 ID；后者标识设备身份，可用于关联来自同一设备的不同连接。`command_id` 则属于单次命令的执行上下文，如果当前解析环境没有提供命令 ID，会得到空字符串。

在命令中可以组合多个变量，以便同时观察目标连接和机器：

```text
shell echo ${rch:hostname} ${rch:client_id} ${rch:machine_id}
```

### 平台与版本字段

| 变量 | 含义 |
|---|---|
| `${rch:build_ver}` | Client Build 版本 |
| `${rch:py_ver}` | Client 使用的 Python 版本 |
| `${rch:platform}` | 标准化平台别名，如 `win`、`mac`、`linux`、`ios` |
| `${rch:os_type}` | 操作系统的显示名称 |
| `${rch:os_alias}` | 标准化平台别名，与 `platform` 同一来源 |
| `${rch:os_name}` | 操作系统名称 |
| `${rch:os_ver}` | 操作系统版本 |
| `${rch:arch}` | 机器架构 |
| `${rch:manufacturer}` | 设备制造商 |
| `${rch:model}` | 设备型号 |

`platform` / `os_alias` 用于需要统一平台判断的场景；`os_type`、`os_name` 和 `os_ver` 则分别提供显示名称、系统名称与版本信息。部分硬件属性由平台提供，不能假定所有设备都会返回同样详细的制造商、型号信息。

### 生成时刻与时区值

| 变量 | 时间格式 | 示例 |
|---|---|---|
| `${rch:timestamp}` | `yyyyMMdd-HHmmss` | `20261016-163000` |
| `${rch:datetime}` | `yyyy-MM-dd HH:mm:ss` | `2026-10-16 16:30:00` |

时间以**目标 Client 所在运行环境的本地时钟**生成，不使用 Server 的时间。上表时间仅为格式示例。

例如，在 Unix 风格 Shell 中按执行时间创建目录：

```text
shell mkdir "backup-${rch:timestamp}"
```

命令执行时先把时间占位符替换为实际值，再创建对应目录；它不是固定的目录名，也不会在 Server 发出命令时预先计算。

## 环境与路径命名空间

### 读取运行环境

`env` 不维护固定的环境变量列表，而是直接读取目标 Client 进程的环境变量。常见写法包括：

```text
${env:HOME}
${env:USER}
${env:PATH}
${env:APPDATA}
${env:TEMP}
```

这些示例并不保证在每个平台上都存在。例如 `APPDATA` 常见于 Windows，而 `HOME` 常见于 Unix 系统。变量名使用实际环境中的名称，`env` 名称部分**保留大小写**；在大小写敏感的系统中，`PATH` 与 `Path` 可能代表不同的键。

例如在 Client 命令通道执行：

```text
shell echo "${env:HOME}"
```

Client 读取其 `HOME` 环境变量并把值放入命令。如果不存在，变量展开直接失败，不会默默替换为空字符串。这里引用的环境不是浏览器本地环境，也不一定等于目标设备当前 GUI 登录用户的环境。

环境变量可能包含 Token、密钥或其他敏感值。通过命令将其输出时，敏感内容可能进入终端结果与执行记录，因此不应无差别地打印全部环境变量。

### 系统目录映射

`path` 命名空间当前暴露四个路径：

| 变量 | 返回内容 |
|---|---|
| `${path:home}` | Client 运行用户的 Home 目录 |
| `${path:desktop}` | 该用户的 Desktop 路径 |
| `${path:downloads}` | 该用户的 Downloads 路径 |
| `${path:temp}` | 当前系统的临时目录路径 |

例如：

```text
shell echo "${path:downloads}"
```

这能得到目标设备对应的 Downloads 路径，减少在不同系统之间硬编码目录名称的需要。但它返回的是**路径字符串**，并不意味着目录一定存在、可写，或当前 Client 一定具有访问权限。

Client 的系统路径信息还可能包含 Root、Documents、程序位置等字段，但它们不等于 `${path:*}` 都已开放。当前 `path` 变量只认上表四个名称；使用 `${path:documents}` 或其他未定义名称会报错。

## 解析时序与命令引用规则

### 缺失变量与替换失败

一条普通命令可以出现多个变量，也可以重复引用同一个变量：

```text
shell echo ${rch:hostname} ${rch:pid} ${rch:hostname}
```

解析器在一轮替换中处理匹配的占位符。`rch` 和 `path` 变量名不区分大小写，命名空间也不区分大小写，因此 `${RCH:PID}` 与 `${rch:pid}` 能解析为同一项。`env` 的名称部分则按输入名称读取系统环境变量。

RCH Variables **不是表达式语言**：不支持计算、条件、函数调用，也没有通过它创建自定义持久化变量的操作。正确写法需要带有受支持的命名空间，如 `${rch:pid}`。不符合 RCH 变量格式的其他字符串（例如 `${pid}`）不会被这套解析器当作 RCH 变量替换；如果随后进入系统 Shell，则由 Shell 自己决定是否处理。

主要异常行为如下：

| 输入情况 | 当前结果 |
|---|---|
| `${rch:unknown}` | 报错：未知 RCH 变量 |
| `${env:NOT_EXIST}` | 报错：目标 Client 未设置该环境变量 |
| `${path:unknown}` | 报错：未知路径变量 |
| `${custom:name}` | 报错：不支持的命名空间 |
| 变量实际返回 `None` | 报错：变量没有有效值 |

在普通命令中遇到这些错误时，会得到类似：

```text
Failed to resolve command variable: Unknown rch variable: unknown
```

由于展开是在命令派发之前执行，这类错误发生时，不会继续运行原命令。变量的字符串内容也不会再进行递归变量求值：当前机制是一次展开，而不是反复求值直到没有占位符。

### 引号与 Shell 上下文

RCH Variables 主要做**字符串替换**，不会普遍为替换结果自动进行 Shell 转义。例如目标目录为 `/Users/alice/My Projects`，直接执行：

```text
shell ls ${rch:cwd}
```

在 Unix Shell 中可能被拆成两个参数。对这类普通路径值，应根据所使用的 Shell 加上适当引号：

```text
shell ls "${rch:cwd}"
```

`rch:exec_path` 是特例：其值在路径包含空格时已经带双引号；`rch:launch_command` 则按启动命令的结构组合了可执行路径及参数。不应不加判断地对这些值再套一层引号，否则可能破坏原本的命令结构。

还需要区分 RCH 占位符和 Shell 自身的 `$HOME`、`${HOME}`、`%APPDATA%` 等语法。RCH 先在 Client 侧做文本展开；随后系统 Shell 可能继续处理 Shell 自己的变量和特殊字符。因此，对于来自环境变量或其他外部内容的值，不要假设插值自动解决了 Shell 注入或参数分词问题。Windows 与 Unix 的引号规则也不同，应使用目标 Shell 适用的写法。

## 变量发现及输入补全

### Manifest 提供的发现能力

Client 在连接握手时上报 `variable_manifest`，Server 随连接信息保存并转给 Web UI。Manifest 是**支持的变量定义清单**，不是在连接时固定计算好的所有变量值。每个预定义变量包含命名空间、名称、模板、描述和动态标记，例如：

```json
{
  "namespace": "rch",
  "name": "pid",
  "template": "${rch:pid}",
  "description": "Current Client process ID.",
  "dynamic": true
}
```

`dynamic: true` 表示这项信息应在使用时解析。`env` 的 Manifest 使用通用模板 `${env:NAME}`，另外提供从 Client 当前环境变量名构造的候选列表，例如：

```json
{
  "namespace": "env",
  "name": "NAME",
  "template": "${env:NAME}",
  "description": "Read NAME from the target Client process environment at execution time.",
  "dynamic": true,
  "candidates": ["HOME", "PATH", "USER"]
}
```

上面的 `candidates` 仅示意数据结构；实际名称来自目标 Client 的环境变量，不保证与示例相同。

连接信息窗口的 **Variables** 标签直接展示这些模板及说明，便于查询可用名称。它不是变量编辑器，不提供创建、修改或删除变量值的操作，也不会因为打开标签页就向 Client 重新请求所有变量当前值。

### 补全提示和候选内容

Web Terminal 输入框使用同一份 Manifest 提供补全，而不是独立硬编码变量表。例如输入：

```text
shell echo ${
```

可以从命名空间候选继续输入 `${rch:`、`${env:` 或 `${path:`；继续输入 `${rch:p`，可匹配 `pid`、`platform` 等名称。环境变量补全会从 `env` 项目的 `candidates` 中寻找名称。

补全基于**握手时上报的名称快照**，实际变量则在**命令执行时**解析。因此如果 Client 的环境变量在连接建立后改变，候选列表与当前实际可解析的值可能不同。变量补全仅帮助输入，不保证命令执行时路径存在、环境变量仍被设置，或目标权限足够。

## Script 运行上下文中的变量

普通命令会自动插值，但 Python Script 代码文本及结构化 `acmd` 参数不走普通命令的自动变量展开链。需要在 Script 中读取变量时，应显式使用 `variables` SDK。

### SDK 读取及字符串展开

`variables.get()` 接收 `namespace:name`，不需要 `${}` 外壳：

```python
from client.runtime.sdk import variables

client_id = variables.get("rch:client_id")
command_id = variables.get("rch:command_id")
home = variables.get("path:home")

print(client_id, command_id, home)
```

它适合直接取得某一个变量。若要在一段字符串内展开多个占位符，则使用 `variables.expand()`：

```python
from client.runtime.sdk import variables

message = variables.expand(
    "Client ${rch:client_id} running on ${rch:hostname}"
)
print(message)
```

两种接口共用普通命令的名称解析、错误处理和取值语义。`get()` 传入不带命名空间的 `pid`、未知变量，或 `expand()` 中出现不支持的命名空间，都会出现相应异常。

**脚本中必须显式导入：** 当前 Script 的自动全局注入不包含 `variables` 名称。直接写 `variables.get("rch:pid")` 而不导入，会出现 `NameError`。使用上面的 `from client.runtime.sdk import variables` 即可，不需要修改脚本全局配置。

### 主进程与子进程的上下文

Script 可使用进程内或 `subprocess_pipe` Python 执行方式。两者都能通过 SDK 读取 Client 变量，但 Subprocess 中的 Python PID、可执行文件及启动命令本来可能与主 Client 不同。

为了保留主 Client 身份，在创建 Subprocess 执行环境时，会预先传递六项主 Client 变量值：

| 预先传递的变量 | 原因 |
|---|---|
| `exec_path`、`launch_command`、`runtime` | 保留主 Client 的程序与运行位置 |
| `pid` | 避免误把临时 Python 子进程 PID 当作 Client PID |
| `client_id`、`command_id` | 保留目标连接与当前执行上下文 |

所以在 Subprocess Script 中调用 `variables.get("rch:pid")`，按设计应得到主 Client PID，而不是子进程自身的 `os.getpid()`。其余没有预先覆盖的变量仍通过适用的运行环境与 SDK 规则解析。

需要留意：SDK 变量值是供脚本使用的**字符串结果**，并不会自动让脚本中的任意普通 Python 字符串进行插值。例如 `print("${rch:pid}")` 只会打印字面文本，除非显式调用 `variables.expand()`。

## 变量值、转义及身份边界

| 现象 | 可能原因与处理方式 |
|---|---|
| `${pid}` 没有展开 | 缺少命名空间，改用 `${rch:pid}` |
| 提示 `Unknown rch variable` | 变量名不在当前 RCH 内置清单中；检查拼写 |
| 提示环境变量未设置 | 目标 Client 进程中不存在该环境变量；不能用 Server 环境代替 |
| 提示 `Unsupported variable namespace` | 占位符用了 `rch`、`env`、`path` 之外的命名空间 |
| 路径存在空格，命令却报参数错误 | 展开不等于 Shell 安全转义；按目标 Shell 的语法正确引用 |
| 变量值与 Server 的 PID、用户或目录不同 | 变量在目标 Client 上解析，属于不同进程和机器 |
| Variables 标签看不到实时值 | 该页面展示的是连接握手上传的变量定义，并非实时变量查询 |
| Environment 自动补全缺少新变量 | 候选名来自握手快照；最终取值发生在执行时 |
| Script 中使用 `variables` 提示 `NameError` | 添加 `from client.runtime.sdk import variables` 显式导入 |
| Subprocess Script 的 `rch:pid` 不等于 `os.getpid()` | 前者表示主 Client，后者是当前 Python 子进程 |

RCH Variables 不是可持久化管理的自定义变量库。它目前提供 23 个 RCH 运行时变量、4 个 Path 快捷变量和动态读取的 Environment 命名空间；Web 端负责展示与补全，不提供变量编辑功能。

使用环境变量时尤其应注意敏感信息和命令构造：读取 `${env:NAME}` 不等于安全输出，变量值中的空格、引号、换行或 Shell 特殊字符都可能改变命令行为。对于需要精确控制参数边界的脚本，优先使用 Python 的结构化参数和 SDK 返回值处理，而不是把未知内容直接拼接进 Shell 命令。
