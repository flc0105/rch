import os
from dataclasses import dataclass

from client.config import runtime_config
from core.utils.logger import logger
from client.runtime.temp_workspace import make_client_temp_dir, cleanup_temp_path


@dataclass
class PreviewUploadFile:
    """
    preview_path 上传前的文件准备结果。
    """

    upload_path: str
    cleanup_dir: str = ''
    extra: dict | None = None

    @property
    def is_compressed(self) -> bool:
        return bool(self.extra and self.extra.get('compress') is True)


class PreviewImageService:
    """
    前端文件预览专用图片压缩服务。

    注意：
    - 只给 preview_path 使用
    - 不影响 download_path / download_paths
    - 不影响 screenshot / webcam / pickupload 等平台命令
    - 启用压缩时，所有支持的图片预览统一转为 JPEG；透明图片会先铺白底
    - PIL 不存在或图片无法处理时，静默回退为原文件上传，只写本地日志
    """

    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tif', '.tiff'
    }

    def __init__(self):
        self.quality = self.get_configured_quality()

    def is_enabled(self) -> bool:
        return bool(getattr(runtime_config, 'PREVIEW_IMAGE_COMPRESS_ENABLED', False))

    def get_configured_quality(self) -> int:
        return self.normalize_quality(
            getattr(runtime_config, 'PREVIEW_IMAGE_COMPRESS_QUALITY', 75)
        )

    def normalize_quality(self, value) -> int:
        try:
            quality = int(value)
        except Exception:
            quality = 75

        if quality < 1:
            return 1
        if quality > 95:
            return 95
        return quality

    def prepare_upload_file(self, file_path: str) -> PreviewUploadFile:
        """
        根据本地配置决定 preview 图片是否压缩。
        """
        if not self.is_enabled():
            return PreviewUploadFile(upload_path=file_path)

        if not self._looks_like_image_path(file_path):
            return PreviewUploadFile(upload_path=file_path)

        self.quality = self.get_configured_quality()

        try:
            from PIL import Image, ImageOps
        except Exception as e:
            logger.warning(f'Preview image compression skipped because PIL is unavailable: {e}')
            return PreviewUploadFile(upload_path=file_path)

        temp_dir = ''
        try:
            original_size = os.path.getsize(file_path)
            if original_size <= 0:
                return PreviewUploadFile(upload_path=file_path)

            image = Image.open(file_path)
            image = ImageOps.exif_transpose(image)

            base_name = os.path.splitext(os.path.basename(file_path))[0] or 'preview'
            temp_dir = make_client_temp_dir('preview_temp', prefix='preview_')
            output_path = os.path.join(temp_dir, f'{base_name}_preview.jpg')

            self._save_compressed_image(image, output_path)
            compressed_size = os.path.getsize(output_path)

            if compressed_size <= 0:
                self._cleanup_dir(temp_dir)
                return PreviewUploadFile(upload_path=file_path)

            if compressed_size >= original_size:
                logger.info(
                    'Preview image compression skipped because compressed file is not smaller: '
                    f'{file_path} original={original_size} compressed={compressed_size}'
                )
                self._cleanup_dir(temp_dir)
                return PreviewUploadFile(upload_path=file_path)

            logger.info(
                'Preview image compressed: '
                f'{file_path} original={original_size} compressed={compressed_size} quality={self.quality}'
            )
            return PreviewUploadFile(
                upload_path=output_path,
                cleanup_dir=temp_dir,
                extra={
                    'compress': True,
                    'quality': self.quality,
                    'format': 'JPEG',
                },
            )
        except Exception as e:
            if temp_dir:
                self._cleanup_dir(temp_dir)
            logger.warning(f'Preview image compression failed, fallback to original file: {file_path}, error={e}')
            return PreviewUploadFile(upload_path=file_path)

    def cleanup_upload_file(self, prepared: PreviewUploadFile):
        if not prepared or not prepared.cleanup_dir:
            return
        self._cleanup_dir(prepared.cleanup_dir)

    def _looks_like_image_path(self, file_path: str) -> bool:
        suffix = os.path.splitext(str(file_path or '').lower())[1]
        return suffix in self.IMAGE_EXTENSIONS

    def _has_alpha(self, image) -> bool:
        if image.mode in ('RGBA', 'LA'):
            return True
        if image.mode == 'P' and 'transparency' in image.info:
            return True
        return False

    def _save_compressed_image(self, image, output_path: str):
        image = self._prepare_jpeg_image(image)
        image.save(
            output_path,
            format='JPEG',
            quality=self.quality,
        )

    def _prepare_jpeg_image(self, image):
        if self._has_alpha(image):
            return self._flatten_alpha_to_background(image, (255, 255, 255))
        if image.mode not in ('RGB', 'L'):
            return image.convert('RGB')
        return image

    def _flatten_alpha_to_background(self, image, background_rgb):
        from PIL import Image

        rgba = image.convert('RGBA')
        background = Image.new('RGBA', rgba.size, background_rgb + (255,))
        background.alpha_composite(rgba)
        return background.convert('RGB')

    def _cleanup_dir(self, temp_dir: str):
        cleanup_temp_path(temp_dir)
