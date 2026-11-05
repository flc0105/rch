import os
import mimetypes
from fractions import Fraction

from core.utils.text_encoding import preview_text_file
from core.utils.zip_peek import ZipPeekService


class ArtifactPreviewService:
    """
    Artifact 预览服务。
    """

    IMAGE_EXIF_TAGS = {
        271: 'make',
        272: 'model',
        305: 'software',
        33434: 'exposure_time',
        33437: 'f_number',
        34855: 'iso',
        36867: 'datetime_original',
        37386: 'focal_length',
        37510: 'user_comment',
        40961: 'color_space',
        42036: 'lens_model',
    }

    def __init__(self, artifact_service):
        self.artifact_service = artifact_service

    def guess_preview_type(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1].lower()

        image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        text_exts = {
            '.txt', '.log', '.py', '.js', '.ts', '.json', '.xml', '.yaml', '.yml',
            '.ini', '.cfg', '.conf', '.md', '.csv', '.sql', '.bat', '.sh', '.html', '.css', '.ps1'
        }

        if ext in image_exts:
            return 'image'
        if ext in text_exts:
            return 'text'

        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            if mime_type.startswith('image/'):
                return 'image'
            if mime_type.startswith('text/'):
                return 'text'

        return 'unsupported'

    @staticmethod
    def _detect_file_signature(file_path: str) -> str:
        with open(file_path, 'rb') as f:
            head = f.read(16)
        if (head.startswith(b'\x89PNG\r\n\x1a\n')
                or head.startswith(b'\xff\xd8\xff')
                or head.startswith((b'GIF87a', b'GIF89a'))
                or head.startswith(b'BM')
                or (head.startswith(b'RIFF') and head[8:12] == b'WEBP')):
            return 'image'
        if head.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
            return 'archive'
        return ''

    def inspect_zip_artifact(self, artifact_id: str) -> dict:
        return ZipPeekService().inspect_zip(self.artifact_service.get_artifact_file_path(artifact_id))

    def read_zip_artifact_entry(self, artifact_id: str, entry_name: str) -> dict:
        return ZipPeekService().read_zip_text_entry(self.artifact_service.get_artifact_file_path(artifact_id), entry_name)

    def _normalize_image_info_value(self, value, tag=None):
        """
        将图片 EXIF 值转换为可读、可 JSON 序列化的基础类型
        """
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace')

        if isinstance(value, tuple):
            return [self._normalize_image_info_value(item, tag=tag) for item in value]

        if tag == 40961:
            return 'sRGB' if value == 1 else 'Uncalibrated'

        try:
            if isinstance(value, Fraction):
                if value.denominator == 1:
                    return value.numerator
                return float(value)
        except Exception:
            pass

        if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
            try:
                numerator = value.numerator
                denominator = value.denominator
                if denominator == 1:
                    return int(numerator)
                return float(value)
            except Exception:
                return str(value)

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        return str(value)

    def _build_image_info_payload(self, file_path: str, display_name: str, artifact: dict) -> dict | None:
        """
        基于 preview artifact 本地文件提取图片信息。
        注意：这里不让图片预览因为元信息提取失败而整体失败。
        """
        try:
            from PIL import Image
        except ImportError:
            return None

        try:
            with Image.open(file_path) as img:
                info = {
                    'name': os.path.basename(display_name),
                    'width': img.width,
                    'height': img.height,
                    'size': f'{img.width}x{img.height}',
                    'format': img.format,
                    'mode': img.mode,
                    'file_size_bytes': os.path.getsize(file_path),
                    'artifact_id': artifact.get('artifact_id', ''),
                }

                exif_data = None
                if hasattr(img, '_getexif'):
                    try:
                        exif_data = img._getexif()
                    except Exception:
                        exif_data = None

                if exif_data:
                    for tag, value in exif_data.items():
                        if tag in self.IMAGE_EXIF_TAGS:
                            info[self.IMAGE_EXIF_TAGS[tag]] = self._normalize_image_info_value(value, tag=tag)

                return info
        except Exception:
            return None

    def build_preview_payload(self, artifact_id: str) -> dict:
        artifact = self.artifact_service.registry_service.get_artifact_by_id(artifact_id)
        file_path = artifact.get('saved_path', '')
        display_name = artifact.get('original_name') or artifact.get('stored_name') or 'artifact'

        if not os.path.isfile(file_path):
            raise FileNotFoundError('file not found')

        preview_type = self._detect_file_signature(file_path)

        if preview_type == 'archive':
            return {
                'type': 'archive',
                'name': os.path.basename(display_name),
                'artifact_id': artifact.get('artifact_id', ''),
            }

        if preview_type == 'image':
            return {
                'type': 'image',
                'name': os.path.basename(display_name),
                'url': artifact.get('raw_url', ''),
                'artifact_id': artifact.get('artifact_id', ''),
                'image_info': self._build_image_info_payload(file_path, display_name, artifact),
            }

        if not preview_type:
            with open(file_path, 'rb') as file_obj:
                decoded = preview_text_file(file_obj, self.artifact_service.MAX_PREVIEW_TEXT_BYTES)
            if decoded['encoding'] == 'unknown':
                return {
                    'type': 'unsupported',
                    'name': os.path.basename(display_name),
                    'artifact_id': artifact.get('artifact_id', ''),
                }
            text = decoded['content']

            return {
                'type': 'text',
                'name': os.path.basename(display_name),
                'content': text,
                'encoding': decoded['encoding'],
                'editable': decoded['editable'],
                'truncated': decoded['truncated'],
                'artifact_id': artifact.get('artifact_id', ''),
            }

        return {
            'type': 'unsupported',
            'name': os.path.basename(display_name),
            'artifact_id': artifact.get('artifact_id', ''),
        }