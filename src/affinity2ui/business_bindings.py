"""Reapply project-owned runtime/field bindings after visual prefab generation."""
from copy import deepcopy
import json
from pathlib import Path


def apply_business_bindings(prefab, project):
    project = Path(project).resolve()
    manifest = project / 'src/ui/prefab-bindings.json'
    if not manifest.exists():
        return False
    bindings = json.loads(manifest.read_text(encoding='utf-8'))
    binding = bindings.get(prefab.get('name'))
    if binding is None:
        return False
    script = (project / binding['runtime']).resolve()
    if not script.is_relative_to(project / 'src') or not script.is_file():
        raise ValueError(f'业务 runtime 脚本不存在或不在 src 内：{script}')
    uuid = json.loads(Path(str(script) + '.meta').read_text(encoding='utf-8'))['uuid']
    if prefab.get('_$type') not in ('GWidget', uuid):
        raise ValueError(f'业务面板根节点类型冲突：{prefab.get("name")}')
    runtime = 'res://' + uuid
    if prefab.get('_$runtime') not in (None, runtime):
        raise ValueError(f'业务 runtime 冲突：{prefab.get("name")}')

    # Validate every path before mutating, so a renamed control cannot produce
    # a partly bound prefab or silently redirect gameplay to a different node.
    fields = {}
    for name, field in binding.get('fields', {}).items():
        node = prefab
        for part in field['path'].split('/'):
            children = [n for n in node.get('_$child', []) if n.get('name') == part]
            if len(children) != 1:
                raise ValueError(f'业务绑定节点缺失或重名：{prefab["name"]}/{field["path"]}')
            node = children[0]
        if node.get('_$type') != field['type'] or not node.get('_$id'):
            raise ValueError(f'业务绑定节点类型不符：{field["path"]}，需要 {field["type"]}')
        fields[name] = {'_$ref': node['_$id']}
    components = deepcopy(prefab.get('_$comp', []))
    for component in binding.get('components', []):
        matches = [c for c in components if c.get('_$type') == component['_$type']]
        if len(matches) > 1:
            raise ValueError(f'业务面板存在重复组件：{component["_$type"]}')
        if matches:
            matches[0].update(deepcopy(component))
        else:
            components.append(deepcopy(component))
    prefab['_$type'] = uuid
    prefab['_$runtime'] = runtime
    prefab.update(fields)
    prefab['_$comp'] = components
    return True


def bind_project_prefabs(project):
    """Explicit repair entry; normal AF exports call the same binder in staging."""
    project = Path(project)
    for path in sorted((project / 'assets/ui/prefabs').glob('*.lh')):
        prefab = json.loads(path.read_text(encoding='utf-8'))
        if apply_business_bindings(prefab, project):
            path.write_text(json.dumps(prefab, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'已恢复 UI 业务绑定：{path.name}')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('client'))
    bind_project_prefabs(parser.parse_args().project)
