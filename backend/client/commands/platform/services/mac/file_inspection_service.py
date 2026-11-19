import os


class MacFileInspectionService:
    """
    macOS 文件覆写删除能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def secure_delete_file(self, path):
        """安全删除文件（覆写后删除）"""
        try:
            target = self.owner.path_resolver.resolve_target_path(path)
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'

            if os.path.isdir(target):
                return 0, 'Use rmdir for directories'

            # 获取文件大小
            size = os.path.getsize(target)

            self.owner.emit_chunk(f'Shredding {target} ({size} bytes)')

            # 多次覆写
            with open(target, 'r+b') as f:
                for _ in range(3):
                    self.owner._checkpoint()
                    f.seek(0)
                    # 第一次: 0x00
                    f.write(b'\x00' * size)
                    f.flush()

                    self.owner._checkpoint()
                    f.seek(0)
                    # 第二次: 0xFF
                    f.write(b'\xFF' * size)
                    f.flush()

                    self.owner._checkpoint()
                    f.seek(0)
                    # 第三次: 随机数据
                    f.write(os.urandom(size))
                    f.flush()

            # 最后删除
            os.remove(target)

            return 1, f'File securely deleted: {target}'

        except Exception as e:
            return 0, f'Failed to shred file: {e}'
