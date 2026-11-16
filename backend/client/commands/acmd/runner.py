from client.runtime.command_variable_resolver import CommandVariableResolutionError
from client.runtime.execution.request import ExecutionRequest


class ArgumentCommandRunner:
    """Execute structured ACMD arguments using the Client's runtime context."""

    def __init__(self, executor):
        self.executor = executor

    def execute(self, request: ExecutionRequest, payload: dict):
        if not isinstance(payload, dict) or not isinstance(payload.get('args', {}), dict):
            return 0, 'Invalid acmd payload'

        resolver = self.executor.command_variable_resolver

        def expand(value):
            if isinstance(value, str):
                return resolver.resolve(value, command_id=request.command_id)
            if isinstance(value, list):
                return [expand(part) for part in value]
            return value

        try:
            resolved_payload = {
                **payload,
                'args': {key: expand(value) for key, value in (payload.get('args') or {}).items()},
            }
        except CommandVariableResolutionError as exc:
            return 0, f'Failed to resolve command variable: {exc}'

        def _invoke(_commands):
            registry = self.executor.get_argument_command_registry()
            return registry.execute(resolved_payload)

        return self.executor.execute_bound_request(request, _invoke)
