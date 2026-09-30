"""
Server Script SDK。

脚本内可直接使用注入对象：
    artifact.save('/tmp/a.log')
    artifact.download('tool.zip', type='shared_files')
    result = command.run_shell('whoami')
    info = getinfo()
    token = keychains.get_secret('token').getvalue()
    current = context.client_id()
    result = xt.tool('ffmpeg')('--version')
    paths = workspace.list()

也可以显式导入：
    from client.runtime.sdk import artifact, command, context, events, keychains, workspace, xt
"""

from client.runtime.sdk import artifact, command, context, events, keychains, workspace, xt

__all__ = ['artifact', 'command', 'context', 'events', 'keychains', 'workspace', 'xt']
