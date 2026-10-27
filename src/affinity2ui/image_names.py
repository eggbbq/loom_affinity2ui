"""Short, portable image names with durable path-based collision detection."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import unicodedata


SCHEME = 'blake2b64-base36-v1'
ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'


def normalize_path(value):
    value = unicodedata.normalize('NFC', str(value).replace('\\', '/'))
    if (not value or value.startswith('/') or re.match(r'^[A-Za-z]:', value)
            or any(part in ('', '.', '..') for part in value.split('/'))
            or PurePosixPath(value).suffix.lower() != '.png'):
        raise ValueError(f'无效图片相对路径：{value}')
    return value


def path_digest(path, size=8):
    return hashlib.blake2b(path.encode('utf-8'), digest_size=size).digest()


def flat_image_name(path, digest_size=8):
    path = normalize_path(path)
    number = int.from_bytes(path_digest(path, digest_size), 'big')
    encoded = ''
    while number:
        number, remainder = divmod(number, 36)
        encoded = ALPHABET[remainder] + encoded
    encoded = encoded.zfill(math.ceil(digest_size * 8 / math.log2(36)))
    name = f'{PurePosixPath(path).stem}@{encoded}.png'
    if len(name.encode('utf-8')) > 255:
        raise ValueError(f'图片名超过文件系统长度：{path}')
    return name


class ImageNames:
    """Reserve all recorded names, keeping existing short names stable."""
    def __init__(self, records=None, images=None):
        self.paths = {}
        self.occupied = {}
        manifests = sorted(Path(records).glob('*/affinity.json')) if records else []
        for manifest in manifests:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            for item in data.get('images', []):
                path = normalize_path(item['sourcePath'])
                name = item['file']
                if Path(name).name != name or not name.endswith('.png'):
                    raise ValueError(f'无效图片记录文件名：{name}')
                key = name.casefold()
                if key in self.occupied and self.occupied[key] != path:
                    raise ValueError(f'不同原路径占用了同一图片名：{name}')
                self.occupied[key] = path
                if data.get('imageNaming') == SCHEME and re.fullmatch(
                        re.escape(PurePosixPath(path).stem) + r'@[0-9a-z]{13,}\.png', name):
                    self.paths[path] = name
        if images:
            for image in Path(images).iterdir() if Path(images).is_dir() else ():
                if image.name.endswith(('.png', '.png.meta')):
                    name = image.name.removesuffix('.meta')
                    self.occupied.setdefault(name.casefold(), None)

    def name(self, path):
        path = normalize_path(path)
        if path in self.paths:
            return self.paths[path]
        # Only the new path grows after a collision. Existing resource names
        # and references are unaffected; the manifest remembers the choice.
        for size in (8, 10, 12, 16, 32):
            name = flat_image_name(path, size)
            key = name.casefold()
            if key not in self.occupied or self.occupied[key] == path:
                self.paths[path] = name
                self.occupied[key] = path
                return name
        raise ValueError(f'图片路径哈希冲突，停止以免覆盖：{path}')
