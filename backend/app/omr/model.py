"""Recognized-score data model, shared by recognition, evaluation and (later) the editor UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fractions import Fraction

STANDARD_TUNINGS = {
    6: [40, 45, 50, 55, 59, 64],
    7: [35, 40, 45, 50, 55, 59, 64],
}


@dataclass
class Note:
    string: int  # 0 = lowest string = bottom line
    fret: int
    confidence: float = 1.0
    dead: bool = False  # "x" in the tab; fret is 0


@dataclass
class Beat:
    duration: int = 4  # 1/2/4/8/16/32
    dots: int = 0
    tuplet: int | None = None  # e.g. 3 for a triplet
    rest: bool = False
    notes: list[Note] = field(default_factory=list)
    x: int = 0
    confidence: float = 1.0

    def length(self) -> Fraction:
        """Length in whole notes."""
        base = Fraction(1, self.duration)
        value = base * (2 - Fraction(1, 2**self.dots))
        if self.tuplet:
            value *= Fraction(
                TUPLET_RATIO.get(self.tuplet, (self.tuplet, self.tuplet))[1], self.tuplet
            )
        return value


# n notes in the time of m: (n, m)
TUPLET_RATIO = {3: (3, 2), 5: (5, 4), 6: (6, 4), 7: (7, 4), 9: (9, 8)}


@dataclass
class Measure:
    number: int | None = None
    time: tuple[int, int] = (4, 4)
    beats: list[Beat] = field(default_factory=list)
    line: int = 0
    x0: int = 0
    x1: int = 0
    confidence: float = 1.0

    def capacity(self) -> Fraction:
        return Fraction(self.time[0], self.time[1])


@dataclass
class Score:
    strings: int = 6
    tuning: list[int] = field(default_factory=list)
    tempo: int | None = None
    measures: list[Measure] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Score:
        measures = []
        for m in d.get("measures", []):
            beats = [
                Beat(**{**b, "notes": [Note(**n) for n in b.get("notes", [])]})
                for b in m.get("beats", [])
            ]
            measures.append(Measure(**{**m, "time": tuple(m.get("time", (4, 4))), "beats": beats}))
        return Score(d.get("strings", 6), d.get("tuning", []), d.get("tempo"), measures)
