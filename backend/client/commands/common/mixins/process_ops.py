# client/commands/mixins/process_ops.py

import json

from client.commands.common.services.process.process_service import ProcessService
from core.device.local_identity import get_local_identity
from core.utils.command_output import StructuredCommandResult, render_structured_result
from core.utils.decorator import desc


class CommandProcessMixin:

    def __init__(self, *args, **kwargs):
        self._process_service = None
        super().__init__(*args, **kwargs)

    def _get_process_service(self):
        if self._process_service is None:
            self._process_service = ProcessService(self)
        return self._process_service

    @desc('List running processes', group='process', suggest=False)
    def list_processes(self, arg=''):

        """
        列出所有运行中的进程
        """
        try:
            processes = self._get_process_service().list_processes()
            return 1, json.dumps(processes)
        except Exception as e:
            return 0, f'Failed to list processes: {e}'

    @desc('Get process detail by PID', group='process', suggest=False)
    def get_process_detail(self, arg=''):
        """
        获取单个进程详情，包括：
        - 基本信息
        - 文件路径 / 启动参数 / 工作目录
        - 网络连接
        - 打开的文件
        """
        try:
            pid = int(str(arg or '').strip())
        except Exception:
            return 0, 'PID is required'

        try:
            details = json.dumps(self._get_process_service().get_process_detail(pid))
            return 1, details
        except Exception as e:
            return 0, str(e)

    @desc('List running applications (GUI apps only)', group='process', suggest=False)
    def list_apps(self, arg=''):
        """
        列出运行中的应用程序（仅 GUI 应用）
        """
        try:
            apps = []
            current_platform = get_local_identity().os_alias
            if current_platform == 'win':
                apps = self._get_process_service().list_windows_apps()
            elif current_platform == 'mac':
                apps = self._get_process_service().list_macos_app()
            else:
                raise Exception('Unsupported os:' + str(current_platform))

            return 1, json.dumps(apps)
        except Exception as e:
            return 0, f'Failed to list apps: {e}'

    @desc('Terminate a process by PID', group='process', suggest=False)
    def kill_process(self, pid: str):
        try:
            self._get_process_service().kill_process(pid)
            return 1, f'Process {pid} terminated'
        except Exception as e:
            return 0, str(e)


    def _acmd_ps_common(self, args_dict, payload=None):
        """
        acmd ps 公共实现。

        只做：
        - 调用 ProcessService.list_processes()
        - 根据 pid / name 筛选
        - 返回 StructuredCommandResult 渲染结果

        不在这里写任何 psutil 枚举逻辑。
        """
        pid = args_dict.get('pid')
        name = str(args_dict.get('name') or '').strip()
        output_json = bool(args_dict.get('json', False))

        if pid is not None:
            pid = int(pid)
            if pid < 0:
                raise ValueError('PID must not be negative: {}'.format(pid))

        rows = self._get_process_service().list_processes()
        rows = self._filter_acmd_ps_rows(rows, pid=pid, name=name)

        if not rows:
            if pid is not None and name:
                raise RuntimeError(
                    'No process found for pid {} and name {}'.format(pid, name)
                )

            if pid is not None:
                raise RuntimeError(
                    'No process found for pid {}'.format(pid)
                )

            if name:
                raise RuntimeError(
                    'No process found for name {}'.format(name)
                )

            raise RuntimeError('No processes found')

        result = StructuredCommandResult(
            status=1,
            data=rows,
            shape='table',
        )

        return render_structured_result(
            result,
            output_format='json' if output_json else 'text',
        )

    def _filter_acmd_ps_rows(self, rows, pid=None, name=''):
        name = str(name or '').strip().lower()
        result = []

        for row in rows or []:
            row_pid = self._normalize_process_int(row.get('pid'))

            if pid is not None and row_pid != pid:
                continue

            row_name = str(row.get('name') or '')

            if name and name not in row_name.lower():
                continue

            result.append({
                'pid': row_pid,
                'ppid': self._normalize_process_int(row.get('ppid')),
                'name': row_name,
                'username': row.get('username') or '',
                'status': row.get('status') or '',
            })

        result.sort(key=lambda item: self._normalize_process_int(item.get('pid')))
        return result

    def _normalize_process_int(self, value):
        if value in (None, ''):
            return 0

        try:
            return int(value)
        except Exception:
            return 0