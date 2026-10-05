"""Image helpers: download scraped media, and render SVG cards for demo data / image concepts."""
import hashlib
import html
import re
import textwrap
from pathlib import Path

import requests

from . import config

PALETTES = [("#7c3aed", "#db2777"), ("#0ea5e9", "#2563eb"), ("#f59e0b", "#ef4444"), ("#10b981", "#0d9488"),
            ("#ec4899", "#f97316"), ("#6366f1", "#14b8a6"), ("#84cc16", "#16a34a"), ("#e11d48", "#7c2d12")]


def download(url: str, folder: str, stem: str) -> str:
    """Download one image. Google image URLs get a larger size requested. Returns the local path or ''."""
    if not url or url.startswith("data:"):
        return ""
    big = re.sub(r"=w\d+-h\d+[^/]*$", "=w1200", url)
    target_dir = config.MEDIA_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(big, timeout=25, headers={"User-Agent": "Mozilla/5.0 (competitor-research tool)"})
        r.raise_for_status()
    except Exception:
        return ""
    ctype = r.headers.get("content-type", "")
    ext = ".png" if "png" in ctype else ".webp" if "webp" in ctype else ".gif" if "gif" in ctype else ".jpg"
    path = target_dir / f"{stem}{ext}"
    path.write_bytes(r.content)
    return str(path)


def svg_card(folder: str, stem: str, title: str, subtitle: str = "", footer: str = "", badge: str = "") -> str:
    """Render a 1200x900 (4:3, the Google Maps update ratio) SVG image and return its path."""
    seed = int(hashlib.md5((title + subtitle).encode()).hexdigest(), 16)
    c1, c2 = PALETTES[seed % len(PALETTES)]
    lines = textwrap.wrap(title, 22)[:4]
    sub = textwrap.wrap(subtitle, 46)[:3]
    tspans = "".join(f'<tspan x="80" dy="{0 if i == 0 else 92}">{html.escape(l)}</tspan>' for i, l in enumerate(lines))
    subspans = "".join(f'<tspan x="80" dy="{0 if i == 0 else 46}">{html.escape(l)}</tspan>' for i, l in enumerate(sub))
    circles = "".join(
        f'<circle cx="{(seed >> (i * 4)) % 1200}" cy="{(seed >> (i * 5)) % 900}" r="{60 + (seed >> i) % 160}" '
        f'fill="#fff" opacity="0.07"/>' for i in range(6))
    badge_svg = (f'<rect x="80" y="70" rx="24" width="{40 + 17 * len(badge)}" height="48" fill="#fff" opacity="0.92"/>'
                 f'<text x="100" y="103" font-size="26" font-weight="700" fill="{c1}">{html.escape(badge)}</text>') if badge else ""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>
<rect width="1200" height="900" fill="url(#g)"/>{circles}{badge_svg}
<text x="80" y="{330 - 46 * (len(lines) - 1)}" font-family="Georgia, serif" font-size="84" font-weight="700" fill="#fff">{tspans}</text>
<text x="80" y="{430 + 46 * len(lines)}" font-family="Helvetica, Arial, sans-serif" font-size="36" fill="#fff" opacity="0.92">{subspans}</text>
<text x="80" y="840" font-family="Helvetica, Arial, sans-serif" font-size="28" fill="#fff" opacity="0.8">{html.escape(footer)}</text>
</svg>"""
    target_dir = config.MEDIA_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{stem}.svg"
    path.write_text(svg, encoding="utf-8")
    return str(path)


def save_bytes(folder: str, stem: str, data: bytes, ext=".png") -> str:
    target_dir = config.MEDIA_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = Path(target_dir) / f"{stem}{ext}"
    path.write_bytes(data)
    return str(path)
