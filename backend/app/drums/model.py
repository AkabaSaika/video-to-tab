"""Recognized drum notation: what is printed, not what it means.

A note keeps its staff position (display step + octave, as on a percussion clef whose
bottom line is E4) and its notehead shape. Which drum that is gets decided at export time
by the instrument map (app.drums.instruments), so a changed map never needs the image
read again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from app.omr.model import TUPLET_RATIO

VERSION = 1
NOTEHEADS = ("normal", "hollow", "x", "circle-x")
_DIA = "CDEFGAB"
_BOTTOM = _DIA.index("E") + 7 * 4  # E4, the bottom staff line


def staff_step(step: str, octave: int) -> int:
    """Staff position: 0 = bottom line, 1 = the space above it, ... (-1 below it)."""
    return _DIA.index(step) + 7 * octave - _BOTTOM


def position(step: int) -> tuple[str, int]:
    """(display step, octave) of staff position `step`."""
    n = step + _BOTTOM
    return _DIA[n % 7], n // 7


@dataclass
class DrumNote:
    step: str  # display step on the percussion staff (A..G)
    octave: int
    notehead: str = "normal"  # one of NOTEHEADS
    accent: bool = False
    ghost: bool = False  # in parentheses
    open: bool = False  # an "o" above it (open hi-hat)

    def key(self) -> str:
        return f"{self.step}{self.octave}"

    def to_dict(self) -> dict:
        d = {"step": self.step, "octave": self.octave, "notehead": self.notehead}
        d |= {k: True for k in ("accent", "ghost", "open") if getattr(self, k)}
        return d

    @staticmethod
    def from_dict(d: dict) -> DrumNote:
        step, octave = str(d["step"]).upper(), int(d["octave"])
        if step not in _DIA:
            raise ValueError(f"bad step {step!r}")
        head = d.get("notehead", "normal")
        if head not in NOTEHEADS:
            head = "normal"
        return DrumNote(
            step,
            octave,
            head,
            bool(d.get("accent")),
            bool(d.get("ghost")),
            bool(d.get("open")),
        )


def _fraction(value) -> Fraction:
    if isinstance(value, str):
        return Fraction(value)
    if isinstance(value, int | float):  # older data: onset in quarter notes
        return Fraction(value).limit_denominator(96) / 4
    raise ValueError(f"bad onset {value!r}")


@dataclass
class Beat:
    onset: Fraction  # from the measure start, in whole notes
    duration: int  # note value: 1 whole, 2 half, 4 quarter, ... 32
    dots: int = 0
    tuplet: int | None = None  # 3 = triplet
    rest: bool = False
    notes: list[DrumNote] = field(default_factory=list)

    def length(self) -> Fraction:
        value = Fraction(1, self.duration) * (2 - Fraction(1, 2**self.dots))
        if self.tuplet:
            n, m = TUPLET_RATIO.get(self.tuplet, (self.tuplet, self.tuplet))
            value *= Fraction(m, n)
        return value

    def end(self) -> Fraction:
        return self.onset + self.length()

    def to_dict(self) -> dict:
        d: dict = {"onset": str(self.onset), "duration": self.duration}
        if self.dots:
            d["dots"] = self.dots
        if self.tuplet:
            d["tuplet"] = self.tuplet
        if self.rest:
            d["rest"] = True
        if self.notes:
            d["notes"] = [n.to_dict() for n in self.notes]
        return d

    @staticmethod
    def from_dict(d: dict) -> Beat:
        duration = int(d["duration"])
        if duration not in (1, 2, 4, 8, 16, 32, 64):
            raise ValueError(f"bad duration {duration}")
        return Beat(
            _fraction(d.get("onset", "0")),
            duration,
            int(d.get("dots", 0)),
            int(d["tuplet"]) if d.get("tuplet") else None,
            bool(d.get("rest")),
            [DrumNote.from_dict(n) for n in d.get("notes", [])],
        )


@dataclass
class DrumMeasure:
    voices: list[list[Beat]]  # voice 1: stems up (hands), voice 2: stems down (feet)
    ok: bool | None = None  # the durations add up to the time signature (None: unknown)
    time: tuple[int, int] | None = None  # the time signature it was read with

    def to_dict(self) -> dict:
        d: dict = {"voices": [[b.to_dict() for b in v] for v in self.voices], "ok": self.ok}
        if self.time:
            d["time"] = list(self.time)
        return d

    @staticmethod
    def from_dict(d: dict) -> DrumMeasure:
        time = d.get("time")
        return DrumMeasure(
            [[Beat.from_dict(b) for b in v] for v in d.get("voices", [])],
            d.get("ok"),
            (int(time[0]), int(time[1])) if time else None,
        )


@dataclass
class DrumScore:
    title: str = ""
    tempo: int = 120  # quarter notes per minute
    time: tuple[int, int] = (4, 4)
    measures: list[DrumMeasure] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": VERSION,
            "title": self.title,
            "tempo": self.tempo,
            "time": list(self.time),
            "measures": [m.to_dict() for m in self.measures],
        }

    @staticmethod
    def from_dict(d: dict) -> DrumScore:
        try:
            time = d.get("time") or (4, 4)
            return DrumScore(
                str(d.get("title", "")),
                int(d.get("tempo", 120)),
                (int(time[0]), int(time[1])),
                [DrumMeasure.from_dict(m) for m in d.get("measures", [])],
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"鼓谱数据不合法：{exc}") from exc
