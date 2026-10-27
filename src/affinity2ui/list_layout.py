"""Infer native list geometry using only names containing item."""
from statistics import median
from .pixel_grid import nearest_pixel

LIST_KINDS = {'list', 'vlist', 'hlist', 'glist'}
DECORATION_UUID = 'a54c5e84-70c2-55ab-83c4-4d81da2c73a1'


def is_cell(node):
    return 'item' in node['name'].lower()


def clusters(cells, axis):
    if not cells:
        return []
    tolerance = max(1, min(c['size'][axis] for c in cells) * .1)
    groups = []
    for cell in sorted(cells, key=lambda n: n['position'][axis]):
        if not groups or abs(cell['position'][axis] - groups[-1][0]['position'][axis]) > tolerance:
            groups.append([])
        groups[-1].append(cell)
    return groups


def scroll_settings(direction):
    """Native UI2 scrolling, independent of global touch defaults."""
    return {'_$type':'Scroller', 'direction':1 if direction == 'horizontal' else 0,
            'touchEffect':1, 'touchEffectButton':0, 'mouseWheelDisabled':False,
            'inertiaDisabled':False, 'barDisplay':5}


def infer_list(node, kind=None, *, pixel_grid=False):
    cells = [c for c in node['children'] if is_cell(c)]
    kind = kind or node['name'].partition('_')[0]
    rows, columns = clusters(cells, 1), clusters(cells, 0)
    direction = {'vlist':'vertical', 'hlist':'horizontal', 'glist':'grid'}.get(kind)
    source = 'prefix' if direction else 'geometry'
    if not direction:
        if len(rows) <= 1 and len(columns) > 1:
            direction = 'horizontal'
        elif len(columns) <= 1:
            direction = 'vertical'
        else:
            direction = 'grid'
    native = dict(type={'vertical':1,'horizontal':2,'grid':3}[direction],
                  stretchX=0, stretchY=0, foldInvisibles=False)
    result = dict(direction=direction, directionSource=source, cellNames=[],
                  decorationNames=[c['name'] for c in node['children'] if not is_cell(c)],
                  native=native, positions={}, uneven=False, templateName=None, initItemNum=len(cells), isDemo=True)
    if not cells:
        return result
    left = min(c['position'][0] for c in cells)
    top = min(c['position'][1] for c in cells)
    right = max(c['position'][0]+c['size'][0] for c in cells)
    bottom = max(c['position'][1]+c['size'][1] for c in cells)
    native['padding'] = [top, max(0,node['size'][0]-right), max(0,node['size'][1]-bottom), left]
    if direction in ('vertical','horizontal'):
        axis = 1 if direction == 'vertical' else 0
        ordered = sorted(cells, key=lambda n:(n['position'][axis], n['position'][1-axis]))
        gaps = [b['position'][axis]-a['position'][axis]-a['size'][axis] for a,b in zip(ordered,ordered[1:])]
        gap = median(gaps) if gaps else 0
        if pixel_grid:
            gap = nearest_pixel(gap)
        native['rowGap' if axis else 'columnGap'] = gap
        result['uneven'] = bool(gaps) and max(gaps)-min(gaps) > .001
        cursor = top if axis else left
        for cell in ordered:
            result['positions'][cell['name']] = [left,cursor] if axis else [cursor,top]
            cursor += cell['size'][axis] + gap
    else:
        ordered_rows = [sorted(row,key=lambda c:c['position'][0]) for row in rows]
        ordered = [c for row in ordered_rows for c in row]
        native['columns'] = max(map(len, ordered_rows))
        xgaps = [b['position'][0]-a['position'][0]-a['size'][0] for row in ordered_rows for a,b in zip(row,row[1:])]
        ygaps = [min(c['position'][1] for c in b)-max(c['position'][1]+c['size'][1] for c in a)
                 for a,b in zip(ordered_rows,ordered_rows[1:])]
        native['columnGap'] = median(xgaps) if xgaps else 0
        native['rowGap'] = median(ygaps) if ygaps else 0
        if pixel_grid:
            native['columnGap'] = nearest_pixel(native['columnGap'])
            native['rowGap'] = nearest_pixel(native['rowGap'])
        result['uneven'] = any(gaps and max(gaps)-min(gaps) > .001 for gaps in (xgaps,ygaps))
        y = top
        for start in range(0,len(ordered),native['columns']):
            line = ordered[start:start+native['columns']]
            x = left
            for cell in line:
                result['positions'][cell['name']] = [x,y]
                x += cell['size'][0] + native['columnGap']
            y += max(c['size'][1] for c in line) + native['rowGap']
    result['cellNames'] = [c['name'] for c in ordered]
    result['templateName'] = result['cellNames'][0]
    return result
