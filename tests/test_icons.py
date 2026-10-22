"""Icon rendering is deterministic, transparent outside the badge, and packs every ICO size."""
from pathlib import Path

from PIL import Image

import icons

ROOT = Path(__file__).resolve().parents[1]


def test_tray_states_render_distinct_transparent_images():
    rendered = {state: icons.draw_icon(64, state) for state in ('idle', 'syncing', 'error')}
    for image in rendered.values():
        assert image.size == (64, 64) and image.mode == 'RGBA'
        assert image.getpixel((0, 0))[3] == 0          # rounded corner stays transparent
        assert image.getpixel((32, 10))[3] == 255      # body is opaque
    assert rendered['idle'].tobytes() != rendered['syncing'].tobytes() != rendered['error'].tobytes()
    assert rendered['error'].getpixel((52, 52))[:3] == icons.BADGES['error']


def test_application_icon_contains_every_size(tmp_path):
    path = tmp_path / 'SyncAgent.ico'
    icons.save_ico(path)
    with Image.open(path) as ico:
        assert {(n, n) for n in icons.ICO_SIZES} <= set(ico.info['sizes'])


def test_build_embeds_the_generated_icon_in_both_executables():
    text = (ROOT / 'build.bat').read_text()
    assert 'src\\icons.py build\\SyncAgent.ico' in text
    assert text.count('--icon "%ROOT%\\build\\SyncAgent.ico"') == 2
    assert text.index('icons.py') < text.index('-m PyInstaller')
