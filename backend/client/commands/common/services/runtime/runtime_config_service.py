import ast
import sys
from dataclasses import dataclass

from client.config.runtime_config_utils import format_runtime_config_value
from client.config import runtime_config
from client.config.runtime_config_store import (
    clear_runtime_overrides,
    get_runtime_config_path,
    load_runtime_overrides,
    remove_runtime_override,
    save_runtime_overrides,
    update_runtime_override,
)
from core.utils.output_marker import warning, error


@dataclass
class RuntimeConfigUpdateResult:
    key: str
    old_value: object
    new_value: object
    default_value: object
    source: str
    store_path: str
    override_removed: bool = False


class RuntimeConfigService:
    """
    client runtime_config 管理服务。

    职责：
    - 读取 client.config.runtime_config 当前配置项
    - set 后实时更新当前进程 runtime_config 模块值
    - 只把“不同于 runtime_config.py 默认值”的配置写入外部 runtime_config.json
    - 如果 set 的值等于默认值，则删除对应 override
    - 不读取、不修改 rchclient.py
    - 不读取、不修改 client/config/runtime_config.py 源码文件
    """

    SUPPORTED_TYPES = (str, int, float, bool, type(None))
    BOOL_TRUE_VALUES = {'true', '1', 'yes', 'y', 'on'}
    BOOL_FALSE_VALUES = {'false', '0', 'no', 'n', 'off'}

    def list_config_items(self, include_hidden: bool = False) -> list[tuple[str, object, object, str]]:
        overrides = load_runtime_overrides()
        defaults = self.get_default_values()

        items = []
        for key in sorted(self._iter_runtime_config_keys()):
            if not include_hidden and not self.is_exposed_key(key):
                continue

            value = getattr(runtime_config, key)
            default_value = defaults.get(key)
            source = 'override' if key in overrides else 'default'
            items.append((key, value, default_value, source))
        return items

    def build_config_payload(self, include_hidden: bool = False) -> dict:
        self.prune_redundant_overrides()
        items = []

        for key, value, default_value, source in self.list_config_items(include_hidden=include_hidden):
            meta = self.get_config_meta(key)
            raw_choices = meta.get('choices')
            choices = list(raw_choices) if isinstance(raw_choices, (list, tuple)) else []

            items.append({
                'key': key,
                'value': value,
                'default_value': default_value,
                'source': source,
                'group': self.get_config_group(key),
                'desc': self.get_config_desc(key),
                'value_type': self.get_value_type(value, default_value),
                'choices': choices,
                'min_value': meta.get('min'),
                'max_value': meta.get('max'),
                'step': meta.get('step'),
                'editable': self.is_supported_key(key),
            })

        return {
            'store_path': self.get_store_path(),
            'items': items,
        }

    def get_value_type(self, value, default_value=None) -> str:
        reference = default_value if default_value is not None else value
        if isinstance(reference, bool):
            return 'boolean'
        if isinstance(reference, int) and not isinstance(reference, bool):
            return 'integer'
        if isinstance(reference, float):
            return 'float'
        if isinstance(reference, str):
            return 'string'
        if reference is None:
            return 'null'
        return type(reference).__name__

    def format_config_items(self, include_hidden: bool = False) -> str:
        items = self.list_config_items(include_hidden=include_hidden)
        if not items:
            return error('No runtime config items')

        grouped_items: dict[str, list[tuple[str, object, object, str]]] = {}
        for item in items:
            key = item[0]
            group = self.get_config_group(key)
            grouped_items.setdefault(group, []).append(item)

        lines = []
        for group in sorted(grouped_items.keys()):
            if lines:
                lines.append('')
            lines.append(f'[{group}]')
            for key, value, default_value, source in grouped_items[group]:
                lines.append(self.format_config_item_line(key, value, default_value, source))
        return '\n'.join(lines)

    def format_config_item_line(self, key: str, value, default_value, source: str) -> str:
        value_text = self.format_value(value)

        if source == 'override':
            return (
                f'{key} = {value_text}  '
                f'[override, default={self.format_value(default_value)}]'
            )

        return f'{key} = {value_text}  [default]'

    def format_active_overrides(self, include_hidden: bool = False) -> str:
        overrides = load_runtime_overrides()
        if not include_hidden:
            overrides = {
                key: value
                for key, value in overrides.items()
                if self.is_exposed_key(key)
            }

        if not overrides:
            return warning('Active overrides: none')

        defaults = self.get_default_values()
        lines = [warning('Active overrides:')]
        for key in sorted(overrides.keys()):
            value = overrides[key]
            default_value = defaults.get(key)
            if key in defaults:
                lines.append(
                    f'  {key} = {self.format_value(value)} '
                    f'(default={self.format_value(default_value)})'
                )
            else:
                lines.append(
                    f'  {key} = {self.format_value(value)} '
                    f'(unknown default)'
                )
        return '\n'.join(lines)

    def set_config_value(self, key: str, raw_value: str) -> RuntimeConfigUpdateResult:
        normalized_key = self.normalize_key(key)
        if not normalized_key:
            raise ValueError('Config key is required')
        if not self.is_supported_key(normalized_key):
            raise KeyError(f'Unknown or unsupported runtime config key: {normalized_key}')

        defaults = self.get_default_values()
        old_value = getattr(runtime_config, normalized_key)
        default_value = defaults.get(normalized_key, old_value)

        new_value = self.coerce_value(raw_value, default_value)
        self.validate_config_value(normalized_key, new_value)
        override_removed = False

        if normalized_key in defaults and new_value == default_value:
            store_path = remove_runtime_override(normalized_key)
            override_removed = True
            source = 'default'
        else:
            store_path = update_runtime_override(normalized_key, new_value)
            source = 'override'

        setattr(runtime_config, normalized_key, new_value)
        self._refresh_runtime_override_markers()
        self._sync_loaded_runtime_symbols(normalized_key, old_value, new_value)

        return RuntimeConfigUpdateResult(
            key=normalized_key,
            old_value=old_value,
            new_value=new_value,
            default_value=default_value,
            source=source,
            store_path=store_path,
            override_removed=override_removed,
        )

    def reset_config_key(self, key: str) -> RuntimeConfigUpdateResult:
        normalized_key = self.normalize_key(key)
        if not normalized_key:
            raise ValueError('Config key is required')
        if not self.is_supported_key(normalized_key):
            raise KeyError(f'Unknown or unsupported runtime config key: {normalized_key}')

        defaults = self.get_default_values()
        if normalized_key not in defaults:
            raise KeyError(f'Default value not found for runtime config key: {normalized_key}')

        old_value = getattr(runtime_config, normalized_key)
        default_value = defaults[normalized_key]

        store_path = remove_runtime_override(normalized_key)
        setattr(runtime_config, normalized_key, default_value)
        self._refresh_runtime_override_markers()
        self._sync_loaded_runtime_symbols(normalized_key, old_value, default_value)

        return RuntimeConfigUpdateResult(
            key=normalized_key,
            old_value=old_value,
            new_value=default_value,
            default_value=default_value,
            source='default',
            store_path=store_path,
            override_removed=True,
        )

    def reset_all_overrides(self) -> str:
        defaults = self.get_default_values()
        old_values = {
            key: getattr(runtime_config, key)
            for key in self._iter_runtime_config_keys()
        }

        store_path = clear_runtime_overrides()

        for key, default_value in defaults.items():
            if self.is_known_config_key(key):
                setattr(runtime_config, key, default_value)

        self._refresh_runtime_override_markers()

        for key, old_value in old_values.items():
            if key in defaults:
                self._sync_loaded_runtime_symbols(key, old_value, defaults[key])

        return store_path

    def prune_redundant_overrides(self) -> list[str]:
        """
        清理 JSON 中和 runtime_config.py 默认值相同的 override。

        场景：
        - 之前 JSON 里有 KEY=false
        - 后来你手动把 runtime_config.py 默认值也改成 false
        - 这个 override 已经没有意义，查询 set 时顺手清理
        """
        overrides = load_runtime_overrides()
        defaults = self.get_default_values()

        deprecated_keys = getattr(runtime_config, '_RUNTIME_CONFIG_DEPRECATED_KEYS', set())
        if not isinstance(deprecated_keys, (set, list, tuple)):
            deprecated_keys = set()
        deprecated_keys = {str(key).strip().upper() for key in deprecated_keys if str(key).strip()}

        removed = []
        for key in list(overrides.keys()):
            if key in deprecated_keys or (key in defaults and overrides[key] == defaults[key]):
                overrides.pop(key, None)
                removed.append(key)

        if removed:
            save_runtime_overrides(overrides)
            self._refresh_runtime_override_markers()

        return removed

    def get_store_path(self) -> str:
        return get_runtime_config_path()

    def get_default_values(self) -> dict:
        defaults = getattr(runtime_config, '_RUNTIME_CONFIG_DEFAULTS', None)
        if isinstance(defaults, dict):
            return dict(defaults)
        return {}

    def get_config_meta(self, key: str) -> dict:
        metadata = getattr(runtime_config, '_RUNTIME_CONFIG_META', None)
        if not isinstance(metadata, dict):
            return {}

        item = metadata.get(self.normalize_key(key))
        return dict(item) if isinstance(item, dict) else {}

    def get_config_group(self, key: str) -> str:
        group = self.get_config_meta(key).get('group')
        return str(group or 'other').strip() or 'other'

    def get_config_desc(self, key: str) -> str:
        desc = self.get_config_meta(key).get('desc')
        return str(desc or '').strip()

    def is_exposed_key(self, key: str) -> bool:
        return bool(self.get_config_meta(key).get('expose'))

    def normalize_key(self, key: str) -> str:
        return str(key or '').strip().upper()

    def is_known_config_key(self, key: str) -> bool:
        if not isinstance(key, str) or not key.isupper():
            return False
        if not hasattr(runtime_config, key):
            return False
        value = getattr(runtime_config, key)
        return isinstance(value, self.SUPPORTED_TYPES)

    def is_supported_key(self, key: str) -> bool:
        # 默认只允许修改 expose=True 的配置，避免内部常量/低频参数被误改。
        # 如果以后要允许所有 runtime_config 基础类型被 set 修改，把这里改成：
        # return self.is_known_config_key(key)
        return self.is_known_config_key(key) and self.is_exposed_key(key)

    def format_value(self, value) -> str:
        return format_runtime_config_value(value)

    def coerce_value(self, raw_value: str, reference_value):
        text = str(raw_value or '').strip()
        if text == '':
            raise ValueError('Config value is required')

        if isinstance(reference_value, bool):
            return self._coerce_bool(text)

        if isinstance(reference_value, int) and not isinstance(reference_value, bool):
            return self._coerce_int(text)

        if isinstance(reference_value, float):
            return self._coerce_float(text)

        if reference_value is None:
            return self._coerce_untyped(text)

        if isinstance(reference_value, str):
            return self._coerce_string(text)

        raise TypeError(f'Unsupported config value type: {type(reference_value).__name__}')

    def validate_config_value(self, key: str, value) -> None:
        meta = self.get_config_meta(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return

        min_value = meta.get('min')
        max_value = meta.get('max')

        if isinstance(min_value, (int, float)) and value < min_value:
            raise ValueError(f'{key} must be >= {min_value}')
        if isinstance(max_value, (int, float)) and value > max_value:
            raise ValueError(f'{key} must be <= {max_value}')

    def _coerce_bool(self, text: str) -> bool:
        lowered = text.strip().lower()
        if lowered in self.BOOL_TRUE_VALUES:
            return True
        if lowered in self.BOOL_FALSE_VALUES:
            return False
        raise ValueError(f'Invalid boolean value: {text}')

    def _coerce_int(self, text: str) -> int:
        try:
            return int(text, 10)
        except Exception as e:
            raise ValueError(f'Invalid integer value: {text}') from e

    def _coerce_float(self, text: str) -> float:
        try:
            return float(text)
        except Exception as e:
            raise ValueError(f'Invalid float value: {text}') from e

    def _coerce_string(self, text: str) -> str:
        try:
            value = ast.literal_eval(text)
            if isinstance(value, str):
                return value
        except Exception:
            pass
        return text

    def _coerce_untyped(self, text: str):
        lowered = text.lower()
        if lowered in ('none', 'null'):
            return None
        if lowered in self.BOOL_TRUE_VALUES:
            return True
        if lowered in self.BOOL_FALSE_VALUES:
            return False
        try:
            return int(text, 10)
        except Exception:
            pass
        try:
            return float(text)
        except Exception:
            pass
        return self._coerce_string(text)

    def _iter_runtime_config_keys(self):
        for key, value in vars(runtime_config).items():
            if key.isupper() and isinstance(value, self.SUPPORTED_TYPES):
                yield key

    def _refresh_runtime_override_markers(self):
        overrides = load_runtime_overrides()
        try:
            runtime_config._RUNTIME_CONFIG_OVERRIDE_KEYS = sorted(overrides.keys())
            runtime_config._RUNTIME_CONFIG_OVERRIDE_PATH = get_runtime_config_path()
        except Exception:
            pass

    def _sync_loaded_runtime_symbols(self, key: str, old_value, new_value):
        """
        兼容当前代码中已有的 from client.config.runtime_config import KEY 写法。

        这里只改当前进程内已经加载的 client/core/rchclient 模块同名常量，
        不读写任何源码文件。
        """
        for module_name, module in list(sys.modules.items()):
            if module is None:
                continue
            if not self._should_touch_loaded_module(module_name):
                continue

            self._set_attr_if_equal(module, key, old_value, new_value)
            module_dict = getattr(module, '__dict__', {}) or {}
            for value in list(module_dict.values()):
                if isinstance(value, type):
                    self._set_attr_if_equal(value, key, old_value, new_value)

    def _should_touch_loaded_module(self, module_name: str) -> bool:
        return (
            module_name == 'rchclient'
            or module_name.startswith('client.')
            or module_name.startswith('core.')
        )

    def _set_attr_if_equal(self, target, key: str, old_value, new_value):
        if not hasattr(target, key):
            return
        try:
            current_value = getattr(target, key)
            if current_value != old_value:
                return
            setattr(target, key, new_value)
        except Exception:
            pass