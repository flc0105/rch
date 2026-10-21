# Administrator Authentication

Server 对受保护 Web API 建立统一的管理员身份边界：浏览器依靠经签名的 Session Cookie，外部 HTTP 客户端使用管理员 API Token；由 Server 授权运行的 Script 和 Client 命令可以在限定范围内使用临时 Grant。三类凭据的来源、可达接口和失效条件不同，但最终由同一请求守卫判断是否放行。

管理员凭据的持久根默认是项目固定的 `backend/runtime/auth.json`（通过 `SERVER_RUNTIME_DIR` 配置）。启动过程决定它何时生成、何时装载；运行中的认证中间件依靠已加载的凭据判断请求，因此理解文件、进程和 Cookie 之间的关系比单独记住某个启动参数更重要。

## 凭据根与服务初始化

Server 加载配置时会先读取 `runtime/auth.json`。文件不存在时，系统仅在首次初始化时生成一套凭据：管理员用户名默认为 `admin`，密码通过安全随机数生成；同时生成独立的 `api_token` 和 `session_secret`。密码使用带随机盐的 `scrypt:32768:8:1` 哈希保存，磁盘上不会写入首次生成的明文密码。

新建文件使用原子发布方式，避免并发启动写出半截配置；在支持相应文件权限的系统上，文件被设置为仅属主可读写的 `0600`。已存在的配置也会检查文件类型并收紧权限。

首次创建后，启动输出会打印：

```text
[RCH] Initial administrator username: admin
[RCH] Initial administrator password: <random-password>
```

`<random-password>` 代表实际生成的密码。**这条明文只在首次创建时输出**。普通重启不再次打印；如果输出被重定向到日志，密码也可能保留在相应日志中。首次登录后应妥善保存密码，并控制启动日志的访问权限。

`auth.json` 始终采用严格的四字段结构：

| 字段 | 含义 |
|---|---|
| `username` | 管理员登录名，首次默认 `admin` |
| `password` | scrypt 密码哈希；启动时临时允许 `plain:...` 以改写密码 |
| `api_token` | 长期管理员 API Token，供非浏览器 HTTP 客户端使用 |
| `session_secret` | Flask Session 签名密钥，也用于计算登录凭据的有效性标识 |

文件不接受字段缺失、多余字段、空字符串、短 Token 或无效密码哈希。`api_token` 与 `session_secret` 至少需要 32 个字符；不合格的现有文件会导致启动失败，**不会为了方便而静默重置**。用户名、API Token 和 Session Secret 都是敏感配置，不能公开提交到仓库。

### 服务入口与运行参数

Web 服务的入口是 `run_web.py`。默认的 `runtime/auth.json` 与 `runtime/rch.db` **固定相对于项目 `backend/`**，不受启动 CWD 影响；在项目目录下启动只是常见用法：

```bash
cd backend
python run_web.py
```

该入口启动 Server Socket、心跳、Web 服务和独立文件传输服务。默认 Socket 端口为 `9999`，Web/API 端口为 `8085`，文件传输端口自动使用 Web 端口加一，即默认 `8086`。只运行 `rchserver.py` 则启动 Socket Server 和控制台，不会启动同一套 Web 登录页面；它仍会在加载 Server 配置时初始化管理员凭据。

运行时确实读取以下相关环境变量：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `RCH_WEB_PORT` | `8085` | Web/API 监听端口，同时决定文件传输端口 `+1` |
| `RCH_SOCKET_PORT` | `9999` | Client Socket 监听端口 |
| `RCH_SERVER_RUNTIME_DIR` | `backend/runtime`（项目固定路径） | Server 所有持久 runtime 数据的根目录；绝对路径或相对于 `backend/` 的路径 |
| `RCH_WEB_AUTH_SESSION_DAYS` | `7` | 浏览器持久 Session 的有效天数 |
| `RCH_WEB_SESSION_COOKIE_NAME` | `rch_admin_session` | Session Cookie 名称 |

例如需要更改 Web 端口、Session 天数和 Cookie 名称，可以在启动前设置环境：

```bash
cd backend
RCH_WEB_PORT=9000 RCH_WEB_AUTH_SESSION_DAYS=14 \
RCH_WEB_SESSION_COOKIE_NAME=rch_admin_session python run_web.py
```

上面是 POSIX Shell 的设置方式；Windows PowerShell 可先设置 `$env:RCH_WEB_PORT = '9000'` 等变量，再运行 `python run_web.py`。由于环境变量是在模块导入时读取的，改变它们需要重启 Server。Web Host 当前固定为 `0.0.0.0`，不能通过上述变量改为仅本地监听。

**管理员身份凭据从 `auth.json` 加载，不从启动环境读取或覆盖。** 启动环境仅配置上表列出的监听与 Web Session 运行选项。需要修改管理员密码或轮换 API Token 时，应编辑受保护的凭据文件并重启 Server；Desktop Notifier 通过自己的 `RCH_NOTIFIER_TOKEN` 读取连接 Token，不会改变 Server 的认证配置。

### 密码与密钥的维护

#### 管理员密码的原子改写

停止 Server 后，编辑 `SERVER_RUNTIME_DIR/auth.json`（默认 `backend/runtime/auth.json`），**保留其他三个字段**，仅将 `password` 改为：

```text
"password": "plain:your-new-password"
```

这只是 JSON 对象内一个字段的写法，不是要把整个文件替换成上述一行。保存并重新启动后，Server 会将 `plain:` 后的明文转为新的加盐 scrypt 哈希，原子写回同一文件，并清除明文形式。`plain:` 后必须有非空密码；不允许直接填写不带 `plain:` 的明文。

修改密码并重启后，以前的管理员登录 Session 会因为凭据版本不同而失效，需要重新登录。**API Token 与 Session Secret 保持不变**，使用旧 Token 的脚本、curl 或 Desktop Notifier 不受这次密码改写影响。两类凭据分别轮换，不需要一起重置。

#### 长期凭据与签名密钥的轮换

如需更换长期 API Token，应停机后仅替换 `api_token` 字段，保持 `username`、有效的 `password` 哈希和 `session_secret` 不变。可以使用 Python 标准库生成足够长的新随机值：

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

把输出放入 `auth.json` 的 `api_token`，重新启动后才会生效。旧 Token 随即失效；使用该 Token 的外部程序必须更新配置。Server **不会在首次启动日志中打印 API Token**，也没有从环境变量直接轮换管理员 Token 的功能。

单独轮换 `session_secret` 时，可用 `secrets.token_urlsafe(48)` 生成新值。这会使此前签发的 Session Cookie 无法继续通过签名验证，所有浏览器必须重新登录；管理员密码和 API Token 不随之改变。管理员用户名也可在停止服务后直接编辑 `auth.json`，但不会由某个 `RCH_ADMIN_USERNAME` 环境变量覆盖。

#### 重新初始化凭据根

停止 Server，安全备份或移走 `SERVER_RUNTIME_DIR/auth.json`（默认 `backend/runtime/auth.json`），随后重启；Server 因找不到该文件而生成新的随机密码、API Token 和 Session Secret，并再次输出新的初始登录信息。此前的登录 Session 和所有使用旧 API Token 的外部客户端都需要更新。不要在 Server 运行时删除、修改凭据文件并期待内存中的认证配置立即刷新：认证值在配置导入时加载，必须重新启动才能应用。

`auth.json` 的位置由 `backend/server/config/config.py` 中的 `SERVER_RUNTIME_DIR` 统一计算，默认 `backend/runtime/`，**不会随着启动工作目录变化**。修改位置就在该文件 `# ------------------ runtime ------------------ #` 章节。启动前可用环境变量 `RCH_SERVER_RUNTIME_DIR` 设置新根目录；绝对路径原样使用，相对路径相对于 `backend/` 解析。该配置与 Client 侧的 `RUNTIME_CONFIG_PATH` 无关。更换根目录不会搬迁旧目录的数据：必须先停机，将原 `auth.json`、`rch.db`、`web_files/` 等所需内容一并搬迁或备份再启动，否则新位置会初始化另一套数据与凭据。

## Web 请求的认证决策

### 浏览器会话与 Cookie

用户通过 `/login.html` 输入管理员用户名和密码。登录页对密码做简单的可逆 XOR 掩码后提交到原有登录接口；不发送明文 `password` 字段，也不需要额外的 challenge 请求：

```http
POST /api/auth/login
Content-Type: application/json
```

```json
{
  "username": "admin",
  "masked_password": "<base64-masked-utf8-password>",
  "mask_nonce": "<base64-random-16-bytes>"
}
```

Server 还原密码并继续使用原有的 scrypt 哈希校验，`auth.json` 不变。凭据错误返回 `401`，数据无效返回 `400`，前端单独提示网络异常与服务错误。旧的复杂 challenge/RSA/AES 流程已移除。

**安全边界：**这种轻量掩码只避免 Network 请求体直接出现可读密码。其算法和固定掩码材料都能从网页源码取得，因此 **不具有抵御抓包或中间人攻击的保密性**。项目不因此强制 HTTPS，也不改变 HTTP 的可用性。

Session 主要由以下两个接口管理：`GET /api/auth/session` 可检测当前是否已认证；`POST /api/auth/logout` 清除当前会话。`/api/auth/session` 本身允许匿名请求，未认证时返回 `authenticated: false`，而不是把它视为一个必须登录才能访问的页面。Web 首页在未认证时跳转登录页，受保护的 `/api/` 请求失败则返回 `401`；前端收到该状态会引导用户重新登录。

当前 Session 是 Flask Cookie Session：Cookie 默认名为 `rch_admin_session`，默认有效期七天，设置了 `HttpOnly` 和 `SameSite=Lax`，并用 `session_secret` 签名。它不是数据库中可逐条管理的 Session 记录，Logout 清除的是当前浏览器会话。每个 Session 还绑定基于当前用户名、密码哈希和 Session Secret 计算的凭据标识，因此修改密码并重启后，旧 Cookie 即使仍在有效期内也会被拒绝。

当前配置没有显式设置 `SESSION_COOKIE_SECURE=True`；如果管理界面暴露到网络，应在可信的 HTTPS 反向代理和 Cookie/会话安全策略下部署。`SameSite=Lax` 不应被解释为所有修改类请求都具备独立的 CSRF 防护。

### 外部 HTTP 客户端的凭据

`api_token` 是独立于登录密码的长期静态凭据。认证守卫支持以下三种提交方式：

```http
Authorization: Bearer <API_TOKEN>
X-Auth-Token: <API_TOKEN>
X-API-Token: <API_TOKEN>
```

`Authorization` 还支持直接填写 Token，推荐使用标准的 `Bearer` 格式。Token 采用常量时间比较。如果 `Authorization` 请求头已提供值，会优先解析该值，不会因它校验失败而回退到另外两个 Token 头。有效的静态 Token 可以通过与 Session 相同的受保护 Web API。**它是完整的管理员 API 凭据，不是仅用于读取通知的低权限 Token。**

例如用 curl 查询通知偏好，可以在终端交互读取 Token，避免把真实秘密直接放进命令历史：

```bash
read -r -s -p 'RCH API Token: ' RCH_API_TOKEN; echo
curl --fail-with-body \
  -H "Authorization: Bearer ${RCH_API_TOKEN}" \
  'http://127.0.0.1:8085/api/notifications/preferences'
unset RCH_API_TOKEN
```

`RCH_API_TOKEN` 在这里只是示例 Shell 变量名称，**不是 Server 读取的配置环境变量**。默认服务地址是 8085；若前面修改了 Web 端口，应同步调整 URL。实际部署中也应使用 HTTPS，避免 Token 在网络上明文传输。

Desktop Notifier 是这个 Token 的实际使用场景。Notifier 会携带相同的 `Authorization: Bearer ...` 访问 `/api/notifications/stream`，并支持在其独立的 `config.json` 配置 `token`，或通过 **Notifier 进程自己的** `RCH_NOTIFIER_TOKEN` 环境变量注入。该环境变量不会生成或修改 RCH Server 的 `auth.json`。Notifier 虽然只读取通知流，但使用的仍是管理员 Token，配置文件的保存权限应按管理员凭据处理。

需要注意普通 API 认证与文件传输、PTY/Screen WebSocket 的专用访问 Token 是不同机制。当前部分路由明确用 `@allow_anonymous` 跳过通用认证守卫，8086 专用文件传输服务也不是这个 Flask WebAuthGuard 的完整镜像；因此不能据此声称 **所有** HTTP、Socket 或 WebSocket 通道都由管理员 API Token 统一保护。

## 委托给执行任务的临时权限

Script Grant 让当前 Client 上运行的 Script 或受支持的 Client 命令，在需要访问受保护的 Server API 时，获得临时且限定范围的权限，而不是把 `auth.json` 里的长期 API Token 复制到设备。Server 为每个授权任务生成随机 Grant Token，仅保存它的 SHA-256 哈希，并把授权与 `client_id`、`command_id` 以及来源名称关联。

普通 Script 在顶部的 `SCRIPT_METADATA` 中声明所需 Scope，例如：

```python
SCRIPT_METADATA = {
    "display_name": "API Reader",
    "params": [],
    "api_grants": ["artifacts:list"],
}

from client.http.client_api import ClientApiClient

artifacts = ClientApiClient().get_data('/api/artifacts')
print(artifacts)
```

这是说明声明与调用关系的最小示例，不属于项目已有实例清单。通过 Web Script 运行入口启动时，Server 从受信任的 Script Catalog Metadata 构建授权请求，在下发执行命令时签发 Grant；Client 将 Grant 放进 Script SDK 上下文。`ClientApiClient` 在访问自己配置的 Server Web API 基地址时自动附加 `X-Script-Grant-Token`，不要求开发者手工输入管理员 Token。

普通 Client 命令则可以通过已有的 `@desc` 注解声明权限，例如 `@desc('...', api_grants=('interactions:request',))`；Server 根据受信任的命令方法定义签发 Grant。该机制只针对明确声明了 Grant 的命令或脚本，并非所有 Shell-like 命令都会获得授权。直接在终端运行普通 Shell 命令，也不能凭一段自报的 Metadata 自行向 Server 申请管理员权限。

Grant 的默认生命周期如下：

| 约束 | 当前行为 |
|---|---|
| 生存时间 | 默认最多 300 秒，申请更大值会被限制至上限 |
| 使用次数 | 默认最多 100 次成功匹配并授权的请求 |
| 请求提交 | 专用 `X-Script-Grant-Token` 请求头 |
| Scope | 仅允许 Server Policy 中明确列出的 HTTP Method + Path |
| 清理 | 到期、用尽、对应命令完成或目标 Client 断开后失效 |
| 存储 | Server 内存，不持久化到 `auth.json` 或 SQLite |

例如 `artifacts:list` 只允许匹配 `GET /api/artifacts`；`interactions:request` 匹配交互请求端点。当前还支持脚本读取、Artifact 读取/下载、Keychain 及部分工作区查询等明确映射的 Scope。完整的实际允许路由以现行 `ScriptGrantPolicy` 为准，不应自行拼造 Scope 名称。未知 Scope 在签发时会被丢弃，若最后没有有效 Scope，就不会签发 Grant。

它是**Method/URL 级**权限判断，不是全面的资源级 RBAC。例如具有某个 Artifact 下载路径 Scope，并不意味着 Grant Service 还会根据 Artifact 类型、归属或敏感程度作独立的细粒度授权。同样，Grant 的 `client_id` 和 `command_id` 主要用于签发时绑定、任务回收，以及 Interaction Broker 等需要任务身份的专用校验；普通 Scope 授权函数本身基于 Token、Method、Path、到期时间和使用次数判断。

只有真正走过 Grant 签发流程的 Script 才有该上下文。`context.get_script_grant_token()` 可以读取当前临时 Token，但不要打印、记录到日志或转发到其他主机；SDK 的自动请求头处理只面向配置中的 Server Web API 基地址，不代表对任意 URL、独立 8086 通道也自动授予权限。对于 Interaction Broker 的用户确认和输入类型，参阅独立的 Interaction Broker 与 Script SDK 文档。

## 访问控制与运维安全

除 OPTIONS、静态资源和标注为 `@allow_anonymous` 的端点以外，Web 请求按以下条件放行：**有效管理员 API Token、有效 Session、有效 Script Grant**，三者满足任何一项即可。没有认证的 API 调用返回 `401`，非 API 页面则跳转 `/login.html`。Script Grant 只覆盖在 Policy 中能匹配的请求；它不能取代整个管理界面的管理员登录。

遇到登录或 API 访问失败时，优先按下面的实际边界判断：

| 现象 | 检查方向 |
|---|---|
| 首次启动不知道密码 | 检查首次启动标准输出及受保护日志；之后不会再次打印旧密码 |
| 重启后密码好像变了 | 检查 `RCH_SERVER_RUNTIME_DIR` 是否变化，以及实际读取的 `SERVER_RUNTIME_DIR/auth.json` 是否与上次相同 |
| 修改了 `plain:` 但仍无法登录 | 确认 JSON 完整有效、Server 已重启、登录名与新密码匹配 |
| 修改环境变量后登录凭据未改变 | 管理员身份凭据由 `runtime/auth.json` 装载，运行时环境变量只负责受支持的服务配置 |
| 修改密码后浏览器被退出 | 旧 Session 绑定的凭据标识已失效，属于预期行为 |
| 修改密码后 curl 仍可使用原 Token | 密码轮换不会修改独立的 `api_token` |
| Desktop Notifier 提示 401 | 检查当前 Server API Token、Notifier 配置和 URL，而不是 Session Cookie |
| Script API 调用提示未认证 | 检查是否由受支持的运行入口签发 Grant、Scope 是否匹配、是否超时/用尽 |
| 已经输入正确密码却不能连接 | 检查 Server 的工作目录、启动报错、Web 端口与 HTTPS 反向代理配置 |

安全上还需区分三种轮换：改密码会影响 Web 登录及旧 Session；改 `api_token` 会影响 curl、Notifier 和其他外部 API 客户端；改 `session_secret` 会使现有签名 Cookie 失效。删除整个文件会同时重置全部三种凭据。上述操作均应在受控停机、备份和重启过程中完成，避免多实例使用不同的凭据文件。

`RCH_HIDDEN_DEVICES_REQUIRE_PASSWORD` 和 `RCH_HIDDEN_DEVICES_PASSWORD` 是隐藏设备访问相关的独立配置，**不是 Web 管理员用户名/密码**。也不要把网络端口可访问、上传接口未设相同守卫，或 Script Grant 能访问某条路由，等同于整个 Server 已实施统一的细粒度访问控制。公网部署前，应结合代理、TLS、网络隔离及独立通道的访问控制一起审查。
