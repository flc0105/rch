# Log Viewer

移动端打开 Log Viewer 时默认占满屏幕，日志内容区使用剩余高度；桌面端保持独立窗口大小。

**Log Viewer** 用于在 Web 界面中查看**在线 Client 文件系统上的文本日志**，支持手动刷新、持续跟踪、搜索当前已加载内容，以及查看文件轮转或截断后的新增内容。Server 自身的 `server.log` 通过 [Logging](logging.md) 中的本地文件路径查看；命令执行记录见 [Command History](command_history.md)。

主日志的产生、路径和保留策略见 [Server / Client Logging](logging.md)。

Log Viewer 的 `log_file` Monitor Session 使用标准库读取客户端日志；在 iOS / Pythonista 中无需安装 `psutil`。文件必须位于该 Client 可读取的路径下。

## 打开日志与选择来源

**常用入口：**

| 入口 | 默认目标 |
| --- | --- |
| **Toolbox → Log Viewer** | 当前选中且在线的 Client 主日志（Client 已上报可用路径时） |
| **Connection Info → Watchdog** 的日志入口 | 对应 Watchdog 的独立日志文件 |
| **External Tools** 的实例日志入口 | 对应工具实例的日志文件 |
| 查看器中的 **Browse** | 在当前目标 Client 上手动选取其他日志文件 |

从带有明确日志路径的入口打开时，**指定的文件优先于 Client 主日志默认值**。Toolbox 直接打开但没有可用默认路径时，查看器保持待选择状态，可使用 Browse。

在设备列表中选择在线 Client，打开 Toolbox 的 **Log Viewer** 即可开始。需要确认默认路径时，在 **Connection Info → Basic Info → Client Log** 查看目标 Client 上报的绝对位置。

Browse 打开远程文件选择器；选择目标 **Client 文件系统** 中的日志路径。目标 Client 必须在线，并且该进程具有读取对应文件的权限。日志读取要求目标文件具有绝对路径；无法访问、文件尚未创建或设备断开时，界面显示相应读取错误或空内容。

> **Server 日志不在此范围内：** `backend/runtime/server.log` 属于 Server 自己的文件。请在 Server 机器上使用 `tail -F` 等方式查看；Log Viewer 不提供 Server 本地文件选择。只有某个文件确实位于选中 Client 可访问的文件系统上时，才可能通过 Client 文件读取通道查看它。

## 工具栏操作

第一行单独显示当前远程日志路径，过长时截断显示，悬停可查看完整路径。第二行左侧使用 Streaming、Follow、Wrap 三个 Switch；右侧提供 Browse、当前日志搜索和 More 菜单。Refresh、Clear View、Copy 收纳于 More。窄屏时开关与操作会换行，搜索框移到单独一行。


| 控件 | 效果 |
| --- | --- |
| **Browse** | 选择当前目标 Client 上的其他日志文件；切换文件后重新开始读取 |
| **Streaming** | 开启时持续接收日志更新；关闭时停止实时读取，不删除已经显示的内容 |
| **More → Refresh** | 清空当前显示并重新从所选文件读取；Streaming 关闭时执行一次读取，开启时恢复持续跟踪 |
| **More → Clear View** | **仅清空此浏览器窗口中的显示内容**；不删除或截断 Client 上的日志文件 |
| **More → Copy** | 复制当前已加载的完整日志文本到浏览器剪贴板（包括未匹配搜索词的行） |
| **Follow** | 有新日志时自动滚动到末尾；向上滚动离开底部后会自动关闭，可手动重新勾选 |
| **Wrap** | 长行在显示区域自动换行；不改变日志原文 |
| **Find in loaded log...** | 对**当前已加载的文本**进行不区分大小写的行筛选；不搜索整个远程文件或旧轮转备份 |

搜索结果只改变显示哪些行，不改变原始日志、当前读取位置或复制的文本。行号在**当前已加载内容**中编号；浏览器保留的内容有限，早期行可能随新内容进入而被淘汰。

## 实时读取的工作方式

打开一个可用文件时，Web 会为当前浏览器标签页和目标 Client 建立独立的远程监控会话。Client 从文件末尾读取一段内容作为初始视图，随后只读取追加部分，经 Server 转发至当前浏览器。**不会在打开时下载整个大日志文件**，也不依赖一次次执行 `shell` 命令。

- 日志文件以 **UTF-8** 文本读取；非 UTF-8 内容可能出现替代字符，不适合用此视图分析二进制文件。
- 浏览器最多保留约 **512 KiB 的显示文本**；超过容量时只保留较新的部分。这是查看器的显示上限，**不影响磁盘文件大小**。
- 默认按约 **0.25 秒**的目标周期检查文件变化；实际间隔受磁盘读取、网络、系统负载和浏览器状态影响。
- 长时间无新增内容时不需要持续发送空白日志；有新数据再追加到当前视图。
- 文件被轮转、更换或截断时，读取器会重新定位，并在视图里插入相应提示。它**不会自动逐份拼接** `.1`、`.2` 等历史备份；需要查看旧文件时可通过 Browse 分别打开。
- 所选文件尚未创建时可能显示 **Waiting for file**；会话运行期间如果文件出现，可继续读取。目标 Client 离线或会话失败时，查看器会显示连接或读取状态。

这套机制与 Dashboard、Processes 使用同一个远程 Monitor 能力，但每个视图有自己的会话，不会把日志内容写入 Quick History 或 Activity Center。参见 [Device Monitor](device_monitor.md)。

## 常见使用场景

### 查看 Client 启动和运行消息

1. 选中在线 Client，在 Basic Info 确认存在 **Client Log** 路径。
2. 打开 **Toolbox → Log Viewer**；查看器应自动选择该文件并开启 Streaming。
3. 保持 **Follow** 打开以观察最新消息；要分析旧行时向上滚动，自动跟随会停止。
4. 使用搜索框缩小当前视图范围；需要把已加载内容带走时使用 **Copy**。

若 Client 主日志不可用，不能因为有一个默认路径就推断文件存在；可使用 Browse 选择其他文件，或查看 Client 控制台对日志写入失败的提示。

### 查看 Watchdog 或 External Tools 日志

从对应功能的日志入口打开 Log Viewer，查看器会使用该入口指定的 Client 和文件路径。不要依赖 Toolbox 默认的 Client 主日志来检查 Watchdog 或独立工具进程。部分工具实例尚未生成日志或已停止，查看器可能等待文件或只能显示现有内容。

### 区分“清空视图”和“清空文件”

- **Clear View** 只清空当前浏览器内存中的内容；已经保存到 Client 磁盘的文件仍在。
- **Refresh** 会重新载入当前文件的近期内容，因此刚刚 Clear View 的内容有可能再次出现。
- 真正的文件删除或工具实例日志清理是另一类操作，必须通过相应功能明确执行。清理磁盘文件应使用对应的文件或工具实例管理功能。

## 故障排查与限制

| 现象 | 排查方向 |
| --- | --- |
| 打开后提示选择文件 | 当前 Client 未在线、未上报主日志路径，或入口本来没有指定日志；先确认设备并使用 Browse |
| 一直显示 Waiting for file | 检查远程文件是否已创建、路径是否属于所选 Client，以及该文件是否已经移动或轮转 |
| Stream error / Disconnected | 检查设备连接和浏览器的实时事件连接，再重新打开或 Refresh |
| Streaming 打开但没有新行 | 文件可能暂时没有追加内容；检查 Follow 只影响滚动，不控制采集 |
| 搜索不到较早记录 | 搜索只覆盖已加载的最近内容；可 Browse 选择轮转备份，或在目标设备直接检查完整文件 |
| Copy 范围 | Copy 复制的是已加载文本，搜索仅影响显示；复制前应注意其中可能含敏感信息 |
| 看不到 Server 的 `server.log` | Log Viewer 没有 Server 本地文件来源；在 Server 机器上查看 [Server / Client Logging](logging.md) 中的终端操作 |

日志可能包含执行命令、文件路径、请求和异常详情。向外分享 Copy 的内容前，应先审查并移除密钥、个人信息及其他敏感数据。
