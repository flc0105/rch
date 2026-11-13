"""Script execution options shared by the Server and Python Client."""
from dataclasses import dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    INPROC = 'inproc'
    SUBPROCESS_PIPE = 'subprocess_pipe'

    @property
    def cancel_policy(self):
        return 'process' if self is ExecutionMode.SUBPROCESS_PIPE else 'none'


class OutputMode(str, Enum):
    COLLECT = 'collect'
    STREAM = 'stream'


@dataclass(frozen=True)
class ScriptRunModes:
    execution_mode: ExecutionMode
    output_mode: OutputMode

    def to_dict(self):
        return {'execution_mode': self.execution_mode.value, 'output_mode': self.output_mode.value}


# Go advertises only the external Python interpreter; both clients support both output modes.
EXECUTION_CONFIG = 'SCRIPT_DEFAULT_EXECUTION_MODE'
OUTPUT_CONFIG = 'SCRIPT_DEFAULT_OUTPUT_MODE'


def normalize_execution_schema(value):
    if not isinstance(value, dict) or set(value) - {'modes', 'output'}:
        raise ValueError('Script execution must contain only modes and output objects')
    result = {}
    for key, enum in (('modes', ExecutionMode), ('output', OutputMode)):
        if key not in value:
            continue
        spec = value[key]
        if not isinstance(spec, dict) or set(spec) - {'allowed', 'default'}:
            raise ValueError(f'Invalid script execution.{key} schema')
        allowed = spec.get('allowed', [item.value for item in enum])
        if not isinstance(allowed, list) or not allowed or any(not isinstance(item, str) for item in allowed):
            raise ValueError(f'execution.{key}.allowed must be a nonempty list')
        try:
            allowed = [enum(item).value for item in allowed]
        except ValueError as exc:
            raise ValueError(f'Invalid execution.{key}.allowed value') from exc
        if len(set(allowed)) != len(allowed):
            raise ValueError(f'Duplicate execution.{key}.allowed value')
        normalized = {'allowed': allowed}
        if 'default' in spec:
            default = spec['default']
            if default not in allowed:
                raise ValueError(f'execution.{key}.default must be in allowed')
            normalized['default'] = default
        result[key] = normalized
    return result


def run_mode_options(metadata, config_items):
    """Compute effective allowed values and defaults from live configuration."""
    schema = normalize_execution_schema(metadata.get('execution', {}))
    config = {item['key']: item for item in config_items}
    result = {}
    for key, field, enum, config_key in (
        ('modes', 'execution_mode', ExecutionMode, EXECUTION_CONFIG),
        ('output', 'output_mode', OutputMode, OUTPUT_CONFIG),
    ):
        item = config.get(config_key)
        if not item:
            raise ValueError(f'Client does not advertise {config_key}')
        spec = schema.get(key, {})
        supported = item.get('choices') or []
        allowed = [mode.value for mode in enum if mode.value in supported and mode.value in spec.get('allowed', [m.value for m in enum])]
        default = spec.get('default', item['value'])
        result[field] = {'allowed': allowed, 'default': default if default in allowed else None}
    return result


def resolve_run_modes(options, execution_mode=None, output_mode=None):
    values = {}
    for key, enum, selection in (('execution_mode', ExecutionMode, execution_mode), ('output_mode', OutputMode, output_mode)):
        spec = options[key]
        value = spec['default'] if selection is None else selection
        if value not in spec['allowed']:
            raise ValueError(f'Invalid or unavailable {key}: {value!r}; allowed: {", ".join(spec["allowed"])}')
        values[key] = enum(value)
    return ScriptRunModes(**values)


def validate_payload_modes(metadata, execution_mode, output_mode):
    # Both resolved values are required on the wire; a Client must not silently
    # choose its own defaults after the Server has validated the request.
    if execution_mode is None or output_mode is None:
        raise ValueError('Script execution_mode and output_mode are required')
    schema = normalize_execution_schema(metadata.get('execution', {}))
    options = {}
    for key, field, enum in (('modes', 'execution_mode', ExecutionMode), ('output', 'output_mode', OutputMode)):
        options[field] = {'allowed': schema.get(key, {}).get('allowed', [m.value for m in enum]), 'default': None}
    return resolve_run_modes(options, execution_mode, output_mode)
