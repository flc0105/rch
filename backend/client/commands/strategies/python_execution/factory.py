from client.commands.strategies.python_execution.inproc import InProcessPythonExecutionStrategy
from client.commands.strategies.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy

from client.config import runtime_config


def normalize_python_execution_mode(mode: str = '', default_mode: str = 'inproc') -> str:
    normalized = str(mode or '').strip().lower()
    if normalized in ('inproc', 'subprocess_pipe'):
        return normalized

    fallback = str(default_mode or '').strip().lower()
    if fallback in ('inproc', 'subprocess_pipe'):
        return fallback

    return 'inproc'


def get_python_execution_mode() -> str:
    return normalize_python_execution_mode(runtime_config.PYTHON_EXECUTION_MODE)


def build_python_execution_strategy(owner, mode: str = '', default_mode: str = 'inproc'):
    normalized = normalize_python_execution_mode(mode, default_mode=default_mode)
    if normalized == 'subprocess_pipe':
        return SubprocessPipePythonExecutionStrategy(owner)
    return InProcessPythonExecutionStrategy(owner)





