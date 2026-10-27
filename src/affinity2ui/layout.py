"""Project naming/geometry contracts, independent of the live Affinity process."""
import math
import re

from .prefab import validate_layout
from .naming import export_name
from .list_layout import LIST_KINDS, DECORATION_UUID, infer_list, is_cell, scroll_settings
from .component_parts import bind_component_parts, plan_part_bindings
from .alignment import CONTENT_ALIGN_X, CONTENT_ALIGN_Y, validate_axis_options
from .pixel_grid import quantize_box

IMAGE_TAGS = {'bg', 'img', 'icon', 'image'}
BUTTON_DOWN_EFFECTS = {'none': 0, 'dark': 1, 'up-scale': 2, 'down-scale': 3}
COMPONENTS = {
    'btn': 'GButton', 'button': 'GButton', 'checkbox': 'GButton', 'switch': 'GButton',
    'tab': 'GButton', 'bar': 'GProgressBar', 'bar0': 'GProgressBar', 'bar1': 'GProgressBar',
    'slider': 'GSlider', 'label': 'GLabel', 'input': 'GWidget',
    'vbox': 'GBox', 'hbox': 'GBox', 'gbox': 'GBox',
    'list': 'GList', 'vlist': 'GList', 'hlist': 'GList', 'glist': 'GList',
}


def token(name):
    return name.partition('_')[0]


def safe_name(name):
    # Reuse PSD filesystem normalization without removing semantic UI prefixes.
    result = export_name('af_' + name)[3:]
    if not result or result in ('.', '..') or result.casefold() in {'con', 'prn', 'aux', 'nul'} or re.fullmatch(r'(?i:com|lpt)[1-9]', result):
        raise ValueError(f'无效资源名称：{name!r}')
    return result


def snapped(value):
    return round(value) if abs(value - round(value)) <= .001 else value


def pixel_box(box):
    x, y, w, h = [snapped(v) for v in box]
    return [math.floor(x), math.floor(y), math.ceil(snapped(x+w)), math.ceil(snapped(y+h))]


def page_roots(snapshot):
    roots = []
    def visit(node):
        if '#' in node['name']:
            return
        if node['kind'] in ('DocumentNode', 'SpreadNode', 'ArtboardNode', 'LayerNode'):
            for child in node['children']:
                visit(child)
        elif '#' not in node['name']:
            roots.append(node)
    visit(snapshot['tree'])
    names = set()
    for node in roots:
        name = node['name']
        if node['kind'] != 'GroupNode' or not re.fullmatch(r'[A-Z][A-Za-z0-9]*', name):
            raise ValueError(f'页面根必须是独立 PascalCase Group：{name!r}')
        if name.casefold() in names:
            raise ValueError(f'重复页面根名：{name}')
        names.add(name.casefold())
        if not {'content', 'bg'} <= {child['name'] for child in node['children']}:
            raise ValueError(f'{name} 缺少 content/bg 接口')
    if not roots:
        raise ValueError('未找到可导出的页面根')
    return roots


class LayoutBuilder:
    def __init__(self, *, pixel_grid=True):
        self.jobs = []
        self.warnings = []
        self.contracts = []
        self.paths = set()
        self.pixel_grid = pixel_grid

    def warn(self, code, path, message):
        item = dict(code=code, path=path, message=message)
        if item not in self.warnings:
            self.warnings.append(item)

    def build(self, root):
        node = self.node(root, (), None, is_root=True)
        node.update(type='root', version=1, position=[0, 0])
        self.finalize(node)
        self.configure_lists(node)
        validate_layout(node)
        return node

    def configure_lists(self, node, ancestry=()):
        path = '/'.join((*ancestry,node['name']))
        _, diagnostics = plan_part_bindings(node)
        for code, message in diagnostics:
            self.warn(code, path, message)
        if node.get('component') == 'GList' and token(node['name']) in LIST_KINDS:
            content = next((c for c in node['children'] if c['name'] == 'content'), None)
            synthetic = content is None
            if synthetic:
                # Older AFs place cells directly under the list. Introduce the
                # same wrapper without moving their absolute display positions.
                cells = [c for c in node['children'] if is_cell(c)]
                content = dict(name='content', type='container', visible=True,
                               position=[0,0], size=list(node['size']), children=cells)
                children = []
                inserted = False
                for child in node['children']:
                    if is_cell(child):
                        if not inserted:
                            children.append(content)
                            inserted = True
                    else:
                        children.append(child)
                if not inserted:
                    children.append(content)
                node['children'] = children
            if content['type'] != 'container':
                raise ValueError(f'列表 content 必须是结构容器：{path}')
            target = content
            node['component'] = 'GWidget'
            node['listContentName'] = 'content'
            content['component'] = 'GList'
            content['listRuntimeName'] = node['name']
            plan = infer_list(target, token(node['name']), pixel_grid=self.pixel_grid)
            target['listLayout'] = plan
            contract = next(c for c in self.contracts if c['path'] == path)
            contract.update(direction=plan['direction'], directionSource=plan['directionSource'],
                cellNames=plan['cellNames'], decorationNames=plan['decorationNames'],
                runtimeLayout='automatic', nativeLayout=plan['native'],
                templateNode=plan['templateName'], initItemNum=plan['initItemNum'], isDemo=True)
            contract.update(container=node['name'] + '_node', list=node['name'], content='content',
                            syntheticContent=synthetic)
            if plan['uneven']:
                self.warn('LIST_NON_UNIFORM_GAP', path, '单元格间距不一致，原生列表布局采用中位间距')
        for child in node.get('children', []):
            self.configure_lists(child, (*ancestry,node['name']))

    def node(self, raw, folders, parent, is_root=False):
        name = raw['name']
        if '#' in name:
            return None
        kind = token(name)
        path = '/'.join((*folders, name))
        component = COMPONENTS.get(kind)
        is_text = 'text' in raw
        image = not is_root and not is_text and (kind in IMAGE_TAGS or not raw['children'])
        node = dict(name=name, visible=raw['visible'])
        node['_absolute'] = [snapped(v) for v in raw['box']]
        if is_text:
            node.update(type='text', text=raw['text'], font=raw['font'], fontSize=raw['fontSize'], align=raw['align'])
            fill = raw.get('fill')
            if fill:
                node['color'] = fill['color']
                node['opacity'] = raw['opacity'] * fill['alpha']
            else:
                self.warn('TEXT_FILL', path, '非纯色文字填充未映射，文字仍保留可编辑')
            styles = {(run['font'], round(run['fontSize'], 5), str(run['fill'])) for run in raw.get('runs', [])}
            if len(styles) > 1:
                self.warn('MIXED_TEXT_STYLE', path, '混合文字样式暂使用首段样式，原始 run 保存在 native.json')
            transform = raw.get('transform', [1, 0, 0, 0, 1, 0])
            a, b, _, c, d, _ = transform
            if a <= 0 or d <= 0 or abs(b) > .001 or abs(c) > .001 or abs(abs(a)-abs(d)) > .001:
                self.warn('TEXT_TRANSFORM', path, '旋转、斜切或非等比文字变换尚未映射')
            node['fontSize'] = snapped(node['fontSize'] * abs(d))
            if parent and token(parent['name']) == 'input' and name == 'title':
                node['component'] = 'GTextInput'
            if raw.get('paragraphAlign', 0) not in (0, 1, 2):
                self.warn('TEXT_ALIGNMENT', path, '特殊段落对齐暂回退为左对齐')
            if raw['effects']:
                self.warn('TEXT_EFFECT', path, '文字图层效果暂未映射为 Laya 文字效果')
        elif image:
            check_ignored_image_layers(raw, path)
            if any('text' in child for child in descendants(raw)):
                raise ValueError(f'图片组中包含文字，不能合并可编辑文本：{path}')
            if not raw['children'] and raw['kind'] in ('GroupNode', 'LayerNode'):
                self.warn('EMPTY_GROUP', path, '空组不作为有效尺寸依据，保留零尺寸容器')
                node.update(type='container', children=[])
                node['_absolute'][2:] = [0, 0]
            else:
                if kind == 'icon':
                    x, y, w, h = node['_absolute']
                    if w != h or w < 16 or w != int(w) or int(w) & (int(w)-1):
                        raise ValueError(f'icon 必须使用至少16px的2次幂正方形画布：{path}: {w}×{h}')
                # Use the native export's full pixel coverage; never alpha-crop.
                x0, y0, x1, y1 = pixel_box(raw['visibleBox'])
                if kind == 'icon' and [x0, y0, x1, y1] != pixel_box(raw['box']):
                    raise ValueError(f'图标可见范围超出完整画布：{path}')
                if x1 <= x0 or y1 <= y0:
                    raise ValueError(f'图片没有有效导出范围：{path}')
                asset = '/'.join((*map(safe_name, folders[1:]), safe_name(name)+'.png'))
                if asset.casefold() in self.paths:
                    raise ValueError(f'资源路径重名：{asset}')
                self.paths.add(asset.casefold())
                node.update(type='image', component='GLoader' if kind == 'icon' else 'GImage', asset=asset)
                node['_absolute'] = [x0, y0, x1-x0, y1-y0]
                self.jobs.append(dict(indices=raw['indices'], name=name, asset=asset, node=node))
        else:
            node.update(type='container', children=[])
            if component:
                node['component'] = component
            if raw['opacity'] != 1:
                node['opacity'] = raw['opacity']
            for child in raw['children']:
                item = self.node(child, (*folders, name), raw)
                if item is not None:
                    node['children'].append(item)
            sibling_names = [child['name'].casefold() for child in node['children']]
            if len(sibling_names) != len(set(sibling_names)):
                raise ValueError(f'同一父节点下存在重名接口：{path}')
            if raw['effects'] or raw.get('enclosures'):
                self.warn('CONTAINER_EFFECT', path, '结构容器的效果或蒙版需要人工复核；未压平内部接口')
            contract = dict(path=path, kind=kind)
            if kind == 'checkbox':
                contract.update(visibilityRule='toggle_on_only', target='on')
            elif kind in {'switch', 'tab'}:
                contract.update(visibilityRule='exclusive_on_off', targets=['on', 'off'])
                states = {c['name']: c['visible'] for c in raw['children']}
                if 'on' not in states or 'off' not in states or states['on'] == states['off']:
                    raise ValueError(f'{kind} 必须保留互斥 on/off 状态：{path}')
            elif kind == 'tabs':
                contract.update(selectionRule='single_switch')
                switches = [c for c in raw['children'] if token(c['name']) == 'switch']
                selected = [c['name'] for c in switches if any(s['name'] == 'on' and s['visible'] for s in c['children'])]
                if len(selected) != 1:
                    raise ValueError(f'tabs 必须恰好有一个选中 switch：{path}')
                contract['selected'] = selected[0]
            elif kind in {'vbox', 'hbox', 'gbox', 'vlist', 'hlist', 'glist'}:
                contract['direction'] = {'v': 'vertical', 'h': 'horizontal', 'g': 'grid'}[kind[0]]
                contract['runtimeLayout'] = 'manual'
            elif kind == 'list':
                contract['runtimeLayout'] = 'manual'
            elif kind == 'input':
                contract.update(container=name + '_node', input=name, placeholder='prompt')
            self.contracts.append(contract)
        return node

    def finalize(self, node, origin=None):
        box = node.pop('_absolute')
        # Native PNG jobs already use the full integer pixel coverage. Never
        # resize/crop those canvases to match rounded container dimensions.
        if self.pixel_grid and node['type'] != 'image':
            box = quantize_box(box)
        x, y, w, h = box
        node['size'] = [w, h]
        node['position'] = [0, 0] if origin is None else [snapped(x-origin[0]), snapped(y-origin[1])]
        for child in node.get('children', []):
            self.finalize(child, (x, y))


def descendants(node):
    for child in node.get('children', []):
        if '#' in child['name']:
            continue
        yield child
        yield from descendants(child)


def check_ignored_image_layers(node, path, visible=True):
    # Native selection export bakes the existing visible descendants. Refuse
    # visible # layers instead of accidentally baking content PSD would omit.
    for child in node.get('children', []):
        shown = visible and child['visible']
        if '#' in child['name']:
            if shown:
                raise ValueError(f'图片组中有可见的 # 忽略层，请隐藏后导出：{path}/{child["name"]}')
        else:
            check_ignored_image_layers(child, path+'/'+child['name'], shown)


def position_relation_data(child, parent):
    """Prefer nearby edges, then classify the geometric center by page thirds."""
    result = []
    alignment = validate_axis_options(child.get('contentAlignment', {}), 'contentAlignment')
    for axis, relation_types in enumerate(((3, 6, 9), (10, 13, 16))):
        key, choices = (('x', CONTENT_ALIGN_X), ('y', CONTENT_ALIGN_Y))[axis]
        explicit = choices[alignment.get(key, 'auto')]
        if explicit is not None:
            result.extend((relation_types[explicit], 0))
            continue
        span = parent['size'][axis]
        start = child['position'][axis]
        size = child['size'][axis]
        center = start + size / 2
        region = 1
        if span > 0:
            tolerance = max(2, span * .1)
            near_start = abs(start) <= tolerance
            near_end = abs(span - start - size) <= tolerance
            if near_start != near_end:
                region = 0 if near_start else 2
            elif not near_start:
                if center < span / 3:
                    region = 0
                elif center > span * 2 / 3:
                    region = 2
        result.extend((relation_types[region], 0))
    return result


def fit_input_to_parent(input_node, parent):
    """Expand the input hit area without moving or resizing its text region."""
    x, y = input_node.get('x', 0), input_node.get('y', 0)
    width, height = input_node['width'], input_node['height']
    top, right, bottom, left = input_node.get('padding', [0, 0, 0, 0])
    input_node['padding'] = [snapped(top + y),
        snapped(right + parent['width'] - x - width),
        snapped(bottom + parent['height'] - y - height), snapped(left + x)]
    input_node.update(x=0, y=0, width=parent['width'], height=parent['height'])


def map_text_input(prefab):
    """Keep the background in a widget wrapper and turn title into the input."""
    name = prefab.get('name', '')
    if token(name) != 'input':
        return
    children = prefab.get('_$child', [])
    if name.endswith('_node'):
        existing = next((child for child in children if child.get('name') == name[:-5]
                         and child['_$type'] == 'GTextInput'), None)
        if existing is not None:
            fit_input_to_parent(existing, prefab)
            return
    by_name = {child['name']: child for child in children}
    title = by_name.get('title')
    if title is None or title['_$type'] not in ('GTextField', 'GTextInput'):
        raise ValueError(f'输入框缺少 title 文本：{name}')
    old_native_root = prefab['_$type'] == 'GTextInput'
    text = title.get('text', '') if title.get('visible', True) else ''
    styles = ('font', 'fontSize', 'color', 'align', 'valign', 'stroke',
              'strokeColor', 'bold', 'italic', 'leading', 'multiline',
              'editable', 'restrict', 'maxChars', 'type', 'underline',
              'underlineColor', 'strikethrough', 'strikethroughColor')
    if old_native_root:
        # Migrate the previous exporter format without losing edited values.
        text = prefab.get('text', text)
        for key in styles:
            if key in prefab:
                title[key] = prefab[key]
    placeholder = by_name.get('placeholder', {})
    title.pop('mouseEnabled', None)
    title.pop('enabled', None)
    title.update(name=name, text=text, visible=True)
    title['_$type'] = 'GTextInput'
    title.setdefault('padding', [0, 0, 0, 0])
    title.setdefault('editable', True)
    title.setdefault('multiline', '\n' in text)
    title['prompt'] = prefab.get('prompt', placeholder.get('text', '')) if old_native_root else placeholder.get('text', '')
    prompt_color = prefab.get('promptColor') if old_native_root else None
    if prompt_color is None:
        prompt_color = placeholder.get('color')
    if prompt_color is not None:
        title['promptColor'] = prompt_color
    title.pop('wordWrap', None)
    title.pop('overflow', None)
    # Keep the original effective text area using padding inside a full-size input.
    fit_input_to_parent(title, prefab)
    parts = [child for child in children if child['name'] not in ('title', 'placeholder') and child is not title]
    for child in parts:
        # Images without input listeners are already non-interactive. The
        # runtime mouseEnabled property is not part of the native UI schema.
        child.pop('mouseEnabled', None)
        if old_native_root and child.get('zIndex') == -1:
            child.pop('zIndex')
    prefab.update(name=name + '_node', **{'_$type': 'GWidget', '_$child': [*parts, title]})
    if old_native_root:
        for key in (*styles, 'text', 'prompt', 'promptColor', 'padding', 'stackingRoot'):
            prefab.pop(key, None)


def apply_button_effects(prefab, default_effect=1):
    """Center scaling effects without changing the button's local transform."""
    for child in prefab.get('_$child', []):
        apply_button_effects(child, default_effect)
    if prefab['_$type'] != 'GButton':
        return
    prefab.setdefault('downEffect', default_effect)
    if prefab['downEffect'] not in (2, 3):
        return
    width, height = prefab['width'], prefab['height']
    old_x = width * prefab['anchorX'] if 'anchorX' in prefab else prefab.get('pivotX', 0)
    old_y = height * prefab['anchorY'] if 'anchorY' in prefab else prefab.get('pivotY', 0)
    dx, dy = width / 2 - old_x, height / 2 - old_y
    # Laya Matrix.setMatrix: compensate the pivot through the existing linear
    # transform so scaled, rotated or skewed buttons retain their visual bounds.
    rotation = math.radians(prefab.get('rotation', 0))
    skew_x = math.radians(prefab.get('skewX', 0))
    skew_y = math.radians(prefab.get('skewY', 0))
    scale_x, scale_y = prefab.get('scaleX', 1), prefab.get('scaleY', 1)
    a, b = math.cos(rotation + skew_y) * scale_x, math.sin(rotation + skew_y) * scale_x
    c, d = math.sin(skew_x - rotation) * scale_y, math.cos(rotation - skew_x) * scale_y
    prefab['x'] = prefab.get('x', 0) + a * dx + c * dy
    prefab['y'] = prefab.get('y', 0) + b * dx + d * dy
    prefab.update(anchorX=.5, anchorY=.5)
    prefab.pop('pivotX', None)
    prefab.pop('pivotY', None)


def patch_prefab(prefab, layout, parent=None, *, responsive=True, button_down_effect=1):
    """Preserve project node interfaces while applying native UI serialization."""
    if prefab['_$type'] == 'GBox':
        prefab['layout'] = {'type': 0}
    if prefab['_$type'] == 'GList':
        prefab['layout'] = dict(layout.get('listLayout', {}).get('native', {'type': 0}))
        direction = layout.get('listLayout', {}).get('direction', 'vertical')
        prefab['scroller'] = scroll_settings(direction)
        prefab['clipping'] = True
        # Native GList/Scroller listeners enable input by default; neither
        # mouseEnabled nor enabled is a serialized property in this IDE schema.
        prefab.pop('mouseEnabled', None)
        prefab.pop('enabled', None)
    if layout['type'] == 'text':
        prefab['valign'] = 'middle' if parent and token(parent['name']) == 'input' and layout['name'] in ('title', 'placeholder') else 'top'
        prefab['wordWrap'] = '\n' in layout['text']
    for child, data in zip(prefab.get('_$child', []), layout.get('children', []), strict=True):
        patch_prefab(child, data, layout, responsive=responsive, button_down_effect=button_down_effect)
    bind_component_parts(prefab)
    if layout['type'] == 'container':
        map_text_input(prefab)
    if layout.get('listLayout'):
        plan = layout['listLayout']
        # Input and nested-list wrappers can change their runtime names.
        by_name = {data['name']:child for child,data in zip(prefab['_$child'],layout['children'],strict=True)}
        source_names = {id(child):name for name,child in by_name.items()}
        ordered = iter(by_name[name] for name in plan['cellNames'])
        prefab['_$child'] = [next(ordered) if source_names[id(c)] in plan['cellNames'] else c for c in prefab['_$child']]
        for child in prefab['_$child']:
            source_name = source_names[id(child)]
            if source_name in plan['cellNames']:
                child['x'],child['y'] = plan['positions'][source_name]
            else:
                child.setdefault('_$comp', []).append({'_$type':DECORATION_UUID, 'sourceX':child['x'], 'sourceY':child['y']})
        prefab['_isDemo'] = True
        prefab['_initItemNum'] = plan['initItemNum']
        if plan['templateName']:
            template = by_name[plan['templateName']]
            prefab['_templateNode'] = {'_$ref':template['_$id'], '_$tmpl':'itemTemplate'}
            # The editor creates demo cells from this one template. Keeping
            # the other static cells here would duplicate the source rows.
            prefab['_$child'] = [c for c in prefab['_$child'] if source_names[id(c)] not in plan['cellNames'] or c is template]
    if layout.get('listRuntimeName'):
        prefab['name'] = layout['listRuntimeName']
    if layout.get('listContentName'):
        prefab['name'] = layout['name'] + '_node'

    if responsive:
        apply_page_relations(prefab, layout)
    if parent is None:
        # Run after parent layout positions have been assigned.
        apply_button_effects(prefab, button_down_effect)


def apply_page_relations(prefab, layout):
    if layout['type'] != 'root':
        return
    children = {child['name']:child for child in prefab.get('_$child', [])}
    for data in layout.get('children', []):
        if data['name'] not in ('bg','content'):
            continue
        relations = [1,0,2,0]
        if data['name'] == 'content':
            relations.extend(position_relation_data(data, layout))
        children[data['name']]['relations'] = [{
            '_$type':'Relation', 'target':{'_$ref':prefab['_$id']}, 'data':relations,
        }]
