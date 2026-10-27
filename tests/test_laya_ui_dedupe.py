import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import hashlib

from PIL import Image
from affinity2ui.shared_images.pipeline import run,identity,commit


def uid(name):return str(uuid.uuid5(uuid.NAMESPACE_URL,name))

def write_image(images,name,color=(80,20,160,255),grid=(1,1,1,1,0)):
    Image.new('RGBA',(3,3),color).save(images/name)
    (images/(name+'.meta')).write_text(json.dumps({'uuid':uid(name),'importer':{
        'textureType':2,'sizeGrid':list(grid),'filterMode':1}}))

def write_prefab(prefabs,name,image_name):
    data={'_$ver':1,'_$id':name,'_$type':'GWidget','name':name,
          '_$child':[{'_$id':name+'-image','_$type':'GImage','name':'bg','x':17,'y':23,
                      'width':300,'height':100,'src':'res://'+uid(image_name),'autoSize':False}]}
    (prefabs/(name+'.lh')).write_text(json.dumps(data))


class SharedImageTests(unittest.TestCase):
    def setup_project(self,folder):
        project=folder/'client';assets=project/'assets/ui';images=assets/'images';prefabs=assets/'prefabs'
        images.mkdir(parents=True);prefabs.mkdir()
        write_image(images,'z_old.png');write_image(images,'a_new.png')
        write_prefab(prefabs,'OldPanel','z_old.png');write_prefab(prefabs,'NewPanel','a_new.png')
        return project,assets,folder/'state'

    def test_existing_image_wins_and_all_laya_references_follow_it(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            before=json.loads((assets/'prefabs/NewPanel.lh').read_text())
            result=run(project,assets,state,preferred=['z_old.png'])
            self.assertEqual(result['mergedImages'],1)
            self.assertTrue((assets/'images/z_old.png').exists())
            self.assertFalse((assets/'images/a_new.png').exists())
            actual=json.loads((assets/'prefabs/NewPanel.lh').read_text())
            expected=copy.deepcopy(before);expected['_$child'][0]['src']='res://'+uid('z_old.png')
            self.assertEqual(actual,expected)
            alias=json.loads((state/'index.json').read_text())['aliases'][0]
            self.assertEqual(alias['uuid'],uid('a_new.png'))
            self.assertTrue((state/'blobs'/alias['blob']).exists())
            snapshot={p:identity(p) for p in (assets/'images',assets/'prefabs',state)}
            run(project,assets,state)
            self.assertEqual({p:identity(p) for p in snapshot},snapshot)

    def test_old_shared_source_can_change_without_replacing_another_pages_art(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            run(project,assets,state,preferred=['z_old.png'])
            run(project,assets,state,restore_only=True)
            self.assertEqual(json.loads((assets/'prefabs/NewPanel.lh').read_text())['_$child'][0]['src'],
                             'res://'+uid('a_new.png'))
            write_image(assets/'images','z_old.png',color=(200,10,10,255))
            run(project,assets,state,preferred=['z_old.png'])
            self.assertTrue((assets/'images/a_new.png').exists())
            self.assertEqual(Image.open(assets/'images/a_new.png').getpixel((0,0)),(80,20,160,255))
            self.assertEqual(Image.open(assets/'images/z_old.png').getpixel((0,0)),(200,10,10,255))

    def test_standalone_pass_also_splits_alias_after_the_old_page_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            run(project,assets,state,preferred=['z_old.png'])
            write_image(assets/'images','z_old.png',color=(200,10,10,255))
            run(project,assets,state,fresh_prefabs=['OldPanel.lh'])
            self.assertEqual(json.loads((assets/'prefabs/NewPanel.lh').read_text())['_$child'][0]['src'],
                             'res://'+uid('a_new.png'))
            self.assertEqual(Image.open(assets/'images/a_new.png').getpixel((0,0)),(80,20,160,255))

    def test_sprite_sampling_and_grid_differences_are_not_merged(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            write_image(assets/'images','a_new.png',grid=(0,1,0,1,0))
            self.assertEqual(run(project,assets,state)['mergedImages'],0)

    def test_verified_original_identity_merges_different_ninegrid_crops(self):
        from ninegrid.visual import VisualCandidate
        import numpy as np
        from affinity2ui.shared_images.provenance import pixel_identity
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            original=Path(directory)/'original.png'
            rgba=np.full((20,50,4),[50,70,90,255],dtype=np.uint8)
            rgba[:,:3]=[10,20,30,255];rgba[:,-3:]=[10,20,30,255]
            Image.fromarray(rgba).save(original)
            items=[]
            for name,band,center in [('z_old.png',(3,47,25),8),('a_new.png',(5,45,25),1)]:
                candidate=VisualCandidate((50,20),band,None,center)
                image=assets/'images'/name;Image.fromarray(candidate.crop(rgba)).save(image)
                meta=json.loads((assets/'images'/(name+'.meta')).read_text())
                meta['importer']['sizeGrid']=[candidate.margins[k] for k in ('top','right','bottom','left','repeat')]
                (assets/'images'/(name+'.meta')).write_text(json.dumps(meta))
                items.append(dict(file=name,uuid=meta['uuid'],sourcePixelSha256=pixel_identity(original),
                                  pngSha256=hashlib.sha256(image.read_bytes()).hexdigest(),optimizedImporter=meta['importer']))
            records=Path(directory)/'Feature';records.mkdir()
            manifest=records/'affinity.json';manifest.write_text(json.dumps({'images':items}))
            before=json.loads((assets/'prefabs/NewPanel.lh').read_text())
            result=run(project,assets,state,preferred=['z_old.png'])
            self.assertEqual(result['aliases'],{'a_new.png':'z_old.png'})
            actual=json.loads((assets/'prefabs/NewPanel.lh').read_text())
            before['_$child'][0]['src']='res://'+uid('z_old.png')
            self.assertEqual(actual,before)
            manifest.unlink()
            # Identity survives a restore/remerge cycle without the export manifest.
            self.assertEqual(run(project,assets,state)['mergedImages'],1)
            # User-edited optimized pixels invalidate the old original identity.
            run(project,assets,state,restore_only=True)
            Image.new('RGBA',(20,20),'red').save(assets/'images/a_new.png')
            self.assertEqual(run(project,assets,state)['mergedImages'],0)

    def test_standalone_without_inventory_prefers_older_image(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            os.utime(assets/'images/z_old.png',ns=(1,1))
            result=run(project,assets,state)
            self.assertEqual(result['aliases'],{'a_new.png':'z_old.png'})

    def test_state_cannot_enclose_project(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            before=identity(assets)
            with self.assertRaises(ValueError):run(project,assets,Path(directory))
            self.assertEqual(identity(assets),before)

    def test_fresh_consumers_do_not_require_or_restore_missing_old_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            run(project,assets,state,preferred=['z_old.png'])
            for name in ('z_old.png','z_old.png.meta'):(assets/'images'/name).unlink()
            write_image(assets/'images','replacement.png')
            write_image(assets/'images','a_new.png')
            write_prefab(assets/'prefabs','OldPanel','replacement.png')
            write_prefab(assets/'prefabs','NewPanel','a_new.png')
            result=run(project,assets,state,fresh_prefabs=['OldPanel.lh','NewPanel.lh'])
            self.assertEqual(result['mergedImages'],1)
            self.assertFalse((assets/'images/z_old.png').exists())

    def test_all_af_export_can_rebuild_an_empty_image_directory(self):
        from affinity2ui.orchestration import SharedImageStep
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project,assets,state=self.setup_project(root)
            records=root/'records';(records/'shared-image-dedupe').mkdir(parents=True)
            (records/'shared-image-dedupe/index.json').write_text('{}')
            for p in (assets/'images').iterdir():p.unlink()
            step=SharedImageStep(root,project,assets,records,.99)
            with patch.object(step,'invoke') as invoke:step.prepare(rebuilding_all=True)
            invoke.assert_not_called()

    def test_external_script_uuid_and_path_references_prevent_removal(self):
        for value in ('res://'+uid('a_new.png'),'ui/images/a_new.png'):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as directory:
                project,assets,state=self.setup_project(Path(directory))
                (project/'src').mkdir();(project/'src/use-image.ts').write_text('const image='+json.dumps(value))
                self.assertEqual(run(project,assets,state,preferred=['z_old.png'])['mergedImages'],0)
                self.assertTrue((assets/'images/a_new.png').exists())

    def test_unrecognized_serialized_reference_prevents_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            p=assets/'prefabs/NewPanel.lh';data=json.loads(p.read_text());data['dataSource']='res://'+uid('a_new.png')
            p.write_text(json.dumps(data))
            self.assertEqual(run(project,assets,state,preferred=['z_old.png'])['mergedImages'],0)

    def test_missing_backup_does_not_modify_project(self):
        with tempfile.TemporaryDirectory() as directory:
            project,assets,state=self.setup_project(Path(directory))
            run(project,assets,state,preferred=['z_old.png'])
            alias=json.loads((state/'index.json').read_text())['aliases'][0]
            (state/'blobs'/alias['blob']).unlink()
            before=identity(assets)
            with self.assertRaises(ValueError):run(project,assets,state)
            self.assertEqual(identity(assets),before)

    def test_publish_failure_rolls_back_images_prefabs_and_state_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pairs=[]
            for name in ('images','prefabs','state'):
                old=root/('old-'+name);new=root/('new-'+name);old.mkdir();new.mkdir()
                (old/'value').write_text('old');(new/'value').write_text('new');pairs.append((new,old))
            rename=Path.rename;calls=0
            def fail_once(path,target):
                nonlocal calls
                calls+=1
                if calls==5:raise OSError('simulated publish failure')
                return rename(path,target)
            with patch.object(Path,'rename',fail_once),self.assertRaises(OSError):commit(pairs,root/'rollback')
            for _,old in pairs:self.assertEqual((old/'value').read_text(),'old')

    def test_orchestrator_calls_separate_program_with_old_image_inventory(self):
        from affinity2ui.orchestration import SharedImageStep
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project,assets,state=self.setup_project(root)
            records=root/'records';(records/'shared-image-dedupe').mkdir(parents=True)
            (records/'shared-image-dedupe/index.json').write_text('{}')
            calls=[]
            def capture(command,**options):
                calls.append(command)
                if '--existing-images' in command:
                    names=json.loads(Path(command[command.index('--existing-images')+1]).read_text())
                    self.assertEqual(set(names),{'z_old.png','a_new.png'})
            with patch('affinity2ui.orchestration.subprocess.run',side_effect=capture):
                step=SharedImageStep(root,project,assets,records,.99)
                step.prepare();step.finish([assets/'prefabs/NewPanel.lh'])
            self.assertIn('--restore-only',calls[0])
            self.assertIn('-m',calls[1])
            self.assertTrue(any(part == 'affinity2ui' or part.startswith('affinity2ui.') for part in calls[1]))
            self.assertNotIn(str(root/'dedupe_laya_ui.py'),calls[1])
            self.assertEqual(calls[1][-1],'NewPanel.lh')


if __name__=='__main__':unittest.main()
