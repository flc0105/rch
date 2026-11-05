from pathlib import Path

import pytest

from client.config import runtime_config
from client.commands.common.services.filesystem.preview_image_service import PreviewImageService


def _save_png(path: Path, image):
    image.save(path, format='PNG')
    return path


def _save_jpeg(path: Path, image, quality=92):
    image.save(path, format='JPEG', quality=quality)
    return path


@pytest.fixture
def runtime_preview_enabled(monkeypatch):
    monkeypatch.setattr(runtime_config, 'PREVIEW_IMAGE_COMPRESS_ENABLED', True)
    monkeypatch.setattr(runtime_config, 'PREVIEW_IMAGE_COMPRESS_QUALITY', 75)


def test_transparent_png_preview_is_flattened_to_jpeg(tmp_path, runtime_preview_enabled):
    Pillow = pytest.importorskip('PIL.Image')
    Image = Pillow

    source = tmp_path / 'transparent.png'
    image = Image.effect_noise((640, 360), 100).convert('L').convert('RGBA')
    alpha = Image.new('L', image.size, 0)
    for x in range(120, 520):
        for y in range(80, 280):
            alpha.putpixel((x, y), 255)
    image.putalpha(alpha)
    _save_png(source, image)

    service = PreviewImageService()
    prepared = service.prepare_upload_file(str(source))
    try:
        assert prepared.is_compressed is True
        assert prepared.extra['format'] == 'JPEG'
        assert prepared.upload_path.endswith('.jpg')
        preview = Image.open(prepared.upload_path)
        assert preview.format == 'JPEG'
        assert preview.mode == 'RGB'
        corner = preview.getpixel((2, 2))
        assert all(channel >= 240 for channel in corner)
    finally:
        service.cleanup_upload_file(prepared)


def test_quality_controls_jpeg_preview_size_for_png_inputs(tmp_path, runtime_preview_enabled, monkeypatch):
    Pillow = pytest.importorskip('PIL.Image')
    Image = Pillow

    source = tmp_path / 'photo_like.png'
    image = Image.effect_noise((640, 360), 120).convert('RGB')
    _save_png(source, image)

    low_quality_service = PreviewImageService()
    monkeypatch.setattr(runtime_config, 'PREVIEW_IMAGE_COMPRESS_QUALITY', 20)
    low = low_quality_service.prepare_upload_file(str(source))

    high_quality_service = PreviewImageService()
    monkeypatch.setattr(runtime_config, 'PREVIEW_IMAGE_COMPRESS_QUALITY', 90)
    high = high_quality_service.prepare_upload_file(str(source))

    try:
        assert low.is_compressed is True
        assert high.is_compressed is True
        assert low.upload_path.endswith('.jpg')
        assert high.upload_path.endswith('.jpg')
        low_size = Path(low.upload_path).stat().st_size
        high_size = Path(high.upload_path).stat().st_size
        assert low_size < high_size
    finally:
        low_quality_service.cleanup_upload_file(low)
        high_quality_service.cleanup_upload_file(high)


def test_small_jpeg_preview_falls_back_to_original_when_not_smaller(tmp_path, runtime_preview_enabled):
    Pillow = pytest.importorskip('PIL.Image')
    Image = Pillow

    source = tmp_path / 'tiny.jpg'
    image = Image.new('RGB', (8, 8), (120, 200, 80))
    _save_jpeg(source, image, quality=1)

    service = PreviewImageService()
    prepared = service.prepare_upload_file(str(source))
    assert prepared.is_compressed is False
    assert prepared.upload_path == str(source)
    assert prepared.cleanup_dir == ''
