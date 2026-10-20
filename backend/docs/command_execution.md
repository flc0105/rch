# Command Execution Pipeline 与 Web Tasks

RCH 将“提交一条指令”和“得到该指令的完整执行结果”分成两个阶段。Web 先向 Server 创建任务，Server 再把指令交给相应的执行路径；持续产生的输出通过 SSE 回到发起任务的浏览器标签页。这里的 Task 是一次 Web 执行的临时协调对象，不等同于 Client 上运行的进程，也不等同于持久的 Command History、Background Job 或交互式 PTY。

本篇以 Web Terminal 的一次执行为主线，解释任务身份、命令分流、前台串行约束、Client 结果流、取消和最终收尾，同时说明 Script、Quick Actions、上传及其他控制入口何处共用这条链路、何处另有边界。

## 1. 从输入到执行结果的完整链路

在 Terminal 输入非空命令并选定在线 Client 后，浏览器调用：

```http
POST /api/connections/<client_id>/command
Content-Type: application/json
X-Tab-Id: <browser-tab-id>

{"command":"pwd"}
```

其中 `pwd` 仅是展示普通命令提交形式的示例，并非所有指令都会经由 Client Shell 直接解释；具体解释规则取决于 Server 的 Command Executor。接口成功时按 Web API 通用格式返回 `code/message/data`：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "e5d9b10c52e74d2bb3eefaf392199e8d",
    "client_id": "client-instance-id",
    "command": "pwd"
  }
}
```

**HTTP 成功只代表任务已接受并启动执行线程，不代表远程命令已经完成或执行成功。** Terminal 在提交之前会先显示输入命令行；随后收到的异步结果和完成状态才决定这条执行的最终呈现。

完整顺序如下：

```text
Web 输入 / 其他 Web 执行入口
  │  POST + command + X-Tab-Id
  ▼
WebCommandExecutionApi（参数标准化）
  │
  ▼
WebTaskService（定位 ClientSession）
  ├─ CommandHistoryOrchestrator：根据记录策略创建 history entry
  ├─ WebTaskStore：创建内存 task_id，初始状态 running
  ├─ SessionExecutionRuntime：尝试占用前台执行槽
  └─ 启动 WebTaskRunner 后台线程 → HTTP 返回 task_id
        │
        ▼
CommandExecutionPipeline / CommandExecutor
        ├─ Server Built-in（可能在 Server 端完成）
        ├─ Alias 解析及远程命令计划
        └─ Client 指令 / ACMD / Script 等远程执行
                │ 生成 command_id，绑定 history entry
                ▼
          ClientSessionCommandChannel → TCP → Client
                │
                ▼
          result 分片、取消 ACK、工作目录更新
                │
                ▼
WebTaskRunner 消费执行事件
  ├─ 逐段发布 command_result SSE
  ├─ 在允许记录时追加历史输出
  ├─ 确定 success / error / cancelled
  └─ 发布 command_complete SSE、释放前台槽并清除临时 Task
                │
                ▼
原浏览器标签页更新 Terminal 或对应 Dialog
```

这里有两点决定整个设计：执行线程负责消费迭代结果流，不阻塞提交请求；浏览器依赖事件流获取输出，而不是反复轮询单条 Task 的查询 API。

## 2. 一个执行过程中存在几种不同的身份

不能用一个 ID 代替整个执行过程。每层 ID 的分配范围和生命周期不同：

| 标识 | 何时产生 | 真正标识什么 | 主要用途 |
|---|---|---|---|
| `client_id` | Client 运行实例启动时 | 目标 Client 实例 | 定位当前 Socket 会话与前台执行槽 |
| `task_id` | Server 接受 Web Task 时 | 一次 Web 提交 | 取消 API、Web 活动状态、SSE 关联 |
| `command_id` | 真正下发 Client 消息时 | 该 Socket 会话上的一条命令消息 | 匹配 `result`、`cancel_ack`、取消目标及 Script Grant |
| `history_entry_id` | 满足记录策略的执行开始时 | 一条持久化执行历史 | SQLite 输出记录、状态、回放与 Artifact 关联 |
| `tab_id` | 浏览器标签页上下文建立时 | 发起操作的浏览器标签页 | 定向投递 `command_result` / `command_complete` |

`task_id` 是 `uuid4().hex`，任务最初记录 `running`、`cancel_requested=false`，并附带 `client_id`、`machine_id`、`hostname`、`tab_id` 等上下文。它保存在 Server 的加锁内存字典中，**不是 SQLite 的任务表**。任务完成后 Runner 主动删除这条记录，因此不能将 `task_id` 当成长期有效的历史记录 ID。

`command_id` 是每个 ClientSessionCommandChannel 自增的消息序号。**Server Built-in 不一定下发远程消息，因此可以有 `task_id` 而没有 `command_id`**；同理，不能假定二者数值相等。远程命令实际组装消息时，`SessionExecutionRuntime.bind_command_execution()` 将 `command_id` 同当前前台 Task 与 `history_entry_id` 绑定，避免取消、结果与历史错位。

`history_entry_id` 只在集中式记录策略允许时存在。Web Task 可以正常执行、产生 SSE 和最终状态，却根本没有对应历史条目；不应根据一个 Task 出现在 Terminal 就断言 SQLite 一定记录了它。详见 [Command History](command_history.md)。

## 3. 执行计划与实际指令不是同一层

`CommandExecutionPipeline` 统一负责“开始、逐段输出、错误、结束”事件；实际执行入口则由 `CommandExecutor` 处理。这个分层允许 Web、Server CLI 等不同入口沿用命令解释规则，而不要求它们都使用 Web Task。

首先会处理纯语法入口（例如历史索引快捷回放），再按名称解析。Server Built-in 由独立处理器接管；否则交给命令规划器，规划器可以解析 Alias、构造普通 Client 命令、ACMD 参数命令或结构化 Script 计划。规划器只产生应当执行的命令类型、文本与 `extra`，真正的远程执行交给 Session 的命令通道。

需要区分以下语义：

- **Server Built-in**：在 Server 执行，或通过已有服务调用继续操作；它未必占用一个 Client 侧的独立命令消息。
- **普通 Client 命令**：在目标 Client 的命令注册体系中解释，不等同于默认交给系统 Shell；显式的 Shell-like 命令另有解析和执行约束。
- **Alias**：先根据机器平台等上下文将用户输入展开为真实执行计划，但执行历史通常保留原始用户输入；可输出展开提示。
- **ACMD**：按命名参数解析，将参数字典通过协议的 `extra` 提交给 Client 的结构化命令处理器。
- **Script**：Server 可以为 Script 组装额外执行参数及最小权限的 Script Grant，再通过对应的远程执行类型下发；Web Dialog 与 Terminal 输出走同一个 Task 生命周期。

在代码层面，执行器先给出 `(status, result)` 迭代输出，流水线再转换为 `CommandExecutionEvent`：`started`、`progress`、`chunk`、`error`、`cancelled`、`completed`。结构化 `result` 可以自带 `event_type`，但普通 `(status, text)` 也可进入统一事件流。`status=0` 通常生成错误事件，其他状态生成普通输出块。

这意味着**一条 Web 命令可能对应多个输出分片、一条完成事件，也可能在完全没有 Client `command_id` 的情况下完成**。不要用“HTTP 请求次数”推断“Socket 命令数”。更详细的命令语义分别参见 [Shell-like Commands](shell_like_commands.md)、[ACMD](acmd.md)、[Scripts](scripts.md) 和 [Aliases / Quick Actions](alias_quick_actions.md)。

## 4. 前台串行约束与执行并发

RCH 在单个 `ClientSession` 上保留一份当前前台 Task 运行态，不是所有浏览器标签页各自拥有一个互不影响的前台槽。普通 Web 命令提交时，在启动 Runner 之前调用 `acquire_foreground_task()`；如果该会话已经被另一前台任务占用，就抛出 `Client is busy: ...`，而不是把新命令悄悄排入一个没有界面的队列。

占槽记录包括 `task_type`、`command`、`source`、`task_id`、可选 `history_entry_id`、稍后绑定的 `command_id`、`cancel_requested` 和 `cancel_state`。失败的提交会释放可能占到的槽、撤销本次创建的 Task，并清理尚未真正执行的历史条目；不会将这些失败准备步骤当作一次成功执行。

后台执行线程结束时会在 `finally` 中释放当前会话的前台槽。仅使用 `task_id` 和命令文本匹配当前占槽对象，避免迟到的清理动作把下一条任务的槽释放掉。

**前台槽是执行策略，不是“Client 一次只能做一件事情”的全局锁。** 心跳、监控会话、通知、PTY、某些文件传输与后台 Job 有各自的控制或数据通道；它们不等于再创建一个普通 Web Command Task。但通过同步远程命令访问 Client 的其他 API，如运行时配置查询或进程控制，仍可能遵守统一前台占槽要求。

目前两类 Web 请求有明确例外：

- **独立 TransferManager 的 Web Upload**：仍可创建 Web Task 与上传历史上下文，但上传执行路径 `use_foreground_guard=False`，进度和取消还需配合 TransferService 维护；不同传输策略并非一律支持取消。
- **经验证的 HTTP 控制请求**：`httpctl` 恢复操作可绕过常规前台槽，通过另外的 HTTP Control 队列供 Client/Watchdog 轮询；它不等同于普通远程命令消息，也不是对任意指令关闭忙碌保护。

这种例外来自具体执行链的机制要求，不能将它当作开发新命令时默认可绕过前台槽的依据。

## 5. Socket 结果如何抵达 Web 并形成最终状态

远程命令通过 `ClientSessionCommandChannel.send_command()` 构造 `type/id/text` 和必要的 `extra`，将它发送给 Client。对 Script/某些带受保护能力声明的 Client 命令，附加参数可能包含与本次 `command_id` 绑定的短期 Grant；授予范围取自 Server 信任的声明，绝不只根据握手 Manifest 中的自报内容批准权限。

收到 Client 返回的 `result` 时，Server 先更新相关工作目录，再交给结果分发器。只有 `id` 与当前队首等待的 `command_id` 匹配，才将 `(status, text, eof)` 投入对应的执行结果队列；正常输出因此按照该等待流逐块消费，直到终止标记 `eof`。不匹配的结果会落入独立的未预期消息处理路径，不能简单并入当前 Terminal 命令的输出。

`WebTaskRunner` 消费标准化事件后执行两件相互独立的操作：向 WebEventBus 发布 `command_result`，并在存在 `history_entry_id` 时追加到 SQLite 历史。最后统一发布 `command_complete`。典型 SSE 消息如下：

```text
event: command_result
data: {"task_id":"<task-id>","client_id":"<client-id>","command":"pwd","command_id":1,"status":1,"text":"/home/user","metadata":{},"time":"<server-local-iso-time>"}

event: command_complete
data: {"task_id":"<task-id>","client_id":"<client-id>","command":"pwd","command_id":1,"success":true,"status":"success","metadata":{},"cancel_requested":false,"cancelled":false,"time":"<server-local-iso-time>"}
```

Web 在 `GET /api/stream?tab_id=<browser-tab-id>` 订阅事件。提交时将同一 `tab_id` 通过 `X-Tab-Id` 传给 Server，Server 才能把该 Task 的输出和完成事件送到相应标签页，而不是传播给所有打开的终端。若提交时没有提供有效 `tab_id`，事件总线不会具有这个定向范围，因此前端应保持两端使用同一标签页标识。

普通 Terminal 将 `command_result.text` 追加到当前设备的输出视图，接到 `command_complete` 后显示成功、失败或取消提示，并清除活动 Task。对于 Script、Quick Action 的 Dialog 展示，前端根据请求 Metadata 把这一 Task 的事件交给相应对话框处理，而不是另建执行引擎。前端还维护少量“已完成 Task ID”标记，处理**完成 SSE 比提交 HTTP 返回更早到达**的竞态，避免短命任务被迟到的 `setActiveTask` 重新显示成 Busy。

最终状态由结果流汇总得到。`status=0` 的失败块通常使 Task 进入 `error`；可以被明确识别的非致命取消能力提示不会被误当成致命执行失败。若已发出取消请求且实际收到取消或超时类结果，则可判为 `cancelled`。单纯调用取消 API，或者 Client 给出“接受取消”的 ACK，均不等于已经进入取消终态。

**这些 SSE 事件是面向当时的在线订阅者的实时投递，不等于完整的任务事件重放日志。** 页面重连以后，可以查询符合策略且已写入 SQLite 的执行历史，但不能凭已删除的内存 Task 恢复完整 Task 运行态。

## 6. 取消是多阶段协商，不是同步杀进程

在 Terminal 中点击取消时，前端使用当前设备记录的 `task_id`：

```http
POST /api/tasks/<task_id>/cancel
```

正常接受取消时的 API `data` 包含 `task_id`、`client_id`、`status: "cancelling"`、可能存在的 `command_id`、`history_entry_id`。浏览器仅显示“已发送取消请求”，不能立即显示“已取消”。

Server 首先确认 Task 仍是 `running` / `cancelling`，并且它确实对应当前 ClientSession 的前台任务；随后设置 `cancel_requested=true`。如果远程消息已经生成 `command_id`，Server 发送 `type: cancel`、`target_id: command_id`；如果此刻尚未真正下发命令，运行态先记下取消请求，命令通道完成 ID 绑定并发送后会立即补发取消消息。

Client 的执行上下文决定是否能取消：对于不支持取消的策略可以拒绝；合作式取消在后续检查点退出；进程型策略可以尝试终止关联的进程。`cancel_ack` 是独立消息，Server 根据目标 `command_id` 更新 `cancel_state`，例如 `requested`、`accepted`、`rejected`、`stopped`、`completed`。迟到的 `accepted` ACK 不会覆盖已观察到的 `stopped` 等完成状态，重复取消也不会把已确认状态降回 `requested`。

这里必须同时辨别三个信号：**取消请求被 API 接受、Client 接受或拒绝取消、执行结果流真正结束**。只有结果流终止后，Runner 才计算并发布最终 Task 状态。Client 可能拒绝取消，也可能接受后正常完成；是否出现 `cancelled` 取决于最终输出，而不是用户是否点击过 Cancel。

对于走独立 TransferManager 的上传，常规前台 Task 取消校验可能不适用，Server 才会根据与 Task 关联的活跃 Transfer 查找 `transfer_id`，检查当前传输是否支持取消，并发送 `transfer_cancel`。它与普通 `command_id` 的取消不是同一协议。详细传输机制参见 [File Transfer](file_transfer.md)；交互式确认与取消边界见 [Interaction Broker](interaction_broker.md)。

## 7. 历史、资源和错误收尾

**历史条目在任务提交阶段按策略创建，而非完成后无条件补写。** 集中的 `CommandHistoryRecordPolicy` 判断应否记录，避免把 Web 高频文件浏览、部分进程控制、Job 控制、上传、结构化 JSON 任务等大量操作污染用户命令历史。用户手动输入的普通命令与符合回放条件的执行通常会记录；Script 等其他模块不一定创建这一类历史条目。规则应在同一策略入口扩展，而不是在每个按钮里各写一套判断。

对允许记录的执行，SQLite Entry 从 `running` 开始，连续输出追加 `status/text/eof` 等记录，并更新行数、字符数、截断标记。持久化输出有数量和字符上限，因此**实时 SSE 中看到的全部输出不保证永久完整保留在历史中**。最后更新 Entry 的成功/错误状态、结束时间及最终工作目录。`command_id → history_entry_id` 映射还允许关联命令产生的 Artifact；当等待流结束时，对应映射和按命令授予的临时 Script Grant 会清理。

Command History 与 Web Task 终态存在一个语义差别：历史的结束状态主要是 `success/error`，Web Task 可以进一步显示 `cancelled`。因此查询历史不能直接等价还原 Web 的每一项任务状态和取消 ACK。

异常链路按以下原则收尾：

- **提交时找不到 Client 或 Client 忙碌**：请求报错，取消创建中的 Task/历史准备步骤；前端展示提交失败，不应等待不存在的成功 SSE。
- **执行规划或远程迭代抛异常**：Pipeline 或 Runner 将错误转成输出事件，标记失败，再尽力进入统一收尾。
- **Client 连接关闭、响应中断**：可能触发等待流结束或异常，最终由 Runner 标记状态；不能把“没有新输出”当作必然执行成功。
- **SSE 订阅断开**：Task 线程不以浏览器 EventSource 的生存时间为条件自动停止；已有 Task 会继续按执行流运行，用户界面可能暂时丢失实时分片。
- **Task 结束**：先记录终态、发送 `command_complete`，再从 WebTaskStore 删除内存记录；在 Runner 的 `finally` 路径释放当前占用的前台槽。

`WebTaskStore` 不提供持久化恢复，也不应承诺 Server 重启后仍可使用旧 `task_id` 调用取消。若用户要求长期任务、后台驻留或可恢复执行，应使用 Background Job 等相应机制，而不是延长 Web Task 的内存状态生命周期。

## 8. 在新功能中复用执行链

新增一个 Web 执行动作，应首先判断它是**会占用前台执行槽的命令**、**无需 Client 命令通道的 Server 操作**，还是**有自己 Session 或 Transfer 生命周期的后台操作**。如果目标是让浏览器提交命令并实时展示结果，优先复用 `WebTaskService` 创建 Task、`CommandExecutionPipeline` 标准化事件，以及 `WebTaskRunner` 的输出与收尾，不应另写一套 `Thread + EventBus + History`。

Web 入口需要提供明确的 `client_id`、命令、`tab_id` 和必要的呈现 Metadata；业务层应使用可信参数构造命令计划，不能把前端展示文案误当执行语句，也不能将任意 Client 自报能力当成 Server 授权依据。前台槽在任务创建后、线程启动前申请；涉及后台传输或 HTTP 恢复队列时才按已有独立执行模型选择相应路径。

前端通常应处理三种独立时刻：**提交返回**保存 `task_id`；**结果事件**按任务上下文显示输出；**完成事件**清理 Busy 状态。Dialog 采用 Metadata 做结果路由时，应维持相同 `task_id` 与 `tab_id`；不能只凭命令字符串匹配，因为相同命令可以重复执行。

对新命令类型，还应核对 Client Command Manifest、Command Planner 与实际执行协议是否一致，是否需要参数 Schema、交互确认、超时或取消策略，以及应否进入 Command History。把这些能力挂到统一执行链中，才能保持 Terminal、Dialog、历史和取消操作语义一致。

### 相关机制

- [Client Handshake & Capability Discovery](client_handshake.md)：目标 Client 的身份及命令能力声明。
- [Command History](command_history.md)：History/Recent/Pin、输出保存和回放。
- [Structured Output](structured_output.md)：结构化结果如何进入终端展示。
- [Scripts](scripts.md)、[Background Jobs](background_jobs.md)：前台脚本任务与长期后台执行的区别。
- [SSE Notifications](sse_notifications.md)：事件总线、定向事件及通知分发。
- [Connection Lifecycle](connection_lifecycle.md)：Socket 连接和离线状态对任务执行的影响。


## Server Builtin 统一路由

Server 只将 `SERVER_COMMAND_REGISTRY` 显式注册的一级名称作为 Builtin，先用公用子命令解析器识别 `script/job/alias/xt/history` 等命令，再交给原业务 Support。未命中注册表的普通命令继续走 ACMD → Alias → Client 普通执行；Client 未注册的普通命令保留 Shell 后备执行。`script exec` / `script run` 两种 Server 输入共用原 `COMMAND_TYPE_SCRIPT` 执行协议，不把结构化 Payload 交给 Client 再做 Builtin 解析。
