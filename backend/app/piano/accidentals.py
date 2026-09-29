"""Add the <accidental> marks MusicXML readers draw.

homr writes each note's pitch (<alter>) but no <accidental> element. MuseScore works the
marks out itself, but Verovio (the preview) and other readers only draw what <accidental>
says, so a D-sharp would show as a plain D. Standard rules: an accidental holds for the
rest of the measure on that staff and octave, and the key signature sets the default.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

SHARP_ORDER = "FCGDAEB"  # the order sharps are added to a key signature; flats reverse it
NAMES = {-2: "flat-flat", -1: "flat", 0: "natural", 1: "sharp", 2: "double-sharp"}
# elements a <note> may have before <accidental> (MusicXML note content order)
BEFORE_ACCIDENTAL = (
    "grace", "chord", "pitch", "unpitched", "rest", "duration", "tie", "cue",
    "instrument", "footnote", "level", "voice", "type", "dot",
)  # fmt: skip


def key_alters(fifths: int) -> dict[str, int]:
    """Step → alter set by a key signature with this many sharps (> 0) or flats (< 0)."""
    if fifths >= 0:
        return {step: 1 for step in SHARP_ORDER[:fifths]}
    return {step: -1 for step in SHARP_ORDER[::-1][:-fifths]}


def _insert_accidental(note: ET.Element, name: str) -> None:
    children = list(note)
    at = 0
    for i, child in enumerate(children):
        if child.tag in BEFORE_ACCIDENTAL:
            at = i + 1
    acc = ET.Element("accidental")
    acc.text = name
    note.insert(at, acc)


def _mark_measure(measure: ET.Element, key: dict[str, int]) -> None:
    held: dict[tuple[str, str, str], int] = {}  # (staff, step, octave) -> alter in force
    for note in measure.findall("note"):
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step, octave = pitch.findtext("step", ""), pitch.findtext("octave", "")
        staff = note.findtext("staff", "1")
        alter = int(round(float(pitch.findtext("alter") or 0)))
        slot = (staff, step, octave)
        expected = held.get(slot, key.get(step, 0))
        tied = any(t.get("type") == "stop" for t in note.findall("tie"))
        if note.find("accidental") is None and alter != expected and not tied:
            _insert_accidental(note, NAMES.get(alter, "natural"))
        held[slot] = alter


def add_accidentals(xml: str) -> str:
    """The same MusicXML with <accidental> added wherever a reader must draw one."""
    root = ET.fromstring(xml)
    for part in root.findall("part"):
        key: dict[str, int] = {}
        for measure in part.findall("measure"):
            fifths = measure.findtext("attributes/key/fifths")
            if fifths is not None:
                key = key_alters(int(fifths))
            _mark_measure(measure, key)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
