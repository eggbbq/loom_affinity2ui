import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from affinity2ui.audit import audit
from affinity2ui.repair_records import verified_repairs
from affinity2ui.shared_images.provenance import pixel_identity
from ninegrid.candidate import choose_candidate


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


class AuditRepairTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'art/ui/pages/Feature.af';source.parent.mkdir(parents=True);source.write_bytes(b'saved-af')
        assets=root/'client/assets/ui';images=assets/'images';images.mkdir(parents=True)
        records=root/'records';repair=root/'repair';name='ICON_图标.png';uid='fixture-uid'
        rgba=np.full((40,60,4),[20,30,40,255],dtype=np.uint8);rgba[3:-3,4:-4]=[80,90,100,255]
        original=repair/'original.png';original.parent.mkdir();Image.fromarray(rgba).save(original)
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        (repair/'originals').mkdir();original.rename(repair/'originals'/(digest+'.png'))
        original=repair/'originals'/(digest+'.png')
        candidate,_=choose_candidate(rgba)
        Image.fromarray(candidate.crop(rgba)).save(images/name)
        meta={'uuid':uid,'importer':{'textureType':2,'sizeGrid':[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]}}
        write(images/(name+'.meta'),meta)
        item=dict(candidate.fields(),source='assets/ui/images/'+name,output='assets/ui/images/'+name,
                  sourceSha256=digest,sourceMetadata={'uuid':uid},status='candidate',references=[])
        write(repair/'report.json',{'items':[item],'settings':{'algorithmVersion':5}})
        write(repair/'published.json',{'images':[{'file':name,'afterSha256':hashlib.sha256((images/name).read_bytes()).hexdigest(),'metadata':meta}]})
        for filename in ('validation/report.json','resize-validation/report.json'):
            write(repair/filename,{'valid':True,'cases':[{'accepted':True,'source':digest+'.png' if filename=='validation/report.json' else item['source'],
                  'afterRuntime':{'textureSize':item['outputSize'],'sizeGrid':meta['importer']['sizeGrid']}}]})
        write(records/'shared-image-dedupe/index.json',{'aliases':[]})
        write(records/'Feature/affinity.json',{'source':str(source),'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'pages':[{'images':1}],'warnings':[],'images':[{'uuid':uid,'file':name,
              'sourcePixelSha256':pixel_identity(original),'pngSha256':digest,'optimizedImporter':{'textureType':2}}]})
        write(records/'Feature/export-records/ninegrid/report.json',{'settings':{'algorithmVersion':4,'centerSize':1},'items':[]})
        return assets,records,repair,images,meta

    def test_repair_overlays_current_provenance_without_rewriting_history_and_obeys_custom_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets,records,repair,images,meta=self.fixture(root)
            historical=(records/'Feature/affinity.json').read_bytes()
            with self.assertRaises(ValueError):audit(root/'bad.json',project=root/'client',assets=assets,records=records,ignored_names=[])
            for names in ([],['custom']):
                result=audit(root/'audit.json',project=root/'client',assets=assets,records=records,quiet=True,ignored_names=names,repair_records=[repair])
                self.assertEqual(result['engineCases']+result['repairEngineCases'],2)
                self.assertEqual(result['griddedImages'],1)
                self.assertEqual(result['excludedNameContains'],names)
            for names in (['icon'],['图标'],['ICON']):
                with self.assertRaisesRegex(ValueError,'忽略'):
                    audit(root/'bad.json',project=root/'client',assets=assets,records=records,ignored_names=names,repair_records=[repair])
            self.assertEqual((records/'Feature/affinity.json').read_bytes(),historical)

    def test_identical_case_payloads_still_count_distinct_executions_and_directory_aliases_do_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets,records,repair,images,meta=self.fixture(root)
            for filename in ('validation/report.json','resize-validation/report.json'):
                proof=json.loads((repair/filename).read_text())
                proof['cases'].append(dict(proof['cases'][0]))
                write(repair/filename,proof)
            result=audit(root/'audit.json',project=root/'client',assets=assets,records=records,
                         quiet=True,ignored_names=[],repair_records=[repair,repair/'../repair'])
            self.assertEqual(result['engineCases'],0)
            self.assertEqual(result['repairEngineCases'],4)

    def test_shared_engine_reports_count_unique_cases_once_across_repaired_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets,records,repair,images,meta=self.fixture(root)
            name='second.png';uid='second-fixture-uid'
            rgba=np.full((40,60,4),[21,31,41,255],dtype=np.uint8)
            rgba[3:-3,4:-4]=[81,91,101,255]
            original=repair/'second-original.png';Image.fromarray(rgba).save(original)
            digest=hashlib.sha256(original.read_bytes()).hexdigest()
            original.rename(repair/'originals'/(digest+'.png'))
            original=repair/'originals'/(digest+'.png')
            candidate,_=choose_candidate(rgba)
            Image.fromarray(candidate.crop(rgba)).save(images/name)
            second_meta={'uuid':uid,'importer':{'textureType':2,'sizeGrid':[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]}}
            write(images/(name+'.meta'),second_meta)
            item=dict(candidate.fields(),source='assets/ui/images/'+name,output='assets/ui/images/'+name,
                      sourceSha256=digest,sourceMetadata={'uuid':uid},status='candidate',references=[])
            report=json.loads((repair/'report.json').read_text());report['items'].append(item)
            write(repair/'report.json',report)
            published=json.loads((repair/'published.json').read_text())
            published['images'].append({'file':name,'afterSha256':hashlib.sha256((images/name).read_bytes()).hexdigest(),'metadata':second_meta})
            write(repair/'published.json',published)
            for filename in ('validation/report.json','resize-validation/report.json'):
                proof=json.loads((repair/filename).read_text())
                proof['cases'].append({'accepted':True,'source':digest+'.png' if filename=='validation/report.json' else item['source'],
                                      'afterRuntime':{'textureSize':item['outputSize'],'sizeGrid':second_meta['importer']['sizeGrid']}})
                write(repair/filename,proof)
            manifest=json.loads((records/'Feature/affinity.json').read_text())
            manifest['images'].append({'uuid':uid,'file':name,'sourcePixelSha256':pixel_identity(original),
                                       'pngSha256':digest,'optimizedImporter':{'textureType':2}})
            write(records/'Feature/affinity.json',manifest)
            historical=(records/'Feature/affinity.json').read_bytes()
            for directories in ([repair],[repair,repair]):
                result=audit(root/'audit.json',project=root/'client',assets=assets,records=records,
                             quiet=True,ignored_names=[],repair_records=directories)
                self.assertEqual(result['engineCases'],0)
                self.assertEqual(result['repairEngineCases'],4)
                self.assertEqual(result['griddedImages'],2)
            self.assertEqual((records/'Feature/affinity.json').read_bytes(),historical)

    def test_corrupted_original_or_failed_engine_proof_cannot_authorize_a_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets,records,repair,images,meta=self.fixture(root)
            metadata={'ICON_图标.png':meta}
            write(repair/'validation/report.json',{'valid':True,'cases':[{'accepted':False}]})
            with self.assertRaisesRegex(ValueError,'引擎证明'):
                verified_repairs([repair],images,metadata)
            write(repair/'validation/report.json',{'valid':True,'cases':[{'accepted':True}]})
            next((repair/'originals').glob('*.png')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'原图备份'):
                verified_repairs([repair],images,metadata)

    def test_later_image_edits_do_not_reuse_old_repair_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets,records,repair,images,meta=self.fixture(root)
            Image.new('RGBA',(10,10),'red').save(images/'ICON_图标.png')
            self.assertEqual(verified_repairs([repair],images,{'ICON_图标.png':meta}),{})
            self.assertEqual(verified_repairs([root/'old-missing-records'],images,{'ICON_图标.png':meta}),{})


if __name__=='__main__':unittest.main()
