# Toolbox — 工具入口

终端工具栏中的 **More** 提供两种打开方式：

- **悬浮 More**：显示原有的工具下拉菜单和 Settings 入口。
- **点击 More**：打开 Toolbox，按图标查看全部工具。

Toolbox 显示 Toolbar 和 More 中的全部工具，顺序与当前工具栏设置一致。顶部搜索框支持按工具名称筛选；清空搜索后恢复全部工具。点击工具图标会打开对应功能，Toolbox 保持打开并处于新弹窗下层；在图标上右键会在鼠标位置打开唯一的操作菜单（右键其他图标时自动切换；点击菜单外、按 ESC 或滚动会关闭）。菜单提供 Open，带 Toolbar 下拉动作的工具还会显示相同子选项（Clipboard Get/Send、Screen View Open in New Tab，以及已 Pin 的 Quick Actions）。顶部 Settings 按钮打开工具栏设置，Close / ESC 仅关闭 Toolbox。

需要在线设备的工具（Remote Files、PTY、Screen View、Clipboard、Processes、Quick Actions）在未选择可用 Client 时不可操作；Documents、Keychains 等 Server 功能保持各自的可用条件。

工具栏上的 **Disconnect、Clear、Bottom** 属于终端操作按钮，不在 Toolbox 工具网格中。工具是否放在 Toolbar 或 More，可在工具栏设置中调整；Toolbox 会按当前设置显示工具列表。


终端 Toolbar 的 Screen View 主按钮打开原 Dialog，悬停下拉 **Open in New Tab** 可以直接打开独立标签页，不必先打开 Dialog。

Toolbox 工具网格末尾提供 **Add** 快捷入口。可以选择 Server Script 或当前 Client 可用的 Quick Action，并选择一个预设 Lucide 图标固定到 Toolbox；不涉及 Background Job 或分组配置。固定项只保留资源身份与图标，不复制脚本、Alias 模板或参数。固定的 Script 点击后直接使用原 Script Run Dialog；固定的 Quick Action 仍遵循原有执行方式（有参数打开参数框，无参数直接运行）。固定的 Quick Action 右键还可选择 Run in Terminal（沿用原有参数输入和终端执行流程）；右键固定项可选择 Unpin，仍使用 Toolbox 的单实例右键菜单。

固定项通过 Toolbar Preferences 中的 `toolbox_shortcuts` 持久化，独立于 Toolbar 的 `quick_actions_pinned`。Toolbar Settings 修改布局时保留这一字段。添加时可设置独立的显示名称（不修改 Script 或 Alias 原名称），并通过独立、可复用的 Icon Picker 弹窗按名称模糊搜索并选择 Lucide 图标。Script 与 Quick Action 的资源选项分别按显示名称 A-Z 排序。

添加列表仅包含选中 Client 平台兼容的 Script（以 `metadata.platforms` 为准）及 `in_current_scope` 的 Quick Action。切换 Client 后，不兼容平台的快捷项自动隐藏；同平台但原资源被删除的快捷项保留并标记 Unavailable，可从右键菜单 Unpin，不能误执行其他同名资源。Toolbox 固定为 70vh；添加弹窗与 Icon Picker 均采用固定高度，超出内容在内部滚动。
