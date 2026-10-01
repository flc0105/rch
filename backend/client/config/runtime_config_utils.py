def format_runtime_config_value(value) -> str:
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if value is None:
        return 'None'
    return str(value)
