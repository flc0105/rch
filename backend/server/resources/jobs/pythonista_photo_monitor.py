JOB_METADATA = {
    "name": "pythonista_photo_monitor",
    "display_name": "Pythonista Photo Monitor",
    "description": "Monitor new photos saved after job start and upload them via HTTP",
    "platforms": ["ios"],
    "params": [
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 5,
            "min": 1,
            "description": "Polling interval in seconds"
        }
    ]
}

import os
import threading
import time

from client.jobs.core.job import Job
from core.utils.formatting import get_size, get_time
from core.utils.artifact_naming import build_artifact_filename
from core.utils.logger import logger


class PythonistaPhotoMonitor(Job):
    def __init__(self):
        super().__init__()
        self.interval = 5
        self.latest_creation_ts = 0.0
        self.latest_boundary_keys = set()

    def on_context_bound(self):
        self.interval = int(self.get_job_param('interval_seconds', 5) or 5)

    def run(self):
        try:
            time.sleep(2)

            import photos
            from PIL import Image

            self.send_to_server(1, 'Dependency loaded: pythonista photos', 0)
            self.send_to_server(1, 'Dependency loaded: pillow', 0)

            self._init_startup_baseline(photos)

            self.mark_running()
            self.send_to_server(1, 'Pythonista photo monitor started', 0)

            while not self.stop_event.is_set():
                try:
                    self._scan_and_upload_new_photos(photos)
                except Exception as e:
                    self.send_to_server(0, f'Photo scan error: {e}', 0)

                time.sleep(self.interval)

            self.send_to_server(1, 'Pythonista photo monitor stopped', 0)

        except Exception as e:
            self.send_to_server(0, f'Pythonista photo monitor error: {e}', 0)
        finally:
            self.mark_stopped()
            logger.info(f'Thread ended: {threading.current_thread().name}')
            self.send_to_server(1, f'Task ended: {threading.current_thread().name}', 1)

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)

    def _init_startup_baseline(self, photos_module):
        assets = list(photos_module.get_assets(media_type='image') or [])

        if not assets:
            self.latest_creation_ts = 0.0
            self.latest_boundary_keys = set()
            self.send_to_server(1, 'Startup baseline set: no existing photos found', 0)
            return

        max_ts = 0.0
        boundary_keys = set()

        for asset in assets:
            ts = self._get_asset_timestamp(asset)
            key = self._get_asset_key(asset)

            if ts > max_ts:
                max_ts = ts
                boundary_keys = {key}
            elif ts == max_ts:
                boundary_keys.add(key)

        self.latest_creation_ts = max_ts
        self.latest_boundary_keys = boundary_keys

        self.send_to_server(
            1,
            f'Startup baseline set: latest existing photo timestamp={self.latest_creation_ts}',
            0
        )

    def _scan_and_upload_new_photos(self, photos_module):
        assets = list(photos_module.get_assets(media_type='image') or [])
        if not assets:
            return

        candidates = []

        for asset in assets:
            ts = self._get_asset_timestamp(asset)
            key = self._get_asset_key(asset)

            if ts > self.latest_creation_ts:
                candidates.append((ts, key, asset))
            elif ts == self.latest_creation_ts and key not in self.latest_boundary_keys:
                candidates.append((ts, key, asset))

        if not candidates:
            return

        candidates.sort(key=lambda x: (x[0], x[1]))

        for ts, key, asset in candidates:
            if self.stop_event.is_set():
                break

            success = self._upload_asset(asset, ts, key)
            if success:
                if ts > self.latest_creation_ts:
                    self.latest_creation_ts = ts
                    self.latest_boundary_keys = {key}
                elif ts == self.latest_creation_ts:
                    self.latest_boundary_keys.add(key)

    def _upload_asset(self, asset, ts, key):
        try:
            image = asset.get_image()
            if image is None:
                self.send_to_server(0, f'Failed to read image from asset: {key}', 0)
                return False

            width = getattr(asset, 'pixel_width', None) or getattr(image, 'width', 0)
            height = getattr(asset, 'pixel_height', None) or getattr(image, 'height', 0)

            # Keep the unique local temporary name, expose a short Artifact name.
            base_name = f'photo_{get_time()}_{int(ts)}_{width}x{height}'
            has_alpha = getattr(image, 'mode', '') in ('RGBA', 'LA') or (
                getattr(image, 'mode', '') == 'P' and 'transparency' in getattr(image, 'info', {})
            )

            if has_alpha:
                file_name = f'{base_name}.png'
                image.save(file_name, 'PNG')
            else:
                if hasattr(image, 'mode') and image.mode not in ('RGB', 'L'):
                    image = image.convert('RGB')
                file_name = f'{base_name}.jpg'
                image.save(file_name, 'JPEG', quality=95)

            file_size = os.path.getsize(file_name)

            self.send_to_server(
                1,
                f'New photo detected, uploading: {file_name} ({get_size(file_size)})',
                0
            )

            try:
                self.upload_file_via_http(
                    file_name, category='job_files',
                    filename=build_artifact_filename('photo', 'png' if has_alpha else 'jpg'),
                )
                self.send_to_server(1, f'Photo uploaded successfully: {file_name}', 0)
                return True
            finally:
                try:
                    os.remove(file_name)
                except Exception as e:
                    self.send_to_server(0, f'Failed to remove temporary photo file: {e}', 0)

        except Exception as e:
            self.send_to_server(0, f'Failed to upload new photo: {e}', 0)
            return False

    def _get_asset_timestamp(self, asset):
        creation_date = getattr(asset, 'creation_date', None)
        if creation_date is None:
            return 0.0

        try:
            return float(creation_date.timestamp())
        except Exception:
            try:
                import calendar
                return float(calendar.timegm(creation_date.utctimetuple()))
            except Exception:
                return 0.0

    def _get_asset_key(self, asset):
        for attr_name in ('local_id', 'local_identifier', 'uuid', 'filename'):
            value = getattr(asset, attr_name, None)
            if value:
                return str(value)

        ts = self._get_asset_timestamp(asset)
        width = getattr(asset, 'pixel_width', 0)
        height = getattr(asset, 'pixel_height', 0)
        media_type = getattr(asset, 'media_type', 'image')

        return f'{media_type}:{ts}:{width}x{height}'