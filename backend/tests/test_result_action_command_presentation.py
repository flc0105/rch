"""The generic command endpoint must remain independent of UI presentation."""

import ast
from pathlib import Path
from types import SimpleNamespace


ROUTE_FILE = Path(__file__).resolve().parents[1] / 'server/web/routes/command_execution.py'


def build_command_route():
    source = ast.parse(ROUTE_FILE.read_text(encoding='utf-8'))
    factory = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                   and node.name == 'create_command_execution_blueprint')
    registered, payload, calls = {}, {}, []

    class Blueprint:
        def __init__(self, *_args, **_kwargs):
            pass

        def __getattr__(self, name):
            if name not in {'get', 'post', 'put', 'delete'}:
                raise AttributeError(name)

            def register(path):
                def decorate(func):
                    registered[(name, path)] = func
                    return func
                return decorate
            return register

    class WebApiResponder:
        def json_endpoint(self, func, **_kwargs):
            return func()

    class CommandExecutionApi:
        def submit_web_command(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {'task_id': 'task-1'}

    api = CommandExecutionApi()
    service = SimpleNamespace(command_execution_api=api, command_catalog_api=object(), artifact_api=object())
    namespace = {
        'Blueprint': Blueprint,
        'allow_anonymous': lambda func: func,
        'WebApiResponder': WebApiResponder,
        'get_json_payload': lambda: payload,
        'get_required_command': lambda: payload['command'],
        'get_optional_tab_id': lambda: 'tab-X',
    }
    exec(compile(ast.Module(body=[factory], type_ignores=[]), str(ROUTE_FILE), 'exec'), namespace)
    namespace['create_command_execution_blueprint'](SimpleNamespace(web_service=service))
    return registered[('post', '/api/connections/<client_id>/command')], payload, calls


def test_normal_command_api_is_presentation_agnostic():
    route, payload, calls = build_command_route()
    payload.update(command='echo normal')
    assert route('client-A') == {'task_id': 'task-1'}
    assert calls == [(('client-A', 'echo normal'), {'tab_id': 'tab-X'})]


def test_unrelated_request_keys_never_become_backend_metadata():
    route, payload, calls = build_command_route()
    payload.update(command='echo safe', result_action_run_id='ignored', json_viewer_refresh_run_id='ignored')
    route('client-A')
    assert calls == [(('client-A', 'echo safe'), {'tab_id': 'tab-X'})]
