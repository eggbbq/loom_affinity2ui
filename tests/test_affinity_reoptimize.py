import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from affinity2ui.reoptimize import original_pixels,reoptimize
from affinity2ui.repair_records import verified_repairs
from affinity2ui.exporter import directory_identity
from ninegrid.candidate import choose_candidate


class ReoptimizationTests(unittest.TestCase):
    def test_repair_output_cannot_replace_project_or_primary_export_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=root/'client';project.mkdir()
            (project/'keep.txt').write_text('keep project')
            records=root/'records';(records/'Feature').mkdir(parents=True)
            (records/'Feature/affinity.json').write_text('{"preserve":"old record"}')
            before=directory_identity(root)
            for target in (project,root,records):
                with self.subTest(target=target),self.assertRaises(ValueError):
                    reoptimize(project,[],target)
                self.assertEqual(directory_identity(root),before)

    def test_verified_repair_survives_file_rename_with_same_uuid(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);records=root/'repair';images=root/'images'
            images.mkdir();(records/'originals').mkdir(parents=True)
            rgba=np.full((24,64,4),[70,40,90,255],dtype=np.uint8)
            rgba[3:-3,3:-3]=[25,200,40,255]
            candidate,_=choose_candidate(rgba)
            original=records/'source.png';Image.fromarray(rgba).save(original)
            digest=hashlib.sha256(original.read_bytes()).hexdigest()
            original.rename(records/'originals'/(digest+'.png'))
            image=images/'bg@0000000000000.png';Image.fromarray(candidate.crop(rgba)).save(image)
            metadata={'uuid':'fixture','importer':{'sizeGrid':[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]}}
            (records/'published.json').write_text(json.dumps({'images':[{'file':'bg@old@long.png',
                'metadata':metadata,'afterSha256':hashlib.sha256(image.read_bytes()).hexdigest()}]}))
            (records/'report.json').write_text(json.dumps({'settings':{},'items':[
                dict(candidate.fields(),status='candidate',source='assets/ui/images/bg@old@long.png',
                     sourceSha256=digest,sourceMetadata={'uuid':'fixture'})]}))
            for name in ('validation','resize-validation'):
                (records/name).mkdir()
                source = digest+'.png' if name=='validation' else 'assets/ui/images/bg@old@long.png'
                (records/name/'report.json').write_text(json.dumps({'valid':True,'cases':[{'accepted':True,
                    'source':source,'afterRuntime':{'textureSize':list(candidate.crop(rgba).shape[1::-1]),
                    'sizeGrid':metadata['importer']['sizeGrid']}}]}))
            self.assertIn('fixture',verified_repairs([records],images,{image.name:metadata}))

    def test_existing_crop_is_restored_only_from_matching_verified_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'originals').mkdir()
            rgba=np.full((24,64,4),[70,40,90,255],dtype=np.uint8)
            rgba[3:-3,3:-3]=[25,200,40,255]
            candidate,_=choose_candidate(rgba)
            original=root/'source.png';Image.fromarray(rgba).save(original)
            content=original.read_bytes();digest=hashlib.sha256(content).hexdigest()
            (root/'originals'/(digest+'.png')).write_bytes(content)
            metadata={'uuid':'fixture','importer':{'sizeGrid':[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]}}
            (root/'report.json').write_text(json.dumps({'items':[dict(candidate.fields(),sourceSha256=digest,sourceMetadata={'uuid':'fixture'})]}))
            image=root/'cropped.png';Image.fromarray(candidate.crop(rgba)).save(image)
            self.assertEqual(original_pixels(image,metadata,[root]),content)
            changed=candidate.crop(rgba).copy();changed[0,0]=[255,0,0,255];Image.fromarray(changed).save(image)
            with self.assertRaisesRegex(ValueError,'匹配'):
                original_pixels(image,metadata,[root])

    def test_failed_optimization_does_not_publish_any_image_or_prefab(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=root/'project';images=project/'assets/ui/images';images.mkdir(parents=True)
            source=images/'fill.png';Image.new('RGBA',(30,20),'green').save(source)
            meta=images/'fill.png.meta';meta.write_text(json.dumps({'uuid':'fixture','importer':{'textureType':2}}))
            scene=project/'assets/Root.lh';scene.write_text(json.dumps({'_$ver':1,'_$id':'root','_$type':'GWidget'}))
            (project/'Fixture.laya').write_text('{"version":"3.4.2"}')
            before={p:p.read_bytes() for p in (source,meta,scene)}
            with patch('affinity2ui.reoptimize.optimize',side_effect=ValueError('engine rejected')):
                with self.assertRaisesRegex(ValueError,'engine rejected'):
                    reoptimize(project,[source],root/'records')
            self.assertEqual({p:p.read_bytes() for p in before},before)
            self.assertFalse((root/'records').exists())


if __name__=='__main__':unittest.main()
