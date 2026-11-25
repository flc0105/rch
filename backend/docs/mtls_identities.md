# RCH mTLS Identity 操作说明

## 设计边界

`tcp` 为独立明文模式，不依赖 Identity 材料。`mtls_tcp` 为独立的双向认证模式。Reverse 和 Bind 均在发送 RCH 应用数据前完成双向 TLS 握手，TLS 至少 1.2。

Server 使用独立的 `server-ca.crt` / `server-ca.key` 签发 Server Identity；Client Identity 由另一个 `client-ca.crt` / `client-ca.key` 签发。两种 CA 各自只被对端按预期角色信任。Server 还按签发登记表检查 Client 证书的 SHA-256 摘要，拒绝未授权、已撤销或已过期的安装身份。证书有效期由标准 SSL 验证，并由 Server 管理表再次判断。SHA-256 用于登记表的内部证书索引，不是旧的网络端 Server 证书指纹固定模式。

## 首次启用（必须在建立 mTLS 连接前完成）

1. 在 Server Web 的 **Settings → Identities** 中点击 **Initialize**。Server 的信任材料保存在 `RCH_SERVER_RUNTIME_DIR/identities/`，默认即 `<project>/backend/runtime/identities/`。此操作只可初始化一次，不会覆盖现有信任根。需要系统安装 `openssl` 命令供签发使用；Socket 握手本身由 Python `ssl` 完成。
2. 在 **Client Identities** 输入安装范围的识别名称和有效期（默认 365 天），点击 **Create**。Web 会下载仅包含 `client.crt`、`client.key`、`server-ca.crt` 的独立 ZIP。务必通过受保护的管理员渠道交付，不能放入公开构建包、匿名 Bootstrap、普通更新包或共享仓库。
3. 在 Client **持久 Identity 目录** 放置上述三份文件，名称必须完全一致。桌面默认 `~/client_bundle/identity/`；iOS / Pythonista 默认 `~/Documents/client_bundle/identity/`。可在 Client 配置中使用绝对路径 `identity_dir` 覆盖。无需导入操作系统的全局证书库。Linux/macOS 解压后运行 `chmod 600 ~/client_bundle/identity/client.key`，目录权限建议 0700。Windows 应仅允许运行 Client 的账户及必要管理员读取私钥（NTFS ACL）。
4. 在 Reverse 的 Listener 配置选择 **mTLS/TCP**，构建对应 Python Client，或在 Bind 的 Agent 构建页及 **Connect to Client** 页面选择 **mTLS/TCP**。确保双方选择同一传输方式。Bind 由 Server 拨号到 Client 的监听 IP/端口；Reverse 由 Client 拨号到 Server 的监听地址。
5. 同一安装下的不同 Release 复用固定 Identity 目录。正常源码 Bundle、升级包只包含应用代码和选择的传输模式，不包含私钥。HTTP 管理与软件下载接口不受 mTLS Socket 替代。

## 常见失败与运维

- **缺少文件或私钥权限过宽**：mTLS 创建连接前报错；不会自动回退为 TCP。确认 `identity_dir` 以及 `client.crt`、`client.key`、`server-ca.crt`，并限制私钥权限。
- **Server 尚未初始化**：mTLS Listener 无法启动，或构建 mTLS Agent 被拒绝；独立的 TCP Listener 仍可使用。
- **撤销**：在 Identities 中点击对应 Client 的 **Revoke**。同一个 Client Identity 的**后续主会话、文件数据和隧道连接**会被拒绝；既有已连接会话不被立即踢下线。按需手动断开旧会话。撤销是不可逆操作，重新授权需签发新身份并安全分发。
- **到期 / 轮换**：客户端证书到期前签发并安装新的 Client Identity，再撤销旧身份；服务器 TLS 身份默认 365 天，需在到期前维护/更新身份文件并重启相关 mTLS Listener 以加载新证书。目前不提供自动证书续签或 Server 轮换 UI；切勿直接删除整个 Identity 根目录，否则此前发出的 Client 安装材料不再匹配新信任根。
- **配置校验**：Listener 配置只接受 `tcp` 和 `mtls_tcp`。无效协议会拒绝加载原配置，配置文件不会被自动改写。Client 选择 mTLS 时需要预先安装有效身份。
- **私钥备份**：Server Identity 目录包含两套 CA 私钥和 Client 私钥，必须严格访问控制、离线加密备份。下载 ZIP、Client 的 Identity 目录和浏览器下载缓存均按敏感凭据处理。

## 实现限制

本版本不支持设备数量上限、自动预注册、匿名签发、自动续签/系统 CA 导入或 Windows ACL 的自动管理。现有活跃会话在撤销前完成的握手不会被强制终止；需要新的立即断开机制必须另行设计。Go 原生 Client 没有提供 mTLS 实现：mTLS Listener 不允许构建 Go 原生 Agent，Go Loader 仅用于加载 Python Client，仍需先安装对应 Identity；iOS TLS 环境尚未实机验证。
