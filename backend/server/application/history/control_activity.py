"""Recording eligibility for the shared Control contract."""
from core.protocol.control import ActivityPolicy, action_spec
from server.config import config


def should_record(domain, action):
    return (action_spec(domain, action).activity == ActivityPolicy.ALWAYS
            or bool(getattr(config, 'RECORD_OPTIONAL_ACTIVITY', False)))
