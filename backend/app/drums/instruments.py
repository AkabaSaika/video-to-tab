"""Which drum a notehead means: a (staff position, notehead) → General MIDI map.

There is no single standard for drum notation, so the map comes from a preset (a common
default, Guitar Pro's or MuseScore's) plus the user's own overrides. Keys look like
"G5:x" (position and notehead family), or "G5:x:open" for a note with an "o" above it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.drums.model import DrumMeasure, DrumNote, staff_step

FAMILIES = ("normal", "x", "circle-x")


@dataclass(frozen=True)
class Instrument:
    gm: int  # General MIDI percussion key (channel 10)
    name: str  # English name (MusicXML)
    label: str  # Chinese name (UI)
    head: str  # the MusicXML notehead it is written with


INSTRUMENTS: dict[int, Instrument] = {
    i.gm: i
    for i in (
        Instrument(35, "Acoustic Bass Drum", "底鼓 2", "normal"),
        Instrument(36, "Bass Drum 1", "底鼓", "normal"),
        Instrument(37, "Side Stick", "边击", "x"),
        Instrument(38, "Acoustic Snare", "军鼓", "normal"),
        Instrument(39, "Hand Clap", "拍手", "normal"),
        Instrument(40, "Electric Snare", "军鼓 2", "normal"),
        Instrument(41, "Low Floor Tom", "低音落地嗵鼓", "normal"),
        Instrument(42, "Closed Hi-Hat", "闭镲", "x"),
        Instrument(43, "High Floor Tom", "落地嗵鼓", "normal"),
        Instrument(44, "Pedal Hi-Hat", "踩镲踏板", "x"),
        Instrument(45, "Low Tom", "低嗵鼓", "normal"),
        Instrument(46, "Open Hi-Hat", "开镲", "x"),  # with an "o" above
        Instrument(47, "Low-Mid Tom", "中嗵鼓", "normal"),
        Instrument(48, "Hi-Mid Tom", "中高嗵鼓", "normal"),
        Instrument(49, "Crash Cymbal 1", "吊镲", "x"),
        Instrument(50, "High Tom", "高嗵鼓", "normal"),
        Instrument(51, "Ride Cymbal 1", "叮叮镲", "x"),
        Instrument(52, "Chinese Cymbal", "中国镲", "x"),
        Instrument(53, "Ride Bell", "叮叮镲镲帽", "diamond"),
        Instrument(54, "Tambourine", "铃鼓", "x"),
        Instrument(55, "Splash Cymbal", "水镲", "x"),
        Instrument(56, "Cowbell", "牛铃", "x"),
        Instrument(57, "Crash Cymbal 2", "吊镲 2", "x"),
        Instrument(59, "Ride Cymbal 2", "叮叮镲 2", "x"),
    )
}

_COMMON = {
    "A5:x": 49,
    "A5:circle-x": 49,
    "B5:x": 57,
    "G5:x": 42,
    "G5:x:open": 46,
    "G5:circle-x": 46,
    "F5:x": 51,
    "F5:circle-x": 53,
    "E5:normal": 50,
    "D5:normal": 47,
    "C5:normal": 38,
    "C5:x": 37,
    "B4:normal": 45,
    "A4:normal": 43,
    "G4:normal": 41,
    "F4:normal": 36,
    "E4:normal": 35,
    "D4:x": 44,
}
PRESETS: dict[str, dict[str, int]] = {
    # the usual convention (Weinberg / most method books)
    "default": dict(_COMMON),
    # Guitar Pro's drum kit: open hi-hat written as a circled x, mid tom Hi-Mid,
    # the crash with a line through it, China above it
    "gp": _COMMON | {"D5:normal": 48, "B5:x": 52, "C6:x": 55, "C5:circle-x": 37},
    # MuseScore's default drum set
    "musescore": _COMMON | {"D5:normal": 48, "B5:x": 57, "C6:x": 52, "E5:x": 53},
}
PRESET_NAMES = {"default": "通用", "gp": "Guitar Pro", "musescore": "MuseScore"}


def head_family(notehead: str) -> str:
    return "normal" if notehead in ("normal", "hollow") else notehead


def note_key(note: DrumNote, with_open: bool = True) -> str:
    key = f"{note.key()}:{head_family(note.notehead)}"
    return f"{key}:open" if with_open and note.open else key


def _check_key(key: str) -> None:
    parts = key.split(":")
    ok = 2 <= len(parts) <= 3 and parts[1] in FAMILIES and parts[2:] in ([], ["open"])
    pos = parts[0]
    ok = ok and len(pos) == 2 and pos[0] in "CDEFGAB" and pos[1].isdigit()
    if not ok:
        raise ValueError(f"乐器对应表的位置不合法：{key}")


@dataclass
class Mapping:
    preset: str = "default"
    overrides: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.preset not in PRESETS:
            raise ValueError(f"未知的预设：{self.preset}")
        for key, gm in self.overrides.items():
            _check_key(key)
            if gm not in INSTRUMENTS:
                raise ValueError(f"未知的乐器编号：{gm}")

    def table(self) -> dict[str, int]:
        return PRESETS[self.preset] | self.overrides

    def resolve(self, note: DrumNote) -> int:
        """GM key of a note: its exact entry, else the entry without "open" (a closed
        hi-hat with an "o" becomes the open one), else the nearest position written with
        the same kind of notehead."""
        table = self.table()
        if note.open and (gm := table.get(note_key(note))) is not None:
            return gm
        family = head_family(note.notehead)
        gm = table.get(note_key(note, with_open=False))
        if gm is None and family == "circle-x":
            family = "x"
            gm = table.get(f"{note.key()}:x")
        if gm is None:
            step = staff_step(note.step, note.octave)
            same = [k for k in table if k.split(":")[1] == family and len(k.split(":")) == 2]
            if not same:
                same = [k for k in table if len(k.split(":")) == 2]

            def distance(key: str) -> tuple[int, int]:
                pos = key.split(":")[0]
                d = staff_step(pos[0], int(pos[1])) - step
                return abs(d), d  # ties: the lower one

            gm = table[min(same, key=distance)]
        if note.open and gm == 42:
            return 46
        return gm

    def to_dict(self) -> dict:
        return {"preset": self.preset, "overrides": dict(self.overrides)}

    @staticmethod
    def from_dict(d: dict | None) -> Mapping:
        d = d or {}
        overrides = {str(k): int(v) for k, v in (d.get("overrides") or {}).items()}
        return Mapping(str(d.get("preset") or "default"), overrides)


def used_keys(measures: Iterable[DrumMeasure]) -> dict[str, int]:
    """How many notes each map key covers in these measures."""
    count: Counter[str] = Counter()
    for m in measures:
        for voice in m.voices:
            for beat in voice:
                count.update(note_key(n) for n in beat.notes)
    return dict(count)


def catalog() -> dict:
    """Everything the mapping panel needs to show choices."""
    return {
        "instruments": [
            {"gm": i.gm, "name": i.name, "label": i.label} for i in INSTRUMENTS.values()
        ],
        "presets": [{"id": k, "name": PRESET_NAMES[k], "table": v} for k, v in PRESETS.items()],
    }
