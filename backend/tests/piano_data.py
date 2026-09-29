"""Shared helpers for the piano tests: the synthetic score fixture (tests/data/piano)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import cv2
import numpy as np
import pytest

DATA = Path(__file__).resolve().parent / "data" / "piano"


@cache
def score() -> np.ndarray:
    """The tall grand-staff score image (BGR), systems stacked top to bottom."""
    img = cv2.imread(str(DATA / "score.png"))
    assert img is not None
    return img


@cache
def meta() -> dict:
    return json.loads((DATA / "score.json").read_text())


def system_crop(i: int, pad: int = 45) -> np.ndarray:
    s = meta()["systems"][i]
    img = score()
    return img[max(0, s["y0"] - pad) : s["y1"] + pad].copy()


def needs_models():
    from app.piano import engine

    return pytest.mark.skipif(
        not engine.models_available(), reason="homr models not installed (see README)"
    )
