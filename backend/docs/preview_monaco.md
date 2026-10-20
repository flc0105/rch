# Preview 与 Monaco Editor：跨功能文件预览和编辑

RCH 将多处文件预览和文本编辑集中到同一个 Web 组件。它既是浏览文件的入口，也是 Scripts、Background Jobs 等模块的源码编辑界面。理解这套功能，需要把**预览来源**、**可编辑性**、**实际保存目标**和**内容是否完整**分开：同样显示 Monaco 的文件，可能来自 Client 本机、Server Artifact、Server 脚本资源，也可能只是一次 Job 附件的只读预览。

## 一、统一预览窗口与入口分布

在 Web 顶层，`App.vue` 挂载一份 `PreviewDialog`，其他组件通过事件或回调请求它打开相应内容。`PreviewDialog` 保存当前来源 `previewSource`、文件标识 `previewFilePath`、内容、编辑状态和 Monaco 实例，并按来源分派保存请求。由此各模块能够复用相同的编辑体验，却**不共用保存地址**。

| 功能入口 | 打开时的数据来源 | 文本编辑模式 | Save 实际写入目标 |
| --- | --- | --- | --- |
| **Remote Files** 文件 Preview | `POST /api/connections/{client_id}/remote-files/preview`；先从指定 Client 传至 Server 预览 Artifact | 先只读；内容完整且编码可无损识别时可 Edit | `POST /api/connections/{client_id}/remote-files/save`；**原 Client 上原路径** |
| **Artifacts**（含 `files`、`shared_files`、`previews`、`command_output` 等适用文件） | `GET /api/artifacts/{artifact_id}/preview` | 文本、未截断且编码可无损识别时可 Edit | `PUT /api/artifacts/{artifact_id}/content`；**Server Artifact 文件** |
| **Shared Files → 新建文件** | 在 Web 创建空 Monaco 模型 | 直接可编辑 | `POST /api/files/upload`；创建 `shared_files` Artifact，之后切换为 Artifact 编辑来源 |
| **Script Library → 新建 / 编辑 Python Script** | 默认脚本模板，或 `GET /api/scripts/download?name=...` | 直接可编辑 | `POST /api/scripts/save`；**Server 脚本资源** |
| **Background Jobs → 新建 / 编辑 Job 模块** | 默认 Job 模板，或 `GET /api/jobs/download?name=...` | 直接可编辑 | `POST /api/jobs/save`；**Server Job 脚本资源** |
| **External Tools → Metadata 编辑** | External Tools Metadata 内容 API，显示为 JSON | 直接可编辑 | `externalToolsApi.saveExternalToolMetaContent()` 对应的 Metadata 保存 API |
| **Background Job 产生的文件 / 附件 Preview** | Artifact ID 或文件自身提供的 `preview_url` | 可以显示通用预览界面；**不等同于 Job 源码编辑** | 当前入口没有单独设置稳定的 Job 附件回写来源；**不能保证编辑后有正确保存通道** |

**必须区分**：`server_script` 与 `background_job` 在这里分别指 Server 保存的 Script/Job **源代码文件**，不是在 Client 上执行脚本时任意生成的远程文件。Script、Job 的创建或编辑虽然从设备相关界面进入，其保存地址仍是 Server 自己的资源目录。另一方面，Remote Files 的 Preview 会产生一份 Server 缓存，但保存时指向原始远端文件，不是修改那份缓存。

Artifact 对象可能从普通文件列表、终端运行结果、通知动作或 Job 输出进入预览；只要最终传入有效 Artifact ID，读取的是同一套 Artifact Preview 服务，不应把这些 UI 入口算作不同编辑器。

## 二、一个文件是如何显示到 Monaco 的

预览窗口根据统一的响应数据建立视图。典型文件预览数据包含以下字段：

```json
{
  "type": "text",
  "name": "example.py",
  "content": "print('hello')\n",
  "encoding": "utf-8",
  "editable": true,
  "truncated": false,
  "artifact_id": "an-artifact-id"
}
```

- `type` 决定显示文本、图片或不支持格式的占位信息。只有 `text` 才创建 Monaco 实例。
- `name` 用作标题和语言识别依据；`content` 是编辑器的初始文本。
- `truncated` 和 `editable` 共同决定 Edit 是否可用：内容必须完整且能严格无损解码。`encoding` 由 Server 对原始字节判断，并用于原编码写回。
- `image` 类型改为读取 `url`，如果附带 `image_info` 则允许打开图片信息弹窗；`unsupported` 不会偷偷尝试用 Monaco 打开二进制内容。

对普通 Artifact 文本，预览服务根据文件扩展名和 MIME 推断预览类型；它最多向浏览器发送前 **512 KiB（524,288 字节，默认可配置）**范围内的完整字符文本；编码校验使用增量解码器流式检查**整份文件**，所以即使截断边界落在 UTF-8 多字节序列或 UTF-16 字符中间，也不会错误地显示 `unknown`。超过预览限额设置 `truncated=true`，并在可见文本后补上截断提示，避免超大文本直接进入浏览器。

读取先尝试严格识别 UTF-8、UTF-8 BOM 和带 BOM 的 UTF-16 LE/BE，只有解码成功且不含明显二进制控制字符、内容未截断时才允许编辑。未知编码文件仍可用替换字符进行**只读**预览；替换后的文本绝不能保存。预览截断发生于字节层，因此即使编码可识别，截断内容也不可编辑。

### Remote Files 有额外的传输阶段

远程文件不是通过浏览器直接读取 Client 的磁盘。它经历：

```text
Remote Files 选中一台 Client 上的文件
    → POST remote-files/preview
    → Server 建立 Transfer（client_to_server_preview）
    → Client TransferManager 读取文件并上传
    → Server 将文件记录为 previews Artifact
    → ArtifactPreviewService 识别类型并构造 payload
    → Browser 显示 Monaco 或图片
```

这种预览缓存与持久 Shared Files 不同。它属于 `previews` 分类，可以在 Server 启动清理中被清除。预览传输完成也不意味着原文件后来没有被其他程序修改。

若随后 Edit → Save，使用的是打开预览时记住的 **`previewRemoteClientId` 与 `previewFilePath`**，即使用户在别处切换了当前选中的设备，也不会因为全局设备选择变化而把文件写到另一台 Client。

## 三、Monaco 的实际能力和 UI 操作

Web 使用 `monaco-editor` 的 ESM 编辑器 API，在组件内部建立/复用 Monaco Editor。界面先默认只读，再通过按钮切换是否可修改；脚本源码和新建文件等入口则可以直接以编辑模式启动。

### 只读 Preview、Edit 与 Save

普通文本的工具栏显示 **Copy、Edit**（Edit 仅在可无损编辑时出现），未知编码或截断内容只有 Copy。全屏图标在右上角标题栏关闭按钮旁边，与 Screen View 一致。选择 Edit 后切换为 **Save、More、Cancel**；Paste、Clear、Reload 在 More 下拉菜单里。它们的含义如下：

| 操作 | 实际行为或限制 |
| --- | --- |
| **Copy** | 读取当前 Monaco 内容并复制，优先 Clipboard API，必要时使用兼容回退。 |
| **Edit** | 仅完整且经过严格解码的文本才显示；记录编辑前文本，切换 Monaco `readOnly=false`。 |
| **Save** | 读取 Monaco 的 `getValue()`，根据来源调用不同的保存 API；服务器成功返回后退出编辑模式。**没有统一的跨来源保存端点**。 |
| **Paste** | 仅编辑模式；先尝试现代 Clipboard 读取，并为特定浏览器/系统环境提供回退路径。 |
| **Clear** | 仅编辑模式；把当前编辑器内容清空，此时尚未写入磁盘。 |
| **Reload** | 仅编辑模式、未正在保存时重新请求当前来源，更新 Monaco 模型和原始内容快照；**尚未保存的修改会被替换**。新建而未保存的 Shared File 不支持 Reload。 |
| **Cancel** | 恢复上一次加载或保存的文本，退出编辑模式，不写入文件。 |
| **Fullscreen / Exit Fullscreen** | 标题栏图标（紧邻 Close）；调整 Dialog 为 `100vw`、`top=0` 的全屏样式并重新布局 Monaco；**不是浏览器原生 Fullscreen API**。 |

文本右侧显示来源、文件大小、编码标签、语言；仅在截断时额外显示 `Truncated`，未截断不额外显示 `Full content`。无法识别编码只通过原编码标签 `Unknown encoding` 的警告色表示，不另加禁用编辑提示。普通对话框宽度为 `1080px`，顶部间距为 `5vh`。关闭后会重置对话框状态与异步加载序号，以减少旧请求/旧渲染帧对新界面的干扰。

这套 UI 没有实现文件编辑的多用户协同、服务器冲突合并、自动保存、版本树或差异比较；保存是**覆盖当前目标内容**的请求。因此当外部程序也在写同一文件时，应在保存前重新核对其状态。Reload 是主动获取最新内容，但不是自动冲突检测或安全的三方合并。

### 语法语言、搜索、折叠与格式化

语言依 **文件名扩展名**选择：例如 `.py` → Python、`.js` → JavaScript、`.ts` → TypeScript、`.json` → JSON、`.html` / `.css`、`.md` → Markdown、`.yaml`、`.sh`、`.sql`、`.ps1` 等。无法识别时使用 Plain Text。代码中还包含 Java、C/C++、Rust、PHP、Ruby、Lua 等语言映射；**识别语言不等于安装该语言的完整编译/诊断服务**。

前端显式引入 Monaco 的查找、代码折叠、括号匹配、注释、Hover、链接、格式化动作等贡献模块，以及 JSON/CSS/HTML/TypeScript 语言 Worker。因而可使用 Monaco 的搜索、代码折叠、行号、括号与部分语言服务，并可在有格式化提供者的语言模型上使用相应 Monaco 格式化动作。**当前 RCH 没有独立的 “Format” 工具栏按钮；也不能保证每一种扩展名都有可运行的 Formatter。**

编辑器主要参数为：浅色主题 `vs`、字号 13、行号显示、自动换行、缩略图关闭、缩进 4 个空格、`renderWhitespace='boundary'`、`automaticLayout=true`。为了避免在普通预览中出现大量补全弹窗，代码明确关闭了 `quickSuggestions`、触发字符提示、Tab Completion、词汇建议、Snippet 建议与参数提示。因此它是**有高亮和导航能力的通用文本编辑器**，不是提供完整代码智能补全的 IDE。

编辑器在多次打开、切换模式时复用已创建的内容视图，以降低重复初始化与销毁带来的卡顿风险。

## 四、保存到哪里：几个最容易混淆的边界

### 远程文件与 Artifact 的保存语义不同

**Remote Files** 预览经 Server 缓存，保存却走远端命令链：`remote-files/save` → `save_file_content` → Client FileSystemService 根据文件真实编码验证后，将完整编码好的字节写入**已经存在的原路径**；目标为目录会拒绝。该路径没有与预览时文件内容绑定的 ETag、修改时间校验或自动冲突保护。保存也不自动为原文件建立备份。

**Artifact** 则把内容写进 `artifact_id` 对应的 Server 文件，并尝试更新 Artifact 元数据的大小和更新时间；它不会同步最初的 Client 文件，也不意味着创建新的 Artifact ID。对于不属于文本的 Artifact，服务端会拒绝内容编辑。`previews` 分类的临时内容即使被改动，也可能在后续缓存清理中消失。

**Shared File 新建**并非先创建空 Artifact：用户在 Monaco 中输入正文，再通过 `Blob` / `FormData` 以 UTF-8 上传至 `/api/files/upload`，分类 `shared_files`。创建成功后组件将来源切换为 `artifact`，之后保存将使用 Artifact 更新接口。

### 脚本源码、Job 源码与 Job 附件

Script Library 在 Server 脚本资源中读取 `.py`，使用专门的 `/api/scripts/save`；Background Jobs 的 **Job 模块源码**使用 `/api/jobs/save`。新建时可以插入各自的示例模板；保存后组件通过事件通知脚本列表或 Job 模块列表刷新。**保存源码不等于执行 Script 或启动 Job**。

Background Job 生成的文件附件可能也提供 Preview，但它的 `previewBackgroundJobFile()` 只是使用 Artifact 预览地址打开内容，不像“编辑 Job 模块源码”那样设置一个专用的可靠保存目标。通用工具栏的 Edit 条件只检查是否为完整文本；**不能因此认定每个 Job 附件都能够回写到生产它的 Job 或原始 Client 路径**。面对这类附件，应优先将它视为预览/下载入口。

### External Tools Metadata

External Tools 的 Metadata 编辑直接以 JSON 文本打开共用 Monaco，保存时调用专门的 Metadata 内容 API，并在成功后通知 External Tools 列表更新。它不同于 External Tools 的 **Preview Command**：后者只是展示即将启动的命令参数，不是文件内容编辑器。更完整的 Metadata 结构及启动规则见 [External Tools](external_tools.md)。

## 五、编码：确定性识别、未知只读、按原编码写回

无需第三方编码检测库，也没有自动猜测编码或编码选择器。普通 Remote Files 和 Artifact 文本预览由 Server 基于**文件原始字节**识别，采用 Python 标准库严格解码：

| 字节格式 | 预览响应 `encoding` | 编辑与保存 |
| --- | --- | --- |
| 严格合法 UTF-8（包括 ASCII） | `utf-8` | 可编辑；以 UTF-8 写回 |
| UTF-8 BOM (`EF BB BF`) | `utf-8-sig` | 可编辑；写回保留 BOM |
| UTF-16 LE BOM (`FF FE`) | `utf-16-le` | 可编辑；写回保留原字节序与 BOM |
| UTF-16 BE BOM (`FE FF`) | `utf-16-be` | 可编辑；写回保留原字节序与 BOM |
| 无法严格解码、无 BOM 的其他编码、明显二进制内容 | `unknown` | 仅供只读预览，不显示 Edit |

无 BOM 的 UTF-16 不进行猜测；GBK、Shift-JIS 等编码不进行自动转换。仅包含 ASCII 字节的文件天然也满足 UTF-8 严格解码，无法从原始字节唯一证明它采用哪种单字节编码。截断预览即使编码确定，`editable` 也必定是 `false`。

Server 在预览响应中返回 `content`、`encoding` 和 `editable`；Web 的 Monaco 只消费 Unicode 字符串，编码标签取自服务端 codec，而不再根据字符串内容猜测。未知编码预览可能含 `�`，但其 `editable=false`，用户不能从 UI 启动 Edit。

保存时 Web 将确定的 codec 传给 Artifact 或 Remote Files 的对应保存入口；真正写文件的 Server/Client 端重新检查**当前目标文件**是否仍可严格解码且 codec 一致，再将全部内容编码为字节，成功后才打开目标进行覆盖。编码不匹配、编码失败、未知编码和无法表示的字符均直接报错，文件不会因编码错误被截断，也不会隐式回退为 UTF-8。编码校验不等同于磁盘写入中断恢复，也不提供多用户编辑冲突合并。

新建 Shared Files、Script Library、Background Jobs 模块源码和 External Tools Metadata 继续沿用各自明确的 UTF-8 文本协议，不增加编码选择。

## 六、图片预览：和文本共用窗口，但不是 Monaco

`ArtifactPreviewService` 对常见图片后缀（如 PNG、JPG/JPEG、GIF、WebP、BMP），以及 MIME 可识别的 `image/*` 返回 `type=image`、Raw URL 和可选的 `image_info`。窗口使用 `<img>` 展示，并提供：

- **Open Original**：浏览器新标签页打开当前预览 URL；对 Remote Files 来说可能是**已上传到 Server 的预览副本**，不是直接访问 Client 的本地磁盘。
- **Image Info**：仅当 Server 成功提取 `image_info` 时显示，另开一个详情弹窗，展示宽高、格式、色彩模式、文件字节数，以及可读取的相机厂商、镜头、拍摄时间、曝光时间、ISO 等 EXIF 字段。Pillow 不可用或解析失败时信息可能为空，但这不必让整个图片预览失败。

远端图片上传预览前，Client 的 `PreviewImageService` 可以根据 `PREVIEW_IMAGE_COMPRESS_ENABLED` / `PREVIEW_IMAGE_COMPRESS_QUALITY` 尝试创建较小的临时预览图，**默认关闭**。启用后视透明通道等条件选择 PNG 或 JPEG；若处理失败、Pillow 缺失、生成结果反而不更小，就上传原文件。这一可选压缩**只影响预览路径**，不改变普通下载的源文件，也不构成非破坏性图片编辑器。

图片预览没有 Monaco 编辑、Save 文本回写，也没有文本工具栏的 Fullscreen 切换。不能把浏览器打开原图误解为“已经支持裁剪、旋转、缩放保存和图片编码转换”。

## 七、错误处理和维护者检查点

- **预览不是原始文件锁定**：Client 文件在 Preview 与 Save 之间可能被修改或删除；远程保存必须由目标 Client 当前权限和路径状态决定。预览缓存不自动证明文件仍同一版本。
- **只对完整且可无损解码的文本开放编辑**：`truncated=false` 不代表 `editable=true`；保存端仍必须校验原文件 codec、存在性和权限。
- **截断发生在字节层**：字节限额可能切在 UTF-8 或 UTF-16 多字节序列中；增量解码会丢弃显示边界尚未完成的字符，完整文件独立流式验证以确定真实编码。显示的后缀不是原文件内容，不能拿它与编辑器文本一起覆盖原文件。
- **Source 决定业务语义**：新接入 Preview 的功能应显式选择数据来源和保存策略；如果只是只读附件，不应假设通用的 Edit 按钮自然提供回写能力。
- **下载与预览不同**：Download 返回原文件或打包数据，Preview 尽量生成可展示的结构化数据与缓存，两者有不同的大小和生命周期边界。
- **功能名 Preview 有多个含义**：命令执行前的审批 Preview、压缩包 Peek、Daemon Preview Command、图像预览和 Monaco 文件预览不能混为一条接口链路。

扩展一个新的文本编辑入口时，至少核对以下顺序：由谁提供文件内容、采用何种编码解码、是否存在截断、编辑目标是谁、保存是否覆盖源文件、保存失败后 Monaco 如何保持待编辑文本、重新加载是否会抹掉修改，以及业务列表应监听什么刷新事件。多文件类型和权限约束应由真正保存数据的 Server/Client 层再次校验，不能只靠前端隐藏 Edit 按钮。

### 主要实现锚点

- 统一 Web 编辑窗口：`frontend/src/components/PreviewDialog.vue`；顶层入口与事件：`frontend/src/App.vue`。
- 文本/图片判定和内容截断：`backend/server/application/artifact/artifact_preview_service.py`、`backend/server/config/config.py`。
- Remote Files 预览 Transfer 与远端写回：`backend/server/application/artifact/remote_file_service.py`、`backend/client/transfers/manager.py`、`backend/client/commands/common/services/filesystem/file_system_service.py`。
- Artifact 内容更新：`backend/server/application/web/artifact_api.py`；图片信息弹窗：`frontend/src/components/PreviewImageInfoDialog.vue`；图片上传预处理：`backend/client/commands/common/services/filesystem/preview_image_service.py`。
- Scripts、Jobs、Metadata 编辑：`PreviewDialog.vue` 内对应的 `open...Editor` 与 `saveTo...` 分支，各自的 Server 保存 API。

相关文档：[Remote Files](remote_files.md) · [Artifacts](artifacts.md) · [Scripts](scripts.md) · [Background Jobs](background_jobs.md) · [External Tools](external_tools.md) · [File Transfer](file_transfer.md)。
