"""Invoked under Python -I after wheel installation; no real Affinity is opened."""
from contextlib import redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

from affinity2ui.cli import main
from affinity2ui.exporter import directory_identity


def validate(fixture_path, output_root):
    fixtures=runpy.run_path(str(fixture_path))
    root,sources=fixtures['PublicAPITests']().setup_workspace(Path(output_root))
    config=root/'export_all_ui.toml'
    config.write_text('[paths]\nreports="out/custom-reports"\n[checks]\nrepair_records=["out/repair-backup"]\n')
    before=directory_identity(root);cwd=Path.cwd()
    base=['export',str(sources[0]),'--workspace',str(root)]
    with patch('affinity2ui.bridge.NativeAffinity',fixtures['FixtureSource']), \
            redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
        plan=main([*base,'--plan'])
    assert plan==0,'Installed CLI plan failed'
    assert directory_identity(root)==before,'Plan wrote resources or report directories'
    assert Path.cwd()==cwd,'Plan did not restore cwd'
    with patch('affinity2ui.bridge.NativeAffinity',fixtures['FixtureSource']), \
            redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
        exported=main([*base,'--export-only'])
    assert exported==0,'Installed CLI export-only failed'
    assert list((root/'out/custom-reports').glob('run-*/summary.json')),'Configured reports directory ignored'
    assert not (root/'out/ui-export-reports').exists(),'Unexpected default report directory created'
    assert Path.cwd()==cwd,'Export did not restore cwd'
    return {'valid':True,'planReadOnly':True,'repairRecordsIsolatedFromPlan':True,'configuredReportsUsed':True}


if __name__=='__main__':print(json.dumps(validate(sys.argv[1],sys.argv[2])))
