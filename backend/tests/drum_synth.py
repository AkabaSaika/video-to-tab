"""Synthetic drum videos made from the fixture (tests/data/drums).

- gp_strip_video: Guitar Pro style. A dark camera area on top, the score as one long
  line in a panel below, shown a screen at a time. The measure being played is
  highlighted in yellow with a cursor moving through it; when it does not fit on the
  screen any more the view jumps (with one in-between frame, like GP's scroll) so that
  it is first. Only the first screen shows the clef and time signature.
- page_video: whole pages of staves under a dark camera area, hard cuts between pages.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from tests.drum_data import DATA, meta, strip_meta

FPS = 10
PANEL = (242, 242, 242)
YELLOW = (200, 245, 250)  # BGR, a light yellow like Guitar Pro's
CURSOR = (230, 150, 50)


def _writer(path: Path, size: tuple[int, int], quality: int = 70) -> cv2.VideoWriter:
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), FPS, size)
    out.set(cv2.VIDEOWRITER_PROP_QUALITY, quality)
    assert out.isOpened()
    return out


def _camera(rng: np.random.Generator, h: int, w: int, t: float) -> np.ndarray:
    """Dark, noisy, moving: a stand-in for the drummer's camera."""
    frame = rng.integers(0, 70, (h, w, 3), dtype=np.uint8)
    cx = int((0.5 + 0.3 * np.sin(t * 2.0)) * w)
    cv2.circle(frame, (cx, h // 2), h // 4, (40, 60, 90), -1)
    return frame


def strip() -> np.ndarray:
    img = cv2.imread(str(DATA / "strip.png"))
    assert img is not None
    return img


def strip_measures() -> list[tuple[int, int]]:
    """[x0, x1) of every measure of the strip (the first starts at the staff start)."""
    img = cv2.cvtColor(strip(), cv2.COLOR_BGR2GRAY)
    lines = strip_meta()["lines"]
    first = int(np.flatnonzero(img[lines[0]] < 128)[0])
    bars = strip_meta()["bars"]
    return list(zip([first, *bars[:-1]], bars, strict=True))


GP_SIZE = (1280, 720)
GP_PANEL_Y = 480


def gp_strip_video(path: Path, measure_seconds: float = 1.0) -> Path:
    W, H = GP_SIZE
    src = strip()
    sh, sw = src.shape[:2]
    canvas = np.full((sh, sw + W, 3), 255, np.uint8)  # room to scroll past the end
    canvas[:, :sw] = src
    measures = strip_measures()
    rng = np.random.default_rng(3)
    out = _writer(path, GP_SIZE)
    top = GP_PANEL_Y + (H - GP_PANEL_Y - sh) // 2

    def frame(offset: int, current: tuple[int, int] | None, cursor: float | None, t: float):
        f = np.empty((H, W, 3), np.uint8)
        f[:GP_PANEL_Y] = _camera(rng, GP_PANEL_Y, W, t)
        f[GP_PANEL_Y:] = PANEL
        view = canvas[:, offset : offset + W].copy()
        if current is not None:
            a, b = max(0, current[0] - offset), max(0, current[1] - offset)
            part = view[:, a:b]
            part[(part >= 200).all(axis=2)] = YELLOW
        if cursor is not None:
            x = int(cursor - offset)
            cv2.line(view, (x, 10), (x, sh - 10), CURSOR, 2)
        f[top : top + sh] = view
        return f

    t = 0.0
    offset = 0
    for _ in range(FPS):  # count-in: the first screen, nothing highlighted yet
        out.write(frame(offset, None, None, t))
        t += 1 / FPS
    per = int(round(measure_seconds * FPS))
    for a, b in measures:
        if b - offset > W - 10:  # the measure does not fit: jump so it comes first
            new = a - 40
            out.write(frame((offset + new) // 2, (a, b), None, t))
            t += 1 / FPS
            offset = new
        for k in range(per):
            out.write(frame(offset, (a, b), a + (b - a) * k / per, t))
            t += 1 / FPS
    for _ in range(FPS):
        out.write(frame(offset, None, None, t))
        t += 1 / FPS
    out.release()
    return path


PAGE_SIZE = (1920, 1080)
PAGE_PANEL_Y = 300
PAGE_PIECES = ["rock8", "hh16", "shuffle", "fills", "ride", "openhh", "ghost", "rests"]


def page_systems() -> list[tuple[str, int, np.ndarray]]:
    """(piece, system index, image) of every staff line, in reading order."""
    out = []
    for piece in PAGE_PIECES:
        img = cv2.imread(str(DATA / f"{piece}_clean.png"))
        for i, s in enumerate(meta()["pieces"][piece]["systems"]):
            out.append((piece, i, img[max(0, s["y0"] - 30) : s["y1"] + 30]))
    return out


def page_groups() -> list[list[int]]:
    systems = page_systems()
    room = PAGE_SIZE[1] - PAGE_PANEL_Y - 40
    groups, cur, height = [], [], 0
    for i, (_, _, img) in enumerate(systems):
        if cur and height + img.shape[0] > room:
            groups.append(cur)
            cur, height = [], 0
        cur.append(i)
        height += img.shape[0]
    return [*groups, cur]


def page_video(path: Path, seconds: float = 1.5) -> Path:
    W, H = PAGE_SIZE
    systems = page_systems()
    rng = np.random.default_rng(5)
    out = _writer(path, PAGE_SIZE, 75)
    t = 0.0
    for group in page_groups():
        page = np.full((H - PAGE_PANEL_Y, W, 3), 250, np.uint8)
        y, boxes = 20, []
        for i in group:
            img = systems[i][2]
            page[y : y + img.shape[0], 40 : 40 + img.shape[1]] = img
            boxes.append((y, y + img.shape[0]))
            y += img.shape[0]
        n = int(seconds * FPS)
        for k in range(n):
            f = np.empty((H, W, 3), np.uint8)
            f[:PAGE_PANEL_Y] = _camera(rng, PAGE_PANEL_Y, W, t)
            view = page.copy()
            y0, y1 = boxes[min(len(boxes) - 1, k * len(boxes) // n)]
            x = int(200 + (k * 97) % (W - 400))
            cv2.line(view, (x, y0 + 10), (x, y1 - 10), CURSOR, 3)
            f[PAGE_PANEL_Y:] = view
            out.write(f)
            t += 1 / FPS
    out.release()
    return path
