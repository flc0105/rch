# Device Monitor：远程监控会话与实时视图

Device Monitor 用于在用户打开监控界面时，按需从指定 Client 采集系统或进程状态，并持续将结果送到当前浏览器。它以 **Monitor Session** 为工作单位：Server 建立会话并绑定设备与浏览器标签页，Client 在独立工作线程中采样，Server 再通过定向 SSE 推送 Snapshot。监控过程不占用普通命令的 Foreground Command Slot，也不要求前端反复执行 Shell-like 命令。

Connection Info 中的 **Dashboard** 和独立的 **Process Manager（Processes / Apps）** 是这套机制的两个完整应用：前者关心设备资源，后者关心进程列表、图形应用和单个进程的详情。它们使用共同的传输协议，却拥有不同的 Session ID、采样内容和生命周期。即使同时打开，二者也无需共享相同的采样周期。

## 1. 按需会话与消息链路

浏览器调用 Monitor Open API 后，Server 根据目标 `client_id` 找到在线连接，生成唯一 `monitor_session_id`，记录发起请求的 `tab_id`、采集 Channel、各 Channel 的周期和可选参数，然后通过现有 Client Socket 发送 `monitor_open`。Client 创建一个由 `stop_event` 控制的守护线程，准备采样器并返回 `monitor_opened`。随后各次采样以 `monitor_snapshot` 返回，Server 通过 WebEventBus 作为 `device_monitor_snapshot` 转发给指定浏览器标签页。

```text
Web Dashboard / Process Manager
       │  HTTP 8085：open / config / close（携带 X-Tab-Id）
       ▼
Server Device Monitor Session
       │  Client Socket：monitor_open / monitor_config / monitor_close
       ▼
Client Monitor Manager ── Session 采样线程 ── psutil / 平台能力
       │  Client Socket：monitor_opened / monitor_snapshot / monitor_error / monitor_closed
       ▼
Server WebEventBus
       │  SSE：device_monitor_snapshot / device_monitor_status（定向 tab_id）
       ▼
当前浏览器中的对应监控组件
```

`client_id` 指定被监控的 Client 连接；`tab_id` 指定接收事件的浏览器标签页；`monitor_session_id` 标识具体监控任务。即使是同一台设备、同一个 Tab，也可以同时存在不同 Session。前端按 **Session ID + Client ID + Channel** 筛选消息，防止 Dashboard 的数据混入进程详情，或已关闭视图的迟到消息更新另一处界面。

Session 信息由 Server 和 Client 分别保存在内存中。它不是 Job、PTY 或 Screen View Session，也不写入命令历史；采集结果没有单独的 SQLite Snapshot 历史。它与 [Connection Lifecycle](connection_lifecycle.md) 中的 TCP 在线状态不同：设备 Online 表示连接可用，不等于目前已经打开了 Monitor Session。

## 2. 会话协议和采样调度

### 创建、配置与关闭

会话创建时可以传入 `channels`、`intervals`、`options`。`channels` 决定本次采集哪些数据；`intervals` 是每个 Channel 的目标采样间隔，单位秒；`options` 保留目标资源等上下文信息，例如单进程监控使用的 `pid`。Server 和 Client 都使用相同的规范化逻辑：去除重复或不支持的 Channel；没有有效 Channel 时采用系统监控的默认组合；间隔限制在 **0.25–60 秒**，缺失或无效值使用该 Channel 的默认周期。

会话创建时处于 `opening`，收到 Client 的 `monitor_opened` 后成为 `open`。浏览器变更订阅使用 `monitor_config`，在现有 Session 内更新 Channel、周期和选项，不需要每次都重建会话。配置时只传入部分字段，Server 会保留未替换的对应会话设置；改变进程目标 PID 时，Client 还会清除旧的进程对象及 CPU 采样基线。

关闭请求会向 Client 发送 `monitor_close` 并把 Server 会话标记为 `closing`。真正收到 `monitor_closed` 后，Server 才从活动会话表移除该项并发布关闭状态。因而 **Close API 返回成功表示关闭请求已被处理，不是工作线程必定已经退出**。Client 发生采样异常会报告 `monitor_error`；正常清理完成后还可能发送 `monitor_closed`。

### Snapshot、状态和定向投递

一次 Snapshot 的主要字段包括会话 ID、采集 Channel、递增的 `seq`、结构化的 `data` 和 `collected_at`（Unix 秒级时间戳）。Server 在转发时补充 `client_id` 和事件时间，将其包装成 `device_monitor_snapshot` SSE：

```json
{
  "monitor_session_id": "本次监控会话ID",
  "client_id": "目标ClientID",
  "channel": "network",
  "seq": 3,
  "collected_at": 1760000000.0,
  "data": {
    "rx_bytes_per_sec": 4096,
    "tx_bytes_per_sec": 1024,
    "bytes_received": 100000,
    "bytes_sent": 50000,
    "interface": "en0",
    "ipv4": "192.0.2.10"
  }
}
```

`seq` 在 **单个 Session** 内递增，不是全项目的全局序号。`collected_at` 记录 Client 采样时间，不代表浏览器收到数据的时间。Server 仅在会话存在且 Channel 合法时转发，并通过 `target_tab_id` 指定 SSE 接收方。打开、关闭和失败则产生 `device_monitor_status`，带有 `state` 与会话基本信息；页面不能把 Snapshot 流和状态流当作同一种数据。

### 周期是采样计划，不是硬实时承诺

Client 为**每个 Session 创建一个工作线程**，在该线程中按 Channel 各自的到期时间顺序采集，而不是为每个 Channel 单独创建线程。完成一次采集后，才从当前时间安排该 Channel 的下一次采样；工作循环以较短等待响应 Stop。某个 Collector 耗时较长，会推迟同一 Session 内其他 Channel 的采集，所以配置 `0.5` 秒不代表每秒必然送达两帧。

Client 打开 Session 时会预热 `psutil` 的 CPU 与网络计数器。`system`、`network` 的首次正式采集需要等待一个周期；存储、电池和进程类 Channel 可较快提交第一份 Snapshot。列表采集等局部错误可以写进对应 Channel 的 `data.error`，而严重异常（如无效进程 PID 或详情采集失败）可能结束整个 Session。切换 Channel 时，采样线程会在发送结果前再次检查当前订阅，丢弃已不需要的迟到结果。

## 3. Info Dashboard：设备资源的持续采集

在 Connection Info 打开 **Dashboard** 时，前端为当前 Client 新建 Session；从 Dashboard 切回 Basic Info、关闭弹窗或切换设备时，停止它。Basic Info 展示的是设备连接及基础属性快照，不需要为那些字段持续开 Monitor Session；Dashboard 才订阅实时资源数据。

Dashboard 将变化速度不同的数据拆到不同 Channel，使用的配置如下。这里是 Dashboard 自身实际提交的订阅配置，而不是一份要求所有新模块照抄的通用模板：

```json
{
  "channels": ["system", "storage", "network", "battery"],
  "intervals": {
    "system": 0.5,
    "network": 0.5,
    "storage": 5,
    "battery": 5
  }
}
```

`system` 提供 CPU 百分比和逻辑核数、内存与 Swap 的用量、设备启动后的运行时长以及进程数量。CPU 使用 `psutil.cpu_percent(interval=None)` 非阻塞采样，需要有前一帧作为测量基线；macOS 下还会处理偶发的单帧 0% 毛刺，避免图表因孤立采样值明显跳动。

`network` 使用设备累计接收/发送字节计数，以两次采样的时间差计算 **bytes/s** 速率，同时选取处于活动状态的网络接口及 IPv4。它反映设备全部网络活动，**不是** Remote Files、Transfer Center 或 RCH Socket 自身的传输速率。第一次采样未建立有效计数器差值时，速率可能显示零值。

`storage` 对实际磁盘分区采集容量、已用、剩余及挂载信息，并按平台过滤虚拟/不适合展示的卷。macOS 重点展示系统根卷与 `/Volumes` 下的卷；Windows 结合驱动器类型和卷标；其他平台过滤 proc、sysfs 等伪文件系统。对 macOS APFS 根卷，Collector 按共享 Container 的容量语义规范化 used/free/total，使数字可以相互对应。

`battery` 返回是否可用、百分比、是否接电及可得时的剩余秒数；设备没有可访问的电池信息时返回 `available: false`，Dashboard 显示 No battery，而非把不存在的电池错误解释为 0%。

前端只接受与当前 Dashboard Session 匹配的 `system`、`network`、`storage`、`battery` 快照，分别更新对应资源卡片和最后更新时间。Dashboard 的 Live 标识表示近期收到监控数据，不应被理解为 TCP 连接的 `online/stale/offline` 判定结果；连接健康度另由连接生命周期机制维护。

## 4. Process Manager：进程、图形应用与详情

Process Manager 是一个独立窗口，进入时创建**自己的** Monitor Session，默认以 1 秒为周期订阅 `processes`。切换到 Apps 标签时，向原 Session 发送 `monitor_config`，把采集 Channel 改成 `apps`；切回时再改回 `processes`。窗口里的 Refresh 会重启这条监控 Session，搜索框则过滤前端已经收到的列表，而不是为每次输入发起新的远程查询。窗口关闭时释放当前监控 Session；再次打开会创建新的 Session。旧关闭动画的迟到回调不得关闭已重新打开的监控。

### Processes 与 Apps 的数据语义不同

`processes` 由 Client 的进程服务基于 `psutil` 获取进程列表，展示 PID、PPID、名称、用户名与进程状态。某些字段可能因为进程在扫描期间退出或系统权限不足而不可读取，前端不能把字段缺失直接当成整个 Client 离线。

`apps` 关注图形应用，不等于进程列表的另一种筛选。Windows 通过可见窗口取得关联 PID，再映射进程；macOS 通过 System Events 查询非后台应用进程，并结合进程信息整理结果。当前 Linux 与 iOS 的 Apps Collector 不提供同等实现，返回不支持的采集错误，而不是保证一定有图形应用列表。macOS 的 System Events 查询有单独的执行超时；超时或短暂失败时，相关逻辑可能复用先前成功获取的应用列表。因此 Apps 显示内容不保证每一帧都完全等同于操作系统瞬时状态。

进程和应用列表的采集错误由 Snapshot 的 `data.error` 带回，前端可展示错误并保留当前监控窗口；这与整个 Session 的 `monitor_error` 是不同级别的失败。

### 单进程详情独立订阅

点击 Details 时，Process Manager **另外创建一条 Session**，不会抢占 Processes/Apps 列表的采样配置。详情 Session 通过 `options.pid` 指定目标，分别订阅基础属性（1 秒）、网络连接（2 秒）和打开文件（3 秒）。三个 Channel 在当前实现中为 `process_detail`、`process_connections` 和 `process_open_files`。

基础属性来自进程服务，包括 PID、PPID、进程名称/状态、用户名、可得时的可执行路径、工作目录、命令行、创建时间、CPU、内存、线程数及平台支持的句柄/文件描述符等。网络连接快照包含本地/远程地址、状态等信息；打开文件返回路径和可得的 FD。详情采样复用该 PID 的 `psutil.Process` 对象，首次 CPU 百分比会用 `null` 标记尚未建立基线，而不是误导性地报告 0%。如果将详情 Session 的 `options.pid` 改为另一进程，会清除对应缓存和 CPU 基线。

打开详情、关闭详情、窗口关闭或设备切换分别有自己的 Session 生命周期。收到 Snapshot 时，前端既校验 Session ID，也会在关联子项中检查 `pid`，避免旧进程数据覆盖当前详情。

### 进程控制不属于采样会话

Processes 和 Apps 都可以通过界面执行 Terminate，但这不是向 Monitor Session 发 `monitor_config` 或在采样线程里直接操作目标进程。界面先请求确认，随后调用独立的进程控制 HTTP API，Server 通过远程前台命令执行链提交终止请求。终止完成后界面更新列表；后续 Monitor 采样也可能反映进程已经消失。

因此 **Monitor 负责观察，Terminate 负责修改远程状态**。前者不占用 Foreground Command Slot，后者遵循独立的控制与执行边界。需要更加完整的会话确认及命令权限说明，可参阅 [Interaction Broker](interaction_broker.md) 和 [Shell-like Commands](shell_like_commands.md)。

## 5. 为新监控视图接入相同机制

新视图不需要自行轮询某条 Shell 命令。它只需要创建 Session、记录服务端返回的 ID、订阅通用 SSE 事件，并在必要时配置或关闭会话。以下接口工作在基础 Web/API 服务上，**不是** 8086 文件传输接口：

| 方法 | 地址 | 语义 |
|---|---|---|
| `POST` | `/api/connections/{client_id}/device-monitor/open` | 为目标在线连接创建新 Session |
| `POST` | `/api/device-monitor/{monitor_session_id}/config` | 更新现有 Session 的订阅和周期 |
| `POST` | `/api/device-monitor/{monitor_session_id}/close` | 请求停止并释放 Session |

所有这些请求均须携带当前浏览器的 `X-Tab-Id`，Config 与 Close 还会核验 Session 所属 Tab。该 ID 是**路由与会话归属标识**，不是用于代替 Web 认证的秘密凭据。会话管理接口通过项目既有 Web 认证体系访问。只记录 `monitor_session_id` 而不保留 `tab_id`，会使后续更新、关闭请求无法正确关联目标会话。

以一个需要进程详情的视图为例，Open 的请求体可写为：

```json
{
  "channels": ["process_detail", "process_connections", "process_open_files"],
  "intervals": {
    "process_detail": 1,
    "process_connections": 2,
    "process_open_files": 3
  },
  "options": {"pid": 12345}
}
```

创建请求会立即返回带 `monitor_session_id` 的会话信息及 `opening` 状态；真正收到 `device_monitor_status` 的 `open`，以及其后的 `device_monitor_snapshot`，才代表 Client 已经进入实际采样。前端应只应用自己的 Session 快照，按 Channel 将 `data` 映射到界面；遇到 `error` 或 `closed` 状态，要清理 UI 中的会话引用，而不是继续认定数据正在实时更新。

如果扩展的是**协议中尚不存在的新指标**，还须同步完成共享 Channel 定义、默认采样周期、Client Collector、前端数据渲染及生命周期处理。不能仅在浏览器请求体中填入任意新名字：不认识的 Channel 会被规范化逻辑过滤，没有有效 Channel 时还会落回默认系统指标。需要进程、路径或其他资源身份时，应通过明确的 `options` 传递，并在 Collector 中进行校验和平台适配。

## 6. 会话结束、容错与资源限制

打开 Dashboard、切换页面或关闭 Process Manager 时，前端会调用 Close API；在 `pagehide` 事件中使用 `fetch(..., {keepalive: true})` 尽量完成清理。Client 断线时，Client Runtime 会停止本地会话，Server 也会移除该 Client 对应的监控会话并通知相关 Tab。监控任务作为内存运行态，Server 重启或 Client 重连后不会自动恢复先前的实时采样；用户需要重新打开视图以创建新 Session。

Server 状态通常经历 `opening → open → closing → closed`，但异常时可能先变为 `error`，随后清理为 `closed`。即使关闭请求已经接受，底层 Collector 若正执行耗时系统调用，也只能在调用返回并检查 `stop_event` 后完成退出。Server 的关闭状态与 Client 工作线程实际退出之间会有短暂时间差。

**当前没有通用的 Monitor Session 租约超时或定时清理机制。** 正常页面关闭依靠显式 Close，异常中断的浏览器不保证立即撤销采样；若客户端仍连接、Close 又没有成功送达，资源可能继续占用，直到后续关闭、Client 断线或进程结束。因此不应将 Monitor Session 当成长期无需维护的后台 Job，也不应为暂时不用的界面持续保留高速采样。

采样负载和平台能力同样限制实际表现：高频 CPU/网络采集与低频磁盘、电池采集应分开调度；应用枚举可能涉及系统权限或慢速平台接口；进程可能在两个 Snapshot 之间退出；细节列表也可能因权限不足缺少文件或连接信息。Dashboard 的图表和 Process Manager 的列表仅表示最近一次成功接收到的采样结果，不是某个固定时点的全系统原子快照。
### Process Manager usage columns and navigation

`processes` and `apps` monitor snapshots include `cpu_percent` and `memory_percent` where psutil can read them. CPU uses nonblocking per-process samples; the first sample has no baseline and is shown as `-`, then updates on the existing 1-second cycle. Memory is the process share of physical RAM (percent). These numbers are per process, not the overall Dashboard CPU/Memory figures; CPU per-process may exceed 100% on multicore systems. PID, Name, CPU and Memory columns are sortable in both tabs; chosen sort order persists across live snapshots. Clicking the Dashboard CPU or Memory overview card closes Connection Info first, then opens the existing Process Manager on All Processes (after the closing transition), sorted descending by that metric; this prevents overlapping modal layers from hiding the target dialog. No extra monitor channel or endpoint is required.
