import json
import re
import shlex

from server.config.config import ALIAS_PATH


class AliasManager:
    PLACEHOLDER_PATTERN = r'<.*?>'
    SUPPORTED_PLATFORMS = ('common', 'win', 'mac', 'linux', 'ios')
    OS_PLATFORM_MAP = {
        'windows': 'win',
        'win': 'win',
        # 兼容旧值 Darwin，但内部统一落到 mac
        'darwin': 'mac',
        'mac': 'mac',
        'macos': 'mac',
        'linux': 'linux',
        'ios': 'ios'
    }
    # QUERY_PLATFORMS = SUPPORTED_PLATFORMS + ('all',)
    QUERY_PLATFORMS = SUPPORTED_PLATFORMS

    def __init__(self):
        self.alias_path = ALIAS_PATH
        self.aliases = self._create_empty_aliases()
        self.load_aliases()

    # ------------------ 持久化 ------------------ #
    def _create_empty_aliases(self):
        return {platform_name: {} for platform_name in self.SUPPORTED_PLATFORMS}

    def _read_alias_file(self):
        """
        从别名文件中读取数据
        """
        with open(self.alias_path, 'r', encoding='utf-8') as file_obj:
            return json.load(file_obj)

    def _write_alias_file(self, aliases: dict):
        """
        将别名数据写入文件
        """
        with open(self.alias_path, 'w', encoding='utf-8') as file_obj:
            json.dump(aliases, file_obj, indent=2, ensure_ascii=False)

    def normalize_platform(
            self,
            platform_name: str,
            allow_empty: bool = False,
            allow_all: bool = False,
            allow_unknown: bool = False,
    ) -> str:
        text = str(platform_name or '').strip().lower()
        if not text:
            if allow_empty:
                return ''
            return 'common'

        normalized = self.OS_PLATFORM_MAP.get(text, text)

        if allow_all and normalized == 'all':
            return 'all'

        if normalized not in self.SUPPORTED_PLATFORMS:
            if allow_unknown:
                return ''
            raise ValueError(f'Unsupported platform: {platform_name}')

        return normalized

    # 兼容现有内部调用；新的跨模块调用使用公开 normalize_platform。
    def _normalize_platform(self, *args, **kwargs):
        return self.normalize_platform(*args, **kwargs)

    def get_supported_platforms(self) -> tuple[str, ...]:
        return tuple(self.SUPPORTED_PLATFORMS)

    def _normalize_alias_payload(self, payload) -> dict:
        normalized = self._create_empty_aliases()
        if not isinstance(payload, dict):
            return normalized

        has_group_keys = any(key in payload for key in self.SUPPORTED_PLATFORMS)
        if has_group_keys:
            for platform_name in self.SUPPORTED_PLATFORMS:
                platform_aliases = payload.get(platform_name) or {}
                if not isinstance(platform_aliases, dict):
                    continue

                normalized[platform_name] = {
                    str(alias_name).strip(): str(command_text)
                    for alias_name, command_text in platform_aliases.items()
                    if str(alias_name).strip() and str(command_text).strip()
                }
            return normalized

        normalized['common'] = {
            str(alias_name).strip(): str(command_text)
            for alias_name, command_text in payload.items()
            if str(alias_name).strip() and str(command_text).strip()
        }
        return normalized

    def load_aliases(self):
        """从文件中加载命令别名"""
        try:
            payload = self._read_alias_file()
            self.aliases = self._normalize_alias_payload(payload)
        except (FileNotFoundError, json.JSONDecodeError):
            self.aliases = self._create_empty_aliases()

    def save_aliases(self):
        """保存命令别名到文件"""
        self._write_alias_file(self.aliases)

    # ------------------ 平台解析 ------------------ #
    def get_platform_for_connection(self, conn=None) -> str:
        session_info = getattr(conn, 'session_info', None)
        os_type = str(getattr(session_info, 'os_type', '') or '').strip().lower()
        os_alias = str(getattr(session_info, 'os_alias', '') or '').strip().lower()
        return self.normalize_platform(
            os_alias or os_type,
            allow_empty=True,
            allow_unknown=True,
        )

    def get_effective_aliases(self, conn=None) -> dict:
        platform_name = self.get_platform_for_connection(conn)
        result = dict(self.aliases.get('common') or {})

        if platform_name and platform_name in self.aliases:
            result.update(self.aliases.get(platform_name) or {})

        return result

    # ------------------ 基础操作 ------------------ #
    def add_alias(self, alias, command, platform: str = 'common'):
        """添加别名"""
        alias_name = str(alias or '').strip()
        command_text = str(command or '').strip()
        platform_name = self.normalize_platform(platform)

        if not alias_name or not command_text:
            raise ValueError("Alias and command cannot be empty")

        self.aliases.setdefault(platform_name, {})
        self.aliases[platform_name][alias_name] = command_text
        self.save_aliases()

    def update_alias(
            self,
            original_alias: str,
            alias: str,
            command: str,
            original_platform: str = 'common',
            platform: str = 'common',
    ):
        """更新 alias；跨名称/平台移动时只进行一次持久化。"""
        original_name = str(original_alias or '').strip()
        alias_name = str(alias or '').strip()
        command_text = str(command or '').strip()
        original_platform_name = self.normalize_platform(original_platform)
        platform_name = self.normalize_platform(platform)

        if not original_name:
            raise ValueError('original alias is required')
        if not alias_name or not command_text:
            raise ValueError('Alias and command cannot be empty')

        original_map = self.aliases.get(original_platform_name) or {}
        if original_name not in original_map:
            raise KeyError(f"Alias '{original_name}' does not exist in {original_platform_name}")

        destination_map = self.aliases.setdefault(platform_name, {})
        moving = original_name != alias_name or original_platform_name != platform_name
        if moving and alias_name in destination_map:
            raise ValueError(f"Alias '{alias_name}' already exists in {platform_name}")

        if moving:
            del original_map[original_name]
        destination_map[alias_name] = command_text
        self.save_aliases()

    def remove_alias(self, alias, platform: str = ''):
        """移除别名"""
        alias_name = str(alias or '').strip()
        if not alias_name:
            raise KeyError("Alias name cannot be empty")

        platform_name = self.normalize_platform(platform, allow_empty=True)
        removed = False
        target_platforms = (platform_name,) if platform_name else self.SUPPORTED_PLATFORMS

        for current_platform in target_platforms:
            alias_map = self.aliases.get(current_platform) or {}
            if alias_name not in alias_map:
                continue
            del alias_map[alias_name]
            removed = True

        if not removed:
            raise KeyError(f"Alias '{alias_name}' does not exist")

        self.save_aliases()

    def list_aliases(self, conn=None):
        """返回格式化的别名列表"""
        return self.get_effective_aliases(conn)

    def list_aliases_for_platform(self, platform: str, conn=None) -> dict:
        platform_name = self.normalize_platform(platform, allow_empty=True, allow_all=True)
        if platform_name == 'all':
            return self.list_aliases_grouped()
        if not platform_name:
            return self.list_aliases(conn=conn)
        return dict(self.aliases.get(platform_name) or {})

    def list_aliases_grouped(self):
        return {
            platform_name: dict(self.aliases.get(platform_name) or {})
            for platform_name in self.SUPPORTED_PLATFORMS
        }

    def get_alias_definition(self, alias: str, platform: str) -> str:
        alias_name = str(alias or '').strip()
        platform_name = self.normalize_platform(platform)
        command = (self.aliases.get(platform_name) or {}).get(alias_name)
        if not command:
            raise KeyError(f"Alias '{alias_name}' not found in {platform_name}")
        return command

    # ------------------ 参数解析 ------------------ #
    def _get_alias_template(self, alias, conn=None):
        """
        获取别名模板命令
        """
        alias_name = str(alias or '').strip()
        command = self.get_effective_aliases(conn).get(alias_name)
        if not command:
            raise KeyError(f"Alias '{alias_name}' not found")
        return command

    def _extract_parameter_occurrences(self, command: str) -> list[dict]:
        """提取模板中的全部占位符，并保留它们的出现位置。"""
        occurrences = []
        for index, placeholder in enumerate(re.findall(self.PLACEHOLDER_PATTERN, str(command or ''))):
            raw_name = str(placeholder or '')[1:-1].strip()
            occurrences.append({
                'name': raw_name or f'arg{index + 1}',
                'placeholder': placeholder,
                'position': index,
            })
        return occurrences

    def _extract_required_args(self, command: str):
        """按首次出现顺序返回唯一参数名；同名占位符共享一个参数。"""
        return [parameter['name'] for parameter in self.extract_parameters(command)]

    def extract_parameters(self, command: str) -> list[dict]:
        parameters = []
        seen_names = set()
        for occurrence in self._extract_parameter_occurrences(command):
            parameter_name = occurrence['name']
            if parameter_name in seen_names:
                continue
            seen_names.add(parameter_name)
            parameters.append(occurrence)
        return parameters

    def _parse_provided_args(self, args=""):
        """
        解析用户实际传入的参数
        """
        return shlex.split(args) if args else []

    def _replace_placeholders(self, command: str, required_args: list, provided_args: list):
        """按参数名绑定值；模板中重复出现的同名占位符复用同一个值。"""
        bindings = {
            parameter_name: str(value)
            for parameter_name, value in zip(required_args, provided_args)
        }
        occurrence_index = 0

        def replace(match):
            nonlocal occurrence_index
            placeholder = match.group(0)
            raw_name = placeholder[1:-1].strip()
            parameter_name = raw_name or f'arg{occurrence_index + 1}'
            occurrence_index += 1
            return bindings[parameter_name]

        return re.sub(self.PLACEHOLDER_PATTERN, replace, command)

    def _validate_alias_args(self, required_args: list, provided_args: list):
        """
        校验 alias 所需参数与实际参数是否匹配
        """
        if required_args:
            if len(required_args) != len(provided_args):
                raise ValueError(f"Expected {len(required_args)} argument(s), got {len(provided_args)}")
            return

        if provided_args:
            raise ValueError('This alias does not accept arguments')

    def resolve_alias_definition(self, alias: str, provided_args: list, platform: str) -> dict:
        alias_name = str(alias or '').strip()
        platform_name = self.normalize_platform(platform)
        command = self.get_alias_definition(alias_name, platform_name)
        required_args = self._extract_required_args(command)
        normalized_args = [str(item) for item in (provided_args or [])]

        self._validate_alias_args(required_args, normalized_args)
        expanded_command = self._replace_placeholders(command, required_args, normalized_args)
        return {
            'alias': alias_name,
            'command': expanded_command,
            'template': command,
            'platform': platform_name,
            'parameters': self.extract_parameters(command),
            'arguments': normalized_args,
        }

    def resolve_alias(self, alias, args="", conn=None) -> dict:
        alias_name = str(alias or '').strip()
        command = self._get_alias_template(alias_name, conn=conn)
        required_args = self._extract_required_args(command)
        provided_args = self._parse_provided_args(args)

        self._validate_alias_args(required_args, provided_args)
        expanded_command = self._replace_placeholders(command, required_args, provided_args)
        return {
            'alias': alias_name,
            'command': expanded_command,
            'platform': self.get_platform_for_connection(conn) or 'common',
        }

    def get_alias_command(self, alias, args="", conn=None):
        """获取别名对应的命令，并替换参数"""
        return self.resolve_alias(alias, args=args, conn=conn)['command']
