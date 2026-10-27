# Ported from the verified psd2ui snapshot; provenance: vendor/prefab-origin.json.
"""Infer a native linear layout's spacing from PSD child rectangles."""


def ordered_children(children, direction):
    axis = 0 if direction == "horizontal" else 1
    return sorted(children, key=lambda child: child["position"][axis])


def layout_gap(children, direction):
    axis = 0 if direction == "horizontal" else 1
    items = ordered_children(children, direction)
    gaps = [right["position"][axis] - left["position"][axis] - left["size"][axis]
            for left, right in zip(items, items[1:])]
    return (round(sum(gaps) / len(gaps), 4) if gaps else 0,
            bool(gaps) and max(gaps) - min(gaps) > 0.01)
