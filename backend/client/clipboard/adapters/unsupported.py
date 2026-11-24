class UnsupportedClipboardAdapter:
    def __init__(self, platform_name: str):
        self.platform_name = platform_name or 'current platform'

    def get_capabilities(self) -> dict:
        return {'text': False, 'image': False, 'files': False}

    def get_snapshot(self) -> dict:
        raise RuntimeError(f'Clipboard is not supported on {self.platform_name}')

    def clear(self):
        raise RuntimeError(f'Clipboard is not supported on {self.platform_name}')

    def set_text(self, text: str):
        raise RuntimeError(f'Clipboard is not supported on {self.platform_name}')

    def set_image(self, image_path: str):
        raise RuntimeError(f'Clipboard is not supported on {self.platform_name}')

    def set_files(self, paths: list[str]):
        raise RuntimeError(f'Clipboard is not supported on {self.platform_name}')
