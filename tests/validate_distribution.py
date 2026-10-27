#!/usr/bin/env python3
"""Install built releases into an isolated environment and validate outside checkout.

This script intentionally uses a new venv without system-site-packages, removes
PYTHONPATH, and runs Python with -I. Its output distinguishes mocked native AF
fixtures from actual Affinity/engine execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheelhouse', type=Path, default=ROOT/'release')
    parser.add_argument('--output', type=Path, default=ROOT/'out/package-validation')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--engine-smoke', action='store_true', help='Install cached Node dependencies and run a small real Laya/Chrome optimization')
    args = parser.parse_args()
    wheelhouse = args.wheelhouse.resolve();output=args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    wheels = sorted(wheelhouse.rglob('loom_affinity2ui-*.whl'))
    if len(wheels)!=1:
        raise SystemExit('Expected exactly one loom-affinity2ui wheel in '+str(wheelhouse))
    wheel = wheels[0]
    dependency_wheels = wheel.parent
    grid_wheels=list(dependency_wheels.glob('loom_image9grid-1.1.0-*.whl'))
    if len(grid_wheels)!=1:
        raise SystemExit('Expected the official loom-image9grid 1.1.0 wheel')
    grid_sha=hashlib.sha256(grid_wheels[0].read_bytes()).hexdigest()
    if grid_sha!='dc63c5401f01d1410d8a83a91e882c1fae9994a97752c35dffb66ad063345cf6':
        raise SystemExit('Official image9grid wheel checksum mismatch')
    if list(dependency_wheels.glob('psd*.whl')):
        raise SystemExit('Release wheelhouse contains retired PSD dependencies')
    with zipfile.ZipFile(wheel) as package_wheel:
        if any(name.startswith(('ninegrid/','psd2ui/','psd_tools/')) for name in package_wheel.namelist()):
            raise SystemExit('Main wheel contains a dependency-owned namespace')
    environment = os.environ.copy()
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'):
        environment.pop(key, None)
    environment['PYTHONDONTWRITEBYTECODE']='1'
    steps = []
    def checked(command, cwd, name):
        result = subprocess.run([str(part) for part in command], cwd=cwd, env=environment,
                                capture_output=True, text=True, timeout=300)
        (output/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        steps.append({'name':name,'returncode':result.returncode})
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {output/(name+".log")}')
        return result
    with tempfile.TemporaryDirectory(prefix='loom-affinity2ui-installed-') as temporary:
        temporary=Path(temporary);venv=temporary/'venv';workspace=temporary/'workspace';workspace.mkdir()
        checked([sys.executable,'-m','venv',venv],temporary,'create-isolated-venv')
        python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        cli=venv/('Scripts/affinity2ui.exe' if os.name=='nt' else 'bin/affinity2ui')
        install=[python,'-m','pip','install','--disable-pip-version-check','--find-links',dependency_wheels,wheel]
        if args.offline:install.insert(4,'--no-index')
        checked(install,workspace,'install-wheel')
        checked([python,'-m','pip','check'],workspace,'pip-check')
        code='''
import importlib.metadata as metadata
import importlib.util
from importlib.resources import files
import json,os,pathlib,sys
before=os.getcwd()
import affinity2ui
import affinity2ui.api
import affinity2ui.bridge
import affinity2ui.shared_images.pipeline
assert os.getcwd()==before
assert pathlib.Path(affinity2ui.__file__).is_relative_to(pathlib.Path(sys.prefix))
assert not pathlib.Path.cwd().joinpath('.venv').exists()
assert metadata.version('loom-affinity2ui')=='0.1.1'
for removed in ('psd2ui','psd-tools'):
 try: metadata.distribution(removed)
 except metadata.PackageNotFoundError: pass
 else: raise AssertionError('Retired PSD distribution installed: '+removed)
assert importlib.util.find_spec('psd2ui') is None
assert importlib.util.find_spec('psd_tools') is None
assert metadata.version('loom-image9grid')=='1.1.0'
package=files('affinity2ui')
for resource in ('native.js','resize_probe.mjs','runtime/AffinityListDecoration.ts','runtime/package.json','runtime/package-lock.json'):
 assert package.joinpath(resource).is_file(),resource
assert any(p.name.endswith('.toml') for p in package.joinpath('templates').iterdir())
import ninegrid
assert pathlib.Path(ninegrid.__file__).is_relative_to(pathlib.Path(sys.prefix))
owners=[]
for distribution in metadata.distributions():
 if any(str(f).replace('\\\\','/').startswith('ninegrid/') for f in distribution.files or []):
  owners.append(distribution.metadata['Name'].lower().replace('_','-'))
assert owners==['loom-image9grid'],owners
requirements=metadata.requires('loom-affinity2ui') or []
assert not any('psd2ui' in requirement.lower() or 'psd-tools' in requirement.lower() for requirement in requirements)
print(json.dumps({'package':affinity2ui.__file__,'grid':ninegrid.__file__,'gridVersion':metadata.version('loom-image9grid'),'gridOwners':owners,'psdDependenciesAbsent':True,'cwdUnchanged':True}))
'''
        checked([python,'-I','-c',code],workspace,'installed-import-resources')
        checked([cli,'--help'],workspace,'installed-cli-help')
        checked([python,'-I','-m','affinity2ui','--help'],workspace,'installed-module-help')
        initialized = temporary/'initialized-workspace'
        checked([cli,'init','--workspace',initialized],workspace,'installed-init-workspace')
        if not list(initialized.glob('*.toml')):raise RuntimeError('init did not create configuration')
        checked([cli,'doctor','--workspace',initialized],workspace,'installed-doctor')
        fixture = temporary/'test_installed_api.py'
        shutil.copy2(ROOT/'tests/test_public_api.py',fixture)
        checked([python,'-I',fixture,'-v'],workspace,'installed-api-transactions')
        cli_probe=temporary/'installed-cli-smoke.py'
        shutil.copy2(ROOT/'tests/installed_cli_smoke.py',cli_probe)
        checked([python,'-I',cli_probe,fixture,temporary/'cli-input'],workspace,'installed-cli-plan-config')
        engine_result = None
        if args.engine_smoke:
            cache = temporary/'node-runtime-cache'
            environment['AFFINITY2UI_CACHE_DIR']=str(cache)
            checked([cli,'setup-runtime','--cache-dir',cache],workspace,'installed-setup-runtime')
            probe = temporary/'installed-engine-smoke.py'
            probe.write_text('''import json,runpy,sys
from pathlib import Path
from affinity2ui.api import export_sources
fixture=runpy.run_path(sys.argv[1])
workspace,sources=fixture['PublicAPITests']().setup_workspace(Path(sys.argv[2]))
result=export_sources(sources[:1],workspace=workspace,source_factory=fixture['FixtureSource'],workers=1)
assert result['valid'] and result['publishedAfterChecks'] and result['engineCases']>0
Path(sys.argv[3]).write_text(json.dumps(result,ensure_ascii=False,indent=2))
''',encoding='utf-8')
            checked([python,'-I',probe,fixture,temporary/'engine-input',output/'engine-summary.json'],
                    workspace,'installed-engine-smoke')
            engine_result=json.loads((output/'engine-summary.json').read_text())
            shutil.copytree(Path(engine_result['reportDirectory']),output/'installed-engine-artifacts',dirs_exist_ok=True)
        source_distributions = sorted(wheelhouse.rglob('loom_affinity2ui-*.tar.gz'))
        if len(source_distributions)!=1:
            raise RuntimeError('Expected exactly one source distribution in '+str(wheelhouse))
        rebuilt = temporary/'rebuilt';rebuilt.mkdir()
        build = [python,'-m','pip','wheel','--no-deps','--wheel-dir',rebuilt,
                 '--find-links',dependency_wheels,source_distributions[0]]
        if args.offline:build.insert(4,'--no-index')
        checked(build,workspace,'build-wheel-from-sdist')
        rebuilt_wheels=list(rebuilt.glob('loom_affinity2ui-*.whl'))
        if len(rebuilt_wheels)!=1:raise RuntimeError('Source distribution did not produce one wheel')
        checked([python,'-m','pip','install','--no-deps','--force-reinstall',rebuilt_wheels[0]],
                workspace,'install-sdist-rebuilt-wheel')
        checked([python,'-I','-c',code],workspace,'sdist-import-resources')
        checked([cli,'--help'],workspace,'sdist-cli-help')
    summary={'valid':True,'wheel':wheel.name,'wheelSha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
             'isolatedVenv':True,'systemSitePackages':False,'pythonIsolatedMode':True,
             'outsideCheckout':True,'offlineInstallation':args.offline,'steps':steps,
             'engineCases':engine_result['engineCases'] if engine_result else 0,
             'gridWheelSha256':grid_sha,'gridVersion':'1.1.0','psdDependenciesAbsent':True,
             'limits':['AF source is faked; native Affinity rendering has not been verified by these distribution tests.']}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
