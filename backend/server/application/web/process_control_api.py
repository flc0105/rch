from core.protocol.control import ControlDomain, ProcessAction


class WebProcessControlApi:
    """
    Web 进程控制子外观。

    职责：
    - 提供 process/app 终止操作

    说明：
    - process/apps/detail 的实时读取已经统一迁移到 Device Monitor channels
    - 这里不再提供 foreground snapshot/list/detail 查询
    """

    def __init__(self, server, remote_execution_service):
        self.server = server
        self.remote_execution_service = remote_execution_service

    def _terminate_process(self, client_id: str, pid: int):
        completion = self.remote_execution_service.run_foreground_control(
            client_id, ControlDomain.PROCESS, ProcessAction.KILL, {'pid': int(pid)},
            task_type='process', source='web_process',
        )
        if not completion.succeeded:
            raise RuntimeError(completion.event.get('message') or 'Remote process operation failed')
        return completion.event.get('message', '')

    def kill_process(self, client_id: str, pid: int, name: str = ''):
        return self._terminate_process(client_id, pid)

    def kill_app(self, client_id: str, pid: int, name: str = ''):
        return self._terminate_process(client_id, pid)
