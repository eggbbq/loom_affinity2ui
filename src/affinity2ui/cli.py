"""Installed entry point. Parse workspace before importing the export backend."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys


def similarity(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise argparse.ArgumentTypeError('相似度必须在 0～1 之间')
    return value


def parser():
    result = argparse.ArgumentParser(description='Affinity → LayaAir UI 独立导出工具')
    result.add_argument('--workspace', type=Path, default=Path.cwd())
    result.add_argument('--version', action='version', version='loom-affinity2ui 0.1.2')
    commands = result.add_subparsers(dest='command', required=True)
    def command(name, help):
        child = commands.add_parser(name, help=help)
        child.add_argument('--workspace', type=Path, default=argparse.SUPPRESS)
        return child
    command('init', '初始化工作区配置（不创建或覆盖 Laya 工程）')
    runtime = command('setup-runtime', '在用户缓存中安装引擎验证的 Node 依赖')
    runtime.add_argument('--cache-dir', type=Path)
    command('doctor', '检查包、后端和验证运行时，不连接 Affinity')
    def configured(child):
        child.add_argument('--config', type=Path)
        child.add_argument('--project', type=Path)
        child.add_argument('--laya-assets-dir', type=Path)
        child.add_argument('--records-dir', type=Path)
        return child
    for name in ('export', 'export-all'):
        child = configured(command(name, '导出指定 AF' if name == 'export' else '批量导出配置目录内 AF'))
        if name == 'export':child.add_argument('source', type=Path)
        else:child.add_argument('--sources-dir', type=Path)
        child.add_argument('--plan', action='store_true')
        child.add_argument('--export-only', action='store_true')
        child.add_argument('--strict', action=argparse.BooleanOptionalAction, default=None)
        child.add_argument('--pixel-grid', action=argparse.BooleanOptionalAction, default=None)
        child.add_argument('--workers', type=int)
        child.add_argument('--dedupe-images', type=similarity, default=argparse.SUPPRESS)
        child.add_argument('--no-dedupe-images', dest='dedupe_images', action='store_const', const=None, default=argparse.SUPPRESS)
        child.add_argument('--mode', choices=('visual','strict'))
        child.add_argument('--button-down-effect', choices=('none','dark','up-scale','down-scale'))
        child.add_argument('--engine-dir', type=Path)
        child.add_argument('--report-dir', type=Path)
        child.add_argument('--content-align-x', choices=('auto','left','center','right'))
        child.add_argument('--content-align-y', choices=('auto','top','center','bottom'))
        child.add_argument('--content-align-config', type=Path)
        child.add_argument('--ninegrid-ignore-names', type=json.loads)
        child.add_argument('--resize-check', action=argparse.BooleanOptionalAction, default=None)
        child.add_argument('--exchange-dir', type=Path, help='Affinity 允许写入的切图交换目录，默认 Desktop')
        child.add_argument('--already-open', action='store_true', help='源文档已在 Affinity 中打开，不调用系统 open')
    configured(command('check', '仅检查已有资源和引擎证明，不重新导出')).add_argument('--engine-dir', type=Path)
    child = configured(command('dedupe', '独立跨页面去重及共享依赖恢复'))
    child.add_argument('--state-dir', type=Path)
    child.add_argument('--threshold', type=similarity, default=.99)
    child.add_argument('--existing-images', type=Path)
    child.add_argument('--fresh-prefabs', nargs='*', default=[])
    child.add_argument('--source-records', type=Path, action='append', default=[])
    child.add_argument('--restore-only', action='store_true')
    child = configured(command('migrate', '预览或迁移旧图片长文件名'))
    child.add_argument('--apply', action='store_true')
    child = configured(command('reoptimize', '从匹配原图记录重优化指定现有图片'))
    next(action for action in child._actions if action.dest == 'records_dir').required = True
    child.add_argument('images', type=Path, nargs='+')
    child.add_argument('--original-records', type=Path, action='append', default=[])
    child.add_argument('--workers', type=int, default=2)
    child.add_argument('--engine-dir', type=Path)
    return result


def settings(args, root):
    from .config import load_config
    path = root/args.config if getattr(args,'config',None) else root/'export_all_ui.toml'
    config = load_config(path if path.exists() else None)
    if getattr(args,'config',None) and not path.exists():
        raise ValueError(f'配置不存在：{path}')
    paths = {key:(root/value).resolve() for key,value in config['paths'].items()}
    if getattr(args,'project',None):
        paths['project'] = (root/args.project).resolve()
        if not getattr(args,'laya_assets_dir',None):paths['assets'] = paths['project']/'assets/ui'
    for key,argument in [('assets','laya_assets_dir'),('records','records_dir'),('sources','sources_dir')]:
        if getattr(args,argument,None):paths[key] = (root/getattr(args,argument)).resolve()
    return config, paths


def run(args, root):
    if args.command == 'init':
        from .config import init_workspace
        return init_workspace(root)
    if args.command == 'setup-runtime':
        from .runtime_env import setup_runtime
        return setup_runtime(args.cache_dir)
    if args.command == 'doctor':
        from .runtime_env import doctor
        return doctor()
    config, paths = settings(args, root)
    if args.command in ('export','export-all'):
        from .api import export_sources
        from .exporter import discover
        from .alignment import load_content_alignment_config
        sources = [root/args.source] if args.command == 'export' else discover(paths['sources'])
        configured = config['export']
        def value(argument, section, key=None):
            supplied = getattr(args,argument,None)
            return supplied if supplied is not None else config[section][key or argument]
        layout_file = value('content_align_config','layout')
        options = dict(strict=value('strict','export'), pixel_grid=value('pixel_grid','export'),
            workers=value('workers','export'), mode=value('mode','export','ninegrid_mode'),
            dedupe=args.dedupe_images if hasattr(args,'dedupe_images') else configured['dedupe_similarity'],
            button_down_effect=value('button_down_effect','export'),
            content_align_x=value('content_align_x','layout') or None,
            content_align_y=value('content_align_y','layout') or None,
            content_align_config=load_content_alignment_config(root/layout_file) if layout_file else None,
            ninegrid_ignore_names=value('ninegrid_ignore_names','export'),
            export_only=args.export_only, engine_dir=(root/args.engine_dir).resolve() if args.engine_dir else None)
        if options['workers'] < 0:raise ValueError('workers 不能小于 0')
        source_options = {'open_document':not args.already_open}
        if args.exchange_dir:source_options['exchange_dir'] = str((root/args.exchange_dir).resolve())
        report_dir = (root/args.report_dir).resolve() if args.report_dir else None
        if report_dir is None and not args.plan:
            import uuid
            report_dir = paths['reports']/('run-'+uuid.uuid4().hex)
        return export_sources(sources, workspace=root, project=paths['project'], assets_dir=paths['assets'],
            records_dir=paths['records'], report_dir=report_dir,
            plan_only=args.plan, rebuilding_all=args.command=='export-all',
            source_options=source_options, resize=value('resize_check','checks','resize'),
            repair_records=[root/path for path in config['checks']['repair_records']], **options)
    if args.command == 'dedupe':
        from .shared_images.pipeline import run as dedupe
        preferred = json.loads((root/args.existing_images).read_text()) if args.existing_images else None
        return dedupe(paths['project'],paths['assets'],(root/args.state_dir).resolve() if args.state_dir else paths['records']/'shared-image-dedupe',
            threshold=args.threshold,preferred=preferred,fresh_prefabs=args.fresh_prefabs,
            restore_only=args.restore_only,source_records=[root/path for path in args.source_records])
    if args.command == 'migrate':
        from .image_name_migration import migrate
        return migrate(paths['project'],paths['assets'],paths['records'],apply=args.apply)
    if args.command == 'reoptimize':
        from .reoptimize import reoptimize
        primary = (root/config['paths']['records']).resolve()
        output = paths['records']
        if output.is_relative_to(primary) or primary.is_relative_to(output):
            raise ValueError('重优化报告必须使用独立目录，不能覆盖、包含或位于主导出记录目录内')
        return reoptimize(paths['project'],[root/path for path in args.images],paths['records'],
                          [root/path for path in args.original_records],workers=args.workers,
                          engine_dir=(root/args.engine_dir).resolve() if args.engine_dir else None)
    if args.command == 'check':
        from .audit import audit
        from .verify_export import verify_exported_resize
        import tempfile
        reports = paths['reports']
        if reports.is_relative_to(paths['project']):raise ValueError('报告目录必须在工程外')
        reports.mkdir(parents=True,exist_ok=True)
        report = Path(tempfile.mkdtemp(prefix='check-',dir=reports))
        repairs = [root/path for path in config['checks']['repair_records']]
        resources = audit(report/'resources.json',project=paths['project'],assets=paths['assets'],records=paths['records'],
            quiet=True,ignored_names=config['export']['ninegrid_ignore_names'],repair_records=repairs)
        resize = verify_exported_resize(report/'resize-project',paths['project'],paths['assets'],paths['records'],
            repair_records=repairs,engine_dir=(root/args.engine_dir).resolve() if args.engine_dir else None) if config['checks']['resize'] else None
        result = dict(valid=True,resources=resources,resize=resize,reportDirectory=str(report))
        (report/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return result


def main(argv=None):
    args = parser().parse_args(argv)
    original = Path.cwd()
    root = args.workspace.expanduser().resolve()
    try:
        if args.command == 'init':root.mkdir(parents=True,exist_ok=True)
        if not root.is_dir():raise ValueError(f'工作区不存在：{root}')
        os.chdir(root)
        result = run(args,root)
        if result is not None:print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,ImportError,subprocess.SubprocessError) as error:
        print(f'affinity2ui 未完成：{error}',file=sys.stderr)
        return 1
    finally:
        os.chdir(original)
