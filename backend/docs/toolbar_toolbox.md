# Toolbox — 工具网格入口

RCH 终端工具栏中的 **More** 有两种入口：鼠标悬浮展开原有 More 下拉菜单，点击 More 打开 **Toolbox** 网格弹窗。原下拉项和 Settings 不变。

## 第一版交互

- Toolbox 展示当前统一的 `TOOLBAR_ACTION_CATALOG` 中全部 16 个工具，位置沿用 Toolbar 与 More 当前偏好顺序，**不提供拖拽排序**。
- 顶部 `Search tools...` 按名称过滤，不修改既有布局偏好；清空搜索恢复完整网格。
- 使用 `@lucide/vue` 静态映射的 Lucide 图标；无新 Server 接口或数据库字段。
- 当前没有在线 Client 时，Remote Files、PTY、Screen View、Clipboard、Processes、Quick Actions 与原工具栏一样不可点击；Server 资源入口保持原有条件。
- 选择工具即刻通过 TerminalToolbar 既有的 `runAction(id)` 分发，同时关闭 Toolbox；新工具无需等待 Toolbox 退出动画结束。顶部 Settings 入口也立即响应。
- 保留 Toolbar 的 Disconnect、Clear、Bottom 等操作按钮。Toolbox 只列现有 16 项工具，不列操作控制。

## 代码与未来边界

目录仍以 `frontend/src/data/toolbarPreferences.js` 为唯一工具 ID / 标题 / 图标来源。Toolbox 只是展示层：不装配 Server/Client 服务，不内置具体工具 Dialog 的打开代码，也不引入 Capability Manifest 协议。

已确认的后续需求——拖拽排序、能力分类、按模块禁用与按需加载——均**未在第一版实现**，避免额外双轨或兼容路径。

依赖为 `@lucide/vue`，已记录在 `frontend/package.json` 和 `frontend/package-lock.json`。使用 `npm ci` 安装后构建；图标按具名 import 使用以便打包器 tree-shaking。
