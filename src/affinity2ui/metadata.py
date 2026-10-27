"""Preserve existing Laya resource identity and importer settings."""
import shutil


def preserve_metadata(output, target):
    # Prefer the project's existing UUIDs and importer settings.
    for meta in target.rglob("*.meta"):
        staged = output / meta.relative_to(target)
        if staged.with_suffix("").is_file():
            shutil.copy2(meta, staged)
