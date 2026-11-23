# Keychains & Credential Management：凭据管理与 Script SDK

RCH 的 Keychains 是一个**由 Server 管理、按机器身份分组的凭据存储与调用功能**。它解决两个相连但不同的问题：管理员在 Web 中维护登录凭据与通用 Secret；经过授权的 Client Script 在运行时从 Server 获取所需值，而不是将密码硬编码在脚本库中。Keychains 不使用 Client 操作系统的密码钥匙串，也不是与 Server Admin 登录共用的账号数据库。

本文集中解释数据模型、机器范围、管理页面、明文读写路径、Script SDK 与权限、安全边界。Client Session Token 的使用与 HTTP 白名单见 [Client Session API](client_session_api.md)；一般 SDK 约定见 [Script SDK API](script-sdk.md)；机器指纹如何变化见 [Device Identity](device_identity.md)。这些独立主题不在此重复展开。

## 一、数据模型与存放范围

### Login 与 Secret

Keychains 有两种业务条目，统一使用 `cred_id` 标识单条凭据，`name` 供 Web 查找、SDK 按名称解析。创建和更新时会记录 `created_at`、`updated_at`；创建 ID 由 Server 生成，而不是由浏览器或脚本指定。

| 类型 | 主要字段 | 用途 |
| --- | --- | --- |
| **Logins**（`kind: "login"`） | `name`、`username`、`secret_value`（密码）、`site`、`note` | 将用户名和密码作为一组凭据管理，站点和说明可选 |
| **Secrets**（`kind: "secret"`） | `name`、`secret_value`（通用值）、`note` | API Token、密钥文本或其他没有用户名结构的秘密值 |

每条数据还带 `machine_id` 与用于展示的 `hostname`。存储层对 Login 要求非空 `username`，对两类条目都要求非空 `name` 和非空 `secret_value`。名称在**同一个机器范围内**按去空白、大小写不敏感方式唯一；不能因为类型不同就在同一范围创建两个同名项。不同 Machine 范围之间可以同名。

服务层的字段限制为：普通文本最多 4096 字符，Secret 最多 256 Ki 个字符；Web 输入表单另有更低的限制，例如 Login Password 4096 字符，Secret Value 65536 字符、名称 160 字符。底层 `_safe_text()` 会对值进行 `strip()` 并按上限截断：**Secret 首尾空白不会被原样保留**，超长文本也不等于无损写入，不能把这套机制当成任意二进制数据仓库。

### Machine 与 Shared 两种范围

```text
Server Keychains
  ├── machine_id = 机器 A 的指纹       → A 的 Logins / Secrets
  ├── machine_id = 机器 B 的指纹       → B 的 Logins / Secrets
  └── machine_id = __shared__        → Shared Logins / Secrets
```

- **Machine**：条目绑定一个 `machine_id`，不是一个短暂的 `client_id`。同台机器多个 Client 进程默认查同一套凭据。
- **Shared**：使用明确的特殊 ID `__shared__`，展示名称为 `Shared`。它并非复制到所有 Client 磁盘，而是 Server 上一组可按共享范围解析的条目。
- SDK 默认使用当前 Client 本地身份的 `machine_id`；`scope='shared'` 才会转向共享范围。当前 SDK 不会自动先查 Machine、找不到再查 Shared。两种范围的同名凭据由 `scope` 显式区分。
- Web 机器列表综合正在连接的 Machine 与**已经有凭据的** Machine，另外总是包含 Shared。因此设备断开后，只要存在凭据，依然可以在 Keychains 中找到该设备范围。

Machine ID 来源于机器指纹；系统升级、改主机名等操作可能导致它改变。**旧凭据不会自动归到新 Fingerprint**：原来的 `machine_id` 对应的数据库记录仍在 Server，新客户端按当前机器身份查找时可能看不到。可通过 Web 编辑凭据，把 `Host Scope` 改到新的机器范围；不要把 `hostname` 当成持久身份。

## 二、Server 存储：SQLite + 轻量可逆保护

Keychains 结构化记录保存在 Server 的 `SERVER_RUNTIME_DIR/rch.db` 里，独立使用 `keychain_entries` 表。凭据按 `machine_id`（以及 Shared 的 `__shared__`）隔离；跨机器移动在一条数据库事务中完成，名称在同一机器范围内不区分大小写唯一。普通列表不解密秘密值，只有详情读取、更新或 SDK Resolve 需要解密。

`secret_value` **不以明文存入数据库**。`secret_ciphertext` 使用 Python 标准库的随机 nonce、HMAC-SHA256 生成的字节流遮蔽和校验标签，属于轻量可逆保护，不依赖第三方密码库，也不等同于经过审计的标准加密算法。服务器首次保存新凭据时，在与 `rch.db` 相同目录生成 `keychains.key`，仅供 Server 本地读取；**可恢复备份需要同时保留 `rch.db` 和 `keychains.key`**，只备份数据库无法解密密码。管理员在 Web 点击 Show/View、Script 请求单条详情时仍能获得明文，沿用既有 API 权限控制；Web 与 Client 请求明文详情时，响应中会包含原始 Secret。

这一方案不需要用户配置主密码，也不引入密钥轮换/托管体系；它阻止单独查看数据库文件时直接读出 Secret，**不能防护同时拿到数据库和密钥文件的攻击者**。不要把 `keychains.key` 提交到源码或公开分享。若密钥文件损坏、遗失，Server 会报明确错误，不会静默创建新密钥覆盖已有数据。备份时要暂停写入或使用 SQLite 在线备份，并保存同一运行目录的密钥文件。

数据库字段详解见 [rch.db 数据库详解](rch_database.md)。

## 三、Web Keychains 的完整操作

Keychains 在 Web 的 `KeychainManagerDialog` 中管理；其 API 由 Server 本地 `WebKeychainApi` 和 `KeychainStore` 实现，**Web 的查看和修改操作不会先向 Client 发送一条 Socket 命令**。当前连接信息仅用于建议机器范围与显示设备信息。

### 列表、范围、搜索

首次打开对话框时，优先选当前连接的 `machine_id`，如果没有当前机器则选择 Shared。工具栏提供 **Refresh、New Credential、Generate Password**，并有 Host Scope 过滤、Logins/Secrets 类型过滤、全文关键词搜索。搜索覆盖名称、用户名、站点、说明、主机显示名、Machine ID 和类型；它作用于已从 Server 拉回的条目，不额外向 Server 发模糊查询。

列表数据默认不带秘密明文。每个条目显示名称、类型、Login 的用户名以及密码/值的掩码，并提供 **Show / Hide、Copy、View、Edit、Delete**。列表的 `has_secret` 仅表明值存在，`secret_placeholder` 是用于显示的掩码，均不是明文的加密形式。

### 明文何时出现在浏览器

- `Show` 首次调用 `GET /api/keychains/<cred_id>`，获得包含 `secret_value` 的详情数据，并将可见值缓存在对话框的 `visibleSecretMap`。`Hide` 清除该条目的显示缓存。
- `Copy` 可能直接使用已加载的缓存，也可能先读取详情，再写入**系统剪贴板**；不要求事先显示秘密。
- `View` 打开详情弹窗，包含主机、Login 站点/用户名、秘密值、创建与更新时间、说明；默认用掩码显示，但**详情数据已在浏览器内存中**。
- `Edit` 从详情 API 拉取完整值，用于编辑原始密码、用户名、名称、站点、说明、类型和 Host Scope；保存是 PUT 而非创建新 ID。
- 关闭主窗口或切换主机筛选会清空部分可见缓存，不能据此推断明文从 JavaScript 内存、浏览器历史或剪贴板中被彻底抹除。复制后的系统剪贴板也不会由当前代码自动定时清空。

### 创建、更新、删除

新建时先选择 Host Scope，再选择 Login 或 Secret。Login 填名称、用户名、密码，可选 Site/Note；Secret 填名称、Value，可选 Note。表单做非空检查；Server 会进一步规范化与校验。保存成功后刷新列表。删除前弹出确认，再发 DELETE；删除不会自动撤销已经被脚本取走、复制或发送出去的秘密。

如果编辑时改变 Host Scope，`cred_id` 保持相同，但是数据库中凭据的 `machine_id` 会原子更新；因此其他脚本必须使用新的 `scope` 或 `machine_id` 才能继续按名称找到它。

### 运行参数中的 Keychain Picker

Script、Background Job 和 External Tool 的共享参数表单支持在 `password` 字段上声明 `keychain_picker`。Login 记录可一次填入用户名与密码；Secret 记录可填入密码或 API Token。选择范围是本次运行目标的 `machine_id` 与 Server Shared，凭证列表只显示元数据，用户选择后才读取完整值。

字段绑定写在密码参数的 Metadata 中，详细格式与校验规则见 [Parameter Schema](parameter_schema.md)。项目内有三个可直接运行的示例：`server/resources/scripts/examples/keychain_login_picker.py`、`server/resources/jobs/examples/keychain_secret_picker.py` 和 External Tool `keychain-picker-demo`。它们只输出参数接收状态与长度，不输出凭证明文。

## 四、Password Generator 与 Keychains 的关系

密码生成器是 Keychains 的**纯前端辅助工具**，可以从工具栏独立打开以复制密码，也可以从正在新建或编辑的 Login/Secret 表单打开。编辑时生成器显示 **Use Password**（填入当前 Credential，待用户检查后按 Save）与 **Use & Save**（填入并使用现有表单校验及保存 API 立即保存）。表单缺少必要字段时仍提示校验错误，不会越过已有凭据规则；独立打开生成器时只提供复制。

它有两种模式：

| 模式 | 当前实现 |
| --- | --- |
| Normal | 长度 6–18，默认 12；可选大写、小写、数字、特殊符号；先保证每个所选字符集至少出现一个字符，再随机补足并打乱 |
| Apple-style | 生成 18 个字母组成的三段式形式，插入两个连字符；其中随机一处为数字、另外随机一处大写，输出形态如 `abcdef-Ghij3l-mnopqr`（示意） |

随机整数优先用 `window.crypto.getRandomValues()`，并使用拒绝采样避免取模偏差；**如果 Web Crypto 不可用，源码会退回 `Math.random()`**。因此不要声称所有情况下都具备密码学级随机性，尤其不要把该回退路径用于高安全性密码生成。生成的密码和从 Keychains 复制的值一样会进入系统剪贴板，具有剪贴板暴露风险。

## 五、Keychains HTTP API

管理员 Session / Admin API Token 保有完整后台权限；连接中的 Client Session Token 则可以操作当前机器和 Server Shared Keychains 的全部凭据，包含明文详情和创建、更新、删除。不能操作其他机器的凭据。允许的方法/路径在 [Client API Policy](client_session_api.md) 集中维护。

| Method | Path | 主要用途 |
| --- | --- | --- |
| `GET` | `/api/keychains?machine_id=...` | 机器范围的凭据列表（不含明文） |
| `GET` | `/api/keychains/<cred_id>` | 指定凭据的完整明文详情 |
| `POST` | `/api/keychains/resolve` | 按名称和当前机器/Shared 解析凭据 |
| `POST` | `/api/keychains` | 创建 Login/Secret |
| `PUT` | `/api/keychains/<cred_id>` | 更新已有凭据 |
| `DELETE` | `/api/keychains/<cred_id>` | 删除凭据 |

`POST /api/keychains/resolve` 的请求示意：

```json
{
  "name": "nas-login",
  "kind": "login",
  "scope": "machine",
  "machine_id": "current-machine-id"
}
```

返回业务数据在统一响应对象的 `data.item` 中，`item.secret_value` 是真正明文；`GET /api/keychains` 的 `data.items` 则移除了这一字段。创建、编辑与删除的返回 `item` 同样使用公开形式，不附带明文；**只有详情及 Resolve 是明文读取路径**。`WebKeychainApi` 会根据当前/已存机器列表补全展示 `hostname`，但是 `hostname` 不用于鉴别授权。

Client Token 请求会先通过 API 方法/路径白名单，再由 Keychain API 校验机器归属；当前机器与 Server Shared 均可访问。管理员请求保留跨机器操作能力。

## 六、Script SDK 如何读取与创建 Keychains

Client Script 使用 `from client.runtime.sdk import keychains`。SDK 模块直接复用 `client.runtime.keychains`，发起 HTTP 请求到 Server 的上述管理 API；自动附带 `X-Client-Session-Token`，并将结果转换为更适合脚本消费的对象。它不会通过 Socket 指令去读取 Client 操作系统密码库。

### 常用 SDK 能力

| SDK 调用 | 返回内容 | 认证 |
| --- | --- | --- |
| `keychains.list(scope='machine')` / `list_keychains(...)` | 元数据字典列表；不含明文值 | Client Session Token |
| `keychains.get_secret(name, scope='machine', machine_id='')` | `SecretValue` | Client Session Token |
| `keychains.get_login(name, scope='machine', machine_id='')` | `LoginCredential` | Client Session Token |
| `keychains.get_keychain(name, kind='', scope='machine', machine_id='')` | 按 `kind` 返回 `LoginCredential` 或 `SecretCredential` | Client Session Token |
| `keychains.create_secret(name, value, scope='machine', note='')` | `SecretCredential` | Client Session Token |
| `keychains.create_login(name, username, password, scope='machine', site='', note='')` | `LoginCredential` | Client Session Token |

与 Web 原始列表的 `cred_id` 不同，SDK 对列表项规范化后用 `id` 表示凭据 ID；不要假定列表查询会返回密码值。`get_keychain` 也不是“返回未经包装的原始 HTTP JSON”，它会按实际类型返回对象。

如下示例只展示使用方式，不输出密钥本身：

```python
SCRIPT_METADATA = {
    "display_name": "Use a stored credential",
    "params": [],
}

from client.runtime.sdk import keychains

login = keychains.get_login("nas-login")
username = login.username
password = login.password.getvalue()
# 将 username/password 交给目标登录逻辑；不要 print 或写入日志。

shared_token = keychains.get_secret("shared-api-token", scope="shared")
# 在真正需要使用时显式取值：shared_token.getvalue()
```

默认 Machine 范围取当前 Client 的本地 `machine_id`；读取 API 可以在 `scope='machine'` 下显式指定 `machine_id`；创建 API 没有向调用者开放单独的 `machine_id` 参数，只按当前机器或 Shared 写入。缺失 `name`、非法 `scope`、类型不匹配或找不到条目，可能得到 `ValueError` 或统一 `KeychainError`，不要将所有失败当作“凭据不存在”。

`SecretValue` 使用包装器降低意外明文打印：`str(value)`、`repr(value)` 显示掩码；`.getvalue()` 才返回字符串。它**不是加密对象或机密计算容器**；实际使用密码时终归会生成明文字符串，且 Secret 已经经由 Server→Client HTTP 响应传输。

### Client Session Token 的机器范围

Client 可以完整读取、创建、更新、删除属于自己机器和 Server Shared 范围的 Keychains；其他机器的凭据不在当前 Client 的访问范围内。凭据列表隐藏明文；详情与 Resolve 返回明文。管理员凭据保持 Server 全局管理能力。

`ClientApiClient` 只对配置的 Server API 地址自动携带 Client Session Token，失效的连接 Token 无法再访问该 API。

## 七、使用边界与故障排查

| 情况 | 首先检查 |
| --- | --- |
| Web 看不到某台机器的凭据 | Host Scope 过滤是否选错、该机器当前 `machine_id` 是否变化、数据库是否有该 Machine ID 记录 |
| 同名创建失败 | 相同 Machine/Shared 范围下是否已有同名项（大小写不敏感，Login 与 Secret 共用名称空间） |
| Script `get_secret` 报 Not Found | 当前 Machine ID 与创建时是否一致；是否应显式使用 `scope='shared'`；名字及类型是否匹配 |
| Client Script 报 `Authentication required` | Client 是否连接、Client API Token 是否有效、HTTP 路径是否列入白名单 |
| 调用列表成功但不能取明文 | 列表不含 `secret_value`；使用详情或 Resolve 获取明文 |
| 在 UI 中点 Hide 之后仍担心泄漏 | Hide 只影响展示缓存；此前写入剪贴板、脚本变量或网络传输的值不由 Hide 收回 |
| 更换设备或重装系统后凭据消失 | 在 Keychains 的机器范围中查找旧 Machine ID，必要时通过管理端迁移范围；不要尝试按 `client_id` 查找 |
| 创建成功但备份里找不到记录 | 凭据记录在 Server `runtime/rch.db`，还需一同备份 `runtime/keychains.key` |
| Password Generator 结果没有进入 Keychains | 从 Credential 编辑表单打开生成器，选 Use Password 或 Use & Save；从工具栏独立打开时只有复制 |

从安全角度，务必把 Server Keychains 的数据库和密钥文件、Server 登录态、API Token、脚本代码、日志和系统剪贴板视作同一条风险链。Web 列表掩码、`SecretValue` 掩码与 Client Token 认证各有用途，但**并不构成对密钥文件泄漏、浏览器明文以及具备对应路由权限的脚本读取行为的端到端保密保证**。

## 实现边界与相关模块

- 服务端凭据存储和规范化：`server/application/keychains/keychain_store.py`。
- Web 管理/解析外观和 HTTP 路由：`server/application/web/keychain_api.py`、`server/web/routes/keychains.py`。
- Web 凭据页面、密码生成器：`KeychainManagerDialog.vue`、`PasswordGeneratorDialog.vue`。
- Client 侧 SDK 与 HTTP 访问：`client/runtime/keychains.py`、`client/runtime/sdk/keychains.py`、`client/http/client_api.py`。
- Client API 路由与认证：`server/application/auth/client_api_policy.py`、`server/web/auth_guard.py`。

本文聚焦 Keychains 的数据与操作边界；正式 Server 管理员认证、Script 通用授权、设备指纹的计算与生命周期均由相应文档解释，避免相同机制多处重复且日后出现不一致。
