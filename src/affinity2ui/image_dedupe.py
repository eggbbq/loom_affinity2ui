# Ported from the verified psd2ui snapshot; provenance: vendor/prefab-origin.json.
"""Deterministic, same-size PNG deduplication in layout traversal order."""
import math
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path

from PIL import Image, ImageChops

from .naming import inside


def similarity_threshold(value):
    """Parse a normalized threshold; shared by the CLI and Python API."""
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Image similarity threshold must be a finite number between 0 and 1")
    return value


def image_nodes(node):
    if node.get("type") == "image":
        yield node
    for child in node.get("children", []):
        yield from image_nodes(child)


def deduplicate_images(root, output, threshold, *, rasters=None):
    """Update references and return redundant paths, without deleting files.

    Similarity is 1 - max(abs(a - b)) / 255 across every pixel and RGBA
    channel, including RGB under transparent pixels. Only retained originals
    are candidates: approximate matches must never form transitive chains.
    """
    threshold = similarity_threshold(threshold)
    output = Path(output)
    references = {}
    for node in image_nodes(root):
        references.setdefault(node["asset"], []).append(node)
    buckets = defaultdict(list)
    for asset in references:
        if rasters is not None:
            buckets[rasters.size(asset)].append(asset)
        else:
            with Image.open(inside(output, asset)) as image:
                buckets[image.size].append(asset)

    replacements = {}
    for assets in buckets.values():
        # Release decoded PNGs after each size bucket; never cache the whole PSD.
        with ExitStack() as images:
            retained = []
            for asset in assets:
                if rasters is not None:
                    image = rasters.load(asset)
                else:
                    with Image.open(inside(output, asset)) as source:
                        image = source.convert("RGBA")
                match = None
                keep = False
                try:
                    for original, candidate in retained:
                        with ImageChops.difference(image, candidate) as difference:
                            maximum = max(high for low, high in difference.getextrema())
                        if 1 - maximum / 255 >= threshold:
                            match = original
                            break
                    if match is None:
                        images.callback(image.close)
                        retained.append((asset, image))
                        keep = True
                    else:
                        replacements[asset] = match
                finally:
                    if not keep:
                        image.close()

    for asset, original in replacements.items():
        for node in references[asset]:
            node["asset"] = original
    return replacements
