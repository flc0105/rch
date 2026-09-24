import os
from datetime import datetime

from core.external_tools.paths import EXTERNAL_TOOLS_RUNTIME_ROOT, external_tool_oneshot_runtime_parts
from server.application.external_tools.external_tool_runtime_component import ExternalToolRuntimeComponent


class ExternalToolProcessState(ExternalToolRuntimeComponent):
    """Client oneshot payload state helpers."""

    def _oneshot_timeout_sec(self, meta: dict, runtime: dict | None = None) -> float | None:
        source = runtime if isinstance(runtime, dict) else {}
        oneshot = meta.get('oneshot') if isinstance(meta.get('oneshot'), dict) else {}
        raw = source.get('timeout_sec', oneshot.get('timeout_sec', meta.get('timeout_sec', 60)))
        if raw in ('', None):
            return None
        try:
            value = float(raw)
        except Exception:
            raise ValueError(f'invalid oneshot timeout_sec: {raw}')
        if value <= 0:
            raise ValueError(f'invalid oneshot timeout_sec: {raw}')
        return value

    def _make_oneshot_run_id(self, meta: dict) -> str:
        prefix = self._sanitize_instance_id(meta.get('name') or meta.get('id') or 'oneshot')
        return f'{prefix}-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}'[:96]

    def _apply_client_oneshot_context(self, context: dict, meta: dict, run_id: str) -> dict:
        package_id = str(meta.get('package_id') or '').strip()
        module_id = str(meta.get('id') or meta.get('module_id') or '').strip()
        run_dir = os.path.join(
            EXTERNAL_TOOLS_RUNTIME_ROOT,
            *external_tool_oneshot_runtime_parts(package_id, module_id, run_id),
        ).replace('\\', '/')
        context['run_id'] = run_id
        context['instance_id'] = ''
        context['instance_name'] = ''
        context['instance_runtime_dir'] = run_dir
        context['state_file'] = os.path.join(run_dir, 'result.json').replace('\\', '/')
        return context
