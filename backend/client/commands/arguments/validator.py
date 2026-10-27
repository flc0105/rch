from typing import Any

from client.commands.arguments.errors import ArgumentCommandValidationError
from client.commands.arguments.models import ArgumentCommandSpec, ArgumentOptionSpec


class ArgumentCommandValidator:
    """
    acmd 参数归一化与校验器
    """

    def normalize(self, spec: ArgumentCommandSpec, raw_args: dict | None) -> dict:
        if raw_args is None:
            raw_args = {}

        if not isinstance(raw_args, dict):
            raise ArgumentCommandValidationError('Invalid acmd args payload')

        raw_args = self.normalize_arg_keys(spec, raw_args)
        option_map = spec.get_option_map()
        normalized = {}

        self._validate_unknown_options(option_map, raw_args)

        positional_args = raw_args.get('_args') or []
        if positional_args and not isinstance(positional_args, list):
            raise ArgumentCommandValidationError('Invalid positional args payload')

        for option_name, option_spec in option_map.items():
            has_value = option_name in raw_args
            raw_value = raw_args.get(option_name)

            if not has_value and option_spec.is_positional:
                positional_index = option_spec.positional_index
                if positional_index is not None and positional_index < len(positional_args):
                    raw_value = positional_args[positional_index]
                    has_value = True

            if not has_value:
                if option_spec.required and option_spec.default is None:
                    raise ArgumentCommandValidationError(
                        f'Missing required option: --{option_name}'
                    )
                normalized[option_name] = option_spec.default
                continue

            normalized_value = self._convert_value(option_spec, raw_value)

            if option_spec.option_type == 'str' and not option_spec.allow_empty:
                if str(normalized_value).strip() == '':
                    raise ArgumentCommandValidationError(
                        f'Option "--{option_name}" cannot be empty'
                    )

            normalized[option_name] = normalized_value

        if '_args' in raw_args:
            normalized['_args'] = positional_args

        return normalized

    def normalize_arg_keys(self, spec: ArgumentCommandSpec, raw_args: dict | None) -> dict:
        if raw_args is None:
            raw_args = {}

        if not isinstance(raw_args, dict):
            raise ArgumentCommandValidationError('Invalid acmd args payload')

        option_map = spec.get_option_map()
        alias_map = spec.get_option_alias_map()
        raw_args = self._normalize_alias_args(option_map, alias_map, raw_args)
        return self._normalize_inline_args(option_map, alias_map, raw_args)

    def _normalize_alias_args(
        self,
        option_map: dict[str, ArgumentOptionSpec],
        alias_map: dict[str, ArgumentOptionSpec],
        raw_args: dict,
    ) -> dict:
        normalized_args = {}
        source_keys = {}

        for key, value in raw_args.items():
            target_key = self._resolve_payload_option_key(option_map, alias_map, key)

            # 同时传入长名和短名时，dict 无法表达顺序，直接拒绝避免隐式覆盖。
            if target_key in normalized_args:
                self._raise_duplicate_option(target_key, source_keys.get(target_key, ''), key)

            normalized_args[target_key] = value
            source_keys[target_key] = key

        return normalized_args

    def _normalize_inline_args(
        self,
        option_map: dict[str, ArgumentOptionSpec],
        alias_map: dict[str, ArgumentOptionSpec],
        raw_args: dict,
    ) -> dict:
        positional_args = raw_args.get('_args') or []
        if not positional_args:
            return raw_args

        if not isinstance(positional_args, list):
            raise ArgumentCommandValidationError('Invalid positional args payload')

        normalized_args = {}
        source_keys = {}

        for key, value in raw_args.items():
            if key == '_args':
                continue
            normalized_args[key] = value
            source_keys[key] = key

        clean_positional_args = []
        index = 0

        while index < len(positional_args):
            item = positional_args[index]
            token = str(item)
            option_name, inline_value, has_inline_value = self._parse_inline_option_token(
                option_map,
                alias_map,
                token,
            )

            if option_name is None:
                clean_positional_args.append(item)
                index += 1
                continue

            option_spec = option_map[option_name]

            if option_spec.option_type == 'flag':
                option_value = inline_value if has_inline_value else True
                self._put_normalized_option(normalized_args, source_keys, option_name, option_value, token)
                index += 1
                continue

            if has_inline_value:
                option_value = inline_value
                index += 1
            else:
                if index + 1 >= len(positional_args):
                    raise ArgumentCommandValidationError(f'Option "--{option_name}" requires a value')
                option_value = positional_args[index + 1]
                index += 2

            self._put_normalized_option(normalized_args, source_keys, option_name, option_value, token)

        normalized_args['_args'] = clean_positional_args
        return normalized_args

    def _resolve_payload_option_key(
        self,
        option_map: dict[str, ArgumentOptionSpec],
        alias_map: dict[str, ArgumentOptionSpec],
        key: str,
    ) -> str:
        key_text = str(key or '').strip()
        if key_text.startswith('_'):
            return key

        option_key = self._strip_option_prefix(key_text)
        if option_key in option_map:
            return option_key
        # CLI spelling may use --keep-alive for the canonical keep_alive field.
        underscore_key = option_key.replace('-', '_')
        if underscore_key in option_map:
            return underscore_key
        if option_key in alias_map:
            return alias_map[option_key].name
        return key

    def _parse_inline_option_token(
        self,
        option_map: dict[str, ArgumentOptionSpec],
        alias_map: dict[str, ArgumentOptionSpec],
        token: str,
    ) -> tuple[str | None, Any, bool]:
        if token == '--':
            return None, None, False
        if not token.startswith('-') or self._looks_like_negative_number(token):
            return None, None, False

        if token.startswith('--'):
            option_key, inline_value, has_inline_value = self._split_inline_option_token(token[2:])
        else:
            option_key, inline_value, has_inline_value = self._split_inline_option_token(token[1:])

        if option_key in option_map:
            return option_key, inline_value, has_inline_value
        underscore_key = option_key.replace('-', '_')
        if underscore_key in option_map:
            return underscore_key, inline_value, has_inline_value
        if option_key in alias_map:
            return alias_map[option_key].name, inline_value, has_inline_value

        raise ArgumentCommandValidationError(f'Unknown option: {self._format_option_key(token)}')

    def _split_inline_option_token(self, option_text: str) -> tuple[str, str, bool]:
        if '=' not in option_text:
            return option_text, '', False

        option_key, inline_value = option_text.split('=', 1)
        return option_key, inline_value, True

    def _strip_option_prefix(self, key: str) -> str:
        if key.startswith('--'):
            return key[2:]
        if key.startswith('-'):
            return key[1:]
        return key

    def _looks_like_negative_number(self, value: str) -> bool:
        try:
            float(value)
            return value.startswith('-') and len(value) > 1
        except Exception:
            return False

    def _put_normalized_option(
        self,
        normalized_args: dict,
        source_keys: dict,
        target_key: str,
        value: Any,
        source_key: str,
    ):
        if target_key in normalized_args:
            self._raise_duplicate_option(target_key, source_keys.get(target_key, ''), source_key)

        normalized_args[target_key] = value
        source_keys[target_key] = source_key

    def _raise_duplicate_option(
        self,
        target_key: str,
        existing_key: str,
        incoming_key: str,
    ):
        if existing_key == incoming_key:
            raise ArgumentCommandValidationError(
                f'Duplicate option: {self._format_option_key(existing_key)}'
            )

        raise ArgumentCommandValidationError(
            f'Duplicate option: {self._format_option_key(existing_key)} and '
            f'{self._format_option_key(incoming_key)} for --{target_key}'
        )

    def _validate_unknown_options(self, option_map: dict[str, ArgumentOptionSpec], raw_args: dict):
        for key in raw_args:
            if key.startswith('_'):
                continue
            if key not in option_map:
                raise ArgumentCommandValidationError(
                    f'Unknown option: {self._format_option_key(key)}'
                )

    def _format_option_key(self, key: str) -> str:
        text = str(key or '')
        if text.startswith('-'):
            return text
        if len(text) == 1:
            return f'-{text}'
        return f'--{text}'

    def _convert_value(self, option_spec: ArgumentOptionSpec, raw_value: Any):
        option_name = option_spec.name

        if option_spec.option_type == 'flag':
            return self._convert_flag_value(option_name, raw_value)

        if raw_value is True:
            raise ArgumentCommandValidationError(f'Option "--{option_name}" requires a value')

        if option_spec.option_type == 'str':
            return str(raw_value)

        if option_spec.option_type == 'int':
            try:
                return int(str(raw_value).strip())
            except Exception:
                raise ArgumentCommandValidationError(f'Option "--{option_name}" must be an integer')

        if option_spec.option_type == 'float':
            try:
                return float(str(raw_value).strip())
            except Exception:
                raise ArgumentCommandValidationError(f'Option "--{option_name}" must be a number')

        if option_spec.option_type == 'bool':
            return self._convert_bool_value(option_name, raw_value)

        return raw_value

    def _convert_flag_value(self, option_name: str, raw_value: Any) -> bool:
        if raw_value is True:
            return True

        if isinstance(raw_value, str):
            text = raw_value.strip().lower()
            if text in ('1', 'true', 'yes', 'on'):
                return True
            if text in ('0', 'false', 'no', 'off'):
                return False

        raise ArgumentCommandValidationError(f'Invalid flag value for --{option_name}')

    def _convert_bool_value(self, option_name: str, raw_value: Any) -> bool:
        if isinstance(raw_value, bool):
            return raw_value

        text = str(raw_value).strip().lower()
        if text in ('1', 'true', 'yes', 'on'):
            return True
        if text in ('0', 'false', 'no', 'off'):
            return False

        raise ArgumentCommandValidationError(f'Option "--{option_name}" must be true/false')
