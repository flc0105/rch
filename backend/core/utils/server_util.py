import os
import traceback



def completer(text, state):
    """
    自动补全函数
    :param text: 输入的文本
    :param state: 状态
    :return: 补全选项
    """
    options = [cmd for cmd in get_commands() if cmd.startswith(text)]
    if state < len(options):
        return options[state]
    else:
        return None


try:
    if os.name == 'posix':
        import readline

        readline.parse_and_bind('tab: complete')
        readline.set_completer(completer)
except ImportError:
    readline = None
    traceback.print_exc()


def get_commands():
    """
    获取所有命令列表
    :return: 命令列表
    """
    return ['cd', 'clear', 'exit', 'list', 'quit', 'select', 'kill']


def cd(path: str):
    """
    改变当前工作路径
    :param path: 目标路径
    :return: 当前工作路径
    """
    if os.path.exists(path):
        os.chdir(path)
    return os.getcwd()
