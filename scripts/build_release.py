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

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dependencies', action='store_true', help='下载当前 Python/平台的依赖 wheels，用于离线安装')
    args = parser.parse_args()
    os.chdir(ROOT)
    provenance = json.loads((ROOT/'vendor/backend.json').read_text())
    backend = ROOT/'vendor/wheels'/provenance['file']
    if hashlib.sha256(backend.read_bytes()).hexdigest() != provenance['sha256']:
        raise SystemExit('后端 wheel 校验失败')
    subprocess.run([sys.executable,'-m','build','--no-isolation'], check=True)
    release = ROOT/'release';wheels = release/'wheels';wheels.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backend, wheels/backend.name)
    for artifact in (ROOT/'dist').iterdir():
        shutil.copy2(artifact, (wheels if artifact.suffix == '.whl' else release)/artifact.name)
    if args.bundle_dependencies:
        main_wheel = next((ROOT/'dist').glob('loom_affinity2ui-0.1.0-*.whl'))
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
