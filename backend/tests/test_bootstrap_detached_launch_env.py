"""Generated SSH bootstrap supplies the detached launch shape explicitly."""
from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService


def test_generated_bootstrap_marks_detached_mode_on_child():
    code = AgentBootstrapScriptService().generate_python_script({
        'server_host': '127.0.0.1', 'server_port': 8123,
        'web_host': '127.0.0.1', 'web_port': 8124,
    })
    assert "kwargs['start_new_session'] = True" in code
    assert "RCH_CLIENT_LAUNCH_MODE='detached'" in code
    assert "RCH_CLIENT_LAUNCH_SOURCE=('detached_process' if sys.platform == 'win32' else 'new_session')" in code
    assert "subprocess.Popen([str(python), str(script)], **kwargs)" in code
    compile(code, '<generated-bootstrap>', 'exec')


def test_generated_bootstrap_passes_shape_to_detached_child(monkeypatch, tmp_path):
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
    assert captured['env']['RCH_CLIENT_LAUNCH_MODE'] == 'detached'
    assert captured['env']['RCH_CLIENT_LAUNCH_SOURCE'] == 'new_session'
    assert captured['start_new_session'] is True
