"""Sync Agent icon: a gradient rounded square with a white two-arrow sync symbol.

draw_icon(size, state) renders the tray image; state 'syncing' or 'error' adds a
status dot. `python icons.py OUT.ico` writes the multi-size application icon.
Drawing happens at 4x and is downsampled so small tray sizes stay crisp.
"""
import math
import sys

from PIL import Image, ImageChops, ImageDraw

TOP_LEFT = (37, 99, 235)       # blue
BOTTOM_RIGHT = (6, 182, 212)   # cyan
BADGES = {'syncing': (245, 158, 11), 'error': (239, 68, 68)}
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SCALE = 4


def _background(s):
    vertical = Image.linear_gradient('L').resize((s, s))
    ramp = ImageChops.add(vertical, vertical.rotate(90), scale=2)  # smooth top-left → bottom-right
    gradient = Image.composite(Image.new('RGBA', (s, s), BOTTOM_RIGHT + (255,)),
                               Image.new('RGBA', (s, s), TOP_LEFT + (255,)), ramp)
    mask = Image.new('L', (s, s), 0)
    margin = round(s * 0.04)
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, s - 1 - margin, s - 1 - margin),
                                           radius=round(s * 0.23), fill=255)
    gradient.putalpha(mask)
    return gradient


def _arrow(draw, centre, radius, start, end, width):
    """Clockwise arc from start to end degrees (screen coordinates) with an arrowhead."""
    cx, cy = centre
    head = width * 1.55
    # Stop the stroke short of the end so the arrowhead tip lands on `end`.
    stroke_end = end - math.degrees(head * 0.55 / radius)
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.arc(box, start, stroke_end, fill='white', width=round(width))
    # Round cap at the tail.
    a = math.radians(start)
    tail = (cx + (radius - width / 2) * math.cos(a), cy + (radius - width / 2) * math.sin(a))
    draw.ellipse((tail[0] - width / 2, tail[1] - width / 2, tail[0] + width / 2, tail[1] + width / 2), fill='white')
    a = math.radians(stroke_end)
    mid = radius - width / 2
    base = (cx + mid * math.cos(a), cy + mid * math.sin(a))
    tangent = (-math.sin(a), math.cos(a))
    normal = (math.cos(a), math.sin(a))
    tip = (base[0] + tangent[0] * head * 1.1, base[1] + tangent[1] * head * 1.1)
    draw.polygon([tip, (base[0] + normal[0] * head, base[1] + normal[1] * head),
                  (base[0] - normal[0] * head, base[1] - normal[1] * head)], fill='white')


def draw_icon(size=64, state='idle'):
    s = size * SCALE
    image = _background(s)
    draw = ImageDraw.Draw(image)
    # Small icons need relatively heavier strokes to stay legible.
    width = s * (0.12 if size <= 24 else 0.095)
    radius = s * 0.30
    centre = (s / 2, s / 2)
    _arrow(draw, centre, radius, 215, 345, width)
    _arrow(draw, centre, radius, 35, 165, width)
    colour = BADGES.get(state)
    if colour:
        r = s * 0.17
        cx = cy = s - r - s * 0.03
        # Transparent ring separates the dot from the icon at any taskbar colour.
        cut = Image.new('L', (s, s), 255)
        gap = s * 0.05
        ImageDraw.Draw(cut).ellipse((cx - r - gap, cy - r - gap, cx + r + gap, cy + r + gap), fill=0)
        image.putalpha(ImageChops.multiply(image.getchannel('A'), cut))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour + (255,))
    return image.resize((size, size), Image.LANCZOS)


def save_ico(path):
    images = [draw_icon(size) for size in ICO_SIZES]
    images[-1].save(path, format='ICO', sizes=[(n, n) for n in ICO_SIZES], append_images=images[:-1])


if __name__ == '__main__':
    save_ico(sys.argv[1] if len(sys.argv) > 1 else 'SyncAgent.ico')
