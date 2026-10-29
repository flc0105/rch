# Web 首屏加载与静态资源交付

Web 管理界面采用 Vue 3 / Vite 构建，由 Flask 提供生产静态资源。启动时优先完成首页必需的界面和数据初始化，再利用浏览器空闲时段预热可选工具窗口；构建产物通过预压缩与浏览器缓存减少传输开销。本文说明加载顺序、交互触发方式，以及维护这些规则的代码位置。

## 首屏与可选窗口

普通管理页由 `frontend/src/main.js` 加载 `App.vue`。应用挂载时初始化连接、设备分组、登录会话、通知与传输数据，并建立 SSE 事件订阅。浏览器页面 `load` 事件之后，调度器再经过两次绘制帧，开始安排可选窗口的代码预热。

自动预热按下表顺序逐项执行。每项等待前一个模块导入完成后，再申请下一次浏览器空闲时机；顺序反映这些工具在管理界面中的常用程度。

| 顺序 | 功能入口 | 动态加载的组件 | 主要作用 |
| --- | --- | --- | --- |
| 1 | External Tools | `ExternalToolManagerDialog.vue` | 外部工具管理与实例操作 |
| 2 | Command History | `CommandHistoryDialog.vue` | 查询与复用终端命令历史 |
| 3 | PTY | `PtyDialog.vue` | 交互式终端窗口，包含 xterm 相关代码 |
| 4 | Background Jobs | `BackgroundJobsDialog.vue` | 后台任务与模块管理 |
| 5 | Processes | `ProcessDialogs.vue` | 远端进程查看与管理 |
| 6 | Keychains | `KeychainManagerDialog.vue` | 密钥管理 |
| 7 | Preview | `PreviewDialog.vue` | 通用文件预览与编辑，导入 Monaco 相关模块 |
| 8 | Documents | `DocumentsDialog.vue` | Server Documents 的浏览与编辑，复用已加载的 Monaco 依赖 |

预热阶段执行的是 JavaScript 模块导入，浏览器可以提前下载、解析并缓存对应代码。窗口组件在实际使用时才挂载并执行打开逻辑；PTY 会话在打开终端时建立，Monaco Editor 的实例及按需使用的 Worker、语言资源则根据编辑内容初始化。因此，已完成模块预热的窗口通常可以直接打开，首次进入特定编辑状态仍可能触发额外资源请求。

### 空闲调度与交互优先级

调度器优先使用浏览器的 `requestIdleCallback`，并为每次请求设置超时；不支持该接口时使用短延时调度。标签页不可见时暂停后续自动预热，恢复可见后继续；页面卸载时取消尚未执行的调度。一个重型模块的导入完成后才安排下一个任务，减少自动预热之间的资源竞争。

工具入口的**指针悬浮或键盘聚焦**可提前触发对应模块的导入，用户点击工具时也会直接请求该模块。自动队列、悬浮和点击共用每个模块的加载任务：已经开始的导入会被复用，尚未开始的模块可由交互直接优先启动。组件准备好后，应用完成 Vue 挂载更新，再调用原窗口的打开操作。

触发位置覆盖 **Top Bar 工具按钮、More 下拉菜单的具体工具项、Toolbox 工具网格**。只对有预热映射且当前可操作的工具进行提示，悬浮 More 按钮本身不会一次预热其全部菜单项。当前映射的工具包括 External Tools、History、Background Jobs、Documents、Keychains、PTY、Processes，以及通过 Artifacts 入口预热 Preview。

通知中心跳转到 External Tools 的管理或日志操作，也使用相同的动态窗口打开路径。其他功能调用 Preview 编辑器时，由统一入口确保模块已加载并完成挂载。未列入上述队列的窗口仍按自身现有加载方式工作。

## 静态资源压缩与浏览器缓存

生产构建执行 `npm run build`。Vite 在 `dist/assets/` 下输出带内容哈希的 JS/CSS，并为超过 1 KiB 且压缩后更小的 JS/CSS 生成同名 `.gz` 文件。Flask 负责静态文件的压缩版本协商与发送，无需额外的静态文件服务器。

浏览器请求 `/assets/` 下的 JS/CSS 且支持 gzip 时，Flask 优先返回对应的 `.gz` 文件，并设置正确的资源类型、`Content-Encoding: gzip` 和 `Vary: Accept-Encoding`。常规文件请求、缺少预压缩文件的情况以及 Range 请求沿用普通静态资源响应。API、SSE、WebSocket、上传与下载使用各自原有的通信和响应路径。

带内容哈希的 `/assets/*.js` 与 `/assets/*.css` 使用 `Cache-Control: public, max-age=31536000, immutable`。浏览器第一次下载后可在缓存有效期内复用相同 URL；内容变化会产生新的哈希文件名，并以新 URL 获取资源。HTML 和 API 不采用该长期强缓存策略。

部署时将 **`frontend/dist/` 的完整内容**复制到 `backend/static/`，包括 `assets/*.gz`。先部署新资源文件，再更新页面入口 `index.html`；仍有旧标签页使用旧哈希资源时，暂时保留相应旧文件。

## Element Plus 组件加载

Web 入口按项目使用范围集中注册 Element Plus 的具名组件和 `v-loading` 指令，并按组件引入 CSS。消息、确认框和通知等程序式 API 通过显式模块导入使用。这样构建入口只包含已注册的 UI 组件及其依赖；当前注册方式为启动时集中注册，新增弹窗仍复用相同的全局 UI 基础组件。

## 维护位置

| 需要调整的内容 | 代码位置 | 修改方向 |
| --- | --- | --- |
| 可选窗口列表、自动预热顺序、悬浮映射、窗口打开入口 | `frontend/src/App.vue` | 调整动态导入、队列项、工具动作对应关系及异步挂载调用 |
| 首屏后何时开始、空闲调度、后台标签页处理 | `frontend/src/utils/idleWarmup.js` | 调整页面绘制后调度、空闲回调和回退行为 |
| Top Bar、More 的工具悬浮与聚焦 | `frontend/src/components/TerminalToolbar.vue` | 保持工具动作提示事件向顶层转发 |
| Toolbox 工具网格的悬浮与聚焦 | `frontend/src/components/ToolboxDialog.vue` | 保持工具动作提示事件向顶层转发 |
| Element Plus 组件与样式注册 | `frontend/src/utils/elementPlusRegistry.js`、`frontend/src/main.js` | 新增实际使用的组件、指令和对应样式 |
| 构建与 `.gz` 文件生成 | `frontend/vite.config.js` | 调整构建时静态文件预压缩规则 |
| Flask 静态文件协商与缓存头 | `backend/server/web/app.py` | 调整 `/assets/` 的 gzip 返回条件和哈希资源缓存策略 |
| 调度与加载入口测试 | `frontend/tests/idleWarmup.test.mjs` | 随队列、交互触发或挂载规则变化更新测试 |

新增可选窗口时，应同步配置动态导入、模板的条件挂载与引用、打开时的加载等待，以及 Toolbar / More / Toolbox 中适用的悬浮映射；跨窗口的通知和编辑操作也应走统一的打开入口。调整顺序时只需更改自动预热队列，交互优先机制保持独立运行。

## 运行与验证

开发环境使用 `npm run dev`；验证真实资源分包、gzip 和缓存行为时应使用 `npm run build` 后由 Flask 提供的页面。Chrome DevTools 的 Network 面板可在禁用缓存、模拟慢网时观察首屏关键资源先于可选窗口加载；启用缓存后再次访问可查看哈希文件复用情况。点击尚未自动预热的工具、悬浮各入口、通过通知打开 External Tools，以及首次进入 Documents/Preview 编辑状态，是需要覆盖的主要交互路径。

相关文档：[Toolbox 与工具入口](toolbar_toolbox.md) · [Preview 与 Monaco](preview_monaco.md) · [PTY](pty.md) · [Documents](documents.md) · [Background Jobs](background_jobs.md) · [External Tools](external_tools.md)。
