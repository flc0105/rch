"""One-liner may omit the default Reverse mode without changing bootstrap semantics."""

from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService


def test_bootstrap_omitted_reverse_and_explicit_reverse_are_equivalent():
    service = AgentBootstrapScriptService()
    payload = {'server_host': '192.0.2.2', 'server_port': 9999, 'web_port': 8085}
    omitted = service.normalize_bootstrap_payload(payload)
    explicit = service.normalize_bootstrap_payload({**payload, 'connection_mode': 'reverse'})
    assert omitted == explicit
    assert omitted['connection_mode'] == 'reverse'
    assert service.generate_python_script(payload) == service.generate_python_script({**payload, 'connection_mode': 'reverse'})
    assert service.generate_powershell_script(payload) == service.generate_powershell_script({**payload, 'connection_mode': 'reverse'})


def test_bootstrap_only_explicit_bind_changes_mode():
    service = AgentBootstrapScriptService()
    payload = {'web_host': '192.0.2.2', 'web_port': 8085, 'connection_mode': 'bind',
               'bind_host': '0.0.0.0', 'bind_port': 9443}
    assert service.normalize_bootstrap_payload(payload)['connection_mode'] == 'bind'
