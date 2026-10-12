"""Génère assets/destripdf.ico (PNG 16 à 256 px) à partir de l'emblème SVG."""

from __future__ import annotations

import struct
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# Emblème sur fond graphite arrondi, lisible aux petites tailles.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="2" y="2" width="60" height="60" rx="11" fill="#303a42"/>
<path d="M18 10h20l10 10v34H18z" fill="#f7f4ef"/>
<path d="M38 10v10h10" fill="#d9a782"/>
<path d="M24 45c4.6-2.9 7.2-7.4 10.4-13.2l5.2 3c-3.2 5.9-6.8 10-12.4 12.7z" fill="#a95d37"/>
<path d="M24 50h20" stroke="#a95d37" stroke-width="2.6" stroke-linecap="round"/>
</svg>"""


def render_png(size: int) -> bytes:
    doc = fitz.open("svg", SVG.encode())
    page = doc[0]
    scale = size / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
    return pix.tobytes("png")


def build_ico(target: Path) -> None:
    images = [(size, render_png(size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + entries + payload)


if __name__ == "__main__":
    out = ROOT / "assets" / "destripdf.ico"
    build_ico(out)
    (ROOT / "assets" / "destripdf-256.png").write_bytes(render_png(256))
    print(out, out.stat().st_size, "octets")
