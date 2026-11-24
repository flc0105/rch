from enum import Enum


class FileTransferMode(str, Enum):
    HTTP_SIMPLE = "http_simple"
    HTTP_STREAMING = "http_streaming"
    TCP_STREAMING = "tcp_streaming"


# HTTP 文件传输 buffer 的共享边界。
# Client runtime_config 提供可修改值；Server 只使用这些值做上传落盘时的安全兜底与限制。
DEFAULT_HTTP_TRANSFER_BUFFER_SIZE = 1024 * 1024
MIN_HTTP_TRANSFER_BUFFER_SIZE = 64 * 1024
MAX_HTTP_TRANSFER_BUFFER_SIZE = 16 * 1024 * 1024
