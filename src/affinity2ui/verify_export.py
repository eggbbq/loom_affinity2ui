"""Validate canonical final cuts against their recorded original pixels."""
import copy
import json
from pathlib import Path
import shutil

from .audit import manifests
from .reoptimize import validate_resizing


def verify_exported_resize(stage, project, assets, records, *, repair_records=(), engine_dir=None):
    stage, project, assets, records = map(lambda p:Path(p).resolve(), (stage, project, assets, records))
    images = stage/'assets/ui/images'
    images.mkdir(parents=True,exist_ok=True)
    live = {json.loads(p.read_text())['uuid']:p for p in (assets/'images').glob('*.png.meta')}
    for prefab in (assets/'prefabs').glob('*.lh'):
        target = stage/'assets/ui/prefabs'/prefab.name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(prefab,target)
    from .repair_records import verified_repairs
    repairs = verified_repairs(repair_records,assets/'images',{p.name[:-5]:json.loads(p.read_text()) for p in live.values()})
    candidates = [(r['directory'],r['item']) for r in repairs.values()]
    for manifest,data in manifests(records):
        directory = manifest.parent/'export-records/ninegrid'
        report = directory/'report.json'
        if report.exists():
            candidates.extend((directory,item) for item in json.loads(report.read_text())['items'] if item['status']=='candidate')
    # Resolve by canonical UUID and matching grid, rather than the first alias:
    # old and new pages may legitimately have different historical cuts.
    selected = {}
    for directory,item in candidates:
        uid = item.get('sourceMetadata',{}).get('uuid')
        if uid not in live or uid in selected:continue
        actual = json.loads(live[uid].read_text())
        grid = [item['sizeGrid'][k] for k in ('top','right','bottom','left','repeat')]
        if actual['importer'].get('sizeGrid') == grid:selected[uid]=(directory,item)
    combined = []
    proof_root = images/'export-records/ninegrid';(proof_root/'originals').mkdir(parents=True,exist_ok=True)
    for uid,meta in live.items():
        actual = json.loads(meta.read_text())
        if not actual['importer'].get('sizeGrid'):continue
        if uid not in selected:raise ValueError(f'最终九宫格缺少匹配的原图证明：{meta.name}')
        directory,entry = selected[uid]
        image = meta.with_suffix('')
        shutil.copy2(image,images/image.name);shutil.copy2(meta,images/meta.name)
        source = directory/'originals'/(entry['sourceSha256']+'.png')
        shutil.copy2(source,proof_root/'originals'/source.name)
        item = copy.deepcopy(entry);item['output']='assets/ui/images/'+image.name
        references=[]
        def visit(node,file):
            if node.get('src') == 'res://'+uid:
                references.append({'file':file,'nodeId':node['_$id'],'type':node['_$type']})
            for child in node.get('_$child',[]):visit(child,file)
        for prefab in (stage/'assets/ui/prefabs').glob('*.lh'):
            visit(json.loads(prefab.read_text()),prefab.relative_to(stage).as_posix())
        item['references']=references;combined.append(item)
    (proof_root/'report.json').write_text(json.dumps({'items':combined},indent=2)+'\n')
    if not combined:return {'valid':True,'uniqueTextures':0,'cases':0,'report':None}
    result = validate_resizing(stage,images,project,engine_dir=engine_dir)
    return {'valid':result['valid'],'uniqueTextures':len(combined),'cases':len(result['cases']),
            'report':str(proof_root/'resize-validation/report.json')}
