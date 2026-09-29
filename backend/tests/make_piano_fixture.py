"""Regenerate the piano test fixture in tests/data/piano.

Run with an environment that has verovio, cairosvg and music21 (dev-only tools, not
project dependencies), for example:

    python tests/make_piano_fixture.py path/to/gt   # folder with k545.musicxml, maple.musicxml

It writes, for each piece, its first measures as ground truth (<piece>.musicxml), a tall
image of all grand-staff systems stacked top to bottom (score.png, 1280 px wide, staff
space about 11.5 px) and score.json with each system's ink box and measure count.
"""

from __future__ import annotations

import io
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg
import numpy as np
import verovio
from music21 import converter
from PIL import Image

OUT = Path(__file__).resolve().parent / "data" / "piano"
WIDTH = 1280
SCALE = 64  # verovio's staff space is 18 units: 18 * 0.64 ≈ 11.5 px
PIECES = {"k545": (1, 16), "maple": (0, 20)}  # piece → measure numbers kept (0 = pickup)
GAP = 60  # white rows between pieces


def trim(src: Path, span: tuple[int, int], dst: Path) -> None:
    score = converter.parse(str(src)).measures(*span)
    score.write("musicxml", fp=str(dst))


def render(xml: Path) -> tuple[np.ndarray, list[int]]:
    """The piece as one tall image, plus the measure count of each system in order."""
    tk = verovio.toolkit()
    tk.setOptions(
        {
            "pageWidth": WIDTH * 100 // SCALE,
            "pageHeight": 60000,
            "scale": SCALE,
            "adjustPageHeight": True,
            "breaks": "auto",
            "header": "none",
            "footer": "none",
            "pageMarginTop": 100,
            "pageMarginBottom": 40,
            "pageMarginLeft": 60,
            "pageMarginRight": 60,
        }
    )
    tk.loadFile(str(xml))
    assert tk.getPageCount() == 1
    svg = tk.renderToSVG(1)
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=WIDTH, background_color="white")
    img = np.array(Image.open(io.BytesIO(png)).convert("RGB"))[:, :, ::-1]  # BGR like cv2
    root = ET.fromstring(svg)
    counts = [
        sum(1 for m in g.iter() if "measure" in (m.get("class") or "").split())
        for g in root.iter()
        if "system" in (g.get("class") or "").split()
    ]
    return img, counts


def ink_boxes(img: np.ndarray, count: int) -> list[tuple[int, int]]:
    """Top/bottom ink rows of each of `count` systems: the widest blank gaps split them."""
    rows = np.flatnonzero((img.min(axis=2) < 160).any(axis=1))
    gaps = np.diff(rows)
    cuts = sorted(np.argsort(gaps)[::-1][: count - 1])
    starts = [rows[0], *(rows[c + 1] for c in cuts)]
    ends = [*(rows[c] for c in cuts), rows[-1]]
    return [(int(a), int(b)) for a, b in zip(starts, ends, strict=True)]


def main(gt: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    images, systems, offset = [], [], 0
    for piece, span in PIECES.items():
        dst = OUT / f"{piece}.musicxml"
        trim(gt / f"{piece}.musicxml", span, dst)
        img, counts = render(dst)
        kept = len(ET.parse(dst).getroot().find("part").findall("measure"))
        assert sum(counts) == kept, (piece, counts, kept)
        for (y0, y1), n in zip(ink_boxes(img, len(counts)), counts, strict=True):
            systems.append({"y0": y0 + offset, "y1": y1 + offset, "measures": n})
        images.append(img)
        offset += img.shape[0] + GAP
        images.append(np.full((GAP, WIDTH, 3), 255, np.uint8))
    score = np.vstack(images[:-1])
    Image.fromarray(score[:, :, ::-1]).save(OUT / "score.png", optimize=True)
    meta = {"pieces": list(PIECES), "systems": systems}
    (OUT / "score.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"{len(systems)} systems, {sum(s['measures'] for s in systems)} measures,", score.shape)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
