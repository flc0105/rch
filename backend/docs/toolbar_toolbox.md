# Toolbox — 工具入口

终端工具栏中的 **More** 提供两种打开方式：

- **悬浮 More**：显示原有的工具下拉菜单和 Settings 入口。
- **点击 More**：打开 Toolbox，按图标查看全部工具。

Toolbox 显示 Toolbar 和 More 中的全部工具，顺序与当前工具栏设置一致。顶部搜索框支持按工具名称筛选；清空搜索后恢复全部工具。点击工具图标会关闭 Toolbox 并打开对应功能。顶部 Settings 按钮打开工具栏设置，Close / ESC 仅关闭 Toolbox。

需要在线设备的工具（Remote Files、PTY、Screen View、Clipboard、Processes、Quick Actions）在未选择可用 Client 时不可操作；Documents、Keychains 等 Server 功能保持各自的可用条件。

工具栏上的 **Disconnect、Clear、Bottom** 属于终端操作按钮，不在 Toolbox 工具网格中。工具是否放在 Toolbar 或 More，可在工具栏设置中调整；Toolbox 会按当前设置显示工具列表。

前端终端工具栏和设备列表的 **Disconnect** 共用 `/api/connections/{client_id}/kill`，Server 转发当前 Client 命令 `kill_instance`，不使用旧 `kill_connection` 命令。
