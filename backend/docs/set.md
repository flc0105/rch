# RCH Client 运行配置指南

## `set` 命令与 Configuration

RCH 为每台 Client 提供一套可以在线查询和调整的运行配置。它主要用于选择文件传输、Python 执行和 Screen View 的工作策略，以及调整超时、重连、预览与 Watchdog 等行为。

你可以通过两种入口管理它：在选中设备的命令终端使用 **`set`**，或者在前台 **Info → Configuration** 中可视化编辑。两者操作的是**同一台 Client 的同一套运行配置**；Configuration 并不是另一份独立的 Server 设置。

配置变更通常作用于后续操作，而不是把已经开始的任务强制切换到另一种工作方式。对于正在运行的文件传输、Python 脚本和屏幕会话，应以当前任务实际使用的策略为准。

## 1. 从哪里进入

### 前台：Info → Configuration

1. 在 RCH 前台选中一台在线 Client。
2. 打开 **Info**，切换到 **Configuration** 标签。
3. 页面显示可用配置项及当前值。标有 `override` 的项目表示当前值覆盖了默认值。
4. **双击**需要修改的配置项：枚举项使用下拉选择，开关使用切换控件，数字使用数值输入。
5. 点击 **Save** 保存，或点击 **Reset Default** 清除该项自定义值，恢复默认。

`Reset Default` 只有当前项目存在 `override` 时才可用。前台只显示支持在线编辑的配置，不负责展示全部底层配置常量。

### 命令终端：`set`

以下命令要在**选中 Client 的 RCH 命令终端**执行，而不是在操作系统的 bash、zsh 或 PowerShell 中执行。

| 命令 | 用途 |
|---|---|
| `set` | 按分组查看可在线管理的配置、当前值及 `default / override` 来源 |
| `set --json` | 以 JSON 查看可在线管理的配置，包含类型、说明、允许的选项等信息 |
| `set --all` | 查看全部基础运行配置，包括不能直接通过 `set` 修改的项目 |
| `set KEY value` | 修改一个允许在线编辑的配置 |
| `set --reset KEY` | 移除一个配置项的自定义值，恢复默认 |
| `set --reset-all` | 清除**所有**运行配置覆盖值，整体恢复默认；请谨慎使用 |

例如：

```text
set
set HTTP_TRANSFER_MODE cancelable
set PYTHON_EXECUTION_MODE subprocess_pipe
set --reset PYTHON_EXECUTION_MODE
```

配置名不区分输入时的大小写，但文档和界面统一使用大写名称。布尔值可使用 `true` / `false`；数字项按配置自身的单位和范围填写。`set KEY` **不是**单项查询语法：查询请使用 `set` 或 `set --json`。

> **如何理解 `default` 与 `override`**  
> `default` 表示正在使用内置默认值；`override` 表示保存了与默认值不同的自定义值。把某项设回它的默认值，也会清除对应覆盖记录。修改不会直接改写程序源码。

## 2. 三种最重要的 Strategy

这里的 Strategy 指**运行方式的选择**。当前常用的三个策略项分别控制 HTTP 文件传输、Python 执行与 Screen View 帧编码；它们相互独立，不是全局统一的“性能模式”。

### 2.1 HTTP 文件传输 — `HTTP_TRANSFER_MODE`

默认：**`legacy`**

| 选项 | 特点 | 更适合的情况 |
|---|---|---|
| `legacy` | 使用较传统的 HTTP 文件上传/下载方式。上传的 multipart 内容可能被整体缓存在内存中；运行中取消不受支持 | 小文件、保持默认行为、无需中途取消的任务 |
| `cancelable` | 流式传输，按块处理文件，支持进度回报与协作取消；大文件上传不必整体装入内存 | 大文件、弱网、需要观察传输进度或中途取消的任务 |

```text
set HTTP_TRANSFER_MODE cancelable
```

`legacy` 上传对**超过 1 GiB** 的文件有保护性限制。涉及较大文件时，更建议选择 `cancelable`。但协作取消不等于在任何网络阻塞点都能瞬间结束任务。

**注意：**这个选项决定的是 **Client 如何处理 HTTP 文件数据**，不决定 Server 使用哪个端口，也不会让所有 HTTP 请求都自动支持取消。浏览器上传、Client 上传、Artifact 下载和 Transfer Center 的进度跟踪仍有各自的实际执行路径。

相关设置：

- `HTTP_TRANSFER_BUFFER_SIZE`：默认 **1 MiB**（`1048576` 字节），允许 **64 KiB～16 MiB**。
- `HTTP_TRANSFER_IDLE_TIMEOUT_ENABLED`：默认 **`true`**。
- `HTTP_TRANSFER_IDLE_TIMEOUT_SECONDS`：默认 **21600 秒（6 小时）**。

Idle Timeout 关注的是**网络 I/O 长时间没有进展**，不是限制整个大文件传输最多运行多久。通常保持默认缓冲区和空闲超时即可；切换传输策略不需要顺便调大它们。

### 2.2 Python 执行 — `PYTHON_EXECUTION_MODE`

默认：**`inproc`**

| 选项 | 特点 | 更适合的情况 |
|---|---|---|
| `inproc` | 在当前 Client 的 Python 进程内执行代码；无需为每次执行启动独立解释器，但运行中不支持可靠的强制取消 | 一般脚本、默认执行方式 |
| `subprocess_pipe` | 使用独立 Python 子进程执行，通过管道接收代码与输出；支持终止子进程来取消执行 | 可能长期运行、希望具备更明确取消能力的脚本 |

```text
set PYTHON_EXECUTION_MODE subprocess_pipe
```

`subprocess_pipe` 需要启动额外进程，会带来一定的启动开销；它也不是安全沙箱或权限隔离机制。与主进程执行相比，进程状态和运行环境存在差异，重要脚本应先测试。`inproc` 无法安全强制中断正在运行的任意 Python 代码，不宜把前台取消按钮理解为随时可以停止脚本。

切换策略后，以**下一次执行**使用的模式为准；已经运行的脚本不会被迁移到另一种执行方式。

### 2.3 Screen View 画面 — `SCREEN_FRAME_STRATEGY`

默认：**`full_jpeg`**

| 选项 | 特点 | 更适合的情况 |
|---|---|---|
| `full_jpeg` | 每次更新发送完整 JPEG 画面，帧相互独立，行为简单稳定 | 通用远程预览、画面变化频繁的桌面 |
| `keyframe_delta` | 先发送关键帧，随后主要发送变化区域；静止画面可以跳过重复传输 | 桌面变化较少、希望减少传输数据的场景 |

```text
set SCREEN_FRAME_STRATEGY keyframe_delta
```

`keyframe_delta` 不是将 WebSocket 改成 HTTP，也不是新的屏幕采集权限模式；它只改变画面数据的编码与重建方法。当画面变化很大、经过一定时间或分辨率改变时，仍会发送新的完整关键帧，因此不保证任何场景都比 `full_jpeg` 省流量。

**该配置只在建立 Screen View 会话时选定。** 修改后需要关闭并重新打开 Screen View，或者使用窗口中的 Restart，当前会话才会采用新策略。窗口内的 **FPS、Quality** 是另两项会话设置，可以在已有会话中调整，和这里的帧策略不必一起修改。

## 3. 其他常用运行配置

这些项目不是上述三个 Strategy，但可以用同样的 `set` / Configuration 入口管理。

| 分组 | 配置项 | 当前默认值 | 用途 |
|---|---|---|---|
| Command | `COMMAND_DEFAULT_SHELL_TIMEOUT` | `30` 秒 | Shell 命令的一般兜底超时 |
| Command | `COMMAND_DEFAULT_STREAM_TIMEOUT` | `300` 秒 | 流式命令的一般兜底超时 |
| Preview | `PREVIEW_IMAGE_COMPRESS_ENABLED` | `false` | 在图片预览上传前尝试压缩，仅影响相应预览流程 |
| Preview | `PREVIEW_IMAGE_COMPRESS_QUALITY` | `75` | 预览压缩的图片质量参数 |
| Connection | `RECONNECT_INTERVAL_SECONDS` | `5` 秒 | Client 断线后再次尝试连接的间隔 |
| Watchdog | `REMOTE_HTTP_WATCHDOG_ENABLED` | `false` | 启用独立 HTTP 远程进程控制 |
| Watchdog | `LOCAL_WATCHDOG_ENABLED` | `false` | 启用本地心跳超时恢复 |
| Watchdog | `PROCESS_WATCHDOG_ENABLED` | `false` | Client 进程异常消失时，由独立监督进程尝试复活 |

关于 Watchdog，容易混淆的是以下三种行为：

- **Remote HTTP Watchdog**：从 Server 取得待执行的远程进程控制操作，不等于自动检测 Client 故障。
- **Local Heartbeat Watchdog**：关注心跳长时间停止，处理“进程还在，但心跳不再更新”的情况。
- **Process Watchdog**：关注 Client 进程是否已经死亡，并在非预期退出后尝试恢复；不会因为网络断开、进程仍存活就触发复活。

它们可以分别启停，不属于同一个三选一的 Strategy。启停开关可在线调整；涉及 Watchdog 组件的配置变更可能重建相应监控进程，因此建议逐项修改、逐项检查。

下列时间参数可通过 `set --all` 查看，但**目前不能**使用普通 `set KEY value` 或前台 Configuration 在线修改：

- `REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS`：默认 **15 秒**。
- `LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS`：默认 **5 秒**。
- `LOCAL_WATCHDOG_TIMEOUT_SECONDS`：默认 **15 秒**。

**能查到某项配置，不等于它一定可编辑。** 运行中 Watchdog 的真实状态可另外使用 `watchdog` 或 `watchdog --json` 查看；配置开关显示为 `true`，不保证监控组件一定已经健康运行。

## 4. 三个常见调整示例

### 大文件传输：减少内存压力并允许取消

```text
set HTTP_TRANSFER_MODE cancelable
```

先只切换模式，确认上传下载、进度和取消行为符合预期；不必一开始就更改缓冲区和超时。

### 希望 Python 长任务可以被取消

```text
set PYTHON_EXECUTION_MODE subprocess_pipe
```

先使用非关键脚本验证运行环境和输出，再应用到日常任务。

### 公网远程查看静态桌面，希望减少画面数据

```text
set SCREEN_FRAME_STRATEGY keyframe_delta
```

然后**重新建立 Screen View 会话**，观察画面是否稳定、延迟和数据量是否符合预期。若遇到不适合的画面场景，可恢复默认：

```text
set --reset SCREEN_FRAME_STRATEGY
```

## 5. 保存、恢复与注意事项

`set` 和 Configuration 的修改会应用到当前 Client 的运行配置；与默认值不同的设置保存在 Client 本机的外部 `runtime_config.json` 中，通常在 Client 重启后仍保留。**这不是 Server 的全局配置，也不会自动批量修改其他设备。**

配置文件默认随 Client 运行用户和操作系统而定，例如 macOS 位于该运行用户的 `~/Library/Application Support/rchclient/runtime_config.json`。如果 Client 以不同系统用户身份启动，所用配置文件也可能不同；实际路径可在 `set` 输出或配置数据中查看。需要自行指定路径时，可使用启动环境变量 `RUNTIME_CONFIG_PATH`。

恢复设置时，优先只重置具体项目：

```text
set --reset HTTP_TRANSFER_MODE
set --reset PYTHON_EXECUTION_MODE
set --reset SCREEN_FRAME_STRATEGY
```

只有确定要**清除整台 Client 的全部自定义运行配置**时，才使用：

```text
set --reset-all
```

一般建议修改一项、验证一项；重点观察下一次传输、下一次脚本执行或重新建立的 Screen View 会话。出现问题时，先核对配置来源与当前实际运行状态，不要只根据配置页面显示的值推断已经开始的任务也切换了策略。

---

**快速记忆**：`set` 是命令入口，**Info → Configuration** 是可视化入口；`default / override` 是配置来源；三个常用策略分别解决**文件怎么传、Python 怎么运行、屏幕画面怎么编码**。
