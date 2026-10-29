# Client Bootstrap 与首次部署

本篇统一介绍 One-liners、Python / PowerShell Bootstrap、Go Loader 和 iOS 上的首次部署。它们使用不同的引导入口，但目标都是从 Server 获取 Python Source Bundle，校验、安装 Release，再启动 RCH Client。**首次部署不同于 Client 在线后的自更新**；后续更新和版本交接参见 [Client Update](client_update.md)。

## 选择合适的启动方式

| 目标环境 | 推荐入口 | 运行特点 |
|---|---|---|
| macOS / Linux，已有 Python 3.10+ | One-liners → Python | 请求生成通用 Python Bootstrap，安装 Bundle，独立启动 Client |
| Windows | One-liners → PowerShell / Python | 可以按环境使用本地 Python 或支持的 Windows Embed 运行时 |
| Windows / macOS / Linux，需要预先分发一个执行文件 | Agent Builder → Go (Loader) | 先构建平台对应的 Loader，目标端再取得 Python Bundle |
| **iOS / Pythonista** | **[iOS 专用 Bootstrap 示例](examples/ios_bootstrap.py)** | 不启动子进程，使用当前解释器运行 Bundle 中的 Client |

首次部署在**目标设备本地**执行。设备通过 Server Web 端口构建并下载 Bundle，再通过配置的 Socket 端口连接；部署开始时目标 Client 尚可处于离线状态。

## 一、整体工作机制

整体分为准备部署入口和目标设备运行两个阶段：One-liners 准备脚本调用命令，Go Loader 由 Agent Builder 准备编译好的可执行文件；目标设备执行对应入口，再完成 Python Bundle 的安装启动。

```text
Banner → Utilities → One-liners
  └─ 填写 Server IP / Socket port / Web port
       └─ 替换模板变量、编辑或复制命令
            ↓ 在需要部署 Client 的设备上运行
目标设备的 Python / PowerShell
  └─ POST 请求 Server 获取动态 Bootstrap 脚本
       └─ Bootstrap 确认运行环境与连接参数
            └─ POST 请求 Bundle 构建、取得文件名与 SHA-256
                 └─ 下载 ZIP → 校验 → 暂存解压 → 安装 Release
                      └─ 启动独立 Client 进程 → Bootstrap 退出
```

Go Loader 的独立流程为 `Agent Builder → Go (Loader) 构建 → 下载可执行文件 → 目标设备运行 → 请求 Bundle → 校验安装 → 启动 Python Client`，它不经过动态生成的 Python/PowerShell Bootstrap 文本。

**One-liners 用于首次安装。**在目标设备的 Python 或 PowerShell 环境执行复制的启动命令，下载、安装并启动 Client；之后在 Server Connections 中确认该设备上线。

安装验证分为两步：确认 Bootstrap 已启动 Client，再到 Server Connections 核对 Socket 连接状态。若仍离线，检查地址、端口、网络与 Client 启动日志。

## 二、One-liners 工具栏与命令模板

从 Banner 右侧 **Utilities → One-liners** 打开对话框，可以选择 Python 或 Windows PowerShell 启动命令。

对话框上方提供以下设置：

| 设置 | 作用 | 默认来源 |
|---|---|---|
| Server IP | 目标设备访问 Server 的地址 | 当前浏览器页面的主机名 |
| Server port | 新 Client 连接 Server 的 Socket 端口 | Server 配置，无法读取时回退为 `9999` |
| Web port | 获取 Bootstrap、构建 Bundle 和下载文件使用的 HTTP 端口 | Server 配置，无法读取时回退为 `8085` |

打开对话框时，页面会请求 `GET /api/agent/platform` 读取 Server 当前配置的 Socket/Web 端口。用户可以手动修改这三个字段，用于跨网段、代理或端口映射场景。**Server IP 应填写目标设备实际能够访问的地址**，不必与浏览器当前地址相同。

模板只识别三个占位符：

```text
{{server_host}}
{{server_port}}
{{web_port}}
```

页面将占位符替换成输入框中的当前值，再展示可复制的完整命令。每个命令区域都可直接编辑；编辑完成并失去焦点后，页面保存该次打开期间的文本覆盖值。点击 **Copy** 复制当前显示内容，不会替用户在远程设备上执行。重新打开对话框会清除临时编辑，重新从内置模板和当前 Server 默认值生成命令。

若对某条命令做过直接编辑，后续再改顶部地址或端口，该条已经覆盖的命令文本不会自动按模板重新生成，需要检查并手动调整。编辑和复制不会永久修改内置模板。

One-liners 的内置条目是随前端发布的静态目录，并非 Server 动态下发的全部部署方式。因此条目增减不会影响 Bootstrap API 的职责。

## 三、启动命令与 Go Loader 的使用方式

**Python One-liner** 适合目标系统能运行 Python 的场景。以下示例把目标 Server 设置为 `192.0.2.10`，Socket 为 `9999`、Web 为 `8085`（示例地址需替换成实际可达地址）：

```bash
python3 -c "import requests; exec(requests.post('http://192.0.2.10:8085/api/agent/bootstrap', json={'server_host':'192.0.2.10','server_port':9999,'web_port':8085}).text)"
```

这条命令首先用 `requests` 向 Web 端口发送 JSON 请求，取得为该地址生成的 Python Bootstrap 文本，随后在本地 Python 解释器中执行。**运行这条 One-liner 的 Python 环境需要已安装 `requests`**；下载得到的 Bootstrap 主体使用 Python 标准库实现后续请求和安装。Bootstrap 会再寻找符合 Client 要求的 Python 运行环境。

Windows PowerShell 的 One-liner 则把脚本先保存为临时 `.ps1` 文件，再执行它。与 Python 版本一样，它以 Server IP / Socket / Web 三个值构造请求；示例形式如下：

```powershell
$ip="192.0.2.10";$sp=9999;$p=8085;
iwr "http://$($ip):$p/api/agent/bootstrap/ps1" -Method Post -ContentType "application/json" -UseBasicParsing -Body "{`"server_host`":`"$ip`",`"server_port`":$sp,`"web_port`":$p}" -OutFile "$env:TEMP\bootstrap.ps1";
& "$env:TEMP\bootstrap.ps1"
```

这里的 `iwr` 即 `Invoke-WebRequest`。它把动态生成的 PowerShell 脚本保存到当前用户的临时目录，然后使用调用运算符 `&` 执行。与仅复制文件不同，命令执行后会继续触发 Bundle 构建、下载、安装和 Client 启动。PowerShell 的执行策略、网络代理和主机安全策略都可能影响脚本执行。

这两条命令都包含**下载后直接执行代码**的行为。应只在确认 Server 身份及返回内容可信、且拥有目标设备管理权限的情况下使用。当前内置示例使用 `http://`，HTTP 不提供传输加密或服务器身份认证；在非可信网络中应采用受信任的安全网络接入方式，不应把 HTTP 的 Bundle SHA-256 校验当成独立的服务器身份校验。


### Go Loader：独立可执行程序启动

Go Loader 与 Python / PowerShell One-liner 的**部署目的相同，但交付入口不同**：前两者在目标设备运行一段从 Server 动态取得的 Bootstrap 脚本；Go Loader 则先由 Server 编译一个注入连接配置的 Go 可执行程序，再将这个可执行文件放到目标设备运行。**当前 One-liners 菜单只提供 Python 和 PowerShell 模板**；Go Loader 通过 Agent Builder 的 **Go (Loader)** 模式构建和下载，而不是假装工具栏还有一个现成的 Go 命令。

在 Agent Builder 选择 Go (Loader)，指定目标操作系统、架构、Server Socket 地址与端口、Web 地址与端口后发起构建。Server 使用 Go 工具链交叉编译目标程序（`CGO_ENABLED=0`），将这些连接参数编入 Loader；Go Loader 支持的构建系统为 `win`、`mac`、`linux`，架构为 `amd64`、`arm64`。目标设备无需安装 Go 编译器，但**最终启动的仍是 Python Client，因此需要可用的 Python 3.10+ 运行环境**。

如果通过 API 构建，下面是 Linux amd64 的示例（请把示例 Server 地址替换成真实可达地址）：

```bash
curl -fsS -X POST 'http://192.0.2.10:8085/api/agent/build' \
  -H 'Content-Type: application/json' \
  -d '{"builder":"go_loader","target_os":"linux","target_arch":"amd64","server_host":"192.0.2.10","server_port":9999,"web_port":8085}'
```

响应中的 `data.file_name` 是生成的 Loader 文件名，`data.download_url` 是下载地址。先把该构建结果下载到目标设备，再赋予执行权限并运行，例如：

```bash
chmod +x ./rchclient-go-loader-linux-amd64-<build-id>
./rchclient-go-loader-linux-amd64-<build-id>
```

`<build-id>` 是占位符，实际名称应以本次构建返回值为准。Windows 目标直接运行对应 `.exe`；macOS 目标使用相应系统架构的可执行文件。将 Loader 传到目标设备、确认来源可信再执行；不能从示例路径推断它已经存在于本机。下载接口使用 `/api/agent/download/{filename}`，不需要先执行 Python Bootstrap。

Loader 启动后会先报告设备 OS、架构、主机名和网络地址，再确定 Python 运行环境，然后主动请求 `builder: "bundle"` 的新 Bundle 构建、下载 ZIP、校验返回的 SHA-256、暂存解压到 Release，最后启动独立 Python Client 并退出 Loader。Loader 报告安装进度；完成后到 Server Connections 检查 Client 上线状态。

## 四、Bootstrap API 与构建请求

One-liners 请求 Server 生成对应平台的 Bootstrap 脚本，再由脚本构建和安装完整 Client Bundle。脚本生成接口如下：

| 方法 | API | 返回内容 |
|---|---|---|
| `POST` | `/api/agent/bootstrap` | 依据参数生成的 Python `bootstrap.py` |
| `POST` | `/api/agent/bootstrap/ps1` | 依据参数生成的 Windows `bootstrap.ps1` |

请求体示例：

```json
{
  "server_host": "192.0.2.10",
  "server_port": 9999,
  "web_port": 8085
}
```

`server_host` 是 Client 将来连接的 Server 地址，`server_port` 是 Socket 端口，`web_port` 是 Bootstrap 请求 API 和下载文件的 HTTP 端口。Python 生成入口还允许提供 `web_host` 和 `web_scheme`，默认分别沿用 `server_host` 与 `http`；当前工具栏模板只暴露前三项，PowerShell 生成路径使用 HTTP 和同一主机地址。

Server 会检查必要地址和端口，并要求 Web 端口处于 `1` 至 `65534` 的有效范围。生成的脚本先写到 Server 临时文件，再作为下载响应返回；正常响应关闭后会尝试清理该临时文件。实际安装和建立连接发生在目标设备执行返回的 Bootstrap 脚本之后。

真正执行 Bootstrap 后，脚本会请求：

```http
POST /api/agent/build
Content-Type: application/json
```

并在请求中指定 `builder: "bundle"`、`target_os: "bundle"`，以及 Server 地址、Socket/Web 端口和 `source: "bootstrap"` 等参数。Server 构建 Python Source Bundle 后，返回构建版本、产物文件名、下载地址及该 Bundle 的 SHA-256。Bootstrap 随后通过 `/api/agent/download/{filename}` 下载该 ZIP。

Go Loader 的首次构建同样使用 `POST /api/agent/build`，但请求 `builder: "go_loader"` 并提供目标 OS 和架构；目标设备运行 Loader 后，它会另行发送 `builder: "bundle"` 的构建请求。Go Loader 并不把它自己的二进制作为最终 Python Client，也不依赖目标设备安装 Go。

Bootstrap 的生成、Bundle 构建和产物下载接口当前允许匿名访问。因此它们必须部署在符合预期的网络和访问控制边界内；不要把“Web 管理界面需要登录”误认为这些启动接口自动受同一登录流程保护。Bundle 构建仍依赖 Server 已注册并可用的 Bundle Builder。

## 五、运行环境、下载校验与安装

### Python 选择及平台差异

Client 需要 **Python 3.10 或更新版本**。Bootstrap 和 Go Loader 会验证候选解释器的 Python 版本后使用符合要求的环境。

- **macOS / 其他非 Windows 的 Python Bootstrap：** 优先检查当前解释器，再检查本地 `python3` / `python`；没有符合要求的解释器则报错，不会自动下载 Windows Embed。macOS 使用本地 Python。
- **Windows Python Bootstrap：** 优先检查以前缓存的 Python Embed，再寻找合适的本地 Python；两者都不可用时，尝试下载适配当前平台的 Python Embed。
- **Windows PowerShell Bootstrap：** 采用相似顺序，先尝试缓存 Embed、再尝试本地 Python，最后按系统条件尝试下载 Embed。

**Go Loader 的 Python 选择：** Windows 优先尝试已缓存的 Embed，再寻找本机 Python；没有合适解释器时才尝试下载 Windows amd64 Embed。非 Windows 的 Go Loader 仅查找本地 `python3` / `python`，缺失则报告错误并结束，不自动获取其他系统的 Python 运行时。

当前提供的 Python Embed 包面向 Windows amd64（Python 3.13.13）；回退下载要求 Windows 8.1 或更新版本，其他 Windows 架构或过旧系统在缺少可用 Python 时不能依靠这条路径自动安装。**iOS / Pythonista 的通用 Python Bootstrap 会直接检查当前解释器，不会为选择 Python 启动子进程**；安装的 Bundle 放在 Pythonista 可写的 `Documents/client_bundle` 中。下文仍提供独立 iOS 示例，便于控制安装过程，并在使用前自行检查环境依赖。

### Bundle 下载与目录组织

桌面版 Bootstrap 和 Go Loader 通常在当前目标用户 Home 下组织运行时、下载文件和版本目录；iOS 专用目录在下文单独说明：

```text
~/client_bundle/
├── runtimes/
│   └── python-embed/
├── downloads/
│   └── <bundle-file>.zip
└── releases/
    └── <build_version>/
        └── rchclient.py
```

Windows 对应当前用户配置文件目录。`build_version` 来自 Server 构建结果；Bundle 的 ZIP 文件名与版本目录名称按照构建产物约定对应。运行时和 Bundle 下载分别放置，避免把安装版本目录用作下载缓存。

Go Loader 在获取 Bundle 元数据时同样要求本次返回 `sha256`、`build_version` 和文件名，校验下载归档的 SHA-256，拒绝不安全的文件名、路径穿越以及 ZIP 内的符号链接，解压到 `.part` 目录后验证 `rchclient.py` 存在，再替换对应 Release。Go Loader 的实现也会在安装前移除同名旧 Release；不能把它理解成原地增量覆盖。

Bootstrap 下载 Bundle 时按块计算 SHA-256，并与**本次构建响应中提供**的期望摘要比较；不匹配则拒绝继续安装。脚本还检查版本名与文件名，拒绝明显异常的路径段；解压到 `.part` 暂存目录之前会检查 ZIP 完整性和不安全的归档路径。

通过验证后，Bootstrap 才将暂存目录移动为对应的 `releases/<build_version>/`。如果这个版本目录已经存在，当前安装流程会**替换该同名 Release 目录**；其他版本目录不会因为这次安装被全部清空。这是文件替换行为，不是已经运行的旧 Client 自动退出的证明。

若下载失败、摘要不一致、解压失败或缺少 `rchclient.py`，流程会报错并停止后续启动。下载目录中的 ZIP 和缓存的 Python Embed 与 Release 的生命周期不同，不要误认为 Bootstrap 完成后会立即清空全部下载缓存。

### Client 启动与 Bootstrap 退出

安装完成后，Bootstrap 使用选定 Python 运行 `rchclient.py`，并将工作目录设为安装好的 Release。Windows 通过隐藏窗口的独立进程启动，Unix 类系统使用新的进程会话；脚本的标准输入输出通常不再与新进程保持连接。iOS 的专用脚本则使用当前解释器的非 daemon 线程调用 `runpy`；它不会创建独立的系统进程，也不保证 iOS 应用切到后台后可持续运行。

Go Loader 同样使用后台分离进程启动 Python Client：Unix 创建独立 Session，Windows 使用隐藏窗口及分离进程标志，输出分别追加在 Release 目录的 `loader_python_stdout.log` 和 `loader_python_stderr.log`。Loader 成功报告 `LAUNCH_OK` 后退出；Server Connections 中的在线状态用于确认后续握手。

Bootstrap 最终打印各阶段日志并结束自己的启动流程。它报告的“Client process launched”表示已经发起并成功创建启动过程，并没有等待新 Client 完成与 Server 的 Socket 握手。是否上线需要到 Server 连接列表再确认。

## 六、iOS / Pythonista Bootstrap

**iOS 有两项和桌面系统不同的边界：**Pythonista 等 iOS Python 运行环境通常不支持创建系统子进程；Client 必须运行在已有 Python 解释器内。此外，Bundle 在 iOS 上的标准目录是 `~/Documents/client_bundle/`，而不是桌面系统的 `~/client_bundle/`。通用 Python Bootstrap 在 iOS 上使用当前解释器；独立脚本提供另一种可直接运行的安装方式。

本仓库提供一个可以直接复制到 iOS Python 环境执行的示例：**[`examples/ios_bootstrap.py`](examples/ios_bootstrap.py)**。此脚本仅使用 Python 3.10+ 标准库，不依赖 `requests`，也不调用 `subprocess`。它不是新的 Server API，也不替代已连接 Client 的在线更新机制。

### 运行步骤

1. 确认 iOS 上的 Pythonista 或其他 Python 环境支持 Python **3.10+**，可访问目标 Server 的 Web 端口、Socket 端口，并且允许在 `Documents` 下写入文件。还需要有运行 Client 所需的第三方依赖；Bootstrap 本身不负责为 Client 安装依赖。
2. 将 [`ios_bootstrap.py`](examples/ios_bootstrap.py) 保存到设备的 Python 脚本目录。在文件开头设置 `WEB_HOST`、`WEB_PORT`、`WEB_SCHEME`、`SERVER_HOST`、`SERVER_PORT`。当 Web 与 Socket 使用不同域名或 IP 时，分别填写；不要直接照用示例局域网地址。
3. 在该设备的 Python 环境中**作为脚本运行** `ios_bootstrap.py`。它请求 Server 构建 Bundle、检查返回数据与 SHA-256、下载 ZIP、检查归档路径，然后解压到独立的暂存目录，安装完成后才启动 Client。
4. 查看控制台的 `[bootstrap]` 输出。脚本显示启动线程成功后，再在 Server 的 Connections 页面确认 Client 是否真正上线。只看到“handoff complete”并不代表 Socket 已握手成功。

安装路径：

```text
~/Documents/client_bundle/
├── downloads/
│   └── <bundle-file>.zip
└── releases/
    └── <build_version>/
        └── rchclient.py
```

示例保留历史已安装的其他 Release，**不会先删除同名 Release**；遇到同名目录会报错停止，防止覆盖正在运行的 Client 文件。它会在目标版本不存在的前提下，将检查合格的完整 Bundle 从暂存位置移动到正式目录。下载、安装或启动失败时，应该根据最后一条错误信息修复原因，不要手动删除仍在使用的 Release。

### 为什么不继续使用通用一行命令？

Python One-liner 会从 `POST /api/agent/bootstrap` 获取通用脚本，再直接 `exec`。通用脚本会在 iOS 上选用当前解释器，而在桌面端按平台进行运行时探测。独立 iOS 示例直接调用 `POST /api/agent/build`，使用相同的 Bundle 构建、下载与哈希校验接口，但采用独立的安装与同名 Release 保护流程。

专用脚本直接构建 Bundle，并检查**构建响应、下载哈希、ZIP 成员、暂存安装和同名 Release**。网络请求只使用标准库，避免首次部署阶段再依赖 `requests`。

### iOS 上的启动与退出边界

安装成功后，脚本使用一个**非 daemon 线程**在当前解释器内运行 `rchclient.py`。Bootstrap 的主线程会返回，但 Client 线程仍然运行；这**不是**通过 `Popen` 创建的独立后台进程。Pythonista 或 iOS 可以在应用退到后台、被挂起或关闭时中止运行，不能承诺其能像桌面 daemon 一样长期驻留。重复运行 Bootstrap 也不会自动接管或停止旧的 Client 线程。

**排障重点：**`subprocess` 不支持时确认执行的是 iOS 专用脚本；`build` 请求失败时查 Web API 和 Builder；SHA-256 不匹配时停止安装；`rchclient.py` 不存在时检查生成的 Bundle；线程启动后仍不在线时查 Socket 地址、端口及 Client 的 Python 依赖。HTTP 示例仅适合可信网络；需要跨公网部署时，应使用可信的加密传输和访问控制，不能把哈希校验等同于服务端身份认证。

## 七、网络、日志与日常诊断

默认监听端口为 Socket `9999`、Web `8085`，独立文件传输端口固定为 **Web port + 1**（默认 `8086`）。One-liners 只需要填写前两个对应的服务端口，即 Socket 和 Web；文件传输端口不能在该表单中单独设置。跨网络做端口映射时，除确保 Socket 与 Web 可达外，还应按 Client 文件传输功能要求转发紧邻 Web 的文件端口。

Go Loader 的进度会通过 `POST /api/agent/loader/report` 写入 Server 小时分段的 `go_loader_YYYYMMDD-HH.log`，本机另可查看系统临时目录的 `go_loader_debug.log`。常见阶段包括 `START`、`PYTHON_OK` / `PYTHON_ERR`、`WORKDIR_OK`、`BUILD_OK`、`DOWNLOAD_OK`、`EXTRACT_OK`、`LAUNCH_OK`，错误阶段也会标记对应失败。报告接口接收日志文本，默认允许匿名访问，因此也需要部署在可信网络范围内；日志并不提供可信的 Client 上线证明。

Bootstrap 输出以 `[bootstrap]` 为阶段前缀，通常会显示：运行时来源及 Python 版本检查、请求 Bundle 构建、Bundle 名称及版本、下载地址与大小、SHA-256 验证、解压安装路径，以及独立 Client 启动。**排障应根据最后成功的一步定位问题**，而不只根据最终有没有出现连接记录判断。

| 表现 | 优先检查 |
|---|---|
| One-liners 地址与实际可达地址不同 | 修改 Server IP；浏览器访问地址不一定是目标设备可访问地址 |
| 无法读取 Server 默认端口 | 检查当前 Web 登录状态及 `/api/agent/platform`；对话框仍可能保留默认端口 |
| Python One-liner 报 `No module named requests` | 桌面启动命令中的 `requests` 未安装；iOS 专用脚本完全使用标准库 |
| iOS 运行 Bootstrap 报子进程不支持 | 确认实际执行的是当前生成的 Python Bootstrap 或本篇独立 iOS 示例；iOS 启动应使用当前解释器，不能通过系统 Shell 拉起新进程 |
| 请求 Bootstrap 失败 | 目标到 Web 端口的网络、地址、防火墙与 HTTP 服务 |
| Bundle 构建失败 | Server 是否注册 Bundle Builder、构建依赖、输出目录写入权限 |
| 找不到可用 Python | 检查 Python 3.10+；Windows 检查 Embed 支持的系统与架构 |
| Bundle 摘要不一致 | 下载内容与此次构建返回的摘要不一致；停止使用该文件并调查下载链路 |
| 解压或安装失败 | ZIP 内容、目标目录权限、同名 Release 被占用或缺少启动入口 |
| 已提示启动但 Server 看不到 Client | Socket 端口可达性、Host 配置、新进程是否退出、Client 启动日志 |
| 修改 One-liner 后再次打开恢复原文 | 窗口编辑只是本次会话的命令文本覆盖，不会写回内置模板 |
| 找不到 Go Loader 构建方式 | 检查 Agent Builder 是否注册 `go_loader`，以及 Server 是否安装 Go 构建工具链 |
| Go Loader 上报 `PYTHON_ERR` | 非 Windows 需要本机 Python 3.10+；Windows 还需检查 Embed 缓存、系统版本和架构 |
| Go Loader 提示 `BUILD_ERR` / `DOWNLOAD_ERR` | 检查 Bundle Builder、构建响应、下载可达性和 SHA-256 校验 |
| Loader 报告 `LAUNCH_OK` 但 Client 离线 | 继续检查 Socket 连通性和新 Python 进程的 stdout/stderr 日志 |

## 八、使用边界

One-liners 交付可复制的 Python / PowerShell 引导命令，Go Loader 交付可分发的可执行程序；两者最终都安装并启动 Python Client Bundle。

One-liners 负责生成和复制部署入口；Bootstrap 完成下载、校验与安装。编辑浏览器中的临时模板文本只改变这次复制的命令，Server 运行配置仍在服务端设置中管理。

Bundle SHA-256 能发现下载内容与当前 Server 所返回摘要不一致的情况；但如果 HTTP 通信本身受到篡改，攻击者也可能替换摘要及文件。因此，应先建立可信的 Server 和传输环境。匿名生成与构建端点还可能消耗 Server 的构建资源，需要做好网络访问约束。

Bootstrap 不会清理所有旧版本，也不会替旧 Client 自动完成运行中进程交接。其目标是安装并启动一个 Client 实例；之后的连接、更新和生命周期管理属于独立功能。对重复部署同一版本，应特别注意 Release 目录替换和可能并存的 Client 进程。

Windows PowerShell bootstrap 使用 `Start-Process` 启动独立 Client，并在创建子进程期间传入 `RCH_CLIENT_LAUNCH_MODE=detached` 与 `RCH_CLIENT_LAUNCH_SOURCE=detached_process`。Client 优先采用显式启动标识；未提供标识时，Windows Service 判定只检查直接父进程是否为 `services.exe`。
