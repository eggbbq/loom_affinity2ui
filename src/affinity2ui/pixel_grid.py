"""Quantize absolute layout edges before deriving parent-relative geometry."""
import math


def nearest_pixel(value):
    # Use symmetric half-away-from-zero rounding, including negative offsets.
    return math.floor(value + .5) if value >= 0 else math.ceil(value - .5)


def quantize_box(box):
    x, y, width, height = box
    if width < 0 or height < 0:
        raise ValueError('几何区域宽高不能为负数')
    left, top = nearest_pixel(x), nearest_pixel(y)
    right, bottom = nearest_pixel(x + width), nearest_pixel(y + height)
    # Preserve intentional zero-size groups, but do not collapse a nonempty
    # text/control area solely because both edges round to the same pixel.
    return [left, top, max(1 if width > 0 else 0, right - left),
            max(1 if height > 0 else 0, bottom - top)]
