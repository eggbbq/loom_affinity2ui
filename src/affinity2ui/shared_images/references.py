"""Find and rewrite stable, serialized UI image references."""
import re

UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
FIELDS = {'src', 'icon', 'selectedIcon', 'skin'}


def nodes(data):
    if isinstance(data, dict):
        if '_$id' in data:
            yield data
        for value in data.values():
            yield from nodes(value)
    elif isinstance(data, list):
        for value in data:
            yield from nodes(value)


def collect(prefabs, uuids):
    references, protected = [], set()
    def walk(value, prefab, node=None, path=()):
        if isinstance(value, dict):
            if '_$id' in value:
                node, path = value, ()
            for key, child in value.items():
                walk(child, prefab, node, (*path,key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, prefab, node, (*path,index))
        elif isinstance(value, str):
            uid = value[6:] if value.startswith('res://') else None
            if uid in uuids and node is not None and path[-1] in FIELDS:
                references.append({'prefab':prefab,'nodeId':node['_$id'],'path':list(path),
                                   'uuid':uid,'kind':node.get('_$type','')+'.'+str(path[-1])})
            else:
                protected.update(set(UUID.findall(value)) & uuids)
    for name, data in prefabs.items():
        walk(data, name)
    return references, protected


def rewrite(prefabs, reference, old_uuid, new_uuid):
    data = prefabs.get(reference['prefab'])
    if data is None:
        return False
    node = next((n for n in nodes(data) if n['_$id']==reference['nodeId']), None)
    if node is None:
        return False
    try:
        target = node
        for key in reference['path'][:-1]:
            target = target[key]
        key = reference['path'][-1]
        if target[key] != 'res://'+old_uuid:
            return False
        target[key] = 'res://'+new_uuid
        return True
    except (KeyError, IndexError, TypeError):
        return False


def external_references(project, prefab_dir, image_dir, uuids, files=None):
    protected = set()
    extensions = {'.lh','.ls','.json','.meta','.ts','.js','.lmat','.sco','.atlascfg','.controller','.shader','.lani'}
    for folder in ('assets','src','settings'):
        root = project/folder
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix not in extensions:
                continue
            if path.parent==prefab_dir and path.suffix=='.lh':
                continue
            if path.parent==image_dir and path.name.endswith('.png.meta'):
                continue
            text=path.read_text(encoding='utf-8',errors='ignore')
            protected.update(set(UUID.findall(text)) & uuids)
            # Path-based script/atlas references cannot be rewritten by this
            # UUID-only pass. Preserve those original files conservatively.
            for name,uid in (files or {}).items():
                if name in text:
                    protected.add(uid)
    return protected
