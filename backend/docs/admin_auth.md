# Administrator Authentication

Server 的 Web 管理员使用经签名的 Session Cookie 或管理员 API Token；已连接的 Client 使用 Client Session Token 访问专门开放的 Client API。两种身份由同一请求守卫识别，Client API 白名单独立维护。

管理员凭据的持久根默认是项目固定的 `backend/runtime/auth.json`（通过 `SERVER_RUNTIME_DIR` 配置）。Server 启动时装载完整凭据；Web 账户菜单修改管理员密码或重置 API Token 时，会原子更新同一文件并立即重新加载认证配置，因此这些操作不需要重启 Server。

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

该入口启动 Server Socket、心跳、直接 Flask HTTP（包含文件传输）和独立 WebSocket 服务。默认 Socket 端口为 `9999`、HTTP 端口为 `8085`、WebSocket 端口为 `8086`（Web 端口 + 1）。只运行 `rchserver.py` 则启动 Socket Server 和控制台，不会启动同一套 Web 登录页面；它仍会在加载 Server 配置时初始化管理员凭据。

运行时确实读取以下相关环境变量：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `RCH_WEB_PORT` | `8085` | Web/API/HTTP 文件传输端口；独立 WebSocket 监听 `+1` |
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

**管理员身份凭据从 `auth.json` 加载，不从启动环境读取或覆盖。** 启动环境仅配置上表列出的监听与 Web Session 运行选项。管理员密码可以在已登录 Web 界面的账户菜单中直接修改；API Token、Session Secret 或用户名的手工维护仍通过受保护的 `auth.json` 完成，并在重启 Server 后装载。Desktop Notifier 通过自己的 `RCH_NOTIFIER_TOKEN` 读取连接 Token，不会改变 Server 的认证配置。

### 密码与密钥的维护

#### 管理员密码的原子改写

已登录 Web 界面的右上角账户菜单提供 **Change Password**。修改时需要输入当前密码、新密码和确认密码；新密码必须至少包含 8 个字符，并同时包含至少一个英文字母和一个数字。成功后 Server 只替换 `auth.json` 中的密码哈希，保留 `username`、`api_token` 和 `session_secret`，立即重新加载认证配置，并退出当前登录。其他浏览器 Session 会在下一次请求时因凭据版本变化而失效。

停机维护时仍可直接编辑 `SERVER_RUNTIME_DIR/auth.json`（默认 `backend/runtime/auth.json`），**保留其他三个字段**，仅将 `password` 改为：

```text
"password": "plain:your-new-password"
```

这只是 JSON 对象内一个字段的写法，不是要把整个文件替换成上述一行。保存并重新启动后，Server 会将 `plain:` 后的明文转为新的加盐 scrypt 哈希，原子写回同一文件，并清除明文形式。`plain:` 后必须有非空密码；不允许直接填写不带 `plain:` 的明文。

通过 Web 修改密码时会立即重新加载密码哈希并结束当前 Session；停机手工改写则在下一次启动时生效。两种方式都会使旧的浏览器登录凭据失效。**API Token 与 Session Secret 保持不变**，使用旧 Token 的脚本、curl 或 Desktop Notifier 不受密码改写影响。

#### 长期凭据与签名密钥的轮换

如需更换长期 API Token，应停机后仅替换 `api_token` 字段，保持 `username`、有效的 `password` 哈希和 `session_secret` 不变。可以使用 Python 标准库生成足够长的新随机值：

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

把输出放入 `auth.json` 的 `api_token`，重新启动后才会生效。旧 Token 随即失效；使用该 Token 的外部程序必须更新配置。Server **不会在首次启动日志中打印 API Token**，也没有从环境变量直接轮换管理员 Token 的功能。

单独轮换 `session_secret` 时，可用 `secrets.token_urlsafe(48)` 生成新值。这会使此前签发的 Session Cookie 无法继续通过签名验证，所有浏览器必须重新登录；管理员密码和 API Token 不随之改变。管理员用户名也可在停止服务后直接编辑 `auth.json`，但不会由某个 `RCH_ADMIN_USERNAME` 环境变量覆盖。

#### 重新初始化凭据根

停止 Server，安全备份或移走 `SERVER_RUNTIME_DIR/auth.json`（默认 `backend/runtime/auth.json`），随后重启；Server 因找不到该文件而生成新的随机密码、API Token 和 Session Secret，并再次输出新的初始登录信息。此前的登录 Session 和所有使用旧 API Token 的外部客户端都需要更新。运行中只有 Web 的 Change Password 流程会执行受控的原子改写与认证重载；直接手工修改 `auth.json` 的其他字段仍应通过重启 Server 应用。

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

登录后的右上角账户入口显示 `auth.json` 当前用户名。菜单中的 **Authorization Info** 通过 `GET /api/auth/info` 读取用户名和管理员 API Token，并提供复制操作。**Reset** 调用 `POST /api/auth/token/reset` 生成新的随机 Token、原子保存 `auth.json` 并立即刷新 Server 内存中的 Token；响应通过 `Cache-Control: no-store` 返回新 Token，当前浏览器 Session 保持有效，旧 Token 从下一次请求起失效。重置后应更新使用旧 Token 的外部 HTTP 客户端。此操作只更换 `api_token`；用户名、密码哈希和 Session Secret 保持不变，后两项不返回前端。**Change Password** 使用 `POST /api/auth/password`，当前密码和新密码沿用登录页相同的轻量掩码字段传输。上述账户管理接口只接受管理员 Session 或管理员静态 Token，不接受 Client Session Token 作为账户管理权限。

当前 Session 是 Flask Cookie Session：Cookie 默认名为 `rch_admin_session`，默认有效期七天，设置了 `HttpOnly` 和 `SameSite=Lax`，并用 `session_secret` 签名。会话状态由签名 Cookie 维护；Logout 清除当前浏览器的认证会话。每个 Session 还绑定基于当前用户名、密码哈希和 Session Secret 计算的凭据标识，因此修改密码并重启后，旧 Cookie 即使仍在有效期内也会被拒绝。

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

8085 Flask Web API 采用管理员 Session/Token 或 Client Session Token（仅允许的 Client API）认证；受控浏览器原始文件上传和部分 Client 传输路径依靠各自的一次性令牌或原有 HTTP 访问策略。8086 的浏览器实时 WebSocket 检查管理员 Session/Token，PTY/Screen 则使用对应会话的一次性 WebSocket Ticket。

## Client Session Token

Client 连接注册后获得一枚随机 Client Session Token，供 Client Command、ACMD、Script、Job 和 SDK 在连接期间访问专门开放的 HTTP API。请求使用 `X-Client-Session-Token`，`ClientApiClient` 自动附加到配置的 Server API 地址；断线立即撤销，重连轮换。Client Token 与管理员 Session Cookie、管理员 API Token 是不同的认证身份。

Client API 方法和路径统一登记在 [`ClientApiPolicy.ROUTES`](client_session_api.md)，未登记的管理员 API（包括对其他设备的命令下发、账户管理）不会接受 Client Token。Keychain 的当前机器和 Server Shared 范围允许完整凭据读取与维护；详细身份与路由规则参阅 [Client Session Token & Client HTTP API](client_session_api.md)。

Command、Script 和 Job 使用同一连接期凭证。Web Browser Interaction 仍核对当前前台任务、命令 ID 和浏览器 Tab。

## 访问控制与运维安全

除 OPTIONS、静态资源和标注为 `@allow_anonymous` 的端点以外，Web 请求按以下条件放行：**有效管理员 API Token、有效管理员 Session、且请求路径在白名单内的有效 Client Session Token**，三者满足任何一项即可。没有认证的 API 调用返回 `401`，非 API 页面则跳转 `/login.html`。Client Session Token 只对 `ClientApiPolicy.ROUTES` 列出的 Client API 生效。

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
| Script API 调用提示未认证 | 确认 Client 当前已连接、持有 Client Session Token，且路由已列入 `ClientApiPolicy.ROUTES` |
| 已经输入正确密码却不能连接 | 检查 Server 的工作目录、启动报错、Web 端口与 HTTPS 反向代理配置 |

安全上还需区分三种轮换：改密码会影响 Web 登录及旧 Session；改 `api_token` 会影响 curl、Notifier 和其他外部 API 客户端；改 `session_secret` 会使现有签名 Cookie 失效。删除整个文件会同时重置全部三种凭据。上述操作均应在受控停机、备份和重启过程中完成，避免多实例使用不同的凭据文件。

`RCH_HIDDEN_DEVICES_REQUIRE_PASSWORD` 和 `RCH_HIDDEN_DEVICES_PASSWORD` 是隐藏设备访问相关的独立配置，**不是 Web 管理员用户名/密码**。也不要把网络端口可访问、上传接口未设相同守卫，或 Client Session Token 能访问某条路由，等同于整个 Server 已实施统一的细粒度访问控制。公网部署前，应结合代理、TLS、网络隔离及独立通道的访问控制一起审查。
