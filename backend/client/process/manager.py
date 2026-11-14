"""One-shot process control using the existing process service."""
from client.runtime.execution.process.process_service import ProcessService
from core.protocol.control import ProcessAction
from core.protocol.result_envelope import ResultEnvelope


class ProcessManager:
    def __init__(self):
        self.service = ProcessService(None)

    def execute(self, scope, action, payload):
        if action != ProcessAction.KILL:
            return 0, 'Unsupported process Control action'
        pid = payload.get('pid')
        if type(pid) is not int or pid <= 0:
            return 0, 'PID must be a positive integer'
        try:
            self.service.kill_process(pid)
            return 1, ResultEnvelope(message=f'Process {pid} terminated').as_payload()
        except Exception as exc:
            return 0, str(exc)
