"""Re-run the real optimizer on selected existing images, preserving prefab edits."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image

from .exporter import directory_identity
from .images import publish_bundles
from .ninegrid import optimize


def read_json(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def original_pixels(image, metadata, record_dirs):
    """Only reuse a backup if its recorded crop exactly matches current pixels."""
    if not metadata.get('importer', {}).get('sizeGrid'):
        return image.read_bytes()
    from ninegrid.jobs import candidate_from_fields
    for directory in record_dirs:
        for item in read_json(directory/'report.json')['items']:
            if item.get('sourceMetadata', {}).get('uuid') != metadata['uuid'] or not item.get('sizeGrid'):
                continue
            original=directory/'originals'/(item['sourceSha256']+'.png')
            if not original.is_file() or digest(original)!=item['sourceSha256']:
                continue
            candidate=candidate_from_fields(item)
            grid=[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]
            if grid!=metadata['importer']['sizeGrid']:
                continue
            with Image.open(original) as source,Image.open(image) as current:
                if np.array_equal(candidate.crop(np.asarray(source.convert('RGBA'))),np.asarray(current.convert('RGBA'))):
                    return original.read_bytes()
    raise ValueError(f'找不到与当前切图完全匹配的原始备份：{image}；请用 --original-records 指定旧九宫格记录目录')


def validate_resizing(stage, images, project, engine_dir=None):
    from ninegrid.jobs import compare_render
    from ninegrid.engine import engine_libraries
    records=images/'export-records/ninegrid'
    report=read_json(records/'report.json')
    owners={}
    def visit(node,file):
        if node.get('_$type') in {'GProgressBar','GSlider'}:
            for key,axis in (('hBar','horizontal'),('_hBar','horizontal'),('vBar','vertical'),('_vBar','vertical')):
                value=node.get(key)
                ref=value.get('_$ref') if isinstance(value,dict) else None
                if ref:owners[file,ref]=dict(type=node['_$type'],axis=axis,width=node['width'],height=node['height'])
        for child in node.get('_$child',[]):visit(child,file)
    for file in stage.joinpath('assets').rglob('*'):
        if file.suffix in {'.lh','.ls'}:visit(read_json(file),file.relative_to(stage).as_posix())
    cases=[]
    for item in report['items']:
        if item['status']!='candidate':continue
        size=item['sourceSize'];original=records/'originals'/(item['sourceSha256']+'.png')
        common=dict(name=item['source'],original=str(original),optimized=str(stage/item['output']),sourceSize=size,
                    grid=[item['sizeGrid'][k] for k in ('top','right','bottom','left','repeat')],
                    mode=item.get('mode','strict'),qualityLimits=item.get('qualityLimits'),filterMode=item['sourceFilterMode'],
                    validationFilterModes=item.get('validationFilterModes',[item['sourceFilterMode']]))
        dynamic=[owners[r['file'],r['nodeId']] for r in item['references'] if (r['file'],r['nodeId']) in owners]
        if dynamic:
            for owner in dynamic:
                for reverse in (False,True):
                    for value in (0,.1,1,2,10,25,50,75,99,100):
                        cases.append(dict(common,owner=owner,reverse=reverse,value=value,capture=[owner['width'],owner['height']]))
        else:
            for factor in (.5,.8,1,1.2):
                target=[round(size[0]*factor),size[1]]
                cases.append(dict(common,target=target,capture=target))
    cases=[dict(case,filterMode=sampling) for case in cases for sampling in case['validationFilterModes']]
    artifacts=records/'resize-validation';artifacts.mkdir()
    payload=dict(cases=cases,artifacts=str(artifacts),libraries=str(engine_libraries(project,engine_dir)))
    from .runtime_env import playwright_module
    import os
    env = dict(os.environ, AFFINITY2UI_PLAYWRIGHT_MODULE=str(playwright_module()))
    result=subprocess.run(['node',str(Path(__file__).with_name('resize_probe.mjs'))],input=json.dumps(payload),env=env,
                          capture_output=True,text=True,timeout=180,check=True)
    proof=[]
    for record in json.loads(result.stdout):
        comparison,_=compare_render((str(stage),record))
        for key in ('before','after'):comparison[key]='resize-validation/'+Path(comparison[key]).name
        proof.append(comparison)
    result=dict(valid=bool(proof) and all(r['accepted'] for r in proof),engine='LayaAir 3.4.2',
                reference='Original texture with the computed nine-slice borders; real native progress/slider value changes',cases=proof)
    (artifacts/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['valid']:raise ValueError('实际尺寸/进度变化验证失败，未回写项目')
    return result


def reoptimize(project, selected, records, original_records=(), workers=2, engine_dir=None):
    project=project.resolve();images=project/'assets/ui/images';records=records.resolve()
    if records.is_relative_to(project) or project.is_relative_to(records):
        raise ValueError('重切记录必须在 Laya 工程外且不能包含工程')
    if records.exists() and (any(records.rglob('affinity.json')) or (records/'shared-image-dedupe').exists()):
        raise ValueError('重切报告不能覆盖主导出记录或共享依赖目录')
    selected=[p.resolve() for p in selected]
    if len(selected)!=len(set(selected)) or any(p.parent!=images or p.suffix!='.png' for p in selected):
        raise ValueError('只接受当前工程 assets/ui/images 中不重复的 PNG')
    identity=directory_identity(images);record_identity=directory_identity(records)
    scenes={p:digest(p) for p in project.joinpath('assets').rglob('*') if p.suffix in {'.lh','.ls'}}
    atlases={p:digest(p) for p in project.joinpath('assets').rglob('*.atlascfg')}
    records.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ninegrid-reoptimize-',dir=records.parent) as temporary:
        stage=Path(temporary);staged=stage/'assets/ui/images';staged.mkdir(parents=True)
        for config in project.glob('*.laya'):shutil.copy2(config,stage/config.name)
        for scene in scenes:
            target=stage/scene.relative_to(project);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(scene,target)
        for config in atlases:
            target=stage/config.relative_to(project);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(config,target)
        before=stage/'before';before.mkdir()
        for image in selected:
            meta=Path(str(image)+'.meta');metadata=read_json(meta)
            shutil.copy2(image,before/image.name);shutil.copy2(meta,before/meta.name)
            (staged/image.name).write_bytes(original_pixels(image,metadata,original_records))
            metadata=copy.deepcopy(metadata);metadata.setdefault('importer',{}).pop('sizeGrid',None)
            (staged/meta.name).write_text(json.dumps(metadata,indent=2)+'\n')
        try:
            optimize(stage,staged,project,'visual',workers,engine_dir)
            resize=validate_resizing(stage,staged,project,engine_dir=engine_dir)
        except (ValueError,subprocess.SubprocessError):
            failure=Path(tempfile.mkdtemp(prefix=records.name+'-failed-',dir=records.parent))
            for proof in (stage/'.ninegrid',staged/'export-records'):
                if proof.is_dir():shutil.copytree(proof,failure/proof.name)
            raise
        current_scenes={p:digest(p) for p in project.joinpath('assets').rglob('*') if p.suffix in {'.lh','.ls'}}
        current_atlases={p:digest(p) for p in project.joinpath('assets').rglob('*.atlascfg')}
        if (directory_identity(images)!=identity or current_scenes!=scenes or current_atlases!=atlases
                or directory_identity(records)!=record_identity):
            raise ValueError('验证期间项目或记录发生变化，未回写')
        merged=stage/'merged';shutil.copytree(images,merged)
        for image in selected:
            for name in (image.name,image.name+'.meta'):shutil.copy2(staged/name,merged/name)
        evidence=stage/'records';shutil.move(str(staged/'export-records/ninegrid'),evidence)
        shutil.move(str(before),evidence/'before')
        summary=dict(images=[dict(file=p.name,beforeSha256=identity[p.name],afterSha256=digest(merged/p.name),
                                 metadata=read_json(merged/(p.name+'.meta'))) for p in selected],resizeCasesPassed=len(resize['cases']))
        (evidence/'published.json').write_text(json.dumps(summary,indent=2)+'\n')
        publish_bundles([(merged,images),(evidence,records)],stage/'rollback')
    return summary
