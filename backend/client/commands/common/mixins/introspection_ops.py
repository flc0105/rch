import inspect
from core.utils.decorator import desc
from client.commands.runtime.manifest_metadata import command_metadata
from core.utils.command_help import render_grouped_client_help


class CommandIntrospectionMixin:

    def _get_exported_command_methods(self):
        """
        获取所有可导出的命令方法
        """
        return {
            name: method
            for name, method in inspect.getmembers(
                self,
                lambda x: inspect.isfunction(x) or inspect.ismethod(x)
            )
            if hasattr(method, 'help')
        }

    def _get_argument_command_registry(self):
        """
        获取 acmd 注册表
        """
        getter = getattr(self, 'get_argument_command_registry', None)
        if callable(getter):
            registry = getter()
            if registry is not None:
                return registry

        from client.commands.arguments.registry import ArgumentCommandRegistry
        return ArgumentCommandRegistry(self)

    def _get_argument_command_manifest_payload(self):
        """
        获取 acmd 自动补全清单
        """
        try:
            registry = self._get_argument_command_registry()
            return registry.get_manifest_payload()
        except Exception:
            return []

    def _get_argument_command_help_items(self):
        """
        获取 acmd help 分组项
        """
        try:
            registry = self._get_argument_command_registry()
            entries = registry.list_command_entries()
            return [
                (f'acmd {item.get("name", "")}', item.get('description') or 'No description')
                for item in entries
                if item.get('name')
            ]
        except Exception:
            return []

    def get_command_manifest_payload(self):
        """
        获取命令清单数据（本地方法，不通过 socket 返回）
        """
        methods = self._get_exported_command_methods()
        payload = [
            {
                'name': name,
                'help': method.help,
                'group': getattr(method, 'group', 'general'),
                'suggest': getattr(method, 'suggest', True),
                **command_metadata(method),
            }
            for name, method in methods.items()
            if getattr(method, 'suggest', True)
        ]

        payload.extend(self._get_argument_command_manifest_payload())
        payload.sort(key=lambda item: (item.get('group', 'general'), item.get('name', '').lower()))
        return payload

    def _group_command_help_payload(self):
        """
        将命令按 group 分组，生成 help 文本结构
        """
        methods = self._get_exported_command_methods()
        grouped = {}

        for name, method in methods.items():
            # suggest=False 的内部命令不在 help 中展示，但仍保留执行能力。
            if not getattr(method, 'suggest', True):
                continue
            group = getattr(method, 'group', 'general')
            grouped.setdefault(group, []).append((name, method.help))

        argument_command_items = self._get_argument_command_help_items()
        if argument_command_items:
            grouped.setdefault('acmd', []).extend(argument_command_items)

        for group_name in grouped:
            grouped[group_name].sort(key=lambda item: item[0].lower())

        return grouped


    @desc('Show available commands', group='session')
    def help(self):
        grouped = self._group_command_help_payload()
        if not grouped:
            return 1, ''

        return 1, render_grouped_client_help(grouped)








