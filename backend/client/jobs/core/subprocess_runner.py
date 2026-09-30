import argparse
import importlib.util
import json
import os
import sys
import threading
from types import SimpleNamespace


def _ensure_backend_on_path():
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)


def _parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--context-file', required=True)
    # The client config module inspects sys.argv directly for --profile. Keep the
    # argument here so the child loads the same Server profile as the parent.
    parser.add_argument('--profile', default='')
    args, _unknown = parser.parse_known_args()
    return args


def _load_context(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError('Invalid background job subprocess context')
    return payload


def _build_fallback_report(context: dict, *, state: str, status: int, text: str) -> dict:
    job_id = str(context.get('job_id') or '').strip()
    job_key = str(context.get('job_key') or '').strip()
    job_name = str((context.get('job_metadata') or {}).get('name') or job_key).strip() or job_key
    return {
        'event_type': 'status',
        'client_id': str(context.get('client_id') or '').strip(),
        'command_id': context.get('command_id'),
        'job_id': job_id,
        'job_name': job_name,
        'job_key': job_key,
        'display_name': f'{job_key}#{job_id[:8]}',
        'thread_name': f'Process-{os.getpid()}',
        'execution_mode': 'subprocess',
        'params': dict(context.get('job_params') or {}),
        'state': state,
        'status': status,
        'text': text,
    }


def _post_fallback_report(context: dict, *, state: str, status: int, text: str):
    client_id = str(context.get('client_id') or '').strip()
    if not client_id:
        return
    try:
        from client.http.client_api import ClientApiClient

        ClientApiClient().post_background_job_report(
            _build_fallback_report(context, state=state, status=status, text=text),
            timeout=10,
        )
    except Exception:
        pass


def _load_job_instance(context: dict):
    from core.utils.reflection import get_main_class

    job_path = os.path.abspath(str(context.get('job_path') or '').strip())
    job_key = str(context.get('job_key') or '').strip()
    if not job_path or not os.path.isfile(job_path):
        raise FileNotFoundError(f'Background job script not found: {job_path}')
    if not job_key:
        raise ValueError('Background job key is required')

    module_name = f'_rch_job_{job_key}_{os.getpid()}'
    spec = importlib.util.spec_from_file_location(module_name, job_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Unable to create import spec for: {job_key}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job_class = get_main_class(module, job_key)
    job_instance = job_class()
    job_instance.job_id = str(context.get('job_id') or job_instance.job_id)

    server_proxy = SimpleNamespace(
        info={
            'hostname': str(context.get('hostname') or '').strip(),
        },
        runtime=None,
    )
    job_instance.bind_context(
        server_proxy,
        context.get('command_id'),
        client_id=str(context.get('client_id') or '').strip(),
        job_key=job_key,
        job_metadata=dict(context.get('job_metadata') or {}),
        job_params=dict(context.get('job_params') or {}),
        execution_mode='subprocess',
    )
    return job_instance


def _start_control_reader(job_instance):
    stop_requested = threading.Event()
    stop_notify = {'value': True}
    original_mark_running = job_instance.mark_running

    def _guarded_mark_running():
        # A stop command can arrive immediately after process creation, before the
        # Job reaches run(). Do not let mark_running() clear that stop request.
        if stop_requested.is_set():
            job_instance.is_running = False
            job_instance.stop_event.set()
            return
        original_mark_running()

    job_instance.mark_running = _guarded_mark_running

    def _request_stop(notify: bool):
        stop_notify['value'] = bool(notify)
        stop_requested.set()
        try:
            job_instance.stop(notify=notify)
        except Exception:
            job_instance.is_running = False
            job_instance.stop_event.set()

    def _reader():
        try:
            for raw_line in sys.stdin:
                command = str(raw_line or '').strip().lower()
                if command == 'stop':
                    _request_stop(True)
                    return
                if command == 'stop_silent':
                    _request_stop(False)
                    return
        finally:
            # Parent exit closes stdin. Do not leave a detached long-running child.
            if not stop_requested.is_set():
                _request_stop(False)

    thread = threading.Thread(
        target=_reader,
        name='JobSubprocessControl',
        daemon=True,
    )
    thread.start()
    return thread, stop_requested, stop_notify


def _build_sdk_context(job_instance) -> dict:
    return {
        'client_id': job_instance.client_id or '',
        'command_id': job_instance.command_id if job_instance.command_id is not None else '',
        'hostname': job_instance.hostname or '',
        'source_type': 'background_job',
        'source_id': job_instance.job_id,
        'source_name': job_instance.job_key or job_instance.job_name,
        'job_id': job_instance.job_id,
        'job_name': job_instance.job_name,
        'job_key': job_instance.job_key,
        'execution_mode': 'subprocess',
    }


def main() -> int:
    _ensure_backend_on_path()
    args = _parse_args()
    context = {}

    try:
        context = _load_context(args.context_file)
        from client.runtime.sdk.context import use_script_sdk_context

        job_instance = _load_job_instance(context)
        _control_thread, _stop_requested, _stop_notify = _start_control_reader(job_instance)

        with use_script_sdk_context(None, {'__context__': _build_sdk_context(job_instance)}):
            try:
                job_instance.run()
            except Exception as exc:
                try:
                    job_instance._report_state('error', status=0, text=f'Job failed: {exc}')
                    job_instance.send_to_server(0, f'Job failed: {exc}', 0)
                except Exception:
                    pass
                return 1
            finally:
                if job_instance.is_running:
                    try:
                        job_instance.mark_stopped()
                    except Exception:
                        pass
        return 0
    except Exception as exc:
        if context:
            _post_fallback_report(
                context,
                state='error',
                status=0,
                text=f'Failed to start background job subprocess: {exc}',
            )
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
