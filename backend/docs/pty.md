# PTY Sessions

PTY 把远程 Shell 作为持续存在的伪终端会话运行。Client 持有真实终端进程与双向字节流，Server 维护会话路由和客户端连接，浏览器以 xterm.js 展示终端并发送键盘输入与 Resize。其输出不是一次普通 Command 结束后返回的字符串，而是伴随会话持续流动的数据。

交互程序依赖终端尺寸和控制字符，因此输入、输出、关闭和断线恢复必须与普通 Shell-like 执行分开处理。Unix PTY 与 Windows ConPTY 在系统 API 上不同，却服从统一的会话控制契约。

## 持久终端会话的端到端链路

PTY 的通信由三个部分组成：

```text
Frontend（浏览器 / xterm.js）
  终端显示、键盘输入、Shell 切换、窗口尺寸适配
                   ↕ WebSocket / HTTP
Server（PTY 会话中转）
  会话创建、状态维护、输出缓存、输入与尺寸转发
                   ↕ Client 已建立的消息连接
Client（远程设备）
  Unix PTY / Windows ConPTY、交互式 Shell、输入输出读写
```

用户在设备工具栏打开 **PTY** 后，会依次发生以下操作：

1. 浏览器向 Server 提交创建请求，包含目标 `client_id`、终端行列数和可选 Shell。
2. Server 生成独立的 `pty_session_id` 和 WebSocket 令牌，记录 `opening` 状态，向对应 Client 发送 `pty_open`。
3. Client 根据操作系统创建 PTY，启动交互式 Shell。启动成功后返回 `pty_opened`；失败则返回 `pty_error`。
4. Server 将会话更新为 `open`，浏览器通过 WebSocket 接收状态和终端输出。键盘输入沿相反方向转发到 Client。
5. 用户调整窗口、切换 Shell 或结束会话时，浏览器分别发送尺寸更新或关闭请求，Client 同步调整或释放终端资源。

**HTTP 创建请求成功不等于 Shell 已经成功运行。** 刚创建时返回的通常是 `opening`，只有 Client 真正启动终端并回报 `pty_opened` 后才是 `open`。WebSocket 已连接也仅说明浏览器与 Server 之间的传输通道可用，不能代替远端启动成功的确认。

Server 使用会话 ID 分别管理不同的 PTY，并没有对每个 Client 强制只允许一个会话的限制，因此可以存在多个互相独立的终端会话。每个会话分别拥有 Shell、终端尺寸、输出序列号和生命周期状态。

## 不同平台的伪终端后端

两种实现向浏览器提供相同的终端体验，但创建进程和读写终端的系统接口不同。

| | Unix（Linux / macOS 等） | Windows |
|---|---|---|
| 终端机制 | 系统 PTY、`forkpty()` | Windows ConPTY |
| 运行依赖 | 系统 PTY 与 Python 标准库 | `pywinpty >= 3.0.5`，使用 ConPTY |
| 默认 Shell | `$SHELL` → `/bin/zsh` → `/bin/bash` | `cmd.exe` → `pwsh.exe` → `powershell.exe` |
| 输入输出 | PTY Master 文件描述符 | ConPTY 的读写接口 |
| 尺寸更新 | `TIOCSWINSZ` | `set_size()` |

### Unix 伪终端分配

Unix 通过 `forkpty()` 创建子进程及与其关联的伪终端。子进程运行选定的 Shell，并使用 `-i` 参数进入交互模式；父侧保留 PTY Master，用它发送输入、接收输出。Shell 继承 Client 的环境变量，如果缺少相关设置则补充 `TERM=xterm-256color` 和 `COLORTERM=truecolor`，以支持常见的终端颜色与控制序列。

未指定 Shell 时，按 `$SHELL`、`/bin/zsh`、`/bin/bash` 的顺序寻找存在且可执行的程序；明确指定 Shell 时，会校验路径或从 `PATH` 解析可执行文件。创建过程中还会确认 Shell 确实执行成功，然后再返回 `opened`，避免将启动失败误判为成功。

Shell 输出由独立读取线程从 PTY Master 获取；线程使用 `select()` 等待可读数据，每次最多读取 4096 字节。用户关闭会话时，Client 向 Shell 进程发送 `SIGTERM` 并清理 PTY；Shell 自然退出时，Client 则尝试回收进程并取得实际退出状态。

可指定 `cwd` 作为启动目录，但 Unix 侧对目录切换异常采取忽略处理：指定目录无效时，Shell 可能仍在继承的工作目录启动，而不是直接报错。

### Windows ConPTY 会话

Windows 统一使用 ConPTY，不保留 WinPTY 备用实现。需要安装支持 ConPTY 的 `pywinpty`，版本不得低于 **3.0.5**；缺少依赖或版本不符时，Client 会报告启动错误。

默认优先使用 `cmd.exe`，然后才考虑 `pwsh.exe` 和 `powershell.exe`；自定义 Shell 可以包含可执行程序及参数。创建时会解析可执行文件，使用 ConPTY 启动进程。如果指定的 `cwd` 不是有效目录，会忽略该目录并采用默认工作目录。

为使新终端正确处理 Ctrl+C，创建过程会临时调整控制台 Ctrl+C 的处理状态，并在创建后立即恢复 Client 原有设置。运行过程中通过 ConPTY 的接口读写终端；读取采用非阻塞方式，Shell 退出后还会尝试读取剩余内容，减少最后一批输出丢失。

当前 iOS 不支持 PTY，创建请求会返回对应错误。

## 字节流、按键与终端尺寸

### 双向输出流

PTY 是连续双向数据流，输入不是“提交一条完整命令后等待结果”。用户输入的文字、Enter、方向键、Ctrl+C 等按键及其控制序列，都由 xterm.js 组织成终端输入。前端将短时间内的输入约每 **10 毫秒**合并一次，用 UTF-8 编码并转换为 Base64，再通过 WebSocket 发送：

```json
{"type":"input","data":"bHMNCg=="}
```

例子中的 `data` 表示 `ls\r\n` 的 Base64 编码。Server 不解释用户输入的 Shell 命令内容，而是将数据转发给对应 Client；Client 解码后写入 PTY。Unix 侧写入原始字节，Windows ConPTY 侧把 UTF-8 数据转换为文本后写入终端。

远程 Shell 产生输出时，Client 从 PTY 读取数据，以 Base64 形式送至 Server。Server 将内容解码成 UTF-8 文本，给每个输出片段分配递增的 `seq`，再通过 WebSocket 推送到浏览器。例如：

```json
{
  "type": "output",
  "status": "open",
  "seq": 2,
  "chunks": [
    {"seq": 1, "text": "hello\r\n"},
    {"seq": 2, "text": "$ "}
  ]
}
```

浏览器把 `chunks` 写入 xterm.js，由其处理 ANSI 控制序列、颜色、光标移动和 `vim`、`top` 等全屏界面。Server 并不将每次键盘输入当成独立任务，也不负责解释这些终端控制序列。

有两个缓冲边界需要区分：Server 每个会话仅保留最近 **500 个输出片段**，用于向浏览器提供当前窗口内的增量输出；xterm.js 的滚动缓冲区为 **5000 行**。两者不相等，也都不是永久的终端日志。长时间大量输出时，早期内容可能不再能从 Server 重新取得。

Server 对每个输出片段分别进行 UTF-8 解码，并在异常字节时采用替换字符。因此，若一个多字节字符恰好被拆在两个片段之间，个别字符可能显示异常；这不意味着 Shell 本身执行失败。

### 终端大小变化

打开终端时，前端通过 xterm.js 的 FitAddon 计算当前容器能容纳的列数和行数，随后随创建请求传给 Server。若直接使用 HTTP API 而未指定尺寸，则采用 **120 列 × 32 行**。Server 和 Client 对尺寸设置下限：**至少 20 列、5 行**。

浏览器窗口变化时，前端会等待约 **80 毫秒**再发送尺寸更新，避免连续调整过程中产生过多消息：

```json
{"type":"resize","cols":120,"rows":32}
```

Client 收到后调用对应平台的 PTY 尺寸调整接口，使远端的行列信息与实际预览空间保持一致。这一点对 `vim`、`top` 等依赖终端尺寸的程序尤其重要。尺寸已与上次发送值一致时，前端不会重复提交。

## 浏览器终端状态管理

从已选中设备的工具栏打开 **PTY**，会出现 **Remote PTY** 窗口。窗口包含设备标识、会话状态、错误提示、Shell 输入框、Switch、Focus 和 Close 按钮，以及 xterm.js 终端显示区域。终端支持 ANSI 控制序列、粘贴、可滚动输出和自动适配尺寸。

默认情况下无需填写 Shell，系统会根据远端操作系统自动选择。需要指定时，可以在 Shell 输入框填写 `zsh`、`bash`、`/bin/bash`、`cmd.exe` 或 `powershell.exe` 等；输入 `default` 与留空等价，表示使用平台默认 Shell。

例如，在 Unix 设备的 Shell 输入框填入：

```text
/bin/bash
```

再点击 **Switch**，系统将关闭当前 PTY，等待其变成 `closed` 或 `error`，之后再按新 Shell 创建一个会话。等待旧会话结束的时间上限约为 **5 秒**。这个操作是**切换到全新的终端进程**，不是在原 Shell 中执行一条 `bash` 命令；旧会话的工作状态、正在运行的前台程序和当前环境不会被继承。若旧会话未能及时结束，切换会报错，不应视为已成功创建新终端。

**Focus** 用于把键盘焦点重新放到终端中，适合用户点过其他输入框后继续操作。**Close** 会关闭远程会话，而不只是隐藏弹窗：前端会请求 Server 终止对应 PTY，同时清理 WebSocket、输入队列和终端组件。Shell 及其中正在运行的程序会受到关闭操作影响。

创建会话的 HTTP API 另支持 `cwd`（工作目录）参数，但当前界面没有单独提供该参数的输入框。需要通过 API 指定时，可以将它与 Shell 和行列数一起提交；目录是否成功应用取决于远端操作系统及实际目录是否存在。

## 控制面与实时传输协议

HTTP 主要负责创建、查询和管理会话；WebSocket 负责低延迟的终端输出及实时输入。两类通道都由 Server 转接，远端 Client 不需要向浏览器开放 PTY 监听端口。

| 方法 | 接口 | 作用 |
|---|---|---|
| POST | `/api/connections/{client_id}/pty/open` | 创建会话，发送 `pty_open` |
| GET | `/api/pty/{pty_session_id}/poll` | 查询状态、尺寸和 `after_seq` 之后的输出 |
| POST | `/api/pty/{pty_session_id}/input` | 发送 Base64 编码的输入数据 |
| POST | `/api/pty/{pty_session_id}/resize` | 更新终端行列数 |
| POST | `/api/pty/{pty_session_id}/close` | 请求关闭终端 |

创建请求的 JSON 参数如下：

```json
{
  "cols": 120,
  "rows": 32,
  "shell": "/bin/bash",
  "cwd": "/tmp"
}
```

示例针对具有 `/bin/bash` 和 `/tmp` 的 Unix 设备。`shell` 和 `cwd` 可省略或留空；Windows 上应使用相应的 Shell 和目录。Server 创建会话后，在响应 `data` 中返回 `pty_session_id`、`status`、`cols`、`rows`、`ws_token` 和 `ws_path`。其中 `status` 一开始通常为 `opening`。

浏览器用返回的路径建立 WebSocket：

```text
/ws/pty/{pty_session_id}?token={ws_token}
```

WebSocket 使用与会话绑定的随机 Token 授权。HTTP 接口则要求通过 Web 服务的正常鉴权。`ws_token` 相当于该终端会话的访问凭据，不应放进公开日志或分享给未授权方。

连接建立后，浏览器以 JSON 发送 `input`、`resize`、`close` 消息；Server 返回 `output` 和 `status`，其中可能包含 `chunks`、`seq`、`shell` 和 `error`。Server 约每 **50 毫秒**检查一次新输出及状态变化，在终态时发送最终状态并关闭发送循环。

`poll` 接口支持 `after_seq` 参数，用来只取得指定序列号之后的缓存输出，例如：

```http
GET /api/pty/{pty_session_id}/poll?after_seq=20
```

这表示请求序列号大于 20 的剩余缓存输出，**不是回放完整历史**。当前 Web 界面使用 HTTP Poll 辅助确认 Shell 名称和关闭状态，实时交互仍主要依赖 WebSocket；没有实现 WebSocket 断开后自动切换 HTTP 长轮询并保持完整交互的回退模式。

## 关闭、断线和进程回收

PTY 的会话状态如下：

| 状态 | 含义 |
|---|---|
| `opening` | Server 已发出创建请求，等待远端启动 |
| `open` | Client 已确认 Shell 启动成功 |
| `closing` | Server 已请求关闭，等待终止或清理 |
| `closed` | Client 已报告关闭，或 Server 已确认 Client 断开 |
| `error` | Shell 创建或运行出错，错误信息可供界面显示 |

远端 Shell 正常退出后，Client 发送 `pty_closed`，并尽可能携带退出码。Unix 的自然退出通常能取得真实退出状态；若由用户主动关闭，Unix 路径返回的可能只是默认值 `0`，不能据此推断原程序正常完成。Windows 会尝试取得 ConPTY 提供的进程退出状态。

关闭窗口或切换 Shell 时，会发送关闭请求，Client 释放会话和终端句柄。**浏览器 WebSocket 意外断开后，Server 也会请求关闭该 PTY**，所以不能把它当作 `tmux` / `screen` 那样可断线保留并重连的持久终端。若需要长期执行、并在断线后继续工作的交互任务，应由远程 Shell 内的专门会话管理工具自行承担。

当 Client 与 Server 的连接断开，Server 会将相关活动 PTY 会话标记为关闭并安排清理；Client 在连接运行态结束时也会关闭其管理的 PTY。已关闭、错误或进入关闭流程的会话由延迟清理机制处理，保留时间为 **300 秒**；这用于短时间内读取最后的状态，不代表 Shell 仍在运行。

PTY 生命周期还会产生通知事件，界面可收到 `pty_opened`、`pty_closed` 和 `pty_error` 对应的启动、停止和错误提示。

## 交互式远程执行的运行边界

| 现象 | 可能原因与处理方式 |
|---|---|
| 长时间停留在 `opening` | 连接请求已创建，但远端尚未确认 Shell 启动。检查 Client 是否在线、Shell 是否存在、操作系统是否支持所选 PTY。WebSocket 已连通不代表 Shell 已启动。 |
| Windows 提示 ConPTY 不可用 | 确认系统支持 ConPTY、`pywinpty` 已安装且版本至少为 3.0.5。当前没有 WinPTY 回退。 |
| 切换 Shell 后终端为空或报错 | 检查 Shell 名称与可执行路径。Switch 会先结束旧会话再创建新会话；若旧会话超过关闭等待时间，切换可能失败。 |
| 命令能执行，但个别字符显示异常 | 检查远端程序输出编码和终端环境；Server 按输出片段分别进行 UTF-8 解码，跨片段的多字节字符可能被替换。 |
| 调整窗口后全屏程序排版异常 | 确认 WebSocket 仍连接、尺寸更新能够传到 Client，并检查终端行列数是否达到最小限制。 |
| WebSocket 断开后原会话无法恢复 | 当前设计会在 WebSocket 结束时请求关闭 PTY，不支持重新附着到原 Shell；需重新打开会话。 |
| 大量输出之后，早期内容消失 | Server 仅缓存最近 500 个输出块；浏览器另有 5000 行滚动缓冲，这两项都不能作为完整历史记录。 |
| Close 后仍发现相关后台子进程 | 当前关闭重点针对 Shell 和关联 PTY，不保证递归终止 Shell 曾启动的全部后台子进程。 |

PTY 的 Shell 以 **Client 进程现有的系统权限**运行，不会额外创建受限沙箱。Web 管理权限能够访问 PTY 的用户，实质上就能够在远端设备以 Client 权限执行交互式系统命令，应按远程命令执行能力管理授权。

需要保留的能力边界是：PTY 是实时交互终端，不是一次性命令接口、持久会话管理器或永久日志系统；它不占用前台命令槽，但仍依赖当前 Client 连接与浏览器 WebSocket。退出码、断线恢复及后台子进程清理都应按上述实际行为判断，不能默认具备额外保证。
