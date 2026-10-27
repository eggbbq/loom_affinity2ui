"""Verify pre-slice pixel identity independently of AF paths or crop settings."""
import hashlib
import json

import numpy as np
from PIL import Image


def pixel_identity(path):
    with Image.open(path) as image:
        rgba=image.convert('RGBA')
        return hashlib.sha256(str(rgba.size).encode()+b'\0'+rgba.tobytes()).hexdigest()


def verified_origins(images, metadata, directories, saved=()):
    identities={}
    def accept(item):
        name=item['file'];meta=metadata.get(name)
        if (meta and item.get('uuid')==meta['uuid'] and item.get('sourcePixelSha256')
                and item.get('optimizedImporter')==meta.get('importer',{})
                and item.get('pngSha256')==hashlib.sha256((images/name).read_bytes()).hexdigest()):
            identities[name]=item['sourcePixelSha256']
    for item in saved:accept(item)
    for root in directories:
        manifests=[root/'affinity.json'] if (root/'affinity.json').is_file() else sorted(root.glob('*/affinity.json'))
        for manifest in manifests:
            for item in json.loads(manifest.read_text()).get('images',[]):
                accept(item)
        # Migrate old exports only with a matching original hash and exact crop.
        by_uuid={meta['uuid']:name for name,meta in metadata.items() if name not in identities}
        if not by_uuid:continue
        reports=[root/'report.json'] if (root/'report.json').is_file() else sorted(root.glob('*/export-records/ninegrid/report.json'))
        for report in reports:
            for item in json.loads(report.read_text()).get('items',[]):
                name=by_uuid.get(item.get('sourceMetadata',{}).get('uuid'))
                if not name or not item.get('sizeGrid'):continue
                original=report.parent/'originals'/(item['sourceSha256']+'.png')
                if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest()!=item['sourceSha256']:continue
                from ninegrid.jobs import candidate_from_fields
                candidate=candidate_from_fields(item)
                grid=[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]
                if grid!=metadata[name].get('importer',{}).get('sizeGrid'):continue
                with Image.open(original) as source,Image.open(images/name) as current:
                    matches=np.array_equal(candidate.crop(np.asarray(source.convert('RGBA'))),np.asarray(current.convert('RGBA')))
                if matches:identities[name]=pixel_identity(original)
    return identities
