"""Verify public API transaction behavior using a fake native document source."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from affinity2ui.api import export_sources
from affinity2ui.api import workspace_directory
from affinity2ui.exporter import directory_identity


def node(name, children=(), **values):
    return dict(name=name, kind='GroupNode', box=[0,0,64,64], visibleBox=[0,0,64,64],
                visible=True, opacity=1, indices=[0], effects=False, enclosures=0,
                transform=[1,0,0,0,1,0], children=list(children), **values)


class FixtureSource:
    """Produces native-like metadata; proves package orchestration, not AF rendering."""
    def __init__(self, **unused):
        self.data = None

    def __enter__(self):return self
    def __exit__(self, *unused):return None

    def open(self, path):
        page = node(path.stem+'Panel', [node('bg',[dict(node('shape'),kind='ShapeNode')]), node('content')])
        self.data = dict(path=str(path),session='fixture-session',dpi=72,
                         tree=dict(node('',[page]),kind='DocumentNode'))
        return copy.deepcopy(self.data)

    def script(self, request):
        if request['action']=='inspect':return copy.deepcopy(self.data)
        for job in request['jobs']:
            Image.new('RGBA',(64,64),(40,80,120,255)).save(job['output'])
        return []


class PublicAPITests(unittest.TestCase):
    def test_relative_workspace_is_resolved_after_waiting_for_other_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();other=root/'other';other.mkdir()
            original=Path.cwd();entered=threading.Event();requested=threading.Event()
            release=threading.Event();observed=[];errors=[]
            class ObservableLock:
                def __init__(self):self.lock=threading.RLock()
                def __enter__(self):
                    if threading.current_thread().name=='second-export':requested.set()
                    self.lock.acquire()
                    return self
                def __exit__(self,*unused):self.lock.release()
            def first():
                try:
                    with workspace_directory(other):
                        entered.set()
                        if not release.wait(5):raise RuntimeError('release timeout')
                except BaseException as error:errors.append(error)
            def second():
                try:
                    with workspace_directory('.') as selected:observed.append(selected)
                except BaseException as error:errors.append(error)
            import os
            os.chdir(root)
            try:
                with patch('affinity2ui.api._WORKSPACE_LOCK',ObservableLock()):
                    one=threading.Thread(target=first,name='first-export');one.start()
                    self.assertTrue(entered.wait(5))
                    two=threading.Thread(target=second,name='second-export');two.start()
                    self.assertTrue(requested.wait(5))
                    release.set();one.join(5);two.join(5)
                self.assertFalse(one.is_alive() or two.is_alive())
                self.assertFalse(errors)
                self.assertEqual(observed,[root])
                self.assertEqual(Path.cwd(),root)
            finally:
                release.set()
                os.chdir(original)

    def setup_workspace(self, root):
        workspace = root/'workspace';pages=workspace/'art/ui/pages';pages.mkdir(parents=True)
        sources=[]
        for name in ('First','Second'):
            source=pages/(name+'.af');source.write_bytes(('fixture-'+name).encode());sources.append(source)
        project=workspace/'client';project.mkdir()
        (project/'Fixture.laya').write_text('{"version":"3.4.2"}')
        return workspace, sources

    def test_api_exports_without_source_repo_scripts_and_keeps_uuid_on_reexport(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace,sources=self.setup_workspace(Path(folder))
            cwd=Path.cwd()
            result=export_sources(sources,workspace=workspace,source_factory=FixtureSource,export_only=True)
            self.assertEqual(Path.cwd(),cwd)
            self.assertTrue(result['valid'])
            images=workspace/'client/assets/ui/images';prefabs=workspace/'client/assets/ui/prefabs'
            self.assertEqual(len(list(prefabs.glob('*.lh'))),2)
            self.assertEqual(len(list(images.glob('*.png'))),1)
            uuids={p.name:json.loads(p.read_text())['uuid'] for p in images.glob('*.png.meta')}
            export_sources(sources,workspace=workspace,source_factory=FixtureSource,export_only=True)
            self.assertEqual(Path.cwd(),cwd)
            self.assertEqual({p.name:json.loads(p.read_text())['uuid'] for p in images.glob('*.png.meta')},uuids)
            self.assertFalse(list((workspace/'client').rglob('affinity.json')))

    def test_final_audit_failure_leaves_existing_live_outputs_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace,sources=self.setup_workspace(Path(folder))
            export_sources(sources,workspace=workspace,source_factory=FixtureSource,export_only=True)
            paths=(workspace/'client/assets/ui',workspace/'out/affinity-export')
            before={p:directory_identity(p) for p in paths}
            cwd=Path.cwd()
            with patch('affinity2ui.workflow.audit',side_effect=ValueError('injected final audit failure')):
                with self.assertRaisesRegex(ValueError,'final audit failure'):
                    export_sources(sources,workspace=workspace,source_factory=FixtureSource,export_only=True)
            self.assertEqual({p:directory_identity(p) for p in paths},before)
            self.assertEqual(Path.cwd(),cwd)

    def test_explicit_engine_directory_reaches_final_resize_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace,sources=self.setup_workspace(Path(folder))
            engine=workspace/'engine-libs'
            with patch('affinity2ui.exporter.optimize'), \
                    patch('affinity2ui.workflow.audit',return_value={'engineCases':0,'liveImages':1}), \
                    patch('affinity2ui.workflow.verify_exported_resize',return_value={'valid':True,'cases':1}) as verify:
                result=export_sources(sources[:1],workspace=workspace,source_factory=FixtureSource,
                                      engine_dir=engine,export_only=False,dedupe=None)
            self.assertTrue(result['valid'])
            self.assertEqual(verify.call_args.kwargs['engine_dir'],engine)


if __name__ == '__main__':unittest.main()
