"""The drum test fixture (tests/data/drums, made by make_drum_fixture.py) and the
instrument + onset scoring used by the spike (docs/superpowers/specs/...-drums-design.md)."""

from __future__ import annotations

import json
from collections import Counter
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from app.drums.instruments import Mapping
from app.drums.model import DrumMeasure

DATA = Path(__file__).resolve().parent / "data" / "drums"
VARIANTS = {"clean": "_clean.png", "deg": "_deg.jpg", "1280": "_1280.jpg", "lily": "_lily.png"}
NAMES = {49: "cr", 42: "hh", 46: "ohh", 51: "rd", 50: "t1", 47: "t2", 38: "sn", 43: "ft"}
NAMES |= {36: "bd", 44: "ph"}


@cache
def meta() -> dict:
    return json.loads((DATA / "pieces.json").read_text())


@cache
def strip_meta() -> dict:
    return json.loads((DATA / "strip.json").read_text())


def image(piece: str, variant: str = "clean") -> np.ndarray:
    img = cv2.imread(str(DATA / f"{piece}{VARIANTS[variant]}"))
    assert img is not None, (piece, variant)
    return img


def gt_measures(events: list, count: int) -> list[list[tuple]]:
    """[(voice, onset16, dur16, instrument or 'rest')] per measure; ghost snare = snare."""
    ms: list[list[tuple]] = [[] for _ in range(count)]
    for mi, vi, on, d, inst in events:
        ms[mi].append((vi, on, d, "sn" if inst == "gs" else inst))
    return ms


def predicted(measures: list[DrumMeasure], mapping: Mapping | None = None) -> list[list[tuple]]:
    mapping = mapping or Mapping()
    out = []
    for m in measures:
        ev = []
        for vi, voice in enumerate(m.voices, 1):
            for b in voice:
                on, d = round(b.onset * 16), round(b.length() * 16)
                if b.rest or not b.notes:
                    ev.append((vi, on, d, "rest"))
                for n in b.notes:
                    gm = mapping.resolve(n)
                    ev.append((vi, on, d, NAMES.get(gm, f"gm{gm}")))
        out.append(ev)
    return out


def _notes(ev):
    return [e for e in ev if e[3] != "rest"]


def _sim(a, b) -> float:
    ca, cb = Counter(e[3] for e in _notes(a)), Counter(e[3] for e in _notes(b))
    return sum((ca & cb).values()) / max(sum(ca.values()), sum(cb.values()), 1)


def align(gt: list, pr: list) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch over measures on their instrument multisets."""
    G, P, gap = len(gt), len(pr), -0.3
    D = [[0.0] * (P + 1) for _ in range(G + 1)]
    B: list[list[str | None]] = [[None] * (P + 1) for _ in range(G + 1)]
    for i in range(1, G + 1):
        D[i][0], B[i][0] = D[i - 1][0] + gap, "u"
    for j in range(1, P + 1):
        D[0][j], B[0][j] = D[0][j - 1] + gap, "l"
    for i in range(1, G + 1):
        for j in range(1, P + 1):
            D[i][j], B[i][j] = max(
                (D[i - 1][j - 1] + _sim(gt[i - 1], pr[j - 1]), "d"),
                (D[i - 1][j] + gap, "u"),
                (D[i][j - 1] + gap, "l"),
            )
    i, j, path = G, P, []
    while i > 0 or j > 0:
        if B[i][j] == "d":
            path.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif B[i][j] == "u":
            path.append((i - 1, None))
            i -= 1
        else:
            path.append((None, j - 1))
            j -= 1
    return path[::-1]


def _inter(a, b) -> int:
    return sum((Counter(a) & Counter(b)).values())


def score(gt: list, pr: list) -> Counter:
    c: Counter = Counter()
    for gi, pi in align(gt, pr):
        g = gt[gi] if gi is not None else []
        p = pr[pi] if pi is not None else []
        gn, pn = _notes(g), _notes(p)
        c["gt"] += len(gn)
        c["pr"] += len(pn)
        c["inst"] += _inter([(e[1], e[3]) for e in gn], [(e[1], e[3]) for e in pn])
        c["dur"] += _inter([(e[1], e[2], e[3]) for e in gn], [(e[1], e[2], e[3]) for e in pn])
        if gi is not None:
            c["exact"] += {(e[1], e[3]) for e in gn} == {(e[1], e[3]) for e in pn}
    c["m_gt"], c["m_pr"] = len(gt), len(pr)
    return c


def rates(c: Counter) -> dict:
    return {
        "recall": round(c["inst"] / max(c["gt"], 1), 3),
        "precision": round(c["inst"] / max(c["pr"], 1), 3),
        "exact_measures": round(c["exact"] / max(c["m_gt"], 1), 3),
        "duration_of_matched": round(c["dur"] / max(c["inst"], 1), 3),
        "measures": f"{c['m_pr']}/{c['m_gt']}",
    }
