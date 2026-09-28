"""Measure-sum solver: pick one duration per beat so the measure adds up to its time
signature, maximizing the joint probability of the per-beat candidates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from app.omr.model import TUPLET_RATIO, Beat
from app.omr.rhythm import BeatMarks

DURATIONS = (1, 2, 4, 8, 16, 32)


@dataclass(frozen=True)
class Option:
    duration: int
    dots: int
    tuplet: int | None
    p: float

    def length(self) -> Fraction:
        value = Fraction(1, self.duration) * (2 - Fraction(1, 2**self.dots))
        if self.tuplet:
            n, m = TUPLET_RATIO.get(self.tuplet, (self.tuplet, self.tuplet))
            value *= Fraction(m, n)
        return value


@dataclass
class BeatEvidence:
    marks: BeatMarks
    circled: bool = False
    rest_kind: str | None = None
    short_stem: bool = False  # stem clearly shorter than the typical one (GP half notes)
    spacing_guess: int | None = None  # duration from horizontal spacing, if no marks


def _add(opts: dict, d: int, dots: int, tup: int | None, p: float) -> None:
    if d not in DURATIONS or p <= 0:
        return
    key = (d, dots, tup)
    opts[key] = max(opts.get(key, 0.0), p)


def candidates(ev: BeatEvidence) -> list[Option]:
    """Primary reading plus the likely misreadings, with rough prior probabilities."""
    m = ev.marks
    opts: dict = {}
    if ev.rest_kind:
        base = {
            "rest_block": [(1, 0.5), (2, 0.45)],
            "rest_4": [(4, 0.9)],
            "rest_8": [(8, 0.9)],
            "rest_16": [(16, 0.9)],
        }[ev.rest_kind]
        for d, p in base:
            _add(opts, d, 0, None, p)
            _add(opts, d, 1, None, p * 0.08)
            _add(opts, d * 2, 0, None, p * 0.05)
            _add(opts, d // 2 if d > 1 else 0, 0, None, p * 0.05)
    elif m.stem:
        d = 4 * 2**m.beams
        if m.beams == 0 and (ev.short_stem or ev.circled):
            d = 2
        dots = 1 if m.dot else 0
        tup = m.tuplet
        pc = 0.9 if m.beam_conf >= 0.7 else 0.7
        _add(opts, d, dots, tup, pc)
        _add(opts, d, 1 - dots, tup, 0.03)
        beamed = 4 * 2**m.beams  # one beam/flag more or less than counted
        _add(opts, beamed * 2, dots, tup, (1 - pc) * 0.5)
        if m.beams:
            _add(opts, beamed // 2, dots, tup, (1 - pc) * 0.5)
        if m.beams == 0:  # half vs quarter is only a stem-length / circle cue
            _add(opts, 4 if d == 2 else 2, dots, tup, 0.01 if d == 2 else 0.08)
        if tup is not None:
            _add(opts, d, dots, None, 0.05)
    elif ev.circled:
        _add(opts, 1, 0, None, 0.85)
        _add(opts, 2, 0, None, 0.08)
        _add(opts, 1, 1, None, 0.02)
        _add(opts, 2, 1, None, 0.02)
    else:  # no rhythm marks: horizontal spacing only
        guess = ev.spacing_guess or 4
        for d in DURATIONS:
            steps = abs(math.log2(d) - math.log2(guess))
            _add(opts, d, 0, None, 0.4 * 0.25**steps)
            _add(opts, d, 1, None, 0.05 * 0.25**steps)
    return [Option(d, dots, t, p) for (d, dots, t), p in opts.items()]


TUPLET_GROUP_P = 0.02  # a whole group of 3 read as a triplet without a visible "3"


def solve_measure(evidence: list[BeatEvidence], capacity: Fraction) -> tuple[list[Option], bool]:
    """Best exact-sum assignment (DP over beat index and running sum); falls back to the
    per-beat best. A run of 3 equal plain durations may also become one triplet group
    (the "3" is often cut off or faint), at a single penalty for the group."""
    cands = [sorted(candidates(ev), key=lambda o: -o.p) for ev in evidence]
    if not cands:
        return [], True
    n = len(cands)
    # states[i]: {total: (logp, chosen)} after the first i beats
    states: list[dict] = [dict() for _ in range(n + 1)]
    states[0][Fraction(0)] = (0.0, [])

    def push(i: int, total: Fraction, lp: float, chosen: list[Option]) -> None:
        if total <= capacity and (total not in states[i] or states[i][total][0] < lp):
            states[i][total] = (lp, chosen)

    for i in range(n):
        for total, (lp, chosen) in states[i].items():
            for o in cands[i]:
                push(i + 1, total + o.length(), lp + math.log(o.p), [*chosen, o])
            if i + 3 <= n:
                firsts = [cands[k][0] for k in range(i, i + 3)]
                d = firsts[0].duration
                if all(f.duration == d and f.tuplet is None and f.dots == 0 for f in firsts):
                    group = [Option(d, 0, 3, f.p) for f in firsts]
                    glp = math.log(TUPLET_GROUP_P) + sum(math.log(f.p) for f in firsts)
                    push(i + 3, total + sum(g.length() for g in group), lp + glp, [*chosen, *group])
    if capacity in states[n]:
        return states[n][capacity][1], True
    return [opts[0] for opts in cands], False


def apply(beats: list[Beat], evidence: list[BeatEvidence], capacity: Fraction) -> bool:
    """Fill in durations on `beats` in place; returns whether the measure sums up."""
    chosen, ok = solve_measure(evidence, capacity)
    for beat, ev, o in zip(beats, evidence, chosen, strict=True):
        total = sum(c.p for c in candidates(ev)) or 1.0
        beat.duration, beat.dots, beat.tuplet = o.duration, o.dots, o.tuplet
        note_conf = min((n.confidence for n in beat.notes), default=1.0)
        beat.confidence = round((o.p / total) * note_conf * (1.0 if ok else 0.5), 3)
    return ok
