"""Render brand/icon.svg into the PNGs and the Windows .ico (16-256 px) the exe and the website use.

Needs Microsoft Edge (renders the SVG headless) and Pillow:  python brand/build_icons.py
"""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
EDGE = next(p for p in (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")) if p.is_file())
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(svg: Path, px: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        page.write_text(f'<html><body style="margin:0;background:transparent"><img src="{svg.as_uri()}" '
                        f'width="{px}" height="{px}" style="display:block"></body></html>', encoding="utf-8")
        subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={tmp}",
                        "--default-background-color=00000000", f"--window-size={px},{px}", f"--screenshot={out}",
                        page.as_uri()], check=True, capture_output=True, timeout=60)


def main() -> None:
    big = HERE / "icon-1024.png"
    render(HERE / "icon.svg", 1024, big)
    master = Image.open(big).convert("RGBA")
    for n in (512, 256, 192, 32):
        master.resize((n, n), Image.LANCZOS).save(HERE / f"icon-{n}.png")
    master.save(HERE / "icon.ico", sizes=[(n, n) for n in SIZES])
    mark = HERE / "mark-512.png"
    render(HERE / "mark.svg", 512, mark)
    print("wrote", ", ".join(p.name for p in sorted(HERE.glob("*.png"))), "and icon.ico")


if __name__ == "__main__":
    main()
