from core.transfer_settings import FileTransferMode
from client.runtime.http_transfer.strategies.base import normalize_http_transfer_mode
from client.runtime.http_transfer.strategies.cancelable import CancelableHttpTransferStrategy
from client.runtime.http_transfer.strategies.legacy import LegacyHttpTransferStrategy


def build_http_transfer_strategy(owner, mode: str = ''):
    normalized = normalize_http_transfer_mode(mode)
    if normalized == FileTransferMode.HTTP_SIMPLE.value:
        return LegacyHttpTransferStrategy(owner)
    return CancelableHttpTransferStrategy(owner)






