"""Stage Affinity conversion and all final checks before touching live outputs."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .exporter import directory_identity, export_feature
from .images import publish_bundles
from .orchestration import SharedImageStep
from .audit import audit
from .verify_export import verify_exported_resize


def run_export(root, sources, project, assets, records, *, report_dir=None, resize=True,
               repair_records=(), rebuilding_all=False, source_options=None, source_factory=None, **options):
    root, project, assets, records = map(lambda p:Path(p).resolve(), (root,project,assets,records))
    if (not assets.is_relative_to(project/'assets') or records.is_relative_to(project)
            or project.is_relative_to(records)):
        raise ValueError('资源须在工程 assets 内，记录须在工程外且不能包含工程')
    sources = [Path(p).resolve() for p in sources]
    identities = {p:directory_identity(p) for p in (assets, records, project/'src/ui')}
    source_hashes = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    records.parent.mkdir(parents=True,exist_ok=True)
    if report_dir is None:
        report_root = root/'out/ui-export-reports';report_root.mkdir(parents=True,exist_ok=True)
        report_dir = Path(tempfile.mkdtemp(prefix='run-',dir=report_root))
    report_dir = Path(report_dir).resolve()
    if report_dir.is_relative_to(project):raise ValueError('检查报告须在工程之外')
    report_dir.mkdir(parents=True,exist_ok=True)
    print(f'报告：{report_dir}',flush=True)
    with tempfile.TemporaryDirectory(prefix='affinity-batch-',dir=records.parent) as temporary:
        stage = Path(temporary);staged_project = stage/'project';staged_project.mkdir()
        for config in project.glob('*.laya'):shutil.copy2(config,staged_project/config.name)
        for folder in ('assets','src','settings'):
            if (project/folder).exists():shutil.copytree(project/folder,staged_project/folder)
        staged_assets = staged_project/assets.relative_to(project)
        staged_records = stage/'records'
        if records.exists():shutil.copytree(records,staged_records)
        else:staged_records.mkdir()
        index = staged_records/'shared-image-dedupe/index.json'
        if index.exists():
            state = json.loads(index.read_text());state['project']=str(staged_project)
            index.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
        try:
            step = SharedImageStep(root,staged_project,staged_assets,staged_records,
                                   .99 if options.get('dedupe') is None else options.get('dedupe',.99))
            if rebuilding_all and not any((staged_assets/'images').glob('*.png')):
                covered = {p.stem.casefold() for p in sources}
                missing = {p.parent.name for p in staged_records.glob('*/affinity.json') if p.parent.name.casefold() not in covered}
                if missing:
                    raise ValueError('图片目录为空，但本批输入未覆盖原有页面，不能安全恢复：'+', '.join(sorted(missing)))
            step.prepare(rebuilding_all=rebuilding_all)
            results, prefabs = [], []
            from .bridge import NativeAffinity
            with (source_factory or NativeAffinity)(**(source_options or {})) as source_adapter:
                for source in sources:
                    print(f'Affinity → LayaAir：{source}',flush=True)
                    result = export_feature(source_adapter,source,staged_project,staged_assets,
                                            records_dir=staged_records,**options)
                    results.append(result);prefabs.extend(result['prefabs'])
            if options.get('dedupe',.99) is not None:
                step.finish(prefabs)
            proof = audit(report_dir/'resources.json',project=staged_project,assets=staged_assets,
                          records=staged_records,quiet=True,ignored_names=options.get('ninegrid_ignore_names'),
                          repair_records=repair_records)
            resizing = None
            if resize and not options.get('export_only',False):
                resizing = verify_exported_resize(report_dir/'resize-project',staged_project,staged_assets,
                                                  staged_records,repair_records=repair_records,
                                                  engine_dir=options.get('engine_dir'))
            for target,identity in identities.items():
                if directory_identity(target) != identity:
                    raise ValueError(f'导出期间目标发生变化，未发布：{target}')
            if any(hashlib.sha256(p.read_bytes()).hexdigest()!=digest for p,digest in source_hashes.items()):
                raise ValueError('导出期间 Affinity 发生变化，未发布')
            if index.exists():
                state = json.loads(index.read_text());state['project']=str(project)
                index.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
            pairs = [(staged_assets,assets),(staged_records,records)]
            runtime = staged_project/'src/ui'
            if directory_identity(runtime) != identities[project/'src/ui']:
                pairs.append((runtime,project/'src/ui'))
            publish_bundles(pairs,stage/'rollback')
        except BaseException as error:
            shutil.copytree(staged_records,report_dir/'failed-records',dirs_exist_ok=True)
            if hasattr(error, 'diagnostics'):
                (report_dir/'design-check.json').write_text(json.dumps(error.diagnostics,ensure_ascii=False,indent=2)+'\n')
            (report_dir/'failure.json').write_text(json.dumps({'valid':False,'error':str(error)},ensure_ascii=False,indent=2)+'\n')
            raise
    summary = {'valid':True,'sources':[str(p) for p in sources], 'project':str(project),'assets':str(assets),
               'records':str(records),'resources':proof,'resize':resizing,'reportDirectory':str(report_dir),
               'engineCases':proof['engineCases']+(resizing['cases'] if resizing else 0),
               'exportOnly':options.get('export_only',False),'publishedAfterChecks':True}
    summary['sourceOptions'] = dict(source_options or {})
    (report_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (report_dir.parent/'latest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(f'完成：{len(sources)} 个 Affinity，{proof["liveImages"]} 张图片，丢失引用 0；全部检查完成后已发布。',flush=True)
    return summary
