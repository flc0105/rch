# Remote Files

Remote Files 的核心是对在线 Client 文件系统进行按需访问，而不是在 Server 复制一份远程文件镜像。浏览器通过控制请求获取路径内容、提交管理操作，并在需要文件字节时调用相应传输链路；Server 负责协商、暂存 Artifact 和把结果送回界面。

同一套目录访问能力也被 Remote File Picker 用于运行参数选择，但 Picker 返回的是路径输入，不承担完整文件管理操作。目录导航、写入和删除、Artifact、路径选择之间有不同的状态边界，需要按操作的真实落点区分。

## 远程文件系统的访问通路

```text
Frontend（浏览器）
  Remote Files Browser              Remote File Picker
  浏览、搜索、文件管理、预览          浏览、选择文件或目录、返回路径
                    \             /
                      HTTP API
                         ↕
Server（远程文件服务）
  连接定位、请求调度、任务状态、Artifact、传输管理
                         ↕
             Client 已有消息连接
                         ↕
Client（远程设备）
  本机文件系统访问、文件操作、ZIP、内容读写
```

浏览器不直接挂载远程磁盘，也不要求远端开放 SMB、SFTP 等文件服务。一次目录浏览由浏览器请求 Server 的目录 API，Server 通过已建立的 Client 连接执行文件系统查询，再将目录条目、统计和分页信息返回前端。与单纯列目录不同，上传、下载与预览会涉及实际文件内容，使用专门的文件传输服务和 Server Artifact 存储。

远程操作分成两类，影响它们与普通命令的并发关系：

| 类型 | 典型操作 | 执行方式 |
|---|---|---|
| 同步文件操作 | 浏览、搜索、新建目录、重命名、删除、复制、移动、ZIP 管理、保存文本 | 经由 Client 命令执行链，使用普通前台命令槽 |
| 文件内容传输 | Browser 下载、打包下载、预览文件的数据搬运，以及专门的上传流程 | 使用 Client TransferManager / Server TransferService 或对应上传链路，文件数据不塞入前台命令结果 |

**文件搬运不占普通前台命令槽，不等于所有相关 HTTP 请求都立即完成。** 例如下载接口需要等待传输结果，取得 Artifact 才能返回可用的文件记录；网络中断或远端不可读仍会导致失败。任何实时操作都要求对应 Client 在线、具备文件访问权限。

| 功能 | Browser | Picker |
|---|---|---|
| 目录导航、面包屑、Quick Jump、分页 | 支持 | 支持 |
| 单选与多选 | 支持 | 支持，取决于调用方参数类型 |
| 文件名搜索与递归搜索 | 支持 | 不提供 |
| 显示隐藏文件开关 | 支持 | 不提供，固定隐藏 |
| 保存和管理 Pinned Paths | 支持 | 不提供 Pins 管理 |
| 上传文件 | 支持 | 支持单文件上传 |
| 下载、删除、复制、移动、ZIP、预览编辑 | 支持 | 不提供 |
| 将选中路径回填到 Script / Job / Tool 参数 | 不作为主要用途 | 核心用途 |

## 目录定位和导航状态

### 目录枚举和分页游标

选择在线 Client 后打开工具栏的 Remote Files，可以浏览该设备上的目录。初始路径未显式指定时，远程路径解析会从 Client 当前工作目录出发。顶部面包屑可回到任意上级目录，也可直接输入路径跳转；双击文件夹进入下一级，Refresh 则重新读取当前目录。

每次目录查询返回 `current_path`、`parent_path`、`entries`、`summary` 和 `pagination`。一个条目的典型结构如下：

```json
{
  "name": "example.txt",
  "path": "/Users/example/Documents/example.txt",
  "is_dir": false,
  "is_symlink": false,
  "is_hidden": false,
  "size": 2048,
  "modified_at": "2026-10-16 12:00:00",
  "parent_path": "/Users/example/Documents",
  "relative_path": "example.txt"
}
```

`path` 是远端实际路径；`size` 是文件字节数，目录显示为 0；`modified_at` 使用远端设备本地时间格式，不包含可供可靠时区换算的偏移量。`parent_path` 和 `relative_path` 在搜索结果中尤其重要，可用来定位匹配项来自哪个目录。`is_symlink` 是链接标记；目录链接即使可识别为目录，递归搜索也不会继续沿该链接深入。

默认每页 **50 项**，界面可切换 **100 / 200**；Client 接受的单页最大值为 **500**。目录优先于文件，随后按不区分大小写的名称排序。`summary` 汇总隐藏项数、筛选和搜索状态；`pagination` 返回当前页、页大小、可见总数和总页数。

分页是在远端**收集、过滤、排序之后**进行，不是从磁盘按页流式读取。因此包含数十万条目的目录即使只显示第一页，也可能需要较长扫描时间。

Search 按名称进行**不区分大小写的子字符串匹配**，不是文件内容搜索，也不支持将表达式解释为正则。不开启 Recursive 时只检索当前目录一层；开启后会向下遍历目录树、附带匹配项的相对路径。只有存在搜索关键词时才会进行递归搜索。隐藏文件可通过 Show Hidden 开关纳入结果；未显示隐藏文件时，递归扫描也不会进入隐藏目录。前端搜索输入约 **300 ms** 后再发请求，避免每个字符都触发扫描。

### 路径跳转与保存入口

Quick Jump 提供 Root、Home、Desktop、Documents、Downloads、Temp 和 Program Directory 等系统位置，以及手动输入路径的 Go to Folder。这些位置以**远端 Client 的系统环境**为准，不是浏览器所在机器的同名目录；具体路径随平台和运行身份不同。

Browser 还提供 Pinned Paths 管理：可以保存常用远程目录、指定显示名称、编辑、删除或直接跳转。Pins 按**机器身份 `machine_id`** 保存于 Server 的 SQLite 数据库 `runtime/rch.db`，不是按单次连接的 `client_id` 暂存，所以同一机器重新连接后仍可复用。固定路径也供终端 `gopin` 和 Script SDK 的 Workspace 能力使用。

例如已经保存显示名称为 `logs` 的 Pin，可以在相应 Client 的终端命令通道执行：

```text
gopin logs
```

这会尝试切换到 Pin 所指向的远程目录。执行前必须先保存该 Pin，并确保当前 Client 能够访问对应路径；仅有显示名称而无有效路径不会自动创建目录。

## 远程文件操作的生命周期

### 写入、删除及重命名

Create Directory 在当前远程目录下创建文件夹。Rename 只修改选中文件或目录的名称。两者都会检查目标路径：**目标已存在时直接失败，不静默覆盖同名文件或目录**；若缺少权限，也会返回系统文件操作错误。

Delete 可处理单项或多项。删除普通文件使用系统删除操作；删除目录会**递归移除整个目录树**，并非默认移入回收站。前端会要求确认，但确认后不具备自动撤销、历史版本或回收站恢复。执行前应核对完整路径及目标目录中是否包含需要保留的内容。

批量删除先分别解析目标，再逐项执行。单项失败不会自动撤销前面已经成功的删除；返回的结果包含成功数和错误详情。只要有至少一项成功，整体执行状态就可能是成功，因此**不要单靠成功提示判定所有项目均被删除**。刷新目录或查看详细返回信息才能确认最终状态。

### 跨目录的复制和移动

Browser 的 Copy、Cut 和 Paste 使用的是**界面内部的远程路径列表**，与工具栏 Clipboard 的原生系统剪贴板不同。

选中一个或多个项目后点击 Copy / Cut，只是在 Browser 中记录待复制或待移动的路径。随后导航到目标目录，点击 Paste，才会向远端执行实际文件系统操作：

- **Copy**：普通文件保留内容和元数据进行复制，目录则复制整个目录树。
- **Cut**：目标目录 Paste 时将源文件或目录移动过去。
- **Copy Path**：仅将所选远程路径字符串复制到浏览器所在机器的剪贴板，不复制文件内容。

例如从 `/tmp` 选中 `a.txt`、`b.txt` 并 Copy，到 `/tmp/backup` Paste，会在目标目录创建相同名称的文件。目标已有同名项时会报告冲突，**不会覆盖原文件**；源目录与目标目录相同、或试图把一个目录放进它自身或其子目录，也会失败。

多项复制或移动同样是逐项执行，允许部分成功，不提供整个批次的事务性回滚。Cut 操作成功提交后，界面清空待移动路径；Copy 列表可保留，便于重复粘贴。目标操作完成后应刷新目录，检查成功数量与失败记录。

## Activity Center 操作记录

Web Remote Files 的真正远程文件修改动作会在 Client 命令成功派发后写入一条 Activity：`delete_files`、`rename_files`、`create_directory`、`copy_files`、`move_files`、`create_archive`、`extract_archive`、`save_file`。批量操作统一为一条记录；部分成功按 `error` 显示数量和失败明细。保存文本仅记录路径和编码，不保存正文或编码载荷。Browse/Preview/读取不属于这些 Activity。用户主动上传/下载作为独立的 `transfer` Activity 记录一次，Transfer Center 继续管理进度与取消；Quick History 不受影响。详情中的 `files` 指生成的 Artifact，不指被修改的远端路径。

## 文件内容和打包传输

### 远端到 Server 的文件搬运

Browser 可以选择文件上传，也可拖放文件到当前目录。上传由 Server 创建传输记录和临时上传凭证，浏览器通过独立文件传输端点传送二进制，随后由 Client 接收并写入指定远程路径。界面报告 **Upload started** 仅表示上传流程已经建立，**不意味着 Client 已经完成写盘**；应查看 Transfer Center 的最终状态并刷新远程目录。

下载方向相反：

```text
Client 上的远程文件
       ↓ Client TransferManager / HTTP 文件传输
Server Artifact（文件记录）
       ↓ Artifact 下载接口
浏览器本地下载
```

单文件 Download 把原文件传到 Server，形成带 `artifact_id` 的 Artifact，再由浏览器下载。选中多个文件或目录时，Browser 使用 Download ZIP：远端先按选中的路径生成打包数据，传输到 Server 后以 ZIP Artifact 交给浏览器。目录下载同样需要 ZIP 包装，不能把远程文件夹当成普通单文件直接下载。

下载过程会有独立的 `transfer_id` 和进度/状态信息。**传输完成、Artifact 成功登记和浏览器成功保存本地文件是三个不同的阶段**：例如 Artifact 已产生但浏览器阻止下载，不能据此断言远端传输失败。

### 压缩包的构建与处理

Browser 对 ZIP 提供三种实际不同的操作：

| 操作 | 作用 |
|---|---|
| **Create ZIP** | 直接在远端目标目录创建包含所选路径的 ZIP 文件 |
| **Peek ZIP** | 不解压就浏览 ZIP 内目录结构与符合条件的文本条目 |
| **Extract Here** | 在远端解压 ZIP，结果写入远端文件系统 |

Create ZIP 可以选择多个文件和目录，并指定生成目录和归档名称；名称不含 `.zip` 时会补上扩展名。已存在同名 ZIP 就报冲突，不覆盖。写入异常时会尝试清理尚未完成的输出文件。

Peek ZIP 先校验压缩包，再展示树形目录、文件数量、压缩与未压缩体积等信息；可选择文本条目读取内容而不必解压整个归档。它有独立的预览限制：

| 限制 | 当前阈值 |
|---|---:|
| ZIP 文件本身 | 2 GiB |
| ZIP 内条目数量 | 5,000 |
| 单个可读取文本条目 | 2 MiB |

这些只约束 Peek 和条目预览，**不等同于 ZIP 创建与解压的限制**。

Extract Here 会分析顶层结构：仅有单一根目录时尽量保留该目录层次；存在多个顶层项目时，在目标目录下新建一个包装目录，防止解压内容散落。解压对绝对路径、父目录穿越、ZIP 符号链接及写入目标路径做安全检查，同时限制最多 **50,000 条目**、声明未压缩总大小最多 **20 GiB**。遇到错误会尝试清理本次新建的目标目录，但这不等于对任何中断、权限错误或系统故障都提供完整回滚保证。

### 文件内容的查看和回写

点击文件的 Preview，系统通过专门传输链路将远端文件或用于预览的副本存入 Server 的 Preview Artifact，之后根据文件类型展示。对于文本，界面提供 Monaco 编辑器、行号和语法高亮；进入 Edit 后可以修改内容，再通过 Save 写回**远程原文件**。保存并不会自动创建历史版本，也没有通用的多人协同编辑或冲突合并机制。

如果预览只是文件开头的一部分、内容已经截断，界面会禁止直接编辑，避免把不完整内容覆盖成整个文件。图片预览可以显示图像、尺寸和可用的元数据；启用相应运行时设置时，上传预览前可尝试对图片压缩，失败或不适合压缩时继续使用原图。ZIP 则使用独立的 Peek 界面，不直接当作文本文件编辑。

文件预览、图片原始下载和文本保存是不同的动作：能在浏览器看到缩略/压缩预览，不意味着远端文件内容被修改；只有明确保存编辑内容，才会写回 Client 文件系统。

## 远程路径选择器的输入契约

Picker 面向**需要远程路径作为输入的其他功能**，主要集成在 Script、Background Job 和 External Tool 的参数表单中。它不代替 Browser 做文件管理，而是负责浏览并把路径交还给调用者。调用方决定选中的路径以后如何使用，Picker 不会自动执行脚本或任务。

### 选择模式及返回形状

远程路径参数支持四种类型：

| 参数类型 | 选择方式 | 返回值 |
|---|---|---|
| `remote_file` | 一个文件 | 字符串 |
| `remote_files` | 多个文件 | 字符串数组 |
| `remote_folder` | 一个目录 | 字符串 |
| `remote_folders` | 多个目录 | 字符串数组 |

单选文件返回一个完整远程路径，例如：

```json
"/Users/example/scripts/demo.py"
```

多选文件则返回数组：

```json
[
  "/Users/example/scripts/a.py",
  "/Users/example/scripts/b.py"
]
```

**多选值是路径数组，不应转换成逗号分隔字符串。** 这影响参数校验、任务启动与运行时拿到的真实数据类型。`selection_mode` 可以显式使用 `file` 或 `folder`；常规参数表单也会依据 `remote_file` / `remote_folder` 等参数类型决定可选内容。`initial_path` 用于指定打开 Picker 时首先浏览的位置。

File 模式允许进入目录浏览，但只有文件可以被选中；Folder 模式主要显示目录并允许选择目录条目。**当前没有独立的 Select Current Folder 按钮**，要选择当前目录通常需要到父目录中找到并选中它。单选点击 Select 后返回字符串，多选可以先勾选多项，再统一确认返回数组。

### Picker 的导航和调用集成

Picker 保留面包屑、上级目录、Quick Jump、Go to Folder 和分页，默认每页 **50 项**，但不提供 Browser 的搜索、Recursive、显示隐藏项开关、Pins 管理、复制删除和 Preview 编辑。它固定请求 `show_hidden=false`，所以隐藏文件或隐藏目录不会出现在普通可选列表中。

Picker 提供一个简单的 Upload 按钮，可选择**单个本地文件**，与 Browser 共用 `POST /api/transfers/browser-upload` 建立受管理任务，再通过 8086 的 `browser-upload/{transfer_id}/content` 上传文件字节并由 Client 写入当前远程目录。Picker 和 Browser 是相同的 Transfer 生命周期，来源分别标记为 `remote_file_picker` 与 `remote_files`。**Upload started 表示任务启动，不能据此推断文件已经可选或已经写入。** Picker 不是 Browser 的全部批量上传功能入口，也不具备文件夹上传选择器。

例如 Script 或 Job 声明一个远程多文件参数：

```json
{
  "name": "source_files",
  "type": "remote_files",
  "required": true
}
```

相应表单会提供 Browse，用户在 Picker 勾选多个远程文件后，最终回填到 `source_files` 的值是路径数组。External Tool 的远程路径参数复用同样的选择机制，因此不需要各自维护另一套目录浏览器。

## 请求结构与跨端状态

Browser、Picker 的目录浏览共用 `/api/connections/{client_id}/remote-files`。下面列出的地址均相对于 Server 的 HTTP 服务；`{client_id}` 为目标在线客户端 ID。调用这些接口需要正常的 Web 认证；浏览器使用当前管理会话，外部工具可使用配置的 API Token，并非开放的匿名文件系统接口。

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/connections/{client_id}/remote-files` | 列表、过滤、分页、搜索 |
| POST | `.../remote-files/mkdir` | 创建远程目录 |
| POST | `.../remote-files/rename` | 重命名 |
| DELETE | `.../remote-files` | 删除单个路径 |
| DELETE | `.../remote-files/batch` | 批量删除 |
| POST | `.../remote-files/paste` | 复制或移动多个路径 |
| POST | `.../remote-files/download` | 下载一个远程文件，生成 Artifact |
| POST | `.../remote-files/download-zip` | 打包下载多个路径 |
| POST | `.../remote-files/create-zip` | 在远端创建 ZIP |
| POST | `.../remote-files/zip-peek` | 查询 ZIP 结构 |
| POST | `.../remote-files/zip-entry` | 读取 ZIP 内文本条目 |
| POST | `.../remote-files/extract-zip` | 在远端解压 ZIP |
| POST | `.../remote-files/preview` | 生成文件预览 |
| POST | `.../remote-files/save` | 保存编辑后的文本文件 |

上述 `...` 省略的是相同前缀 `/api/connections/{client_id}`。Pinned Paths、系统路径 Quick Jump、Artifact 下载和文件 Transfer 另有对应接口，不应误认为都由目录浏览 API 负责。

### 列表查询字段

例如列出远端 `/tmp` 的第一页、每页 50 条、隐藏项不显示：

```http
GET /api/connections/{client_id}/remote-files?path=/tmp&page=1&page_size=50&show_hidden=false
```

若要搜索名称包含 `log` 的文件或目录，并向下递归搜索，可追加 `search=log&recursive=true`。递归范围可能非常大，且目录读取占前台命令槽，建议首先从较窄的目录开始。

请求返回的数据中，`entries` 是当前页数组，`pagination.total_visible` 是过滤后的可见匹配数量；例如 `page=2` 并不表示 Client 只扫描第二页。`summary.search_keyword` 与 `summary.recursive_search` 可以反映本次生效的查询条件。

### 文件搬运的请求结构

要将两个远端文件复制到另一个**已存在**的目录，可提交：

```http
POST /api/connections/{client_id}/remote-files/paste
Content-Type: application/json
```

```json
{
  "paths": ["/tmp/a.txt", "/tmp/b.txt"],
  "destination_dir": "/tmp/backup",
  "operation": "copy"
}
```

`operation` 只接受 `copy` 或 `move`，省略时按 `copy` 处理。该请求不会自动创建 `/tmp/backup`，也不会覆盖目标中的同名文件。返回结果应核对成功数量和 `Errors` 文本，特别是同时处理多个路径时。若要移动，则将 `operation` 改为 `move`；无需先向系统 Clipboard 写入路径。

创建目录使用 `mkdir` 接口的 `{"path":"/tmp/backup"}`；重命名使用 `{"old_path":"/tmp/old.txt","new_name":"new.txt"}`。保存文本使用 `{"path":"/tmp/note.txt","content":"...","encoding":"utf-8"}`。这些都是直接改变远程文件系统的请求，应确认目标设备及绝对路径正确后再操作。

### 只读接口的命令行调用

在有权管理目标 Client 的环境中，可通过 API Token 查询目录。例如：

```bash
SERVER_URL='http://127.0.0.1:5000'
CLIENT_ID='替换为实际Client-ID'
API_TOKEN='替换为Server管理API-Token'

curl --fail-with-body -sS \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -G "${SERVER_URL}/api/connections/${CLIENT_ID}/remote-files" \
  --data-urlencode 'path=/tmp' \
  --data-urlencode 'page=1' \
  --data-urlencode 'page_size=50' \
  --data-urlencode 'show_hidden=false'
```

`SERVER_URL` 是实际 Web 服务地址，上面的本机地址仅是替换示例，并不表示项目固定监听该端口；`CLIENT_ID` 应指向已连接的目标设备，`API_TOKEN` 必须是服务端实际配置的有效管理 Token。`--data-urlencode` 负责对目录和查询参数编码。成功时返回包含目录条目和分页数据的 JSON 响应；连接离线、权限不足或路径不存在时会返回错误。这个示例只读目录，不会修改或删除文件。实际远程访问应使用受保护的 HTTPS 服务，避免泄露 Token。

## 文件一致性及破坏性操作边界

| 现象 | 行为与排查方向 |
|---|---|
| 目录打开缓慢 | 远端先收集排序再分页；超大目录和 Recursive 搜索会耗时 |
| 某些条目不可见 | 检查 Show Hidden；Picker 固定隐藏这些条目 |
| 搜索不到文件内容 | Search 只匹配名称，不搜索文件正文 |
| 复制/移动失败 | 核对目标存在、重名冲突、源目标关系和操作系统权限 |
| 删除/批量操作只完成一部分 | 操作逐项执行，查看实际成功数和每条错误，不能假定整体回滚 |
| 上传提示 Started 但看不到文件 | 等传输任务结束并 Refresh；必要时查看 Transfer Center |
| 下载传输完成但未保存到浏览器 | 分别核对 Transfer、Artifact 和浏览器下载授权/拦截 |
| ZIP 无法 Peek | 可能超出 2 GiB / 5,000 条限制，或不是合法 ZIP |
| ZIP 无法解压 | 检查路径安全、条目与体积限制、目标冲突和写入权限 |
| 文本可预览不能编辑 | 可能被识别为非文本，或预览内容已截断 |
| 编辑后文件内容不符合预期 | Save 覆盖原文件，不会自动保留历史版本；注意编码和并发修改 |
| Picker 选不了目录 | 检查 `file` / `folder` 模式；当前目录须到父级选择 |
| Pin 重新连接仍存在 | Pins 按 `machine_id` 存储；路径仍要符合当前 Client 的文件系统和权限 |

**权限边界。** Remote Files 不是独立的远程目录沙箱。路径可以是绝对路径，也可以根据 Client 工作目录解析；最终能够访问、删除或修改哪些文件，由 Client 运行账号的操作系统权限和 Web 管理授权共同决定。管理员应避免把高权限 Client 暴露给不受信任的操作者。

**批处理边界。** 批量删除、复制、移动不会以一个文件事务整体提交，已经完成的项目不会因为后续单项失败自动恢复。重命名、Save、ZIP 创建等也不提供统一的历史版本或回滚机制。涉及重要数据时应先确认选择范围，必要时另外备份。

**在线与缓存边界。** 目录列表、路径选择和实时文件操作都需要 Client 当前能响应；它们不是 Server 自动同步的一份远端文件镜像。已经传到 Server 的 Artifact 可以通过 Server 的相应权限和存储策略独立管理，但其存在不代表远端文件仍保持原样。

**Browser 与 Picker 的职责边界。** Browser 用于文件管理，Picker 用于回填远程参数。二者共用列表查询不代表操作能力完全相同；Picker 返回路径值以后，具体脚本、任务或工具是否接受该路径，以及之后如何处理，由调用方负责。
