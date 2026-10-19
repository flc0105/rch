# Documents：Server 本地 Markdown 文件库

Documents 是 RCH Web 的纯 Server 功能，不连接 Client、不使用数据库保存正文，也不需要文件传输任务。工具栏 `Documents`（默认位于 `More`，可以在 Toolbar Settings 移动）打开目录树。支持 `.md` 文件预览、Monaco 源码编辑与右侧实时 Markdown 渲染、新建 Markdown 文件和文件夹。

## 映射目录

配置位于 `backend/server/config/config.py` 中的 `DOCUMENT_ROOTS`。默认映射：

- `rch` / `RCH Docs` → `<backend>/docs`（项目真实文档，可直接修订，受 Git 更新影响）
- `notes` / `Notes` → `<backend>/runtime/documents/notes`（持久化笔记；`RCH_SERVER_RUNTIME_DIR` 可改变 runtime 根）

也可在 Server 启动前设置环境变量 `RCH_DOCUMENT_ROOTS`，替换全部默认映射。例如：

```bash
export RCH_DOCUMENT_ROOTS='{"api":{"label":"API Docs","path":"/srv/docs/api"},"notes":{"label":"Notes","path":"/srv/data/notes"}}'
```

路径须为 **Server 机器/容器内的绝对路径** 且已存在。Docker 部署应预先挂载宿主机目录；RCH 不提供让网页浏览任意 Server 磁盘选择映射的入口。配置修改需重启 Server。给笔记目录选择不会被部署覆盖的位置。默认 Notes 目录由 Server 创建；自定义目录不会自动创建。

## HTTP API

统一复用 RCH Web 的管理员登录和 API Token 认证；路由不会调用 Client：

| Method | Route | 参数 / 请求体 |
| --- | --- | --- |
| GET | `/api/documents/roots` | 无 |
| GET | `/api/documents/tree` | `root_id`, `path`（空表示根目录） |
| GET | `/api/documents/content` | `root_id`, `path` |
| PUT | `/api/documents/content` | `root_id`, `path`, `content`, `encoding`, `sha256` |
| POST | `/api/documents/files` | `root_id`, `path`（新 `.md` 相对路径） |
| POST | `/api/documents/directories` | `root_id`, `path`（新目录相对路径） |

树是按展开目录懒加载，仅列出普通子目录和 `.md` 文件，不列出符号链接和隐藏项。路径不接受绝对路径、`..`、空片段或反斜杠；任何符号链接路径被拒绝。文件读写受到 Server 操作系统账号自身的目录权限限制。

## Markdown 与编辑安全

- 前端用 `markdown-it` 渲染 CommonMark 和表格，关闭原始 HTML，默认链接协议校验；不解析 HTML，也不加载 Markdown 图片。外部 HTTP(S) 链接在新标签页打开，同一映射根内的相对 `.md` 链接可以在 Documents 中打开。
- 使用现有 Monaco 编辑源码，编辑时并排实时展示 Markdown 结果；这是**源码编辑 + 实时预览**，不是 Typora 式行内富文本编辑。
- Monaco 实例使用非响应式存储，并在编辑、取消、关闭和重新打开后复用固定容器；初始化与布局延后至动画帧，关闭时取消待执行任务并使编辑器失焦，不主动调用可能导致界面卡死的 `dispose()`。此生命周期策略与现有 PreviewDialog 一致。
- 文件大小上限共用 `WEB_PREVIEW_TEXT_MAX_BYTES`（默认 512 KiB），超过限额将拒绝在 Documents 内编辑。读取保留 UTF-8、UTF-8 BOM、UTF-16 LE/BE BOM；无法无损解码的文件允许只读显示，禁止编辑。
- 保存必须携带打开文件时的 SHA-256 和真实编码；外部文件改变后拒绝覆盖，要求重新加载；输出在覆盖前完整编码，在同目录写入临时文件并以原子替换完成保存。新文件以排他模式创建，默认 UTF-8。
- 页面关闭、换文件及重新加载前会提示未保存更改。没有数据库、文件监控、实时同步、自动搜索、附件或上传逻辑；目录和正文均直接从磁盘读取。

`markdown-it` 是本功能唯一新增的前端直接依赖。部署环境执行 `cd frontend && npm ci` 安装依赖。
