import io

from PIL import Image


class iOSClipboardAdapter:
    """Pythonista clipboard adapter; file clipboard is intentionally unsupported."""

    @staticmethod
    def _clipboard_module():
        import clipboard
        return clipboard

    def get_capabilities(self) -> dict:
        try:
            clipboard = self._clipboard_module()
        except Exception:
            return {'text': False, 'image': False, 'files': False}

        text_supported = (
            callable(getattr(clipboard, 'get', None))
            and callable(getattr(clipboard, 'set', None))
        )
        image_supported = callable(getattr(clipboard, 'get_image', None)) and callable(
            getattr(clipboard, 'set_image', None)
        )
        return {
            'text': text_supported,
            'image': image_supported,
            'files': False,
        }

    def get_snapshot(self) -> dict:
        clipboard = self._clipboard_module()

        get_image = getattr(clipboard, 'get_image', None)
        if callable(get_image):
            image = get_image()
            if image is not None:
                output = io.BytesIO()
                image.save(output, format='PNG')
                return {
                    'kind': 'image',
                    'data': output.getvalue(),
                    'format': 'png',
                    'width': int(image.width),
                    'height': int(image.height),
                }

        get_text = getattr(clipboard, 'get', None)
        if not callable(get_text):
            raise RuntimeError('Text clipboard is not available in Pythonista')

        text = get_text()
        if text:
            return {'kind': 'text', 'text': str(text)}
        return {'kind': 'empty'}

    def clear(self):
        from objc_util import ObjCClass, ns, on_main_thread

        @on_main_thread
        def clear_pasteboard():
            ObjCClass('UIPasteboard').generalPasteboard().setItems_(ns([]))

        clear_pasteboard()

    def set_text(self, text: str):
        clipboard = self._clipboard_module()
        set_text = getattr(clipboard, 'set', None)
        if not callable(set_text):
            raise RuntimeError('Text clipboard is not available in Pythonista')
        set_text(str(text or ''))

    def set_image(self, image_path: str):
        clipboard = self._clipboard_module()
        set_image = getattr(clipboard, 'set_image', None)
        if not callable(set_image):
            raise RuntimeError('Image clipboard is not available in Pythonista')

        image_class = Image.Image
        needs_legacy_tostring = (
                not hasattr(image_class, 'tostring')
                and callable(getattr(image_class, 'tobytes', None))
        )
        if needs_legacy_tostring:
            # Pythonista clipboard.set_image still uses Pillow's removed tostring().
            image_class.tostring = image_class.tobytes

        try:
            with Image.open(image_path) as image:
                image.load()
                set_image(image.copy(), format='png')
        finally:
            if needs_legacy_tostring:
                delattr(image_class, 'tostring')

    def set_files(self, paths: list[str]):
        raise RuntimeError('File clipboard is not supported on iOS/Pythonista')
