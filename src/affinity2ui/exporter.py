"""Stage a complete feature before replacing its generated Laya bundle."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from PIL import Image
from .image_dedupe import deduplicate_images, image_nodes
from .prefab import generate_prefab, write_json
from .metadata import preserve_metadata

from .layout import LayoutBuilder, page_roots, patch_prefab, apply_page_relations, BUTTON_DOWN_EFFECTS
from .ninegrid import optimize
from .runtime_support import install_list_adapter
from .images import restore_shared_metadata, pack_images, publish_bundles, restore_prefab_metadata, pack_prefabs, ensure_sprite_texture
from .alignment import validate_content_alignment_config, resolve_content_alignment
from .selection_states import apply_selection_states
from .business_bindings import apply_business_bindings


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover(pages, source=None):
    pages = pages.resolve()
    files = [Path(source)] if source else sorted(pages.glob('*.af'))
    for path in files:
        if path.is_symlink() or path.resolve().parent != pages or path.suffix != '.af' or not path.is_file():
            raise ValueError(f'只接受 pages 下平铺的正式 .af：{path}')
        if not path.stem.isascii() or not path.stem[0].isupper() or not path.stem.isalnum():
            raise ValueError(f'功能文件必须使用英文 PascalCase：{path.name}')
    if not files:
        raise ValueError(f'未找到正式设计稿：{pages}')
    return [path.resolve() for path in files]


def make_plans(snapshot, *, pixel_grid=True):
    if abs(snapshot['dpi'] - 72) > .001:
        raise ValueError(f'设计稿应为72DPI，实际为{snapshot["dpi"]}')
    plans = []
    for root in page_roots(snapshot):
        builder = LayoutBuilder(pixel_grid=pixel_grid)
        layout = builder.build(root)
        plans.append((builder, layout))
    return plans


def export_feature(native, source, project, assets, *, strict=False, dedupe=.99,
                   export_only=False, mode='visual', workers=0, engine_dir=None, plan_only=False, records_dir=None,
                   button_down_effect='dark', content_align_x=None, content_align_y=None,
                   content_align_config=None, pixel_grid=True, ninegrid_ignore_names=None):
    if type(pixel_grid) is not bool:
        raise ValueError('pixel_grid 必须为布尔值')
    if button_down_effect not in BUTTON_DOWN_EFFECTS:
        raise ValueError(f'无效按钮按下效果：{button_down_effect}')
    alignment_config = validate_content_alignment_config(content_align_config)
    resolve_content_alignment('', alignment_config, content_align_x, content_align_y)
    before = sha256(source)
    snapshot = native.open(source)
    plans = make_plans(snapshot, pixel_grid=pixel_grid)
    for _, layout in plans:
        content = next(child for child in layout['children'] if child['name'] == 'content')
        content['contentAlignment'] = resolve_content_alignment(
            layout['name'], alignment_config, content_align_x, content_align_y)
    warnings = [item for builder, _ in plans for item in builder.warnings]
    summary = dict(source=str(source), sourceSha256=before, buttonDownEffect=button_down_effect, pixelGrid=pixel_grid,
                   pages=[dict(name=layout['name'], images=len(builder.jobs), warnings=len(builder.warnings),
                               contentAlignment=next(c['contentAlignment'] for c in layout['children'] if c['name']=='content'))
                          for builder, layout in plans],
                   warnings=warnings, exportOnly=export_only)
    if strict and warnings:
        raise ValueError('严格模式拒绝存在未映射项目的设计稿：' + json.dumps(warnings, ensure_ascii=False))
    if plan_only:
        return summary
    project = project.resolve()
    assets = assets.resolve()
    if not assets.is_relative_to(project / 'assets'):
        raise ValueError('资源目录必须在指定 Laya 工程的 assets 内')
    target = assets / source.stem
    target_identity = directory_identity(target)
    shared_target = assets / 'images'
    shared_identity = directory_identity(shared_target)
    prefab_target = assets / 'prefabs'
    prefab_identity = directory_identity(prefab_target)
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError(f'输出目标必须是普通目录：{target}')
    records_parent = Path(records_dir or Path.cwd() / 'out/affinity-export').resolve()
    if records_parent.is_relative_to(project):
        raise ValueError('中间产物目录必须位于 Laya 工程之外')
    records_target = records_parent / source.stem
    staging_parent = records_parent / '.staging'
    staging_parent.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    if os.stat(staging_parent).st_dev != os.stat(assets).st_dev:
        raise ValueError('中间产物与资源目录需位于同一文件系统，请用 --records-dir 指定工程外的同盘目录')
    with tempfile.TemporaryDirectory(prefix='affinity-', dir=staging_parent) as temporary:
        stage_project = Path(temporary)
        relative = target.relative_to(project)
        staged = stage_project / relative
        staged.mkdir(parents=True)
        # Retain the Laya importer UUID namespace across stages and reexports.
        exchange_parent = Path(getattr(native, 'exchange_dir', Path.home() / 'Desktop'))
        if not exchange_parent.is_dir():
            raise ValueError(f'未找到 Affinity 允许写入的 Desktop：{exchange_parent}')
        with tempfile.TemporaryDirectory(prefix='AffinityExport-', dir=exchange_parent) as exchange:
            jobs = []
            for builder, layout in plans:
                page = staged / layout['name']
                page.mkdir()
                for job in builder.jobs:
                    output = Path(exchange) / f'{len(jobs):05d}.png'
                    jobs.append((builder, layout, job, output, page / job['asset']))
            for offset in range(0, len(jobs), 12):
                batch = jobs[offset:offset+12]
                native.script(dict(path=str(source), session=snapshot['session'], action='render', jobs=[
                    dict(indices=job['indices'], name=job['name'], output=str(output))
                    for _, _, job, output, _ in batch]))
                for _, _, job, output, destination in batch:
                    with Image.open(output) as image:
                        if image.format != 'PNG' or list(image.size) != job['node']['size']:
                            raise ValueError(f'原生切图范围与节点不一致：{job["name"]}: {image.size} / {job["node"]["size"]}')
                        image.load()
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(output, destination)
                print(f'  原生切图 {min(offset+12, len(jobs))}/{len(jobs)}', flush=True)
        after_snapshot = native.script(dict(path=str(source), session=snapshot['session'], action='inspect'))
        if sha256(source) != before or snapshot != after_snapshot:
            raise ValueError('采集期间设计稿发生变化，已丢弃本次暂存结果')
        for builder, layout in plans:
            page = staged / layout['name']
            if dedupe is not None:
                # Keep loader/icon sampling separate from ordinary images.
                for component in ('GImage', 'GLoader'):
                    group = {'children': [n for n in image_nodes(layout) if n['component'] == component]}
                    replacements = deduplicate_images(group, page, dedupe)
                    for asset in replacements:
                        (page / asset).unlink()
            write_json(page / 'layout.json', layout)
        # The PSD metadata helper copies only metadata whose resource already
        # exists. Reserve prefab paths before copying so their UUIDs survive too.
        for _, layout in plans:
            (staged / layout['name'] / (layout['name'] + '.lh')).touch()
        if target.is_dir():
            preserve_metadata(staged, target)
        restore_shared_metadata(staged, shared_target, source.stem, records_target)
        restore_prefab_metadata(staged, prefab_target)
        # Every PNG above is freshly rendered at full source size. Old grid
        # metadata describes the previous optimized texture, not these pixels.
        for meta in staged.rglob('*.png.meta'):
            data = ensure_sprite_texture(json.loads(meta.read_text(encoding='utf-8')))
            data['importer'].pop('sizeGrid', None)
            write_json(meta, data)
        for _, layout in plans:
            page = staged / layout['name']
            prefab_path = page / (layout['name']+'.lh')
            generate_prefab(page / 'layout.json', stage_project,
                            prefab_path.relative_to(stage_project).as_posix(), preserve_resource_paths=True)
            prefab = json.loads(prefab_path.read_text(encoding='utf-8'))
            patch_prefab(prefab, layout, responsive=False, button_down_effect=BUTTON_DOWN_EFFECTS[button_down_effect])
            write_json(prefab_path, prefab)
            for image in image_nodes(layout):
                if image.get('component') == 'GLoader':
                    meta = page / (image['asset'] + '.meta')
                    data = json.loads(meta.read_text(encoding='utf-8'))
                    data.setdefault('importer', {})['filterMode'] = 0
                    write_json(meta, data)
        write_json(staged / 'affinity.json', dict(version=1, **summary, contracts=[
            item for builder, _ in plans for item in builder.contracts]))
        write_json(staged / 'native.json', snapshot)
        write_json(staged / 'diagnostics.json', dict(warnings=warnings, fullPageEnginePreview=False))
        from affinity2ui.shared_images.provenance import pixel_identity
        source_identities={p.relative_to(staged).as_posix():pixel_identity(p) for p in staged.rglob('*.png')}
        if any(n.get('listLayout', {}).get('decorationNames') for _, layout in plans for n in tree_nodes(layout)):
            install_list_adapter(project)
        if not export_only:
            optimize(stage_project, staged, project, mode, workers, engine_dir, ninegrid_ignore_names)
        # Validate/optimize static source geometry first. Apply the known page
        # resizing relations afterwards so they cannot suppress optimization.
        for _, layout in plans:
            prefab_path = staged / layout['name'] / (layout['name']+'.lh')
            prefab = json.loads(prefab_path.read_text(encoding='utf-8'))
            apply_page_relations(prefab, layout)
            apply_selection_states(prefab)
            apply_business_bindings(prefab, project)
            write_json(prefab_path, prefab)
        # Check again immediately before publishing after potentially long optimization.
        final_snapshot = native.script(dict(path=str(source), session=snapshot['session'], action='inspect'))
        if sha256(source) != before or snapshot != final_snapshot:
            raise ValueError('优化期间源文件发生变化，已丢弃本次暂存结果')
        staged_records = stage_project / 'records'
        move_intermediates(staged, staged_records)
        shared_stage = stage_project / 'shared-images'
        pack_images(staged, shared_stage, shared_target, staged_records, records_target, source.stem,source_identities)
        prefab_stage = stage_project / 'prefabs'
        prefabs = pack_prefabs(staged,prefab_stage,prefab_target,staged_records,records_target)
        if directory_identity(shared_target) != shared_identity:
            raise ValueError('导出期间共享图片被修改，已保留原资源')
        if directory_identity(prefab_target) != prefab_identity:
            raise ValueError('导出期间预制体目录被修改，已保留原资源')
        if directory_identity(target) != target_identity:
            raise ValueError('导出期间目标资源被修改，已保留用户修改并丢弃本次暂存结果')
        retired = [target,Path(str(target)+'.meta')] if source.stem.lower() not in ('images','prefabs') else []
        publish_bundles([(prefab_stage,prefab_target), (shared_stage,shared_target), (staged_records,records_target)],
                        stage_project / 'rollback', retired=retired)
    return dict(**summary, output=str(prefab_target), prefabs=[str(prefab_target/p['file']) for p in prefabs],
                images=str(shared_target), records=str(records_target))



def directory_identity(path):
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f'输出目标必须是普通目录：{path}')
    identity = {}
    for file in sorted(path.rglob('*')):
        if file.is_symlink():
            raise ValueError(f'输出目标不能包含符号链接：{file}')
        if file.is_file():
            identity[file.relative_to(path).as_posix()] = sha256(file)
    return identity


def tree_nodes(node):
    yield node
    for child in node.get('children', []):
        yield from tree_nodes(child)


def move_intermediates(bundle, records):
    """Keep only runtime PNG/LH assets and their metadata in the Laya bundle."""
    records.mkdir(parents=True, exist_ok=True)
    report_directory = bundle / 'export-records'
    if report_directory.exists():
        shutil.move(str(report_directory), str(records / 'export-records'))
    for file in sorted(bundle.rglob('*')):
        if not file.is_file():
            continue
        final = file.suffix.lower() in ('.png','.lh') or file.name.endswith(('.png.meta','.lh.meta'))
        folder_meta = file.suffix == '.meta' and file.with_suffix('').is_dir()
        if final or folder_meta:
            continue
        destination = records / file.relative_to(bundle)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file), str(destination))
    for directory in sorted((p for p in bundle.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
