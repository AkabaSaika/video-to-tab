"""Read one track of a Guitar Pro 7/8 file (a zip holding Content/score.gpif) as a Score."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from app.omr.model import HARMONICS, Beat, Measure, Note, Score

NOTE_VALUES = {"Whole": 1, "Half": 2, "Quarter": 4, "Eighth": 8, "16th": 16, "32nd": 32, "64th": 64}


def _index(root: ET.Element, tag: str) -> dict[str, ET.Element]:
    node = root.find(tag)
    return {} if node is None else {e.get("id"): e for e in node}


def _props(el: ET.Element) -> dict[str, ET.Element]:
    props = el.find("Properties")
    return {} if props is None else {p.get("name"): p for p in props}


def track_names(path: Path) -> list[str]:
    root = _load(path)
    return [t.findtext("Name") or "" for t in root.find("Tracks")]


def _load(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("Content/score.gpif"))


def _tuning(track: ET.Element) -> list[int]:
    for prop in track.iter("Property"):
        if prop.get("name") == "Tuning":
            pitches = prop.findtext("Pitches")
            if pitches:
                return [int(v) for v in pitches.split()]
    return []


def _rhythm(r: ET.Element) -> tuple[int, int, int | None]:
    duration = NOTE_VALUES.get(r.findtext("NoteValue") or "Quarter", 4)
    dot = r.find("AugmentationDot")
    dots = int(dot.get("count", "0")) if dot is not None else 0
    tup = r.find("PrimaryTuplet")
    tuplet = int(tup.get("num")) if tup is not None else None
    return duration, dots, tuplet


# GPIF "Slide" flags
SLIDE_OUT_FLAGS = {1: "shift", 2: "legato", 4: "out_down", 8: "out_up"}
SLIDE_IN_FLAGS = {16: "below", 32: "above"}
BEND_UNIT = 50.0  # GPIF bend values: 100 = a whole tone, so 50 per semitone
STACCATO = 1  # bit of a note's <Accent> flags


def _float(p: dict[str, ET.Element], name: str) -> float:
    el = p.get(name)
    text = "".join(el.itertext()).strip() if el is not None else ""
    return float(text) if text else 0.0


def techniques(el: ET.Element, note: Note) -> None:
    """Set the note's playing techniques from its GPIF <Note> element."""
    p = _props(el)
    if "Bended" in p:
        points = [_float(p, f"Bend{k}Value") for k in ("Origin", "Middle", "Destination")]
        peak = max(points)
        if peak > 0:
            note.bend = peak / BEND_UNIT
            note.bend_release = points[2] < peak and points[1] >= peak
    if "Slide" in p:
        flags = int(_float(p, "Slide"))
        note.slide = next((v for k, v in SLIDE_OUT_FLAGS.items() if flags & k), None)
        note.slide_in = next((v for k, v in SLIDE_IN_FLAGS.items() if flags & k), None)
    note.hopo = "HopoOrigin" in p
    if "HarmonicType" in p:
        kind = "".join(p["HarmonicType"].itertext()).strip().lower()
        if kind in HARMONICS:
            note.harmonic = kind
            note.harmonic_fret = _float(p, "HarmonicFret")
    note.palm_mute = "PalmMuted" in p
    note.vibrato = el.find("Vibrato") is not None
    accent = (el.findtext("Accent") or "0").strip()
    note.staccato = accent.isdigit() and bool(int(accent) & STACCATO)


def read_track(path: Path, track_name: str) -> Score:
    """Notes (String/Fret, dead, tied, techniques), durations (NoteValue, dots,
    PrimaryTuplet); first voice only."""
    root = _load(Path(path))
    bars, voices = _index(root, "Bars"), _index(root, "Voices")
    beats, notes, rhythms = _index(root, "Beats"), _index(root, "Notes"), _index(root, "Rhythms")
    tracks = list(root.find("Tracks"))
    names = [t.findtext("Name") for t in tracks]
    if track_name not in names:
        raise ValueError(f"track {track_name!r} not in {names}")
    ti = names.index(track_name)
    tuning = _tuning(tracks[ti])
    tempos = [a for a in root.iter("Automation") if a.findtext("Type") == "Tempo"]
    shown = [a for a in tempos if a.findtext("Visible") != "false"] or tempos
    tempo = int(float((shown[0].findtext("Value") or "0").split()[0])) if shown else None

    measures = []
    for number, mb in enumerate(root.find("MasterBars"), start=1):
        num, den = (int(v) for v in (mb.findtext("Time") or "4/4").split("/"))
        bar = bars[(mb.findtext("Bars") or "").split()[ti]]
        out: list[Beat] = []
        vids = [v for v in (bar.findtext("Voices") or "").split() if v != "-1"]
        if vids:
            for bid in (voices[vids[0]].findtext("Beats") or "").split():
                b = beats[bid]
                duration, dots, tuplet = _rhythm(rhythms[b.find("Rhythm").get("ref")])
                beat_notes = []
                for nid in (b.findtext("Notes") or "").split():
                    p = _props(notes[nid])
                    string = int(p["String"].findtext("String"))
                    note = Note(string, int(p["Fret"].findtext("Fret")))
                    note.dead = "Muted" in p
                    tie = notes[nid].find("Tie")
                    note.tied = tie is not None and tie.get("destination", "").lower() == "true"
                    techniques(notes[nid], note)
                    beat_notes.append(note)
                beat_notes.sort(key=lambda n: n.string)
                out.append(Beat(duration, dots, tuplet, not beat_notes, beat_notes))
        measures.append(Measure(number, (num, den), out))
    return Score(len(tuning), tuning, tempo, measures)
