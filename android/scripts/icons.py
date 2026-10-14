"""The Android app's icons and splash from brand/: launcher icons (square, round, adaptive foreground), the notification
icon (a white silhouette, eyes cut out) and the splash images. Drawn by a headless browser from the SVGs so every size
is sharp. Run from the repo root, with Playwright installed: python android/scripts/icons.py"""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "android" / "app" / "src" / "main" / "res"
BRICK, NIGHT = "#A8443D", "#111013"
mark = (ROOT / "brand" / "mark.svg").read_text(encoding="utf-8")
square = (ROOT / "brand" / "icon.svg").read_text(encoding="utf-8")
hood = re.search(r'<path fill="#18171B" d="([^"]+)"', mark).group(1)
silhouette = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><mask id="m"><rect width="100" height="100" fill="#fff"/>
<ellipse cx="38.5" cy="62" rx="6.2" ry="7.8" fill="#000"/><ellipse cx="61.5" cy="62" rx="6.2" ry="7.8" fill="#000"/></mask></defs>
<path fill="#fff" mask="url(#m)" d="{hood}"/></svg>"""
DENSITY = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def draw(page, out: Path, w: int, h: int, svg: str, size: float, bg: str = "transparent", round_bg: str = "") -> None:
    inner = f'<div style="width:{size}px;height:{size}px;line-height:0">{svg.replace("<svg ", "<svg width=\'100%\' height=\'100%\' ", 1)}</div>'
    if round_bg:
        inner = f'<div style="width:{w}px;height:{h}px;border-radius:50%;background:{round_bg};display:grid;place-items:center">{inner}</div>'
    page.set_viewport_size({"width": w, "height": h})
    page.set_content(f'<body style="margin:0;width:{w}px;height:{h}px;background:{bg};display:grid;place-items:center;overflow:hidden">{inner}</body>')
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), omit_background=bg == "transparent")


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    page = b.new_page(device_scale_factor=1)
    for name, k in DENSITY.items():
        n = round(48 * k)
        draw(page, RES / f"mipmap-{name}" / "ic_launcher.png", n, n, square, n)
        draw(page, RES / f"mipmap-{name}" / "ic_launcher_round.png", n, n, mark, n * 0.6, round_bg=BRICK)
        f = round(108 * k)
        draw(page, RES / f"mipmap-{name}" / "ic_launcher_foreground.png", f, f, mark, f * 0.56)
        s = round(24 * k)
        draw(page, RES / f"drawable-{name}" / "ic_stat_icon.png", s, s, silhouette, s * 0.92)
    for splash in RES.glob("drawable*/splash.png"):
        from PIL import Image
        w, h = Image.open(splash).size
        draw(page, splash, w, h, mark, min(w, h) * 0.3, bg=NIGHT)
    b.close()
(RES / "values" / "ic_launcher_background.xml").write_text(
    f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">{BRICK}</color>\n</resources>\n', encoding="utf-8")
print("icons and splash drawn into", RES)
