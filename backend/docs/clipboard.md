# Clipboard

Clipboard 在浏览器操作与远程操作系统剪贴板之间建立按需的数据交换。文本和图像通常可以作为值读写，文件或目录则必须通过可访问的文件实体、暂存区和上传通道传递引用或内容。Client 负责操作本机剪贴板，Server 负责协调传输，浏览器提供 Get / Send 的使用入口。

剪贴板内容具有平台相关的生命周期：一次写入成功只代表远端当前剪贴板状态发生了变化，不等于文件会被永久保存或已经被目标应用成功粘贴。实际设计需区分剪贴板格式、文件搬运和系统原生适配三层。

## 远程剪贴板如何与浏览器交互

```text
Frontend（浏览器）
  Get / Send、内容预览、本地复制、下载、拖放与文件选择
                       ↕ HTTP API / 上传与下载
Server（请求中转）
  按 client_id 定位连接、关联请求 ID、等待结果、暂存上传文件与 Artifact
                       ↕ Client 现有消息连接
Client（远程设备）
  读取或写入系统剪贴板、处理图片、下载暂存文件、恢复目录树
```

用户操作触发一次 Clipboard 请求时，Server 生成独立的 `clipboard_request_id`，通过现有连接向目标 Client 发送 `clipboard_get` 或 `clipboard_set`。Client 完成操作后以 `clipboard_result` 返回成功状态、数据或错误；Server 根据请求 ID 匹配等待者，并把结果返回最初的 HTTP 请求。

Get 包含查询支持能力与读取当前内容两种请求；Send 则按 `kind` 区分 `text`、`image`、`files`。这些操作不经普通前台命令槽，也不要求建立专用 WebSocket 会话，但**仍依赖目标 Client 在线和现有消息连接可用**。请求默认最长等待 **3600 秒**；若目标 Client 断线，Server 会使相关待处理请求以断线错误结束。

一次读取返回的是当前识别到的**一种**剪贴板内容，而不是把操作系统所支持的全部格式同时导出。浏览器打开对话框时，默认进入 Get，先获取目标平台能力，再读取一次内容；点击 Refresh 或重新切回 Get 会重新读取。

## 读取并还原远端内容

### 文本和图像采集

对于文本，Client 从原生剪贴板读取字符串并返回：

```json
{
  "kind": "text",
  "text": "Hello from remote client"
}
```

浏览器以只读文本显示内容。点击 **Copy Local**，尝试调用浏览器的 Clipboard API 写入当前电脑的系统剪贴板，不会修改目标设备；如果浏览器权限阻止自动复制，仍可选中文本手动复制。

对于图片，Client 从原生剪贴板取得图片数据，必要时转换为 PNG，然后上传至 Server 的 Artifact 存储。Get 结果返回 `kind: image` 及图片的 `artifact` 信息，浏览器据此加载预览，并提供 **Copy Local** 和 **Download**。前者尝试将图片写入浏览器本地剪贴板，后者下载图片文件。浏览器不支持图片剪贴板写入或权限被拒绝时，可改用 Download。

图片通过 Artifact 保存，**不是把完整图片字节直接放在 Get 的 JSON 响应中**。每次重新读取图片都可能生成新的 Artifact；关闭窗口不等于删除这些已经保存的记录。

### 文件引用与内容回传

当远端剪贴板提供文件或目录引用时，Client 读取其路径并检查目标是否存在，返回可供显示的名称、大小和目录标记，例如：

```json
{
  "kind": "files",
  "files": [
    {
      "path": "/Users/example/Desktop/report.pdf",
      "name": "report.pdf",
      "size": 204800,
      "is_directory": false
    },
    {
      "path": "/Users/example/Desktop/project",
      "name": "project",
      "size": 0,
      "is_directory": true
    }
  ]
}
```

这里目录的 `size` 为 `0`，不代表目录内容为空。Get 只传递元数据；**不会自动把每个文件搬到 Server**。只有用户按 Download，才会使用远程文件传输功能将实际内容传到 Server，生成下载用的 Artifact，再交给浏览器下载。

| 操作 | 结果 |
|---|---|
| 下载一个文件 | 保持原文件格式，传输并下载该文件 |
| 下载一个目录 | 远端目录打包为 ZIP 后下载 |
| Download All：仅一项 | 沿用该项的下载方式；文件仍是原文件，目录仍是 ZIP |
| Download All：多项 | 将多个文件和/或目录统一打成一个 ZIP 下载 |

多项下载由远程文件传输服务处理，并在 Server 返回 Artifact 后才触发浏览器下载。列表里的路径描述的是**远程设备上的实际文件**；这些文件可能在读取剪贴板后被移动、删除或权限改变，所以稍后下载仍可能失败。文件操作完成后，相关 Artifact 也可能出现在 Server 的文件记录中。

## 将内容写入远端剪贴板

Send 将浏览器中准备的内容送到 Client，由目标平台的原生接口更新系统剪贴板。**一次 Send 只采用一种类型**：文本、单张图片，或者文件与目录集合。附加了文件或图片后，文本输入区会被禁用；移除附件后才能继续发送文本。

### 远端文本和图像写入

发送文本最直接：在 Send 输入框中填写内容，点击 **Send to Target**，Server 转发文本，Client 将其写入目标系统剪贴板。例如请求的数据内容为：

```json
{
  "kind": "text",
  "text": "Hello remote desktop"
}
```

操作完成后，用户可以在目标设备的其他应用中粘贴该文本。这里不需要文件上传，也不会自动在目标设备上执行粘贴动作。

发送图片需要先把图片上传至 Server 的临时文件，再由 Client 根据下载 URL 拉取到本地，将数据转换为目标平台支持的图片剪贴板格式。目标剪贴板写入成功后才回复结果；Server 会在本次请求结束时清理相应的上传临时文件。

**图片通过什么方式进入 Send 区域，会影响它被发送成什么类型：**

- **Read Local Clipboard** 识别到单张图片，或者在 Send 区域粘贴单张图片：使用图片剪贴板流程，目标应用粘贴的是图片数据。
- 通过文件选择器选择图片，或直接拖放图片：当前界面将其作为文件附件，走文件剪贴板流程。目标应用看到的是图片文件的引用，而不一定是图片数据。

Read Local Clipboard 优先尝试读取浏览器系统剪贴板中的图片；没有图片时再尝试文本。浏览器剪贴板访问受浏览器权限和安全上下文约束，失败后可以手动粘贴或选择文件，不影响远端协议本身。

### 文件集合的组织与落地

Send 可以通过文件选择器添加多个文件，或将文件、目录拖入对话框。对于目录，浏览器会递归收集子目录、文件及其相对路径，形成 Manifest。它不仅记录实际文件，也明确记录目录条目，因此能够重建空目录。例如：

```json
{
  "roots": ["project", "notes.txt"],
  "entries": [
    {"type": "directory", "path": "project"},
    {"type": "directory", "path": "project/assets"},
    {"type": "file", "path": "project/assets/logo.png", "upload_index": 0},
    {"type": "file", "path": "notes.txt", "upload_index": 1}
  ]
}
```

其中 `roots` 是最后交给系统剪贴板的顶层项目，`entries` 描述完整目录树，`upload_index` 对应同一 multipart 表单中 `files` 字段的文件顺序。Server 将上传的文件暂存，并把可下载地址与目录结构传给 Client；Client 下载这些文件、恢复目录树，最后将顶层文件或目录的路径写入原生剪贴板。

目录递归读取依赖浏览器提供的文件系统 Entry API；不支持它的浏览器可能无法还原拖入文件夹的完整树结构。当前文件选择器支持多文件选择，但没有单独提供“选择文件夹”模式。

**Send 文件成功，只表示目标剪贴板包含可粘贴的文件引用，不表示文件已被粘贴到某个目标目录。** 用户仍需在目标设备的文件管理器或其他支持文件粘贴的应用中执行粘贴。若发送失败，应区分文件上传、Client 下载、目录构建和原生剪贴板写入四个阶段。

## 操作系统剪贴板适配

| Client 平台 | 文本 | 图片 | 文件/目录 |
|---|---|---|---|
| Windows | 支持 | 支持 | 支持 |
| macOS | 支持 | 支持 | 支持 |
| iOS / Pythonista | 视 Clipboard API 是否可用 | 视 Clipboard API 是否可用 | 不支持 |
| Linux 及其他未适配平台 | 不支持 | 不支持 | 不支持 |

能力查询返回 `platform`、`text`、`image`、`files` 四个字段，前端会显示可用类型，并据此限制不支持的 Send 操作。平台表表示实现范围，不保证当前机器一定满足系统依赖或桌面会话权限。

### 桌面系统能力

Windows 使用系统 Clipboard API，Get 优先识别文件 `CF_HDROP`，其次是图片 `CF_DIB`，最后是 Unicode 文本 `CF_UNICODETEXT`。写入图片时会转换为 DIB；写入文件时则生成系统能识别的 `CF_HDROP` 路径列表，而非把文件内容直接填入剪贴板。

macOS 使用 `NSPasteboard`。Get 优先读取文件 URL，其次读取 PNG/TIFF 图片，最后读取文本；写入文件时将实际文件 URL 交给 Pasteboard，供 Finder 等应用粘贴。TIFF 图片在需要上传展示时会转换为 PNG。

Windows 和 macOS 的文件剪贴板写入均借助独立 Helper 进程执行，最长等待 **15 秒**。直接运行项目时使用随项目提供的 Helper；打包运行时会生成临时 Helper，并要求设备上有可用的系统 Python：Windows 可使用 Python 3 或 Python Launcher，macOS 需要 `python3`。缺少依赖、Helper 超时或没有可访问的桌面剪贴板环境，都会导致文件剪贴板操作失败。

### 轻量运行环境与降级

iOS 使用 Pythonista 的 `clipboard` 接口，文本能力由 `get/set` 决定，图片能力由 `get_image/set_image` 决定。图片写入过程会把下载后的图片读入内存并交给 Pythonista；文件剪贴板明确不支持，能力查询中 `files=false`。

尚未实现原生剪贴板适配的其他平台会返回不支持能力，Get / Send 也会给出 Unsupported 错误；不能因为设备可以运行 Client，就推断其系统剪贴板操作一定可用。

## 文件载体的暂存与清理

Clipboard 涉及的临时内容分布在不同位置，清理时机也不同：

```text
Send 文件/图片
浏览器原始内容 → Server 上传临时文件 → Client 下载/重建 → 远端系统剪贴板

Get 图片
Client 剪贴板图片 → Server Artifact → 浏览器预览、复制或下载

Get 文件/目录
Client 剪贴板路径元数据 → 用户点击 Download → 远程文件传输 → Server Artifact
```

**Server 上传临时文件**仅用于 Send 阶段的中转，接口在请求结束时尝试删除这些文件。Get 图片和下载文件创建的是 Artifact，属于另一类存储，不随 Clipboard 对话框关闭而自动清理。

**Client 文件暂存目录**默认为：

```text
~/.rch/clipboard_staging/
```

每次接收文件使用独立的请求 ID 作为子目录名。Client 将上传文件下载到对应位置、恢复目录层级，再将实际存在的根路径交给原生剪贴板。目录和路径分量会进行安全规范化处理，避免直接把浏览器提交的任意相对路径拼接为落地位置。

这里不能在 Send 成功后立即清空 Client 暂存目录：Windows 的文件剪贴板保存路径列表，macOS 保存文件 URL。如果源文件此时被删除，目标应用之后的粘贴可能无法读取它。因此当前实现主要在 **Clipboard Manager 初始化时**清理旧 Staging，再重新创建根目录，而不是每个 Send 结束就删除本次传输的文件。

macOS 还需要处理后台 Client 用户与图形桌面登录用户不一致的情况：在能够识别控制台用户时，可以将 `~` 暂存目录定位到该用户的 Home；必要时调整所创建文件和目录的属主与访问权限，使 Finder 等图形应用能够读取。若无法识别登录用户或文件本身权限不满足要求，粘贴依然可能失败。

这意味着：**Send 成功与文件长期可粘贴并不是同一件事**。重启 Client、重新初始化 Clipboard Manager、移动暂存文件或外部清理这些目录，都可能使先前剪贴板中的文件引用失效。

## 浏览器入口和传输协议

### 工具栏交互

选中在线设备后，从工具栏打开 **Clipboard**。打开时默认是 Get；切换到 Send 可以准备内容。设备离线时，工具栏入口不可用。Screen View 内的 Clipboard 按钮会打开同一套功能，不涉及另一种剪贴板协议。

| 界面操作 | 作用 |
|---|---|
| Get / Refresh | 获取或重新读取远端剪贴板内容 |
| Copy Local | 将 Get 中的文本或图片复制到浏览器所在设备的系统剪贴板 |
| Download | 下载 Get 中的一张图片、一个文件或一个目录 |
| Download All | 单项维持原格式，多项合并 ZIP |
| Send / Send to Target | 准备内容并写入目标剪贴板 |
| Read Local Clipboard | 尝试读取浏览器本地剪贴板的文本或图片到 Send 区域 |
| 拖放 / 文件选择器 | 添加文件；支持的浏览器还可通过拖放保留目录层级 |
| Clear | 清空 Send 编辑区，不清空远程系统剪贴板 |

发送成功会显示 Target clipboard updated；这表示剪贴板写入过程返回成功，不表示远程应用已经执行粘贴。发送失败则在界面显示错误。Get 中的 Download 会通过远程文件传输完成，下载 Artifact 成功创建后才触发浏览器下载动作。

### 上传资源和调用协议

这些请求使用普通 Web HTTP API，而不是 Clipboard 专用 WebSocket。所有以下接口都需要 Web 管理会话或有效的受支持认证凭据。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/connections/{client_id}/clipboard/capabilities` | 查询目标支持的剪贴板类型 |
| POST | `/api/connections/{client_id}/clipboard/get` | 读取目标当前剪贴板内容 |
| POST | `/api/connections/{client_id}/clipboard/set-text` | 发送 JSON 文本 |
| POST | `/api/connections/{client_id}/clipboard/set-image` | 上传单张图片并写入目标图片剪贴板 |
| POST | `/api/connections/{client_id}/clipboard/set-files` | 上传文件和目录 Manifest，并写入文件剪贴板 |
| POST | `/api/connections/{client_id}/clipboard/set-artifact-file` | 将已有的 `shared_files` Artifact 发往目标文件剪贴板 |

`set-artifact-file` 是可供其他功能调用的接口；目前 Toolbar Send 自己上传附件，不使用这一入口。需要先确认目标支持文件剪贴板，且指定的 Artifact 类型为 `shared_files`。

直接调用 API 时，可以使用后台配置的管理员 API Token。例如在有权访问 Server 的终端执行：

```bash
SERVER='http://127.0.0.1:5000'
CLIENT_ID='替换为目标Client的client_id'
TOKEN='替换为管理员API Token'

curl -sS -H "Authorization: Bearer $TOKEN" \
  "$SERVER/api/connections/$CLIENT_ID/clipboard/capabilities"

curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  "$SERVER/api/connections/$CLIENT_ID/clipboard/get"
```

第一条读取目标能力，返回类似 `{"platform":"mac","text":true,"image":true,"files":true}` 的数据字段；第二条获取此刻剪贴板的内容。示例中的 `SERVER`、`CLIENT_ID`、`TOKEN` 都必须替换为实际值；Server 地址和端口以真实部署为准。完整响应由 API 统一格式封装，实际内容位于响应的 `data` 字段内。

写入文本使用 JSON 请求：

```bash
curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"text":"Hello Clipboard"}' \
  "$SERVER/api/connections/$CLIENT_ID/clipboard/set-text"
```

这里请求体只需 `text` 字段，Server 会将其转换为内部的 `kind: text` 消息。HTTP 成功返回后，可在目标设备打开文本编辑器并粘贴，确认实际内容。

图片和文件使用 multipart 上传，不能直接把本地文件路径作为 JSON 值交给远端：

```bash
# 上传一张图片并写入远端图片剪贴板
curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -F 'file=@./sample.png' \
  "$SERVER/api/connections/$CLIENT_ID/clipboard/set-image"

# 上传一个文件并写入远端文件剪贴板
curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -F 'files=@./notes.txt' \
  -F 'manifest={"roots":["notes.txt"],"entries":[{"type":"file","path":"notes.txt","upload_index":0}]}' \
  "$SERVER/api/connections/$CLIENT_ID/clipboard/set-files"
```

第一条在 Server 暂存图片、Client 下载后写入图片数据；第二条在 Client 的 Staging 目录中创建 `notes.txt`，再把该路径写入目标文件剪贴板。目录上传时，需在 Manifest 中保留目录及各子文件的相对路径，并确保每个 `upload_index` 对应一个实际上传文件。对目标设备写入剪贴板是有状态操作，重复发送会替换当前剪贴板内容。

下载远端 Clipboard 列表里的文件不使用上述 `clipboard/get` 重新请求数据，而是根据 Get 返回的路径调用远程文件下载接口；单目录和多项组合使用 ZIP 接口，生成 Artifact 后再下载。

## 可粘贴性、权限与失败处理

| 现象 | 检查方向 |
|---|---|
| Get 显示 Empty | 当前剪贴板可能为空，或内容类型未被适配器识别；检查平台能力与是否能手动粘贴 |
| Get 只显示一种类型 | 一次只返回优先匹配的格式，不会同时导出文件、图片和文本的所有表现形式 |
| Get 很快但 Download 较慢 | Get 文件列表仅查询元数据；实际数据传输在 Download 时发生 |
| 文件路径出现在 Get，但下载失败 | 远端原文件可能已移动、删除或权限发生变化 |
| Send 成功却不能粘贴文件 | 检查目标应用是否支持文件粘贴、Client 暂存文件是否还在、图形用户是否具有访问权限 |
| 图片粘贴成“图片文件” | 可能通过文件选择器或拖放进入了 `files` 流程，而非粘贴单张图片的 `image` 流程 |
| Copy Local / Read Local Clipboard 不可用 | 检查浏览器剪贴板权限与安全上下文；文本可手动复制粘贴，图片可下载 |
| macOS 文件 Send 失败 | 检查桌面登录会话、Python Helper、暂存目录归属及访问权限 |
| iOS 文件发送不支持 | Pythonista 只支持可用的文本/图片 API，文件剪贴板未实现 |
| Linux 返回 Unsupported | 当前没有相应平台的剪贴板适配器 |
| Client 连接断开 | 等待中的请求会收到断线错误；恢复连接后重新发起操作 |
| 连续刷新图片产生多个 Artifact | 图片 Get 每次可能重新上传并创建记录；关闭对话框不自动回收这些 Artifact |

**Clipboard 不会主动将两端剪贴板持续同步。** 用户必须显式 Get、Refresh 或 Send；Send 的结果也不能替代目标设备上的实际粘贴。

**文件剪贴板保留的是可读取的文件引用。** Client 暂存目录的清理策略服务于“先写入剪贴板、稍后再粘贴”的操作顺序，但不能保证这些文件被永久保存。若需要把文件稳定存放到目标指定目录，应使用相应文件传输或文件管理功能，而不是把剪贴板暂存目录当作长期存储。

**不占用普通前台命令槽，也不等于传输完全独立。** 剪贴板 Get/Send 仍通过 Client 现有消息处理链与文件上传下载能力进行，系统剪贴板调用、网络传输及大文件操作都可能影响请求完成时间。排查时应区分浏览器权限、Server 临时存储、Client 在线状态和平台原生剪贴板操作四类问题。
