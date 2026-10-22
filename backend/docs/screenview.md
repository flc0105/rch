# Screen View

Screen View 为在线 Client 建立带状态的图像采集与远程输入会话。Client 采集屏幕并编码帧，Server 协调会话和消息转发，浏览器显示图像并将鼠标、键盘事件映射回目标桌面。画面流与输入控制由会话协议管理，不持续占用普通命令前台槽。

采集质量、差分帧、坐标换算和输入后端是同一画面链路上的不同环节。网络连接、平台权限或图形桌面不可用时，可能出现能建立会话却无法取得或控制画面的情况。

## 屏幕会话的控制与数据路径

Screen View 的通信分为三层：

```text
Frontend（浏览器）
  显示画面、设置帧率与质量、发送鼠标键盘事件
              ↕ WebSocket / HTTP
Server（会话中转）
  创建会话、管理状态、缓存最新画面、转发控制事件
              ↕ Client 已建立的消息通道
Client（远程设备）
  截取屏幕、编码 JPEG、发送画面、执行系统输入
```

用户在设备工具栏打开 **Screen View** 后，会经过以下过程：

1. 浏览器选择目标在线 Client，向 Server 请求创建屏幕会话。
2. Server 分配独立的 `screen_session_id`，生成 WebSocket 访问令牌，将状态设为 `opening`，并向目标 Client 发送 `screen_open`。
3. Client 建立屏幕采集线程，回复 `screen_opened`，随后按指定 FPS 周期采集屏幕并发送 `screen_frame`。
4. Server 将收到的画面保存为该会话的最新帧。浏览器优先通过 WebSocket 接收、解码和显示；必要时改为 HTTP 轮询。
5. 用户操作预览区域时，浏览器通过 WebSocket 发送输入事件，Server 再经 Client 消息通道转发给被控设备。
6. 关闭窗口、重启预览或 Client 断开连接时，会话进入关闭流程，并释放采集与输入控制状态。

采集、画面传输和输入控制各有独立职责：**看到画面不代表远程输入一定可用**。例如，系统允许截图却不允许注入鼠标键盘时，预览仍可能正常，但 Control 会收到错误并被关闭。

Server 为每个会话维护独立状态。同一 Client 已有活动 Screen View 时，新的打开请求会被拒绝并提示该设备已开启 Screen View，不会关闭正在使用的会话。关闭中的会话不阻止下一次正常打开。

## 采集管线与帧编码

Client 优先调用 Pillow ImageGrab 截图，出现异常时再尝试使用 PyAutoGUI。采集时优先请求所有屏幕；Windows 还会结合虚拟桌面的原点处理多显示器可能出现的负坐标。截图被转换为 RGB，再用 JPEG 编码。若截图组件不可用、桌面会话不存在或系统权限不足，采集线程会报告错误并结束该会话。

目前提供 `full_jpeg` 和 `keyframe_delta` 两种帧策略。选择的是**帧数据如何生成和重建**，并不是两种不同的网络连接方式。

### 完整帧编码

`full_jpeg` 是默认策略。Client 每次采集完整画面，编码成一张独立 JPEG 后发送。浏览器将收到的 Base64 图像显示为完整屏幕帧。

这种方式不依赖之前的画面，丢失中间帧也不会影响下一帧的解码，适合作为通用默认方案。代价是即使桌面只有很小的变化，也会重新编码并发送整屏图像；画面静止时仍按采集周期发送完整帧。

### 关键帧与差分帧

`keyframe_delta` 使用固定 Keyframe（关键帧）和变化区域 Delta（差分帧）减少数据量：

1. 首帧始终是完整 Keyframe，记录作为比较基准的画面。
2. 后续截图与**当前 Keyframe** 比较，计算发生变化的矩形区域。
3. 变化矩形向四周扩展最多 8 像素，裁剪该区域并编码为 JPEG Patch；浏览器将其绘制到与 Keyframe 对应的画布位置。
4. 当扩展后的变化面积达到整屏面积的 **50%**、距离上次 Keyframe 已经过 **2 秒**，或屏幕分辨率改变时，直接发送新的完整 Keyframe。
5. 如果画面相对 Keyframe 没有变化，则本次编码返回空结果，不发送图像帧。

**Delta 始终相对于固定 Keyframe，而不是上一张 Delta。** 因此，同一 Keyframe 之间的中间差分帧可以被跳过。浏览器只要拥有当前基准关键帧和与之匹配的最新 Delta，就可以重建当前画面。

Server 不保存连续录像队列，而是保存当前 Keyframe 和最新的一张帧数据。浏览器请求更新时，如果缺少最新 Delta 所依赖的 Keyframe，Server 会先返回 Keyframe，再返回最新 Delta。对于 `full_jpeg`，只需要返回最新一帧。

| 特性 | `full_jpeg` | `keyframe_delta` |
|---|---|---|
| 当前默认策略 | 是 | 否 |
| 完整画面帧 | 每次采集都发送 | 首帧、定时或变化过大时发送 |
| 局部变化 | 仍发送整屏 JPEG | 发送变化矩形的 JPEG |
| 完全静止 | 仍可能持续发送 | 可跳过发送 |
| 丢失中间帧 | 下一帧可直接显示 | 需要保留对应 Keyframe |
| 浏览器渲染 | 完整图像 | Canvas 组合关键帧与补丁 |

策略由 Client 运行时配置决定，**创建会话时选定**。修改策略不会把当前会话的编码器中途替换；需要重新打开 Screen View 才会使用新策略。目前没有根据带宽或画面变化量自动在两种策略之间切换的功能。

### 帧更新和丢帧处理

Client 发送的帧包含会话 ID、编码策略、帧类型、序列号、基准序列号、图像尺寸、Patch 位置与尺寸、JPEG 的 Base64 数据、压缩字节数和采集时间。

| 字段 | 作用 |
|---|---|
| `screen_session_id` | 指定该帧所属的屏幕会话 |
| `frame_strategy` | `full_jpeg` 或 `keyframe_delta` |
| `frame_type` | `full`、`keyframe` 或 `delta` |
| `frame_seq` / `base_seq` | 当前帧序列号 / 所依赖的关键帧序列号 |
| `width` / `height` | 整个采集画面的像素尺寸 |
| `patch_x` / `patch_y` | 变化区域在整屏画面中的左上角位置 |
| `patch_width` / `patch_height` | 变化区域的尺寸，完整帧则等于整屏尺寸 |
| `data` | Client 消息中的 Base64 JPEG 内容 |
| `bytes` / `captured_at` | JPEG 大小 / 采集时间 |

Server 对外提供的帧对象将 Base64 图像放在 `frame` 字段，并以 `seq`、`base_seq` 等字段标识重建关系。它会检查序列号、画面尺寸、Patch 边界，以及 Delta 是否引用当前有效的 Keyframe；不符合要求的帧不会更新当前画面。

WebSocket 发送循环约每 **30 毫秒**查询一次会话的最新状态，只向浏览器发送需要更新的帧。它不承诺将每次采集到的历史画面逐帧送达，优先保证实时画面能够追上最新状态。

浏览器无法建立 WebSocket 时，会尝试每 **250 毫秒**通过 HTTP 轮询获取最新帧和状态。这个回退路径可以继续用于画面查看，但现有实时鼠标键盘控制依赖 WebSocket，因此轮询模式不能作为完整远程控制通道使用。

## 远程输入的坐标和事件语义

Screen View 不只是只读画面。Server 默认将新会话的 `control_enabled` 设为 `true`，Client 打开会话后会收到输入准备消息。不过，前端 Control 实际可用还取决于会话已经打开、首帧已经成功显示以及 WebSocket 已连接。

启用 Control 后，浏览器把预览区域中的鼠标位置换算为 **0～1 的归一化坐标**。Client 再根据本机可用的输入坐标空间还原实际位置。采用这种协议，是为了避免直接传浏览器窗口尺寸或截图像素坐标时，在多屏、缩放和高 DPI 环境下产生偏移。

支持的输入动作如下：

| 动作 | 实际行为 |
|---|---|
| `mouse_move` | 移动远程鼠标指针 |
| `mouse_down` / `mouse_up` | 按下或释放左、中、右鼠标按钮 |
| `mouse_wheel` | 在远程位置执行滚轮，单次增量限制在 -10～10 |
| `key_down` / `key_up` | 按下或释放按键，支持常用修饰键、功能键等 |
| `release_all` | 释放当前会话记录的按下状态，防止卡键或卡鼠标按钮 |

鼠标移动事件不会原样无限制地高频发送。浏览器会合并等待中的移动位置，大约每 **33 毫秒**发送一次最新位置；按键、按下和释放等操作则按事件处理。

当预览区域或浏览器窗口失去焦点，或者指针操作被取消时，页面会尝试发送 `release_all`，让远端释放已按下的键和鼠标按钮。关闭控制、结束会话时也会执行输入状态清理，降低按键停留在按下状态的风险。

键盘使用浏览器键名映射到远程可执行的按键，覆盖常用方向键、编辑键、修饰键、功能键和 ASCII 字符。对于部分中文输入法造成的 `Process`、`Unidentified` 或全角标点报告，前端会在必要时使用物理键码映射基础按键。这是键盘事件映射，不等于传输任意中文文本的专用输入法协议。

### 系统输入后端的能力边界

- **macOS**：Retina 截图尺寸可能与系统输入坐标不同，控制准备阶段会另外读取输入尺寸。屏幕录制与辅助功能权限会分别影响采集和操作。
- **Windows**：针对 DPI 缩放和多显示器虚拟桌面建立输入坐标空间；鼠标移动优先尝试 SendInput，使任务栏悬停等行为更接近系统鼠标事件，失败时再尝试常规移动方式。
- **Windows 安全与权限边界**：UAC 安全桌面、受限制的目标窗口或目标权限高于 Client 时，输入可能被拒绝。Client 会报告控制错误，Server 记录 `control_error` 并关闭该会话的控制能力，画面采集本身不必因此结束。

Control 开关关闭时，Server 会阻止后续正常输入消息，并通知 Client 清理已按下的输入状态。再次启用时会重新进行控制准备。需要排查时，应分别看预览是否持续更新、WebSocket 是否可用，以及页面是否出现具体 `control_error`，而不是只依据画面能否显示判断控制是否成功。

## 画面质量与会话配置

| 配置或界面设置 | 默认值 | 范围 / 可选值 | 生效方式 |
|---|---|---|---|
| `SCREEN_FRAME_STRATEGY` | `full_jpeg` | `full_jpeg`、`keyframe_delta` | 仅新建会话 |
| FPS | 15 | 1～30 | 当前会话可实时修改 |
| Quality | 60 | 20～95 | 当前会话可实时修改 |
| Control | 开启 | 开 / 关 | 当前会话即时切换，需 WebSocket 可用 |

**切换帧策略**需要在 Client 命令通道使用 `set`。例如，希望在屏幕内容变化较小时减少发送的数据，可以设置：

```text
set SCREEN_FRAME_STRATEGY keyframe_delta
```

此设置写入 Client 的运行时配置。当前已经运行的 Screen View 会话继续使用打开时的策略，关闭并重新打开后，新的会话才使用 Delta。需要恢复默认的整屏 JPEG 编码时执行：

```text
set SCREEN_FRAME_STRATEGY full_jpeg
```

可以在 Client 命令通道执行 `set` 查看配置列表，或使用 `set --json` 查看完整 JSON 配置数据，并在结果中找到 `SCREEN_FRAME_STRATEGY`。该值反映的是新会话将采用的策略，不能替代正在运行的会话实际策略，后者以 Screen View 窗口的策略标签和状态数据为准。

**调整帧率和质量**不需要重建会话。在窗口工具栏的 FPS 和 Quality 下拉菜单选择新值后，Server 更新会话参数并把新配置通知 Client，采集线程随后使用新的 FPS 和 JPEG 质量。

当前界面的 FPS 预设为 `1、2、4、6、10、15、20、24、30`；Quality 预设为 `30、45、60、75、90`。协议层接受范围内的其他整数，但界面只提供这些常用值。

FPS 是目标采集上限，而不是保证的实际显示帧率。如果截图与 JPEG 编码本身耗时较长，实际发送频率会低于设定值；浏览器的渲染速度、网络状况及 Server 最新帧缓存策略也会影响观感。Quality 较高通常意味着 JPEG 更大，需在画质与带宽之间选择。

## 浏览器显示与跨功能协作

在在线设备的工具栏打开 **Screen View** 后，窗口会显示连接对象、会话状态、帧策略、分辨率与每帧大小，并提供以下操作：

| 界面功能 | 用途与行为 |
|---|---|
| FPS / Quality | 在会话运行时修改采集帧率及 JPEG 压缩质量 |
| Control | 启用或关闭远程鼠标、键盘输入；需活动 WebSocket 和可用画面 |
| Clipboard | 点击直接进入 Get 标签；悬停菜单可选择 Get 或 Send，直接进入相应的 Clipboard 标签 |
| More → Screenshot | 将当前已经显示的画面保存为 Server Artifact |
| More → Restart | 关闭当前会话，再创建新会话；可使新编码策略生效 |
| More → Open in New Tab | 在独立浏览器标签页使用同一个 Screen View 控件全屏显示与控制；工具栏悬浮于画面上方，支持 Control、Clipboard Get/Send、FPS/Quality、Screenshot、Restart |
| Fullscreen | 将 Screen View 预览窗口展开为全屏布局 |
| 状态信息 | 显示会话打开、关闭、错误状态及画面参数 |

Open in New Tab 使用现有 Screen View 和 Clipboard 控件，并通过同一个 Server 创建会话。打开新标签页时，先结束原 Screen View 会话，再进入新标签页建立会话；从主页面重复打开同一 Client 时会提示已开启，而不会抢占新标签页。关闭新标签页时会请求 Server 释放会话。新标签页沿用原 Screen View 的设备名称展示（hostname 与短 machine_id），不显示完整 client_id。新标签页的控制工具栏不占用画面布局高度，默认隐藏；仅将鼠标移到画面顶部居中的细长触发条时浮现，离开工具栏后收起，打开下拉菜单期间保持可操作。画面保持原始宽高比，不拉伸或裁剪。

**Screenshot** 不会在点击时额外发送一次远程截图命令。浏览器直接读取已经渲染的完整图像或 Delta Canvas，按当前 Quality 重新编码为 JPEG，再上传到 `/api/files/upload`，保存为 `category=screenshot` 的 Artifact。这样保存的是当时页面已经看到的画面，而不是之后重新采集的另一帧。上传的附加信息包含 Client、会话、编码策略、尺寸和采集记录相关元数据。

**Clipboard** 只提供联动入口，不意味着每一帧或每次复制都会持续自动同步。文本、图像及文件/目录的剪贴板读写由独立 Clipboard 功能处理，需要用户显式发起对应操作。

**Restart** 会重新建立会话，重置客户端的帧编码状态与浏览器渲染状态；由于编码策略在打开时选定，所以修改 `SCREEN_FRAME_STRATEGY` 后可以用它使设置生效。这不是重启 Client 进程。

## 流式通道及会话回收

Screen View 的 HTTP 接口负责创建、配置、轮询和关闭会话；WebSocket 负责浏览器实时接收画面，以及向 Server 发送控制与输入事件。

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/connections/{client_id}/screen-view/open` | 创建会话，并要求 Client 启动采集 |
| `POST` | `/api/screen-view/{screen_session_id}/config` | 修改当前会话的 FPS / Quality |
| `GET` | `/api/screen-view/{screen_session_id}/poll?after_seq={seq}` | 获取状态和指定序列号之后的最新帧 |
| `POST` | `/api/screen-view/{screen_session_id}/close` | 请求关闭会话 |

打开会话时可以提供 `fps`、`quality`。正常响应的 `data` 中包含 `screen_session_id`、`status`、`fps`、`quality`、`frame_strategy`、`control_enabled`、`ws_token` 以及 `ws_path`。此时状态可能仍为 `opening`，`frame_strategy` 也可能尚未填充，需要等待 Client 的打开确认。

WebSocket 地址采用：

```text
/ws/screen/{screen_session_id}?token={ws_token}
```

其中 `ws_token` 由 Server 为会话单独生成，并在 WebSocket 建连时比对；它与 HTTP 请求所使用的 Web 管理鉴权不是一回事，不能仅凭会话 ID 省略令牌。HTTP 接口按 Web 管理端的鉴权规则访问。

浏览器通过 WebSocket 发送的主要消息：

| 类型 | 示例有效载荷 | 处理方式 |
|---|---|---|
| `config` | `{"type":"config","fps":15,"quality":60}` | 修改采集参数 |
| `control` | `{"type":"control","enabled":false}` | 开启或关闭输入控制 |
| `input` | `{"type":"input","event":{"action":"mouse_move","x":0.5,"y":0.5}}` | 转发一次远程输入事件 |
| `close` | `{"type":"close"}` | 请求关闭当前会话 |

Server 发送的消息以 `frames` 和 `status` 为主。`frames` 包含状态、最新序列号、`frames` 数组、尺寸、字节数、策略和 Control 状态；`status` 用于结束或错误等状态变化。`poll` 返回的字段内容相近，但由 HTTP 请求按 `after_seq` 拉取。普通 HTTP 配置接口目前仅处理 FPS 和 Quality，不作为鼠标键盘事件入口。

会话状态及其含义：

| 状态 | 含义 |
|---|---|
| `opening` | Server 已分配会话并通知 Client，尚在等待打开结果 |
| `open` | Client 确认启动，画面可以持续接收 |
| `closing` | 已提出关闭请求，等待 Client 结束 |
| `closed` | Client 已关闭，或 Client 连接断开后被结束 |
| `error` | 打开或截图过程出现错误，无法继续正常采集 |

关闭窗口时，浏览器会尝试关闭远程会话。WebSocket 断开也会触发 Server 的关闭处理；Client 断线时，Server 会将该 Client 尚未结束的屏幕会话标为 `closed`，并停止允许远程输入。Server 通过生命周期事件发布启动、关闭和错误通知，供 SSE/通知中心使用。

结束及错误会话的状态会在 Server 内存中保留一段时间。**超过 300 秒的旧记录是在创建新会话时顺带清理**，不是独立计时器每隔 300 秒执行清理；因此某些旧记录可能存留更久。

## 权限、延迟与可用性边界

Screen View 侧重实时预览，不是远程录像系统。Server 只保存最新画面以及 Delta 所需的 Keyframe，不提供完整历史帧顺序重放；显示端可能直接跳过网络拥塞期间的中间帧。这种设计避免了实时屏幕长时间运行时无意义的数据积压。

常见现象及判断方式：

| 现象 | 优先检查 | 说明 |
|---|---|---|
| 打开后长时间显示等待首帧 | 远程桌面会话、截图权限、Client 是否仍在线 | `opening` 或已连接并不保证截图已经成功 |
| 出现 Screen preview unavailable | 页面错误信息、设备当前桌面状态 | Pillow/PyAutoGUI 都失败时会话会报告采集错误 |
| 有画面但 Control 无法打开 | WebSocket 状态、首帧是否显示、系统辅助功能/输入权限 | HTTP 轮询可以显示画面，但不能代替实时输入通道 |
| Windows 某些界面无法操作 | UAC、安全桌面、目标进程权限 | 输入限制可以独立于屏幕采集发生 |
| 鼠标位置偏移 | DPI 缩放、多显示器布局、是否为虚拟桌面 | 截图像素与 OS 输入坐标空间不一定相同 |
| FPS 达不到设置值 | 截图/编码耗时、网络、浏览器负载 | 设定值是目标频率，非实际帧率保证 |
| Delta 图像重建异常 | Keyframe 与 `base_seq` 是否一致 | 差分依赖有效基准，Server 会丢弃不匹配的 Delta |
| 切换帧策略后仍显示旧策略 | 会话是否已重新建立 | `SCREEN_FRAME_STRATEGY` 只对新会话生效 |
| Screenshot 保存失败 | 当前画面是否已渲染、Artifact 上传是否正常 | Screenshot 保存的是浏览器当前画面并走文件上传 |

定位问题时，先区分**采集失败、画面传输失败、浏览器渲染失败、远程输入失败**四条链路。它们可以出现不同的结果：例如 WebSocket 不可用时还能通过 HTTP 看到最新画面；采集正常而 OS 拒绝输入时，Control 会被关闭但画面仍可继续显示。

此外，以下能力边界应作为日常使用预期：

- 默认帧策略为 `full_jpeg`；差分策略需显式配置。
- 画面来自 Client 所在的实际图形桌面，未登录、锁定、无显示会话或缺少屏幕录制权限时，采集可能受限。
- 屏幕数据经现有 Client 连接转发，不建立不依赖 Client 主连接的独立远程桌面隧道。
- HTTP 轮询仅是画面与状态的回退，不提供现有 WebSocket 输入控制能力。
- Screen View 的输入动作包含按键事件和鼠标事件，并非针对任意文本内容的独立输入法同步；复制内容应使用 Clipboard。
- 同一 Client 同时只允许一个活动 Screen View 会话；重复打开会被拒绝，不支持同一设备的并发预览。
