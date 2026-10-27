"""Narrow compatibility adapter for this project's installed LayaAir 3.4.2."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
from .ninegrid_references import native_ui_references


@contextmanager
def project_version(version, libraries):
    from ninegrid.laya.project import LayaProject
    core = (Path(libraries) / 'laya.core.js').read_text(encoding='utf-8')
    match = re.search(r'LayaEnv\.version\s*=\s*[\'"]([^\'"]+)', core)
    if version not in {'3.4.1', '3.4.2'} or not match or match[1] != version:
        raise ValueError(f'九宫格引擎与项目版本不匹配：工程 {version}，引擎 {match[1] if match else "未知"}')
    original = LayaProject.SUPPORTED
    # 3.4.2 uses the same version-1 .lh and PNG importer fields. All texture
    # changes still pass NineGrid's actual engine pixel comparison before apply.
    LayaProject.SUPPORTED = original | {version}
    try:
        yield
    finally:
        LayaProject.SUPPORTED = original


def optimize(stage_project, staged, original_project, mode, workers, engine_dir, ignore_names=None):
    from ninegrid.engine import engine_libraries
    from ninegrid.laya.adapter import LayaProjectAdapter
    from ninegrid.parallel import ImagePool
    from ninegrid.pipeline import build, apply
    from ninegrid.verify import verify_project
    from ninegrid.run_9grid import print_report
    from psd2ui.laya_prefab import write_json
    from .ninegrid_names import configured_ignore_names, normalize_ignored_names
    ignore_names=configured_ignore_names() if ignore_names is None else normalize_ignored_names(ignore_names)
    versions = {json.loads(p.read_text(encoding='utf-8'))['version'] for p in original_project.glob('*.laya')}
    if len(versions) != 1:
        raise ValueError('需要单一有效的 Laya 工程版本')
    version = next(iter(versions))
    libraries = engine_libraries(original_project, engine_dir)
    # Export staging must see the same ancestor atlas settings as the project,
    # including Point/Linear overrides, before accepting any texture changes.
    parent = staged
    assets = stage_project / 'assets'
    while parent.is_relative_to(assets):
        original = original_project / parent.relative_to(stage_project)
        for config in original.glob('*.atlascfg'):
            target = parent / config.name
            if target.exists() and target.read_bytes() != config.read_bytes():
                raise ValueError(f'暂存图集设置与工程不一致：{config}')
            if not target.exists():
                shutil.copy2(config, target)
        parent = parent.parent
    write_json(stage_project / 'AffinityExport.laya', {'version':version})
    with project_version(version, libraries), native_ui_references(), ImagePool(workers, progress=print) as pool:
        result = build(LayaProjectAdapter(stage_project), inputs=[staged], output=staged,
                       mode=mode, min_saving=.2, center_size=1, pool=pool, ignore_names=ignore_names)
        print_report(result['report'])
        validated = {}
        def validate_pending(adapter, entries, unused):
            pending=[];retained=[]
            def key(entry):
                item=entry['item']
                return (item['source'],item['outputSha256'],item['layaSizeGrid'],
                        tuple(item.get('validationFilterModes',[])),tuple(entry['types']))
            for entry in entries:
                if key(entry) in validated:retained.extend(validated[key(entry)])
                else:pending.append(entry)
            proof=validate_engine(adapter,pending,libraries,version,pool)
            for entry in pending:
                cases=[c for c in proof['cases'] if Path(c['source']).stem==entry['item']['sourceSha256']]
                if cases and all(c['accepted'] for c in cases):validated[key(entry)]=cases
            combined=dict(proof,cases=retained+proof['cases'])
            combined['valid']=bool(combined['cases']) and all(c['accepted'] for c in combined['cases'])
            (stage_project/'.ninegrid/validation/report.json').write_text(json.dumps(combined,indent=2)+'\n')
            return combined
        for attempt in range(17):
            try:
                apply(LayaProjectAdapter(stage_project), pool=pool,
                      engine_validator=validate_pending)
                break
            except (ValueError, RuntimeError):
                diagnostics = stage_project.parent.parent / 'failures' / (stage_project.name + f'-attempt-{attempt}')
                diagnostics.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(stage_project / '.ninegrid', diagnostics, dirs_exist_ok=True)
                proof_path=stage_project/'.ninegrid/validation/report.json'
                if attempt==16 or not proof_path.is_file():raise
                from ninegrid.retry import inset_failed_candidates
                proof=json.loads(proof_path.read_text())
                if proof.get('valid'):raise
                changed=inset_failed_candidates(LayaProjectAdapter(stage_project),proof)
                if not changed:raise
                print(f'  引擎采样校验重试：自动收紧 {len(changed)} 张图的拉伸区，误差上限保持不变',flush=True)
        verify_project(LayaProjectAdapter(stage_project), pool=pool)
    # Raw package reports retain their original version labels. Record the
    # actual engine version checked above, alongside the unmodified proof.
    records = staged / 'export-records/ninegrid'
    records.mkdir(parents=True)
    for name in ('report.json', 'report.md', 'apply-report.json', 'validation/report.json'):
        source = stage_project / '.ninegrid' / name
        if source.is_file():
            destination = records / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for name in ('originals', 'validation'):
        source = stage_project / '.ninegrid' / name
        if source.is_dir():
            shutil.copytree(source, records / name, dirs_exist_ok=True)
    write_json(records / 'compatibility.json', dict(projectVersion=version, engineVersion=version,
        engineLibraries=str(libraries), adapter='affinity2ui', layoutStage='before-ninegrid',
        referencePolicy='native-ui-static-images', retainedCenterSize=1,
        reportPathMapping={'.ninegrid/':'export-records/ninegrid/'}))


def validate_engine(adapter, entries, libraries, version, pool):
    """Use NineGrid's original render cases and pixel comparisons on 3.4.2."""
    import os
    import subprocess
    from ninegrid import engine
    from ninegrid.jobs import compare_render
    from ninegrid.paths import inside, load_json, atomic_write, json_bytes
    root = adapter.project.root
    directory = inside(root, '.ninegrid/validation')
    directory.mkdir(parents=True, exist_ok=True)
    from .runtime_env import playwright_module
    module_path = str(playwright_module())
    # Keep every render assertion in the upstream probe. Only replace its exact
    # version guard, after checking actual engine/project version consistency.
    source = Path(engine.__file__).with_name('engine_probe.mjs').read_text(encoding='utf-8')
    old = "if (Laya.LayaEnv.version !== '3.4.1') throw new Error('Unverified engine version');"
    dynamic = "if (Laya.LayaEnv.version !== version) throw new Error('Unverified engine version');"
    if source.count(old) != 1:
        # The pinned 1.1 backend passes version into page.evaluate. Keep its
        # guard unchanged and supply the validated project version in payload.
        if (source.count(dynamic) != 1
                or source.count("version:config.version||'3.4.1'") != 1
                or source.count('async ({width, height, version})') != 1):
            raise ValueError('NineGrid 引擎探针接口已变化，需要重新适配')
        old = dynamic
    script = directory / 'engine_probe.mjs'
    substitutions = {
        old: old if old == dynamic else f"if (Laya.LayaEnv.version !== {json.dumps(version)}) throw new Error('Unverified engine version');",
        'const width = Math.max(...dimensions.map(d => d[0])) + 32;':
            'const width = Math.ceil(Math.max(...dimensions.map(d => d[0])) * 1.2) + 64;',
        'const height = Math.max(...dimensions.map(d => d[1])) + 32;':
            'const height = Math.ceil(Math.max(...dimensions.map(d => d[1])) * 1.2) + 64;',
        "c.source + ':' + c.type + ':' + c.filterMode":
            "c.source + ':' + c.type + ':' + c.filterMode + ':' + c.pose",
        "name: 'Probe', x: 16, y: 16, width:":
            "name: 'Probe', x: 16 + data.offsetX, y: 16 + data.offsetY, scaleX: data.renderScale, scaleY: data.renderScale, width:",
        'width: c.sourceSize[0], height: c.sourceSize[1]':
            'width: Math.ceil(c.sourceSize[0] * c.renderScale) + 2, height: Math.ceil(c.sourceSize[1] * c.renderScale) + 2',
        'type: c.type, filterMode: c.filterMode, mode:':
            'type: c.type, filterMode: c.filterMode, pose: c.pose, mode:',
    }
    for original, replacement in substitutions.items():
        expected = 2 if original == 'width: c.sourceSize[0], height: c.sourceSize[1]' else 1
        if source.count(original) != expected:
            raise ValueError(f'NineGrid 引擎探针接口已变化：{original}')
        source = source.replace(original, replacement)
    script.write_text(source, encoding='utf-8')
    cases = []
    for entry in entries:
        item = entry['item']
        original = item.get('originalBackup', item['source'])
        output = item.get('stagedOutput', item['output']) if item.get('status') != 'applied' else item['output']
        meta_path = inside(root, item['source'] + '.meta')
        meta = load_json(meta_path) if meta_path.exists() else {}
        for filter_mode in item.get('validationFilterModes', [meta.get('importer', {}).get('filterMode', 1)]):
            for kind in entry['types']:
                for pose, scale, x, y in (('normal', 1, 0, 0), ('subpixel', 1, .5, .25),
                                          ('down-scale', .8, .5, .25), ('up-scale', 1.2, .5, .25)):
                    # Avoid exact texel-boundary ties with Point sampling:
                    # float UV rounding can select either adjacent texel even
                    # when the image is losslessly represented. Linear keeps
                    # its half-pixel cases; Point still tests fractional poses.
                    if filter_mode == 0 and x:
                        x = .375
                    cases.append(dict(source=str(inside(root, original)), output=str(inside(root, output)),
                        type=kind, sourceSize=item['sourceSize'], sizeGrid=item['layaSizeGrid'],
                        filterMode=filter_mode, mode=item.get('mode', 'strict'),
                        qualityLimits=item.get('qualityLimits'), pose=pose, renderScale=scale, offsetX=x, offsetY=y))
    payload = dict(project=str(root), libraries=str(libraries), artifacts=str(directory), cases=cases, version=version)
    env = dict(os.environ, NINEGRID_PLAYWRIGHT_MODULE=module_path)
    result = subprocess.run(['node', str(script)], input=json.dumps(payload), capture_output=True,
                            text=True, timeout=180, env=env)
    if result.returncode:
        raise ValueError('LayaAir 引擎验证失败：' + result.stderr[-3000:])
    records = json.loads(result.stdout)
    stats = []
    for stat, diff in pool.map(compare_render, [(str(root), record) for record in records], '引擎截图比较'):
        if diff is not None:
            atomic_write(inside(root, stat['after'] + '.diff.png'), diff)
        stats.append(stat)
    proof = dict(valid=all(s['accepted'] for s in stats) and len(stats) == len(cases),
                 engine='LayaAir ' + version, renderer='Chrome WebGL', cases=stats)
    atomic_write(directory / 'report.json', json_bytes(proof))
    return proof
