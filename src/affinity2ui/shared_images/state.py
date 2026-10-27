"""Durable aliases allow a later page export to split shared images safely."""
import json
import hashlib
import shutil
import re
from pathlib import Path


def filename(value, suffix):
    if not isinstance(value,str) or Path(value).name!=value or not value.endswith(suffix):
        raise ValueError(f'无效去重记录文件名：{value!r}')
    return value


def read_state(directory, project):
    path = directory/'index.json'
    if not path.exists():
        return {'version':1,'project':str(project.resolve()),'aliases':[],'canonicalOrder':[]}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=1 or data.get('project')!=str(project.resolve()):
        raise ValueError('跨页面去重记录与当前项目不匹配')
    for alias in data['aliases']:
        filename(alias['file'],'.png');filename(alias['canonicalFile'],'.png')
        filename(alias['blob'],'.png')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}',alias['uuid']) or alias['metadata'].get('uuid')!=alias['uuid']:
            raise ValueError('共享图片记录 UUID 无效')
        for ref in alias['references']:
            filename(ref['prefab'],'.lh')
    return data


def expand_aliases(state, old_state_dir, images, prefabs, fresh_prefabs):
    from .references import rewrite
    for alias in state['aliases']:
        if alias['references'] and all(ref['prefab'] in fresh_prefabs for ref in alias['references']):
            # All consumers were regenerated from their own AF sources. Old
            # aliases must not resurrect stale art or require deleted outputs.
            continue
        target = images/alias['file']
        blob = old_state_dir/'blobs'/alias['blob']
        canonical=images/alias['canonicalFile']
        if not canonical.exists():
            raise ValueError(f'共享原图缺失，停止修改引用：{canonical.name}')
        if not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest()!=alias['sha256']:
            raise ValueError(f'共享图片备份缺失或已变化：{blob}')
        if target.exists():
            meta = json.loads(Path(str(target)+'.meta').read_text())
            if meta['uuid']!=alias['uuid']:
                raise ValueError(f'新图片 UUID 与原共享记录冲突：{target.name}')
        else:
            shutil.copy2(blob,target)
            Path(str(target)+'.meta').write_text(json.dumps(alias['metadata'],ensure_ascii=False,indent=2)+'\n')
        for ref in alias['references']:
            if ref['prefab'] not in fresh_prefabs:
                rewrite(prefabs,ref,alias['canonicalUuid'],alias['uuid'])


def remember_alias(state_dir, file, metadata, canonical_file, canonical_uuid, references):
    content = file.read_bytes();digest = hashlib.sha256(content).hexdigest()
    blob = metadata['uuid']+'_'+digest+'.png'
    directory = state_dir/'blobs';directory.mkdir(parents=True,exist_ok=True)
    (directory/blob).write_bytes(content)
    return {'file':file.name,'uuid':metadata['uuid'],'metadata':metadata,'sha256':digest,'blob':blob,
            'canonicalFile':canonical_file,'canonicalUuid':canonical_uuid,'references':references}
