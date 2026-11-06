# Client Session Token & Client HTTP API

每次 Client 连接注册后，Server 生成一枚随机 **Client Session Token**，通过当前 RCH Socket 交付给 Client。Command、ACMD、Script、Job 和 SDK 在同一连接期间使用这枚 Token 访问 Server 的 Client API；断线撤销、重连轮换。它不写入 `baseinfo`、日志、持久化文件或数据库。

## HTTP 请求

```http
X-Client-Session-Token: <connected-client-token>
```

`ClientApiClient` 只对当前配置的 Server Web API Base URL 自动附加此 Header，不发送至任意外部网站。Client Python Script 子进程从执行上下文取得 Token；独立 Background Job 子进程通过启动环境接收，并在启动后立即从环境中移除，Token 不写入 Job 上下文 JSON。无需在 Script Metadata 中声明 API Scope，也无需为单个命令签发执行级 Token。

## 在哪里维护允许的 API

**唯一权威表：** `backend/server/application/auth/client_api_policy.py` 中 `ClientApiPolicy.ROUTES`。每行是 `(HTTP Method, Path Template)`，例如：

```python
('GET', '/api/artifacts/<artifact_id>/download'),
```

新增 Client 可用 API 时，在这一处补充方法与路由，再添加正向及拒绝路径测试。未列入表中的 HTTP 请求不接受 Client Session Token。管理员 Session 和 Admin API Token 仍沿用各自完整的后台 API 权限，不经过这张 Client API 表。

表内当前覆盖：Script/Job 下载、Background Job 上报、设备事件、Agent 构建/下载、Artifact 查询/下载/预览、External Tool Catalog、当前 Client 的 Pinned Paths、Keychains、Interaction 请求。`/api/connections/<client_id>/command`、账户管理、其他设备操作及管理员配置不在 Client API 中。

## 资源归属

- Pinned Paths 仅允许当前 Client 的 `client_id`。
- Client Keychains 可操作**当前机器**和 **Server Shared** 范围（列表、详情明文读取、Resolve、创建、更新、删除）；其他机器范围拒绝。管理员操作不受此 Client 范围限制。
- Interaction 请求同时要求 Client 当前连接、前台命令 ID、Web Task 和目标 Tab 一致，保证 UI 交互路由到当前任务。

## 运行与验证

Client 建立连接后，从 Client 的 SDK 或命令调用 `ClientApiClient` 即可访问允许的 API；无需自行携带管理员 Token。断线/重新连接时旧 Token 失效，Server 重启后内存中的 Token 全部失效，重新连接获得新值。手工验证时应分别覆盖允许的 `GET /api/artifacts`、拒绝的 `POST /api/connections/<client_id>/command`、Keychain 自身/Shared 范围以及其他机器拒绝、Interaction 任务身份校验。不要在命令结果或日志中打印 Token。
