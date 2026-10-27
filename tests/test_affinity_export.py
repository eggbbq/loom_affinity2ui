import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from affinity2ui.exporter import discover, export_feature, make_plans
from affinity2ui.layout import LayoutBuilder, page_roots, patch_prefab, pixel_box, position_relation_data


def node(name, children=(), **extra):
    return dict(name=name, kind='GroupNode', box=[0, 0, 64, 64], visibleBox=[0, 0, 64, 64],
                visible=True, opacity=1, indices=[0], effects=False, enclosures=0,
                transform=[1, 0, 0, 0, 1, 0], children=list(children), **extra)


def snapshot(*roots):
    return dict(path='source.af', session='session', dpi=72, tree=node('', roots, **{}))


def page(name='TaskPanel'):
    return node(name, [node('bg', [dict(node('shape'), kind='ShapeNode')]), node('content')])


class LayoutTests(unittest.TestCase):
    def test_multiple_roots_and_required_interfaces(self):
        data = snapshot(page(), page('RewardDialog'))
        data['tree']['kind'] = 'DocumentNode'
        self.assertEqual([x['name'] for x in page_roots(data)], ['TaskPanel', 'RewardDialog'])
        data['tree']['children'][1]['children'].pop()
        with self.assertRaisesRegex(ValueError, 'content/bg'):
            page_roots(data)

    def test_hidden_images_keep_canvas_order_and_interface_names(self):
        root = page()
        icon = node('icon', [dict(node('marker'), kind='ShapeNode')])
        icon['visible'] = False
        root['children'][1]['children'] = [node('quality', [node('img_quality_1', [node('paint')])]), icon]
        builder = LayoutBuilder()
        layout = builder.build(root)
        content = layout['children'][1]
        self.assertEqual([c['name'] for c in content['children']], ['quality', 'icon'])
        self.assertEqual(content['children'][0]['type'], 'container')
        self.assertEqual(content['children'][1]['size'], [64, 64])
        self.assertFalse(content['children'][1]['visible'])
        self.assertEqual(len(builder.jobs), 3)

    def test_editable_text_cannot_be_baked_into_picture(self):
        root = page()
        root['children'][0]['children'].append(node('title', text='hello'))
        with self.assertRaisesRegex(ValueError, '包含文字'):
            LayoutBuilder().build(root)

    def test_hidden_switch_retains_local_child_visibility(self):
        root = page()
        off = node('off', [node('image_off', [node('paint')])])
        on = node('on', [node('image_on', [node('paint')])])
        on['visible'] = False
        root['children'][1]['children'] = [node('switch_sound', [off, on])]
        builder = LayoutBuilder()
        layout = builder.build(root)
        control = layout['children'][1]['children'][0]
        self.assertFalse(control['children'][1]['visible'])
        self.assertTrue(control['children'][1]['children'][0]['visible'])
        self.assertEqual(next(c for c in builder.contracts if c['kind'] == 'switch')['visibilityRule'], 'exclusive_on_off')
        on['visible'] = True
        with self.assertRaisesRegex(ValueError, '互斥'):
            LayoutBuilder().build(root)

    def test_duplicate_assets_and_invalid_icons_fail(self):
        root = page()
        root['children'][1]['children'] = [node('img_a', [node('x')]), node('img_a', [node('x')])]
        with self.assertRaisesRegex(ValueError, '重名'):
            LayoutBuilder().build(root)
        root['children'][1]['children'] = [node('icon', [node('x')])]
        root['children'][1]['children'][0]['box'] = [0, 0, 80, 80]
        with self.assertRaisesRegex(ValueError, '2次幂'):
            LayoutBuilder().build(root)

    def test_switch_interaction_is_added_after_static_image_optimization(self):
        self.assert_exclusive_binding_after_optimization('switch')

    def test_tab_interaction_is_added_after_static_image_optimization(self):
        self.assert_exclusive_binding_after_optimization('tab')

    def assert_exclusive_binding_after_optimization(self, kind):
        root = page()
        root['children'][1]['children'] = [node(f'{kind}_sound', [
            node('off', [node('image_off', [node('paint')])]),
            dict(node('on', [node('image_on', [node('paint')])]), visible=False),
        ])]
        class NativeFixture:
            def open(self, source):
                data = snapshot(root); data['tree']['kind'] = 'DocumentNode'; return data
            def script(self, request):
                if request['action'] == 'inspect': return self.open(None)
                for job in request['jobs']:
                    Image.new('RGBA', (64, 64), (50, 60, 70, 255)).save(job['output'])
                return []
        def optimize(project, staged, *args):
            data = json.loads(next(staged.rglob('*.lh')).read_text())
            control = data['_$child'][1]['_$child'][0]
            self.assertNotIn('controllers', control)
            self.assertFalse(control['_$child'][1]['visible'])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); project = folder/'project'; project.mkdir()
            source = folder/'Task.af'; source.write_bytes(b'source')
            with patch('affinity2ui.exporter.optimize', side_effect=optimize) as optimizer:
                result = export_feature(NativeFixture(), source, project, project/'assets/ui',
                                        dedupe=None, records_dir=folder/'records',ninegrid_ignore_names=[])
            optimizer.assert_called_once()
            self.assertEqual(optimizer.call_args.args[-1],[])
            data = json.loads((Path(result['output'])/'TaskPanel.lh').read_text())
            control = data['_$child'][1]['_$child'][0]
            self.assertEqual(control['controllers']['checked']['selectedIndex'], 0)
            self.assertEqual(control['downEffect'], 0)
            self.assertEqual([c['gears'][0]['pages'] for c in control['_$child']], [[0], [1]])

    def test_tab_requires_exclusive_on_off_in_design_plan(self):
        for selected in (False, True):
            root = page()
            control = node('tab_tasks', [node('off'), node('on')])
            root['children'][1]['children'] = [control]
            control['children'][0]['visible'] = not selected
            control['children'][1]['visible'] = selected
            builder = LayoutBuilder()
            builder.build(root)
            contract = next(c for c in builder.contracts if c['kind'] == 'tab')
            self.assertEqual(contract['visibilityRule'], 'exclusive_on_off')
            for invalid in ('both', 'neither', 'missing'):
                with self.subTest(selected=selected, invalid=invalid):
                    broken = copy.deepcopy(root)
                    states = broken['children'][1]['children'][0]['children']
                    if invalid == 'missing': states.pop()
                    else:
                        for state in states: state['visible'] = invalid == 'both'
                    with self.assertRaisesRegex(ValueError, '互斥 on/off'):
                        LayoutBuilder().build(broken)

    def test_fractional_pixel_coverage(self):
        self.assertEqual(pixel_box([0, 336.96, 749.999999, 120]), [0, 336, 750, 457])
        self.assertEqual(pixel_box([94, 470, 63.99999, 64.00001]), [94, 470, 158, 534])

    def test_checkbox_only_binds_on_after_optimization(self):
        root = page()
        root['children'][1]['children'] = [node('checkbox_agreement', [
            node('off', [node('img_off', [node('paint')])]),
            node('on', [node('img_on', [node('paint')])]),
        ])]
        class NativeFixture:
            def open(self, source):
                data = snapshot(root); data['tree']['kind'] = 'DocumentNode'; return data
            def script(self, request):
                if request['action'] == 'inspect': return self.open(None)
                for job in request['jobs']:
                    Image.new('RGBA', (64, 64), (50, 60, 70, 255)).save(job['output'])
                return []
        def optimize(project, staged, *args):
            data = json.loads(next(staged.rglob('*.lh')).read_text())
            control = data['_$child'][1]['_$child'][0]
            self.assertNotIn('controllers', control)
            self.assertTrue(all(c['visible'] for c in control['_$child']))
            self.assertTrue(all('gears' not in c for c in control['_$child']))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); project = folder/'project'; project.mkdir()
            source = folder/'Fixture.json'; source.write_bytes(b'fixture')
            with patch('affinity2ui.exporter.optimize', side_effect=optimize) as optimizer:
                result = export_feature(NativeFixture(), source, project, project/'assets/ui',
                                        dedupe=None, records_dir=folder/'records')
            optimizer.assert_called_once()
            data = json.loads((Path(result['output'])/'TaskPanel.lh').read_text())
            control = data['_$child'][1]['_$child'][0]
            self.assertTrue(control['selected'])
            self.assertNotIn('gears', control['_$child'][0])
            self.assertEqual(control['_$child'][1]['gears'][0]['pages'], [1])
            self.assertEqual(control['downEffect'], 0)

    def test_pixel_grid_quantizes_absolute_edges_without_accumulated_parent_rounding(self):
        root=page();root['box']=[100.4,200.4,750,1334]
        image=node('img_area',[node('paint')]);image['box']=image['visibleBox']=[111.2,222.2,4.4,3.4]
        text=node('title',text='示例',font='Arial',fontSize=20.25,align='left',
                  fill={'color':'#ffffff','alpha':1},runs=[])
        text['box']=[111.49,222.49,5.02,3.02]
        group=node('group',[image,text]);group['box']=[110.98,220.98,20.04,20.04]
        content=root['children'][1];content['children']=[group];content['box']=[110.49,220.49,50.02,40.02]
        untouched=copy.deepcopy(root)
        builder=LayoutBuilder();layout=builder.build(root)
        content=layout['children'][1];group=content['children'][0]
        self.assertEqual(content['position'],[10,20])
        self.assertEqual(content['size'],[51,41])
        self.assertEqual(group['position'],[1,1])
        self.assertEqual(group['size'],[20,20])
        image,text=group['children']
        self.assertEqual(image['position'],[0,1])
        self.assertEqual(image['size'],[5,4])
        self.assertEqual(builder.jobs[-1]['node']['size'],[5,4])
        self.assertEqual(text['fontSize'],20.25)
        self.assertEqual(root,untouched)
        original=LayoutBuilder(pixel_grid=False).build(root)
        self.assertAlmostEqual(original['children'][1]['position'][0],10.09)
        self.assertAlmostEqual(original['children'][1]['children'][0]['position'][0],.49)

    def test_pixel_grid_rounds_shared_boundaries_symmetrically_and_keeps_nonempty_regions(self):
        from affinity2ui.pixel_grid import nearest_pixel,quantize_box
        self.assertEqual([nearest_pixel(v) for v in [-2.5,-1.5,-.5,.5,1.5,2.5]],[-3,-2,-1,1,2,3])
        left=quantize_box([.2,.2,10.3,4.2]);right=quantize_box([10.5,.2,10.3,4.2])
        self.assertEqual(left[0]+left[2],right[0])
        self.assertEqual(quantize_box([.1,.1,.1,.1]),[0,0,1,1])
        self.assertEqual(quantize_box([.1,.1,0,0]),[0,0,0,0])
        with self.assertRaises(ValueError):
            quantize_box([0,0,-1,10])

    def test_pixel_grid_keeps_inferred_list_spacing_on_integer_pixels(self):
        from affinity2ui.list_layout import infer_list
        data=dict(name='vlist_tasks',size=[100,100],children=[
            dict(name=f'item_{i}',position=[0,y],size=[10,10]) for i,y in enumerate([0,12,25])])
        original=infer_list(data)
        quantized=infer_list(data,pixel_grid=True)
        self.assertEqual(original['native']['rowGap'],2.5)
        self.assertEqual(quantized['native']['rowGap'],3)
        self.assertEqual([p[1] for p in quantized['positions'].values()],[0,13,26])

    def test_export_pixel_grid_is_enabled_by_default_and_can_be_disabled(self):
        root=page();root['box']=[0,0,750,1334]
        image=node('img_body',[node('paint')]);image['box']=image['visibleBox']=[0,337,64,64]
        root['children'][1]['box']=[0,336.96,750,997.04]
        root['children'][1]['children']=[image]
        class NativeFixture:
            def open(self,source):
                data=snapshot(root);data['tree']['kind']='DocumentNode';return data
            def script(self,request):
                if request['action']=='inspect':return self.open(None)
                for job in request['jobs']:Image.new('RGBA',(64,64),(50,60,70,255)).save(job['output'])
                return []
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);project=folder/'project';project.mkdir()
            source=folder/'Task.af';source.write_bytes(b'source')
            for enabled,options in [(True,{}),(False,{'pixel_grid':False})]:
                result=export_feature(NativeFixture(),source,project,project/'assets/ui',export_only=True,
                    dedupe=None,records_dir=folder/'records',**options)
                prefab=json.loads((Path(result['output'])/'TaskPanel.lh').read_text())
                content=prefab['_$child'][1]
                self.assertEqual(result['pixelGrid'],enabled)
                self.assertEqual([content['y'],content['height']],[337,997] if enabled else [336.96,997.04])
                self.assertEqual(content['_$child'][0]['width'],64)
                self.assertEqual(content['_$child'][0]['height'],64)

    def test_discovery_excludes_working_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = root / 'pages'; pages.mkdir()
            (pages / 'Task.af').touch()
            outside = root / 'Working.af'; outside.touch()
            self.assertEqual(discover(pages), [(pages / 'Task.af').resolve()])
            with self.assertRaisesRegex(ValueError, '正式'):
                discover(pages, outside)
            (pages / 'Other.af').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, '正式'):
                discover(pages)

    def test_native_controls_keep_static_layout_and_input_alignment(self):
        data = dict(name='input_1', type='container', children=[dict(name='title', type='text', text='abc')])
        prefab = {'_$type': 'GWidget', 'name':'input_1', 'width':100, 'height':40, '_$child': [
            {'_$type':'GTextInput', 'name':'title', 'text':'abc', 'x':10, 'y':5, 'width':80, 'height':30}]}
        patch_prefab(prefab, data)
        self.assertEqual(prefab['_$child'][0]['valign'], 'middle')
        self.assertEqual(prefab['_$type'], 'GWidget')
        self.assertEqual(prefab['name'], 'input_1_node')
        self.assertEqual(prefab['_$child'][0]['name'], 'input_1')
        self.assertEqual(prefab['_$child'][0]['text'], 'abc')
        self.assertEqual(prefab['_$child'][0]['padding'], [5,10,5,10])
        self.assertEqual(prefab['_$child'][0]['x'], 0)
        self.assertEqual(prefab['_$child'][0]['y'], 0)
        self.assertEqual(prefab['_$child'][0]['width'], 100)
        self.assertEqual(prefab['_$child'][0]['height'], 40)
        prefab = {'_$type':'GList', '_$child':[]}
        patch_prefab(prefab, dict(type='container', children=[]))
        self.assertEqual(prefab['layout'], {'type':0})

    def test_button_title_is_bound_and_initialized_from_source_text(self):
        layout = dict(name='btn_login', type='container', children=[
            dict(name='title', type='text', text='登录')])
        prefab = {'_$type':'GButton', '_$child':[
            {'_$id':'login-title', '_$type':'GTextField', 'name':'title', 'text':'登录'}]}
        patch_prefab(prefab, layout)
        self.assertEqual(prefab['titleWidget'], {'_$ref':'login-title'})
        self.assertEqual(prefab['title'], '登录')
        self.assertEqual(prefab['_$child'][0]['text'], '登录')
        # Retrofitting the binding must keep an explicitly edited button title.
        prefab['title'] = '进入游戏'
        patch_prefab(prefab, layout)
        self.assertEqual(prefab['title'], '进入游戏')
        icon_button = {'_$type':'GButton', '_$child':[]}
        patch_prefab(icon_button, dict(type='container', children=[]))
        self.assertNotIn('titleWidget', icon_button)

    def test_scaling_button_effects_center_anchor_without_moving_the_content(self):
        for effect in (2,3):
            with self.subTest(effect=effect):
                layout = dict(type='container', children=[dict(type='image', name='bg')])
                prefab = {'_$type':'GButton', 'x':12, 'y':34, 'width':300, 'height':100,
                          '_$child':[{'_$type':'GImage', 'name':'bg', 'x':7, 'y':9}]}
                original_child = copy.deepcopy(prefab['_$child'][0])
                patch_prefab(prefab, layout, button_down_effect=effect)
                self.assertEqual((prefab['anchorX'],prefab['anchorY']), (.5,.5))
                self.assertEqual((prefab['x'],prefab['y']), (162,84))
                self.assertEqual((prefab['x']-prefab['width']/2, prefab['y']-prefab['height']/2), (12,34))
                self.assertEqual(prefab['_$child'][0], original_child)
                once = copy.deepcopy(prefab)
                patch_prefab(prefab, layout, button_down_effect=effect)
                self.assertEqual(prefab, once)
        plain = {'_$type':'GButton', 'x':12, 'y':34, 'width':300, 'height':100}
        patch_prefab(plain, dict(type='container', children=[]))
        self.assertEqual((plain['x'],plain['y']), (12,34))
        self.assertNotIn('anchorX', plain)

    def test_scaling_button_keeps_rotated_scaled_position_with_existing_pixel_pivot(self):
        from affinity2ui.layout import apply_button_effects
        button = {'_$type':'GButton', 'downEffect':3, 'x':100, 'y':200, 'width':100, 'height':40,
                  'pivotX':10, 'pivotY':5, 'rotation':90, 'scaleX':2, 'scaleY':3}
        apply_button_effects(button)
        self.assertAlmostEqual(button['x'],55)
        self.assertAlmostEqual(button['y'],280)
        self.assertEqual((button['anchorX'],button['anchorY']), (.5,.5))
        self.assertNotIn('pivotX', button)
        self.assertNotIn('pivotY', button)

    def test_export_button_effect_option_reaches_nested_button(self):
        class NativeFixture:
            def open(self, source):
                root = page()
                root['children'][1]['children'] = [node('btn_confirm', [node('bg', [node('paint')])])]
                data = snapshot(root);data['tree']['kind'] = 'DocumentNode'
                return data
            def script(self, request):
                if request['action']=='inspect':
                    return self.open(None)
                for job in request['jobs']:
                    Image.new('RGBA',(64,64),(50,60,70,255)).save(job['output'])
                return []
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory);project = folder/'project';project.mkdir()
            source = folder/'Task.af';source.write_bytes(b'source')
            result = export_feature(NativeFixture(),source,project,project/'assets/ui',export_only=True,
                                    dedupe=None,records_dir=folder/'records',button_down_effect='down-scale')
            prefab = json.loads((Path(result['output'])/'TaskPanel.lh').read_text())
            button = prefab['_$child'][1]['_$child'][0]
            self.assertEqual(button['downEffect'],3)
            self.assertEqual((button['anchorX'],button['anchorY']),(.5,.5))
            self.assertEqual((button['x'],button['y']),(32,32))

    def test_input_wraps_background_and_converts_title_with_native_prompt(self):
        from affinity2ui.layout import map_text_input
        prefab = {'_$type':'GWidget', 'name':'input_account', 'width':480, 'height':92, '_$child':[
            {'_$id':'background', '_$type':'GImage', 'name':'bg', 'src':'res://keep-image'},
            {'_$id':'prompt', '_$type':'GTextField', 'name':'placeholder', 'text':'请输入账号', 'color':'#e5e2d8'},
            {'_$id':'value', '_$type':'GTextInput', 'name':'title', 'text':'示例账号', 'visible':False,
             'x':24, 'y':22, 'width':432, 'height':40, 'fontSize':30, 'color':'#fff9df', 'valign':'middle'},
        ]}
        map_text_input(prefab)
        self.assertEqual(prefab['_$type'], 'GWidget')
        self.assertEqual(prefab['name'], 'input_account_node')
        self.assertEqual([c['name'] for c in prefab['_$child']], ['bg','input_account'])
        input_node = prefab['_$child'][1]
        self.assertEqual(input_node['_$type'], 'GTextInput')
        self.assertEqual(input_node['text'], '')
        self.assertEqual(input_node['prompt'], '请输入账号')
        self.assertEqual(input_node['promptColor'], '#e5e2d8')
        self.assertEqual(input_node['padding'], [22,24,30,24])
        self.assertEqual([input_node[k] for k in ('x','y','width','height')], [0,0,480,92])
        self.assertEqual(input_node['fontSize'], 30)
        self.assertEqual([c['_$id'] for c in prefab['_$child']], ['background','value'])
        self.assertEqual(prefab['_$child'][0]['src'], 'res://keep-image')
        self.assertNotIn('zIndex', prefab['_$child'][0])
        self.assertTrue(input_node['visible'])
        self.assertTrue(input_node['editable'])
        self.assertNotIn('enabled', input_node)
        self.assertNotIn('mouseEnabled', input_node)
        self.assertNotIn('mouseEnabled', prefab['_$child'][0])
        self.assertNotIn('text', prefab)
        input_node['text'] = '用户账号'
        map_text_input(prefab)
        self.assertEqual(prefab['_$child'][1]['text'], '用户账号')

    def test_input_migrates_previous_native_root_without_losing_edited_value(self):
        from affinity2ui.layout import map_text_input
        prefab = {'_$id':'wrapper-id', '_$type':'GTextInput', 'name':'input_password',
            'width':480, 'height':92,
            'text':'edited-value', 'fontSize':32, 'prompt':'请输入密码', 'padding':[22,24,30,24],
            'stackingRoot':True, '_$child':[
                {'_$id':'bg-id', '_$type':'GImage', 'name':'bg', 'zIndex':-1},
                {'_$id':'text-id', '_$type':'GTextInput', 'name':'title', 'visible':False,
                 'text':'sample', 'x':24, 'y':22, 'width':432, 'height':40, 'padding':[0,0,0,0]},
            ]}
        map_text_input(prefab)
        self.assertEqual(prefab['_$id'], 'wrapper-id')
        self.assertEqual(prefab['name'], 'input_password_node')
        self.assertNotIn('text', prefab)
        self.assertNotIn('padding', prefab)
        self.assertNotIn('stackingRoot', prefab)
        self.assertNotIn('zIndex', prefab['_$child'][0])
        actual = prefab['_$child'][1]
        self.assertEqual(actual['_$id'], 'text-id')
        self.assertEqual(actual['text'], 'edited-value')
        self.assertEqual(actual['fontSize'], 32)
        self.assertEqual(actual['prompt'], '请输入密码')
        self.assertEqual(actual['padding'], [22,24,30,24])

    def test_expanding_input_preserves_effective_text_rectangle_and_existing_padding(self):
        from affinity2ui.layout import map_text_input
        original = {'_$id':'input-id', '_$type':'GTextInput', 'name':'input_password',
                    'x':24.5, 'y':22.25, 'width':431, 'height':40.5,
                    'padding':[2,3,4,5], 'text':'edited', 'prompt':'请输入密码'}
        def text_rectangle(node):
            top, right, bottom, left = node['padding']
            return [node['x']+left, node['y']+top,
                    node['width']-left-right, node['height']-top-bottom]
        before = text_rectangle(original)
        wrapper = {'_$type':'GWidget', 'name':'input_password_node', 'width':480, 'height':92,
                   '_$child':[copy.deepcopy(original)]}
        map_text_input(wrapper)
        actual = wrapper['_$child'][0]
        self.assertEqual([actual[k] for k in ('x','y','width','height')], [0,0,480,92])
        self.assertEqual(text_rectangle(actual), before)
        self.assertEqual(actual['text'], 'edited')
        self.assertEqual(actual['prompt'], '请输入密码')
        once = copy.deepcopy(wrapper)
        map_text_input(wrapper)
        self.assertEqual(wrapper, once)

    def test_fresh_export_generates_widget_wrapper_and_native_input(self):
        def text(name, value, visible=True):
            return node(name, text=value, font='Arial', fontSize=20, align='left',
                        fill={'color':'#ffffff','alpha':1}, runs=[])
        root = page('LoginPanel')
        title = text('title', '示例密码'); title['visible'] = False
        title['box'] = title['visibleBox'] = [8,12,40,24]
        root['children'][1]['children'] = [node('input_password', [
            node('bg', [node('paint')]), text('placeholder', '请输入密码'), title])]
        class NativeFixture:
            def open(self, source):
                data = snapshot(root); data['tree']['kind'] = 'DocumentNode'
                return data
            def script(self, request):
                if request['action'] == 'inspect':
                    return self.open(None)
                for job in request['jobs']:
                    Image.new('RGBA', (64,64), (50,60,70,255)).save(job['output'])
                return []
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); project = folder/'project'; project.mkdir()
            source = folder/'LoginPanel.af'; source.write_bytes(b'source')
            result = export_feature(NativeFixture(), source, project, project/'assets/ui',
                export_only=True, dedupe=None, records_dir=folder/'records')
            prefab = json.loads((Path(result['output'])/'LoginPanel.lh').read_text())
            wrapper = prefab['_$child'][1]['_$child'][0]
            self.assertEqual((wrapper['name'], wrapper['_$type']), ('input_password_node','GWidget'))
            self.assertEqual([c['name'] for c in wrapper['_$child']], ['bg','input_password'])
            actual = wrapper['_$child'][1]
            self.assertEqual(actual['_$type'], 'GTextInput')
            self.assertEqual(actual['prompt'], '请输入密码')
            self.assertEqual(actual['text'], '')
            self.assertTrue(actual['visible'])
            self.assertEqual([actual[k] for k in ('x','y','width','height')], [0,0,64,64])
            self.assertEqual(actual['padding'], [12,16,28,8])

    def test_component_parts_bind_names_only_when_the_types_are_compatible(self):
        from affinity2ui.component_parts import bind_component_parts
        button = {'_$type':'GButton', '_$child':[
            {'_$id':'wrong-title', '_$type':'GImage', 'name':'title'},
            {'_$id':'icon', '_$type':'GLoader', 'name':'icon', 'src':'res://icon-texture'},
        ]}
        diagnostics = bind_component_parts(button)
        self.assertNotIn('titleWidget', button)
        self.assertNotIn('title', button)
        self.assertEqual(button['iconWidget'], {'_$ref':'icon'})
        self.assertEqual(button['icon'], 'res://icon-texture')
        self.assertEqual(diagnostics[0][0], 'COMPONENT_PART_TYPE')
        # A matching name nested inside a plain container is another interface.
        label = {'_$type':'GLabel', '_$child':[
            {'_$type':'GWidget', 'name':'content', '_$child':[
                {'_$id':'nested-title', '_$type':'GTextField', 'name':'title'}]},
        ]}
        bind_component_parts(label)
        self.assertNotIn('titleWidget', label)

    def test_range_parts_bind_fill_orientation_grip_and_text(self):
        from affinity2ui.component_parts import bind_component_parts
        for size, expected in [((300,24),'hBar'), ((24,300),'vBar')]:
            with self.subTest(size=size):
                slider = {'_$type':'GSlider', 'width':size[0], 'height':size[1], '_$child':[
                    {'_$id':'fill', '_$type':'GImage', 'name':'img_fill'},
                    {'_$id':'thumb', '_$type':'GImage', 'name':'img_thumb'},
                    {'_$id':'title', '_$type':'GTextField', 'name':'title'},
                ]}
                self.assertEqual(bind_component_parts(slider), [])
                self.assertEqual(slider['_'+expected], {'_$ref':'fill'})
                self.assertEqual(slider['_gripButton'], {'_$ref':'thumb'})
                self.assertEqual(slider['_titleWidget'], {'_$ref':'title'})
                self.assertNotIn('_vBar' if expected=='hBar' else '_hBar', slider)
                self.assertNotIn(expected, slider)
        label = {'_$id':'label', '_$type':'GLabel', 'name':'title', '_$child':[
            {'_$id':'text', '_$type':'GTextField', 'name':'title', 'text':'嵌套标题'}]}
        bind_component_parts(label)
        button = {'_$type':'GButton', '_$child':[label]}
        bind_component_parts(button)
        self.assertEqual(button['titleWidget'], {'_$ref':'label'})
        self.assertEqual(button['title'], '嵌套标题')

    def test_mismatched_component_parts_are_reported_in_export_plan(self):
        root = page()
        root['children'][1]['children'] = [node('btn_login', [node('title', [node('paint')])])]
        builder = LayoutBuilder()
        builder.build(root)
        self.assertTrue(any(w['code']=='COMPONENT_PART_TYPE' and w['path'].endswith('/btn_login')
                            for w in builder.warnings))

    def test_render_failure_preserves_previous_bundle(self):
        class BrokenNative:
            def open(self, source):
                data = snapshot(page());data['tree']['kind'] = 'DocumentNode'
                return data
            def script(self, request):
                raise ValueError('render failed')
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'; project.mkdir()
            source = project / 'Task.af'; source.write_bytes(b'original source')
            assets = project / 'assets/ui'; target = assets / 'Task'; target.mkdir(parents=True)
            (target / 'previous.txt').write_text('preserve me')
            with self.assertRaisesRegex(ValueError, 'render failed'):
                export_feature(BrokenNative(), source, project, assets, export_only=True, records_dir=project.parent / 'records')
            self.assertEqual((target / 'previous.txt').read_text(), 'preserve me')
            self.assertFalse(list(assets.glob('.affinity-export-*')))


    def test_successful_reexport_preserves_metadata(self):
        class NativeFixture:
            def __init__(self):
                self.data = snapshot(page())
                self.data['tree']['kind'] = 'DocumentNode'
            def open(self, source):
                return copy.deepcopy(self.data)
            def script(self, request):
                if request['action'] == 'inspect':
                    return copy.deepcopy(self.data)
                for job in request['jobs']:
                    Image.new('RGBA', (64, 64), (50, 60, 70, 255)).save(job['output'])
                return []
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'; project.mkdir()
            source = project / 'Task.af'; source.write_bytes(b'source')
            assets = project / 'assets/ui'
            native = NativeFixture()
            result = export_feature(native, source, project, assets, export_only=True, records_dir=project.parent / 'records')
            target = Path(result['output'])
            meta = target / 'TaskPanel.lh.meta'
            data = json.loads(meta.read_text()); data['uuid'] = 'af30101c-6d87-437c-a4fb-7a750e110598'
            data['custom'] = 'preserve'
            meta.write_text(json.dumps(data))
            from affinity2ui.image_names import flat_image_name
            png_meta = assets / ('images/' + flat_image_name('Task/TaskPanel/bg.png') + '.meta')
            original_png_meta = json.loads(png_meta.read_text())
            original_png_meta.setdefault('importer', {})['sizeGrid'] = [1,1,1,1,0]
            original_png_meta['importer']['filterMode'] = 0
            original_png_meta['importer']['textureType'] = 0
            png_meta.write_text(json.dumps(original_png_meta))
            def verify_optimization_order(stage_project, staged, *unused):
                staged_prefab=json.loads((staged/'TaskPanel/TaskPanel.lh').read_text())
                self.assertNotIn('relations',staged_prefab['_$child'][0])
                staged_meta=json.loads((staged/'TaskPanel/bg.png.meta').read_text())
                self.assertNotIn('sizeGrid',staged_meta['importer'])
                self.assertEqual(staged_meta['importer']['textureType'],2)
            with patch('affinity2ui.exporter.optimize',side_effect=verify_optimization_order) as optimize:
                export_feature(native, source, project, assets, export_only=False, records_dir=project.parent / 'records')
                optimize.assert_called_once()
            new_png_meta = json.loads(png_meta.read_text())
            self.assertEqual(new_png_meta['uuid'], original_png_meta['uuid'])
            self.assertEqual(new_png_meta['importer']['filterMode'], 0)
            self.assertEqual(new_png_meta['importer']['textureType'],2)
            self.assertNotIn('sizeGrid', new_png_meta['importer'])
            self.assertEqual(json.loads(meta.read_text()), data)
            prefab = json.loads((target / 'TaskPanel.lh').read_text())
            self.assertEqual(prefab['name'], 'TaskPanel')
            self.assertEqual(prefab['_$child'][0]['relations'][0]['data'], [1,0,2,0])
            self.assertEqual(source.read_bytes(), b'source')
            self.assertFalse(list(target.rglob('*.json')))
            self.assertTrue((Path(result['records'])/'native.json').is_file())
            self.assertTrue((Path(result['records'])/'TaskPanel/layout.json').is_file())

    def test_version_adapter_requires_matching_engine_and_restores_guard(self):
        from affinity2ui.ninegrid import project_version
        from ninegrid.laya.project import LayaProject
        original = LayaProject.SUPPORTED
        with tempfile.TemporaryDirectory() as directory:
            libraries = Path(directory)
            (libraries / 'laya.core.js').write_text('LayaEnv.version = "3.4.2";')
            with self.assertRaisesRegex(RuntimeError, 'failure'):
                with project_version('3.4.2', libraries):
                    self.assertIn('3.4.2', LayaProject.SUPPORTED)
                    raise RuntimeError('failure')
            self.assertIs(LayaProject.SUPPORTED, original)
            with self.assertRaisesRegex(ValueError, '不匹配'):
                with project_version('3.4.1', libraries):
                    pass

    def test_changed_source_discards_complete_render(self):
        class ChangingNative:
            def __init__(self, source):
                self.source = source
                self.data = snapshot(page()); self.data['tree']['kind'] = 'DocumentNode'
            def open(self, source):
                return copy.deepcopy(self.data)
            def script(self, request):
                if request['action'] == 'render':
                    for job in request['jobs']:
                        Image.new('RGBA', (64, 64)).save(job['output'])
                    self.source.write_bytes(b'user change')
                    return []
                return copy.deepcopy(self.data)
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'; project.mkdir()
            source = project / 'Task.af'; source.write_bytes(b'original')
            assets = project / 'assets/ui'; target = assets / 'Task'; target.mkdir(parents=True)
            (target / 'previous.txt').write_text('preserve')
            with self.assertRaisesRegex(ValueError, '发生变化'):
                export_feature(ChangingNative(source), source, project, assets, export_only=True, records_dir=project.parent / 'records')
            self.assertEqual((target / 'previous.txt').read_text(), 'preserve')
            self.assertEqual(source.read_bytes(), b'user change')


    def test_visible_ignored_layer_inside_image_cannot_be_baked(self):
        root = page()
        ignored = node('#draft', text='do not bake')
        root['children'][0]['children'].append(ignored)
        with self.assertRaisesRegex(ValueError, '忽略层'):
            LayoutBuilder().build(root)
        ignored['visible'] = False
        self.assertEqual(len(LayoutBuilder().build(root)['children']), 2)

    def test_target_changed_during_render_is_preserved(self):
        class ChangingNative:
            def __init__(self, target):
                self.target = target
                self.data = snapshot(page()); self.data['tree']['kind'] = 'DocumentNode'
            def open(self, source):
                return copy.deepcopy(self.data)
            def script(self, request):
                if request['action'] == 'render':
                    for job in request['jobs']:
                        Image.new('RGBA', (64, 64)).save(job['output'])
                    (self.target / 'previous.txt').write_text('user edit')
                    return []
                return copy.deepcopy(self.data)
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'; project.mkdir()
            source = project / 'Task.af'; source.write_bytes(b'original')
            assets = project / 'assets/ui'; target = assets / 'Task'; target.mkdir(parents=True)
            (target / 'previous.txt').write_text('original')
            with self.assertRaisesRegex(ValueError, '目标资源被修改'):
                export_feature(ChangingNative(target), source, project, assets, export_only=True, records_dir=project.parent / 'records')
            self.assertEqual((target / 'previous.txt').read_text(), 'user edit')


    def test_page_content_and_background_resize_without_changing_component_internals(self):
        layout = dict(type='root', name='LoginPanel', size=[750,1334], children=[
            dict(type='image', name='bg', position=[0,0], size=[750,1334]),
            dict(type='container', name='content', position=[20,40], size=[710,1254], children=[
                dict(type='container', name='btn_login', position=[300,1100], size=[100,50], children=[
                    dict(type='image', name='bg', position=[0,0], size=[100,50])]),
            ]),
        ])
        prefab = {'_$type':'GWidget', '_$id':'page-root', '_$child':[
            {'_$type':'GImage', 'name':'bg'},
            {'_$type':'GWidget', '_$id':'content-id', 'name':'content', '_$child':[
                {'_$type':'GButton', 'name':'btn_login', '_$child':[{'_$type':'GImage', 'name':'bg'}]},
            ]},
        ]}
        patch_prefab(prefab, layout)
        self.assertEqual(prefab['_$child'][0]['relations'], [{
            '_$type':'Relation', 'target':{'_$ref':'page-root'}, 'data':[1,0,2,0],
        }])
        content = prefab['_$child'][1]
        self.assertEqual(content['relations'], [{
            '_$type':'Relation', 'target':{'_$ref':'page-root'}, 'data':[1,0,2,0,6,0,13,0],
        }])
        self.assertNotIn('relations', content['_$child'][0])
        self.assertNotIn('relations', content['_$child'][0]['_$child'][0])

    def test_position_anchors_cover_center_edges_and_corners(self):
        parent = dict(size=[900,1200])
        cases = [
            ([0,0], [3,0,10,0]), ([400,0], [6,0,10,0]), ([800,0], [9,0,10,0]),
            ([0,550], [3,0,13,0]), ([400,550], [6,0,13,0]), ([800,550], [9,0,13,0]),
            ([0,1100], [3,0,16,0]), ([400,1100], [6,0,16,0]), ([800,1100], [9,0,16,0]),
        ]
        for position, expected in cases:
            with self.subTest(position=position):
                self.assertEqual(position_relation_data(dict(position=position,size=[100,100]), parent), expected)

    def test_content_alignment_prioritizes_ten_percent_edges_then_geometric_center(self):
        parent = dict(size=[1000,800])
        cases = [
            ([350,260], [200,200], [6,0,13,0]),
            ([450,340], [200,200], [6,0,13,0]),
            ([0,250], [700,550], [3,0,16,0]),  # centers in middle thirds, but only left/bottom touch
            ([300,0], [700,550], [9,0,10,0]),
            ([50,60], [900,700], [6,0,13,0]),  # both edges near -> center
            ([100,80], [600,440], [3,0,10,0]),  # exactly 10% -> near
            ([100.1,80.1], [600,440], [6,0,13,0]),
            ([101,81], [200,100], [3,0,10,0]),  # no near edges, center outside middle thirds
            ([699,619], [200,100], [9,0,16,0]),
            ([-200,-200], [1000,1200], [3,0,13,0]),  # large overflow is not a touching edge
        ]
        for position,size,expected in cases:
            with self.subTest(position=position,size=size):
                self.assertEqual(position_relation_data(dict(position=position,size=size),parent),expected)
        page = dict(size=[750,1334])
        self.assertEqual(position_relation_data(dict(position=[0,336.96],size=[750,997.04]),page),[6,0,16,0])
        self.assertEqual(position_relation_data(dict(position=[64,390],size=[623,598]),page),[6,0,13,0])
        self.assertEqual(position_relation_data(dict(position=[2,2],size=[4,4]),dict(size=[10,10])),[3,0,10,0])

    def test_explicit_content_alignment_takes_precedence_per_axis(self):
        page = dict(size=[750,1334])
        content = dict(position=[0,336.96],size=[750,997.04],contentAlignment={'y':'center'})
        self.assertEqual(position_relation_data(content,page),[6,0,13,0])
        content['contentAlignment']={'x':'left'}
        self.assertEqual(position_relation_data(content,page),[3,0,16,0])
        content['contentAlignment']={'x':'right','y':'top'}
        self.assertEqual(position_relation_data(content,page),[9,0,10,0])

    def test_content_alignment_parameter_file_and_auto_precedence(self):
        from affinity2ui.alignment import validate_content_alignment_config, resolve_content_alignment
        config=validate_content_alignment_config({'defaults':{'x':'right','y':'top'},
            'pages':{'TaskPanel':{'x':'left','y':'bottom'}}})
        self.assertEqual(resolve_content_alignment('TaskPanel',config,x='center'),{'x':'center','y':'bottom'})
        self.assertEqual(resolve_content_alignment('TaskPanel',config),{'x':'left','y':'bottom'})
        self.assertEqual(resolve_content_alignment('TaskPanel',config,y='auto'),{'x':'left','y':'auto'})
        self.assertEqual(resolve_content_alignment('OtherPanel',config),{'x':'right','y':'top'})
        empty=validate_content_alignment_config(None)
        self.assertEqual(resolve_content_alignment('TaskPanel',empty),{'x':'auto','y':'auto'})
        self.assertEqual(config['pages']['TaskPanel'],{'x':'left','y':'bottom'})

    def test_content_alignment_file_validation_rejects_invalid_values(self):
        from affinity2ui.alignment import load_content_alignment_config,validate_content_alignment_config
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'alignment.json'
            path.write_text(json.dumps({'pages':{'TaskPanel':{'y':'bottom'}}}))
            self.assertEqual(load_content_alignment_config(path)['pages']['TaskPanel'],{'y':'bottom'})
        for data in ({'pages':[]},{'pages':{'TaskPanel':{'x':'bottom'}}},
                     {'defaults':{'horizontal':'center'}},{'unknown':{}},[]):
            with self.subTest(config=data),self.assertRaises(ValueError):
                validate_content_alignment_config(data)

    def test_export_content_alignment_obeys_parameter_file_auto_priority(self):
        class NativeFixture:
            def open(self,source):
                root=page();root['children'][1]['children']=[node('img_body',[node('paint')])]
                data=snapshot(root);data['tree']['kind']='DocumentNode';return data
            def script(self,request):
                if request['action']=='inspect':return self.open(None)
                for job in request['jobs']:Image.new('RGBA',(64,64),(50,60,70,255)).save(job['output'])
                return []
        config={'pages':{'TaskPanel':{'x':'right','y':'top'}}}
        cases=[({'content_align_y':'bottom','content_align_config':config},[9,0,16,0]),
               ({'content_align_config':config},[9,0,10,0]),
               ({},[6,0,13,0])]
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);project=folder/'project';project.mkdir()
            source=folder/'Task.af';source.write_bytes(b'source')
            for options,relations in cases:
                result=export_feature(NativeFixture(),source,project,project/'assets/ui',export_only=True,
                    dedupe=None,records_dir=folder/'records',**options)
                prefab=json.loads((Path(result['output'])/'TaskPanel.lh').read_text())
                self.assertEqual(prefab['_$child'][1]['relations'][0]['data'],[1,0,2,0,*relations])


    def test_plain_and_directional_lists_export_as_native_lists(self):
        for name in ('list_tasks', 'vlist_tasks', 'hlist_tasks', 'glist_tasks'):
            with self.subTest(name=name):
                root = page()
                background = node('img_list_background', [node('shape')])
                item = node('task_item_1', [node('img_row', [node('paint')])])
                root['children'][1]['children'] = [node(name, [background, item])]
                builder = LayoutBuilder()
                layout = builder.build(root)
                result = layout['children'][1]['children'][0]
                self.assertEqual(result['component'], 'GWidget')
                self.assertEqual(result['name'], name)
                self.assertEqual([c['name'] for c in result['children']], ['img_list_background', 'content'])
                self.assertEqual(result['children'][1]['type'], 'container')
                self.assertEqual(result['children'][1]['component'], 'GList')
                self.assertEqual(result['children'][1]['children'][0]['name'], 'task_item_1')
                contract = next(c for c in builder.contracts if c['path'].endswith('/'+name))
                self.assertEqual(contract['runtimeLayout'], 'automatic')
                if name == 'list_tasks':
                    self.assertEqual(contract['direction'], 'vertical')
                    self.assertEqual(contract['directionSource'], 'geometry')

    def test_content_is_the_native_list_and_root_is_only_a_wrapper(self):
        for name, direction in [('list_tasks','horizontal'), ('vlist_tasks','vertical'),
                                ('hlist_tasks','horizontal'), ('glist_tasks','grid')]:
            with self.subTest(name=name):
                root = page()
                items = [node('item_2',[node('img_row',[node('paint')])]),
                         node('item_1',[node('img_row',[node('paint')])])]
                for item, x in zip(items,[120,30]):
                    item['box'] = [x,50,80,60]
                content = node('content',items);content['box'] = [20,40,220,100]
                outer = node(name,[node('img_bg',[node('paint')]),
                    node('outside_item_decoration',[node('img_decoration',[node('paint')])]),content])
                root['children'][1]['children'] = [outer]
                builder = LayoutBuilder();layout = builder.build(root)
                wrapper = layout['children'][1]['children'][0]
                actual = wrapper['children'][2]
                self.assertEqual(wrapper['component'],'GWidget')
                self.assertEqual(actual['component'],'GList')
                self.assertEqual(actual['listRuntimeName'],name)
                self.assertEqual(actual['position'],[20,40])
                self.assertEqual(actual['size'],[220,100])
                self.assertEqual(actual['listLayout']['initItemNum'],2)
                self.assertNotIn('outside_item_decoration',actual['listLayout']['cellNames'])
                self.assertEqual(actual['listLayout']['direction'],direction)

    def test_export_nested_content_list_keeps_template_geometry_and_enables_scrolling(self):
        root = page()
        cells = []
        for i,y in enumerate([55,100,145],1):
            item = node(f'item_{i}',[node('img_row',[node('paint')])]);item['box'] = [35,y,80,30]
            cells.append(item)
        content = node('content',cells);content['box'] = [30,50,200,70]
        source_list = node('list_tasks',[node('bg',[node('paint')]),content]);source_list['box'] = [10,20,300,180]
        root['children'][1]['children'] = [source_list]
        class NativeFixture:
            def open(self,source):
                data=snapshot(root);data['tree']['kind']='DocumentNode';return data
            def script(self,request):
                if request['action']=='inspect':return self.open(None)
                for job in request['jobs']:Image.new('RGBA',(64,64),(50,60,70,255)).save(job['output'])
                return []
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);project=folder/'project';project.mkdir()
            source=folder/'Task.af';source.write_bytes(b'source')
            result=export_feature(NativeFixture(),source,project,project/'assets/ui',export_only=True,
                                  dedupe=None,records_dir=folder/'records')
            prefab=json.loads((Path(result['output'])/'TaskPanel.lh').read_text())
            wrapper=prefab['_$child'][1]['_$child'][0]
            self.assertEqual((wrapper['name'],wrapper['_$type']),('list_tasks_node','GWidget'))
            self.assertNotIn('layout',wrapper)
            self.assertNotIn('scroller',wrapper)
            self.assertEqual([c['name'] for c in wrapper['_$child']],['bg','list_tasks'])
            actual=wrapper['_$child'][1]
            self.assertEqual(actual['_$type'],'GList')
            self.assertEqual([actual[k] for k in ('x','y','width','height')],[20,30,200,70])
            self.assertEqual(actual['_initItemNum'],3)
            self.assertTrue(actual['_isDemo'])
            self.assertEqual([c['name'] for c in actual['_$child']],['item_1'])
            template=actual['_$child'][0]
            self.assertEqual(actual['_templateNode'],{'_$ref':template['_$id'],'_$tmpl':'itemTemplate'})
            self.assertEqual([wrapper['x']+actual['x']+template['x'],
                              wrapper['y']+actual['y']+template['y']],[35,55])
            self.assertTrue(actual['clipping'])
            self.assertNotIn('enabled', actual)
            self.assertNotIn('mouseEnabled', actual)
            self.assertEqual(actual['scroller']['_$type'],'Scroller')
            self.assertEqual(actual['scroller']['direction'],0)
            self.assertEqual(actual['scroller']['touchEffect'],1)
            self.assertFalse(actual['scroller']['mouseWheelDisabled'])
            self.assertEqual(actual['scroller']['barDisplay'],5)


    def test_list_inference_uses_only_item_names_and_preserves_decorations(self):
        from affinity2ui.list_layout import infer_list, DECORATION_UUID
        cells = [dict(name=f'task_item_{i}',type='container',position=[20,21+i*128],size=[628,118],children=[]) for i in range(5)]
        decor = [dict(name='img_background',type='image',position=[0,0],size=[668,668]),
                 dict(name='header',type='container',position=[600,0],size=[68,40],children=[])]
        data = dict(name='list_tasks',type='container',size=[668,668],children=[decor[0],*cells,decor[1]])
        plan = infer_list(data)
        self.assertEqual(plan['direction'], 'vertical')
        self.assertEqual(plan['native']['type'], 1)
        self.assertEqual(plan['native']['rowGap'], 10)
        self.assertEqual(plan['cellNames'], [c['name'] for c in cells])
        self.assertEqual(plan['decorationNames'], ['img_background','header'])
        data['listLayout'] = plan
        prefab = {'_$type':'GList','_$child':[{'_$type':'GWidget','_$id':'node-'+c['name'],'name':c['name'],'x':c['position'][0],'y':c['position'][1],'_$child':[]} for c in data['children']]}
        patch_prefab(prefab,data)
        self.assertEqual(prefab['layout']['type'],1)
        self.assertEqual(prefab['_$child'][0]['_$comp'],[{'_$type':DECORATION_UUID,'sourceX':0,'sourceY':0}])
        self.assertNotIn('_$comp',prefab['_$child'][1])
        self.assertEqual([prefab['_$child'][1]['x'],prefab['_$child'][1]['y']],[20,21])
        self.assertEqual(prefab['_templateNode'], {'_$ref':'node-task_item_0','_$tmpl':'itemTemplate'})
        self.assertTrue(prefab['_isDemo'])
        self.assertEqual(prefab['_initItemNum'],5)
        self.assertEqual([c['name'] for c in prefab['_$child']],['img_background','task_item_0','header'])

    def test_list_inference_supports_horizontal_grid_and_explicit_direction(self):
        from affinity2ui.list_layout import infer_list
        def sample(positions, name='list_tasks'):
            return dict(name=name,size=[500,500],children=[dict(name=f'item_{i}',position=p,size=[80,60]) for i,p in enumerate(positions)])
        result=infer_list(sample([[10,20],[100,20],[190,20]]))
        self.assertEqual(result['direction'],'horizontal')
        self.assertEqual(result['native']['columnGap'],10)
        result=infer_list(sample([[10,20],[100,20],[10,90],[100,90]]))
        self.assertEqual(result['direction'],'grid')
        self.assertEqual(result['native']['columns'],2)
        self.assertEqual(result['native']['rowGap'],10)
        self.assertEqual(result['native']['columnGap'],10)
        result=infer_list(sample([[10,20],[100,20]],'vlist_tasks'))
        self.assertEqual(result['direction'],'vertical')
        self.assertEqual(result['directionSource'],'prefix')


    def test_flat_image_name_uses_short_portable_path_hash(self):
        from affinity2ui.images import flat_image_name
        self.assertRegex(flat_image_name('Task/content/head/bg.png'), r'^bg@[0-9a-z]{13}\.png$')
        self.assertNotEqual(flat_image_name('Task/content/head/bg.png'),flat_image_name('Task/TaskPanel/content/head/bg.png'))
        with self.assertRaises(ValueError):
            flat_image_name('../Task/bg.png')

    def test_multi_bundle_publish_rolls_back_all_outputs(self):
        from affinity2ui.images import publish_bundles
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            target=root/'existing';target.mkdir();(target/'user.txt').write_text('keep')
            staged=root/'staged';staged.mkdir();(staged/'new.txt').write_text('new')
            with self.assertRaises(OSError):
                publish_bundles([(staged,target),(root/'missing',root/'other')],root/'rollback')
            self.assertEqual((target/'user.txt').read_text(),'keep')
            self.assertFalse((target/'new.txt').exists())


    def test_separator_migration_preserves_original_texture_uuid(self):
        from affinity2ui.images import restore_shared_metadata
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staged=root/'staged';shared=root/'shared';records=root/'records'
            (staged/'TaskPanel').mkdir(parents=True);shared.mkdir();records.mkdir()
            (staged/'TaskPanel/bg.png').write_bytes(b'placeholder')
            old='bg#TaskPanel#Task.png'
            (shared/(old+'.meta')).write_text(json.dumps({'uuid':'keep-existing-texture-uuid'}))
            (records/'affinity.json').write_text(json.dumps({'images':[{'sourcePath':'Task/TaskPanel/bg.png','file':old}]}))
            restore_shared_metadata(staged,shared,'Task',records)
            self.assertEqual(json.loads((staged/'TaskPanel/bg.png.meta').read_text())['uuid'],'keep-existing-texture-uuid')


    def test_sprite_texture_keeps_uuid_grid_and_sampling_settings(self):
        from affinity2ui.images import ensure_sprite_texture
        metadata = {'uuid':'keep-me','custom':'preserve', 'importer':{
            'textureType':0, 'sizeGrid':[1,2,3,4,0], 'filterMode':0, 'sRGB':False,
        }}
        result=ensure_sprite_texture(copy.deepcopy(metadata))
        expected=copy.deepcopy(metadata)
        expected['importer']['textureType']=2
        self.assertEqual(result,expected)
        self.assertEqual(ensure_sprite_texture({'uuid':'new'})['importer']['textureType'],2)


if __name__ == '__main__':
    unittest.main()
