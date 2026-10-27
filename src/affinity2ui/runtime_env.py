"""Mutable Node dependencies live in a user cache, never in site-packages."""
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import subprocess


def runtime_dir(cache_dir=None):
    base = cache_dir or os.environ.get('AFFINITY2UI_CACHE_DIR')
    if base:
        return Path(base).expanduser().resolve()/'runtime'
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'loom-affinity2ui'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'loom-affinity2ui'
    return base/'runtime'


def playwright_module(cache_dir=None):
    explicit = os.environ.get('AFFINITY2UI_PLAYWRIGHT_MODULE') or os.environ.get('NINEGRID_PLAYWRIGHT_MODULE')
    path = Path(explicit).expanduser().resolve() if explicit else runtime_dir(cache_dir)/'node_modules/playwright/index.js'
    if not path.is_file():
        raise ValueError('缺少引擎验证依赖，请执行 affinity2ui setup-runtime，或设置 AFFINITY2UI_PLAYWRIGHT_MODULE')
    return path


def setup_runtime(cache_dir=None):
    if not shutil.which('npm'):
        raise ValueError('需要 Node.js/npm 安装验证依赖')
    target = runtime_dir(cache_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'package-lock.json'):
        content = files('affinity2ui').joinpath('runtime', name).read_bytes()
        (target/name).write_bytes(content)
    subprocess.run(['npm', 'ci', '--prefix', str(target), '--ignore-scripts'], check=True)
    return {'directory': str(target), 'playwrightModule': str(playwright_module(cache_dir))}


def doctor():
    from importlib.metadata import version
    result = {'packageVersion': version('loom-affinity2ui'), 'backendVersion': version('psd2ui'),
              'node': shutil.which('node'), 'npm': shutil.which('npm'),
              'runtimeDirectory': str(runtime_dir()), 'affinityEndpoint': 'http://[::1]:6767/sse'}
    try:
        result['playwrightModule'] = str(playwright_module())
        result['nodeRuntimeReady'] = bool(result['node'])
    except ValueError:
        result['nodeRuntimeReady'] = False
    return result
