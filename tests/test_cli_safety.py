"""Protect primary export records when routing the standalone repair command."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from affinity2ui.cli import main
from installed_cli_smoke import validate


class CLISafetyTests(unittest.TestCase):
    def test_plan_has_no_writes_and_configured_report_directory_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(__file__).with_name('test_public_api.py')
            self.assertTrue(validate(fixture,Path(folder))['valid'])

    def invoke(self, arguments):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                return main(arguments)
            except SystemExit as error:
                return error.code

    def test_reoptimize_requires_distinct_explicit_repair_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for directory in (None, 'out/affinity-export', 'out', 'out/affinity-export/repair'):
                with self.subTest(directory=directory), patch('affinity2ui.reoptimize.reoptimize') as optimize:
                    args=['reoptimize','image.png','--workspace',str(root)]
                    if directory:args.extend(['--records-dir',directory])
                    self.assertNotEqual(self.invoke(args),0)
                    optimize.assert_not_called()

    def test_reoptimize_forwards_separate_repair_output_without_changing_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cwd=Path.cwd()
            with patch('affinity2ui.reoptimize.reoptimize',return_value={'valid':True}) as optimize:
                status=self.invoke(['reoptimize','client/assets/ui/images/bg.png',
                    '--workspace',str(root),'--records-dir','out/repair-images',
                    '--original-records','out/old-grid','--engine-dir','engine-libs'])
            self.assertEqual(status,0)
            optimize.assert_called_once()
            self.assertEqual(Path(optimize.call_args.args[2]).resolve(),(root/'out/repair-images').resolve())
            self.assertEqual(optimize.call_args.kwargs['engine_dir'],(root/'engine-libs').resolve())
            self.assertEqual(Path.cwd(),cwd)


if __name__ == '__main__':unittest.main()
