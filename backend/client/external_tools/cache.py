import os
import time

from client.external_tools.common import ExternalToolCommon
from core.external_tools.paths import EXTERNAL_TOOLS_PACKAGE_CACHE_ROOT


class ExternalToolCache(ExternalToolCommon):
    """Package cache operations for client-side external tools."""

    def package_cache_path(self, payload: dict) -> tuple[str, str]:
        package = payload.get('package') or {}
        filename = os.path.basename(str(package.get('filename') or '').strip())
        if not filename:
            raise ValueError('package.filename is required')
        cache_dir = self.expand_path(EXTERNAL_TOOLS_PACKAGE_CACHE_ROOT)
        return cache_dir, os.path.join(cache_dir, filename)

    def cache_info(self, payload: dict) -> dict:
        try:
            cache_dir, archive_path = self.package_cache_path(payload)
        except Exception as e:
            return {
                'cache_dir': self.expand_path(EXTERNAL_TOOLS_PACKAGE_CACHE_ROOT),
                'cache_path': '',
                'cached': False,
                'exists': False,
                'size': 0,
                'mtime': '',
                'error': str(e),
            }

        exists = os.path.isfile(archive_path) and os.path.getsize(archive_path) > 0
        info = {
            'cache_dir': cache_dir,
            'cache_path': archive_path,
            'cached': bool(exists),
            'exists': bool(exists),
            'size': 0,
            'mtime': '',
        }
        if exists:
            try:
                stat = os.stat(archive_path)
                info['size'] = int(stat.st_size)
                info['mtime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
            except OSError as e:
                info['error'] = str(e)
        return info

    def download_package(self, payload: dict) -> dict:
        self.validate_package_payload(payload, 'download')
        package = payload.get('package') or {}
        download_url = str(package.get('download_url') or '').strip()

        if not download_url:
            raise ValueError('package.download_url is required')

        cache_dir, archive_path = self.package_cache_path(payload)
        os.makedirs(cache_dir, exist_ok=True)

        before = self.cache_info(payload)
        if before.get('cached'):
            before.update({
                'archive_path': archive_path,
                'source': 'cache',
                'downloaded': False,
                'used_cache': True,
                'message': f'Using cached package: {archive_path}',
            })
            return before

        self.client_api.download_file(
            download_url,
            archive_path,
            timeout=self.DOWNLOAD_TIMEOUT,
            chunk_size=self.DOWNLOAD_CHUNK_SIZE,
            ensure_not_interrupted=self._ensure_not_interrupted,
        )

        after = self.cache_info(payload)
        after.update({
            'archive_path': archive_path,
            'source': 'download',
            'downloaded': True,
            'used_cache': False,
            'message': f'Downloaded package to cache: {archive_path}',
        })
        return after

    def clear_cache_payload(self, payload: dict) -> dict:
        self.validate_package_payload(payload, 'clear-cache')
        cache = self.cache_info(payload)
        cache_path = cache.get('cache_path') or ''
        removed = False
        if cache_path and os.path.isfile(cache_path):
            os.unlink(cache_path)
            removed = True
        after = self.cache_info(payload)
        return {
            'tool_id': payload.get('tool_id') or '',
            'package_id': payload.get('package_id') or payload.get('tool_id') or '',
            'display_name': payload.get('display_name') or payload.get('tool_id') or '',
            'source': payload.get('source') or '',
            'side': payload.get('side') or 'client',
            'platform': payload.get('platform') or '',
            'arch': payload.get('arch') or '',
            'package_key': payload.get('package_key') or '',
            'cache': after,
            'cache_before': cache,
            'cache_removed': removed,
            'removed': removed,
            'message': (
                f'Removed cached package: {cache_path}'
                if removed
                else f'No cached package found: {cache_path or "-"}'
            ),
        }
