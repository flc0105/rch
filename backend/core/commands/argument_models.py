from dataclasses import dataclass, field
from typing import Any

from core.commands.argument_errors import ArgumentCommandValidationError


@dataclass
class ArgumentOptionSpec:
    """
    单个命令参数定义
    """
    name: str
    option_type: str = 'str'
    required: bool = False
    default: Any = None
    allow_empty: bool = True
    help_text: str = ''
    alias: str = ''
    positional_index: int | None = None
    arity: int = 1
    repeatable: bool = False

    @property
    def is_flag(self) -> bool:
        return self.option_type == 'flag'

    @property
    def is_positional(self) -> bool:
        return self.positional_index is not None


@dataclass
class ArgumentCommandSpec:
    """
    单个命令参数 Schema
    """
    name: str
    description: str = ''
    options: list[ArgumentOptionSpec] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    trailing_named_arguments: str | None = None

    def get_option_map(self) -> dict[str, ArgumentOptionSpec]:
        return {item.name: item for item in self.options}

    def get_option_alias_map(self) -> dict[str, ArgumentOptionSpec]:
        alias_map = {}
        option_map = self.get_option_map()

        for item in self.options:
            alias = str(item.alias or '').strip()
            if not alias:
                continue
            if len(alias) != 1 or alias.startswith('-'):
                raise ArgumentCommandValidationError(
                    f'Invalid alias for --{item.name}: alias must be a single character without dash'
                )
            if alias in option_map:
                raise ArgumentCommandValidationError(
                    f'Invalid alias for --{item.name}: -{alias} conflicts with option --{alias}'
                )
            if alias in alias_map:
                exists = alias_map[alias].name
                raise ArgumentCommandValidationError(
                    f'Duplicate alias -{alias} for --{exists} and --{item.name}'
                )
            alias_map[alias] = item

        return alias_map
