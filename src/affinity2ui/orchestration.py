"""Invoke the independent installed shared-image command after page import."""
from pathlib import Path
import subprocess
import sys
import json
import tempfile


class SharedImageStep:
    def __init__(self, root, project, assets, records, threshold):
        self.root, self.project, self.assets, self.records = map(Path, (root, project, assets, records))
        self.threshold = threshold
        self.state = self.records/'shared-image-dedupe'
        self.existing = [p.name for p in sorted((self.assets/'images').glob('*.png'),
                                               key=lambda p:(p.stat().st_mtime_ns, p.name))]

    def invoke(self, extra):
        subprocess.run([sys.executable, '-m', 'affinity2ui', 'dedupe', '--workspace', str(self.root),
            '--project', str(self.project), '--laya-assets-dir', str(self.assets),
            '--state-dir', str(self.state), '--threshold', str(self.threshold), *extra],
            cwd=self.root, check=True)

    def prepare(self, rebuilding_all=False):
        if rebuilding_all and not any((self.assets/'images').glob('*.png')):
            return
        if (self.state/'index.json').exists():
            self.invoke(['--restore-only'])

    def finish(self, prefabs):
        self.records.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dedupe-input-', dir=self.records) as temporary:
            inventory = Path(temporary)/'existing.json'
            inventory.write_text(json.dumps(self.existing, ensure_ascii=False), encoding='utf-8')
            self.invoke(['--existing-images', str(inventory), '--fresh-prefabs', *[Path(p).name for p in prefabs]])
