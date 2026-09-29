"""Synthetic piano videos made from the fixture score (tests/data/piano/score.png)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from tests.piano_data import meta, score

SIZE = (1280, 720)
FPS = 10


def _writer(path: Path, quality: int) -> cv2.VideoWriter:
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), FPS, SIZE)
    out.set(cv2.VIDEOWRITER_PROP_QUALITY, quality)
    assert out.isOpened()
    return out


def _cursor(frame: np.ndarray, top: int, bottom: int, t: float) -> None:
    """A red play cursor across one system, moving right like a player's."""
    x = int(60 + (t * 330) % (SIZE[0] - 120))
    cv2.line(frame, (x, max(0, top)), (x, min(SIZE[1] - 1, bottom)), (40, 40, 220), 3)


def scroll_video(path: Path, speed: float = 150.0, quality: int = 55) -> Path:
    """The score scrolls up continuously, `speed` pixels per second, after a short hold."""
    img, systems = score(), meta()["systems"]
    end = img.shape[0] - SIZE[1]
    hold = FPS  # one second still at the start and at the end
    offsets = [0.0] * hold + list(np.arange(0, end, speed / FPS)) + [float(end)] * hold
    out = _writer(path, quality)
    for i, off in enumerate(offsets):
        y = int(round(off))
        frame = img[y : y + SIZE[1]].copy()
        # the cursor plays the first system whose top is in the upper half of the frame
        playing = next((s for s in systems if s["y0"] - y >= 0), systems[-1])
        _cursor(frame, playing["y0"] - y, playing["y1"] - y, i / FPS)
        out.write(frame)
    out.release()
    return path


def pages() -> list[list[int]]:
    """Systems grouped into pages that fit the frame, in order."""
    groups, current, height = [], [], 0
    for i, s in enumerate(meta()["systems"]):
        h = s["y1"] - s["y0"] + 60
        if current and height + h > SIZE[1] - 40:
            groups.append(current)
            current, height = [], 0
        current.append(i)
        height += h
    return groups + [current]


def page_video(path: Path, seconds: float = 1.5, quality: int = 55) -> Path:
    """Whole pages of systems, each shown for `seconds`, hard cuts between them."""
    img, systems = score(), meta()["systems"]
    out = _writer(path, quality)
    t = 0
    for group in pages():
        page = np.full((SIZE[1], SIZE[0], 3), 255, np.uint8)
        y = 30
        boxes = []
        for i in group:
            s = systems[i]
            part = img[s["y0"] - 30 : s["y1"] + 30]
            page[y : y + part.shape[0]] = part
            boxes.append((y + 30, y + part.shape[0] - 30))
            y += part.shape[0]
        for _ in range(int(seconds * FPS)):
            frame = page.copy()
            top, bottom = boxes[min(len(boxes) - 1, int(t / FPS / seconds * len(boxes)) % 2)]
            _cursor(frame, top, bottom, t / FPS)
            out.write(frame)
            t += 1
    out.release()
    return path
