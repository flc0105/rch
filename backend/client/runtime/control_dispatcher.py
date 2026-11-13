from core.protocol.control import validate_control_fields


class ClientControlDispatcher:
    """Dispatch registered domains without loading a command catalog."""

    def __init__(self, execution, handlers, cancel_policies=None):
        self.execution = execution
        self.handlers = dict(handlers)
        self.cancel_policies = dict(cancel_policies or {})

    def prepare(self, request_id, domain, action, payload):
        if not isinstance(request_id, int) or not isinstance(domain, str):
            return
        try:
            validate_control_fields(domain, action, payload)
        except ValueError:
            return
        policy = self.cancel_policies.get(domain)
        if policy is not None:
            mode = policy(action, payload)
            if mode is not None:
                context = self.execution.context_store.get_or_create(request_id)
                context.set_cancel_policy(mode, message='Current execution mode does not support cancellation')

    def execute(self, request_id, domain, action, payload, options=None):
        validate_control_fields(domain, action, payload)
        handler = self.handlers.get(domain)
        if handler is None:
            return 0, f'Unsupported Control domain: {domain}'
        return self.execution.run(request_id, lambda scope: handler(scope, action, payload), options)
