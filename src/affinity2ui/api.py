"""High-level, workspace-explicit API; no command-line globals are modified."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading

_WORKSPACE_LOCK = threading.RLock()


@contextmanager
def workspace_directory(workspace):
    """Resolve legacy relative paths consistently inside the explicit workspace.

    This context restores cwd on success and failure. Calls are process-local;
    use separate processes for concurrent exports in different workspaces.
    """
    with _WORKSPACE_LOCK:
        # Resolve relative workspaces only after the previous export restored
        # cwd; otherwise a second caller could accidentally select its workspace.
        workspace = Path(workspace).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f'工作区不存在：{workspace}')
        original = Path.cwd()
        os.chdir(workspace)
        try:
            yield workspace
        finally:
            os.chdir(original)


def export_sources(sources, *, workspace, project='client', assets_dir=None,
                   records_dir='out/affinity-export', report_dir=None, source_factory=None,
                   plan_only=False, rebuilding_all=False, resize=True, source_options=None,
                   repair_records=(), **options):
    with workspace_directory(workspace) as root:
        # Deliberately import only after selecting the caller's workspace.
        from .workflow import run_export
        from .exporter import discover, export_feature
        from .bridge import NativeAffinity
        paths = [Path(p) if Path(p).is_absolute() else root/Path(p) for p in sources]
        if not paths:
            raise ValueError('没有指定 AF 源文件')
        for path in paths:
            if path.is_symlink() or path.suffix.lower() != '.af' or not path.is_file():
                raise ValueError(f'需要普通 AF 文件：{path}')
        if len({p.stem.casefold() for p in paths}) != len(paths):
            raise ValueError('本批 AF 功能文件名重复')
        project = (root/project).resolve()
        assets = (root/assets_dir).resolve() if assets_dir else project/'assets/ui'
        records = (root/records_dir).resolve()
        if not assets.is_relative_to(project/'assets'):
            raise ValueError('资源目录必须在 Laya 工程 assets 内')
        if plan_only:
            with (source_factory or NativeAffinity)(**(source_options or {})) as adapter:
                return [export_feature(adapter, path.resolve(), project, assets, plan_only=True, **options) for path in paths]
        return run_export(root, paths, project, assets, records, report_dir=report_dir,
                          source_factory=source_factory, source_options=source_options,
                          rebuilding_all=rebuilding_all, resize=resize,
                          repair_records=[(root/path).resolve() for path in repair_records], **options)


def export_all(*, workspace, sources_dir='art/ui/pages', **options):
    with workspace_directory(workspace) as root:
        from .exporter import discover
        sources = discover((root/sources_dir).resolve())
    return export_sources(sources, workspace=workspace, rebuilding_all=True, **options)
