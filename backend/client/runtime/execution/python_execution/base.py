class PythonExecutionStrategy:
    """
    Python 执行策略基类。

    设计目标：
    - 像 HTTP 传输策略一样，后续可由配置切换执行方式
    - 区分：
      - inproc：当前解释器 exec（兼容原行为，不可强制终止）
      - subprocess_pipe：子进程 + stdin 管道（支持强制取消，不落地文件）
    """

    MODE_NAME = 'base'

    def __init__(self, owner):
        self.owner = owner

    def get_mode_name(self) -> str:
        return self.MODE_NAME

    def is_cancel_supported(self) -> bool:
        return False

    def configure_context(self):
        self.owner._set_cancel_policy(
            mode='process' if self.is_cancel_supported() else 'none',
            message='Current Python execution mode does not support cancellation',
        )

    def execute_collect(self, code, kwargs=None, timeout=None):
        raise NotImplementedError

    def execute_stream(self, code, kwargs=None, timeout=None):
        raise NotImplementedError





