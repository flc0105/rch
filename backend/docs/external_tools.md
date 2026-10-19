# External Tools

External Tools 把可分发的外部程序与运行时进程解耦。Package 描述可安装的程序资源，Exec 描述可调用入口，Module 描述一次具体用途及运行方式；目标平台选择、安装缓存、命令模板和执行结果都由这些元数据共同驱动。

程序被安装并不代表某个 Module 已经运行，结束运行也不代表 Package 被卸载。Web Manager、终端控制与 Script SDK 使用同一组运行对象，但 Daemon 与 Oneshot 的生命周期、日志和状态维护差异明显，应沿着分发、安装、启动、观察和回收的完整路径理解。

## 分发单元与运行单元如何协作

一次典型操作经过以下链路：

```text
External Tool Manager / Server Terminal / Script SDK
                   │
              Server Catalog
       读取 Package / Module Metadata
                   │
         选择目标 Client 和平台架构
                   │
        参数解析、上下文及命令模板渲染
                   │
             Client 消息连接
                   │
       目标端检查安装 / 执行程序 / 管理实例
                   │
            状态、结果、日志回传
```

Server 负责保存和解释工具目录（Catalog），并依据目标 Client 的平台、架构及表单参数构造执行请求；Client 负责检查目标文件系统、下载安装包、运行程序以及维护进程和日志。浏览器不直接向 Client 的文件系统发起操作，也不需要为每个工具单独建立 Server 到 Client 的 SSH 连接。

External Tools 的三个基本概念：

| 概念 | 标识及职责 |
|---|---|
| **Package** | 用 `id` 标识；定义版本、平台安装包、安装位置、可执行文件及 Module 集合 |
| **Exec** | Package 内 `execs` 定义的入口名称；映射到各平台安装包中的实际相对路径，可供 `xt` 和 SDK 调用 |
| **Module** | Package 内 `modules[]` 定义的运行方式；使用 `package_id.module_id` 作为 `tool_id`，选择一个 Exec 并声明 Daemon 或 Oneshot、参数、命令模板及生命周期 |

例如，一个程序包可以定义 `server` 与 `client` 两个 Module，分别使用同一包中的两个 Exec；也可以用同一个 Exec 定义多个不同参数预设的 Module。**安装以 Package 为单位，启动和停止以 Module / Instance 为单位**，这是后续各类操作的基础。

管理界面主要面向所选目标 Client：可以查询 Package 的安装状态，安装、卸载、启动 Module、查看实例；每一步使用的目标平台和架构都来自当前 Client 会话，并由服务端再次核对。

## 元数据中的程序入口与模块契约

External Tool 以 JSON Metadata 描述一个可安装的 Package。Server 读取工具 Metadata 目录中的 JSON 并构造 Catalog；一个 JSON 对应一个 Package。读取失败的条目会在 Catalog 中保留错误信息，而不会被当成有效可运行的 Package。

以下示例采用项目中 Python Heartbeat 工具的组织方式，保留说明机制所需的字段：

```json
{
  "id": "python-heartbeat-log",
  "display_name": "Python Heartbeat Log",
  "version": "1.0.0",
  "category": "demo",
  "platform_packages": {
    "common-all": {
      "platform": "*",
      "arch": "all",
      "filename": "python-heartbeat-log-v1.0.0-common-all.zip",
      "download_url": "/api/external-tools/packages/python-heartbeat-log-v1.0.0-common-all.zip",
      "root": ""
    }
  },
  "execs": {
    "heartbeat": {
      "paths": { "common-all": "heartbeat.py" },
      "launcher": { "type": "client_python", "prefix_args": ["-u"] }
    }
  },
  "install": {
    "install_dir": "{{external_tools_root}}/{{package_id}}/{{version}}/{{package_key}}"
  },
  "modules": [
    {
      "id": "heartbeat",
      "execution": "daemon",
      "exec": "heartbeat",
      "params": [
        { "name": "interval", "type": "number", "default": 2, "min": 0.2, "max": 3600 }
      ],
      "runtime": {
        "cwd": "{{install_dir}}/{{package_root}}",
        "argv": ["{{bin_heartbeat}}", "--interval", "{{interval}}"],
        "stdout": "{{instance_runtime_dir}}/stdout.log",
        "stderr": "stdout",
        "pid_file": "{{instance_runtime_dir}}/tool.pid",
        "state_file": "{{instance_runtime_dir}}/state.json"
      },
      "lifecycle": {
        "stop": { "type": "signal", "signal": "TERM", "timeout_sec": 5, "kill_after_timeout": true }
      }
    }
  ]
}
```

这份定义使 `heartbeat` 成为一个可被安装和识别的 Exec，同时形成 `python-heartbeat-log.heartbeat` Module。`runtime.argv` 使用参数和路径占位符描述真实启动命令；运行弹窗输入的 `interval` 会在执行前经过类型转换，然后代入启动参数。此例是 Metadata 结构说明；实际使用前还须保证 ZIP 文件已在 Server 的 Package 下载目录中可用。

### 包、入口和模块的映射

| 层次 | 字段 | 作用 |
|---|---|---|
| Package | `id`、`name`、`display_name`、`description`、`version` | 标识、名称和展示信息 |
| Package | `category`、`tags` | Catalog 分类与辅助展示 |
| Package | `platform_packages` | 每个平台/架构对应的安装包及下载地址，必需 |
| Package | `execs` | 可执行入口名称及各安装包中的路径，必需 |
| Package | `install.install_dir` | 安装目录模板 |
| Package | `params` | Package 级公共运行参数，可为空 |
| Package | `modules` | Module 数组，至少需要一个有效 Module |
| Exec | `paths` | `package_key → 相对路径`，必须有可用映射 |
| Exec | `enabled`、`description`、`arg_mode` | 是否进入可用 Exec 列表、说明及 CLI 选项 |
| Exec | `launcher` | 可选的启动器与前置参数 |
| Module | `id`、`display_name`、`exec` | Module 标识、展示名称与所选 Exec |
| Module | `execution` | 必须是 `daemon` 或 `oneshot` |
| Module | `params` | Module 自己的参数声明 |
| Module | `runtime`、`runtimes` | 通用运行模板和按平台覆盖的运行模板 |
| Module | `config` | 可选的运行前配置文件生成规则 |
| Module | `lifecycle` | Daemon 的停止和状态相关声明 |

规范化时，Package 的 `params` 会和 Module 的 `params` **依次拼接**，形成 Module 的运行参数 Schema。它不是同名字段的覆盖合并，因此公共参数与 Module 私有参数应避免重名。`execution` 缺失或不是规定的两个值、Module 引用了不存在的 Exec，都会导致该 Package 的 Metadata 无效。

`tool_id` 是 `package_id.module_id`，而 `exec_name` 是 `execs` 中的名称：调用运行 API 要提供 Module 的 `tool_id`，调用 `xt` 或 SDK 的执行入口则通常提供 `exec_name`，不能混为一谈。

### 运行参数由 Metadata 驱动

External Tool 与 Script、Job 复用同一套运行参数 Schema 和单字段表单渲染机制。常规类型包括 `string`、`textarea`、`integer`、`number`、`boolean`、`select`、`remote_file`、`remote_files`、`remote_folder`、`remote_folders`。

例如：

```json
{
  "name": "listen_port",
  "label": "Listen Port",
  "type": "integer",
  "required": true,
  "default": 8080,
  "min": 1,
  "max": 65535,
  "description": "Port for the service"
}
```

界面会显示数字输入控件、默认值与说明；Server 再进行类型转换、必填与范围检查，并将结果用于模板替换。远程多路径参数的结果必须是路径数组，而不是逗号连接的字符串。更多通用字段与转换规则参见 `parameter_schema.md`。

External Tool 的共享参数解析对缺失的可选值采用适合命令模板使用的策略，但这不等于用户显式输入的所有空值都能保留原样。前端初始值、Preset 恢复与服务端解析是不同阶段；涉及默认值或空数组时，实际以最终校验结果为准。

## 在目标平台构建可执行命令

### 平台与架构匹配

每个 `platform_packages` 条目指定 `platform`、`arch`、`filename`、`download_url` 和可选的 `root`。常见 Package Key 形式为 `darwin-arm64`、`linux-amd64`、`win-amd64`；规范化后操作系统使用 `mac`、`linux`、`win` 等平台别名。

选择时优先寻找目标平台与架构完全匹配的 Package Key。如果没有完全匹配，会检查通配平台/架构或 `compatible_targets` 明确声明的兼容目标。只有一个匹配项时才选择；如果出现多个候选，直接报歧义错误，而不是随意取第一个。

`common-all` 可声明 `platform: "*"` 与 `arch: "all"`，适合真正不依赖单一 OS/CPU 的内容包；但是**通用打包不意味着其中的运行程序可以在所有平台执行**。例如脚本包仍可能依赖目标 Client 的 Python 或 Java 环境。

`compatible_targets` 可标记特定兼容条件，例如 macOS Intel 构建在 Apple Silicon 上通过 Rosetta 运行。这是明确允许选择该包的声明；**选择逻辑本身不负责自动安装或检测 Rosetta 等兼容依赖**，运行环境仍须满足对应要求。

服务端 Web 操作要求请求中提供 `platform` 与 `arch`，并与目标 Client 实际会话信息一致。Client 接到安装或运行 Payload 后也会校验目标，防止把一台机器的构建意外装到另一种平台。

### 命令模板和配置生成

Metadata 内使用 `{{name}}` 引用当前构建上下文。常用变量包括 `package_id`、`module_id`、`tool_id`、`version`、`platform`、`arch`、`package_key`、`package_root`、`install_dir`、`instance_id`、`instance_runtime_dir`、`state_file`，以及 `{{bin_<exec_name>}}` 一类执行路径和运行参数名称。

例如：

```json
{
  "config": {
    "target": "{{instance_runtime_dir}}/service.conf",
    "template": "port={{listen_port}}\nname={{instance_name}}\n"
  },
  "runtime": {
    "cwd": "{{install_dir}}/{{package_root}}",
    "argv": ["{{bin_mytool}}", "--config", "{{instance_runtime_dir}}/service.conf"]
  }
}
```

启动时将先根据参数及实例上下文渲染出配置内容，再在 Client 写入 `config.target`，随后启动进程。配置写入目标是覆盖写入，没有独立的版本备份。没有声明有效的 `config.target` 和 `config.template` 时不生成配置文件。

`runtime.argv` 可以是数组，也可以是以 Shell-like 方式拆分的字符串。它最终作为参数列表以 `shell=False` 执行，不经过系统 Shell 再解释一遍；需要环境变量展开、管道、重定向等 Shell 语义时，必须由所选可执行程序或显式 Launcher 自己实现。

`runtime.extra_args`、`runtime.extra_args_param` 可以把额外参数追加到 `argv`；`runtimes` 可为不同平台提供覆盖项。匹配到第一个适用平台/架构的运行变体后，以该变体字段覆盖基础 `runtime`，而不是累加所有匹配项。

模板引擎只替换可解析的 `{{变量}}`，不支持任意表达式。未找到值时会保留原始占位符，因此 Metadata 拼写错误可能直到生成命令或执行时才暴露。

### 执行器的入口定义

默认直接运行 `runtime.argv` 的第一个元素。若包中 Exec 配置了 `launcher`，还可以使用：

| 类型 | 行为 |
|---|---|
| `direct` | 不额外包装命令，直接执行原入口 |
| `client_python` | 使用目标 Client 的 Python 启动脚本，可追加 `prefix_args`（如 `-u`） |
| `system` | 从系统 PATH 或指定路径解析外部启动器，再执行程序入口 |

`client_python` 在普通 Python 运行模式下使用 Client 当前解释器；打包模式会寻找与 Client Python 主次版本一致的系统解释器，若找不到则报错，并不会凭空提供 Python 运行环境。

Web 运行弹窗可先请求目标 Client 解析 Launcher，再临时修改可执行程序路径。该 Override 仅影响本次 Preview/Run，不会自动写回 Metadata 或保存到 Preset。`prefix_args` 与目标脚本路径仍按照声明组合。

## 程序包落地与文件状态

### 准备与安装阶段

External Tool 使用 Package ZIP 分发。Server 根据 Metadata 指定的 `filename` 从自己的 Package 目录提供下载；Client 按以下流程安装：

1. 按平台与架构选择对应的 Package，构造下载和安装 Payload。
2. 检查 Client 本地 Package 缓存；已有非空同名缓存文件则复用，否则通过 Client HTTP 下载接口取得 ZIP。
3. 确定安装目录并检查实际文件是否已存在、是否具备该 Package 声明的全部 Exec 路径。
4. 若未安装，将 ZIP 解压到对应安装目录；解压前检查 ZIP 条目是否越过目标路径。
5. 重新核对安装目录和 Exec 文件，成功后设置必要的可执行权限并写安装日志。
6. 将安装结果、安装目录、Exec 路径、缓存状态和错误信息返回 Web。

默认路径由 Client 用户 Home 解析：

```text
~/.ops/external_tools/packages/
~/.ops/external_tools/installed/<package_id>/<version>/<package_key>/
~/.ops/external_tools/runtime/
```

三者分别用于下载缓存、已解压程序包和运行实例。Metadata 可以自定义安装目录模板，因此真实路径以 Client 返回结果为准。

**安装成功的标准是目标安装目录存在，且所有声明的 Exec 路径都存在对应文件**。历史安装记录、前端显示缓存或单个可执行文件存在，都不能代替完整的实际文件检查。当前常规安装状态主要是 `installed` / `not_installed`；请求失败则给出 `error`。安装日志保存在安装目录中的 `.install.log`。

缓存命中仅依据文件存在且大小非零；这条安装链没有进行独立的包内容 SHA-256 校验。路径安全检查防止普通 ZIP 路径穿越，但并不能把来源未知的 ZIP 视为可信程序。建议只使用可控的 Package 源。

### 已安装状态的判定

**Install 只负责准备 Package，不会因为安装完成就自动创建 Daemon Instance。** 管理界面的运行操作也不默认悄悄安装缺失的 Package：如果尚未安装，需先执行 Install，再 Run。

Uninstall 删除该 Package 对应平台构建的安装目录，并在存在活动 Daemon 实例时拒绝操作，以避免正在运行的实例仍引用已删除程序。**Uninstall 不等于删除实例运行目录、状态文件、日志或 Package ZIP 缓存**。

Clear Package Cache 只删除对应包的 ZIP 缓存，用于下次重新下载；不会替代 Uninstall，也不会自动停止正在运行的实例。如果安装包已经更新但文件名没有变化，原缓存可能继续命中，需按需要清除缓存后重新安装。

## 进程托管与运行结果

两个模式共享 Package、Exec、参数和模板解析，但执行生命周期不同。

| | Daemon | Oneshot |
|---|---|---|
| 目标 | 常驻服务、多次管理 | 执行一次并取得结果 |
| 进程启动 | 分离启动，持有 PID、状态和日志路径 | 前台子进程运行，等待结束 |
| 运行身份 | `instance_id` | 每次自动生成 `run_id` |
| 返回时机 | 启动请求完成并取得 PID 后 | 进程完成或超时后 |
| 输出 | 写到实例日志 | 返回 `stdout` / `stderr` |
| 主要操作 | Start、Status、Stop、Logs、Restart、Remove | Run Once、查看一次性结果 |

### 常驻实例的启动

Daemon 按 `package_id/module_id/instance_id` 隔离状态。启动请求包含参数和可选的显式 `instance_id`；没有指定时，可以从 `instance_name` 等参数推导。针对特定用途，还可能从 `proxy_name + remote_port`、`bind_port` 构造实例名，最终名称中的不安全字符会被替换，并限制长度。

运行实例通常放在：

```text
~/.ops/external_tools/runtime/<package_id>/<module_id>/instances/<instance_id>/
├── tool.pid
├── state.json
└── stdout.log
```

可以在同一个 Module 下启动多个不同 `instance_id` 的实例。每个实例有自己的命令上下文、PID 文件、配置文件、输出日志和历史状态。

启动前会检查实例 PID 是否仍然存活：已存活时返回 Already Running 状态，不创建第二个同名实例；否则检查 Package 是否已安装、写入配置、构建最终命令并分离启动。POSIX 下使用独立 Session，Windows 下使用分离进程和新的进程组；底层启动均不使用 `shell=True`。启动结果记录 PID、命令、参数、路径和开始时间。

**`running: true` 表示系统检查到该 PID 存活，不是应用已通过端口监听、HTTP 健康检查或业务可用性验证。** 分离启动后的程序如果立即退出，稍后的 Status 可能显示 `stale`。

### 常驻实例的管理与回收

状态读取 PID 文件和 `state.json`，结合操作系统 PID 存活检查得到 `running`、`stale`、`stopped`、`not_started` 等状态：

- `running`：PID 被判断为存活；
- `stale`：PID 文件存在，但该 PID 已不存活；
- `stopped`：记录了已停止状态，且当前无活跃进程；
- `not_started`：没有有效运行记录。

Stop 默认向目标 PID/进程组发送 `TERM`，按配置等待一段时间，必要时强制发送 `KILL`。Module 的 `lifecycle.stop` 也可以指定通过外部命令停止，并在需要时配置信号 fallback；不同停止方式的执行细节由对应规则决定。

**Stop 只负责停止进程并更新状态，不自动删除该实例的日志和文件。** 如果 PID 已失效，会清理过期 PID 文件并写停止状态，避免对不存在的 PID 再发送信号。若停止后仍有进程存活，Status 会继续反映实际检查结果，不能仅凭“stop requested”字样认为进程必已退出。

Remove Instance 会删除整个实例运行目录（含日志、PID、状态文件）；Clear Logs 只清空当前实例的 stdout 日志。两者都要求实例先处于非运行状态。重启通常是先 Stop 再重新使用参数启动，而不是在原进程内热更新配置。

### 一次性命令的完成语义

`execution: "oneshot"` 的 Module 使用同步子进程执行，捕获 stdout、stderr、退出码和时间信息，结束后返回结果。运行结果常见字段：

```json
{
  "execution": "oneshot",
  "status": "completed",
  "success": true,
  "running": false,
  "returncode": 0,
  "stdout": "...",
  "stderr": "",
  "timed_out": false,
  "duration_sec": 0.18
}
```

这里的数字与输出是结构示例，并非本次运行记录。退出码为 0 且没有超时才算成功；非 0 或超时标记失败。超时以 `runtime.timeout_sec` 等显式设置为准，未声明时请求构建使用 60 秒默认值；Web 会等进程结束再弹出结果，不会把它列为一个可 Start/Stop 的常驻实例。

Oneshot 的 `run_id` 可用于确定本次请求的运行上下文，但不要与 Daemon 的 `instance_id` 混淆；常规 Oneshot 返回 `stdout` / `stderr`，并未按 Daemon 模式建立可供 Instances 页独立管理的运行记录。

## 管理界面及可复用运行配置

External Tool Manager 的主要视图是 **Packages** 和 **Instances**。

**Packages** 展示 Server Catalog，并按当前目标 Client 过滤适用 Package。用户可以选择设备，查看 Package 安装状态、下载 Package、Install、Uninstall、Clear Package Cache、查看状态及编辑 Metadata。Package 下再展开可执行的 Module，按 Daemon/Oneshot 显示对应 Run 操作。

**Instances** 展示当前设备已有 Daemon 实例，包含实例标识、状态、PID、端口/参数相关信息和开始时间等。对于具体实例，可查看日志、请求停止、查看详细信息、重启、清理日志或移除实例；运行中的实例不可直接执行清理文件的操作。

### Preset 与运行请求

打开 Module 的 Run 弹窗后，共享参数渲染器依据 `params` 显示控件。`remote_file`、`remote_folder` 等类型可以打开 Remote File Picker，返回的是目标 Client 路径，而非浏览器本地路径。

弹窗提供一个 **Module Defaults** 选项，并支持保存自定义 Preset、更新和删除。选择某个 Preset 时，先建立 Module 默认表单值，再用 Preset 中的参数覆盖对应字段；所以 Preset 是一套运行参数快照，并不改变 Metadata 本身。

Preset 按完整 `tool_id` 保存在 Server 的 `rch.db`，名称在同一个 Module 下不区分大小写且不可重复。创建/更新时只允许保存该 Module 已声明的参数名称。**Preset 存储时不会替代每次运行的类型校验**：如果 Metadata 的限制变化，原 Preset 可能在下一次 Run 时不再通过校验。

Daemon 还可利用 `instance_name` 区分同一 Module 的多个实例；Preset 与 Instance 不是同一对象。删除 Preset 不会停止已有实例，Remove Instance 也不会删除 Preset。

### 命令预览和 Metadata 编辑

Daemon 运行弹窗中的 **Preview Command** 会在目标 Client 上生成最后的 `argv`、`cwd` 和可复制的 Shell 风格命令文本，但**不启动程序、不执行配置写入，也不代替安装检查**。它适合确认模板变量、Launcher 和最终参数有没有拼错。当前这个按钮只面向 Daemon，Oneshot 弹窗不提供同样的 Preview 操作。

Metadata 的 **Edit Metadata** 功能打开 Server 上的 Package JSON。保存前检查 JSON 格式及关键 Metadata 规则，不允许通过编辑器直接修改 Package ID；保存只修改 Catalog 定义，不自动替换已安装的 ZIP 文件，也不会重新构造已启动实例的进程命令。变更版本、路径或 Exec 声明后，需要重新检查对应目标的安装状态与运行参数。

## 终端和 Script 的调用通路

External Tool Manager 负责安装和常驻实例管理；`xt` 和 Script SDK 则提供更加轻量的**已安装 Exec 调用**入口，它们不会将一个任意命令名自动变成可安装工具。

### 终端控制入口

在已选择目标 Client 的 Server Terminal 中，可用：

```text
xt list
xt info ffmpeg
xt which ffmpeg
xt ffmpeg -- -version
```

`xt list` 根据当前 Client 平台与架构列出可解析的 Exec；`xt info` 查看指定 Exec 的信息，`xt which` 查询它在 Client 上已安装的可执行文件位置；最后一条把 `-version` 作为原始命令行参数传给对应 Exec。`--` 可明确区分 `xt` 自身语法和目标程序参数。

`xt list --json` 也可输出结构化 JSON；终端支持的具体调用形式可查看 `xt` 帮助。**`xt install` 不支持**，需要先在 Manager 中完成安装。不同 Package 如果在当前平台提供相同 Exec 名称，会产生歧义错误，应使目标平台可用的 Exec 名称保持唯一。

Exec CLI 会在 Client 上创建子进程，标准输出与错误输出通过常规命令流返回；它具有取消/等待行为，但不自动在 Manager 中登记为 Daemon 实例。与 Module 运行不同，它面向 Exec 级直接命令调用。

### 脚本访问的执行上下文

脚本可以显式导入：

```python
from client.runtime.sdk import xt

ffmpeg = xt.tool("ffmpeg")
if ffmpeg.is_installed:
    result = ffmpeg("-version")
    print(result.stdout if result.ok else result.stderr)
```

SDK 还提供 `xt.run("ffmpeg", "-version")` 和 `xt.ffmpeg("-version")` 等入口，并可通过 `which()`、`status()` 获取 Exec 信息。运行结果包含 `returncode`、`stdout`、`stderr`、`command`，`ok` 表示成功。

Script 使用这项能力须在 Metadata 的 `api_grants` 中声明 `external_tools:catalog`，并使用支持 Client 内部服务的 **In-process Python 执行模式**。SDK 会向 Server 请求 Catalog 定义，但安装状态由当前 Client 的文件系统判断；它不能绕过 Web/Client 权限凭空安装不存在的工具。

## 状态查询、日志与事件分发

External Tools 的 HTTP 管理接口分两类：**Catalog / Preset** 面向 Server 管理数据，**Client Lifecycle** 则转为发往当前 Client 的执行命令。

| 方法 | 接口 | 用途 |
|---|---|---|
| GET | `/api/external-tools/catalog` | 查询 Package、Module Catalog |
| GET / POST | `/api/external-tools/{package_id}/meta/content` | 读取或保存 Package Metadata |
| GET | `/api/external-tools/{package_id}/download?platform=...&arch=...` | 获取选定平台安装包 |
| GET | `/api/external-tools/{tool_id}/param-presets` | 查询 Module Preset |
| POST | `/api/external-tools/{tool_id}/param-presets` | 创建 Module Preset |
| PUT / DELETE | `/api/external-tools/{tool_id}/param-presets/{preset_id}` | 更新或删除 Preset |
| POST | `/api/connections/{client_id}/external-tools/catalog` | 查询目标 Client 的 Package 安装状态 |
| POST | `/api/connections/{client_id}/external-tools/{package_id}/install` | 安装 Package |
| POST | `/api/connections/{client_id}/external-tools/{package_id}/install-status` | 核查 Package 是否已安装 |
| POST | `/api/connections/{client_id}/external-tools/{package_id}/uninstall` | 卸载 Package |
| POST | `/api/connections/{client_id}/external-tools/{package_id}/clear-cache` | 清除 Package ZIP 缓存 |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances/start` | 启动 Daemon Instance |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances/preview-command` | 预览 Daemon 启动命令 |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/oneshot` | 执行 Oneshot |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances` | 查询某 Module 的实例 |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances/{instance_id}/stop` | 停止实例 |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances/{instance_id}/logs` | 获取日志 |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances/{instance_id}/remove` | 移除已停实例运行文件 |
| POST | `/api/connections/{client_id}/external-tools/{tool_id}/instances/{instance_id}/clear-logs` | 清空已停实例日志 |

还有 `/api/connections/{client_id}/external-tools/instances` 用于汇总当前 Client 的实例，以及 `.../{tool_id}/launcher` 用于解析目标 Client 的 Launcher。绝大多数管理 API 使用正常 Web 身份验证；安装包下载端点允许匿名下载，因此对这些地址的网络暴露应单独考虑。

例如要在某个 macOS arm64 Client 上启动已安装的 Module，可提交：

```http
POST /api/connections/{client_id}/external-tools/{tool_id}/instances/start
Content-Type: application/json

{
  "platform": "mac",
  "arch": "arm64",
  "params": { "interval": 2, "instance_name": "demo-a" },
  "instance_id": "demo-a"
}
```

`{tool_id}` 应传完整 Module ID，例如 `python-heartbeat-log.heartbeat`；`platform/arch` 必须与该 Client 会话一致。实际允许哪些参数，仍由该 Module 的 Metadata 决定，上述示例不表示所有 Module 都具有 `interval` 字段。请求成功只说明 Client 接受并执行了对应启动路径，不是应用层健康检查通过。

### 日志增量读取及实时通知

Daemon 默认将 stdout 写入 `stdout.log`，stderr 可配置为合并到 stdout 或另写文件。Manager 的 Logs 操作主要读取实例 stdout 日志。首次返回文件末尾片段，之后通过 `cursor` 继续读取新追加的字节；如果日志被替换、轮转或截断，返回 `reset` 告知客户端重新建立位置。

```json
{
  "content": "service started\n",
  "cursor": "...",
  "reset": false,
  "log_file": ".../stdout.log"
}
```

单次增量日志读取设置了大小上限（最多约 256 KiB），不会一次性把完整日志全部加载到浏览器。Streaming 开关是前端轮询该增量接口，并不是让目标进程改用 WebSocket 推送每一行日志。

Server 会在安装成功/失败、卸载成功/失败，以及 Daemon 启动、停止或发生相关错误时发布 External Tool 生命周期事件。这些事件可进入 SSE 通知与通知中心；Oneshot 的执行结果主要由本次运行请求返回并展示在结果弹窗中，不应视为同样的独立生命周期推送。通知产生也不等于自动验证服务端口或业务健康。

## 部署一致性及异常恢复

| 现象 | 应检查的机制 |
|---|---|
| Catalog 显示某 Package 无效 | JSON 结构、必填的 `platform_packages` / `execs` / `modules`、Module 引用的 Exec |
| 目标设备看不到或无法安装工具 | 平台及架构匹配、`compatible_targets`、目标会话信息，是否出现多个候选 Package Key |
| Package 下载返回不存在 | Server 的 Package 目录是否有 Metadata 指定的 ZIP；Metadata 存在不等于 ZIP 已存在 |
| Installed 为 False，但安装目录存在 | 是否缺少任何声明的 Exec 路径；安装状态不由旧状态文件决定 |
| 安装使用了旧 ZIP | 本地同名缓存是否命中；需要时 Clear Package Cache 并重新安装 |
| Install 成功但 Run 失败 | 所选 Module 对应 Exec、Launcher、目标 `cwd`、参数模板与依赖是否正确 |
| Preview 的命令看起来正确，但不能启动 | Preview 不运行程序、不检查运行后的依赖和端口可用性 |
| 报找不到 Python 或外部 Launcher | `client_python` / `system` 所需启动器在目标 Client 中不可用 |
| Instance 显示 `stale` | PID 文件仍在，但进程不再存活；检查 stdout 和启动参数 |
| Stop 返回后仍显示 Running | 进程未真正退出或自定义 stop command 未停止目标；重新查询 PID 状态 |
| Clear Logs / Remove 不允许操作 | 必须先停止目标实例；二者也不是卸载 Package |
| Oneshot 返回 Failed | 查看 `returncode`、`timed_out`、`stdout`、`stderr` 和超时设置 |
| Preset 无法加载或运行 | Metadata 参数名称可能变化；Preset 不保证永远符合当前类型与范围要求 |
| Script SDK 提示权限或执行模式错误 | 确认 `external_tools:catalog` Grant 和 In-process Python 模式 |
| `xt` 找不到或出现歧义 | 确认 Exec 已安装，且目标平台同名 Exec 不产生多个候选 |

几个行为边界应始终区分：

- **Catalog 不是运行环境镜像。** Catalog 来自 Server Metadata；实际安装和进程状态必须向目标 Client 查询。
- **运行状态不是应用健康状态。** PID 存活不代表服务已监听端口或完成业务初始化。
- **Package、Instance、Preset、Cache 是四类不同对象。** 卸载、停止、移除实例、删除 Preset、清缓存不会自动互相替代。
- **不是完整事务系统。** 安装、解压、生成配置、启动进程分别执行；中途失败可能留下缓存、部分解压文件或运行文件，需要根据实际状态处理。
- **外部程序继承 Client 所在设备的执行权限。** 安装包、脚本和命令模板应当来自可信来源；管理界面不会为每个工具自动创建独立的操作系统权限沙箱。
- **Server Metadata 的修改不会自动重建已安装程序。** 更新配置后要重新评估安装包、平台路径和现有实例，避免以为保存 JSON 就已经更新了远端进程。
