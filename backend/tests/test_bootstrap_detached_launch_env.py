"""Generated bootstrap launches detached processes using OS flags."""
from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService


def test_generated_bootstrap_uses_process_flags_without_mode_markers():
    code = AgentBootstrapScriptService().generate_python_script({
        'server_host': '127.0.0.1', 'server_port': 8123,
        'web_host': '127.0.0.1', 'web_port': 8124,
    })
    assert "kwargs['start_new_session'] = True" in code
    assert 'RCH_CLIENT_LAUNCH_MODE' not in code
    assert 'RCH_CLIENT_LAUNCH_SOURCE' not in code
    assert "subprocess.Popen([str(python), str(script)], **kwargs)" in code
    compile(code, '<generated-bootstrap>', 'exec')


def test_generated_bootstrap_launches_detached_child_without_markers(monkeypatch, tmp_path):
    """Check the subprocess kwargs, not only the generated source text."""
    import sys
    from types import SimpleNamespace
    import subprocess
    code = AgentBootstrapScriptService().generate_python_script({
        'server_host': 'localhost', 'server_port': 1234,
        'web_host': 'localhost', 'web_port': 1235,
    })
    namespace = {'__name__': 'bootstrap_test_module'}
    exec(compile(code, '<bootstrap>', 'exec'), namespace)
    (tmp_path / 'rchclient.py').write_text('# client stub\n')
    captured = {}
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kw: captured.update(kw) or SimpleNamespace(pid=7))
    namespace['launch'](sys.executable, tmp_path)
    assert 'env' not in captured
    assert captured['start_new_session'] is True


def test_windows_powershell_bootstrap_uses_detached_process_flags():
    script = AgentBootstrapScriptService().generate_powershell_script({
        'server_host': 'localhost', 'server_port': 9999, 'web_port': 8085,
    })
    assert 'subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP' in script
    assert '& $py -c $launchCode $script' in script
    assert '$startInfo.CreateNoWindow' not in script
