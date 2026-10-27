"""Explicit page content alignment options, resolved independently per axis."""
import json
from pathlib import Path


CONTENT_ALIGN_X = {'auto':None, 'left':0, 'center':1, 'right':2}
CONTENT_ALIGN_Y = {'auto':None, 'top':0, 'center':1, 'bottom':2}


def validate_axis_options(options, label):
    if not isinstance(options, dict) or set(options) - {'x', 'y'}:
        raise ValueError(f'{label} 必须是仅包含 x/y 的对象')
    for axis, value in options.items():
        allowed = CONTENT_ALIGN_X if axis == 'x' else CONTENT_ALIGN_Y
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f'{label}.{axis} 对齐值无效：{value!r}；可用值：{", ".join(allowed)}')
    return dict(options)


def validate_content_alignment_config(config):
    if config is None:
        return {'defaults':{}, 'pages':{}}
    if not isinstance(config, dict) or set(config) - {'defaults', 'pages'}:
        raise ValueError('content 对齐配置必须是仅包含 defaults/pages 的对象')
    defaults = validate_axis_options(config.get('defaults', {}), 'defaults')
    pages = config.get('pages', {})
    if not isinstance(pages, dict):
        raise ValueError('pages 必须是按页面根节点名索引的对象')
    result = {}
    for name, options in pages.items():
        if not isinstance(name, str) or not name:
            raise ValueError('pages 的页面名称不能为空')
        result[name] = validate_axis_options(options, f'pages.{name}')
    return {'defaults':defaults, 'pages':result}


def load_content_alignment_config(path):
    return validate_content_alignment_config(json.loads(Path(path).read_text(encoding='utf-8')))


def resolve_content_alignment(page_name, config, x=None, y=None):
    cli = {axis:value for axis,value in (('x',x),('y',y)) if value is not None}
    validate_axis_options(cli, '命令行')
    return {'x':'auto', 'y':'auto', **config['defaults'], **config['pages'].get(page_name, {}), **cli}
