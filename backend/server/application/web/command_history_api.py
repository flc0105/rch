class WebCommandHistoryApi:
    """
    Web 命令历史子外观。

    职责：
    - 提供 command history / execution history 读写能力
    - 提供 pinned history 调整能力
    """

    def __init__(self, server):
        self.server = server

    def get_command_history(self, machine_id: str):
        return self.server.command_history.view_service.get_history_by_machine_id(machine_id)

    def get_command_execution_history(self, machine_id: str, *, limit=None, cursor: str = '', query: str = '', kind: str = '', errors: bool = False):
        return self.server.command_history.view_service.get_execution_history_page(
            machine_id,
            limit=limit,
            cursor=cursor,
            query=query,
            kind=kind,
            errors=errors,
        )

    def clear_command_history(self, machine_id: str):
        self.server.command_history.write_service.clear_history_by_machine_id(machine_id)
        return None

    def set_command_history_pinned(self, machine_id: str, command: str, is_pinned: bool):
        changed = self.server.command_history.write_service.set_command_pinned_by_machine_id(
            machine_id,
            command,
            is_pinned,
        )
        return {
            'machine_id': (machine_id or '').strip(),
            'command': (command or '').strip(),
            'is_pinned': bool(is_pinned),
            'changed': bool(changed),
        }

    def move_command_history_pinned(self, machine_id: str, command: str, direction: str):
        changed = self.server.command_history.write_service.move_pinned_command_by_machine_id(
            machine_id,
            command,
            direction,
        )
        return {
            'machine_id': (machine_id or '').strip(),
            'command': (command or '').strip(),
            'direction': (direction or '').strip().lower(),
            'changed': bool(changed),
        }

    def delete_command_execution_history_entry(self, machine_id: str, entry_id: str):
        deleted = self.server.command_history.write_service.delete_execution_entry_by_machine_id(machine_id, entry_id)
        return {
            'machine_id': (machine_id or '').strip(),
            'entry_id': (entry_id or '').strip(),
            'deleted': bool(deleted),
        }