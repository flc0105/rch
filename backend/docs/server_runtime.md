# Server Runtime 目录

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
| `SERVER_RUNTIME_DIR/rch.db` | SQLite 历史、通知等数据 |
| `SERVER_RUNTIME_DIR/web_files/` | Artifact / Shared Files / 上传存储 |
| `SERVER_RUNTIME_DIR/keychains/` | Server 凭据相关文件 |
| `SERVER_RUNTIME_DIR/cleanup_logs/` | 清理日志 |
| `SERVER_RUNTIME_DIR/server.log`、`server.log.1` ～ `.5` | `run_web.py` 的 Server 日志及自动轮转备份 |
| `SERVER_RUNTIME_DIR/logs/` | Go Loader 上报日志 |
| `SERVER_RUNTIME_DIR/agent_output/` | Agent 构建产物及其元数据 |

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
