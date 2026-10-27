"""Project-wide name exclusions shared by exporting and manual inspection."""
from pathlib import Path
import tomllib

from ninegrid.names import DEFAULT_IGNORE_NAMES, normalize_ignored_names, matches_ignored_name


def configured_ignore_names(config=None):
    path=Path(config) if config is not None else Path.cwd()/'export_all_ui.toml'
    if not path.exists():return DEFAULT_IGNORE_NAMES
    with path.open('rb') as file:data=tomllib.load(file)
    options=data.get('export',{})
    if not isinstance(options,dict):raise ValueError('配置 [export] 必须是表')
    return normalize_ignored_names(options.get('ninegrid_ignore_names',DEFAULT_IGNORE_NAMES))
