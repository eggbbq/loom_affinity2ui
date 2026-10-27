"""Assert legacy serialization identity without installing a PSD backend."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from affinity2ui import prefab
from affinity2ui.image_dedupe import deduplicate_images
from affinity2ui.metadata import preserve_metadata
from build_prefab_golden import run_case,layout_fixture


GOLDEN=Path(__file__).with_name('fixtures')/'legacy_prefab_v1.json'


class PrefabCompatibilityTests(unittest.TestCase):
    def test_current_serializer_matches_historical_json_and_uuid_bytes(self):
        golden=json.loads(GOLDEN.read_text())
        self.assertEqual(golden['layout'],layout_fixture())
        self.assertEqual(golden['originWheelSha256'],'89736bcfe016b1fd3aa1fb5f1cdd257a696e750573e7a059f19b2efc3dba7d68')
        for mode in ('default','preserved'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                actual=run_case(prefab,Path(folder),mode)
                self.assertEqual(actual,golden['cases'][mode])

    def test_invalid_layout_is_rejected_before_writing_assets(self):
        samples=[{'size':[True,240]},{'position':[float('nan'),0]},{'opacity':2},{'component':'UnknownType'}]
        for update in samples:
            with self.subTest(update=update):
                layout=layout_fixture();layout['children'][0].update(update)
                with self.assertRaises(ValueError):prefab.validate_layout(layout)
        for asset in ('../escape.png','/escape.png','parts\\escape.png','http://host/a.png'):
            layout=layout_fixture();layout['children'][0]['asset']=asset
            with self.subTest(asset=asset),self.assertRaises(ValueError):prefab.validate_layout(layout)

    def test_dedupe_remains_size_aware_nontransitive_and_transparent_rgb_aware(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            samples=[('a.png',(3,3),(10,20,30,255)),('b.png',(3,3),(10,20,30,255)),
                     ('c.png',(3,3),(12,20,30,255)),('d.png',(3,3),(14,20,30,255)),
                     ('different_size.png',(4,3),(10,20,30,255)),
                     ('transparent_a.png',(3,3),(0,0,0,0)),('transparent_b.png',(3,3),(255,0,0,0))]
            for name,size,color in samples:Image.new('RGBA',size,color).save(root/name)
            layout={'children':[{'type':'image','asset':name} for name,_,_ in samples]}
            result=deduplicate_images(layout,root,.99)
            self.assertEqual(result,{'b.png':'a.png','c.png':'a.png'})
            self.assertEqual([n['asset'] for n in layout['children']],
                ['a.png','a.png','a.png','d.png','different_size.png','transparent_a.png','transparent_b.png'])

    def test_metadata_copy_keeps_existing_uuid_and_custom_importer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'old';new=root/'new'
            old.mkdir();new.mkdir()
            Image.new('RGBA',(2,2),'red').save(new/'bg.png')
            original='{"uuid":"11111111-1111-4111-8111-111111111111","importer":{"filterMode":0},"custom":true}\n'
            (old/'bg.png.meta').write_text(original)
            (old/'deleted.png.meta').write_text('{"keep":"unused"}')
            preserve_metadata(new,old)
            self.assertEqual((new/'bg.png.meta').read_text(),original)
            self.assertFalse((new/'deleted.png.meta').exists())


if __name__=='__main__':unittest.main()
