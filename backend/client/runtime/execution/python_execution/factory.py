from client.runtime.execution.python_execution.inproc import InProcessPythonExecutionStrategy
from client.runtime.execution.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy

from client.config import runtime_config


def normalize_python_execution_mode(mode: str = '', default_mode: str = 'inproc') -> str:
    from core.protocol.script_execution import ExecutionMode
    return ExecutionMode(mode or default_mode).value


def get_python_execution_mode() -> str:
    return normalize_python_execution_mode(runtime_config.SCRIPT_DEFAULT_EXECUTION_MODE)


def build_python_execution_strategy(owner, mode: str = '', default_mode: str = 'inproc'):
    normalized = normalize_python_execution_mode(mode, default_mode=default_mode)
    if normalized == 'subprocess_pipe':
        return SubprocessPipePythonExecutionStrategy(owner)
    return InProcessPythonExecutionStrategy(owner)





