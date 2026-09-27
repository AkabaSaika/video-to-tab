"""Synthetic guitar-video generator used by the tests.

Layout (640x480, 25 fps): random noise "performance" on top, white tab panel at
ROI_TRUTH with 6 staff lines and random fret numbers, a red cursor sweeping each page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.models import Roi

W, H, FPS = 640, 480, 25
ROI_TRUTH = Roi(20, 300, 600, 180)
LINE_YS = [350 + 16 * i for i in range(6)]  # absolute y of staff lines
LINE_X0, LINE_X1 = 30, 610

# (kind, page, start, end); kind: blank | page | fade | flash
TIMELINE = [
    ("blank", None, 0.0, 1.0),
    ("page", "A", 1.0, 3.0),
    ("fade", ("A", "B"), 3.0, 3.4),
    ("page", "B", 3.4, 5.4),
    ("flash", None, 5.4, 5.6),
    ("page", "B", 5.6, 7.6),
    ("page", "C", 7.6, 9.6),
    ("page", "A", 9.6, 11.6),
]
EXPECTED_PAGES = [  # (page, start, end, duplicate_of) after merge + repeat marking
    ("A", 1.0, 3.0, None),
    ("B", 3.4, 7.6, None),
    ("C", 7.6, 9.6, None),
    ("A", 9.6, 11.6, 0),
]


def render_panel(seed: int | None, dark: bool = False) -> np.ndarray:
    """Return a clean ROI-sized BGR panel. seed=None gives an empty panel (no staff)."""
    bg, ink = (30, 255) if dark else (255, 0)
    panel = np.full((ROI_TRUTH.h, ROI_TRUTH.w, 3), bg, np.uint8)
    if seed is None:
        return panel
    ox, oy = ROI_TRUTH.x, ROI_TRUTH.y
    for y in LINE_YS:
        cv2.line(panel, (LINE_X0 - ox, y - oy), (LINE_X1 - ox, y - oy), (ink,) * 3, 1)
    rng = np.random.default_rng(seed)
    for k in range(16):
        x = 50 + k * 34 + int(rng.integers(-4, 5)) - ox
        y = LINE_YS[int(rng.integers(0, 6))] - oy
        text = str(int(rng.integers(0, 20)))
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(panel, (x - 1, y - th // 2 - 2), (x + tw + 1, y + th // 2 + 2), (bg,) * 3, -1)
        cv2.putText(panel, text, (x, y + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (ink,) * 3, 1)
    return panel


PANELS = {"A": 1, "B": 2, "C": 3}


@dataclass
class SynthVideo:
    path: Path
    roi: Roi
    panels: dict[str, np.ndarray]


def make_video(path: Path, dark: bool = False) -> SynthVideo:
    panels = {name: render_panel(seed, dark) for name, seed in PANELS.items()}
    blank = render_panel(None, dark)
    rng = np.random.default_rng(0)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    total = int(round(TIMELINE[-1][3] * FPS))
    for f in range(total):
        t = f / FPS
        frame = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
        frame[ROI_TRUTH.y :, :] = 90
        kind, page, start, end = next(e for e in TIMELINE if e[2] <= t + 1e-9 < e[3])
        if kind == "blank":
            panel = blank
        elif kind == "flash":
            panel = np.zeros_like(blank)
        elif kind == "fade":
            a = (t - start) / (end - start)
            panel = cv2.addWeighted(panels[page[0]], 1 - a, panels[page[1]], a, 0)
        else:
            panel = panels[page].copy()
            cx = int((t - start) / (end - start) * (ROI_TRUTH.w - 1))
            cv2.line(panel, (cx, 0), (cx, ROI_TRUTH.h - 1), (0, 0, 255), 3)
        r = ROI_TRUTH
        frame[r.y : r.y + r.h, r.x : r.x + r.w] = panel
        writer.write(frame)
    writer.release()
    return SynthVideo(path, ROI_TRUTH, panels)
