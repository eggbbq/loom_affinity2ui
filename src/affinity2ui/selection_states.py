"""Serialize native switch/checkbox/tab selection without runtime scripts or animation."""
from copy import deepcopy


CONTROLLER_NAME = 'checked'


def bind_selection(node):
    """Bind selection to each component's declared display rule."""
    kind = node.get('name', '').partition('_')[0]
    if node.get('_$type') != 'GButton':
        raise ValueError(f'{kind} 必须输出为 GButton：{node.get("name")}')
    children = node.get('_$child', [])
    states = {child['name']: child for child in children if child.get('name') in ('on', 'off')}
    exclusive = kind in {'switch', 'tab'}
    targets = (('off', 0), ('on', 1)) if exclusive else (('on', 1),)
    if any(name not in states for name, _ in targets):
        required = 'on/off' if exclusive else 'on'
        raise ValueError(f'{kind} 缺少 {required} 分组：{node.get("name")}')

    controllers = node.setdefault('controllers', {})
    # Match native IDE prefabs: the controller dictionary needs a Record type
    # so the runtime decoder constructs each nested Controller instance.
    controllers['_$type'] = 'Record'
    previous = controllers.get(CONTROLLER_NAME)
    if previous is not None and previous.get('pages') != ['off', 'on']:
        raise ValueError(f'{kind} 的 checked 控制器名称冲突：{node.get("name")}')
    if previous is None:
        on_visible = states['on'].get('visible', True)
        if exclusive and on_visible == states['off'].get('visible', True):
            raise ValueError(f'{kind} 必须保留互斥 on/off 初始状态：{node.get("name")}')
        selected = on_visible
    else:
        selected = node.get('selected', previous.get('selectedIndex', 0) == 1)

    reference = {'_$ref': node['_$id'], '_$ctrl': CONTROLLER_NAME}
    controllers[CONTROLLER_NAME] = {
        '_$type': 'Controller', 'pages': ['off', 'on'], 'selectedIndex': int(selected),
    }
    # selectedPage must be decoded before selectedController, whose setter
    # immediately synchronizes the button from the controller's current page.
    for key in ('mode', 'changeStateOnClick', 'mouseEnabled', 'selectedPage', 'selectedController', 'selected'):
        node.pop(key, None)
    # Native click handling already enables mouse input and changes selection.
    # These runtime properties are not part of the IDE's GButton asset schema.
    node.update(mode=1, selectedPage=1,
                selectedController=deepcopy(reference), selected=selected,
                downEffect=0)

    for name, page in targets:
        state = states[name]
        gears = state.setdefault('gears', [])
        gears[:] = [gear for gear in gears if gear.get('controller') != reference]
        gears.append({'_$type': 'GearDisplay', 'controller': deepcopy(reference), 'pages': [page]})
        # The design's hidden group must remain locally visible; GearDisplay
        # owns its effective visibility from now on. Descendants stay untouched.
        state['visible'] = True


def apply_selection_states(prefab):
    """Run after image optimization so state gears do not block static cutting."""
    for child in prefab.get('_$child', []):
        apply_selection_states(child)
    if prefab.get('name', '').partition('_')[0] in {'switch', 'checkbox', 'tab'}:
        bind_selection(prefab)
