"""Stage and commit a post-import deduplication without changing node layout."""
import json
import hashlib
import shutil
import tempfile
from pathlib import Path

from .references import collect,rewrite,external_references
from .state import read_state,expand_aliases,remember_alias
from .optimizer import plan


def identity(path):
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f'去重目录必须是普通目录：{path}')
    values={}
    for file in path.rglob('*'):
        if file.is_symlink():
            raise ValueError(f'去重目录不允许符号链接：{file}')
        if file.is_file():
            values[file.relative_to(path).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    return values


def commit(pairs,rollback):
    rollback.mkdir();backups=[];published=[]
    try:
        for index,(_,target) in enumerate(pairs):
            if target.exists():
                backup=rollback/str(index);target.rename(backup);backups.append((backup,target))
        for source,target in pairs:
            source.rename(target);published.append(target)
    except BaseException:
        for target in reversed(published):shutil.rmtree(target)
        for backup,target in reversed(backups):backup.rename(target)
        raise


def run(project,assets,state_dir,*,threshold=.99,preferred=None,fresh_prefabs=(),restore_only=False,source_records=()):
    from ..image_dedupe import similarity_threshold
    threshold=similarity_threshold(threshold)
    project,assets,state_dir=map(lambda p:Path(p).resolve(),(project,assets,state_dir))
    if (not assets.is_relative_to(project/'assets') or state_dir.is_relative_to(project)
            or project.is_relative_to(state_dir)):
        raise ValueError('UI 目录必须在项目 assets 内，去重记录必须在项目外')
    images,prefab_dir=assets/'images',assets/'prefabs'
    if not images.is_dir() or not prefab_dir.is_dir():
        raise ValueError('需要已导入的 images 和 prefabs 目录')
    if preferred is None:
        preferred=[p.name for p in sorted(images.glob('*.png'),key=lambda p:(p.stat().st_mtime_ns,p.name))]
    if not isinstance(preferred,(list,tuple)) or any(not isinstance(n,str) for n in preferred):
        raise ValueError('已有图片清单必须为文件名数组')
    paths=(images,prefab_dir,state_dir);before={p:identity(p) for p in paths}
    state=read_state(state_dir,project)
    state_dir.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dedupe-',dir=state_dir.parent) as temp:
        stage=Path(temp);staged_images=stage/'images';staged_prefabs=stage/'prefabs';staged_state=stage/'state'
        shutil.copytree(images,staged_images);shutil.copytree(prefab_dir,staged_prefabs)
        if state_dir.exists():shutil.copytree(state_dir,staged_state)
        else:staged_state.mkdir()
        prefabs={p.name:json.loads(p.read_text(encoding='utf-8')) for p in staged_prefabs.glob('*.lh')}
        expand_aliases(state,state_dir,staged_images,prefabs,set(fresh_prefabs))
        metadata={p.name:json.loads(Path(str(p)+'.meta').read_text(encoding='utf-8')) for p in staged_images.glob('*.png')}
        uids={m['uuid'] for m in metadata.values()}
        if len(uids)!=len(metadata):raise ValueError('图片 UUID 重复，停止去重')
        refs,protected=collect(prefabs,uids)
        protected|=external_references(project,prefab_dir,images,uids,{n:m['uuid'] for n,m in metadata.items()})
        preferred=list(preferred)
        order=[n for n in state['canonicalOrder'] if n in preferred]
        order+=preferred+state['canonicalOrder']+[a['file'] for a in state['aliases']]
        from .provenance import verified_origins
        origins={} if restore_only else verified_origins(staged_images,metadata,[state_dir.parent,*map(Path,source_records)],
                                                       state.get('imageOrigins',[]))
        origin_entries=[dict(file=name,uuid=metadata[name]['uuid'],sourcePixelSha256=source_id,
                             pngSha256=hashlib.sha256((staged_images/name).read_bytes()).hexdigest(),
                             optimizedImporter=metadata[name].get('importer',{}))
                        for name,source_id in sorted(origins.items())]
        matches={} if restore_only else plan(staged_images,metadata,refs,protected,order,threshold,origins)
        aliases=[];changed=0
        for old,new in matches.items():
            old_meta,new_meta=metadata[old],metadata[new]
            affected=[r for r in refs if r['uuid']==old_meta['uuid']]
            aliases.append(remember_alias(staged_state,staged_images/old,old_meta,new,new_meta['uuid'],affected))
            for ref in affected:
                if not rewrite(prefabs,ref,old_meta['uuid'],new_meta['uuid']):raise ValueError('引用更新失败')
                changed+=1
            (staged_images/old).unlink();(staged_images/(old+'.meta')).unlink()
        remaining={m['uuid'] for name,m in metadata.items() if name not in matches}
        final_refs,_=collect(prefabs,uids)
        if any(r['uuid'] not in remaining for r in final_refs):raise ValueError('去重后存在丢失的图片引用')
        for name,data in prefabs.items():
            original=json.loads((prefab_dir/name).read_text(encoding='utf-8'))
            if data!=original:(staged_prefabs/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        kept=[n for n in dict.fromkeys(order+sorted(metadata)) if n in metadata and n not in matches]
        new_state={'version':1,'project':str(project),'canonicalOrder':kept,'aliases':sorted(aliases,key=lambda a:a['file'])}
        new_state['imageOrigins']=state.get('imageOrigins',[]) if restore_only else origin_entries
        (staged_state/'index.json').write_text(json.dumps(new_state,ensure_ascii=False,indent=2)+'\n')
        pairs=[]
        for staged,target in ((staged_images,images),(staged_prefabs,prefab_dir),(staged_state,state_dir)):
            if identity(target)!=before[target]:raise ValueError(f'去重期间目录已变化：{target}')
            if identity(staged)!=before[target]:pairs.append((staged,target))
        if pairs:commit(pairs,stage/'rollback')
    return {'phase':'restore' if restore_only else 'deduplicate',
            'mergedImages':len(matches),'rewrittenReferences':changed,'aliases':matches,
            'images':str(images),'state':str(state_dir/'index.json')}
