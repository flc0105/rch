## 在 Command Registry 中使用 Interaction Broker

Interaction Broker 允许正在执行的命令向当前 Web 页面发起确认、输入、选择或计划预览，并等待用户回复。它不创建另一条 Command，也不需要为普通命令单独开发前端弹窗。

### Client 普通命令

在 Client Command Mixin 中调用 `CommandInteractions`。例如：

```python
from core.utils.decorator import desc
from client.commands.common.services.interaction_service import (
    CommandInteractions,
    CommandInteractionError,
)


class CommandExampleMixin:
    @desc('Confirm an operation', group='interaction')
    def confirm_task(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: confirm_task'
        self._set_timeout(120)
        try:
            if not CommandInteractions(self).confirm(
                'Continue this operation?', title='Confirmation'
            ):
                return 0, 'Cancelled'
            # Execute the operation only after approval.
            return 1, 'Approved'
        except CommandInteractionError as exc:
            return 0, f'Cancelled: {exc}'
```

接入步骤：

1. 将 Mixin 加入 `backend/client/commands/common/groups.py` 的 `CommonRuntimeCommands`；若直接在现有 Mixin 中增加命令，则不需要新建 Mixin。
2. 在 `backend/server/connection/channel/session_command_channel.py` 的 `ClientSessionCommandChannel.build_command_payload()` 中，把新命令名 `confirm_task` 加入明确允许交互的 Client 命令名单，使 Server 为当前命令签发 `interactions:request` Grant。**单独添加 `@desc` 不会自动获得 Grant。**
3. 从有活动执行任务的 Web 页面执行 `confirm_task`。命令会等待交互结果，然后继续原来的执行流程。

`CommandInteractions` 提供 `confirm(message, title=...)`、`ask(message, title=..., secret=False)`、`select(message, labels, title=...)`、`approve_preview(message, preview, title=...)`。`ask` 和 `select` 在用户取消或超时时可抛出 `CommandInteractionError`；布尔审批只在用户明确同意时返回 `True`。带有自定义开关返回值的 Preview 需要单独校验回复结构，不能直接当作布尔审批处理。

现有的 Client 普通命令 `interaction_demo`、`interaction_advanced_demo`、`interaction_preview_demo` 分别演示基本交互、选择/保密输入和结构化预览；进程相关示例可参考 `kill_port`、`kill_proc`。

### Server Builtin 命令

`BuiltinCommandHandler` 初始化时已经提供 `self.interactions`（`BuiltinInteractionSupport`），不需要 Client Grant。可以直接在 `backend/server/application/command/builtin_command_handler.py` 中添加处理方法：

```python
from server.application.command.interaction_builtin_support import BuiltinInteractionError

# Method in BuiltinCommandHandler:
def confirm_task(self, arg=''):
    if str(arg or '').strip():
        yield 0, 'Usage: confirm_task'
        return
    try:
        if not self.interactions.confirm(
            'Continue this operation?', title='Confirmation'
        ):
            yield 0, 'Cancelled'
            return
    except BuiltinInteractionError as exc:
        yield 0, f'Cancelled: {exc}'
        return
    # Execute the operation only after approval.
    yield 1, 'Approved'
```

如需在 Web 命令候选列表中显示，还应在 `BuiltinCommandHandler.WEB_COMMAND_TEMPLATES` 添加相应条目，例如：

```python
{
    'name': 'confirm_task',
    'template': 'confirm_task',
    'help': 'Confirm an operation',
    'source': 'server',
}
```

Server Builtin 使用现有 Web Task 的 `task_id`、`client_id` 和 `tab_id` 与 Interaction Broker 绑定。**必须存在有效的当前 Web Task**；没有活动任务的后台执行不能直接弹出此类交互。可参考现有 `disconnect` 的 Broker 调用方式。

### 运行与权限边界

- Client 普通命令：`CommandInteractions` → Client API → Server Interaction Broker → Web Dialog → 原命令继续执行；Grant 绑定当前命令，未获授权时直接拒绝请求。
- Server Builtin：`self.interactions` → Interaction Broker → Web Dialog → 原 Builtin 继续执行，不经过 Client Grant。
- 用户拒绝、取消、超时或执行中断时，应返回取消结果，不执行需批准的操作。操作对象和权限检查仍由命令自己负责，Broker 只负责交互与回答。
- 无须新增 `acmd`、Script Metadata、HTTP API 或 Vue 弹窗；复用已有的 Broker 和页面交互组件。
