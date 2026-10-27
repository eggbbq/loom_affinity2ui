import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from affinity2ui.ninegrid_references import references,native_ui_references
from ninegrid.laya.references import unsafe_reason


def image(uid):
    return {'_$id':uid,'_$type':'GImage','src':'res://background','width':10,'height':10,'autoSize':False}


def project(node):
    return SimpleNamespace(scenes={'assets/Test.lh':node},resolve_reference=lambda value:Path('/tmp/background.png'))


class NativeNineGridTests(unittest.TestCase):
    def test_native_containers_and_plain_progress_images_are_eligible(self):
        root={'_$id':'root','_$type':'GWidget','_$child':[
            {'_$id':'button','_$type':'GButton','downEffect':1,'_$child':[image('button-bg')]},
            {'_$id':'list','_$type':'GList','layout':{'type':1,'stretchX':0,'stretchY':0},'_$child':[
                {'_$id':'row','_$type':'GWidget','_$child':[image('row-bg')]}]},
            {'_$id':'progress','_$type':'GProgressBar','hBar':{'_$ref':'fill'},'_$child':[image('progress-bg'),image('fill')]},
        ]}
        refs={ref.id:ref for ref in references(project(root))}
        for name in ('button-bg','row-bg','progress-bg','fill'):
            self.assertIsNone(unsafe_reason(refs[name],[10,10]),name)

    def test_scripts_masks_stretching_and_non_integer_visual_edges_remain_blocked(self):
        variants=[{'_$comp':[{'_$type':'custom-script'}]}, {'mask':{'_$ref':'mask'}},
                  {'gears':[{'propPath':'src'}]}, {'scaleX':1.1}, {'x':.25},
                  {'_$type':'GList','layout':{'type':1,'stretchX':1}}, {'_$type':'CustomWidget'},
                  {'_$type':'GMovieClip'}]
        for settings in variants:
            with self.subTest(settings=settings):
                root={'_$id':'root','_$type':'GWidget','_$child':[image('bg')],**settings}
                ref=references(project(root))[0]
                self.assertIsNotNone(unsafe_reason(ref,[10,10]))

    def test_centered_odd_button_with_integer_visual_edges_is_eligible(self):
        root={'_$id':'button','_$type':'GButton','width':11,'height':11,
              'anchorX':.5,'anchorY':.5,'x':5.5,'y':5.5,'_$child':[image('bg')]}
        before=copy.deepcopy(root)
        self.assertIsNone(unsafe_reason(references(project(root))[0],[10,10]))
        self.assertEqual(root,before)

    def test_ide_serialized_progress_fill_reference_is_eligible(self):
        root={'_$id':'progress','_$type':'GProgressBar','_hBar':{'_$ref':'fill'},
              '_$child':[image('bg'),image('fill')]}
        refs={ref.id:ref for ref in references(project(root))}
        self.assertIsNone(unsafe_reason(refs['bg'],[10,10]))
        self.assertIsNone(unsafe_reason(refs['fill'],[10,10]))

    def test_progress_mesh_and_unknown_fill_implementations_remain_guarded(self):
        for settings in ({'mesh':{'_$type':'ProgressMesh'}},{'_$type':'GLoader'},
                         {'_$comp':[{'_$type':'custom-script'}]}):
            root={'_$id':'progress','_$type':'GProgressBar','hBar':{'_$ref':'fill'},
                  '_$child':[{**image('fill'),**settings}]}
            self.assertIsNotNone(unsafe_reason(references(project(root))[0],[10,10]))

    def test_native_slider_vertical_image_is_eligible(self):
        root={'_$id':'slider','_$type':'GSlider','vBar':{'_$ref':'fill'},'_$child':[image('fill')]}
        self.assertIsNone(unsafe_reason(references(project(root))[0],[10,10]))

    def test_native_page_geometry_relations_allow_reoptimization(self):
        relation={'_$type':'Relation','target':{'_$ref':'page'},'data':[1,0,2,0,6,0,13,0]}
        root={'_$id':'content','_$type':'GWidget','relations':[relation],'_$child':[image('bg')]}
        self.assertIsNone(unsafe_reason(references(project(root))[0],[10,10]))
        relation['data']=[999,0]
        self.assertIsNotNone(unsafe_reason(references(project(root))[0],[10,10]))

    def test_reference_policy_is_scoped_and_restored_on_failure(self):
        from ninegrid.laya import adapter
        original=adapter.references
        with self.assertRaisesRegex(RuntimeError,'stop'):
            with native_ui_references():
                self.assertIs(adapter.references,references)
                raise RuntimeError('stop')
        self.assertIs(adapter.references,original)


if __name__=='__main__':unittest.main()
