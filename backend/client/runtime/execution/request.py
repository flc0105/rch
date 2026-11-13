from dataclasses import dataclass


@dataclass
class ExecutionRequest:
    """
    统一前台执行请求。

    说明：
    - 仅保存执行 ID 与可选超时。
    """

    command_id: int
    timeout: float | None = None
