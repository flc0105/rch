# Artifacts

Artifact 是保存在 RCH Server 上的文件资源，具有稳定 `artifact_id`。它可以来自 Client 上传、截图、摄像头、剪贴板、远程下载、Script、Job、单次命令输出或用户保存的终端/PTY 日志。Command History 和 Job 可通过 ID 引用同一文件，不重复存储字节内容。

## 文件空间与导航

Artifact Manager 可以从顶部 Banner → Utilities → Artifacts 独立打开，作为 Server 文件中心使用；此入口不要求选择 Client，隐藏“Send to Current Device”等设备操作。从已选择设备的工具栏打开时，仍可使用原有的设备发送操作。两种入口共用 Saved / Shared 文件、目录、搜索、预览、下载和管理能力。

Artifact Manager 有两个一级空间：

- **Saved Files**：Server 保存的文件，可按设备、目录和名称查看。从设备工具栏打开时默认筛选当前设备；从顶部 Utilities 独立打开时默认查看全部设备。切换设备会同步更新 Saved 文件数量与列表；Shared Files 数量不受设备筛选影响。设备离线不影响 Server 上已保存的文件。
- **Shared Files**：Server 上跨设备复用的文件，支持创建、上传与发送到指定 Client。它不按某一台设备归属。

两个空间共用文件存储和 SQLite 目录机制，但用户需要明确选择共享空间才能让文件走 Shared 的发送操作；移动目录不能改变共享范围。只有 Shared Files 可以新建、重命名与删除自定义目录；Saved Files 的目录结构固定，只有预设目录。**Create File / Upload 只在 Shared Files 显示**，Saved Files 的文件仅通过截图、下载、脚本/Job 输出、剪贴板、命令/终端保存等正式保存动作产生。Shared 文件创建入口使用现有编辑器流程。

Saved Files 共有九个预设分类，`category` 与目录严格一对一；分类值与显示目录名如下：

| category | Saved 目录 |
|---|---|
| `screenshots` | Screenshots |
| `webcam` | Webcam |
| `downloads` | Downloads |
| `clipboard` | Clipboard |
| `script_files` | Script Files |
| `job_files` | Job Files |
| `command_output` | Command Output |
| `terminal_logs` | Terminal Logs |
| `inbox` | Inbox |

`category` 输入大小写不敏感，按固定值规范化；缺失或不在九种之内均归入 `inbox`。Saved 目录 ID 恒为 `saved:<category>`，读取时由分类计算，不能移动或自行创建目录。Shared Files 不存在 `category`，仅通过目录 ID 管理自建共享目录（允许嵌套、重命名和移动文件）；额外上传来源如有需要放入结构化的 `extra`。

预设分配遵循当前生产来源：截图上传进 Screenshots，摄像头进 Webcam，远程与浏览器下载进 Downloads，剪贴板进 Clipboard，Script SDK 生成的实体文件进 Script Files，Job 产出的实体文件进 Job Files，单次命令、Script 与 Job 的执行输出快照统一进 Command Output，用户显式保存的 Web Terminal 与 PTY 日志进 Terminal Logs。未知类别或未指定类别的上传统一进 Inbox；Script SDK 需要显式传 `category=script_files` 才进入 Script Files。**所有普通文件都使用同一套 Catalog，不再为来源建立各自的独立 Tab。**

## SQLite、实际文件与备份

**Artifact 元数据统一保存在 Server 的 `runtime/rch.db`。** 其中 `artifact_entries` 管理文件记录，`artifact_folders` 管理逻辑目录；文件本体继续位于 `runtime/web_files/artifacts/`。元数据包含 `artifact_id`、`artifact_type`、设备和命令引用、保存时间 `saved_at` 及相对文件路径；Job 关系由 `background_job_files` 记录。`artifact_entries.category` 仅对 Saved Files 非空，Shared/Preview 为 NULL 且对外元数据没有 `category`；只有 Shared Files 持久存储 `folder_id`。Saved Files 的目录 ID 读取时由 `category` 推导。所有元数据访问共用 `RchDatabase` 的连接、事务与 Schema 校验。

Saved、Shared 和 Preview 的文件体统一保存到 `runtime/web_files/artifacts/objects/<artifact_id 前两位>/<artifact_id>`，使用无扩展名的 32 位十六进制 Artifact ID。例如 `objects/a7/a7f9032b8c41e569d037ac0e5216b844`。`artifact_id` 在分配文件路径时生成，SQLite 的 `saved_path` 保存该相对路径；分类、设备和原文件名都不参与物理路径。`original_name` 负责显示、下载文件名和内容类型识别；Info 中展示 Saved Path，不再展示 Stored Name。

**Rename 只更新显示名（支持 Unicode，拒绝路径分隔符及控制字符），Shared Move 只更新目录 ID**，不会移动文件或改变 Artifact ID。`/raw` 根据 `original_name` 推导 MIME 类型，普通图片和纯文本可内联显示，其余内容按附件发送。Preview 同样使用 ID 路径；Server 启动清理依据启动时的 Preview 元数据快照移除对应文件和记录，不遍历整个 `objects/`。`upload_tmp/` 是独立的文件传输暂存区。

恢复数据必须同时备份 `rch.db` 和 Artifact 文件内容，且应在停服状态下备份以保证二者一致。只备份 SQLite 会缺少内容；只备份文件则缺少 ID、来源和目录关联。当前服务使用 `saved_path` 检查文件可用性，文件已经不在磁盘上时，列表可标记 `File removed`。


### Artifact 保存时间、来源与关联

每条 Artifact **仅有一个保存时间**：`saved_at` 是 `artifact_entries` 的时间列，也是返回给前端的顶层字段；它是 Server 登记文件的时间。`extra` 不再存第二份 `saved_at` 或 `created_at`。`artifact_folders.created_at` 是另一张表的目录创建时间，Agent Outputs 等其他业务的 `created_at` 也不受影响。

`category` 决定 Saved 的九个固定目录，不负责描述产生入口。`extra.saved_from` 记录入口，不再接受重复的 `origin/source/source_kind` 或把 Job ID 复制进去。实际来源信息按需要记录，不强迫所有文件带相同字段：

| 保存入口 | `extra.saved_from` | 可选上下文 |
|---|---|---|
| `saveout` | `saveout` | `source_command`、`started_at`、`finished_at`、`final_status` |
| Terminal 单块保存 | `terminal_output` | `source_command`、Script 的 `script_path` 与可用的执行时间/状态 |
| Terminal JSON Viewer | `terminal_json_viewer` | 同上；将当前展示的完整 JSON 原文保存为文本输出（`.txt`） |
| Terminal 工具栏 / PTY 工具栏 | `terminal_toolbar` / `pty_toolbar` | 无须伪造执行命令 |
| Job Detail → Save Output | `background_job_detail` | 可用的执行时间/状态；Job 关系从关联表查询 |
| RCH Client 截图、摄像头、下载命令 | `client_command` | 真实 RCH `source_command` |
| Screen View 的截图 | `screen_view` | `jpeg_quality`（使用的 JPEG 质量） |
| Clipboard 图片和文件下载 | `clipboard` | 可选 `source_path` / 多路径 `source_paths` |
| Remote File Browser 下载 | `remote_file_browser` | `source_path` 或 `source_paths`，ZIP 条目可加 `source_entry` |
| Script SDK / Job 自动文件 | `script_sdk` / `background_job` | 已知时的 `script_path`，Job 关系另存关联表 |

输出保存 API 的 `output_kind` 仅决定命名：`script` 以真实 `script_path` 叶子名命名，`job` 以稳定 `job_key` 命名，普通命令用命令摘要；它不是 Saved `category`，也不会写进 `extra`。Terminal/PTY 整段保存到 `terminal_logs`，其余六类输出保存操作归入 `command_output`。

Job ↔ Artifact 的正式关联是 `background_job_files(job_id, artifact_id)`。Job 文件自动上报和 Job Detail 手动保存均登记此关联；Artifact 查询时投影 `linked_jobs`，不重复写入 Artifact 持久化元数据。删除 Artifact 与 Job 各自遵守现有生命周期与清理规则。

## 访问、预览和编辑

| 操作 | 行为 |
|---|---|
| `/api/artifacts` | 返回文件列表、设备列表和逻辑目录；支持 `scope`、`folder_id`、`machine_id`、`category`、`search`；默认排除 Preview 临时缓存 |
| `/api/artifacts/{id}/download` | 用显示名下载文件 |
| `/api/artifacts/{id}/raw` | 直接传输文件字节 |
| `/api/artifacts/{id}/preview` | 文本、图片、归档等预览描述 |
| `/api/artifacts/{id}/content` | 编辑 Server 上可编辑文本并更新 SQLite 大小与时间 |
| `/api/artifacts/{id}/rename` | 更改显示名，实际文件路径不变 |
| `/api/artifacts/{id}/move` | 仅 Shared Files 内移动到指定共享目录 ID；Saved 拒绝移动 |
| `/api/artifacts/{id}`（DELETE） | 删除内容和 SQLite 记录 |
| `/api/artifacts/clear` | 按 `scope`、目录和可选设备范围删除文件 |
| `/api/artifacts/folders`（POST） | 仅在 Shared Files 创建目录（可选父目录） |
| `/api/artifacts/folders/{id}/rename` | 仅在 Shared Files 重命名自建目录 |
| `/api/artifacts/folders/{id}`（DELETE） | 仅在 Shared Files 删除空的自建目录 |
| `/api/artifacts/create` | 仅允许在 Shared 创建空文本文件 |
| `/api/files/upload` | Saved Files 传 `category`（不传或未知值归 Inbox），按固定映射选择目录；Shared Files 不允许传 `category`，可传 `folder` 或 `folder_id` 指定现有共享目录；Preview 不需要分类或目录 |
| `/api/artifacts/command-output/save` | 用 `output_kind=command/script/job` 选择文件名，`output_format=text/json` 选择内容格式；Saved 的 `category` 由保存入口决定 |
| `/api/artifacts/{id}/send-to-client` | 仅 Shared Files 可提交设备下发任务 |

预览会使用文件签名识别图片、ZIP 和文本；文本查看仍有 512 KiB 预览上限，大于上限时不允许直接编辑覆盖。ZIP 预览使用 `zip-peek`、`zip-entry` 读取结构和条目，不解压覆盖原文件。Remote Files 的 Preview 是独立的临时下载行为，在请求携带当前 `X-Tab-Id` 后，会显示在当前标签页的 Transfer Center Recent 中；这类普通预览仍不自动制造长期 Activity 下载记录。

## SDK 与来源分类

Client Script SDK 使用 `artifact.save(path, category=..., extra=...)` 和 `artifact.upload(path, category=...)` 上传 Saved 文件；不指定 `category` 时归入 `inbox`，指定 `category='script_files'` 进入 Script Files，指定 `category='screenshots'` 则保存到 Screenshots。Job 的实体文件默认传 `category='job_files'`；普通非 SDK 上传未传类别时进 `inbox`。分类字段按上表匹配，仅此九种有效，未知值也直接保存到 Inbox。Shared 使用 `artifact.save(path, type='shared_files', folder=...)`，默认写入共享根目录，`folder` 指定已存在的共享路径；Shared 不允许传 `category`。内部 SQLite 只储存 Saved 的规范 `category`，Shared 只持久化共享 `folder_id`；文件实体不因分类逻辑变化而移动。

**Command Output** 收纳单次命令、Script 和 Job 的执行输出快照（含 Text/JSON）；**Script Files / Job Files** 收纳脚本与 Job 实际生成并上传的文件；**Terminal Logs** 收纳整个终端或 PTY 会话的显式保存。文件名按脚本实际路径叶子名和 Job 的稳定 `job_key` 生成。命令引用使用 Artifact 顶层的 `source_command_id`；Job 关联只存在于 `background_job_files`，Artifact 详情可按关系投影，不在 Artifact 顶层或 `extra` 中重复保存 Job ID/Key。

```python
from client.runtime.sdk import artifact

script_file = artifact.save('./report.txt', category='script_files')  # Saved / Script Files
screenshot = artifact.upload('./shot.png', category='screenshots')  # Saved / Screenshots
shared = artifact.save('./tool.zip', type='shared_files', folder='Team/Tools')
```

自动创建的文件采用 `类型_yyyyMMdd_HHmmss[_简短标识].扩展名`：截图使用 `screenshot_...`、摄像头 `webcam_...`、自动上传的相册照片 `photo_...`、单次命令结果 `command_output_..._首个命令词`、脚本执行输出 `script_..._脚本名`、Job 消息快照 `job_output_..._job_key`，整个终端/PTY 导出分别使用 `terminal_output_...`、`pty_output_...`。命令词摘要使用通用 `build_command_name`，不按特定命令维护特殊规则；生成时间使用各生产端的本地时间。明确指定的文件名、剪贴板原始文件名和远程下载原始文件名保持原样。`extra.saved_from` 只描述文件实际保存入口；执行命令用 `extra.source_command` 存储真实命令，Screen View 截图可记录 `extra.jpeg_quality`。多路径自动 Bundle ZIP 统一使用 `bundle_yyyyMMdd_HHmmss.zip`，单目录 ZIP 继续采用 `<目录名>.zip`，用户明确指定的名称不被覆盖。

文件下载与发送到 Client 的实际进度仍由 File Transfer 管理；`artifact_created` 表示 Server 已登记文件，`file_transfer_lifecycle` 表示传输生命周期，二者是不同事件。Transfer Center 的 Recent 和长期 Activity 也遵守各自的记录范围，参见 [File Transfer](file_transfer.md)。
