# Artifacts

Artifact 是保存在 RCH Server 上的文件资源，具有稳定 `artifact_id`。它可以来自 Client 上传、截图、摄像头、剪贴板、远程下载、Script、Job、单次命令输出或用户保存的终端/PTY 日志。Command History 和 Job 可通过 ID 引用同一文件，不重复存储字节内容。

## 文件空间与导航

Artifact Manager 可以从顶部 Banner → Utilities → Artifacts 独立打开，作为 Server 文件中心使用；此入口不要求选择 Client，隐藏“Send to Current Device”等设备操作。从已选择设备的工具栏打开时，仍可使用原有的设备发送操作。两种入口共用 Saved / Shared 文件、目录、搜索、预览、下载和管理能力。

Artifact Manager 有两个一级空间：

- **Saved Files**：Server 保存的文件，可按设备、目录和名称查看。默认打开 **All Files**，按创建时间降序显示。设备筛选是可选的；设备离线不影响 Server 上已保存的文件。
- **Shared Files**：Server 上跨设备复用的文件，支持创建、上传与发送到指定 Client。它不按某一台设备归属。

两个空间共用文件存储和 SQLite 目录机制，但用户需要明确选择共享空间才能让文件走 Shared 的发送操作；移动目录不能改变共享范围。只有 Shared Files 可以新建、重命名与删除自定义目录；Saved Files 的目录结构固定，只有预设目录。**Create File / Upload 只在 Shared Files 显示**，Saved Files 的文件仅通过截图、下载、脚本/Job 输出、剪贴板、命令/终端保存等正式保存动作产生。Shared 文件创建入口使用现有编辑器流程。

Saved Files 预设目录为：`Screenshots`、`Webcam`、`Downloads`、`Clipboard`、`Script Files`、`Job Files`、`Command Output`、`Terminal Logs`，另有 `Inbox` 作为未明确指定来源时的默认目录。Saved Files 不能创建、重命名或删除目录；Shared Files 的自建目录支持嵌套、重命名和空目录删除。Saved 目录是不可移动的来源分类，`source_kind` 是 Saved 文件唯一的持久归类字段；目录 ID 由 `source_kind` 推导，不能 Move。Shared 的 `source_kind` 与 `folder_id` 独立，允许在共享目录间移动。UI 不再使用重复的 Source 筛选，正式 Artifact 数据也不再保存 `category`。

首次启动新规则前请备份 `catalog.sqlite3` 和 Artifact 实体文件。Catalog 会将旧 Saved 目录引用清空并以文件的规范 `source_kind` 决定显示位置，过时的 Saved 目录 ID 不再保留；Shared Files 的目录关系不受影响。来源字段不合法的记录会触发明确错误，需要在停服备份后处理。

预设分配遵循当前生产来源：截图上传进 Screenshots，摄像头进 Webcam，远程与浏览器下载进 Downloads，剪贴板进 Clipboard，Script SDK 生成的实体文件进 Script Files，Job 产出的实体文件进 Job Files，单次命令、Script 与 Job 的执行输出快照统一进 Command Output，用户显式保存的 Web Terminal 与 PTY 日志进 Terminal Logs。无法识别来源的普通上传进 Inbox；Script SDK 默认为 Script Files。**所有普通文件都使用同一套 Catalog，不再为来源建立各自的独立 Tab。**

## SQLite、实际文件与备份

**SQLite 是唯一的 Artifact 元数据源。** Catalog 存在 `runtime/web_files/artifacts/catalog.sqlite3`，两张业务表分别管理文件记录和逻辑目录。元数据包含 `artifact_id`、`scope`、`source_kind`、设备和命令/Job 关联信息、创建时间及文件路径；只有 Shared Files 持久存储 `folder_id`。Saved Files 的目录 ID 读取时根据 `source_kind` 生成。其他 RCH 业务仍使用 `runtime/rch.db`，Artifact Catalog 单独存放以隔离文件管理的数据和备份边界。

新文件内容保存到 `runtime/web_files/artifacts/objects/`，存储名包含随机后缀。`original_name` 用于显示和下载，`stored_name` 对应磁盘文件；**Rename 只更新显示名，Shared Move 只更新目录 ID**，不会移动大文件，也不会改变稳定的 Artifact ID 或 `/api/artifacts/{id}` URL。Preview 缓存内容继续在独立 `previews/` 路径里，由 Server 启动清理规则管理；Preview 是操作，不在 Saved Files 或 Shared Files 中作为永久目录展示。

恢复数据必须同时备份 SQLite Catalog 和 Artifact 文件内容，且应在停服状态下备份以保证二者一致。只备份 SQLite 会缺少内容；只备份文件则缺少 ID、来源和目录关联。当前服务使用 `saved_path` 检查文件可用性，文件已经不在磁盘上时，列表可标记 `File removed`。

### 现有 `.meta.json` 的一次性迁移

此重构**不进行长期双写，也不会在运行时回退到 `.meta.json` 扫描**。旧数据需要停服后一次性导入，文件本体保持原位，原始 Artifact ID 和关联关系保留。部署顺序：

1. 停止 Server（HTTP、独立 WebSocket 和文件上传服务），备份整个 `backend/runtime/web_files/artifacts/`。
2. 在项目根目录覆盖 v10 增量补丁（不要先启动 Server）。
3. 在 `backend/` 目录运行 `python scripts/migrate_artifact_metadata.py` 预览旧元数据数量和异常。
4. 运行 `python scripts/migrate_artifact_metadata.py --apply`，确认 `invalid=0`，并检查数据库记录数量、附件能否按 ID 读取。
5. 确认备份及导入结果后，可用 `python scripts/migrate_artifact_metadata.py --apply --remove-sidecars` 清理旧的 `.meta.json`。脚本不会删除文件内容。
6. 重新启动 Server 和 Web，验证 Saved/Shared 的文件及来源目录。

脚本采用幂等导入：已有相同 ID 且路径一致的记录跳过；同 ID 路径冲突、目标文件缺失或越界会计入 `invalid` 并退出失败。导入新 Catalog 后运行期不依赖这些旧旁车文件。未来新建文件直接写 SQLite。

## 访问、预览和编辑

| 操作 | 行为 |
|---|---|
| `/api/artifacts` | 返回文件列表、设备列表和逻辑目录；支持 `scope`、`folder_id`、`machine_id`、`source_kind`、`search`；默认排除 Preview 临时缓存 |
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
| `/api/files/upload` | 上传文件，可传入 `folder_id` 指定当前空间中的目录 |
| `/api/artifacts/command-output/save` | 按既有 Text/JSON 协议保存命令、Script、Job 或终端输出 |
| `/api/artifacts/{id}/send-to-client` | 仅 Shared Files 可提交设备下发任务 |

预览会使用文件签名识别图片、ZIP 和文本；文本查看仍有 512 KiB 预览上限，大于上限时不允许直接编辑覆盖。ZIP 预览使用 `zip-peek`、`zip-entry` 读取结构和条目，不解压覆盖原文件。Remote Files 的 Preview 是独立的临时下载行为，在请求携带当前 `X-Tab-Id` 后，会显示在当前标签页的 Transfer Center Recent 中；这类普通预览仍不自动制造长期 Activity 下载记录。

## SDK 与来源分类

Client Script SDK 使用 `artifact.save(path, folder=..., extra=...)` 和 `artifact.upload(path, folder=...)`，`folder` 表示目标虚拟目录名。SDK 在脚本执行上下文中默认保存到 **Saved Files / Script Files**；例如指定 `folder='Screenshots'` 则改存到截图目录。Job 产出的实际文件默认进 **Job Files**；普通来源未知的非 SDK 上传进入 **Inbox**。对于 `type='shared_files'`，默认写到 Shared Files 根目录；`folder` 可填写已存在的共享文件夹路径。Saved Files 仅允许九个固定来源目录，非法目录会在写入实体文件前拒绝。`source_kind` 是 Saved 文件的最终归类字段；明确指定 `folder` 就确定该字段，未指定时使用生产入口的默认目录。Shared 保留独立的来源与目录字段。

**Command Output** 收纳单次命令、Script 和 Job 的执行输出快照（含 Text/JSON）；**Script Files / Job Files** 收纳脚本与 Job 实际生成并上传的文件；**Terminal Logs** 收纳整个终端或 PTY 会话的显式保存。文件名和 Job/Command 关联元数据仍按各自来源保留。

```python
from client.runtime.sdk import artifact

script_file = artifact.save('./report.txt')                   # Saved / Script Files
screenshot = artifact.upload('./shot.png', folder='Screenshots') # Saved / Screenshots
shared = artifact.save('./tool.zip', type='shared_files', folder='Team/Tools')
```

自动创建的文件采用 `类型_yyyyMMdd_HHmmss[_简短标识].扩展名`：截图使用 `screenshot_...`、摄像头 `webcam_...`、自动上传的相册照片 `photo_...`、单次命令结果 `command_output_..._首个命令词`、脚本执行输出 `script_..._脚本名`、Job 消息快照 `job_output_..._Job名`，整个终端/PTY 导出分别使用 `terminal_output_...`、`pty_output_...`。命令词摘要使用通用 `build_command_name`，不按特定命令维护特殊规则；生成时间使用各生产端的本地时间。明确指定的文件名、剪贴板原始文件名和远程下载原始文件名保持原样。`extra.origin` 记录截图产生的入口（截图命令、Screen View、Script 或 Job），与决定 Saved 目录的 `source_kind` 分开。

文件下载与发送到 Client 的实际进度仍由 File Transfer 管理；`artifact_created` 表示 Server 已登记文件，`file_transfer_lifecycle` 表示传输生命周期，二者是不同事件。Transfer Center 的 Recent 和长期 Activity 也遵守各自的记录范围，参见 [File Transfer](file_transfer.md)。
