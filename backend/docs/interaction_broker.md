# Interaction Broker

Interaction Broker 在执行中的 Script 或 Command 与当前 Web 用户之间建立一次有边界的问答往返。调用方提交交互类型和约束；Server 把请求绑定到具体任务与浏览器标签页；前端收集回复；Broker 校验身份、值和超时后将结果交还给等待中的执行流程。

确认、文本输入、保密输入、单选以及结构化 Preview 共用这一传递机制，但回复对象的含义取决于类型。Broker 决定能否收到有效回应，不替业务代码决定如何执行已经批准的操作，也不是后台消息或通知系统。

## 执行任务与用户交互的连接

```text
Web Terminal 启动命令 / Script
          ↓
Server 创建正在运行的 Web Task，绑定 client_id、task_id、tab_id
          ↓
Client 命令 / Script 调用交互 API（或 Server Builtin 直接调用 Broker）
          ↓
Server 验证执行身份与授权 → Interaction Broker 创建待回复请求
          ↓
SSE interaction_requested → 对应 Web 标签页的统一交互窗口
          ↓
用户 Approve / Continue、Reject，或输入选择值
          ↓
POST 交互回答 → Broker 验证 → 唤醒原执行流程
          ↓
原命令 / Script 根据结果继续、拒绝执行或结束
```

每次交互有独立 `interaction_id`，但仍属于原来的 `task_id`。Server 在内存中保留未完成请求，等待原任务状态和用户回应。请求发布到指定 `tab_id`；浏览器还可以按标签页读取待处理请求，以应对页面连接和事件到达的时间差。完成后发布 `interaction_resolved`，页面关闭对应弹窗。

同一任务在同一时间只允许一个未完成的交互。可以在用户完成第一步后再发起下一步，但不能让同一任务并发挂起多个对话框。Broker 不保存永久的审批记录或独立工作流状态。

## 交互请求及答复模型

| 类型 | 页面展示 | 调用方取得的结果 | 典型用途 |
|---|---|---|---|
| `confirm` | 确认/拒绝按钮 | 明确同意才是 `True` | 高风险动作前确认 |
| `input` | 普通文本框 | 用户输入的字符串 | 询问名称、路径、说明 |
| `secret` | 密码式输入框 | 用户输入的字符串 | 不在页面明文展示的输入 |
| `select` | 固定选项选择 | 预先提供的选项字符串 | 多个候选中选其一 |
| `preview` | 摘要、表格、详情和批准按钮 | 布尔批准，或经验证的开关/选中行对象 | 先展示计划再执行 |

一次请求会携带 `kind`、`title`、`message`、`timeout_seconds`，按类型附带 `placeholder`、`options` 或 `preview`。正常批准后的底层回复为：

```json
{"status": "answered", "value": true}
```

拒绝、超时和任务结束不等于用户批准。典型状态有 `answered`、`rejected`、`expired`、`cancelled`：

- `answered` 表示用户提交了合法回复；仍要检查 `value`，尤其 Preview 可能返回对象。
- `rejected` 表示用户主动拒绝；`confirm` 和 Preview 会返回 `False`，输入和选择没有有效值。
- `expired` 表示超过交互期限仍未收到有效回复。
- `cancelled` 表示原 Web Task 不再运行或已经失去执行上下文。

高层 API 的 `confirm()` / `approve_preview()` 仅在明确批准时返回 `True`；`ask()`、`select()`、`select_preview_rows()` 在没有合法答复时抛出交互异常。调用方应将这些路径视为不继续执行，而不是随意使用默认值。

Broker 限制单次等待时间在 **1～180 秒**；Select 提供 **1～24 个互不重复的选项**，用户的文本答复不能超过 **4096 字符**。这些限制用于控制一次交互的边界，并不是整条命令或 Script 的全部执行时间预算。

## 结构化计划的预览与决策

Preview 是纯数据的计划呈现，不执行任意 HTML 或 JavaScript。可以组合摘要、表格、可展开详情、提示说明，以及审批前可调整的开关或选中行。没有额外选项的 Preview 只返回布尔批准。

下面是一个普通的只读计划预览：

```python
preview = {
    'summary': [
        {'label': 'Files', 'value': '2'},
        {'label': 'Destination', 'value': '/tmp/archive'},
    ],
    'columns': [
        {'key': 'name', 'label': 'Name'},
        {'key': 'size', 'label': 'Size'},
    ],
    'rows': [
        {'name': 'a.txt', 'size': '1 KiB'},
        {'name': 'b.txt', 'size': '2 KiB'},
    ],
    'details': [{'title': 'Scope', 'content': 'Copy these two files only.'}],
    'notice': 'Please verify the destination before approving.',
}
```

`summary` 展示关键值，`columns` 定义表头，`rows` 使用与列 `key` 对应的文本字段，`details` 提供折叠的长说明，`notice` 适合显示必要风险。所有字段都有大小与数量校验，不能把 HTML 或任意对象塞进单元格。

Preview 的能力进一步分成以下三种：

**纯批准：** 将以上 `preview` 交给 `approve_preview()`，只有明确批准才继续执行。适合操作范围已经固定、用户只需检查的情况。

**批准时调整开关：** 在 Preview 中增加 `switches`，例如：

```python
preview['switches'] = [
    {'key': 'dry_run', 'label': 'Dry run',
     'description': 'Preview only; do not write files.', 'default': True},
]
```

这时底层回复的 `value` 是 `{'dry_run': True}` 这样的对象，而**不是** `True`。内置的布尔 `approve_preview()` 并不适用于要读取开关值的业务；需要通过底层 `request('preview', ...)` 取得返回对象，逐项验证后执行。当前已有进程控制流程就是先确认目标，再读取经审批的开关以决定最终操作策略。

**批准时选择行：** 对表格添加与 `rows` 一一对应的、稳定唯一的 `row_ids`：

```python
preview['row_ids'] = ['a', 'b']
```

然后调用 `select_preview_rows()`，获得用户勾选的 ID 列表，例如 `['a']`。**选中零行 `[]` 是有效审批结果，和取消审批不同**；实际业务可自行决定是否允许空选中。可选的 `row_details` 按 `row_id` 为个别行提供展开说明。也可以同时声明行选择与开关，此时回复对象须包含 `selected_rows` 以及所有开关键。

当前 Preview 的主要上限包括：摘要不超过 **16** 项、列不超过 **8** 列、行不超过 **100** 行、详情不超过 **16** 项、开关不超过 **8** 项。列名与行 ID 必须符合指定字符规则；Server 会拒绝多余字段、重复 ID、未知列或非法开关回复。Preview 适合显示**有界的执行计划**，不应代替完整文件浏览或无限长的实时输出流。

## 授权和等待状态的管理

交互必须绑定正在运行的 Web Task，而不是仅凭 `client_id` 就允许弹出窗口。Server 保存并核对当前 `task_id`、`client_id`、`tab_id`，交互回复时重新确认任务仍在 `running` 状态。Client 发起交互还要验证授权令牌所绑定的 `command_id` 与当前前台命令相同。

Client 命令和 Script 通过受限的 `POST /api/interactions/client/request` 进入 Broker。该入口需要 **`interactions:request` 授权范围**，令牌在执行时签发并绑定到当前 Client 命令，受有效期和调用次数约束；不是通用 Web 登录令牌。Server Builtin 在 Server 内部直接访问 Broker，不需要 Client 的 Script Grant，但同样需要当前 Web Task 和标签页身份。

调用方同步等待 Broker 回复。Broker 在等待期间会检查期限、任务是否仍在运行以及当前命令是否仍对应前台任务；超时或任务结束后移除待处理请求并发送解决事件。对已回答、已过期或失效的请求再次回答会报错，不会让原任务恢复执行。

交互期限和命令超时预算是**两个独立限制**。命令如果还要执行耗时操作，必须确保自身有效预算足以覆盖用户交互及后续工作。不能用交互确认取代命令的取消策略，也不能把“用户点击批准”视为敏感操作已安全执行：目标是否还存在、权限是否足够、计划对象是否改变，都应在执行时重新检查。

## Script 的交互上下文

Script 在 `SCRIPT_METADATA` 中声明 `interactions:request`，然后通过 SDK 的 `context` 或 `interactions` 模块调用。适用于从 Web 启动、运行在 **inproc Python 执行策略**中且具有有效 Client 命令上下文的 Script；不能假定 `subprocess_pipe` 脚本或任意脱离 Web Task 的后台 Python 代码也能弹出页面交互。

```python
SCRIPT_METADATA = {
    'name': 'review_example',
    'display_name': 'Review Example',
    'description': 'Ask the operator to review a harmless plan.',
    'category': 'Example',
    'platforms': ['*'],
    'params': [],
    'api_grants': ['interactions:request'],
}

from client.runtime.sdk import context

label = context.ask('Enter a short label:', title='Label', placeholder='Example')
preview = {
    'summary': [{'label': 'Label', 'value': label}],
    'notice': 'No changes will be made in this example.',
}
if not context.approve_preview('Review the input:', preview, title='Review'):
    print('Not approved; no action taken.')
else:
    print('Approved:', label)
```

`context.confirm(message, title=..., timeout=...)` 适合简单确认；`context.ask(..., secret=True)` 获取隐藏显示的字符串；`context.select(message, options, ...)` 返回一项合法选项；`context.approve_preview()` 用于纯审批；`context.select_preview_rows()` 用于可勾选计划。也可显式 `from client.runtime.sdk import interactions` 调用同名接口。

`secret=True` 只意味着 Web 输入控件按保密模式呈现，**不意味着字符串会自动加密存储或永远不会出现在日志里**。脚本不应 `print()` 保密输入，也不应把它插入结果文本。用户取消/超时会导致输入和选择抛出 `ScriptSdkInteractionError`，需要在执行重要操作之前捕获或结束当前流程。

脚本 Metadata 声明授权不等于绕过 Web 用户批准。若没有有效执行 Grant、缺少 `command_id`、当前任务或 Web 标签页失效，请求会失败；不能把这种失败当作默认允许。

## Client 命令的交互接口

普通 Client 命令可以使用 `@confirm` 完成最简确认，或使用 `CommandInteractions` 进行输入、选择和 Preview。详细的命令注册、`@desc` / `@confirm` 注解以及可复制的代码样例见 [Shell-like Commands](shell_like_commands.md)，这里重点说明如何进入 Broker。

```python
from core.utils.decorator import desc
from client.commands.common.services.interaction_service import (
    CommandInteractions, CommandInteractionError,
)

class CommandExampleMixin:
    @desc('Ask for an operation label', group='general',
          api_grants=('interactions:request',))
    def ask_label(self, arg=''):
        try:
            label = CommandInteractions(self).ask(
                'Enter a label:', title='Label')
        except CommandInteractionError as exc:
            return 0, f'No label supplied: {exc}'
        return 1, f'Accepted label: {label}'
```

新的 Mixin 还需接入当前 Client 公共命令组，命令才能被发现。这里的 `api_grants` 由可信的 Server 命令定义核对后签发；直接给 Client 发送自造的 Manifest 项目并不能获取授权。执行时必须在有活动 Web Task 的普通前台命令上下文中调用。

Server Builtin 使用已经存在的 `self.interactions`，不需要 Client Grant：

```python
from server.application.command.interaction_builtin_support import BuiltinInteractionError

# BuiltinCommandHandler 中的方法

def approve_local_action(self, arg=''):
    try:
        approved = self.interactions.confirm(
            'Continue this Server operation?', title='Server confirmation')
    except BuiltinInteractionError as exc:
        yield 0, f'Interaction unavailable: {exc}'
        return
    if not approved:
        yield 0, 'Cancelled'
        return
    yield 1, 'Approved'
```

这个示例只说明 Broker 调用：Server Builtin 自己还要按现有 Handler 的注册和 Web Task 规则接入，并自行实现经过审批的操作。Server Builtin 与 Client 命令的授权路径不同，但共享 `confirm`、`ask`、`select`、`approve_preview`、`select_preview_rows` 等交互方式。

## Web 响应与异常回收

Web 的统一交互窗口根据 `kind` 生成输入控件、选择列表或 Preview；不是每个命令单独实现一个弹窗。实时消息通过 SSE 送到对应标签页，网页可调用 `GET /api/interactions/pending?tab_id=...` 补取未完成请求，最终用 `POST /api/interactions/{interaction_id}/answer` 提交 `approved` 和按需提供的 `value`。这两个浏览器接口仍走 Web 的正常鉴权，不能把它们视为任何用户都可代答的匿名端点。

例如批准一条普通 Confirm：

```json
{"approved": true}
```

批准输入和选择时，`value` 必须为合法字符串；批准带开关/选中行的 Preview 时，`value` 必须是与呈现字段**精确匹配**的对象。拒绝则提交 `approved: false`。`interaction_id` 用于定位尚未完成的请求，不能用另一个任务的 ID 替代。

| 现象 | 原因或排查方向 |
|---|---|
| 没有弹出交互窗口 | 没有活跃 Web Task、标签页不匹配、SSE 未到达；检查待处理请求与任务状态 |
| Client 提示缺少授权 | 命令未声明 `interactions:request`，或 Script Metadata / 执行 Grant 不完整 |
| `@confirm` 拒绝后仍有后续操作 | 应确认危险操作只写在获得批准之后的路径中 |
| 输入/选择突然失败 | 用户取消、交互超时或原执行任务已结束 |
| Preview 返回值不是布尔值 | 声明了 `switches` 或 `row_ids`，应解析并验证对象回复 |
| 选中了零行但业务直接终止 | 空列表可以是有效答复，是否执行由业务决定 |
| 交互窗口出现，但最后操作失败 | Broker 只负责批准/取值；文件权限、目标状态、执行错误需业务代码处理 |
| 后台 Job 没有交互窗口 | 没有符合要求的前台 Web Task；Broker 不是后台通知系统 |

Broker 解决的是“在现有执行流程中征求当前 Web 用户回应”，不是操作审计、完整权限系统、队列调度或多用户审批流。对于不可逆操作，推荐先收集并验证输入，再生成固定的 Preview，收到明确批准后重新确认目标状态，最后执行并返回真实结果。
