class WebCommandCatalogApi:
    """
    Web 命令候选子外观。

    职责：
    - 聚合客户端命令清单
    - 聚合服务端命令候选
    - 输出去重后的 command candidates
    - 对外暴露 CommandCompletionProvider 补全入口
    """

    def __init__(self, server, command_executor_factory, command_completion_service=None):
        self.server = server
        self.command_executor_factory = command_executor_factory
        self.command_completion_service = command_completion_service

    def _get_client_command_candidates(self, session):
        payload = session.session_info.command_manifest or []
        if not isinstance(payload, list):
            return []

        result = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            name = (item.get('name') or '').strip()
            if not name:
                continue

            result.append({
                'name': name,
                'help': item.get('help', ''),
                'group': item.get('group', 'general'),
                'suggest': item.get('suggest', True),
                'source': item.get('source', 'client'),
                'kind': item.get('kind', 'command'),
                'cancel_policy': item.get('cancel_policy', 'none'),
                'timeout': item.get('timeout'),
                **({'confirmation': True} if item.get('confirmation') else {}),
                'interaction': item.get('interaction') or {'may_request': False},
                'output': item.get('output', 'collect'),
            })

        return result

    def get_command_candidates(self, client_id: str):
        session = self.server.get_target_connection_by_client_id(client_id)
        client_candidates = self._get_client_command_candidates(session)
        server_candidates = self.command_executor_factory.create(session).get_command_candidates()
        # Top-level Server Builtins own these names; do not present shadowed
        # Client manifest entries as independently reachable terminal commands.
        registered_server_names = {str(item.get('name') or '').strip().split(' ', 1)[0].lower() for item in server_candidates
                                   if item.get('source') == 'server'}
        client_candidates = [item for item in client_candidates
                             if str(item.get('name') or '').lower() not in registered_server_names]

        merged = []
        seen = set()
        for item in client_candidates + server_candidates:
            name = (item.get('name') or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(item)

        merged.sort(key=lambda item: (item.get('source', ''), item.get('name', '').lower()))
        return merged

    def get_command_completions(self, client_id: str, raw_input: str = '', cursor_position=None, max_results: int = 50):
        if self.command_completion_service is None:
            return {
                'context': {},
                'items': [],
            }

        return self.command_completion_service.complete(
            client_id=client_id,
            raw_input=raw_input,
            cursor_position=cursor_position,
            max_results=max_results,
        )
