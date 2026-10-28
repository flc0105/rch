# iOS / Pythonista 运行环境与 Client 支持

RCH 可以把运行在 iPhone 或 iPad 的 Pythonista 作为 **Client 执行环境**：由 Pythonista 启动 Python Client，通过网络连接 RCH Server，再使用远程命令、Python Script 和 Background Job 等功能。本篇介绍 Pythonista 的运行环境、RCH 在 iOS 上的执行路径、所需依赖、系统权限与任务生命周期。首次安装步骤见 [Client Bootstrap](bootstrap.md)，在线更新见 [Client Update](client_update.md)。

> **使用定位：**RCH Client 在 Pythonista 的 Python 解释器中运行，通过网络与 Server 通信，并调用标准库、已安装的第三方模块及获授权的 iOS 接口执行任务。具体能力由执行方式、应用沙盒和 iOS 生命周期共同决定。

## Pythonista 提供的 Python 环境

Pythonista 是在 iOS / iPadOS App 内嵌入 Python 解释器的开发与运行环境，不要求设备安装系统级 Python。官方文档与 App Store 页面目前介绍的是 **Python 3.10**；实际环境以设备上安装的 Pythonista 版本为准。它提供编辑器、交互控制台、调试工具、离线文档、iOS 集成模块和若干预装的第三方库。

### 标准库与普通 Python 逻辑

Pythonista 支持**大部分 Python 标准库**。常规的字符串与数据处理、JSON、时间日期、路径与文件读写、归档、哈希、网络请求、Socket 通信，以及不少线程和同步机制都可以在应用允许的条件下运行。这正是 RCH 能在 iOS 上执行大量 Python 逻辑的基础。

iOS 对部分标准库能力有明确的系统约束：

- **子进程创建受限。**`subprocess`、`multiprocessing` 模块可能可以导入，但 Pythonista 官方说明实际创建子进程会受到 iOS 沙盒限制，常见结果是 `PermissionError`。需要系统进程的执行路径应使用支持该能力的平台。
- **交互控制台。**Pythonista 的控制台用于输入 Python 和查看输出，缺少完整的系统终端模拟；`readline`、`curses` 的支持受限，`tkinter` 不受支持。需要操作系统 Shell 或 PTY 的任务应在支持的 Client 平台运行。
- **应用沙盒文件系统。**标准库可以读写 Pythonista 沙盒内有权限的文件；访问文件选择器、iCloud 或 iOS API 提供的资源时，遵循对应的系统授权。其他 App 的私有目录受沙盒隔离。
- **设备接口和权限。**Pythonista 通过 iOS API 访问受授权的设备功能。进程管理、系统管理及原生程序启动能力由 iOS 沙盒限制，具体功能应采用对应的 iOS 接口。

RCH 的 iOS 路径使用 Python API 和平台专用实现，适合标准库计算、网络通信、沙盒文件处理及已授权的设备操作。

### 第三方包与 iOS 原生能力

Pythonista 自带部分常用第三方包，例如 `requests`、Pillow、NumPy 等，也提供 `clipboard`、`photos`、`contacts`、`location`、`ui` 和 `objc_util` 等 iOS 集成模块。它们**不属于 Python 标准库**，而是 Pythonista 随 App 提供的运行环境能力。能否导入及实际使用，还取决于设备上的版本、系统权限及调用场景。

额外依赖按 Pythonista 的打包条件安装：纯 Python 且不依赖缺失的本地扩展的包，可以通过复制模块文件加入脚本目录或 Pythonista 的模块目录；涉及额外 C/C++ 编译扩展的包，一般无法在普通 Pythonista 环境中直接安装。RCH 的设计应让与某个平台无关的第三方依赖**尽可能按功能加载**，并在调用缺少依赖的功能时给出明确错误，保持其他功能可用。

**依赖检查分两段进行：**Bootstrap 使用当前 Python 环境中的标准库完成构建请求、下载与安装；启动 Client 时还需满足 Bundle 所调用模块的依赖。遇到导入错误时，应检查报错指向的 Client 模块和 Pythonista 的已安装包。

## RCH 在 iOS 上的工作方式

RCH 为 iOS 选择独立的平台能力实现，但保留 Server / Client 的统一连接、请求与结果传输机制。iOS 上的功能可理解为三层：

**第一层是跨平台的 RCH 协议和 Python 业务逻辑。**Client 连接 Server 后，命令下发、结果回传、部分文件传输、进程内 Script 执行和 Job 状态上报可以通过 Python 代码及网络协议完成。网络可达、运行时依赖齐全且文件访问已获授权时，这些能力可以正常使用。

**第二层是 Pythonista 提供的 iOS 平台接口。**RCH 能通过 Pythonista 暴露的接口访问获得权限的数据或设备能力，例如文本/图片剪贴板、文件选择、照片及部分设备信息。调用照片、联系人、文件选择等资源时，按 iOS 提示完成必要授权或界面交互。

**第三层是平台执行边界。**依赖独立进程、本机 Shell、外部二进制、其他 App 私有目录或长期后台常驻的操作受 iOS 限制；这类任务需选择支持其系统能力的目标平台。

### Command、Script 和 Job 的实际边界

在 iOS 实机使用反馈中，RCH 的 **Command、Job、Script 已有大量可正常运行的场景**。这些能力分别沿着以下执行路径工作：

- **Command** 可以分派到 RCH 内置的跨平台或 iOS 专用操作，它们可以直接调用 Python 库、Socket 或 iOS API；但未匹配到内置操作后若转成系统 Shell 执行，就会碰到 iOS 的进程限制。Web Terminal 会按命令路由选择实际执行路径。
- **Python Script** 可以在当前解释器内运行，使用标准库和已有第三方包处理数据、文件及网络。若脚本自身再要求运行系统可执行文件，仍会受 iOS 限制；执行模式切换到“子进程”不会解除该限制。
- **Background Job** 有基于线程的进程内运行路径，能够执行不依赖新进程的任务，并上报状态和输出。另一类需要独立子进程的运行方式不适用于普通 Pythonista。进程内任务的停止通常要依靠协作机制，不能指望像桌面子进程一样强制终止，同时其生命周期仍受宿主 App 控制。

运行具体任务前，按所选执行模式核对依赖、权限、内存、网络和预期运行时长。Script / Job 的通用约定分别参见 [Scripts](scripts.md)、[Background Jobs](background_jobs.md) 和 [Command Execution](command_execution.md)。

### 平台功能边界

RCH 的浏览器终端按 Client 平台分派命令。iOS Client **不支持交互式 PTY 会话**；普通 RCH Command 和进程内 Python Script 沿各自的 Python 执行路径运行。

Pythonista 提供文本、图片剪贴板接口，实际能力由模块和系统授权决定；RCH 的 **iOS 文件剪贴板暂不支持**。文件读写可使用沙盒路径，文件传输使用 RCH 通道，系统文件选择器负责获得其他授权位置的文件，参见 [Clipboard](clipboard.md) 与 [File Transfer](file_transfer.md)。

屏幕、进程监测、系统级自恢复和外部程序运行等功能具有更强的平台依赖。它们可能要求 iOS 不提供的系统 API、进程权限、持久后台执行或原生可执行文件；应按当前设备实际返回的能力和错误判断，不宜照搬桌面端的功能预期。参见 [Device Monitor](device_monitor.md)、[Process Watchdog](process_watchdog.md)。

在 iOS / Pythonista 上，有效 `feature_manifest.watchdog=false`；Client 不加载 Watchdog 实现。`set` 中三个 Watchdog 开关的值可以保留，运行时不会启用相应监督进程。Web Watchdog 面板保留 HTTP Control 三个操作入口并显示功能不可用的原因。

## 沙盒存储、网络与系统权限

**Client 的本地目录属于运行它的 Pythonista App 沙盒。**iOS 首次安装的 Source Bundle 按项目布局存放在 Pythonista 可写的 `~/Documents/client_bundle/` 下，下载缓存与已解压的 Release 分开组织。运行时配置、日志和临时文件分别按其保留规则管理。详细路径及更新交接见 [Client Update](client_update.md)，日志见 [Logging](logging.md)。

iOS 的 Files / iCloud 集成、分享菜单与文件选择器可以让 RCH 处理用户授权访问的文件；其他 App 的私有数据仍由系统沙盒保护。照片、联系人、定位等访问需要对应系统能力及用户授权；遇到访问被拒绝时，先确认相应的系统授权及资源路径。

Client 连接 Server 依赖实际网络连通性。除了 Web 端口用于构建和下载，Client 还需要连接配置指定的 Socket 服务；局域网地址、设备切换 Wi‑Fi / 蜂窝网络、应用网络权限或服务端网络策略变化，都可能使连接中断。部署时先检查 Bundle 下载和安装日志，再在 Server Connections 页面确认 Socket 握手与在线状态。

## 前台、后台与任务生命周期

RCH Client 的在线时长受 Pythonista 宿主 App 的前台与后台生命周期影响。

Pythonista 官方说明：App 切入后台后，脚本可能在约几十秒内被系统挂起，具体时长并不固定。Apple 对普通 iOS App 的后台执行也有明确限制。Pythonista 线程、Socket 连接、定时任务和 Job 都受此挂起机制影响。应用被挂起、系统回收或用户关闭时，Client 可能掉线，进行中的任务也可能停止或失去连接。重新进入前台后是否自动恢复，取决于 Pythonista 和 Client 当时的实际运行状态，不能保证所有任务继续执行。

Pythonista 与 Shortcuts、分享扩展的集成适合触发**有限时长、有限资源**的脚本；扩展环境有更严格的内存、时间和交互限制。持续连接需以 App 实际运行状态和 Server 在线状态为准。

## 部署、更新与运行诊断

在 iOS 上，推荐使用 [Client Bootstrap](bootstrap.md) 中的 **iOS 专用 Bootstrap 示例**：它利用当前 Pythonista 解释器请求 Source Bundle、下载与校验归档，再在同一 App 进程内启动 Client，不需要尝试寻找桌面 Python 可执行文件或创建子进程。

这种启动属于**进程内交接**：Bootstrap 的入口脚本可以执行完毕，但运行中的 Client 仍依赖 Pythonista 进程。后续更新与桌面平台也不同：iOS 下载并准备新的 Release 后，由用户在 Pythonista 中运行新入口，再通过 Server Connections 检查新实例是否上线。

当 iOS 上某类操作异常时，宜先判断失败属于哪一层：**网络与连接、Python 模块是否可用、沙盒及系统权限、是否依赖子进程、还是 App 进入后台后的暂停**。分别核对上述条件，再查看相应任务的报错和结果。记录 Pythonista 控制台错误、RCH Client 日志及 Server Connection 状态，能够帮助区分真正的功能缺陷与平台限制。

对于远程下发脚本和 Bundle，还应遵守正常的代码来源与网络信任边界。运行远程脚本前确认其来源和内容：Python 代码可访问沙盒内文件、已授权资源和网络，未经审查的代码可能泄露数据或造成文件变更。

## 参考资料

本篇对 Pythonista 平台能力的描述参考其官方文档和 Apple 平台说明；对 RCH 功能边界的描述依据本项目的 iOS Client、Command、Script、Job、PTY 和 Clipboard 实现。Command / Job / Script 的实际可用范围包含用户在 iOS 上的运行反馈；需要新环境验证时，以目标设备的命令结果、依赖和系统权限为准。

- [Pythonista 官方 FAQ：标准库、子进程、第三方模块与后台行为](https://omz-software.com/pythonista/docs-3.4/py3/ios/faq.html)
- [Pythonista 官方文档：内置模块与使用环境](https://www.omz-software.com/pythonista/docs-3.4/py3/contents.html)
- [Pythonista 3 — App Store 官方介绍](https://apps.apple.com/us/app/pythonista-3/id1085978097)
- [Apple：App 进入后台时的运行与挂起机制](https://developer.apple.com/documentation/uikit/preparing-your-ui-to-run-in-the-background)

