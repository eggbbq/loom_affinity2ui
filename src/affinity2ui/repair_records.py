"""Read independent reoptimization proofs without rewriting AF export history."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from affinity2ui.shared_images.provenance import pixel_identity
from ninegrid.jobs import candidate_from_fields


def verified_repairs(directories, images, metadata):
    repairs={}
    by_uuid={meta['uuid']:name for name,meta in metadata.items()}
    for directory in map(Path,directories):
        if not directory.exists():continue  # Optional old records need not survive a clean full export.
        published=json.loads((directory/'published.json').read_text())
        report=json.loads((directory/'report.json').read_text())
        entries={i.get('sourceMetadata',{}).get('uuid'):i for i in report['items'] if i['status']=='candidate'}
        for publication in published['images']:
            name=by_uuid.get(publication['metadata']['uuid'],publication['file']);meta=metadata.get(name)
            if not meta or meta!=publication['metadata']:
                continue
            image=images/name
            if hashlib.sha256(image.read_bytes()).hexdigest()!=publication['afterSha256']:
                continue  # Fresh exports or later edits must use their own evidence.
            uid=meta['uuid'];item=entries[uid]
            original=directory/'originals'/(item['sourceSha256']+'.png')
            if hashlib.sha256(original.read_bytes()).hexdigest()!=item['sourceSha256']:
                raise ValueError(f'重切原图备份已变化：{original}')
            candidate=candidate_from_fields(item)
            grid=[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]
            with Image.open(original) as source,Image.open(image) as current:
                equal=np.array_equal(candidate.crop(np.asarray(source.convert('RGBA'))),np.asarray(current.convert('RGBA')))
            if not equal or grid!=meta['importer'].get('sizeGrid'):
                raise ValueError(f'重切证明与当前图片不匹配：{name}')
            proofs=[]
            for filename in ('validation/report.json','resize-validation/report.json'):
                proof=json.loads((directory/filename).read_text())
                if not proof['valid'] or not proof['cases'] or not all(c['accepted'] for c in proof['cases']):
                    raise ValueError(f'重切引擎证明未通过：{directory/filename}')
                relevant=[c for c in proof['cases'] if (Path(c.get('source','')).stem==item['sourceSha256']
                          if filename=='validation/report.json' else c.get('source')==item['source'])]
                if not relevant or any(c.get('afterRuntime',{}).get('textureSize')!=item['outputSize'] for c in relevant):
                    raise ValueError(f'重切引擎证明缺少当前图片：{name}')
                if filename=='validation/report.json' and any(c['afterRuntime'].get('sizeGrid')!=grid for c in relevant):
                    raise ValueError(f'重切引擎证明的九宫格不匹配：{name}')
                proofs.extend(proof['cases'])
            repairs[uid]=dict(directory=directory,item=item,publication=publication,
                              sourcePixelSha256=pixel_identity(original),engineCases=len(proofs),
                              algorithmVersion=report['settings'].get('algorithmVersion','strict'))
    return repairs
