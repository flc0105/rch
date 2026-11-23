# Server Runtime 目录

### Bind Web URL 公告

在 Server 的环境中设置 `RCH_WEB_ADVERTISED_URL`（例如 `http://192.168.1.10:8085`），用于为主动连接的 Bind Client 公告默认 Server Web API origin。未设置时使用本次 Web 管理请求的 origin 作为默认值。设备栏 More → Connect to Client 自动填入该地址，可在连接前覆盖本次会话的公告值。重连后会再次获取 Server 设置；Reverse Client 保持构建时所配置的 Web URL。

Client 使用 Socket 连接注册阶段接收 `session_config`，独立的 HTTP 请求仍走 Web 服务。若 Client 无法访问该公告地址，需调整 Server 公告值或提供可达的代理/VPN 地址，并重新连接。

## 根目录和配置

Server 所有主要运行时持久数据共用 `backend/server/config/config.py` 中的 **`SERVER_RUNTIME_DIR`**：

```python
# ------------------ runtime ------------------ #
SERVER_RUNTIME_DIR = os.path.abspath(os.path.join(
    BACKEND_DIR,
    os.path.expanduser(os.environ.get('RCH_SERVER_RUNTIME_DIR', '').strip() or 'runtime'),
))
```

默认目录为 **项目固定的 `backend/runtime/`**，并非 Server 的当前工作目录。`BACKEND_DIR` 来自配置文件的实际源码路径，因此从 PyCharm、终端或其他 CWD 启动都指向同一处。

可在**启动 Server 前**设置环境变量 `RCH_SERVER_RUNTIME_DIR` 改变默认路径。绝对路径直接使用，相对路径相对于项目 `backend/` 解析，`~` 展开为用户主目录。例如 macOS/Linux：

```bash
RCH_SERVER_RUNTIME_DIR=/data/rch-runtime python backend/run_web.py
```

也可以直接在上述 `config.py` 的 `SERVER_RUNTIME_DIR` 定义处改默认目录；运行中的 Server 不会自动热更新，修改后需重新启动。

## 共用目录的组成

| 路径 | 用途 |
| --- | --- |
| `SERVER_RUNTIME_DIR/auth.json` | 管理员凭据和 Web Session 密钥 |
| `SERVER_RUNTIME_DIR/rch.db` | 统一 SQLite：历史、通知、Artifact 和 Agent Outputs 元数据 |
| `SERVER_RUNTIME_DIR/web_files/` | Artifact / Shared Files / 上传存储 |
| `SERVER_RUNTIME_DIR/keychains.key` | 解密 Keychains 数据库密文所需的本地密钥；须和 `rch.db` 一起备份 |
| `SERVER_RUNTIME_DIR/cleanup_logs/` | 清理日志 |
| `SERVER_RUNTIME_DIR/server.log`、`server.log.1` ～ `.5` | `run_web.py` 的 Server 日志及自动轮转备份 |
| `SERVER_RUNTIME_DIR/logs/` | Go Loader 上报日志 |
| `SERVER_RUNTIME_DIR/agent_output/` | Agent 构建产物文件（元数据位于 `rch.db`） |

上述位置都由 Server 的配置目录派生，不能再分别由启动 CWD 决定。Client 侧的三个 Watchdog 日志**不在这里**，它们位于客户端用户配置目录的 `logs/` 下，参见 [Watchdog](watchdog.md)。

## 变更和迁移注意

从以前以不同 CWD 启动的项目切换到固定目录时，原有 `runtime/` 可能散落在其他位置。**程序不会自动扫描或迁移旧文件**。更换配置或升级前先停止 Server，确认旧数据库、`auth.json`、文件存储和其他数据的真实位置，按实际需要备份并搬到同一个目标目录，然后启动。尤其避免遗失 `auth.json`，否则新的管理员密码、API Token 和 Session Secret 将在新路径生成，旧登录状态会失效。

## Server 日志

使用 `run_web.py` 启动时，Server 除了继续保留原有的终端日志输出，还会自动写入
`SERVER_RUNTIME_DIR/server.log`。因此 `nohup` 的重定向文件、`launchctl` 的 stdout/stderr
配置均不影响这份 Server 自己维护的日志。文件包括项目 Python Logger、Uvicorn
主日志和 HTTP 访问日志；Werkzeug 等传播到根 Logger 的记录也会写入。不会重新注册
或替换原有的控制台 Handler。

日志按**文件大小**自动轮转：当前文件最大约 **10 MiB**，保留最多 **5** 个旧文件
(`server.log.1` ～ `server.log.5`)。轮转时最新文件仍叫 `server.log`，可以持续跟踪：

```bash
tail -n 100 -F backend/runtime/server.log
```

如果使用 `RCH_SERVER_RUNTIME_DIR` 自定义了 runtime 路径，则对对应路径执行 `tail -F`。
文件必须能由启动 Server 的系统用户写入；无法创建日志时启动会报错，而不是静默跳过。
轮转适用于当前 `run_web.py` 的单进程 Web Server 入口，不要让多个独立 Server 进程
同时轮转同一个文件。直接 `print()`、程序启动早期导入失败的 traceback 和子进程
直接写向 stdout/stderr 的内容不属于 Python Logger，仍依赖原启动方式的标准输出捕获。

## Web Server Maintenance

管理员可在 **Settings → Server → Server Maintenance** 执行当前 Server 的 **Shutdown** 或 **Restart**。两项操作都需要二次确认，并要求当前没有执行中的前台任务、后台 Job 或文件传输；存在活动操作时，接口返回 HTTP 409，停止相应任务后再操作。

- `GET /api/server/maintenance` 返回当前运行实例的 `instance_id`，用于区分重启前后的进程实例。
- `POST /api/server/shutdown` 在确认接受后关闭 HTTP、WebSocket 和 Client Listener，停止心跳、关闭现有 Client 连接，再退出 `run_web.py`。
- `POST /api/server/restart` 先执行同样的清理，然后通过 `os.execv()` 重新运行当前 `run_web.py`。它保留当前进程 PID、启动参数、环境和工作目录，也适用于通过 `nohup python3 run_web.py &` 启动的进程。

这三个接口统一使用管理员 API Token（`Authorization: Bearer <token>`，也可使用 `X-Auth-Token` 或 `X-API-Token`）；浏览器 Settings 会取得当前管理员 API Token 后随维护请求提交。`curl`、rchcli 和其他脚本可直接调用。请求不检查 `Origin`、`Referer` 或 `Sec-Fetch-Site`，管理员 Web Session Cookie 和 Client Session Token 均不能直接授权维护接口。重复发起的生命周期操作返回 HTTP 409。POST 成功表示操作已接受，关闭过程在 HTTP 响应完成后执行。前端 Restart 在新实例返回不同 `instance_id` 后显示成功；超时则提示检查 Server 日志。

使用管理员 API Token 直接调用 Restart（默认 Web 端口为 `8085`）：

```bash
curl -fsS -X POST 'http://127.0.0.1:8085/api/server/restart' \
  -H "Authorization: Bearer ${RCH_ADMIN_API_TOKEN}"
```

将 `RCH_ADMIN_API_TOKEN` 设置为当前管理员 API Token；Shutdown 把 URL 末尾改为 `/api/server/shutdown`。

如果 Restart 后出现 Python 启动错误，新进程可能无法启动；可从 Server 终端日志或 `SERVER_RUNTIME_DIR/server.log` 查看原因并手动运行 `run_web.py`。

## Bind TCP 主动连接

Python Client 采用 Bind TCP 时在本机监听，Server 从设备栏主动发起连接，使用普通 TCP。Agent Build 支持 Python Source Bundle 选择 Reverse / Bind；Bind 需填写 Client 本机监听 IP 和端口，无参数启动生成的 Bundle 时使用构建时选择的模式。One-liners 同样支持这两种构建模式；Bind 只需 Server Web IP/Port（用于 Bootstrap 和 HTTP 请求）及 Client Listen IP/Port，不填写 Server Socket IP/Port。连接后仍由 Client 首先发送 `info`，其余命令、PTY、心跳和文件控制沿用原有 Socket Session。

在 **Client 的 `backend/` 目录**启动：

```bash
python rchclient.py --profile bind
```

`backend/client/config/profiles/bind.json` 默认监听 `0.0.0.0:9443`。可在此文件调整 `bind_host` 与 `bind_port`；`bind_host` 是 Client 监听的本地接口，Server 对应填写 Client 的可访问 IP/主机名和端口。跨设备使用文件、Artifact、Script SDK HTTP 功能时，把同一份 profile 的 `server_web_host` 设置为 Server 在局域网中的地址。

在 **Server 的 `backend/` 目录**正常启动：

```bash
python run_web.py
```

浏览器打开 RCH → 左侧设备栏右上角 **More → Connect to Client** → 填写 Client IP 和端口 → **Connect**。连接成功后自动显示并选中该 Client；重复连接同一地址会复用仍然在线的会话。设备菜单 **Disconnect** 会关闭当前 Bind Session，Client 进程保留监听，可重新从 More 连接。

同一个 Client 实例最多保持一条活动 Server Session。`pause_connection` 暂停接入，恢复后可重新主动连接。固定端口的 `update`、`spawn_instance`、`spawn_elevated_instance`、`relaunch_instance` 继续采用手工进程交接，避免同一端口冲突。Reverse TCP/TLS 仍是默认启动模式。

Bind TCP 当前使用明文 TCP，不执行 TLS 握手。
