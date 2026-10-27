import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from PIL import Image

from affinity2ui.image_names import ImageNames, SCHEME, flat_image_name
from affinity2ui.image_name_migration import migrate
from affinity2ui.exporter import directory_identity
from affinity2ui.shared_images.pipeline import run


class ImageNameTests(unittest.TestCase):
    def test_hash_is_full_64_bit_blake2b_encoded_as_lowercase_base36(self):
        path = 'Task/content/head/bg_btn.png'
        name = flat_image_name(path)
        encoded = name.removeprefix('bg_btn@').removesuffix('.png')
        self.assertRegex(encoded, r'^[0-9a-z]{13}$')
        self.assertEqual(int(encoded, 36), int.from_bytes(hashlib.blake2b(path.encode(), digest_size=8).digest(), 'big'))
        self.assertEqual(name, flat_image_name(path))

    def test_relative_paths_normalize_slashes_and_unicode_but_preserve_case(self):
        self.assertEqual(flat_image_name(r'Task\content\bg.png'), flat_image_name('Task/content/bg.png'))
        self.assertEqual(flat_image_name('Task/cafe\u0301/bg.png'), flat_image_name('Task/caf\u00e9/bg.png'))
        self.assertNotEqual(flat_image_name('Task/bg.png'), flat_image_name('task/bg.png'))
        for path in ('/Task/bg.png', '../Task/bg.png', 'Task/../bg.png', 'Task//bg.png', 'C:/Task/bg.png'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                flat_image_name(path)

    def test_collision_extends_only_new_name_and_remains_stable_from_records(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory); (records/'A').mkdir()
            with patch('affinity2ui.image_names.path_digest', side_effect=lambda path,size:bytes(size)):
                names = ImageNames()
                old = names.name('A/bg.png'); new = names.name('B/bg.png')
                self.assertEqual(old, 'bg@0000000000000.png')
                self.assertEqual(new, 'bg@0000000000000000.png')
                (records/'A/affinity.json').write_text(json.dumps({'imageNaming':SCHEME, 'images':[
                    {'sourcePath':'A/bg.png','file':old}, {'sourcePath':'B/bg.png','file':new}]}))
                restored = ImageNames(records)
                self.assertEqual(restored.name('B/bg.png'), new)
                self.assertEqual(restored.name('A/bg.png'), old)

    def test_untracked_existing_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory)
            with patch('affinity2ui.image_names.path_digest', side_effect=lambda path,size:bytes(size)):
                (images/'bg@0000000000000.png').touch()
                self.assertEqual(ImageNames(images=images).name('A/bg.png'), 'bg@0000000000000000.png')


class MigrationTests(unittest.TestCase):
    def setup_project(self, root):
        project = root/'client'; assets = project/'assets/ui'; records = root/'records'
        images, prefabs = assets/'images', assets/'prefabs'
        images.mkdir(parents=True); prefabs.mkdir()
        items = []
        for feature in ('A', 'B'):
            old = f'bg@{feature}.png'; uid = str(uuid.uuid5(uuid.NAMESPACE_URL, old))
            Image.new('RGBA', (3,3), 'red').save(images/old)
            meta = {'uuid':uid,'importer':{'textureType':2,'sizeGrid':[1,1,1,1,0]}}
            (images/(old+'.meta')).write_text(json.dumps(meta))
            (prefabs/(feature+'.lh')).write_text(json.dumps({'_$id':feature,'_$type':'GImage','src':'res://'+uid}))
            item = {'file':old,'sourcePath':feature+'/content/bg.png','uuid':uid}
            folder = records/feature; folder.mkdir(parents=True)
            (folder/'affinity.json').write_text(json.dumps({'images':[item]}))
            items.append(item)
        run(project, assets, records/'shared-image-dedupe', preferred=[items[0]['file']])
        return project, assets, records, items

    def test_migrate_preserves_png_metadata_prefabs_and_alias_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            project, assets, records, items = self.setup_project(Path(directory))
            before_prefabs = directory_identity(assets/'prefabs')
            png = (assets/'images'/items[0]['file']).read_bytes()
            meta = (assets/'images'/(items[0]['file']+'.meta')).read_bytes()
            state_before = json.loads((records/'shared-image-dedupe/index.json').read_text())
            result = migrate(project, assets, records, apply=True)
            self.assertEqual(result['renamedImages'], 1)
            name = flat_image_name(items[0]['sourcePath'])
            self.assertEqual((assets/'images'/name).read_bytes(), png)
            self.assertEqual((assets/'images'/(name+'.meta')).read_bytes(), meta)
            self.assertEqual(directory_identity(assets/'prefabs'), before_prefabs)
            self.assertFalse((assets/'images'/items[0]['file']).exists())
            state = json.loads((records/'shared-image-dedupe/index.json').read_text())
            alias = state['aliases'][0]
            self.assertEqual(alias['file'], flat_image_name(items[1]['sourcePath']))
            self.assertEqual(alias['canonicalFile'], name)
            self.assertEqual(alias['metadata'], state_before['aliases'][0]['metadata'])
            for item in items:
                manifest = json.loads((records/item['sourcePath'][0]/'affinity.json').read_text())
                self.assertEqual(manifest['images'][0]['uuid'], item['uuid'])
                self.assertEqual(manifest['images'][0]['file'], flat_image_name(item['sourcePath']))
            snapshot = {p:directory_identity(p) for p in (assets, records)}
            self.assertEqual(migrate(project, assets, records, apply=True)['renamedImages'], 0)
            self.assertEqual({p:directory_identity(p) for p in snapshot}, snapshot)
            run(project, assets, records/'shared-image-dedupe', restore_only=True)
            self.assertEqual((assets/'images'/alias['file']).read_bytes(), png)
            self.assertFalse((assets/'images'/items[1]['file']).exists())
            result = run(project, assets, records/'shared-image-dedupe', preferred=[name])
            self.assertEqual(result['aliases'], {alias['file']: name})

    def test_preview_and_publish_failure_leave_live_resources_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            project, assets, records, _ = self.setup_project(Path(directory))
            snapshot = {p:directory_identity(p) for p in (assets, records)}
            migrate(project, assets, records)
            self.assertEqual({p:directory_identity(p) for p in snapshot}, snapshot)
            with patch('affinity2ui.image_name_migration.publish_bundles', side_effect=OSError('failure')):
                with self.assertRaises(OSError):migrate(project, assets, records, apply=True)
            self.assertEqual({p:directory_identity(p) for p in snapshot}, snapshot)

    def test_path_consumers_block_rename_instead_of_breaking_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            project, assets, records, items = self.setup_project(Path(directory))
            (project/'src').mkdir()
            (project/'src/use.ts').write_text('const image="ui/images/'+items[0]['file']+'";')
            before = directory_identity(assets)
            with self.assertRaisesRegex(ValueError, '旧文件名引用'):
                migrate(project, assets, records, apply=True)
            self.assertEqual(directory_identity(assets), before)


if __name__ == '__main__':unittest.main()
