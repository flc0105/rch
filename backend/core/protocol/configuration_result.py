"""Typed presentation intent for Configuration Control results."""

from core.protocol.control import ConfigurationAction
from core.protocol.result_envelope import ResultEnvelope


def build_configuration_result(action, *, status='success', message='', data=None):
    """Return one business result for both Web and CLI consumers."""
    if action not in (ConfigurationAction.GET, ConfigurationAction.SET, ConfigurationAction.RESET):
        raise ValueError('Invalid Configuration action')
    if action == ConfigurationAction.GET and status == 'success' and (not isinstance(data, dict) or not isinstance(data.get('items'), list)):
        raise ValueError('Configuration GET requires a configuration payload')
    return ResultEnvelope(status=status, message=str(message), data=data if action == ConfigurationAction.GET and status == 'success' else None).as_payload()
