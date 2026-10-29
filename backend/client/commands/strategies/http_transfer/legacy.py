import os

import requests

from client.commands.strategies.http_transfer.base import HttpTransferStrategy


class LegacyHttpTransferStrategy(HttpTransferStrategy):
    MODE_NAME = 'legacy'

    def upload_file(self, file_path: str, upload_url: str, form_data: dict, progress_callback=None):
        file_size = os.path.getsize(file_path)
        if file_size > 1024 * 1024 * 1024:
            raise ValueError(
                'Legacy HTTP upload is limited to 1 GB.\n'
                'Legacy HTTP upload buffers the full multipart body in memory.\n'
                'Use cancelable transfer mode for large files.'
            )

        self.configure_context_for_upload()
        session = self.create_http_session()
        try:
            with open(file_path, 'rb') as file_obj:
                return session.post(
                    upload_url,
                    files={'file': (os.path.basename(file_path), file_obj)},
                    data=form_data,
                )
        except requests.RequestException as e:
            raise
        finally:
            session.close()

    def download_file(self, url: str, target_path: str, progress_callback=None):
        self.configure_context_for_download()
        session = self.create_http_session()
        try:
            with session.get(
                    url,
                    stream=True,
            ) as response:
                response.raise_for_status()
                try:
                    total_bytes = max(0, int(response.headers.get('Content-Length') or 0))
                except Exception:
                    total_bytes = 0
                transferred_bytes = 0

                with open(target_path, 'wb') as file_obj:
                    for chunk in response.iter_content(chunk_size=self.get_buffer_size()):
                        if not chunk:
                            continue
                        file_obj.write(chunk)
                        transferred_bytes += len(chunk)
                        if callable(progress_callback):
                            progress_callback(transferred_bytes, total_bytes)
        except requests.RequestException as e:
            raise
        finally:
            session.close()
