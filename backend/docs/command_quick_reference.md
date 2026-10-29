# RCH 命令速查表

本文面向 **Web Terminal / Server 命令入口**，按命令的实际执行位置和 Client 平台整理常用命令。命令名称采用当前注册的正式名称；表格提供用途与适用范围，完整参数见各命令文档或 `help`。

> **先选目标 Client。** 浏览器输入的普通远程命令由所选 Client 执行。Server Builtin 则先由 Server 识别并处理，部分 Builtin 再对选中的 Client 发起操作。当前设备支持的 Client 命令以 `help client`、`acmd help` 和 Info → Commands 为准；执行远程操作前选择在线 Client。

## 1. 先分清命令入口

| 类型 | 典型写法 | 在哪里处理 | 主要区别 |
|---|---|---|---|
| **Server Builtin** | `alias list`、`script list`、`job ps` | Server 先处理，再按需要访问 Client | 用于服务端目录、别名、历史、任务与连接控制；同名时优先于 Client 普通命令 |
| **Client 普通内置命令** | `pwd`、`set`、`clean` | 目标 Client | 已导出的 RCH 操作；通常接收一段原始参数文本 |
| **Client Shell** | `shell <命令>`、系统可执行程序名称 | 目标 Client 的操作系统 | `shell` 明确启动系统子进程；未匹配 RCH 内置方法的普通输入也可能回退到系统 Shell |
| **ACMD** | `acmd ps --name python` | Server 解析入口、Client 校验并执行 | 使用独立注册表及结构化参数校验；**不会**在不支持时回退到系统 Shell |
| **Alias / Quick Actions** | 自定义别名名称 | Server 展开，Client 执行对应普通命令 | 命令模板的快捷入口；优先按目标平台选择对应定义 |
| **Script / Job** | `script exec …`、`job start …` | Server 管理入口；Client 运行 | 使用 Server 的 Script / Job 管理入口提交任务 |

日常查找：`help` 查看 Server 与当前 Client 的帮助汇总；`help server` 查看 Server Builtin；`help client` 查看目标 Client；`help alias`、`help job` 等查看某个 Builtin；`acmd help` / `acmd help ps` 查看当前 Client 的 ACMD 及参数。自动补全显示命令名称；实际执行还需要目标连接、平台支持与相应权限。

## 2. Server Builtin：先由 Server 识别

这些是 Server 注册的一级命令，不属于 Client 操作系统自带的 Shell 命令。

| 命令 | 作用 | 使用提示 |
|---|---|---|
| `help` | 查看 Server Builtin 与当前 Client 的命令说明 | `help server`、`help client` 或 `help <builtin>` 缩小范围 |
| `alias` | 查看、建立、删除适用于目标平台的快捷别名 | 默认列出当前生效的别名；定义保存在 Server 上 |
| `script` | 列出、查看及执行 Server Script Library 中的脚本 | 脚本由 Server 提供，再交给目标 Client 按 Python 策略执行 |
| `job` | 列出可用 Job，并启动、查询或停止目标 Client 的 Job | 启动响应确认 Job 已提交；最终结果查看 Job 状态 |
| `history` | 查看当前设备的 Quick History，并按序号重放或清理 Recent | Activity Center 的完整活动记录使用独立的 History 入口 |
| `gopin` | 查看或跳转到当前设备保存的远程路径 | 使用 Remote Files 保存的路径记录；需要关注当前目标设备 |
| `rtt` | 查看当前连接心跳的往返延迟 | 反映连接心跳 RTT，不等同于网络测速 |
| `upload` | 将 Server 端可用的文件上传到目标 Client | 文件来源是 **Server 文件系统** |
| `saveout` | 执行一个 Client 命令，并将其输出保存为 Artifact | 适合留存输出或下载结果，而不只是看终端文字 |
| `notify` | 执行一个 Client 命令，在完成时发送通知 | **不同于** `acmd notify` 的设备本地通知 |
| `xt` | 查询、定位和调用 External Tool | 由 Server 的 External Tool 目录解析后在目标 Client 侧使用 |
| `httpctl` | 通过 HTTP 控制通道管理当前 Agent | 含终止、重启、克隆等高影响操作，先确认目标 Client |

### 常用子命令

| 写法 | 作用 |
|---|---|
| `alias` / `alias list` | 显示针对当前 Client 平台已生效的 Alias；`--json` 返回结构化列表 |
| `alias set [--platform PLATFORM] name = command` | 创建或替换 Alias；默认作用域为 `common`，也可指定 `win`、`mac`、`linux`、`ios` |
| `alias unset [--platform PLATFORM] name` | 删除指定作用域的 Alias；不会自动删除其他平台同名定义 |
| `script list` | 查看 Server Script Library；可选 `--json` |
| `script view <path>` | 查看 Server 脚本内容 |
| `script exec <path> [options]` | 使用命令行选项执行 Server 脚本 |
| `script run <__json__:payload>` | 使用结构化负载执行脚本，主要供相应界面/流程使用 |
| `job list` | 查看 Server 已登记的 Job 定义；可选 `--json` |
| `job start <name> [--mode MODE] [--params JSON]` | 在目标 Client 启动 Job，并可指定运行模式和参数 |
| `job ps` / `job status <name>` | 查看正在运行的 Job / 单个 Job 状态 |
| `job stop <name>` / `job stop-all` | 停止指定 Job / 所有正在运行的 Job |
| `history` / `history list` | 查看 Quick History 的 Recent 列表 |
| `history run <index>` | 按 Quick History 序号重放命令，**可能再次执行原来的危险操作** |
| `history clear` | 清理当前设备 Quick Recent，保留 Activity Center 及 Pin |
| `xt list` / `xt info <name>` | 查看 External Tool 列表 / 具体工具信息 |
| `xt which <name>` | 查找工具可执行文件 |
| `xt run <name> [--] [args]` | 执行 External Tool；`xt <name> ...` 也是直接执行入口 |
| `httpctl help` | 显示 HTTP 控制通道支持的操作 |
| `httpctl kill` / `httpctl relaunch` / `httpctl clone` | 终止、重新启动或克隆当前 Agent，属于高风险管理操作 |

Alias 的模板参数、平台覆盖与安全边界见 [Aliases / Quick Actions](alias_quick_actions.md)；Script 的参数与授权见 [Scripts](scripts.md)；Job 运行状态见 [Background Jobs](background_jobs.md)；External Tool 见 [External Tools](external_tools.md)。

## 3. Client 通用命令：Windows / macOS / Linux / iOS 共享注册

下列名称来自当前 Client 公共命令集合。**共享注册不表示底层系统能力完全一致**：涉及子进程、权限、设备自动化或文件访问的命令仍受目标平台和运行环境限制，特别是 iOS / Pythonista。

### 终端、Python、当前目录

| 命令 | 作用 | 注意 |
|---|---|---|
| `help` | 显示 Client 支持的命令 | 从 Server Terminal 查阅时优先使用 `help client`，以免与 Server Builtin `help` 混淆 |
| `pwd` | 显示 Client 当前工作目录 | 返回目标 Client 的工作目录 |
| `cd <path>` | 修改 Client **进程本身**的工作目录 | 会影响后续相对路径命令；不同于临时 Shell 内的 `cd` |
| `var NAME=VALUE` | 设置当前 Client 连接的变量，可由 `${var:NAME}` 引用 | `var` 列出变量；`var --unset NAME` 删除；与进程环境 `${env:*}` 分开 |
| `shell <command>` | 启动系统 Shell 子进程，等待完成后收集输出 | 适合短任务；非零退出码通常返回失败 |
| `shell_stream <command>` | 启动 Shell 子进程，边运行边发送标准输出/错误 | 适合观察日志或持续输出；交互式终端使用 PTY |
| `bgrun <command>` | 在后台启动程序并尽快返回 PID | 不等待最终结果，也不持续收集输出 |
| `pyexec <code>` | 在 Client Python 环境执行代码并汇总输出 | 执行模式依赖 Python Runtime 配置 |
| `pyexec_stream <code>` | 执行 Python 代码并推送中间输出 | 按当前 Python 执行模式流式输出 |
| `piplist` | 列出当前 Client Python 环境中的第三方包 | 查询**目标 Client**的解释器环境 |

**`shell`、`shell_stream`、`bgrun` 依赖目标平台可创建系统子进程。** 在普通 iOS / Pythonista 中，这类操作通常受限；`pyexec`、进程内 Script 和进程内 Job 使用 Python 执行路径，按其自身依赖与权限运行。详见 [iOS / Pythonista](ios_pythonista.md) 与 [Shell-like Commands](shell_like_commands.md)。

### 系统信息、网络和运行环境

| 命令 | 作用 | 注意 |
|---|---|---|
| `getuid` | 查看 Client 当前用户身份 | 依目标系统提供的身份信息展示 |
| `getpid` | 查看 Client 自身进程 PID | 返回目标 Client 进程 PID |
| `uptime` | 查看系统运行时间 | 返回目标设备信息 |
| `userenum` | 枚举系统用户账户 | 可见范围受目标系统权限约束 |
| `is_elevated` | 检查 Client 是否具有提升的系统权限 | 只检查当前进程权限，不自动提权 |
| `ifconfig` | 查看目标设备网络接口 | 输出格式由 RCH 的平台信息提供者决定 |
| `set` | 查看及修改 Client Runtime Config | 无参查看可暴露设置；`set --all` 查看更完整列表 |
| `set KEY value` | 设置允许覆盖的 Runtime Config 项 | 可能影响客户端运行行为，修改前确认范围 |
| `set --reset KEY` / `set --reset-all` | 还原一项 / 全部运行时覆盖值 | `--reset-all` 影响所有已保存的覆盖设置 |
| `watchdog` | 查看 Client Watchdog 的当前状态 | 用于判断 Local Heartbeat Watchdog / Remote Control Watchdog / Process Recovery Watchdog 配置与运行状态 |

### 文件、传输、清理和更新

| 命令 | 作用 | 注意 |
|---|---|---|
| `download <path>` | 从目标 Client 把一个文件上传给 Server，以便下载/领取 | 方向与 Server 的 `upload` **相反** |
| `zip_dir <directory>` | 在 Client 上把目录打包为 ZIP | 生成的压缩文件位于 Client 侧 |
| `unzip <archive>` | 在 Client 当前工作目录解压 ZIP | 应先确认归档来源、内容和目标目录 |
| `clean` | 扫描 Client 可清理项目，显示带类别选择的确认预览 | 默认预览时可能已勾选候选项；确认才执行删除 |
| `clean --no-confirm` | 跳过交互、直接执行受规则允许的清理范围 | **会真实删除匹配数据**，执行前需确认清理范围 |
| `update` | 构建、下载并准备新的 Client Bundle | iOS 更新交接与桌面自动启动方式不同 |

Web Remote Files 还会使用 `browse_dir`、`preview_path`、`download_paths`、`delete_path`、`rename_path`、`paste_paths` 等内部可导出命令。它们接受 Web 提交的专用负载，**这些入口由 Web 的 Remote Files 操作发送结构化负载**；对应交互使用 [Remote Files](remote_files.md)。`receive_file` 也是 Server → Client HTTP 传输的内部承载入口，而不是供用户直接填写普通路径的上传命令。清理的具体范围见 [Cleanup](cleanup.md)。

### 进程、会话和设备控制

| 命令 | 作用 | 注意 |
|---|---|---|
| `kill_instance` | 结束当前 Client 会话 / 实例 | 会使当前连接断开 |
| `relaunch_instance` | 重新启动 Client 并尝试重新连接 | 依赖平台可以实际创建/交接新进程 |
| `reexec_instance` | 用当前程序替换进程并重启 | 属于影响连接的管理操作 |
| `spawn_instance` | 启动额外的 Client 实例 | 可能形成多个连接及多实例资源占用 |
| `keyboard_send` | 向目标设备发送模拟键盘输入 | 依赖系统自动化权限及活动桌面会话 |

`list_processes`、`get_process_detail`、`list_apps`、`kill_process` 等属于供 Process UI 使用的隐藏建议入口，不一定出现在普通命令推荐列表。终端中需要**按条件查看或终止进程**时，优先使用下文 `acmd ps` / `acmd kill`，其中 `acmd kill` 提供目标选择和执行前预览。强制结束进程前应先确认设备、PID 及操作影响。

### External Tool 的 Client 侧入口

Server 的 `xt ...` 是面向用户的统一目录与运行入口；Client 另外导出 `external_tool_*` 操作，主要用于工具安装、预览、启动、停止与状态管理。这些命令在 Manifest 中标记为**不主动推荐**，通常由 External Tools 界面或 Server 工作流调用。

| Client 操作名称 | 作用 |
|---|---|
| `external_tool_install` / `external_tool_uninstall` | 安装 / 卸载 External Tool 包（卸载需满足实例状态条件） |
| `external_tool_start` / `external_tool_stop` | 启动 / 停止一个工具实例 |
| `external_tool_run` / `external_tool_oneshot` | 安装并运行 / 一次性运行工具模块 |
| `external_tool_status` / `external_tool_list_instances` | 查询实例状态 / 列出实例 |
| `external_tool_preview` / `external_tool_resolve_launcher` | 预览启动命令 / 解析启动程序 |
| `external_tool_which` / `external_tool_exec` | 定位安装后的程序 / 执行对应程序 |
| `external_tool_remove` / `external_tool_clear_logs` / `external_tool_clear_cache` | 清除停止实例的运行数据、日志或工具包缓存 |

详细的参数、实例生命周期和风险见 [External Tools](external_tools.md)，按 External Tools 预设、安装状态与工具实例参数调用。

## 4. 平台专属的普通 Client 命令

共享命令之外，以下方法由目标操作系统的 Client 另外导出；平台专属命令只在其导出平台作为 RCH 内置操作生效。其他平台输入同名文本时可能走操作系统 Shell 回退，具体结果取决于目标系统。

### Windows

| 命令 | 作用 |
|---|---|
| `getinfo` | 采集 Windows 系统信息 |
| `screenshot` | 截屏并上传结果 |
| `idletime` | 查看用户空闲时间 |
| `run <command>` | 启动程序而不等待完成；不等于收集输出的 `shell` |
| `run_elevated <command>` | 请求以管理员权限执行命令，可能弹出 UAC 授权 |
| `spawn_elevated_instance` | 请求以提升权限启动新 Client 实例，可能弹出 UAC |

### macOS

| 命令 | 作用 |
|---|---|
| `getinfo` | 采集 macOS 系统信息 |
| `screenshot` | 截屏并上传结果 |
| `webcam_snap` | 使用摄像头拍照并上传结果，受摄像头权限限制 |
| `idletime` | 查看用户空闲时间 |
| `run_elevated <command>` | 请求以提升权限执行命令，可能弹出系统授权 |
| `spawn_elevated_instance [--detached]` | 请求启动提升权限的 Client 实例；macOS 使用 `--detached` 时新实例以独立后台 session 运行 |
| `file_shred <path>` | 对文件执行覆盖式删除，属于不可逆高风险操作；闪存等设备不保证物理不可恢复 |

### Linux

Linux 平台额外提供 `getinfo [--json]`，采集发行版、内核、主机、CPU、内存、GPU、网络、Python、Shell、桌面、用户及当前 Client 进程信息。输出为平铺字段，使用 `distro`、`pid`、`ppid`、`has_desktop`、`resolution` 等简明字段名；需要区分含义时使用 `cpu_model`、`memory_total_gb`、`python_version` 等限定名称。默认文本列表，`--json` 输出扁平 JSON。其余如 `pwd`、`shell`、`set`、`clean` 仍按公共 Client 命令执行。

### iOS / Pythonista

iOS 的 RCH Client 专门实现了一组可在 Pythonista 中通过 Python / iOS API 完成的操作，用来替代部分桌面 Shell 用途。

| 命令 | 作用 |
|---|---|
| `ls` / `cat` | 列出目录 / 读取文本文件 |
| `touch` | 创建空文件 |
| `echo` / `printenv` | 输出文本或环境变量 / 查看环境变量 |
| `whoami` / `getinfo` / `uptime` | 查看当前身份 / iOS 设备信息 / 系统运行时间 |
| `md5sum` | 计算文件 MD5（用于文件比对，不适合作为安全校验） |
| `clipboard_read` / `clipboard_write` | 读取 / 写入文本剪贴板 |
| `openurl` / `open_in` | 打开 URL / 将文件交给其他 App |
| `quick_look` / `pick_upload` | 预览文件 / 选取照片或文件并上传 |
| `get_location` / `list_contacts` | 读取获授权的定位 / 联系人信息 |
| `speak` | 使用设备语音合成朗读文本 |
| `keep_awake` | 请求保持屏幕唤醒；不保证 App 长期后台运行 |
| `clear_console` | 清理 Pythonista 控制台输出 |
| `kill_app` | 请求结束当前 App / Client；会中断连接 |

这些是 **RCH 在 iOS 上的内置命令**，通过 Python 与受授权的平台接口执行。iOS 不注册 `acmd ps` / `acmd kill`，也不提供系统 Shell、后台子进程、用户枚举、提权检查和软件包枚举命令。部分操作需要设备端用户授权或在前台使用。详情见 [iOS / Pythonista](ios_pythonista.md)。

## 5. ACMD：有参数定义的 Client 命令

ACMD 统一使用 `acmd <name> ...` 前缀，使用独立的命令注册表、参数类型转换和错误提示。它按独立的注册表校验参数；支持的名称与用法通过 `acmd help` 查看。

可使用 `--key value`、`--key=value`、特定命令声明的短别名、Flag 或位置参数。**选项并非全局通用**：例如 `--json`、`--pid`、`--name`、`--no-confirm` 只有相应命令确实声明时才生效。

| 平台 | 当前已注册的 ACMD | 作用概述 |
|---|---|---|
| **Windows / macOS / Linux** | `acmd ps` | 按 PID、名称、端口查看进程，部分形式支持 JSON 结果 |
| **Windows / macOS / Linux** | `acmd netstat` | 查看 TCP / UDP 连接，可按端口、监听状态和协议筛选 |
| **Windows / macOS / Linux** | `acmd kill` | 按 PID、名称或端口选择并终止进程；可先显示预览和确认，具体能力受权限限制 |
| **macOS** | `acmd msgbox` / `acmd notify` | 显示本机提示框 / 发送本地通知 |
| **macOS** | `acmd launchd` | 管理 LaunchAgent / LaunchDaemon；未填 action/kind 时交互选择，执行前预览审批；支持 `--json` 结构化结果与 `--no-confirm` 直接执行；详见 [launchd](launchd.md) |
| **macOS** | `acmd sqlite_query` | 对指定 SQLite 数据库做只读查询 |
| **macOS** | `acmd image_info` | 查询图片文件信息 |
| **macOS** | `acmd import_check` | 检查当前 Python 解释器是否能导入指定模块 |
| **macOS** | `acmd archive_peek` | 查看压缩包内容，不直接解压 |
| **iOS** | `acmd alert` / `acmd notify` | 显示 Pythonista 提示 / 发出本地通知 |
| **iOS** | `acmd find` / `acmd tree` | 按关键字查找文件或展示目录树 |
| **iOS** | `acmd head` / `acmd tail` | 阅读文本文件开头 / 末尾若干行 |
| **iOS** | `acmd wget` | 从 URL 下载文件 |
| **iOS** | `acmd tcp_ping` / `acmd ping` | 测量 TCP 连接或 ICMP 请求延迟；是否可用受系统网络权限影响 |

示例（只展示语法，不表示允许随意操作目标设备）：

```text
acmd help
acmd help ps
acmd ps --name python --json
acmd ps --pid ${rch:pid} --json
acmd netstat --port 443
acmd netstat --status LISTENING
acmd netstat -l -t --port 443 --json
acmd netstat -u
acmd kill --pid 1234
acmd tree . --max_depth 2
```

- `acmd ps`：查看进程；终止操作是 **`acmd kill`**，进程结束操作需显式调用 `acmd kill`。
- `acmd kill`：指定目标后仍应核对预览；`--no-confirm` 会跳过交互确认，只在明确知道对象和影响时使用。
- `acmd notify`：作用于 **macOS/iOS Client 本地通知**；Server Builtin `notify <command>` 则是**运行远程命令后发送完成通知**，不能混为一谈。
- 平台间同名 `acmd` 不保证完全相同的选项或系统能力，应以 `acmd help <name>` 为准。

ACMD 的参数解析规则、输出与交互风险见 [ACMD](acmd.md)；进程信息和结构化输出见 [Structured Output](structured_output.md)。

## 6. 实用选择与常见误区

| 你想做什么 | 优先用什么 | 为什么 |
|---|---|---|
| 快速确定当前 Client 支持哪些功能 | `help client`、`acmd help` | 比照搬另一台设备的命令清单可靠 |
| 在 Client 上运行短 Shell 命令 | `shell …` | 明确交给目标系统 Shell 并收集最终结果 |
| 运行持续输出的命令 | `shell_stream …` | 可看到中间输出；如需交互式会话则应使用独立 PTY 功能 |
| 执行 Python 逻辑 | `pyexec …`、`script exec …` | 前者适合直接代码；后者复用 Server Script Library |
| 查进程、按条件结束进程 | `acmd ps`、`acmd kill` | 有明确参数、预览和平台约束 |
| 管理已有 Python Job | `job …` | Job 目录和控制在 Server Builtin 中统一管理 |
| 上传、领取文件 | Server `upload`、Client `download` | 文件来源和目标由 Server 与所选 Client 决定 |
| 操作文件夹和批量文件 | Remote Files UI | 比手工构造 Web 专用命令负载更合适 |
| 调整 Client 运行时设置 | `set` | 直接针对目标 Client 的 Runtime Config |
| 清理临时残留 | `clean` | 先看预览，不将 `--no-confirm` 当成模拟 |
| 运行外部工具 | `xt …` | Server 端统一目录与运行入口 |

**命令是否成功取决于目标 Client 的真实状态。** RCH 可能先由 Server 处理输入，再经网络转发；有些 Client 命令执行后会改变工作目录、进程或磁盘文件；Shell 回退不能提供 RCH 专用命令的所有确认与结构化参数保障。遇到命令异常时，先确认目标设备、执行类别（Server / Client / ACMD / Shell）、平台和权限，再核对该入口自己的帮助。

进一步阅读：[Command Registry](command_registry.md) · [Command Execution](command_execution.md) · [Shell-like Commands](shell_like_commands.md) · [ACMD](acmd.md) · [Autocomplete](autocomplete.md)。
