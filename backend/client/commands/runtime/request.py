from dataclasses import dataclass


@dataclass
class CommandExecutionRequest:
    """
    统一命令执行请求。

    说明：
    - 这里只承载 CommandExecutor 主链分发所需的最小字段
    - 不引入额外兼容入口，统一 command / acmd / script 三类请求的绑定流程
    """

    command_id: int
    timeout: float | None = None
