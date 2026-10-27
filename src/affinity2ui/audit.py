"""Validate final shared resources, manifest identities and engine proofs."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from PIL import Image
from affinity2ui.shared_images.provenance import pixel_identity
from .ninegrid_names import configured_ignore_names, normalize_ignored_names, matches_ignored_name




def manifests(records):
    return [(p, json.loads(p.read_text(encoding='utf-8'))) for p in sorted(Path(records).glob('*/affinity.json'))]


def audit(output, *, project=None, assets=None, records=None, quiet=False, ignored_names=None, repair_records=()):
    project = Path(project or Path.cwd()/'client').resolve()
    assets = Path(assets or project/'assets/ui').resolve()
    records = Path(records or Path.cwd()/'out/affinity-export').resolve()
    ignored_names = configured_ignore_names() if ignored_names is None else normalize_ignored_names(ignored_names)
    images = assets/'images'
    index = records/'shared-image-dedupe/index.json'
    state = json.loads(index.read_text()) if index.exists() else {'aliases':[]}
    aliases = {item['uuid']:item for item in state['aliases']}
    metadata = {p.name[:-5]:json.loads(p.read_text()) for p in images.glob('*.png.meta')}
    by_uuid = {meta['uuid']:name for name,meta in metadata.items()}
    if len(by_uuid) != len(metadata):raise ValueError('图片 UUID 重复')
    from .repair_records import verified_repairs
    repairs = verified_repairs(repair_records, images, metadata)
    features, originals = [], defaultdict(list)
    engine_cases, versions = 0, set()
    for manifest, data in manifests(records):
        source = Path(data['source'])
        if source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() != data['sourceSha256']:
            raise ValueError(f'源 Affinity 已变化，导出记录过期：{source}')
        directory = manifest.parent/'export-records/ninegrid'
        report_path = directory/'report.json'
        cases = []
        if report_path.exists():
            report = json.loads(report_path.read_text())
            versions.add(report['settings'].get('algorithmVersion', 'strict'))
            if report['settings'].get('algorithmVersion') in {'auto-grid-v1','auto-grid-v2','auto-grid-v3'}:
                settings=report['settings']
                cpu_tolerance=1 if settings.get('algorithmVersion')=='auto-grid-v3' and settings.get('mode')=='visual' else 0
                if (not settings.get('automatic') or settings.get('cpuPixelTolerance')!=cpu_tolerance
                        or settings.get('gpuChannelTolerance') not in (0,1)):
                    raise ValueError(f'自动九宫格缺少已声明CPU/有界GPU策略：{manifest}')
                for candidate in report['items']:
                    if candidate['status']=='candidate' and candidate.get('candidateCoding')=='linear':
                        if (settings['mode']!='visual' or candidate.get('cpuMaxRawChannelError',999)>1
                                or candidate.get('cpuMeanError',999)>.02):
                            raise ValueError(f'线性中心缺少有界CPU证明：{manifest}')
            elif report['settings'].get('centerSize', 1) != 1:
                raise ValueError(f'旧九宫格中心段不是 1px：{manifest}')
            proof_path = directory/'validation/report.json'
            if proof_path.exists():
                proof = json.loads(proof_path.read_text())
                if not proof.get('valid') or not all(c['accepted'] for c in proof['cases']):raise ValueError(f'引擎证明未通过：{proof_path}')
                cases = proof['cases']
            elif any(item['status'] == 'candidate' for item in report['items']):raise ValueError(f'九宫格候选缺少引擎证明：{directory}')
        elif not data.get('exportOnly'):raise ValueError(f'缺少九宫格记录：{manifest}')
        engine_cases += len(cases)
        for item in data['images']:
            uid, seen = item['uuid'], set()
            while uid in aliases:
                if uid in seen:raise ValueError('共享引用形成循环')
                seen.add(uid);uid = aliases[uid]['canonicalUuid']
            if uid not in by_uuid:raise ValueError(f'图片丢失：{item["file"]}')
            if not item.get('sourcePixelSha256'):raise ValueError(f'缺少原始像素身份：{item["file"]}')
            if item['uuid'] in aliases:
                alias = aliases[item['uuid']]
                content = (records/'shared-image-dedupe/blobs'/alias['blob']).read_bytes()
                importer = alias['metadata']['importer']
            else:
                content = (images/by_uuid[uid]).read_bytes()
                importer = metadata[by_uuid[uid]]['importer']
            effective = item
            repair = repairs.get(uid)
            if item['uuid'] not in aliases and repair and repair['sourcePixelSha256'] == item['sourcePixelSha256']:
                effective = dict(item, pngSha256=repair['publication']['afterSha256'], optimizedImporter=repair['publication']['metadata']['importer'])
            if hashlib.sha256(content).hexdigest() != effective['pngSha256'] or importer != effective['optimizedImporter']:
                raise ValueError(f'图片或导入设置与记录不一致：{item["file"]}')
            originals[item['sourcePixelSha256']].append({'feature':manifest.parent.name,'file':by_uuid[uid],'uuid':uid})
        features.append({'source':str(source),'sourceSha256':data['sourceSha256'],'pages':data['pages'],
                         'warnings':data['warnings'],'engineCases':len(cases),'exportOnly':data.get('exportOnly',False)})
    if not features:raise ValueError('没有可检查的 Affinity 导出记录')
    references = []
    def visit(value, file):
        if isinstance(value,dict):
            for key,child in value.items():
                if key in {'src','skin','icon','selectedIcon'} and isinstance(child,str) and child.startswith('res://'):
                    uid = child[6:]
                    if uid not in by_uuid:raise ValueError(f'预制体图片引用丢失：{file}: {uid}')
                    references.append({'prefab':file,'uuid':uid})
                else:visit(child,file)
        elif isinstance(value,list):
            for child in value:visit(child,file)
    for prefab in (assets/'prefabs').glob('*.lh'):visit(json.loads(prefab.read_text()),prefab.name)
    gridded, pixels = [], defaultdict(list)
    for name,meta in metadata.items():
        with Image.open(images/name) as image:size = image.size
        importer = meta['importer']
        if importer.get('textureType') != 2:raise ValueError(f'不是精灵纹理：{name}')
        grid = importer.get('sizeGrid')
        if grid:
            if matches_ignored_name(name,ignored_names):raise ValueError(f'忽略名称不应有九宫格：{name}')
            if (len(grid) != 5 or any(type(n) is not int or n < 0 for n in grid)
                    or grid[1]+grid[3] >= size[0] or grid[0]+grid[2] >= size[1] or grid[4] not in (0,1)):raise ValueError(f'无效九宫格：{name}')
            gridded.append({'file':name,'size':size,'sizeGrid':grid})
        pixels[(pixel_identity(images/name),json.dumps(importer,sort_keys=True))].append(name)
    summary = dict(valid=True,features=features,liveImages=len(metadata),griddedImages=len(gridded),
        imageReferences=len(references),brokenReferences=0,engineCases=engine_cases,
        algorithmVersions=sorted(map(str,versions)),originalIdentityGroups=len(originals),
        duplicateOriginalGroups=sum(len({v['uuid'] for v in group}) > 1 for group in originals.values()),
        duplicateFinalPixelGroups=sum(len(group)>1 for group in pixels.values()),ninegrid=gridded,
        excludedNameContains=list(ignored_names))
    repair_cases={(str(record['directory']),filename,key) for record in repairs.values()
                  for filename,key in record.get('proofKeys',[])}
    summary.update(repairEngineCases=len(repair_cases),
                   repairAlgorithmVersions=sorted({str(r['algorithmVersion']) for r in repairs.values()}),
                   repairsHaveSeparatePerCaseTolerances=bool(repairs))
    output = Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not quiet:print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary
