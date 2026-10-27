"""Install the small project-owned list decoration adapter when needed."""
import hashlib
import json
from pathlib import Path
from .list_layout import DECORATION_UUID


def install_list_adapter(project):
    source = Path(__file__).parent / 'runtime/AffinityListDecoration.ts'
    target = project / 'src/ui/affinity-list-decoration.ts'
    target.parent.mkdir(parents=True, exist_ok=True)
    # Upgrade only a byte-identical adapter previously installed by this tool.
    managed_versions = {'5167b0767df9725e5392d70208a891ddbbeacda10c8cbed349f84bee3f4eef8c', '5760c6fd18e8ca59ccb199777dadc0f831d744157dbc09c29283441305bd1ef4'}
    if target.exists() and target.read_bytes() != source.read_bytes():
        if hashlib.sha256(target.read_bytes()).hexdigest() not in managed_versions:
            raise ValueError(f'列表适配脚本已有不同内容，保留现有文件：{target}')
    meta = Path(str(target)+'.meta')
    if meta.exists() and json.loads(meta.read_text(encoding='utf-8')).get('uuid') != DECORATION_UUID:
        raise ValueError(f'列表适配脚本 UUID 与现有文件冲突：{meta}')
    if not target.exists() or target.read_bytes() != source.read_bytes():
        target.write_bytes(source.read_bytes())
    if not meta.exists():
        meta.write_text(json.dumps({'uuid':DECORATION_UUID},indent=2)+'\n',encoding='utf-8')
