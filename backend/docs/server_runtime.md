# Server Runtime 目录

### Bind Web URL 公告

在 Server 的环境中设置 `RCH_WEB_ADVERTISED_URL`（例如 `http://192.168.1.10:8085`），用于为主动连接的 Bind Client 公告默认 Server Web API origin。未设置时使用本次 Web 管理请求的 origin 作为默认值。设备栏 More → Connect to Client 自动填入该地址，可在连接前覆盖本次会话的公告值。重连后会再次获取 Server 设置；Reverse Client 保持构建时所配置的 Web URL。

Client 使用 Socket 连接注册阶段接收 `session_config`，独立的 HTTP 请求仍走 Web 服务。若 Client 无法访问该公告地址，需调整 Server 公告值或提供可达的代理/VPN 地址，并重新连接。

## 根目录和配置

Server 持久数据默认位于项目的 `backend/runtime/`。启动前可设置 `RCH_SERVER_RUNTIME_DIR`；相对路径以 `backend/` 为基准，绝对路径直接使用，支持 `~` 展开。修改后重启 Server。

```bash
RCH_SERVER_RUNTIME_DIR=/data/rch-runtime python backend/run_web.py
```

## 共用目录的组成

| 路径 | 用途 |
| --- | --- |
| `SERVER_RUNTIME_DIR/auth.json` | 管理员凭据和 Web Session 密钥 |
| `SERVER_RUNTIME_DIR/rch.db` | 统一 SQLite：历史、通知、Artifact 和 Agent Outputs 元数据 |
| `SERVER_RUNTIME_DIR/web_files/` | Artifact / Shared Files / 上传存储 |
| `SERVER_RUNTIME_DIR/keychains.key` | 解密 Keychains 数据库密文所需的本地密钥；须和 `rch.db` 一起备份 |
| `SERVER_RUNTIME_DIR/cleanup_logs/` | 清理日志 |
| `SERVER_RUNTIME_DIR/agent_build_tmp/`、`bootstrap_tmp/` | 受管理的构建工作目录、Bootstrap 下载中转 |
| `SERVER_RUNTIME_DIR/server.log`、`server.log.1` ～ `.5` | `run_web.py` 的 Server 日志及自动轮转备份 |
| `SERVER_RUNTIME_DIR/logs/` | Go Loader 上报日志 |
| `SERVER_RUNTIME_DIR/listeners.json` | Reverse Listener 配置 |
| `SERVER_RUNTIME_DIR/identities/` | mTLS 信任根、签发记录及私钥；严格保护 |
| `SERVER_RUNTIME_DIR/agent_output/` | Agent 构建产物文件（元数据位于 `rch.db`） |

上述位置都由 Server 的配置目录派生，不能再分别由启动 CWD 决定。Client 侧的三个 Watchdog 日志**不在这里**，它们位于客户端用户配置目录的 `logs/` 下，参见 [Watchdog](watchdog.md)。

## 备份与目录变更

变更 Runtime 目录前停止 Server，备份数据库、凭据、Identity、文件及配置，再按需复制到目标位置。管理员认证、Keychains 和 mTLS 身份材料需要和对应数据一起保存；使用空目录会初始化新的运行数据。

## Server 日志

使用 `run_web.py` 启动时，Server 除了继续保留原有的终端日志输出，还会自动写入
`SERVER_RUNTIME_DIR/server.log`。因此 `nohup` 的重定向文件、`launchctl` 的 stdout/stderr
配置均不影响这份 Server 自己维护的日志。文件包括项目 Python Logger、WebSocket 与 HTTP 访问日志；Werkzeug 等传播到根 Logger 的记录也会写入。不会重新注册
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

Settings → Maintenance 提供 [Server Cleanup 和 Optimize Database](cleanup.md)，用于清理符合条件的本机残留及回收 SQLite 空闲页。每个 Runtime 应由单个 Server 实例独占。

## Bind 主动连接

Python 和 Go Client 均支持 Bind；Server 主动拨号至 Client 的监听 IP 和端口。Agent Builder 选择 Bind 与 TCP 或 mTLS/TCP，使用 mTLS 前按 [mTLS Identities](mtls_identities.md) 初始化和安装身份材料。

源码 Python Client 可在 Client 的 `backend/` 目录启动：

```bash
python rchclient.py --profile bind
```

Bind Profile 默认监听 `0.0.0.0:9443`；`bind_host` 和 `bind_port` 对应 Client 本机接口和端口。启动 Server Web 后，从设备栏 **More → Connect to Client** 填写可达的 Client 地址、端口、传输方式和 Server Web URL。该 URL 必须可由 Client 访问，用于 HTTP 文件和 SDK 请求。成功连接后目标可保存；设备菜单提供 Disconnect、Reconnect、Connect 及 Remove Connection 等相应操作。详见 [Connection Lifecycle](connection_lifecycle.md)。
