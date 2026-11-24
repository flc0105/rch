import time

from PIL import ImageChops

from client.screen.frame_strategies.base import ScreenFrameStrategy


class KeyframeDeltaFrameStrategy(ScreenFrameStrategy):
    """
    基于固定 Keyframe 的自包含差分策略。

    Delta 始终相对当前 Keyframe 计算，因此中间 Delta 可以丢弃；
    变化过大、分辨率变化或 Keyframe 超时都会直接发送新的完整 Keyframe。
    """

    name = 'keyframe_delta'
    KEYFRAME_INTERVAL_SECONDS = 2.0
    FULL_FRAME_AREA_RATIO = 0.50
    DELTA_PADDING = 8

    def __init__(self):
        self._seq = 0
        self._base_seq = 0
        self._base_image = None
        self._base_created_at = 0.0
        self._last_bbox = None
        self._last_patch = None
        self._quality = None

    def encode(self, image, quality: int):
        image = self._prepare_rgb(image)
        now = time.monotonic()

        if self._should_emit_keyframe(image, now) or quality != self._quality:
            return self._encode_keyframe(image, quality, now)

        bbox = ImageChops.difference(self._base_image, image).getbbox()
        if bbox is None:
            # A previous patch must be explicitly removed when the desktop
            # returns to the base, even if intermediate frames were skipped.
            if self._last_bbox is not None:
                return self._encode_keyframe(image, quality, now)
            return None

        left, top, right, bottom = bbox
        # 给 JPEG patch 留少量上下文，减少块边界处的视觉接缝。
        left = max(0, left - self.DELTA_PADDING)
        top = max(0, top - self.DELTA_PADDING)
        right = min(int(image.width), right + self.DELTA_PADDING)
        bottom = min(int(image.height), bottom + self.DELTA_PADDING)
        patch_width = max(0, right - left)
        patch_height = max(0, bottom - top)
        full_area = max(1, int(image.width) * int(image.height))
        patch_area = patch_width * patch_height

        if patch_area / full_area >= self.FULL_FRAME_AREA_RATIO:
            return self._encode_keyframe(image, quality, now)

        # Outside the bounding box both images equal the fixed base. Compare
        # only the cropped patch when its bounds match; avoid a second full
        # desktop scan or storing another full-sized screenshot.
        patch = image.crop((left, top, right, bottom))
        if bbox == self._last_bbox and ImageChops.difference(self._last_patch, patch).getbbox() is None:
            return None
        frame_bytes = self._encode_jpeg(patch, quality)
        self._seq += 1
        self._last_bbox = bbox
        self._last_patch = patch

        return {
            'strategy': self.name,
            'frame_type': 'delta',
            'frame_seq': self._seq,
            'base_seq': self._base_seq,
            'data': frame_bytes,
            'width': int(image.width),
            'height': int(image.height),
            'patch_x': int(left),
            'patch_y': int(top),
            'patch_width': int(patch_width),
            'patch_height': int(patch_height),
        }

    def _should_emit_keyframe(self, image, now: float) -> bool:
        if self._base_image is None:
            return True
        if self._base_image.size != image.size:
            return True
        return (now - self._base_created_at) >= self.KEYFRAME_INTERVAL_SECONDS

    def _encode_keyframe(self, image, quality: int, now: float):
        frame_bytes = self._encode_jpeg(image, quality)
        self._seq += 1
        self._base_seq = self._seq
        self._base_image = image.copy()
        self._last_bbox = None
        self._last_patch = None
        self._quality = quality
        self._base_created_at = now

        return {
            'strategy': self.name,
            'frame_type': 'keyframe',
            'frame_seq': self._seq,
            'base_seq': self._base_seq,
            'data': frame_bytes,
            'width': int(image.width),
            'height': int(image.height),
            'patch_x': 0,
            'patch_y': 0,
            'patch_width': int(image.width),
            'patch_height': int(image.height),
        }
