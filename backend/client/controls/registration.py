"""Composition of protocol actions with Client business managers.

The dispatcher consumes registrations; it never resolves a domain or action
into a concrete manager, path preparer or cancellation implementation itself.
"""
from core.protocol.control import ControlDomain, ClipboardAction, ScriptAction, control_actions
from client.controls.dispatcher import ClientControlDispatcher


def register_control_domain(dispatcher, domain, handler, *, prepares=None, cancel_policies=None):
    for action, policy in control_actions(domain):
        dispatcher.register(
            domain, action, handler, policy=policy,
            prepare=(prepares or {}).get(action),
            cancel_policy=(cancel_policies or {}).get(action),
        )


def register_remote_files(dispatcher, manager):
    register_control_domain(
        dispatcher, ControlDomain.REMOTE_FILES, manager.execute,
        prepares=dict.fromkeys(manager.actions, manager.prepare_paths),
        cancel_policies=dict.fromkeys(manager.actions, 'cooperative'),
    )


def _clipboard_disabled(scope, action, payload):
    return 0, 'Clipboard disabled on Client'


def build_control_dispatcher(runtime):
    dispatcher = ClientControlDispatcher(runtime.execution)
    register_control_domain(dispatcher, ControlDomain.JOB, runtime.job_manager.execute)
    register_remote_files(dispatcher, runtime.remote_files_manager)
    register_control_domain(dispatcher, ControlDomain.SCRIPT, runtime.script_manager.execute,
                            cancel_policies={ScriptAction.RUN: runtime.script_manager.cancel_policy})
    register_control_domain(dispatcher, ControlDomain.CONFIGURATION, runtime.configuration_manager.execute)
    register_control_domain(dispatcher, ControlDomain.PROCESS, runtime.process_manager.execute)
    register_control_domain(dispatcher, ControlDomain.WATCHDOG, runtime.watchdog_control.execute)
    register_control_domain(dispatcher, ControlDomain.SESSION, runtime.session_control.execute,
                            cancel_policies={'disconnect': 'none'})
    clipboard = runtime.clipboard_manager
    register_control_domain(dispatcher, ControlDomain.CLIPBOARD,
                            clipboard.execute if clipboard is not None else _clipboard_disabled,
                            cancel_policies=dict.fromkeys(ClipboardAction, 'cooperative'))
    from client.external_tools.control import ExternalToolControl
    from core.protocol.control import ExternalToolAction
    runtime.external_tool_control = ExternalToolControl(runtime)
    register_control_domain(dispatcher, ControlDomain.EXTERNAL_TOOL, runtime.external_tool_control.execute,
                            cancel_policies={ExternalToolAction.READ_INSTANCE_LOGS: 'cooperative',
                                             ExternalToolAction.INSTALL_PACKAGE: 'cooperative',
                                             ExternalToolAction.RUN_ONESHOT: 'cooperative',
                                             ExternalToolAction.EXEC: 'cooperative'})
    # Tunnel is currently disabled for Client sessions; keep the existing
    # control domain registered so requests fail explicitly without importing it.
    def tunnel_control(scope, action, payload):
        return 0, 'Tunnel disabled on Client'
    register_control_domain(dispatcher, ControlDomain.TUNNEL, tunnel_control)
    return dispatcher
