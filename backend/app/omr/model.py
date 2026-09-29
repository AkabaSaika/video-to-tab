"""Recognized-score data model, shared by recognition, evaluation and (later) the editor UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
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
    title: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Score:
        """Build a Score from JSON data; missing fields get defaults, wrong types raise
        ValueError with a Chinese message naming the field."""
        d = _obj(d, "乐谱")
        measures = []
        for i, m in enumerate(_list(d, "measures", "measures")):
            where = f"measures[{i}]"
            m = _obj(m, where)
            beats = []
            for j, b in enumerate(_list(m, "beats", f"{where}.beats")):
                bw = f"{where}.beats[{j}]"
                b = _obj(b, bw)
                notes = []
                for k, n in enumerate(_list(b, "notes", f"{bw}.notes")):
                    nw = f"{bw}.notes[{k}]"
                    n = _obj(n, nw)
                    notes.append(
                        Note(
                            _int(n, "string", 0, nw),
                            _int(n, "fret", 0, nw),
                            _num(n, "confidence", 1.0, nw),
                            _bool(n, "dead", False, nw),
                        )
                    )
                beats.append(
                    Beat(
                        _int(b, "duration", 4, bw),
                        _int(b, "dots", 0, bw),
                        _int(b, "tuplet", None, bw, optional=True),
                        _bool(b, "rest", False, bw),
                        notes,
                        _int(b, "x", 0, bw),
                        _num(b, "confidence", 1.0, bw),
                    )
                )
            time = m.get("time", [4, 4])
            if not (
                isinstance(time, list | tuple) and len(time) == 2 and all(_is_int(v) for v in time)
            ):
                raise ValueError(f"{where}.time 应为两个整数")
            measures.append(
                Measure(
                    _int(m, "number", None, where, optional=True),
                    (time[0], time[1]),
                    beats,
                    _int(m, "line", 0, where),
                    _int(m, "x0", 0, where),
                    _int(m, "x1", 0, where),
                    _num(m, "confidence", 1.0, where),
                )
            )
        tuning = d.get("tuning", [])
        if not (isinstance(tuning, list) and all(_is_int(v) for v in tuning)):
            raise ValueError("tuning 应为整数列表")
        title = d.get("title", "")
        if not isinstance(title, str):
            raise ValueError("title 应为字符串")
        return Score(
            _int(d, "strings", 6, "乐谱"),
            list(tuning),
            _int(d, "tempo", None, "乐谱", optional=True),
            measures,
            title,
        )


def pad_numbers(score: Score) -> Score:
    """Make measures[i].number == i + 1 when the recognized numbers strictly increase.

    Measures before the first one shown in the video become whole rests (line -1,
    confidence 1: nothing to check); numbers missing in between become whole rests with
    confidence 0 so the editor flags them. Otherwise the score is returned unchanged.
    """
    numbers = [m.number for m in score.measures]
    if not numbers or any(n is None for n in numbers) or numbers[0] < 1:
        return score
    if any(b <= a for a, b in zip(numbers, numbers[1:], strict=False)):
        return score
    measures: list[Measure] = []
    for m in score.measures:
        while len(measures) + 1 < m.number:
            n = len(measures) + 1
            confidence = 1.0 if n < numbers[0] else 0.0
            rest = Beat(1, 0, None, True, [])
            measures.append(Measure(n, (4, 4), [rest], line=-1, confidence=confidence))
        measures.append(m)
    return replace(score, measures=measures)


# ------------------------------------------------------------ from_dict validation


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _obj(v: object, where: str) -> dict:
    if not isinstance(v, dict):
        raise ValueError(f"{where} 应为对象")
    return v


def _list(d: dict, key: str, where: str) -> list:
    v = d.get(key, [])
    if not isinstance(v, list):
        raise ValueError(f"{where} 应为列表")
    return v


def _int(d: dict, key: str, default: int | None, where: str, optional: bool = False):
    v = d.get(key, default)
    if (v is None and optional) or _is_int(v):
        return v
    raise ValueError(f"{where}.{key} 应为整数")


def _num(d: dict, key: str, default: float, where: str) -> float:
    v = d.get(key, default)
    if isinstance(v, int | float) and not isinstance(v, bool):
        return float(v)
    raise ValueError(f"{where}.{key} 应为数字")


def _bool(d: dict, key: str, default: bool, where: str) -> bool:
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    raise ValueError(f"{where}.{key} 应为 true 或 false")
