import shlex
import uuid


class WebQuickActionApi:
    """Alias-backed Quick Actions Web facade."""

    def __init__(self, server, alias_manager, command_execution_api):
        self.server = server
        self.alias_manager = alias_manager
        self.command_execution_api = command_execution_api

    def _get_session(self, client_id: str):
        normalized_client_id = str(client_id or '').strip()
        if not normalized_client_id:
            raise ValueError('client_id is required')
        return self.server.get_target_connection_by_client_id(normalized_client_id)

    def _normalize_alias_name(self, alias: str) -> str:
        alias_name = str(alias or '').strip()
        if not alias_name:
            raise ValueError('alias is required')
        if any(char.isspace() for char in alias_name):
            raise ValueError('alias name cannot contain whitespace')
        return alias_name

    def _normalize_command(self, command: str) -> str:
        command_text = str(command or '').strip()
        if not command_text:
            raise ValueError('command is required')
        return command_text

    def _build_item(self, platform: str, alias: str, command: str, current_platform: str, current_aliases: dict):
        overridden = (
            platform == 'common'
            and current_platform not in {'', 'common'}
            and alias in current_aliases
        )
        effective = (
            platform == current_platform
            or (platform == 'common' and not overridden)
            or (current_platform in {'', 'common'} and platform == 'common')
        )
        return {
            'platform': platform,
            'alias': alias,
            'command': command,
            'parameters': self.alias_manager.extract_parameters(command),
            'in_current_scope': platform == 'common' or platform == current_platform,
            'overridden': overridden,
            'effective': effective,
        }

    def list_quick_actions(self, client_id: str) -> dict:
        session = self._get_session(client_id)

        # aliases.json 可能被 CLI 之外的方式直接编辑。每次列表请求都重新从磁盘
        # 加载一次，确保 Quick Actions 打开/刷新列表时展示本地最新定义。
        self.alias_manager.load_aliases()

        current_platform = self.alias_manager.get_platform_for_connection(session) or 'common'
        grouped = self.alias_manager.list_aliases_grouped()
        current_aliases = grouped.get(current_platform) or {}
        items = []

        for platform in self.alias_manager.get_supported_platforms():
            alias_map = grouped.get(platform) or {}
            for alias_name in sorted(alias_map.keys()):
                items.append(self._build_item(
                    platform,
                    alias_name,
                    alias_map.get(alias_name) or '',
                    current_platform,
                    current_aliases,
                ))

        return {
            'supported_platforms': list(self.alias_manager.get_supported_platforms()),
            'current_platform': current_platform,
            'default_platforms': ['common'] if current_platform == 'common' else ['common', current_platform],
            'items': items,
        }

    def create_quick_action(self, client_id: str, platform: str, alias: str, command: str) -> dict:
        self._get_session(client_id)
        platform_name = self.alias_manager.normalize_platform(platform)
        alias_name = self._normalize_alias_name(alias)
        command_text = self._normalize_command(command)
        alias_map = self.alias_manager.list_aliases_for_platform(platform_name)
        if alias_name in alias_map:
            raise ValueError(f"Alias '{alias_name}' already exists in {platform_name}")

        self.alias_manager.add_alias(alias_name, command_text, platform=platform_name)
        return {
            'message': f'Quick Action created [{platform_name}]: {alias_name}',
            'item': {
                'platform': platform_name,
                'alias': alias_name,
                'command': command_text,
                'parameters': self.alias_manager.extract_parameters(command_text),
            },
        }

    def update_quick_action(
            self,
            client_id: str,
            original_platform: str,
            original_alias: str,
            platform: str,
            alias: str,
            command: str,
    ) -> dict:
        self._get_session(client_id)
        original_platform_name = self.alias_manager.normalize_platform(original_platform)
        platform_name = self.alias_manager.normalize_platform(platform)
        original_alias_name = self._normalize_alias_name(original_alias)
        alias_name = self._normalize_alias_name(alias)
        command_text = self._normalize_command(command)

        self.alias_manager.update_alias(
            original_alias_name,
            alias_name,
            command_text,
            original_platform=original_platform_name,
            platform=platform_name,
        )
        return {
            'message': f'Quick Action updated [{platform_name}]: {alias_name}',
            'item': {
                'platform': platform_name,
                'alias': alias_name,
                'command': command_text,
                'parameters': self.alias_manager.extract_parameters(command_text),
            },
        }

    def delete_quick_action(self, client_id: str, platform: str, alias: str) -> dict:
        self._get_session(client_id)
        platform_name = self.alias_manager.normalize_platform(platform)
        alias_name = self._normalize_alias_name(alias)
        self.alias_manager.remove_alias(alias_name, platform=platform_name)
        return {
            'message': f'Quick Action removed [{platform_name}]: {alias_name}',
            'platform': platform_name,
            'alias': alias_name,
        }

    def execute_quick_action(
            self,
            client_id: str,
            platform: str,
            alias: str,
            arguments=None,
            presentation: str = 'dialog',
            run_id: str = '',
            tab_id: str = '',
    ) -> dict:
        session = self._get_session(client_id)
        platform_name = self.alias_manager.normalize_platform(platform)
        alias_name = self._normalize_alias_name(alias)
        provided_args = arguments if isinstance(arguments, list) else []
        resolved = self.alias_manager.resolve_alias_definition(
            alias_name,
            provided_args,
            platform_name,
        )

        normalized_presentation = str(presentation or 'dialog').strip().lower()
        if normalized_presentation not in {'dialog', 'terminal'}:
            raise ValueError('presentation must be dialog or terminal')

        normalized_run_id = str(run_id or '').strip() or uuid.uuid4().hex
        display_command = shlex.join([alias_name, *resolved.get('arguments', [])])

        # Terminal 模式在所选 definition 正好是当前 effective alias 时，直接提交 alias 调用，
        # 保留与手工输入 alias 一致的 planner / resolve 反馈；跨平台或被覆盖的原始 definition
        # 则提交已经由 AliasManager 展开的命令，确保执行的仍是用户点选的那一行。
        current_platform = self.alias_manager.get_platform_for_connection(session) or 'common'
        current_aliases = self.alias_manager.list_aliases_for_platform(current_platform) if current_platform != 'common' else {}
        selected_definition_is_effective = (
            platform_name == current_platform
            or (platform_name == 'common' and alias_name not in current_aliases)
        )
        submitted_command = (
            display_command
            if normalized_presentation == 'terminal' and selected_definition_is_effective
            else resolved['command']
        )

        metadata = {
            'quick_action': True,
            'quick_action_run_id': normalized_run_id,
            'quick_action_alias': alias_name,
            'quick_action_platform': platform_name,
            'quick_action_presentation': normalized_presentation,
            'quick_action_display_command': display_command,
            'quick_action_resolved_command': resolved['command'],
            'quick_action_effective_definition': selected_definition_is_effective,
        }
        submitted = self.command_execution_api.submit_web_command(
            client_id,
            submitted_command,
            tab_id=tab_id,
            metadata=metadata,
            source='quick_action',
        )
        return {
            **submitted,
            'run_id': normalized_run_id,
            'platform': platform_name,
            'alias': alias_name,
            'display_command': display_command,
            'resolved_command': resolved['command'],
            'submitted_command': submitted_command,
            'presentation': normalized_presentation,
        }
