"""Bundle the brand fonts (all SIL Open Font License) into the app: Bricolage Grotesque, Figtree, JetBrains Mono.
Latin subset, variable weight, woff2.  python brand/fetch_fonts.py"""

import re
import urllib.request
from pathlib import Path

OUT = Path(__file__).parents[1] / "app" / "superagents" / "ui" / "fonts"
FAMILIES = {"bricolage": "Bricolage+Grotesque:opsz,wght@12..96,400..800", "figtree": "Figtree:wght@300..900",
            "jetbrains-mono": "JetBrains+Mono:wght@400..700"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in FAMILIES.items():
        css = urllib.request.urlopen(urllib.request.Request(f"https://fonts.googleapis.com/css2?family={spec}&display=swap",
                                                            headers=UA), timeout=30).read().decode()
        # the last @font-face block is the basic latin subset
        latin = css.split("/* latin */")[-1]
        url = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", latin).group(1)
        data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        (OUT / f"{name}.woff2").write_bytes(data)
        print(f"{name}.woff2  {len(data) // 1024} KB")
    (OUT / "LICENSE.txt").write_text(
        "Bricolage Grotesque, Figtree and JetBrains Mono are licensed under the SIL Open Font License, Version 1.1.\n"
        "https://openfontlicense.org  Sources: https://github.com/google/fonts (ofl/bricolagegrotesque, ofl/figtree),\n"
        "https://github.com/JetBrains/JetBrainsMono\n", encoding="utf-8")


if __name__ == "__main__":
    main()
