import copy
import unittest

from affinity2ui.selection_states import apply_selection_states


def switch(selected=False):
    return {'_$type': 'GButton', '_$id': 'sound', 'name': 'switch_sound',
            'downEffect': 2, 'x': 123, 'width': 106,
            '_$child': [
                {'_$type': 'GImage', '_$id': 'bg', 'name': 'bg', 'visible': True},
                {'_$type': 'GWidget', '_$id': 'off', 'name': 'off', 'visible': not selected},
                {'_$type': 'GWidget', '_$id': 'on', 'name': 'on', 'visible': selected,
                 '_$child': [{'_$type': 'GTextField', 'name': 'title', 'visible': False}]},
            ]}


class SwitchTests(unittest.TestCase):
    kind = 'switch'

    def make_node(self, selected=False):
        node = switch(selected)
        node['name'] = f'{self.kind}_sound'
        return node

    def test_both_initial_states_bind_native_selection_and_exclusive_display(self):
        for selected in (False, True):
            with self.subTest(selected=selected):
                node = self.make_node(selected)
                bg = copy.deepcopy(node['_$child'][0])
                hidden_title = copy.deepcopy(node['_$child'][2]['_$child'])
                apply_selection_states(node)
                self.assertEqual(node['mode'], 1)
                self.assertEqual(node['selected'], selected)
                self.assertEqual(node['selectedPage'], 1)
                self.assertEqual(node['controllers']['checked']['selectedIndex'], int(selected))
                self.assertEqual(node['controllers']['_$type'], 'Record')
                self.assertEqual(node['selectedController'], {'_$ref': 'sound', '_$ctrl': 'checked'})
                self.assertNotIn('changeStateOnClick', node)
                self.assertNotIn('mouseEnabled', node)
                self.assertEqual(node['downEffect'], 0)
                self.assertEqual(node['_$child'][0], bg)
                self.assertEqual(node['_$child'][2]['_$child'], hidden_title)
                for state, page in zip(node['_$child'][1:], (0, 1)):
                    self.assertTrue(state['visible'])
                    self.assertEqual(state['gears'], [{
                        '_$type': 'GearDisplay', 'controller': node['selectedController'], 'pages': [page]}])
                self.assertEqual((node['x'], node['width']), (123, 106))
                self.assertLess(list(node).index('selectedPage'), list(node).index('selectedController'))

    def test_repeated_binding_preserves_edited_selection_and_does_not_duplicate_gears(self):
        node = self.make_node()
        apply_selection_states(node)
        node['selected'] = True
        apply_selection_states(node)
        self.assertEqual(node['controllers']['checked']['selectedIndex'], 1)
        once = copy.deepcopy(node)
        apply_selection_states(node)
        self.assertEqual(node, once)

    def test_missing_or_ambiguous_initial_states_are_rejected(self):
        for invalid in ('missing', 'both', 'neither'):
            with self.subTest(invalid=invalid):
                node = self.make_node()
                if invalid == 'missing':
                    node['_$child'].pop()
                else:
                    for state in node['_$child'][1:]:
                        state['visible'] = invalid == 'both'
                with self.assertRaises(ValueError):
                    apply_selection_states(node)

    def test_foreign_controller_is_not_overwritten(self):
        node = self.make_node()
        node['controllers'] = {'checked': {'pages': ['one', 'two']}}
        with self.assertRaisesRegex(ValueError, '冲突'):
            apply_selection_states(node)

    def test_regular_buttons_do_not_receive_selection_behavior(self):
        node = self.make_node()
        node['name'] = 'btn_sound'
        original = copy.deepcopy(node)
        apply_selection_states(node)
        self.assertEqual(node, original)


class CheckboxTests(unittest.TestCase):
    kind = 'checkbox'

    def test_only_binds_on_preserving_all_other_children(self):
        for selected in (False, True):
            for off_visible in (False, True):
                with self.subTest(selected=selected, off_visible=off_visible):
                    node = switch(selected)
                    node['name'] = f'{self.kind}_agreement'
                    node['_$child'][1]['visible'] = off_visible
                    unchanged = copy.deepcopy(node['_$child'][:2])
                    descendants = copy.deepcopy(node['_$child'][2]['_$child'])
                    apply_selection_states(node)
                    self.assertEqual(node['selected'], selected)
                    self.assertEqual(node['_$child'][:2], unchanged)
                    self.assertEqual(node['_$child'][2]['_$child'], descendants)
                    self.assertEqual(node['downEffect'], 0)
                    self.assertEqual(node['_$child'][2]['gears'][0]['pages'], [1])
                    self.assertEqual(node['controllers']['checked']['selectedIndex'], int(selected))
                    node['selected'] = not selected
                    apply_selection_states(node)
                    once = copy.deepcopy(node)
                    apply_selection_states(node)
                    self.assertEqual(node, once)
                    self.assertEqual(node['controllers']['checked']['selectedIndex'], int(not selected))

    def test_requires_on_but_does_not_require_off(self):
        node = switch()
        node['name'] = f'{self.kind}_agreement'
        node['_$child'].pop(1)
        apply_selection_states(node)
        node['_$child'].pop()
        with self.assertRaisesRegex(ValueError, '缺少 on'):
            apply_selection_states(node)

    def test_preserves_unrelated_controller_and_display_gears(self):
        node = switch()
        node['name'] = f'{self.kind}_agreement'
        controller = {'_$type': 'Controller', 'pages': ['normal', 'disabled']}
        gear = {'_$type': 'GearDisplay', 'controller': {'_$ref': 'other', '_$ctrl': 'enabled'}, 'pages': [0]}
        node['controllers'] = {'enabled': copy.deepcopy(controller)}
        node['_$child'][2]['gears'] = [copy.deepcopy(gear)]
        apply_selection_states(node)
        self.assertEqual(node['controllers']['enabled'], controller)
        self.assertEqual(node['_$child'][2]['gears'][0], gear)
        self.assertEqual(len(node['_$child'][2]['gears']), 2)


class TabTests(SwitchTests):
    kind = 'tab'


if __name__ == '__main__':
    unittest.main()
