#!/usr/bin/env python3
"""Build reviewable wheel/sdist and an optional platform wheel installation bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dependencies', action='store_true', help='下载当前 Python/平台的依赖 wheels，用于离线安装')
    args = parser.parse_args()
    os.chdir(ROOT)
    dependencies = []
    for metadata in ('image9grid.json',):
        provenance = json.loads((ROOT/'vendor'/metadata).read_text())
        artifact = ROOT/'vendor/wheels'/provenance['file']
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != provenance['sha256']:
            raise SystemExit(f'{metadata} wheel 校验失败')
        dependencies.append(artifact)
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    for path in ('dist', 'build'):
        shutil.rmtree(ROOT/path, ignore_errors=True)
    subprocess.run([sys.executable,'-m','build','--no-isolation'], check=True)
    # This is generated staging only. Start fresh so retired dependencies cannot
    # remain in the offline bundle after a dependency is removed.
    release = ROOT/'release'
    shutil.rmtree(release, ignore_errors=True)
    wheels = release/'wheels';wheels.mkdir(parents=True, exist_ok=True)
    for dependency in dependencies:
        shutil.copy2(dependency, wheels/dependency.name)
    for artifact in (ROOT/'dist').iterdir():
        shutil.copy2(artifact, (wheels if artifact.suffix == '.whl' else release)/artifact.name)
    if args.bundle_dependencies:
        main_wheel = next((ROOT/'dist').glob(f'loom_affinity2ui-{version}-*.whl'))
        subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:',
                        '--find-links',str(wheels),'--dest',str(wheels),str(main_wheel)], check=True)
        # pip builds sdist in an isolated environment; ship its build backend
        # too so --no-index can genuinely rebuild the supplied source archive.
        subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:',
                        '--dest',str(wheels),'setuptools>=77','wheel'], check=True)
    manifest = {p.relative_to(release).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(release.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
    (release/'SHA256.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'发行产物：{release}；未上传任何注册表。')


if __name__ == '__main__':main()
