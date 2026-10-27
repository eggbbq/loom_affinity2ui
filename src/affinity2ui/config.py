"""Portable configuration schema, independent of the package install path."""
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
import tomllib


DEFAULTS = {
    'paths': dict(project='client', assets='client/assets/ui', sources='art/ui/pages',
                  records='out/affinity-export', reports='out/ui-export-reports'),
    'export': dict(workers=2, ninegrid_mode='visual', ninegrid_ignore_names=['icon','ico','图标'],
                   dedupe_similarity=.99, pixel_grid=True, button_down_effect='dark', strict=False),
    'layout': dict(content_align_x='', content_align_y='', content_align_config=''),
    'checks': dict(resize=True, repair_records=[]),
}


def load_config(path=None):
    data = {}
    if path is not None:
        with Path(path).open('rb') as stream:
            data = tomllib.load(stream)
    if set(data)-set(DEFAULTS):
        raise ValueError('未知配置分组')
    result = deepcopy(DEFAULTS)
    for section, values in data.items():
        if not isinstance(values, dict) or set(values)-set(DEFAULTS[section]):
            raise ValueError(f'无效配置分组：{section}')
        for key, value in values.items():
            expected = type(DEFAULTS[section][key])
            if not (type(value) is expected or expected is float and type(value) in (float,int)):
                raise ValueError(f'配置类型错误：{section}.{key}')
        result[section].update(values)
    if any(not p.strip() for p in result['paths'].values()):
        raise ValueError('路径不能为空')
    export = result['export']
    if export['workers'] < 0 or not 0 <= export['dedupe_similarity'] <= 1:
        raise ValueError('workers 或 dedupe_similarity 超出范围')
    if export['ninegrid_mode'] not in ('visual','strict') or export['button_down_effect'] not in ('none','dark','up-scale','down-scale'):
        raise ValueError('九宫格模式或按钮效果无效')
    if any(not isinstance(n,str) or not n.strip() for n in export['ninegrid_ignore_names']):
        raise ValueError('九宫格忽略名称必须为非空字符串数组')
    if any(not isinstance(p,str) or not p.strip() for p in result['checks']['repair_records']):
        raise ValueError('repair_records 必须为非空路径数组')
    for key, choices in [('content_align_x', ('','auto','left','center','right')),
                         ('content_align_y', ('','auto','top','center','bottom'))]:
        if result['layout'][key] not in choices:
            raise ValueError(f'无效对齐参数：{key}')
    return result


def init_workspace(workspace):
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root/'export_all_ui.toml'
    if target.exists():
        raise ValueError(f'配置已经存在，未覆盖：{target}')
    target.write_bytes(files('affinity2ui').joinpath('templates', 'export_all_ui.toml').read_bytes())
    (root/'art/ui/pages').mkdir(parents=True, exist_ok=True)
    return {'workspace': str(root), 'config': str(target)}
