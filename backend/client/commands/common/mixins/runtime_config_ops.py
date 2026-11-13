import json
import os

from core.utils.parsing import split_shell_arguments
from core.utils.configuration_cli import JSON_FLAGS, ALL_FLAGS, RESET_FLAGS, RESET_ALL_FLAGS

from client.config.manager import ConfigurationManager
from core.utils.decorator import desc
from client.commands.runtime.interrupts import timeout
from core.utils.output_marker import success, info, error, warning
from client.runtime.launch_context import is_launchd_managed_client


class CommandRuntimeConfigMixin:
    """
    client runtime_config 查询与修改命令。
    """

    @property
    def configuration_manager(self):
        runtime = getattr(self.socket, 'runtime', None)
        manager = getattr(runtime, 'configuration_manager', None)
        if manager is None:
            manager = ConfigurationManager(self.socket, getattr(runtime, 'features', None))
        return manager

    @property
    def runtime_config_service(self):
        return self.configuration_manager.service

    @desc('Show or update client runtime config', group='runtime')
    @timeout(30)
    def set(self, arg=''):
        """
        set
            列出 runtime_config 下 expose=True 的配置项和值，并标注 default / override 来源

        set --all
            按分组列出 runtime_config 下所有基础配置项和值

        set --json
            输出 expose=True 配置项的结构化 JSON

        set KEY value
            修改 runtime_config.KEY。默认只允许修改 expose=True 的配置项。
            如果 value 和 runtime_config.py 默认值相同，则删除 JSON override。
            如果 value 和默认值不同，则写入外部 runtime_config.json。

        set --reset KEY
            删除指定 KEY 的 override，恢复 runtime_config.py 默认值

        set --reset-all
            删除所有 override，全部恢复 runtime_config.py 默认值
        """
        text = str(arg or '').strip()
        if not text:
            return 1, self._format_runtime_config_listing()

        try:
            parts = split_shell_arguments(text, literal_backslashes=(os.name == "nt"))
        except Exception as e:
            return 0, error(f'Invalid set arguments: {e}')

        if not parts:
            return 1, self._format_runtime_config_listing()

        if parts[0] in JSON_FLAGS:
            return 1, json.dumps(
                self.runtime_config_service.build_config_payload(),
                ensure_ascii=False,
            )

        if parts[0] in ALL_FLAGS:
            return 1, self._format_runtime_config_listing(include_hidden=True)

        if parts[0] in RESET_FLAGS:
            if len(parts) != 2:
                return 0, 'Usage: set --reset KEY'
            return self._reset_runtime_config_key(parts[1])

        if parts[0] in RESET_ALL_FLAGS:
            return self._reset_all_runtime_config_overrides()

        if len(parts) < 2:
            return 0, 'Usage: set KEY value'

        key = parts[0]
        value = parts[1] if len(parts) == 2 else ' '.join(parts[1:])

        try:
            result, side_effects = self.configuration_manager.update(key, value, self._checkpoint, is_launchd_managed_client)

            lines = [
                success(
                    f'{result.key} updated, value: {self.runtime_config_service.format_value(result.old_value)}'
                    f' → {self.runtime_config_service.format_value(result.new_value)}'
                ),
            ]
            lines.extend(side_effects)
            return 1, '\n'.join(lines)
        except Exception as e:
            return 0, error(f'Failed to set runtime config: {e}')

    def _format_runtime_config_listing(self, include_hidden: bool = False):
        removed = self.runtime_config_service.prune_redundant_overrides()
        store_path = self.runtime_config_service.get_store_path()
        active_overrides = self.runtime_config_service.format_active_overrides(include_hidden=include_hidden)
        config_items = self.runtime_config_service.format_config_items(include_hidden=include_hidden)

        message = (
                info(f'Runtime config store path: {store_path}\n') +
                f'{active_overrides}\n'
        )

        if removed:
            message += (
                    warning('Pruned redundant overrides: ')
                    + ', '.join(removed)
                    + '\n'
            )

        message += '\n' + config_items
        return message

    def _reset_runtime_config_key(self, key: str):
        try:
            result, side_effects = self.configuration_manager.reset(key, self._checkpoint, is_launchd_managed_client)

            message = (
                    success(f'{result.key} reset to default: ') +
                    f'{self.runtime_config_service.format_value(result.old_value)} -> {self.runtime_config_service.format_value(result.new_value)}'
            )

            if side_effects:
                message += '\n' + '\n'.join(side_effects)

            return 1, message
        except Exception as e:
            return 0, error(f'Failed to reset runtime config: {e}')

    def _reset_all_runtime_config_overrides(self):
        try:
            store_path, side_effects = self.configuration_manager.reset_all(self._checkpoint, is_launchd_managed_client)

            message = (
                    success('All runtime config overrides reset to runtime_config.py defaults\n') +
                    info(f'Runtime config store: {store_path}')
            )

            if side_effects:
                deduped = []
                for item in side_effects:
                    if item not in deduped:
                        deduped.append(item)
                message += '\n' + '\n'.join(deduped)

            return 1, message
        except Exception as e:
            return 0, error(f'Failed to reset all runtime config overrides: {e}')

    def _apply_runtime_config_side_effects(self, key: str, value):
        return self.configuration_manager.effects(key, value, self._checkpoint, is_launchd_managed_client)
