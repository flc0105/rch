import os
from urllib.parse import quote

import requests

from client.config.config import FILE_TRANSFER_BASE_URL, UPLOAD_BASE_URL
# from client.runtime.sdk.context import get_script_grant_token


def _get_script_grant_token() -> str:
    """
    延迟读取 Script SDK 上下文，避免 client_api 与 sdk.artifact 形成初始化循环。
    """
    try:
        from client.runtime.sdk.context import get_script_grant_token
        return get_script_grant_token()
    except ImportError:
        return ''

class ClientApiError(RuntimeError):
    """
    Client 访问 Server Web API 时的统一异常。
    """
    pass


class ClientApiClient:
    """
    Client 端访问 Server Web API 的统一入口。

    这里只处理 Server Web API：
    - job catalog
    - agent build/download
    - background job report
    - artifact upload endpoint

    普通外部 HTTP 请求不要放进这里。
    """

    DEFAULT_TIMEOUT = 30

    def __init__(self, base_url: str = '', file_transfer_base_url: str = ''):
        self.base_url = (base_url or UPLOAD_BASE_URL).rstrip('/')
        self.file_transfer_base_url = (file_transfer_base_url or FILE_TRANSFER_BASE_URL).rstrip('/')

    def build_url(self, path_or_url: str) -> str:
        value = str(path_or_url or '').strip()
        if value.startswith('http://') or value.startswith('https://'):
            return value
        if value.startswith('/'):
            return self.base_url + value
        return self.base_url + '/' + value.lstrip('/')

    def normalize_server_url(self, path_or_url: str) -> str:
        return self.build_url(path_or_url)

    def build_file_transfer_url(self, path_or_url: str) -> str:
        value = str(path_or_url or '').strip()
        if value.startswith('http://') or value.startswith('https://'):
            return value
        if value.startswith('/'):
            return self.file_transfer_base_url + value
        return self.file_transfer_base_url + '/' + value.lstrip('/')

    def normalize_file_transfer_url(self, path_or_url: str) -> str:
        return self.build_file_transfer_url(path_or_url)

    def _should_attach_script_grant(self, url: str) -> bool:
        base_url = (self.base_url or '').rstrip('/')
        return bool(base_url and (url == base_url or url.startswith(base_url + '/')))

    def _build_headers(self, url: str, headers=None) -> dict:
        merged = dict(headers or {})
        token = _get_script_grant_token()
        if token and self._should_attach_script_grant(url):
            has_header = any(str(key).lower() == 'x-script-grant-token' for key in merged.keys())
            if not has_header:
                merged['X-Script-Grant-Token'] = token
        return merged

    def build_file_upload_url(self) -> str:
        return self.build_file_transfer_url('/api/files/upload')

    def try_parse_json(self, response):
        try:
            return response.json()
        except Exception:
            return None

    def _extract_response_error(self, response, fallback_message: str = '') -> str:
        payload = self.try_parse_json(response)
        if isinstance(payload, dict):
            message = str(payload.get('message') or '').strip()
            if message:
                return message

        text = str(getattr(response, 'text', '') or '').strip()
        if text:
            return text[:500]

        return fallback_message or f'HTTP {response.status_code}'

    def parse_json_response(self, response, *, expect_api_code: bool = True):
        payload = self.try_parse_json(response)
        if payload is None:
            payload = {}

        if response.status_code >= 400:
            raise ClientApiError(
                self._extract_response_error(
                    response,
                    fallback_message=f'HTTP {response.status_code}',
                )
            )

        if expect_api_code and isinstance(payload, dict):
            code = payload.get('code', 0)
            if code != 0:
                raise ClientApiError(str(payload.get('message') or 'Server API request failed'))

        return payload

    def request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        timeout=None,
        expect_api_code: bool = True,
        **kwargs,
    ):
        url = self.build_url(path_or_url)
        headers = self._build_headers(url, kwargs.pop('headers', None))
        response = requests.request(
            method,
            url,
            timeout=self.DEFAULT_TIMEOUT if timeout is None else timeout,
            headers=headers,
            **kwargs,
        )
        return self.parse_json_response(response, expect_api_code=expect_api_code)

    def get_json(self, path_or_url: str, *, timeout=None, expect_api_code: bool = True, **kwargs):
        return self.request_json(
            'GET',
            path_or_url,
            timeout=timeout,
            expect_api_code=expect_api_code,
            **kwargs,
        )

    def post_json(self, path_or_url: str, *, timeout=None, expect_api_code: bool = True, **kwargs):
        return self.request_json(
            'POST',
            path_or_url,
            timeout=timeout,
            expect_api_code=expect_api_code,
            **kwargs,
        )

    def get_data(self, path_or_url: str, *, timeout=None, **kwargs):
        payload = self.get_json(path_or_url, timeout=timeout, **kwargs)
        if not isinstance(payload, dict):
            return None
        return payload.get('data')

    def post_data(self, path_or_url: str, *, timeout=None, **kwargs):
        payload = self.post_json(path_or_url, timeout=timeout, **kwargs)
        if not isinstance(payload, dict):
            return None
        return payload.get('data')

    def list_jobs(self, *, timeout=10) -> list:
        data = self.get_data('/api/jobs/list', timeout=timeout)
        if isinstance(data, dict):
            jobs = data.get('jobs') or []
            return jobs if isinstance(jobs, list) else []
        if isinstance(data, list):
            return data
        return []

    def download_text(self, path_or_url: str, *, params=None, timeout=None) -> str:
        url = self.build_url(path_or_url)
        response = requests.get(
            url,
            params=params,
            timeout=self.DEFAULT_TIMEOUT if timeout is None else timeout,
            headers=self._build_headers(url),
        )

        if response.status_code >= 400:
            raise ClientApiError(
                self._extract_response_error(
                    response,
                    fallback_message=f'HTTP {response.status_code}',
                )
            )

        return response.text or ''

    def download_job(self, job_name: str, *, timeout=30) -> str:
        normalized_name = str(job_name or '').strip()
        if not normalized_name:
            raise ValueError('job name is required')

        text = self.download_text(
            '/api/jobs/download',
            params={'name': normalized_name},
            timeout=timeout,
        )
        if not text.strip():
            raise ClientApiError(f'Downloaded empty job: {normalized_name}')
        return text

    def build_agent_bundle(self, build_payload: dict, *, timeout=(15, 600)) -> dict:
        payload = self.post_json(
            '/api/agent/build',
            json=build_payload,
            timeout=timeout,
        )

        data = payload.get('data') if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}

        file_name = str(data.get('file_name') or '').strip()
        if not file_name:
            raise ClientApiError('Build bundle response missing file_name')

        download_url = str(data.get('download_url') or '').strip()
        if not download_url:
            download_url = self.build_url(f'/api/agent/download/{quote(file_name, safe="")}')
        else:
            download_url = self.normalize_server_url(download_url)

        data['file_name'] = file_name
        data['download_url'] = download_url
        return data

    def download_file(
        self,
        path_or_url: str,
        target_path: str,
        *,
        timeout=None,
        chunk_size: int = 64 * 1024,
        ensure_not_interrupted=None,
    ):
        url = self.normalize_server_url(path_or_url)
        temp_path = target_path + '.part'
        target_dir = os.path.dirname(target_path)

        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

        try:
            with requests.get(
                url,
                stream=True,
                timeout=self.DEFAULT_TIMEOUT if timeout is None else timeout,
                headers=self._build_headers(url),
            ) as response:
                response.raise_for_status()
                with open(temp_path, 'wb') as file_obj:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if ensure_not_interrupted is not None:
                            ensure_not_interrupted()
                        if not chunk:
                            continue
                        file_obj.write(chunk)

            os.replace(temp_path, target_path)
            return target_path
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            raise

    def post_background_job_report(self, payload: dict, *, timeout=10):
        return self.post_json(
            '/api/background-jobs/report',
            json=payload,
            timeout=timeout,
        )

    def post_device_event(self, payload: dict, *, timeout=10):
        return self.post_json(
            '/api/device-events',
            json=payload,
            timeout=timeout,
        )

    def upload_file_source(
        self,
        file_source,
        *,
        filename: str = '',
        form_data: dict | None = None,
        timeout=30,
    ):
        close_after = False

        if isinstance(file_source, str):
            file_obj = open(file_source, 'rb')
            close_after = True
            upload_name = filename or os.path.basename(file_source)
        else:
            file_obj = file_source
            upload_name = filename or getattr(file_obj, 'name', None) or 'upload.bin'

        try:
            try:
                file_obj.seek(0)
            except Exception:
                pass

            url = self.build_file_upload_url()
            return requests.post(
                url,
                files={
                    'file': (upload_name, file_obj),
                },
                data=form_data or {},
                timeout=timeout,
                headers=self._build_headers(url),
            )
        finally:
            if close_after:
                try:
                    file_obj.close()
                except Exception:
                    pass

    def upload_file(self, file_path: str, form_data: dict, *, timeout=30):
        return self.upload_file_source(
            file_path,
            filename=os.path.basename(file_path),
            form_data=form_data,
            timeout=timeout,
        )