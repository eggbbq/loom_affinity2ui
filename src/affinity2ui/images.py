"""Flatten shared runtime images while retaining existing texture UUIDs."""
import json
import hashlib
from pathlib import Path, PurePosixPath
import shutil

from psd2ui.laya_prefab import write_json
from .image_names import ImageNames, SCHEME, flat_image_name


# LayaAir 3.4.2 ITextureSettings: 0 default, 1 lightmap, 2 sprite.
SPRITE_TEXTURE_TYPE = 2


def ensure_sprite_texture(metadata):
    metadata.setdefault('importer', {})['textureType'] = SPRITE_TEXTURE_TYPE
    return metadata


def restore_shared_metadata(staged, shared, feature, previous_records=None):
    previous = {}
    manifest = Path(previous_records) / 'affinity.json' if previous_records else None
    if manifest and manifest.is_file():
        previous = {item['sourcePath']:item for item in json.loads(manifest.read_text(encoding='utf-8')).get('images', [])}
    names = ImageNames(Path(previous_records).parent if previous_records else None, shared)
    for image in sorted(staged.rglob('*.png')):
        source_path = (PurePosixPath(feature) / image.relative_to(staged).as_posix()).as_posix()
        name = names.name(source_path)
        meta = shared / (name+'.meta')
        if not meta.is_file() and source_path in previous:
            old = previous[source_path]['file']
            if Path(old).name != old:
                raise ValueError('旧图片清单中存在无效路径')
            meta = shared / (old+'.meta')
        destination = Path(str(image)+'.meta')
        if meta.is_file():
            shutil.copy2(meta, destination)
        elif not destination.exists() and source_path in previous and previous[source_path].get('uuid'):
            importer=previous[source_path].get('optimizedImporter',{
                'textureType':2, 'sRGB':True, 'generateMipmap':False, 'npot':0, 'maxSize':0, 'usePng8':False})
            write_json(destination, {'uuid':previous[source_path]['uuid'], 'importer':importer})


def pack_images(staged, shared_stage, shared_target, records, previous_records, feature, source_identities=None):
    names = ImageNames(previous_records.parent, shared_target)
    if shared_target.exists():
        shutil.copytree(shared_target, shared_stage)
    else:
        shared_stage.mkdir(parents=True)
    previous_manifest = previous_records / 'affinity.json'
    owned = set()
    if previous_manifest.is_file():
        for item in json.loads(previous_manifest.read_text(encoding='utf-8')).get('images', []):
            name = item['file']
            if Path(name).name != name or not name.endswith('.png'):
                raise ValueError('旧图片清单中存在无效路径')
            owned.add(name)
    for name in owned:
        (shared_stage/name).unlink(missing_ok=True)
        (shared_stage/(name+'.meta')).unlink(missing_ok=True)
    references = set()
    def visit(node):
        src = node.get('src')
        if isinstance(src,str) and src.startswith('res://'):
            references.add(src[6:])
        for child in node.get('_$child', []):
            visit(child)
    for prefab in staged.rglob('*.lh'):
        visit(json.loads(prefab.read_text(encoding='utf-8')))
    images = []
    for image in sorted(staged.rglob('*.png')):
        meta = Path(str(image)+'.meta')
        metadata = ensure_sprite_texture(json.loads(meta.read_text(encoding='utf-8')))
        write_json(meta,metadata)
        relative = image.relative_to(staged)
        source_path = (PurePosixPath(feature) / relative.as_posix()).as_posix()
        if metadata['uuid'] not in references:
            # Source-only states from non-template rows are intermediate art.
            archive = records / 'unused-images' / relative
            archive.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(image),str(archive))
            shutil.move(str(meta),str(Path(str(archive)+'.meta')))
            continue
        name = names.name(source_path)
        target = shared_stage/name
        if target.exists():
            old_meta = Path(str(target)+'.meta')
            old_uuid = json.loads(old_meta.read_text(encoding='utf-8')).get('uuid') if old_meta.is_file() else None
            if old_uuid != metadata['uuid']:
                raise ValueError(f'共享图片路径与现有资源冲突：{name}')
        shutil.move(str(image),str(target))
        shutil.move(str(meta),str(Path(str(target)+'.meta')))
        item=dict(file=name,uuid=metadata['uuid'],sourcePath=source_path)
        if source_identities and relative.as_posix() in source_identities:
            item.update(sourcePixelSha256=source_identities[relative.as_posix()],
                        pngSha256=hashlib.sha256(target.read_bytes()).hexdigest(),optimizedImporter=metadata.get('importer',{}))
        images.append(item)
    manifest = records / 'affinity.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data.update(imageDirectory='images',imageNaming=SCHEME,images=images)
    write_json(manifest,data)
    for directory in sorted((p for p in staged.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return images


def publish_bundles(pairs, rollback, retired=()):
    """Publish final prefabs, shared images and records together; restore on failure."""
    rollback.mkdir(parents=True)
    backups, published = [], []
    try:
        for index, (_, target) in enumerate(pairs):
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                raise ValueError(f'输出目录必须为普通目录：{target}')
            if target.exists():
                backup = rollback / str(index)
                target.rename(backup)
                backups.append((backup,target))
        for index,target in enumerate(retired):
            if target.exists():
                backup=rollback/('retired-'+str(index))
                target.rename(backup)
                backups.append((backup,target))
        for source,target in pairs:
            target.parent.mkdir(parents=True,exist_ok=True)
            source.rename(target)
            published.append(target)
    except BaseException:
        for target in reversed(published):
            shutil.rmtree(target)
        for backup,target in reversed(backups):
            backup.rename(target)
        raise


def restore_prefab_metadata(staged, prefab_target):
    for prefab in staged.rglob('*.lh'):
        meta = prefab_target / (prefab.name+'.meta')
        if meta.is_file():
            shutil.copy2(meta, Path(str(prefab)+'.meta'))


def pack_prefabs(staged, prefab_stage, prefab_target, records, previous_records):
    if prefab_target.exists():
        shutil.copytree(prefab_target,prefab_stage)
    else:
        prefab_stage.mkdir(parents=True)
    manifest = previous_records / 'affinity.json'
    owned = []
    if manifest.is_file():
        owned = json.loads(manifest.read_text(encoding='utf-8')).get('prefabs', [])
    for item in owned:
        name=item['file']
        if Path(name).name != name or not name.endswith('.lh'):
            raise ValueError('旧预制体清单中存在无效路径')
        (prefab_stage/name).unlink(missing_ok=True)
        (prefab_stage/(name+'.meta')).unlink(missing_ok=True)
    prefabs=[]
    for prefab in staged.rglob('*.lh'):
        meta=Path(str(prefab)+'.meta')
        metadata=json.loads(meta.read_text(encoding='utf-8'))
        target=prefab_stage/prefab.name
        if target.exists():
            existing=json.loads(Path(str(target)+'.meta').read_text(encoding='utf-8'))
            if existing['uuid'] != metadata['uuid']:
                raise ValueError(f'预制体根名与其他功能冲突：{prefab.name}')
        shutil.move(str(prefab),str(target))
        shutil.move(str(meta),str(Path(str(target)+'.meta')))
        prefabs.append(dict(file=target.name,uuid=metadata['uuid']))
    manifest=records/'affinity.json'
    data=json.loads(manifest.read_text(encoding='utf-8'))
    data.update(prefabDirectory='prefabs',prefabs=prefabs)
    write_json(manifest,data)
    return prefabs
