"""Rename existing exports without rendering, changing UUIDs, or editing prefabs."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .image_names import ImageNames, SCHEME
from .images import publish_bundles
from .exporter import directory_identity


TEXT_EXTENSIONS = {'.lh', '.ls', '.json', '.ts', '.js', '.meta', '.atlascfg',
                   '.lmat', '.sco', '.controller', '.shader', '.lani'}


def file_references(project, images, renamed):
    """Unknown path consumers must keep working; refuse rather than guess."""
    snapshots = {}
    for folder in ('assets', 'src', 'settings'):
        for file in (project/folder).rglob('*'):
            if not file.is_file() or file.suffix not in TEXT_EXTENSIONS:
                continue
            if file.parent == images and file.name.endswith('.png.meta'):
                continue
            content = file.read_bytes()
            snapshots[file] = hashlib.sha256(content).hexdigest()
            text = content.decode('utf-8', errors='ignore')
            for old in renamed:
                if old in text:
                    raise ValueError(f'存在按旧文件名引用的资源，请先适配该引用：{file}: {old}')
    return snapshots


def migrate(project, assets, records, *, apply=False):
    project, assets, records = (Path(p).resolve() for p in (project, assets, records))
    if (not assets.is_relative_to(project/'assets') or records.is_relative_to(project)
            or project.is_relative_to(records)):
        raise ValueError('资源须在工程 assets 内，记录须在工程外且不能包含工程')
    images = assets/'images'
    before = {p: directory_identity(p) for p in (images, records)}
    if before[images] is None or before[records] is None:
        raise ValueError('需要现有 images 和完整导出记录')
    names = ImageNames(records, images)
    manifests = {p: json.loads(p.read_text(encoding='utf-8')) for p in sorted(records.glob('*/affinity.json'))}
    mapping, expected_uuids = {}, {}
    for data in manifests.values():
        for item in data.get('images', []):
            old, new = item['file'], names.name(item['sourcePath'])
            if old in mapping and mapping[old] != new:
                raise ValueError(f'图片记录原路径冲突：{old}')
            mapping[old] = new
            expected_uuids[old] = item['uuid']
    renamed = {old:new for old,new in mapping.items() if old != new}
    external = file_references(project, images, renamed)
    live = {p.name for p in images.glob('*.png')}
    for old in renamed.keys() & live:
        meta = json.loads((images/(old+'.meta')).read_text(encoding='utf-8'))
        if meta['uuid'] != expected_uuids[old]:
            raise ValueError(f'图片 UUID 与导出记录不一致，停止迁移：{old}')
    summary = {'scheme': SCHEME, 'renamedImages': len(renamed.keys() & live),
               'recordedPaths': len(mapping), 'names': renamed, 'applied': apply}
    if not apply or not renamed:
        return summary
    with tempfile.TemporaryDirectory(prefix='image-name-', dir=records.parent) as temporary:
        stage = Path(temporary)
        staged_images, staged_records = stage/'images', stage/'records'
        shutil.copytree(images, staged_images)
        shutil.copytree(records, staged_records)
        for old,new in renamed.items():
            if old not in live:
                continue  # Deduplicated originals live in blobs, not images.
            if (staged_images/new).exists() or (staged_images/(new+'.meta')).exists():
                raise ValueError(f'目标图片已存在，停止迁移：{new}')
            (staged_images/old).rename(staged_images/new)
            (staged_images/(old+'.meta')).rename(staged_images/(new+'.meta'))
        for manifest,data in manifests.items():
            for item in data.get('images', []):
                item['file'] = mapping[item['file']]
            data['imageNaming'] = SCHEME
            target = staged_records/manifest.relative_to(records)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        index = staged_records/'shared-image-dedupe/index.json'
        if index.exists():
            state = json.loads(index.read_text(encoding='utf-8'))
            if state['project'] != str(project):
                raise ValueError('共享图片记录与项目不匹配')
            def mapped(value):
                if value not in mapping:
                    raise ValueError(f'共享图片缺少原始路径记录：{value}')
                return mapping[value]
            state['canonicalOrder'] = [mapped(n) for n in state['canonicalOrder']]
            for alias in state['aliases']:
                alias['file'] = mapped(alias['file'])
                alias['canonicalFile'] = mapped(alias['canonicalFile'])
            for origin in state.get('imageOrigins', []):
                origin['file'] = mapped(origin['file'])
            index.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        for target, snapshot in before.items():
            if directory_identity(target) != snapshot:
                raise ValueError(f'迁移期间目录已变化，未提交：{target}')
        if any(not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != digest
               for file,digest in external.items()):
            raise ValueError('迁移期间引用文件发生变化，未提交')
        publish_bundles([(staged_images, images), (staged_records, records)], stage/'rollback')
    return summary
