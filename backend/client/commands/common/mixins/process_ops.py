# client/commands/mixins/process_ops.py

import json

from client.commands.common.services.process.process_service import ProcessService
from client.commands.arguments.decorators import argument_command
from client.commands.platform.specs.common import KILL_ARGUMENT_SPEC, FIND_PROC_ARGUMENT_SPEC
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


    @argument_command('kill', spec=KILL_ARGUMENT_SPEC, api_grants=('interactions:request',))
    def _acmd_kill(self, args_dict, payload=None):
        from client.commands.common.services.process.approved_process_service import (
            ClientCommandInteractions, ProcessApprovalError, find_targets,
            build_multi_preview, terminate_verified,
        )
        import os

        self._set_timeout(240)
        try:
            extra = args_dict.get('_args') or []
            if extra and any(token != '-9' for token in extra):
                raise ValueError('Unknown kill argument; use --pid, --name, --port, -9, --force or --no-confirm')
            force = bool(args_dict.get('force') or '-9' in extra)
            no_confirm = bool(args_dict.get('no-confirm'))
            criteria = {key: args_dict[key] for key in ('pid', 'name', 'port')
                        if args_dict.get(key) not in (None, '')}
            if len(criteria) > 1:
                raise ValueError('Specify exactly one of --pid, --name or --port')
            if not criteria and no_confirm:
                raise ValueError('--no-confirm requires --pid, --name or --port')
            if not criteria:
                ui = ClientCommandInteractions(self)
                choice = ui.select('Find a process by:', ['pid', 'name', 'port'],
                                   title='Process lookup')
                target = ui.ask(f'Enter {choice}:', title='Process lookup')
                criteria[choice] = target
            if 'pid' in criteria:
                criteria['pid'] = int(criteria['pid'])
                if criteria['pid'] <= 1:
                    raise ProcessApprovalError('Protected PID')
            if 'port' in criteria:
                criteria['port'] = int(criteria['port'])
                if not 1 <= criteria['port'] <= 65535:
                    raise ProcessApprovalError('Port must be 1..65535')
            if 'name' in criteria:
                criteria['name'] = str(criteria['name']).strip()
                if not criteria['name']:
                    raise ValueError('Name must not be empty')
            rows = (find_targets(criteria) if no_confirm
                    else find_targets(criteria, preview_limit=100))
            if not rows:
                return 0, 'No matching Client processes'
            own_pid = os.getpid()
            if any(int(row['pid']) <= 1 or int(row['pid']) == own_pid for row in rows):
                raise ProcessApprovalError('Protected process in matching results; narrow the selection')
            if not no_confirm:
                selected_ids, force = ClientCommandInteractions(self).approve_processes(
                    'Approve termination of selected Client processes?',
                    build_multi_preview(rows, criteria=criteria, force_default=force))
                rows = [row for row in rows if str(row['pid']) in selected_ids]
                if not rows:
                    return 1, 'No processes selected; no signal sent.'
            self._checkpoint(fallback_timeout=240)
            outcomes = []
            for row in rows:
                self._checkpoint(fallback_timeout=240)
                try:
                    signal_name = terminate_verified(row, force=force, port=criteria.get('port'))
                    outcomes.append(f'{signal_name} sent to PID {row["pid"]} ({row["name"]})')
                except (OSError, ProcessApprovalError) as exc:
                    outcomes.append(f'PID {row["pid"]} failed: {exc}')
            failures = [line for line in outcomes if ' failed:' in line]
            return (0 if failures else 1), '\n'.join(outcomes)
        except (ValueError, ProcessApprovalError, OSError) as exc:
            return 0, f'Process termination failed: {exc}'
        except Exception as exc:
            return 0, f'Process termination unavailable: {exc}'

    @argument_command('find_proc', spec=FIND_PROC_ARGUMENT_SPEC)
    def _acmd_find_proc(self, args_dict, payload=None):
        from client.commands.common.services.process.approved_process_service import (
            find_targets, ProcessApprovalError,
        )
        criteria = {key: args_dict[key] for key in ('pid', 'name', 'port')
                    if args_dict.get(key) not in (None, '')}
        if len(criteria) > 1:
            return 0, 'Specify one of --pid, --name or --port'
        try:
            if 'pid' in criteria and int(criteria['pid']) <= 1:
                raise ValueError('PID must be greater than 1')
            if 'port' in criteria and not 1 <= int(criteria['port']) <= 65535:
                raise ValueError('Port must be 1..65535')
            rows = find_targets(criteria) if criteria else self._get_process_service().list_processes()
            output = []
            for row in rows:
                pid = int(row.get('pid') or 0)
                item = {key: row.get(key, '') for key in ('pid', 'name', 'status')}
                item['user'] = row.get('user') or row.get('username') or ''
                item['_actions'] = ([{'label': 'Kill', 'command': f'acmd kill --pid {pid}'}]
                                    if pid > 1 and pid != __import__('os').getpid() else [])
                output.append(item)
            if not output:
                return (1, '[]' if args_dict.get('json') else 'No matching processes')
            if args_dict.get('json'):
                return render_structured_result(
                    StructuredCommandResult(status=1, data=output, shape='table'),
                    output_format='json')
            # Row actions are presentation metadata for the JSON viewer only.
            return render_structured_result(
                StructuredCommandResult(status=1,
                    data=[{k:v for k,v in row.items() if k != '_actions'} for row in output],
                    shape='table'), output_format='text')
        except (ValueError, ProcessApprovalError, OSError) as exc:
            return 0, f'Process lookup failed: {exc}'

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