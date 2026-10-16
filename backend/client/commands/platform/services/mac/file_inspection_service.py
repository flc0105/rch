import json
import os
import time
from pathlib import Path

from core.utils.formatting import format_dict, format_table, get_size


class MacFileInspectionService:
    """
    macOS 文件安全处理、文件内容探查和本地包检查能力。
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

            self.owner._send_interim_result(1, f'Shredding {target} ({size} bytes)', 0)

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

    def acmd_sqlite_query(self, args_dict, payload=None):
        """只读 SQLite 查询"""
        try:
            import sqlite3

            db_path = args_dict.get('db', '')
            query = args_dict.get('query', '')
            output_json = args_dict.get('json', False)

            if not db_path or not query:
                return 0, 'db and query are required'

            if not os.path.isfile(db_path):
                return 0, f'Database file not found: {db_path}'

            # 只读模式打开
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(query)
            rows = cursor.fetchall()

            result = [dict(row) for row in rows]
            conn.close()

            if output_json:
                return 1, json.dumps(result, ensure_ascii=False, indent=2)

            if not result:
                return 1, 'No results'

            headers = list(result[0].keys())
            data = [[str(row[h]) for h in headers] for row in result[:100]]

            return 1, format_table(headers, data)

        except Exception as e:
            error_name = e.__class__.__name__
            if error_name == 'Error':
                return 0, f'SQLite error: {e}'
            return 0, f'Query failed: {e}'

    def acmd_image_info(self, args_dict, payload=None):
        """获取图片信息"""
        try:
            from fractions import Fraction

            from PIL import Image

            def _normalize_exif_value(value, tag=None):
                """
                将 EXIF 值转换为可读、可 JSON 序列化的基础类型
                """
                if isinstance(value, bytes):
                    return value.decode('utf-8', errors='replace')

                if isinstance(value, tuple):
                    return [_normalize_exif_value(item, tag=tag) for item in value]

                if tag == 40961:
                    return 'sRGB' if value == 1 else 'Uncalibrated'

                # 兼容 Pillow 的 IFDRational / 其他 Rational 类型
                try:
                    if isinstance(value, Fraction):
                        if value.denominator == 1:
                            return value.numerator
                        return float(value)
                except Exception:
                    pass

                # 某些 IFDRational 不是 Fraction 子类，这里再兜一层
                if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
                    try:
                        numerator = value.numerator
                        denominator = value.denominator
                        if denominator == 1:
                            return int(numerator)
                        return float(value)
                    except Exception:
                        return str(value)

                # 兜底：保证 json.dumps 不炸
                if isinstance(value, (str, int, float, bool)) or value is None:
                    return value

                return str(value)

            img_path = args_dict.get('path', '')
            output_json = args_dict.get('json', False)

            if not img_path:
                return 0, 'path is required'

            if not os.path.isfile(img_path):
                return 0, f'File not found: {img_path}'

            img = Image.open(img_path)

            info = {
                'path': img_path,
                'width': img.width,
                'height': img.height,
                'size': f'{img.width}x{img.height}',
                'format': img.format,
                'mode': img.mode,
                'file_size': get_size(os.path.getsize(img_path))
            }

            # 获取 EXIF 信息
            exif_tags = {
                271: 'make',
                272: 'model',
                42036: 'lens_model',
                33434: 'exposure_time',
                33437: 'f_number',
                34855: 'iso',
                36867: 'datetime_original',
                37386: 'focal_length',
                305: 'software',
                37510: 'user_comment',
                40961: 'color_space',
            }

            if hasattr(img, '_getexif') and img._getexif():
                raw_exif = img._getexif()
                for tag, value in raw_exif.items():
                    if tag in exif_tags:
                        info[exif_tags[tag]] = _normalize_exif_value(value, tag=tag)

            img.close()

            if output_json:
                return 1, json.dumps(info, ensure_ascii=False, indent=2)

            return 1, format_dict(info, width=30)

        except ImportError:
            return 0, 'PIL not installed, install with: pip install Pillow'
        except Exception as e:
            return 0, f'Failed to get image info: {e}'

    def acmd_import_check(self, args_dict, payload=None):
        """检查 Python 包是否可以导入"""
        try:
            import importlib
            import importlib.metadata

            module_name = args_dict.get('module', '')

            if not module_name:
                return 0, 'module name is required'

            result = {
                'module': module_name,
                'importable': False,
                'module_path': None,
                'module_version': None,
                'package_name': None,
                'package_version': None,
                'package_dependencies': []
            }

            try:
                module = importlib.import_module(module_name)
                result['importable'] = True
                result['module_path'] = getattr(module, '__file__', None)

                for attr in ['__version__', 'version', 'VERSION']:
                    if hasattr(module, attr):
                        result['module_version'] = str(getattr(module, attr))
                        break

                if result['module_path']:
                    module_path = Path(result['module_path']).resolve()
                    for dist in importlib.metadata.distributions():
                        try:
                            dist_files = list(dist.files or [])
                            for file in dist_files:
                                if str(module_path).endswith(str(file)):
                                    result['package_name'] = dist.metadata['Name']
                                    result['package_version'] = dist.version
                                    result['package_dependencies'] = [str(req) for req in dist.requires or []]
                                    break
                            if result['package_name']:
                                break
                        except Exception:
                            continue

            except ImportError as e:
                result['error'] = str(e)

            return 1, format_dict(result, width=24)

        except Exception as e:
            return 0, f'Check failed: {e}'

    def acmd_archive_peek(self, args_dict, payload=None):
        """查看压缩包内容"""
        try:
            import tarfile
            import zipfile

            archive_path = args_dict.get('path', '')
            limit = args_dict.get('limit', 50)

            if not archive_path:
                return 0, 'path is required'

            if not os.path.isfile(archive_path):
                return 0, f'File not found: {archive_path}'

            entries = []

            # ZIP
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for info in zf.infolist()[:limit]:
                        entries.append({
                            'name': info.filename,
                            'size': get_size(info.file_size),
                            'compressed': get_size(info.compress_size),
                            'date': f'{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d}'
                        })

            # TAR
            elif tarfile.is_tarfile(archive_path):
                with tarfile.open(archive_path, 'r') as tf:
                    for info in tf.getmembers()[:limit]:
                        entries.append({
                            'name': info.name,
                            'size': get_size(info.size),
                            'type': 'dir' if info.isdir() else 'file',
                            'date': time.strftime('%Y-%m-%d', time.localtime(info.mtime))
                        })
            else:
                return 0, 'Unsupported archive format'

            headers = ['Name', 'Size', 'Date']
            data = [[e['name'], str(e['size']), e.get('date', '-')] for e in entries]

            result = format_table(headers, data)

            if len(entries) >= limit:
                result += f'\n... and more (limited to {limit})'

            return 1, result

        except Exception as e:
            return 0, f'Failed to peek archive: {e}'