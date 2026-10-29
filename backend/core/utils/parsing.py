import argparse
import shlex
from typing import Sequence, Tuple


class SafeArgumentParser(argparse.ArgumentParser):
    def __init__(self):
        super().__init__(add_help=False)
        self.error_message = None

    def error(self, message):
        self.error_message = message

    def parse_args(self, *args, **kwargs):
        namespace = super().parse_args(*args, **kwargs)
        if self.error_message:
            raise ValueError(self.error_message)
        return namespace


class CommandParser:
    # @staticmethod
    # def parse_command(command: str) -> Tuple[str, str]:
    #     normalized = command.replace('\\', '/').strip()
    #     if not normalized:
    #         return '', ''
    #
    #     parts = shlex.split(normalized)
    #     if not parts:
    #         return '', ''
    #
    #     command_name = parts[0]
    #     command_arg = normalized[len(command_name):].strip()
    #     return command_name, command_arg

    @staticmethod
    def parse_command(command: str) -> Tuple[str, str]:
        raw_command = command.strip()
        normalized = raw_command.replace('\\', '/')
        if not normalized:
            return '', ''

        parts = shlex.split(normalized)
        if not parts:
            return '', ''

        command_name = parts[0]
        # 仅规范化命令名；参数必须保留 shell 原始转义字符，例如 \n。
        command_arg = raw_command[len(command_name):].strip()
        return command_name, command_arg

def split_shell_arguments(text: str, *, literal_backslashes: bool = False) -> list[str]:
    """Split user arguments; Windows paths use literal backslashes, not POSIX escapes.

    Quoting and whitespace grouping stay available in both modes.
    """
    if not literal_backslashes:
        return shlex.split(text)
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''
    return list(lexer)


def parse(cmd: str) -> Tuple[str, str]:
    return CommandParser.parse_command(cmd)


def parse_args(options: Sequence[str], arg_split: Sequence[str]) -> dict:
    parser = SafeArgumentParser()
    for option in options:
        parser.add_argument(f'--{option}', f'-{option[0]}', type=str, nargs='*', required=True)

    arg_dict = vars(parser.parse_args(arg_split))
    for option, value in arg_dict.items():
        if not value:
            raise ValueError(f'Null value not accepted: {option}')
        arg_dict[option] = ' '.join(value)
    return arg_dict


def parse_kwargs(kwargs: Sequence[Tuple[Sequence[str], dict]], arg_split: Sequence[str]) -> dict:
    parser = SafeArgumentParser()
    for kwarg in kwargs:
        parser.add_argument(*kwarg[0], **kwarg[1])

    arg_dict = vars(parser.parse_args(arg_split))
    for key, value in arg_dict.items():
        if isinstance(value, list):
            arg_dict[key] = ' '.join(value)
    return arg_dict


def _is_flag_option(option_name):
    return option_name in {'topmost'}

def scan_args(arg_split: Sequence[str]) -> dict:
    arg_dict = {}
    current_option = None
    current_values = []

    def flush_current():
        nonlocal current_option, current_values
        if current_option is None:
            return

        if not current_values:
            if _is_flag_option(current_option):
                arg_dict[current_option] = True
            else:
                arg_dict[current_option] = ''
        else:
            arg_dict[current_option] = _coerce_scan_arg_value(' '.join(current_values))

        current_option = None
        current_values = []

    for item in arg_split:
        if item.startswith('--'):
            flush_current()
            current_option = item.lstrip('-')
            current_values = []
        else:
            if current_option is None:
                raise ValueError(f'Unexpected argument without option: {item}')
            current_values.append(item)

    flush_current()
    return arg_dict


def _coerce_scan_arg_value(value):
    if value is True:
        return True

    if not isinstance(value, str):
        return value

    normalized = value.strip()
    lowered = normalized.lower()

    if lowered == 'true':
        return True

    if lowered == 'false':
        return False

    return value
