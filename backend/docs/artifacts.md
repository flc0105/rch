# Artifacts

Artifact 是 RCH 在 Server 端保存、管理和复用文件的统一对象。一次远程下载、Script 上传、Job 输出或终端内容保存，最终都可以形成一个具有稳定 `artifact_id` 的文件记录。浏览器和脚本通过 Artifact API 查找、预览或下载这些文件；Command History、Background Job 等功能则保留 Artifact 引用，以便在执行结束后仍能找到相关结果。

Artifact 并非传输协议，也不是远程设备文件系统的镜像。它描述的是**已经落到 Server 文件系统并完成登记的文件**。实际数据传输可能经过 8085 或 8086，也可能由 Server 直接生成文本；任务进度与取消由 File Transfer 及相应的执行管理机制负责。需要理解大文件的上传通道和 Transfer Center 时，参见 [File Transfer](file_transfer.md)。

## 文件如何成为 Artifact

一次典型的 Client 文件上传经过以下流程：Client 准备本地文件，携带 `artifact_type`、`category` 和可选的来源信息调用上传接口；Server 将文件保存到对应的 Artifact 目录，产生唯一的存储文件名和 `artifact_id`，写入同目录体系内的 `.meta.json` 元数据，最后把 Artifact 描述返回调用方。经过 Web 上传 API 的正式注册还会发布 `artifact_created` 事件，让浏览器更新已打开的 Artifact Manager，并在适用时显示文件已就绪的提示。

```text
Client / Browser / Server 内部任务
              │
      上传文件或生成内容
              │
       Artifact Registry
        ├─ 分配存储路径
        ├─ 保存文件字节
        ├─ 注册 .meta.json
        └─ 生成 artifact_id 与访问 URL
              │
       Artifact API / SDK
         ├─ Artifact Manager
         ├─ Command History
         └─ Job 的文件关联
```

文件的来源不限定为某一种命令或任务。使用通用 HTTP 上传的调用方、在 Server 直接保存命令输出的调用方，以及负责远程文件预览的 Client，最终共享同一套 Artifact 查询与访问机制。但**并不是所有创建路径都会自动发布相同的 SSE 事件**：通用 Web 上传、特定命令输出注册路径显式发布 `artifact_created`；直接调用更底层的保存服务时，仍需由上层调用方决定是否发布事件。

Server 还能创建临时文件供 Client 下载，例如浏览器向远端设备上传时先暂存的文件。它们位于 `upload_tmp`，**不是已经注册的正式 Artifact**：没有可供 Artifact Manager 管理的 `artifact_id`，应按传输任务的生命周期清理，而不是当作共享文件长期保存。

## 文件身份、类型与存储组织

Artifact 采用文件系统存储，默认根目录由 `WEB_FILES_ROOT_DIR` 决定，默认对应固定项目路径 `backend/runtime/web_files/`（可通过 `RCH_SERVER_RUNTIME_DIR` 修改 Server runtime 根目录）。正式文件位于其中的 `artifacts/` 子目录，记录通过旁边的 `meta/*.meta.json` 文件保存，而不是写进 `runtime/rch.db` 的一张 Artifact 主表。

目前登记的正式 `artifact_type` 分为四类。这是 Registry 接受的类型约束，不是用户可以任意扩展的普通标签：

| `artifact_type` | 数据组织与主要语义 |
|---|---|
| `files` | 按 `category`、`machine_id` 分层保存的普通文件 Artifact |
| `previews` | 按 `machine_id` 保存的预览缓存文件 |
| `shared_files` | Server 共享文件区，按 `category` 分组，与某个 Client 身份解绑 |
| `command_output` | 按 `category`、`machine_id` 分层保存的命令、Script 或 Job 文本输出 |

这里有两个独立概念。`artifact_type` 控制文件进入哪个目录体系，也控制 Artifact Manager 的主要标签页；`category` 是同一类型下的业务分组，不能拿它代替 `artifact_type`。例如 `command_output` 下可以使用不同的输出分类，但在访问和列表中过滤它时，类型仍然是 `command_output`。

Registry 会清理文件名中的不安全字符，为实际存储名添加随机后缀；必要时还会防止路径重名覆盖。因此：

- `original_name` 是展示给用户的文件名称；
- `stored_name` 是 Server 磁盘上的实际文件名称；
- `artifact_id` 是对外访问和关联时最可靠的标识，不受重命名影响。

典型的元数据结构如下（字段值仅为结构示意）：

```json
{
  "artifact_id": "<generated-id>",
  "artifact_type": "files",
  "category": "default",
  "hostname": "<device-name>",
  "machine_id": "<machine-id>",
  "client_id": "<connection-id>",
  "original_name": "report.txt",
  "stored_name": "report_<suffix>.txt",
  "saved_path": "<server-absolute-path>",
  "size": 1024,
  "created_at": "2026-10-16 12:00:00",
  "source_command_id": null,
  "job_id": "",
  "download_url": "/api/artifacts/<generated-id>/download",
  "raw_url": "/api/artifacts/<generated-id>/raw",
  "preview_url": "/api/artifacts/<generated-id>/preview"
}
```

其中 `machine_id` 表示可跨连接保留的设备身份；`client_id` 对应产生文件时的具体连接。来源字段可以包含命令、Job 等关联信息，`extra` 则保存调用方附加的 JSON 元信息。共享文件在登记时会清空机器、连接、命令和 Job 来源身份，因此不能依靠它们筛选某一台设备的共享文件。

Artifact 列表不是单独维护的数据库索引。Server 遍历正式 Artifact 根目录下的 `.meta.json` 文件，解析后按创建时间逆序排列，并在读取时检查 `saved_path` 是否仍存在；缺失时返回 `is_available=false` 和状态文本。直接从磁盘移走文件但保留元数据，会使它继续出现在列表中却无法下载。对于大量 Artifact，枚举元数据文件也会形成实际的目录扫描开销。

## 访问、查找与内容呈现

Web 的 Artifact Manager 将文件按上述四种类型展示，提供文件名或分类搜索、设备过滤、详情查看、批量选择和管理操作。普通 Artifact 使用 `machine_id` 过滤，Shared Files 则是全局共享区，不绑定当前设备。页面打开、手动刷新或收到相关事件时可重新获取 Server 列表；界面搜索是在已加载的 Artifact 数据上匹配，不是远端设备文件内容的搜索。

### 下载、原始响应和预览

Artifact 的三个 URL 含义不同：

| URL | 返回行为 |
|---|---|
| `/api/artifacts/{artifact_id}/download` | 下载附件，使用 `original_name` 等信息确定下载名称 |
| `/api/artifacts/{artifact_id}/raw` | 直接以文件响应返回内容，适合浏览器显示图片等 |
| `/api/artifacts/{artifact_id}/preview` | 返回用于预览界面的结构化描述，而非直接返回整个原始文件 |

预览根据扩展名和 MIME 类型区分图片、文本和不支持的格式。图片预览返回 Raw URL；如果运行环境安装 Pillow，还可能附加尺寸、格式和部分 EXIF 信息。文本预览默认最多显示文件前 **512 KiB**，同时校验完整文件的编码；支持严格 UTF-8、UTF-8 BOM 与带 BOM 的 UTF-16。无法无损识别编码时只读显示；超过限额会标记 `truncated`，不允许将截断内容直接保存覆盖原文件。无法识别为图片或文本时仍可下载，但 Preview 会返回 `unsupported`。

Preview Dialog 对可编辑文本提供编辑入口；保存实际修改的是 **Server 上的 Artifact 文件**，并同步更新其元数据大小和更新时间。它不会自动将编辑内容同步回最初的 Client 文件。如果是 Remote Files 中的远程文件编辑，则要使用那条独立的远端保存链路。被截断的预览不应作为完整内容直接覆盖保存。

### 从 Script SDK 使用 Artifact

Script SDK 的 `artifact` 模块允许任务上传本地文件、查询 Server 已登记 Artifact，并按标识或文件名下载。下面只是一次典型调用方式，不依赖项目中任何现成命令或 Job 实例：

```python
from client.runtime.sdk import artifact

saved = artifact.save("./report.txt", type="files", category="report")
artifact_id = saved["artifact_id"]
info = artifact.get(artifact_id, type="files")
local_copy = artifact.download(artifact_id, type="files", target_path="./downloads/")
```

`save(path, type=..., category=..., extra=...)` 的 `path` 是运行 Script 的 **Client 本地路径**；SDK 会先确保目标文件真实存在，再上传并取得 Server 返回的登记信息。`get(ref, type=...)` 和 `download(ref, type=..., target_path=...)` 接受 `artifact_id`、原始文件名或存储文件名；如果同一类型下出现多个同名匹配，它们会抛出歧义错误，不会随意选取其中一份。实际使用中应优先保存 `artifact_id`。

SDK 还提供 `artifact.list(type=..., machine_id=...)` 和 `artifact.find_by_file_name(..., exact=True)`。前者返回 Server Artifact 列表；后者在列表上匹配 `original_name` / `stored_name` 并返回简要信息，`exact=False` 为不区分大小写的包含匹配。这些查询不是在目标 Client 的文件系统搜索。

SDK 的默认值有意不同：`save()` 默认上传到 `files`，`get()` / `download()` 默认从 `shared_files` 查找。因此如果保存到 `files`，随后就需要明确传入 `type="files"`。如果无特殊 Client 目录解析器，下载目标路径会依据任务工作目录解析；传入以分隔符结尾的目录，或者传入现存目录时，SDK 会把文件名追加到该目录。

SDK 读取 Artifact 列表、下载内容时使用 Server API；权限应符合当前调用上下文的 Web 认证或 Script Grant 策略。Artifact ID 是定位符，不是自动获得所有文件访问权限的临时签名 URL。

## 共享文件与远程任务的衔接

Shared Files 适合保存希望从 Server 重复分发、由脚本引用或在多个设备间复用的文件。Artifact Manager 可以直接上传到 Shared Files，还支持创建文本文件并通过编辑器保存。共享文件即使没有在线设备也仍然可列出；其元数据不会因为某个 Client 离线而删除。

当需要把共享文件送到当前设备时，Web 调用 `/api/artifacts/{artifact_id}/send-to-client`，传入目标 `client_id` 和可选 `target_path`。Server 先查找 Artifact 文件，再通过现有 Web 上传执行链创建下发任务，由 Client 下载到目标路径；API 返回的是提交任务的信息，而**不是保证远端文件已经落盘**。该专用发送接口目前仅接受 `shared_files` 类型，不能认为 Artifact Manager 中任何文件都能走同一条接口直接下发。

在 Shared Files 标签中，还可以把文件交给目标 Client 的剪贴板设置接口。它只是另一种消费 Artifact 的方式：Clipboard 最终能否在目标系统提供文件取决于连接、平台能力和 Clipboard 的实现，不是对 Artifact 存储的额外复制保证。有关真实字节路径及进度，仍以 File Transfer 文档为准；Clipboard 行为参见 [Clipboard](clipboard.md)。

## 命令结果与运行记录之间的引用

Artifact 的一个重要用途是让**运行结束后的文件仍可从执行记录追溯**。上传时携带 `source_command_id`，Server 在对应连接中定位绑定的历史执行条目，尝试将 Artifact 信息关联到 Command History；Job 则通过独立的文件上报将 Artifact ID 和快照存入 Job 关联记录。两者都是关联关系，而非在历史数据库中重新保存文件字节。

读取历史和 Job 详情时，Server 会使用关联的 `artifact_id` 重新查询当前 Artifact。如果文件已被删除或元数据不再存在，历史项仍可保留，但会显示 `Artifact removed` 或文件不可用。这意味着删除 Artifact **不等于**删除某次 Command History、Job 执行或它们的日志。

终端还支持将完整 Client 命令输出保存为 `command_output` Artifact。对应执行器将返回的输出分块写入 Server 文件、结束后注册元数据，再返回保存位置和 `artifact_id`，而不是把完整文本重新塞回终端。浏览器也可以将终端已有的输出内容保存为命令输出 Artifact；这条路径直接调用保存文本 API，因此其事件发布行为与上传文件的标准路径不必完全相同。输出的文件名会依据分类、时间和命令显示名称生成，并由 Registry 继续加入防重名后缀。

Artifact 创建通知与 Transfer 完成事件也是两个不同层面：`artifact_created` 表示一份正式文件已经登记；`transfer_updated` 表示传输进度正在变化；`file_transfer_lifecycle` 代表受管理传输的状态变化。一个普通 Script SDK 上传可以产生 Artifact，却未必在 Transfer Center 拥有独立追踪任务。

## 生命周期管理与运行边界

在 Artifact Manager 中删除单条、批量删除或按类型 Clear，最终都执行 Artifact Registry 的文件删除操作。删除单条时会移除实际文件和对应的 `.meta.json`；Clear 则先按 `artifact_type`（可附带 `machine_id`）筛选，再逐个删除，并返回成功删除的数量。Shared Files 是跨设备共享的，不应在界面操作时把某台设备的筛选理解成 Shared Files 的归属限制。

Rename 会更新 `original_name`，同时重命名磁盘文件和元数据文件，但保持原来的 `artifact_id` 不变；如果目标文件名冲突，Registry 会生成不冲突的实际文件名。`previews` 不允许执行 Rename。删除后，基于 ID 的 Download、Raw 或 Preview 会因元数据查找失败而返回不存在；文件本体缺失但元数据尚在时，也无法正常读取内容。

预览文件虽然属于正式 `previews` 类型，但 Server 的启动清理配置同时包含 `preview_cache`：启动清理会清除该预览目录下的缓存文件，包括相关元数据。相较之下，`files`、`shared_files` 和 `command_output` 不是当前启动清理配置中的常规清理目标。`upload_tmp` 会单独清理，它不参与正式 Artifact 的列表与 Clear。

Artifact 数据在 Server 本地文件系统中，备份时应考虑文件与元数据一起保存。只备份 SQLite 不能恢复 Artifact；只保留 `.meta.json` 而丢失实际文件，则只能得到不可用的记录。默认路径固定相对于项目 **`backend/`**，不会随启动 CWD 改变；自定义路径由 `RCH_SERVER_RUNTIME_DIR` 决定，变更后应停机并整体迁移对应数据。对外部署时应保护这份目录和访问 API，尤其 8086 的专用上传入口并不等同于对所有 Web 会话做相同认证。

开发和运维时可以从现象定位到具体边界：找不到 Artifact 先确认上传是否真正注册并返回 `artifact_id`；列表可见却无法下载则检查 `saved_path` 的文件是否存在；按文件名查找有多条结果时应改用 ID；预览被截断不代表磁盘内容缺失；共享文件无法下发需要区分 Artifact 是否存在、目标 Client 是否在线、下发任务是否完成；历史还在而文件已失效则应检查 Artifact 的独立清理记录。

## API 接口与权限边界

Web API 以 `/api/artifacts` 为主入口。以下是接口协议的边界，用来解释不同操作如何消费同一个 Artifact ID；它们不构成某一类业务命令的固定清单。

| HTTP | 路径 | 返回或操作 |
|---|---|---|
| `GET` | `/api/artifacts` | 列表及机器过滤信息，支持 `type`、`machine_id` 查询参数 |
| `GET` | `/api/artifacts/{id}/download` | 附件下载 |
| `GET` | `/api/artifacts/{id}/raw` | 原始文件响应 |
| `GET` | `/api/artifacts/{id}/preview` | 文本、图片或不支持类型的预览描述 |
| `PUT` | `/api/artifacts/{id}/content` | 修改可编辑文本的 Server 文件内容 |
| `POST` | `/api/artifacts/{id}/rename` | 修改显示名和实际文件名 |
| `DELETE` | `/api/artifacts/{id}` | 删除文件和元数据 |
| `POST` | `/api/artifacts/clear` | 按类型、可选机器范围清理 |
| `POST` | `/api/artifacts/command-output/save` | 以文本内容创建命令输出 Artifact |
| `POST` | `/api/artifacts/{id}/send-to-client` | 提交共享文件下发任务 |

上传文件的兼容入口 `POST /api/files/upload` 同时存在于基础 Web 服务（默认 8085）和专用传输服务（默认 8086）。其 multipart 表单包含 `file`，可携带 `artifact_type`、`category`、`client_id`、`source_command_id`、Job 来源信息及 JSON `extra`。接口完成后返回注册的 Artifact 描述，浏览器再通过正式 Artifact URL 访问它。**选择 8086 并不自动意味着 Client 使用可取消传输策略，也不保证 Transfer Center 会创建进度记录。**

Artifact 管理路由通常由 Web Session 或管理员 API Token 保护；Script Grant 对列表、下载、Raw 和 Preview 等读取请求有单独的 Scope 授权规则。`/api/files/upload` 是专门标记的匿名入口，8086 文件上传服务也不是完整复用基础 Web 的会话认证中间件；因此不要将 `artifact_id`、上传路径或可下载 URL 理解为已包含完整身份校验的能力。对外暴露这些接口时，应同时考虑网络入口、管理员凭据和实际调用方权限。认证方式详见 [Administrator Authentication](admin-auth.md)。
