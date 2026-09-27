from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    w: int
    h: int

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y : self.y + self.h, self.x : self.x + self.w]

    def clamp(self, width: int, height: int) -> Roi:
        x = min(max(self.x, 0), width - 1)
        y = min(max(self.y, 0), height - 1)
        w = max(1, min(self.w, width - x))
        h = max(1, min(self.h, height - y))
        return Roi(x, y, w, h)

    def iou(self, other: Roi) -> float:
        ix = max(0, min(self.x + self.w, other.x + other.w) - max(self.x, other.x))
        iy = max(0, min(self.y + self.h, other.y + other.h) - max(self.y, other.y))
        inter = ix * iy
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union else 0.0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class Segment:
    start_idx: int  # first sample index (inclusive)
    end_idx: int  # last sample index (inclusive)
    start: float  # seconds
    end: float  # seconds (end of last sample's interval)


@dataclass
class Page:
    image: np.ndarray  # BGR crop of the ROI, cursor removed
    start: float
    end: float
    duplicate_of: int | None = None  # index of an earlier page with identical content
