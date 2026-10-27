# Ported from the verified psd2ui snapshot; provenance: vendor/prefab-origin.json.
import re
from pathlib import Path

from .laya_types import new_ui_component


LEGACY_IMAGE_MARKER = re.compile(r"\.img", re.IGNORECASE)


def layer_tag(raw: str):
    """Match the first underscore-delimited segment, or the entire name."""
    token, separator, _ = raw.partition("_")
    if new_ui_component(token):
        return token + separator
    return None


def untagged_name(raw: str) -> str:
    """Logical node name, before filesystem-safe normalization."""
    raw = LEGACY_IMAGE_MARKER.sub("", raw)
    tag = layer_tag(raw)
    return raw[len(tag):] if tag and "_" in raw else raw


def export_name(raw: str) -> str:
    """One safe cross-platform path component; preserve legal Unicode and spaces."""
    name = untagged_name(raw).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name)
    name = name.replace("..", "_").rstrip(". ")
    if not name:
        raise ValueError("Name is empty after removing the tag and unsafe characters")
    if re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name):
        name = "_" + name
    return name


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes output directory: {relative}")
    return path

