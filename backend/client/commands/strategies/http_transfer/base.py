import requests
from requests.adapters import HTTPAdapter

from client.config import runtime_config
from core import transfer_settings


class TransferBufferHttpAdapter(HTTPAdapter):
    """
    统一控制 urllib3 读取 request body 时使用的 blocksize。

    requests/urllib3 默认 blocksize 较小；大文件上传时即使上层 stream
    自己设置了更大的 chunk，也可能被底层反复以较小 size 调用 read()。
    """

    def __init__(self, buffer_size: int, *args, **kwargs):
        self.buffer_size = max(int(buffer_size or 1), 1)
        super().__init__(*args, **kwargs)

    @staticmethod
    def _ignore_blocksize_in_pool_key(pool_manager):
        """
        urllib3 1.x 的 PoolKey 没有 key_blocksize 字段，但连接池本身仍可以
        将 blocksize 作为 connection kwargs 传给底层 HTTPConnection。

        因此只从 pool key 的计算上下文中移除 blocksize，不移除实际连接配置，
        既兼容旧版 urllib3，也继续让请求 body 使用配置的传输 buffer。
        """
        key_functions = getattr(pool_manager, 'key_fn_by_scheme', None)
        if not isinstance(key_functions, dict):
            return

        for scheme, key_function in list(key_functions.items()):
            if getattr(key_function, '_rch_ignore_blocksize', False):
                continue

            def compatible_key_function(request_context, original=key_function):
                compatible_context = dict(request_context or {})
                compatible_context.pop('blocksize', None)
                return original(compatible_context)

            compatible_key_function._rch_ignore_blocksize = True
            key_functions[scheme] = compatible_key_function

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs['blocksize'] = self.buffer_size
        result = super().init_poolmanager(
            connections,
            maxsize,
            block=block,
            **pool_kwargs,
        )
        self._ignore_blocksize_in_pool_key(self.poolmanager)
        return result

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs['blocksize'] = self.buffer_size
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        self._ignore_blocksize_in_pool_key(manager)
        return manager


class HttpTransferStrategy:
    MODE_NAME = 'base'

    def __init__(self, owner):
        self.owner = owner

    def get_mode_name(self) -> str:
        return self.MODE_NAME

    def is_cancel_supported(self) -> bool:
        return False

    def configure_context_for_upload(self):
        self.owner._set_cancel_policy(
            mode='cooperative' if self.is_cancel_supported() else 'none',
            message='Current HTTP transfer mode is legacy; upload cancellation is not supported',
        )

    def configure_context_for_download(self):
        self.owner._set_cancel_policy(
            mode='cooperative' if self.is_cancel_supported() else 'none',
            message='Current HTTP transfer mode is legacy; download cancellation is not supported',
        )

    def get_buffer_size(self) -> int:
        try:
            value = int(
                getattr(
                    runtime_config,
                    'HTTP_TRANSFER_BUFFER_SIZE',
                    transfer_settings.DEFAULT_HTTP_TRANSFER_BUFFER_SIZE,
                )
                or 0
            )
        except Exception:
            value = transfer_settings.DEFAULT_HTTP_TRANSFER_BUFFER_SIZE

        return max(value, 1)

    def get_idle_timeout(self):
        enabled = bool(
            getattr(
                runtime_config,
                'HTTP_TRANSFER_IDLE_TIMEOUT_ENABLED',
                True,
            )
        )

        if not enabled:
            return None

        try:
            seconds = float(
                getattr(
                    runtime_config,
                    'HTTP_TRANSFER_IDLE_TIMEOUT_SECONDS',
                    6 * 60 * 60,
                )
                or 0
            )
        except Exception:
            seconds = float(6 * 60 * 60)

        if seconds <= 0:
            return None

        return seconds

    def create_http_session(self):
        session = requests.Session()

        adapter = TransferBufferHttpAdapter(
            self.get_buffer_size()
        )

        session.mount('http://', adapter)
        session.mount('https://', adapter)

        return session

    def normalize_request_exception(
        self,
        exc: requests.RequestException,
    ):
        idle_timeout = self.get_idle_timeout()

        if idle_timeout is None:
            return exc

        text = str(exc or '').lower()

        if (
            isinstance(exc, requests.Timeout)
            or 'timed out' in text
            or 'timeout' in text
        ):
            return requests.Timeout(
                'HTTP file transfer made no network I/O progress '
                f'for {idle_timeout:g}s'
            )

        return exc

    def upload_file(
        self,
        file_path: str,
        upload_url: str,
        form_data: dict,
        progress_callback=None,
    ):
        raise NotImplementedError

    def download_file(
        self,
        url: str,
        target_path: str,
        progress_callback=None,
    ):
        raise NotImplementedError


def normalize_http_transfer_mode(mode: str = '') -> str:
    normalized = str(mode or '').strip().lower()

    if normalized in ('legacy', 'cancelable'):
        return normalized

    normalized_default = str(
        runtime_config.HTTP_TRANSFER_MODE or ''
    ).strip().lower()

    if normalized_default in ('legacy', 'cancelable'):
        return normalized_default

    return 'cancelable'