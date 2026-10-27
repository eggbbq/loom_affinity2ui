"""Named component parts checked against the project's LayaAir 3.4.2 APIs."""
from .laya_types import NEW_UI_TYPES


LABEL_TYPES = {'GLabel', 'GButton', 'GComboBox'}
RANGE_TYPES = {'GProgressBar', 'GSlider'}
TEXT_TYPES = {'GTextField', 'GTextInput'}
ICON_TYPES = {'GImage', 'GLoader'}


def widget_type(node):
    return node.get('_$type') or node.get('component') or {
        'text': 'GTextField', 'image': 'GImage',
    }.get(node.get('type'), 'GWidget')


def children_of(node):
    return node.get('_$child', node.get('children', []))


def compatible(node, capability):
    kind = widget_type(node)
    if capability == 'widget':
        return kind in NEW_UI_TYPES
    if kind in (TEXT_TYPES if capability == 'text' else ICON_TYPES):
        return True
    # GLabel/GButton forward text/icon to their own bound part. A plain
    # container with a title-like name cannot implement that contract.
    if kind in LABEL_TYPES:
        bindings, _ = plan_part_bindings(node)
        return ('titleWidget' if capability == 'text' else 'iconWidget') in bindings
    return False


def plan_part_bindings(node):
    """Return valid direct-child references and diagnostics for either schema."""
    kind = widget_type(node)
    rules = {}
    if kind in LABEL_TYPES | RANGE_TYPES:
        rules['titleWidget'] = (('title', 'titleWidget', 'title_widget'), 'text')
    if kind in LABEL_TYPES:
        rules['iconWidget'] = (('icon', 'iconWidget', 'icon_widget'), 'icon')
    if kind in RANGE_TYPES:
        size = node.get('size', [node.get('width', 0), node.get('height', 0)])
        horizontal = size[0] >= size[1]
        rules['hBar'] = (('hBar', 'h_bar', 'img_fill_h') + (('img_fill',) if horizontal else ()), 'widget')
        rules['vBar'] = (('vBar', 'v_bar', 'img_fill_v') + (() if horizontal else ('img_fill',)), 'widget')
    if kind == 'GSlider':
        rules['gripButton'] = (('img_thumb', 'gripButton', 'grip_button'), 'widget')
    bindings = {}
    diagnostics = []
    for prop, (names, capability) in rules.items():
        matches = [child for child in children_of(node) if child.get('name') in names]
        if len(matches) > 1:
            diagnostics.append(('COMPONENT_PART_AMBIGUOUS', f'{kind}.{prop} 匹配多个子节点，未绑定'))
        elif matches:
            child = matches[0]
            if compatible(child, capability):
                bindings[prop] = child
            else:
                diagnostics.append(('COMPONENT_PART_TYPE',
                    f'{kind}.{prop} 无法绑定 {child["name"]}（{widget_type(child)}），需要 {capability} 类型'))
    return bindings, diagnostics


def bind_component_parts(prefab):
    bindings, diagnostics = plan_part_bindings(prefab)
    for prop, child in bindings.items():
        # Range components serialize their backing fields in native IDE
        # prefabs; public setters are runtime APIs with construction effects.
        serialized = '_'+prop if widget_type(prefab) in RANGE_TYPES else prop
        if serialized != prop:
            prefab.pop(prop, None)
        prefab[serialized] = {'_$ref': child['_$id']}
    if widget_type(prefab) in LABEL_TYPES:
        if 'titleWidget' in bindings:
            title = bindings['titleWidget']
            prefab.setdefault('title', title.get('text', title.get('title', '')))
        if 'iconWidget' in bindings:
            icon = bindings['iconWidget']
            prefab.setdefault('icon', icon.get('src', icon.get('icon', '')))
    return diagnostics
