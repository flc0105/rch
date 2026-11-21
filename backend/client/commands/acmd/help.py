from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


class ArgumentCommandHelpBuilder:
    """
    acmd 帮助文本构造器
    """

    TYPE_LABELS = {
        'str': 'string',
        'int': 'int',
        'float': 'float',
        'bool': 'bool',
        'flag': 'flag',
    }

    def build(self, spec: ArgumentCommandSpec) -> str:
        lines = [self._build_usage_line(spec)]

        if spec.description:
            lines.append('')
            lines.append(spec.description)

        option_map = spec.get_option_map()
        if option_map:
            lines.append('')
            lines.append('Options:')

            for option in option_map.values():
                type_label = self.TYPE_LABELS.get(option.option_type, option.option_type)
                required_label = 'required' if option.required else 'optional'
                default_label = ''
                positional_label = ''

                if option.default not in (None, '') and option.option_type != 'flag':
                    default_label = f' default={option.default}'

                option_usage = self._build_option_help_usage(option)
                if option.option_type != 'flag' and option.is_positional:
                    positional_label = f' positional[{option.positional_index}]'

                lines.append(
                    f'  {option_usage:<22} {type_label:<7} {required_label:<8} '
                    f'{option.help_text}{default_label}{positional_label}'
                )

        lines.extend(('', 'Display: --format/-f <format> or --json (available formats depend on the result)'))

        if spec.examples:
            lines.append('')
            lines.append('Examples:')
            for example in spec.examples:
                example_text = str(example or '').strip()
                if example_text:
                    lines.append(f'  {example_text}')

        return '\n'.join(lines).rstrip()

    def build_command_list(self, command_entries: list[dict]) -> str:
        """
        构造 acmd 命令列表帮助
        """
        lines = ['acmd help']

        if not command_entries:
            lines.append('')
            lines.append('No acmd commands registered')
            return '\n'.join(lines)

        lines.append('')
        lines.append('Registered acmd commands:')

        name_width = max(len(item.get('name', '')) for item in command_entries)
        name_width = max(name_width, 4)

        for item in command_entries:
            command_name = item.get('name', '')
            description = item.get('description') or 'No description'
            lines.append(f'  {command_name:<{name_width}}  {description}')

        lines.append('')
        lines.append('Use "acmd help <command>" to show command details')
        return '\n'.join(lines).rstrip()

    def _build_usage_line(self, spec: ArgumentCommandSpec) -> str:
        parts = [f'acmd {spec.name}']

        positional_options = [
            option for option in spec.options
            if option.is_positional and option.option_type != 'flag'
        ]
        positional_options.sort(key=lambda item: item.positional_index)

        for option in positional_options:
            token = f'<{option.name}>'
            if option.required:
                parts.append(token)
            else:
                parts.append(f'[{token}]')

        for option in spec.options:
            if option.is_positional and option.option_type != 'flag':
                continue

            option_token = self._build_option_usage_token(option)
            if option.option_type == 'flag':
                parts.append(f'[{option_token}]')
            elif option.required:
                parts.append(f'[{option_token} <value>]')
            else:
                parts.append(f'[{option_token} <value>]')

        return ' '.join(parts)

    def _build_option_usage_token(self, option: ArgumentOptionSpec) -> str:
        long_token = f'--{option.name}'
        alias = str(option.alias or '').strip()
        if alias:
            return f'-{alias}|{long_token}'
        return long_token

    def _build_option_help_usage(self, option: ArgumentOptionSpec) -> str:
        option_token = self._build_option_usage_token(option).replace('|', ', ')
        if option.option_type == 'flag':
            return option_token
        return f'{option_token} <value>'
