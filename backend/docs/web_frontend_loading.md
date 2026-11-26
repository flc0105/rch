# Web 首屏加载与静态资源交付

Web 管理界面采用 Vue 3 / Vite 构建，生产静态资源由 Flask 提供。首页先加载登录、连接、Terminal 及必要状态，并通过 WebSocket 接收实时事件。大型工具窗口按需加载，浏览器空闲时可预热其代码。

## 首屏与按需工具

External Tools、Activity History、PTY、Background Jobs、Processes、Keychains、Preview、Documents 等窗口使用动态导入。预热只加载模块；实际窗口打开时才建立 PTY 等业务会话或初始化编辑器。Monaco 的 Worker 和语言资源按使用需求加载。

自动预热逐项调度，避免争抢首屏资源。用户悬浮或聚焦可用工具入口、点击工具、从通知跳转时，可以优先加载相应模块。Toolbar、More、Toolbox 及跨窗口操作应使用共享的打开和加载机制。隐藏标签页暂停自动预热，恢复可见后继续。

## 静态资源压缩与缓存

`npm run build` 输出带内容哈希的 JS/CSS。Vite 为适合压缩的资源生成 `.gz`，Flask 按 `Accept-Encoding` 协商 gzip，并设置正确的资源类型、`Content-Encoding` 和 `Vary`。带内容哈希的资源使用长期不可变缓存，HTML 和 API 保持各自的响应策略。

部署时将 `frontend/dist/` 的完整内容复制到 `backend/static/`，包含 `.gz` 文件。先交付新资源，再切换 `index.html`；仍有旧标签页使用的资源可以保留到这些会话退出。

Element Plus 在 Web 入口集中安装并加载完整样式。UI 组件、指令及程序式消息使用项目统一的 UI 基础。

## 维护与验证

动态窗口入口由 App 和共享加载机制协调；Vite 负责构建和预压缩，Flask 负责资源协商及缓存。新增窗口应保持用户交互优先于自动预热，并复用已有打开入口。

生产构建后使用浏览器 Network 面板核对首屏、按需窗口、gzip 和缓存；首次打开编辑器、从通知打开工具及网络较慢时的交互应纳入回归。开发端口和代理设置见 [Frontend README](../../frontend/README.md)。
