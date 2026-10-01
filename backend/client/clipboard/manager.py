import json
import os
import shutil
import uuid
from client.runtime.temp_workspace import make_client_temp_dir, cleanup_temp_path
from pathlib import Path

import requests
from PIL import Image

from client.clipboard.adapters.ios import iOSClipboardAdapter
from client.clipboard.adapters.macos import MacOSClipboardAdapter
from client.clipboard.adapters.unsupported import UnsupportedClipboardAdapter
from client.clipboard.adapters.windows import WindowsClipboardAdapter
from client.http.client_api import ClientApiClient
from core.device.local_identity import get_local_identity
from core.protocol.message_types import MSG_TYPE_CLIPBOARD_RESULT


class ClipboardManager:
    # Clipboard staging 是内部实现目录，不进入 client profile/config。
    DEFAULT_STAGING_DIR = '~/.rch/clipboard_staging'

    def __init__(self, connection):
        self.connection = connection
        self.client_api = ClientApiClient()
        self._os_alias = get_local_identity().os_alias
        self._macos_console_identity = self._get_macos_console_identity()
        self.staging_dir = self._resolve_staging_dir(self.DEFAULT_STAGING_DIR)
        self.adapter = self._build_adapter()
        self._clear_staging_on_startup()

    def _build_adapter(self):
        if self._os_alias == 'win':
            return WindowsClipboardAdapter()
        if self._os_alias == 'mac':
            return MacOSClipboardAdapter()
        if self._os_alias == 'ios':
            return iOSClipboardAdapter()
        return UnsupportedClipboardAdapter(self._os_alias)

    def get_capabilities(self) -> dict:
        caps = self.adapter.get_capabilities()
        return {
            'platform': self._os_alias,
            'text': bool(caps.get('text')),
            'image': bool(caps.get('image')),
            'files': bool(caps.get('files')),
        }

    def handle_get(self, request_id: str, mode: str = 'content'):
        request_id = str(request_id or '').strip()
        if not request_id:
            return
        try:
            if str(mode or '').strip().lower() == 'capabilities':
                payload = {
                    'kind': 'capabilities',
                    'capabilities': self.get_capabilities(),
                }
            else:
                payload = self._materialize_snapshot(
                    self.adapter.get_snapshot()
                )
                payload['capabilities'] = self.get_capabilities()

            self._send_result(
                request_id,
                'get',
                True,
                payload=payload,
            )
        except Exception as e:
            self._send_result(
                request_id,
                'get',
                False,
                error=str(e),
            )

    def handle_set(self, request_id: str, payload: dict):
        request_id = str(request_id or '').strip()
        if not request_id:
            return

        try:
            normalized = payload if isinstance(payload, dict) else {}
            kind = str(
                normalized.get('kind') or ''
            ).strip().lower()

            if kind == 'text':
                self.adapter.set_text(
                    str(normalized.get('text') or '')
                )

            elif kind == 'image':
                items = (
                    normalized.get('items')
                    if isinstance(normalized.get('items'), list)
                    else []
                )
                paths = self._download_staged_items(
                    request_id,
                    items,
                )

                if not paths:
                    raise ValueError('Image payload is empty')

                self.adapter.set_image(paths[0])

            elif kind == 'files':
                items = (
                    normalized.get('items')
                    if isinstance(normalized.get('items'), list)
                    else []
                )
                roots = (
                    normalized.get('roots')
                    if isinstance(normalized.get('roots'), list)
                    else []
                )
                paths = self._download_staged_items(
                    request_id,
                    items,
                    roots=roots,
                )

                if not paths:
                    raise ValueError('File payload is empty')

                self.adapter.set_files(paths)

            else:
                raise ValueError(
                    f'Unsupported clipboard payload: '
                    f'{kind or "empty"}'
                )

            self._send_result(
                request_id,
                'set',
                True,
                payload={
                    'kind': kind,
                    'capabilities': self.get_capabilities(),
                },
            )

        except Exception as e:
            self._send_result(
                request_id,
                'set',
                False,
                error=str(e),
            )

    def _materialize_snapshot(self, snapshot: dict) -> dict:
        kind = str(
            (snapshot or {}).get('kind') or 'empty'
        ).strip().lower()

        if kind == 'text':
            return {
                'kind': 'text',
                'text': str(snapshot.get('text') or ''),
            }

        if kind == 'image':
            raw = snapshot.get('data') or b''

            if not raw:
                return {'kind': 'empty'}

            image_format = str(
                snapshot.get('format') or 'png'
            ).lower()

            if image_format != 'png':
                raw = self._convert_image_to_png(raw)

            artifact = self._upload_bytes_artifact(
                raw,
                filename=(
                    f'clipboard_'
                    f'{uuid.uuid4().hex[:8]}.png'
                ),
                category='clipboard_image',
                extra={
                    'clipboard_kind': 'image',
                },
            )

            return {
                'kind': 'image',
                'artifact': artifact,
            }

        if kind == 'files':
            paths = (
                snapshot.get('paths')
                if isinstance(snapshot.get('paths'), list)
                else []
            )

            files = []

            for path in paths:
                if not path:
                    continue

                abs_path = os.path.abspath(path)
                if not os.path.exists(abs_path):
                    continue

                is_directory = os.path.isdir(abs_path)
                try:
                    size = 0 if is_directory else int(os.path.getsize(abs_path))
                except OSError:
                    size = 0

                files.append({
                    'path': abs_path,
                    'name': (
                        os.path.basename(abs_path.rstrip(os.sep))
                        or abs_path
                    ),
                    'size': size,
                    'is_directory': is_directory,
                })

            return {
                'kind': 'files',
                'files': files,
            }

        return {'kind': 'empty'}

    def _upload_bytes_artifact(
        self,
        data: bytes,
        *,
        filename: str,
        category: str,
        extra: dict,
    ) -> dict:
        temp_dir = make_client_temp_dir(
            'clipboard_temp',
            prefix='upload_',
        )

        try:
            path = os.path.join(
                temp_dir,
                filename,
            )

            with open(path, 'wb') as file_obj:
                file_obj.write(data)

            return self._upload_file_artifact(
                path,
                filename=filename,
                category=category,
                extra=extra,
            )

        finally:
            cleanup_temp_path(temp_dir)

    def _upload_file_artifact(
        self,
        path: str,
        *,
        filename: str,
        category: str,
        extra: dict,
    ) -> dict:
        client_id = str(
            getattr(
                self.connection,
                'client_id',
                '',
            )
            or ''
        )

        form = {
            'artifact_type': 'files',
            'category': category,
            'client_id': client_id,
            'extra': json.dumps(
                extra or {},
                ensure_ascii=False,
            ),
        }

        with open(path, 'rb') as file_obj:
            response = requests.post(
                self.client_api.build_file_upload_url(),
                files={
                    'file': (
                        filename,
                        file_obj,
                    ),
                },
                data=form,
                timeout=(15, 60 * 60),
            )

        payload = self.client_api.parse_json_response(
            response
        )

        data = (
            payload.get('data')
            if isinstance(payload, dict)
            else None
        )

        if (
            not isinstance(data, dict)
            or not data.get('artifact_id')
        ):
            raise RuntimeError(
                'Clipboard artifact upload did not '
                'return artifact metadata'
            )

        return data

    def _download_staged_items(
        self,
        request_id: str,
        items: list[dict],
        *,
        roots: list[str] | None = None,
    ) -> list[str]:
        request_dir = os.path.join(
            self.staging_dir,
            self._safe_component(request_id),
        )

        # macOS 文件剪贴板必须让桌面登录用户能直接访问源文件。
        self._ensure_staging_directory(request_dir)

        if roots is not None:
            for item in items:
                if not isinstance(item, dict):
                    continue

                relative_path = self._safe_relative_path(
                    item.get('path')
                    or item.get('name')
                    or ''
                )
                if not relative_path:
                    continue

                target_path = os.path.join(
                    request_dir,
                    *relative_path.split('/'),
                )
                item_type = str(
                    item.get('type') or 'file'
                ).strip().lower()

                if item_type == 'directory':
                    self._ensure_staging_directory(target_path)
                    continue

                url = str(
                    item.get('url') or ''
                ).strip()
                if not url:
                    continue

                self._ensure_staging_directory(
                    os.path.dirname(target_path)
                )
                self.client_api.download_file(
                    url,
                    target_path,
                    timeout=(15, 60 * 60),
                )

                # Client 可能由 root 启动，文件最终要交给 GUI 用户读取。
                self._prepare_staged_path_for_console_user(
                    target_path
                )

            root_paths = []
            seen_roots = set()

            for root in roots:
                relative_root = self._safe_relative_path(root)
                if not relative_root or relative_root in seen_roots:
                    continue

                seen_roots.add(relative_root)
                root_path = os.path.join(
                    request_dir,
                    *relative_root.split('/'),
                )
                if not os.path.exists(root_path):
                    continue

                self._prepare_staged_path_for_console_user(
                    root_path
                )
                root_paths.append(root_path)

            return root_paths

        paths = []
        used_names = set()

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            url = str(
                item.get('url') or ''
            ).strip()

            if not url:
                continue

            original = self._safe_component(
                item.get('name')
                or f'clipboard_{index + 1}.bin'
            )

            name = self._unique_name(
                original,
                used_names,
            )

            used_names.add(name)

            target_path = os.path.join(
                request_dir,
                name,
            )

            self.client_api.download_file(
                url,
                target_path,
                timeout=(15, 60 * 60),
            )

            # Client 可能由 root 启动，文件最终要交给 GUI 用户读取。
            self._prepare_staged_path_for_console_user(
                target_path
            )

            paths.append(target_path)

        return paths

    def _clear_staging_on_startup(self):
        try:
            if os.path.isdir(self.staging_dir):
                shutil.rmtree(
                    self.staging_dir,
                    ignore_errors=True,
                )

            self._ensure_staging_directory(
                self.staging_dir
            )

        except Exception:
            pass

    def _get_macos_console_identity(self):
        if self._os_alias != 'mac':
            return None

        try:
            import pwd

            console_stat = os.stat(
                '/dev/console'
            )

            uid = int(console_stat.st_uid)

            if uid <= 0:
                return None

            user = pwd.getpwuid(uid)

            username = str(
                user.pw_name or ''
            ).strip()

            if (
                not username
                or username in {
                    'root',
                    'loginwindow',
                    '_mbsetupuser',
                }
            ):
                return None

            return {
                'uid': uid,
                'gid': int(user.pw_gid),
                'home': str(
                    user.pw_dir or ''
                ).strip(),
            }

        except Exception:
            return None

    def _resolve_staging_dir(
        self,
        configured_path: str,
    ) -> str:
        configured = (
            str(configured_path or '').strip()
            or self.DEFAULT_STAGING_DIR
        )

        identity = self._macos_console_identity

        # macOS 上 "~" 表示当前 GUI 用户，而不是后台 Client 用户。
        if (
            self._os_alias == 'mac'
            and identity
            and configured.startswith('~')
        ):
            home = str(
                identity.get('home') or ''
            ).strip()

            if home:
                if configured == '~':
                    return os.path.abspath(home)

                if configured.startswith('~/'):
                    return os.path.abspath(
                        os.path.join(
                            home,
                            configured[2:],
                        )
                    )

        return os.path.abspath(
            os.path.expanduser(configured)
        )

    def _ensure_staging_directory(
        self,
        directory: str,
    ):
        directory = os.path.abspath(directory)

        identity = self._macos_console_identity

        home = (
            os.path.abspath(
                str(
                    (identity or {}).get('home')
                    or ''
                )
            )
            if identity
            else ''
        )

        if (
            self._os_alias == 'mac'
            and identity
            and home
        ):
            try:
                if (
                    os.path.commonpath(
                        [home, directory]
                    )
                    == home
                ):
                    relative = os.path.relpath(
                        directory,
                        home,
                    )

                    current = home

                    for component in relative.split(
                        os.sep
                    ):
                        if (
                            not component
                            or component == '.'
                        ):
                            continue

                        current = os.path.join(
                            current,
                            component,
                        )

                        os.makedirs(
                            current,
                            exist_ok=True,
                        )

                        self._prepare_staged_path_for_console_user(
                            current
                        )

                    return

            except Exception:
                pass

        os.makedirs(
            directory,
            exist_ok=True,
        )

        self._prepare_staged_path_for_console_user(
            directory
        )

    def _prepare_staged_path_for_console_user(
        self,
        path: str,
    ):
        if (
            self._os_alias != 'mac'
            or not os.path.exists(path)
        ):
            return

        identity = self._macos_console_identity

        if not identity:
            return

        # root Client 创建的 staging 文件直接交给桌面用户。
        try:
            if (
                hasattr(os, 'geteuid')
                and os.geteuid() == 0
            ):
                os.chown(
                    path,
                    int(identity['uid']),
                    int(identity['gid']),
                )
        except Exception:
            pass

        # 至少确保 owner 自己可以访问文件/目录。
        try:
            mode = (
                os.stat(path).st_mode
                & 0o777
            )

            required = (
                0o700
                if os.path.isdir(path)
                else 0o600
            )

            os.chmod(
                path,
                mode | required,
            )

        except Exception:
            pass

    def _send_result(
        self,
        request_id: str,
        operation: str,
        ok: bool,
        *,
        payload=None,
        error: str = '',
    ):
        self.connection.send({
            'type': MSG_TYPE_CLIPBOARD_RESULT,
            'clipboard_request_id': request_id,
            'operation': operation,
            'ok': bool(ok),
            'payload': (
                payload
                if isinstance(payload, dict)
                else {}
            ),
            'error': str(error or ''),
        })

    @staticmethod
    def _convert_image_to_png(
        raw: bytes,
    ) -> bytes:
        import io

        image = Image.open(
            io.BytesIO(raw)
        )

        output = io.BytesIO()

        image.save(
            output,
            format='PNG',
        )

        return output.getvalue()

    @classmethod
    def _safe_relative_path(
        cls,
        value: str,
    ) -> str:
        parts = []

        for component in str(value or '').replace('\\', '/').split('/'):
            component = component.strip()
            if not component or component in {'.', '..'}:
                continue
            parts.append(cls._safe_component(component))

        return '/'.join(parts)

    @staticmethod
    def _safe_component(
        value: str,
    ) -> str:
        value = os.path.basename(
            str(value or '')
            .strip()
            .replace('\\', '/')
        )

        return (
            ''.join(
                ch
                for ch in value
                if ch
                not in '<>:"/\\|?*\x00'
            )
            or 'clipboard_item'
        )

    @staticmethod
    def _unique_name(
        name: str,
        used_names: set[str],
    ) -> str:
        if name not in used_names:
            return name

        stem, ext = os.path.splitext(name)

        index = 1

        while (
            f'{stem}_{index}{ext}'
            in used_names
        ):
            index += 1

        return f'{stem}_{index}{ext}'