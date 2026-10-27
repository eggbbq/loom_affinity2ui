"""Check bundled immutable resources and independently writable runtime caches."""
from importlib.resources import files
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from affinity2ui.runtime_env import runtime_dir, setup_runtime, playwright_module


class PackageResourcesTests(unittest.TestCase):
    def test_native_script_and_runtime_templates_are_package_resources(self):
        package = files('affinity2ui')
        self.assertIn('finally', package.joinpath('native.js').read_text(encoding='utf-8'))
        self.assertIn('selection', package.joinpath('native.js').read_text(encoding='utf-8'))
        self.assertTrue(package.joinpath('resize_probe.mjs').is_file())
        self.assertTrue(package.joinpath('runtime', 'AffinityListDecoration.ts').is_file())
        manifest = json.loads(package.joinpath('runtime', 'package.json').read_text())
        self.assertIn('playwright', manifest['dependencies'])
        json.loads(package.joinpath('runtime', 'package-lock.json').read_text())
        templates = [p for p in package.joinpath('templates').iterdir() if p.name.endswith('.toml')]
        self.assertTrue(templates)
        for template in templates:
            self.assertIsInstance(tomllib.loads(template.read_text()), dict)

    def test_runtime_install_writes_only_explicit_cache_not_package_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)/'cache'
            package = files('affinity2ui')
            before = {name:package.joinpath('runtime',name).read_bytes()
                      for name in ('package.json','package-lock.json')}
            def fake_npm(command, **options):
                self.assertIn('ci', command)
                target = Path(command[command.index('--prefix')+1])
                self.assertEqual(target, runtime_dir(cache))
                module = target/'node_modules/playwright/index.js'
                module.parent.mkdir(parents=True)
                module.write_text('module.exports = {};')
            with patch('affinity2ui.runtime_env.shutil.which', return_value='/fixture/npm'), \
                    patch('affinity2ui.runtime_env.subprocess.run', side_effect=fake_npm):
                result = setup_runtime(cache)
            self.assertEqual(Path(result['directory']), runtime_dir(cache))
            self.assertEqual(playwright_module(cache), runtime_dir(cache)/'node_modules/playwright/index.js')
            self.assertEqual({name:package.joinpath('runtime',name).read_bytes() for name in before}, before)

    def test_explicit_runtime_module_and_missing_dependency_error(self):
        with tempfile.TemporaryDirectory() as folder:
            module = Path(folder)/'playwright.mjs';module.write_text('export {};')
            with patch.dict(os.environ, {'AFFINITY2UI_PLAYWRIGHT_MODULE':str(module)}):
                self.assertEqual(playwright_module(), module.resolve())
            with patch.dict(os.environ, {'AFFINITY2UI_PLAYWRIGHT_MODULE':'',
                                         'NINEGRID_PLAYWRIGHT_MODULE':''}):
                with self.assertRaisesRegex(ValueError, 'setup-runtime'):
                    playwright_module(Path(folder)/'missing')


if __name__ == '__main__':unittest.main()
