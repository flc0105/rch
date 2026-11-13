from core.protocol.control import validate_control_fields


class ClientControlDispatcher:
    """Dispatch registered domains without loading a command catalog."""

    def __init__(self, execution, handlers):
        self.execution = execution
        self.handlers = dict(handlers)

    def execute(self, request_id, domain, action, payload, options=None):
        validate_control_fields(domain, action, payload)
        handler = self.handlers.get(domain)
        if handler is None:
            return 0, f'Unsupported Control domain: {domain}'
        return self.execution.run(request_id, lambda scope: handler(scope, action, payload), options)
