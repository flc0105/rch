# Device Identity & Inventory

RCH 同时需要识别**一台设备**和**设备上运行的一条 Client 连接**。这两个层次不能使用同一个 ID：前者负责最近设备、名称、分组和跨连接历史；后者负责当前 Socket 会话、命令投递和连接级控制。Python Client 使用本地机器特征计算 `machine_id`，并在创建 Client 实例时独立生成 `client_id`；Server 在握手后分别维护这两种身份。这里的“同一台设备”是按指纹算法得出的**逻辑机器身份**，不等于经过硬件认证的不可变物理设备。

## 1. 设备身份和运行实例

| 标识 | 生成者与构成 | 生命周期 | 实际用途 |
| --- | --- | --- | --- |
| `machine_id` | Python Client 采集七项机器特征，规范化后对固定字符串计算 SHA-256 | 特征不变时可跨进程重启复现 | 最近设备缓存、设备别名、分组成员、历史查询等 |
| `client_id` | Python Client 初始化对象时调用 `uuid.uuid4()` | 同一个 Client 对象断线重连时不变，重新创建对象时通常改变 | 活动 Socket 会话、发送命令、取消或关闭指定连接 |
| `machine_id_short` | `machine_id[:24]` | 随 `machine_id` 变化 | 本地身份载荷中的短显示值；不是另一种身份 |
| `group_id` | Server 创建设备分组时生成 UUID 十六进制值 | 分组存在期间稳定 | 标识用户自定义的设备分组，不代表设备 |

一台机器运行两个 Python Client 进程时，只要它们探测到的机器特征相同，两个进程就具有同一个 `machine_id`，但有不同 `client_id`。Server 因此可以同时保留两条可独立操作的在线连接，并在设备库存中以同一个机器键记录最近设备信息。

`client_id` 不是 TCP 四元组、进程 PID 或主机名；`machine_id` 也不是 Session ID。即使同一 Client 因网络中断重新建立 Socket，它仍可能使用原 `client_id`，但 Socket 本身和连接时间已经更新。详细的心跳与在线状态流转见 [Connection Lifecycle](./connection_lifecycle.md)。

## 2. 机器指纹的完整构造过程

Python 侧的权威计算入口是 `core.device.machine_identity.build_machine_identity_payload()`；实际运行中的 Client 通常通过 `core.device.local_identity.get_local_identity()` 获取其结果。算法不是随机生成机器 UUID，也不直接把操作系统原生 ID 作为 `machine_id`。它先采集以下七项输入，再统一进行规范化。

| 指纹字段 | 采集含义与通用来源 |
| --- | --- |
| `hostname` | `platform.node()` 返回的设备主机名 |
| `os_name` | 平台显示名称；Linux 读取发行版 NAME/ID |
| `os_version` | 系统/发行版版本；Linux 优先 `VERSION_ID`、再 `VERSION`，最后系统内核版本信息 |
| `arch` | `platform.machine()`；iOS 使用 ARM64 系统能力检测 |
| `manufacturer` | 系统报告的制造商 |
| `model` | 系统报告的设备型号 |
| `native_id` | 操作系统提供的机器/设备原生标识 |

### 平台探测

| 系统 | 制造商 / 型号 | `native_id` 来源 |
| --- | --- | --- |
| Windows | `wmic computersystem get manufacturer,model /value` | 注册表 `HKLM\SOFTWARE\Microsoft\Cryptography` 中的 `MachineGuid` |
| macOS | 制造商为 `Apple`，型号来自 `sysctl -n hw.model` | `ioreg` 查询 `IOPlatformExpertDevice` 的 `IOPlatformUUID` |
| Linux | DMI 的 `sys_vendor` 与 `product_name` | `/etc/machine-id`，不存在时读取 `/var/lib/dbus/machine-id` |
| iOS | `Apple` 与设备 API / `platform.machine()` | `UIDevice.identifierForVendor().UUIDString()` |

Linux 发行版名称/版本取自 `/etc/os-release`，其次尝试 `/usr/lib/os-release`；macOS 版本取自 `platform.mac_ver()`；Windows 版本使用 Python 平台信息的版本字段；iOS 版本由 `UIDevice.systemVersion()` 提供。查询失败时不会抛出必须停止启动的指纹异常：采集函数通常返回空字符串，规范化阶段用 `na` 表示缺失值。这里的 iOS `identifierForVendor` 具有厂商作用域，不能当作永久且不变的硬件序列号。

### 规范化、拼接与散列

除 `os_version` 以外，字段会先转换为字符串、去掉首尾空白、转小写，然后把连续空白替换为 `_`；不属于 `a-z`、`0-9`、`.`、`_`、`:`、`-` 的字符也替换成 `_`；连续下划线合并并去掉两端下划线。结果为空时为 `na`。`os_version` 额外优先提取第一段带点号的数字版本（例如 `15.7.1`），其次提取一个数字，再使用普通字段规则。

规范化后的值按**固定字段名、固定顺序、固定分隔符**拼成一条字符串：

```text
v1|hostname=<hostname>|os_name=<os_name>|os_version=<os_version>|arch=<arch>|manufacturer=<manufacturer>|model=<model>|native_id=<native_id>
```

这里的 `v1` 是实际参与哈希的格式前缀 `MACHINE_ID_VERSION`，**不是随机盐**。机器身份为：

```python
machine_id = hashlib.sha256(fingerprint_basis.encode('utf-8')).hexdigest()
machine_id_short = machine_id[:24]
```

例如，以下是**合成数据**，不对应任何真实设备：

```python
from core.device.machine_identity import build_machine_identity_payload

payload = build_machine_identity_payload({
    'hostname': 'test-host',
    'os_name': 'macOS',
    'os_version': '15.7.1',
    'arch': 'x86_64',
    'manufacturer': 'Apple',
    'model': 'MacBookPro18,1',
    'native_id': 'ABC-123',
})
print(payload['fingerprint_basis'])
print(payload['machine_id_hash'])
```

实际生成的规范化输入为：

```text
v1|hostname=test-host|os_name=macos|os_version=15.7.1|arch=x86_64|manufacturer=apple|model=macbookpro18_1|native_id=abc-123
```

对应的 SHA-256 十六进制字符串：

```text
ce728284ec284dcab7704f5ba3d44c83ceab1606e7f2c2d531d52583cf5f6aee
```

`build_machine_identity_payload()` 返回 `machine_id_version`、`machine_id_hash`、`machine_id_short`、`fingerprint_basis`、`raw_components`、`normalized_components`，便于比较采集值与最终身份。注意：这是**本地函数返回的诊断载荷**；实际 Python Client 握手只选择了其中的 `machine_id` 和 `machine_fingerprint_basis`，并非把该字典原样发给 Server。

### 一次探测、一份进程内身份

`get_local_identity()` 使用进程级缓存和锁保存不可变的 `LocalIdentity` 对象。第一次需要身份时会执行平台探测，包括可能调用注册表、`wmic`、`sysctl`、`ioreg`、DMI 或读取系统文件；同一进程后续读取默认重用同一份结果。`get_local_identity(refresh=True)` 会强制重新采集，`clear_local_identity_cache()` 可清空缓存。

因此，运行期间修改主机名或系统环境，并不保证已运行的 Client 立刻改变其握手身份。重新创建进程或显式刷新身份后，才会基于新特征生成不同结果。运行时的 `LocalIdentity.arch` 会经平台架构别名归一化；**指纹本身仍使用探测到的原始 `arch` 值进行指纹规范化**，不能拿展示用架构名重新计算散列。

## 3. 从握手到活动连接

Python Client 在创建 Client 对象时生成 `client_id`，组装握手时通过 `ClientInfoBuilder` 读取本地 `LocalIdentity`。以下是与身份相关的**精简消息示意**：

```json
{
  "type": "info",
  "id": "9fd3524d-27dd-4b25-9207-a499c01b83ec",
  "hostname": "test-host",
  "machine_id": "ce728284ec284dcab7704f5ba3d44c83ceab1606e7f2c2d531d52583cf5f6aee",
  "machine_fingerprint_basis": "v1|hostname=test-host|os_name=macos|os_version=15.7.1|arch=x86_64|manufacturer=apple|model=macbookpro18_1|native_id=abc-123"
}
```

实际握手还携带平台、权限、进程、工作目录、Build Version、源码 Revision、Command Manifest、Variable Manifest 等信息；以上仅保留身份字段，不代表完整协议结构。Server 将消息字段中的 `id` 映射到 `SessionInfo.client_id`，并读取 `machine_id` 与 `machine_fingerprint_basis`。

Server 的 `ConnectionManager` 使用 `client_id -> ClientSession` 的活动映射；如果握手没有 `client_id`，会进入单独的匿名连接集合。服务端指令需要操作特定在线连接时，按 `client_id` 取当前会话，而不是通过 `machine_id` 猜测目标进程。同机多个 Client 应保持独立执行与关闭能力。

Python Client 自动重连时复用 Client 对象，因此沿用其 `client_id`。退出进程、重新创建 Client 对象则调用新的 UUID v4。**随机重建的是 Client 实例身份，而不是机器指纹。**

## 4. 活动会话、最近设备与历史记录

Server 有三类不同的数据，不能互相代替。

| 数据层 | 主要键 | 保留内容及用途 |
| --- | --- | --- |
| 活动连接 `ConnectionManager` | `client_id` | 当前 Socket 会话；发命令、查看实时状态、停止连接 |
| Recent Devices | 规范化后的 `machine_id`（`machine_key`） | 最近连接快照、上次 Client ID、别名、隐藏设置、排序和最近状态 |
| Connection Sessions | `(machine_id, client_id)` | 每次 Client 实例关联的连接时间、结束时间、时长、最近活动及历史状态 |

Server 收到连接注册时，先记录最近设备并登记连接历史，然后发布 `connection_online`；处理心跳 ACK 时刷新最近设备和历史会话；连接关闭时登记 Offline、记录历史并发送离线事件。Web `/api/connections` 查询会取活动 `ClientSession`，更新对应最近设备，再追加**当前没有任何活动连接的机器**的离线缓存项。

这一行为有两个容易误读的结果：

- 多个活动 `client_id` 可以指向相同 `machine_id`，实时列表仍可显示多条连接；Recent Devices 本身则每台逻辑机器只保留一份最近快照。
- 已离线的设备可能仍留在 Web 列表。这是 Server 持久化设备库存的行为，不表示仍存在 Socket；其 `connection_state` 是 `offline`。

最近设备和历史记录都存储在 Server 的 SQLite 数据库中，默认数据库路径由 `RCH_DB_PATH` 指向启动工作目录下的 `runtime/rch.db`。Recent Devices 对应 `recent_devices` 表，连接历史对应 `connection_sessions` 表；Server 的用户自定义分组另存在 `device_groups` 与 `device_group_members` 表中。不要将数据库路径理解为 Client 机器上的 `runtime/`。

连接历史按机器归集，再区分每个 Client ID。记录中的 `online`、`offline`、`interrupted` 描述历史会话结局；实时界面的 `stale` 则由当前连接的新鲜度判定，不是历史的第四种状态。查看一台机器的连接历史时，Server 还会将关联命令计数汇入各次会话。详见 `command_history.md` 和 [Connection Lifecycle](./connection_lifecycle.md)。

## 5. 设备库存的用户管理能力

### 名称、隐藏与顺序

设备别名 `machine_alias`、整机隐藏 `device_hidden_by_machine`、设备排序 `machine_order` 都归属机器身份；`hidden_client_ids` 则在该机器记录中保存按 `client_id` 隐藏的连接集合。前端最终显示的 `device_hidden` 是整机隐藏与对应 Client 隐藏的合并结果。

因此，**隐藏某个 Client** 只影响那个 Client ID，Client 进程重新创建后得到新的 ID，不会天然继承该连接级隐藏状态；**隐藏整台机器** 则跟着同一个 `machine_id` 保留。清空机器别名会恢复使用其他展示信息，而不是改变机器指纹。

前端设备侧边栏按客户端条目选择连接，`selectedId` 实际保存 `client_id`，并通过 `sessionStorage` 记住最后选中的 `machine_id` 和 `client_id`。刷新后尝试优先恢复对应 Client；它不存在时再按机器 ID 选取可见连接。过滤、设备组及隐藏规则仍会影响最终候选。此项浏览器选中状态不是 Server 的设备主身份数据库。

### 分组与成员

分组有自己的 `group_id` 与名称，创建、重命名、删除和分配均由 Server 的 `DeviceGroupStore` 持久化。名称不能为空、最长 80 个字符，忽略大小写后不得重复。分组成员的主键是规范化后的 `machine_id`，不是 `client_id`；一个机器当前最多有一个分组分配。删除分组会清除这些成员关系，但不会删除机器自身的最近设备记录或活动连接。

设备分组的聚合计数也按机器身份去重，同一台机器上的多个活动 Client 不应使该组的“机器数量”简单翻倍。没有 `machine_id` 的连接仍可出现在当前连接视图，但不具有按机器分组的同等能力。

### 忘记设备与关闭连接

下面三个动作不同：

| 用户操作 | 实现边界 |
| --- | --- |
| 隐藏连接或机器 | 修改设备视图偏好；不主动关闭 Socket |
| Kill Connection | 向指定 `client_id` 的在线会话发起关闭控制；不是删除设备历史 |
| Remove Connection / Forget | 按指定 Client/Machine 身份移除 Recent Devices 记录；如果目标仍在线，还会尝试结束会话并发布移除事件 |

“忘记”不是全库级级联删除。当前 `remove_connection()` 删除的是匹配的最近设备缓存，**没有在同一操作中删除 `device_group_members`、`connection_sessions` 或执行历史**。为了避免已经发出的离线更新立刻重新插回刚删除的缓存，Recent Device Store 还维护进程内的 `_forgotten_machine_keys` 集合；同一机器之后再次出现非离线连接更新时，会解除该临时屏蔽并重新记录。

如果要真正清除所有与某机器身份有关的历史信息，不能把界面上的 Remove 当成完整数据清除流程。

## 6. API、管理入口与数据关联

通过已认证的 Web API 可以读取连接列表、历史与分组，更新设备视图偏好。常用路径及作用如下：

| 请求 | 行为 |
| --- | --- |
| `GET /api/connections` | 活动连接与最近离线设备合并列表 |
| `PATCH /api/connections/device-view-prefs` | 更新机器别名、整机隐藏或指定 Client 隐藏 |
| `GET /api/device-groups` | 查询分组及 Machine ID → Group ID 关系 |
| `POST /api/device-groups` | 创建分组（Body 含 `name`） |
| `PATCH /api/device-groups/{group_id}` | 重命名分组 |
| `DELETE /api/device-groups/{group_id}` | 删除分组及成员关系 |
| `PATCH /api/machines/{machine_id}/device-group` | 设置 / 清除机器的分组归属（Body 含 `group_id`） |
| `GET /api/machines/{machine_id}/connection-history` | 查询某台机器的历史 Client 会话及统计 |
| `GET /api/machines/{machine_id}/connection-history/{client_id}/commands` | 分页查询某次 Client 身份关联的命令 |
| `POST /api/connections/{client_id}/kill` | 结束指定连接 |
| `DELETE /api/connections/{client_id}` | 移除指定连接/最近设备，可在请求 Body 提供 `machine_id` |

例如，为某台设备设置别名与整机隐藏：

```http
PATCH /api/connections/device-view-prefs
Content-Type: application/json

{
  "machine_id": "<实际 machine_id>",
  "machine_alias": "Office Mac",
  "machine_hidden": false
}
```

要仅隐藏当前运行实例，可提供 `client_id` 与 `client_hidden`。实际调用应按部署的 Session 或管理员 Bearer Token 认证要求发送凭据，不能把 Machine ID 当作 API Token。API 请求中 `{machine_id}` / `{client_id}` 是路径参数，占位符并非真实身份。

按机器分组的数据不仅服务设备侧边栏：一些功能（如按机器的命令历史、固定路径、特定参数和共享资源选择）也依赖机器身份。开发者扩展这种持久化数据时，应明确键是设备维度还是连接维度，避免把临时 `client_id` 写成长期归属键。RCH 命令变量 `${rch:machine_id}` 读取的也是当前 Python Client 的本地身份，相关变量解析见 `variables.md`。

## 7. 身份稳定性、安全性与排查

**确定性不等于永久不变。** 七个规范化字段任意一个发生有效变化，都可能导致不同 SHA-256；即使原生 `native_id` 不变，修改主机名或升级系统版本也可能得到新 `machine_id`。相反，克隆系统镜像如果保留相同系统 ID、主机名和其余特征，也可能计算出同一机器身份。重新构建 Client Bundle 本身不参与 Fingerprint，但更换运行系统环境可能影响其结果。

这直接影响 Server 设备库存：新 `machine_id` 会作为新的机器键写入最近设备；原别名、隐藏、排序、分组和历史引用仍绑定旧 Machine ID。当前代码没有靠主机名或相似硬件信息自动把两个不同哈希合并的迁移逻辑；即使它们确实来自同一物理设备，也不能假定用户偏好会自动转移。

**指纹不是认证。** SHA-256 在这里用于确定性标识，不是签名、私钥或者硬件可信证明。握手中的 `machine_id` 与 `machine_fingerprint_basis` 是 Client 自报字段，不能证明其未被伪造；更不能据此绕开 Session / Bearer / Script Grant 等认证体系。原始 `native_id` 虽未单独出现在正常 Web 连接载荷，但 `machine_fingerprint_basis` 可能包含它；Server 序列化该字段并将其保存到最近设备快照，因此日志、诊断导出与 API 数据应控制访问范围。不要随意公开完整 Basis。

遇到设备重复、丢失分组或历史不连续，应依次确认：

1. 对照两次连接的 `machine_id`，判断它们究竟是否被认为是同一机器；不能只比较 `hostname`。
2. 若 Machine ID 改变，比较 `machine_fingerprint_basis` 中的七项字段，重点检查主机名、OS 版本、架构、原生系统 ID 和空值 `na`。比较 Basis 时应避免将其泄露到公开渠道。
3. 检查 Client 是否重新创建：如果只变了 `client_id`，属于新的运行实例，不意味着机器身份变化；如果两者都变，先排查 Fingerprint 输入变化。
4. 确认 Server 当前使用的 SQLite 数据库和实际启动工作目录；设备偏好、分组和历史不是由新 Client 进程自动带回的。
5. 若一台机器仍有活动连接，区分 Server 活动 Session、Recent Device 最近快照和浏览器的选中项；它们可指向不同 Client ID。

当需要修改身份算法时，应同时评估本地 `LocalIdentity`、握手字段、Server 的 Machine 键、分组成员、最近设备和历史数据之间的关联后果。仅改变哈希输入或前缀会产生一批新的逻辑机器身份，并不会自动给历史记录换键。
