"""DrumScore → MusicXML (unpitched notes on a percussion staff) and Standard MIDI File.

The instrument of every note comes from the Mapping at export time: MusicXML gets one
<score-instrument>/<midi-instrument> per drum used and an <instrument id> on each note;
MIDI gets GM percussion keys on channel 10. music21's MIDI export ignores
<midi-unpitched> (every drum comes out as key 36), so the MIDI file is written here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from fractions import Fraction
from xml.sax.saxutils import escape

from app.drums.instruments import INSTRUMENTS, Mapping
from app.drums.model import Beat, DrumMeasure, DrumNote, DrumScore

DIVISIONS = 1680  # per quarter: whole numbers for 64ths and 3-, 5-, 6-, 7-tuplets
PPQ = 480
TYPES = {1: "whole", 2: "half", 4: "quarter", 8: "eighth", 16: "16th", 32: "32nd", 64: "64th"}
VELOCITY = {"normal": 96, "accent": 120, "ghost": 40}
GATE = Fraction(1, 16)  # drums are one-shots: a short note-off keeps MIDI files tidy


@dataclass
class Placed:
    """A beat as written: its start, its written length and how it is spelled."""

    start: Fraction
    length: Fraction
    duration: int
    dots: int
    tuplet: int | None
    rest: bool
    notes: list[DrumNote]


def capacity(time: tuple[int, int]) -> Fraction:
    return Fraction(time[0], time[1])


def spell(length: Fraction) -> tuple[int, int] | None:
    """(note value, dots) whose length is exactly `length`, plain or dotted."""
    for d in TYPES:
        for dots in (0, 1, 2):
            if Fraction(1, d) * (2 - Fraction(1, 2**dots)) == length:
                return d, dots
    return None


def _largest_fitting(length: Fraction) -> tuple[int, int, Fraction]:
    for d in TYPES:
        for dots in (1, 0):
            value = Fraction(1, d) * (2 - Fraction(1, 2**dots))
            if value <= length:
                return d, dots, value
    return 64, 0, Fraction(1, 64)


def place(voice: list[Beat], cap: Fraction) -> list[Placed]:
    """A voice made writable: in time order, nothing before the previous beat's end,
    nothing past the measure end. A beat too long for the room before the next one is
    shortened (and respelled); the gaps are left for <forward>."""
    beats = sorted(voice, key=lambda b: b.onset)
    out: list[Placed] = []
    pos = Fraction(0)
    for i, b in enumerate(beats):
        start = max(b.onset, pos)
        if start >= cap:
            break
        nxt = next((n.onset for n in beats[i + 1 :] if n.onset > start), cap)
        room = min(nxt, cap) - start
        length = b.length()
        d, dots, tup = b.duration, b.dots, b.tuplet
        if length > room:
            d, dots, length = _largest_fitting(room)
            tup = None
        out.append(Placed(start, length, d, dots, tup, b.rest or not b.notes, b.notes))
        pos = start + length
    return out


def beam_tags(placed: list[Placed], beat_len: Fraction) -> list[list[tuple[int, str]]]:
    """Beams per note: notes shorter than a quarter within one beat are joined; level k
    joins neighbours that both have k beams, a lone one gets a hook."""
    tags: list[list[tuple[int, str]]] = [[] for _ in placed]

    def beams(p: Placed) -> int:
        return {8: 1, 16: 2, 32: 3, 64: 4}.get(p.duration, 0)

    groups: list[list[int]] = []
    cur: list[int] = []
    for i, p in enumerate(placed):
        joinable = not p.rest and beams(p) > 0
        same_beat = cur and (p.start // beat_len) == (placed[cur[-1]].start // beat_len)
        adjacent = cur and placed[cur[-1]].start + placed[cur[-1]].length == p.start
        if joinable and same_beat and adjacent:
            cur.append(i)
            continue
        if len(cur) > 1:
            groups.append(cur)
        cur = [i] if joinable else []
    if len(cur) > 1:
        groups.append(cur)
    for g in groups:
        for k, i in enumerate(g):
            tags[i].append((1, "begin" if k == 0 else "end" if k == len(g) - 1 else "continue"))
        for level in range(2, 5):
            runs: list[list[int]] = []
            for k, i in enumerate(g):
                if beams(placed[i]) < level:
                    continue
                if runs and runs[-1][-1] == k - 1:
                    runs[-1].append(k)
                else:
                    runs.append([k])
            for run in runs:
                if len(run) == 1:
                    k = run[0]
                    tags[g[k]].append((level, "forward hook" if k == 0 else "backward hook"))
                    continue
                for j, k in enumerate(run):
                    kind = "begin" if j == 0 else "end" if j == len(run) - 1 else "continue"
                    tags[g[k]].append((level, kind))
    return tags


def _ticks(length: Fraction) -> int:
    return int(round(length * 4 * DIVISIONS))


def _note_xml(
    p: Placed, note: DrumNote | None, voice: int, mapping: Mapping, chord: bool, extra: str
) -> str:
    dur = _ticks(p.length)
    head = ""
    if note is None:
        body = "<rest/>"
        inst = ""
    else:
        body = (
            f"<unpitched><display-step>{note.step}</display-step>"
            f"<display-octave>{note.octave}</display-octave></unpitched>"
        )
        gm = mapping.resolve(note)
        inst = f'<instrument id="P1-I{gm}"/>'
        shape = INSTRUMENTS[gm].head if gm in INSTRUMENTS else "normal"
        if note.notehead in ("x", "circle-x"):
            shape = note.notehead if shape != "normal" else shape
        par = ' parentheses="yes"' if note.ghost else ""
        if shape != "normal" or par:
            head = f"<notehead{par}>{shape}</notehead>"
    xml = "<note>" + ("<chord/>" if chord else "") + body + f"<duration>{dur}</duration>"
    xml += inst + f"<voice>{voice}</voice><type>{TYPES[p.duration]}</type>" + "<dot/>" * p.dots
    if p.tuplet:
        normal = {3: 2, 5: 4, 6: 4, 7: 4, 9: 8}.get(p.tuplet, p.tuplet)
        xml += (
            f"<time-modification><actual-notes>{p.tuplet}</actual-notes>"
            f"<normal-notes>{normal}</normal-notes></time-modification>"
        )
    if note is not None:
        xml += f"<stem>{'up' if voice == 1 else 'down'}</stem>"
    xml += head + extra
    notations = ""
    if note is not None and note.open:
        notations += "<technical><open-string/></technical>"
    if note is not None and note.accent:
        notations += "<articulations><accent/></articulations>"
    if notations:
        xml += f"<notations>{notations}</notations>"
    return xml + "</note>"


def _voice_xml(voice: list[Beat], number: int, cap: Fraction, beat_len: Fraction, mapping) -> str:
    placed = place(voice, cap)
    tags = beam_tags(placed, beat_len)
    out = []
    pos = Fraction(0)
    for p, tag in zip(placed, tags, strict=True):
        if p.start > pos:
            out.append(
                f"<forward><duration>{_ticks(p.start - pos)}</duration>"
                f"<voice>{number}</voice></forward>"
            )
        beam = "".join(f'<beam number="{lv}">{kind}</beam>' for lv, kind in tag)
        if p.rest:
            out.append(_note_xml(p, None, number, mapping, False, ""))
        else:
            notes = sorted(p.notes, key=lambda n: (n.octave, "CDEFGAB".index(n.step)))
            for k, n in enumerate(notes):
                out.append(_note_xml(p, n, number, mapping, k > 0, beam if k == 0 else ""))
        pos = p.start + p.length
    if pos < cap and out:
        out.append(
            f"<forward><duration>{_ticks(cap - pos)}</duration><voice>{number}</voice></forward>"
        )
    return "".join(out)


def beat_length(time: tuple[int, int]) -> Fraction:
    num, den = time
    if den == 8 and num % 3 == 0 and num > 3:  # compound time: dotted quarter beats
        return Fraction(3, 8)
    return Fraction(1, den)


def musicxml(score: DrumScore, mapping: Mapping | None = None) -> str:
    mapping = mapping or Mapping()
    used = sorted(
        {mapping.resolve(n) for m in score.measures for v in m.voices for b in v for n in b.notes}
    )
    decl = "".join(
        f'<score-instrument id="P1-I{g}"><instrument-name>{escape(INSTRUMENTS[g].name)}'
        "</instrument-name></score-instrument>"
        for g in used
    ) + "".join(
        f'<midi-instrument id="P1-I{g}"><midi-channel>10</midi-channel>'
        f"<midi-unpitched>{g + 1}</midi-unpitched></midi-instrument>"
        for g in used
    )
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">',
        '<score-partwise version="4.0">',
    ]
    if score.title:
        out.append(f"<movement-title>{escape(score.title)}</movement-title>")
    out.append(
        '<part-list><score-part id="P1"><part-name>Drumset</part-name>'
        f"<part-abbreviation>Dr.</part-abbreviation>{decl}</score-part></part-list>"
        '<part id="P1">'
    )
    prev_time = None
    for i, m in enumerate(score.measures or [DrumMeasure([[]])]):
        time = m.time or score.time
        cap = capacity(time)
        out.append(f'<measure number="{i + 1}">')
        attrs = ""
        if i == 0:
            attrs += f"<divisions>{DIVISIONS}</divisions><key><fifths>0</fifths></key>"
        if time != prev_time:
            attrs += f"<time><beats>{time[0]}</beats><beat-type>{time[1]}</beat-type></time>"
        if i == 0:
            attrs += (
                "<clef><sign>percussion</sign></clef>"
                "<staff-details><staff-lines>5</staff-lines></staff-details>"
            )
        if attrs:
            out.append(f"<attributes>{attrs}</attributes>")
        if i == 0 and score.tempo:
            out.append(
                '<direction placement="above"><direction-type><metronome>'
                f"<beat-unit>quarter</beat-unit><per-minute>{score.tempo}</per-minute>"
                f'</metronome></direction-type><sound tempo="{score.tempo}"/></direction>'
            )
        prev_time = time
        v1 = m.voices[0] if m.voices else []
        v2 = m.voices[1] if len(m.voices) > 1 else []
        first = _voice_xml(v1, 1, cap, beat_length(time), mapping)
        if not first:
            first = (
                f'<note><rest measure="yes"/><duration>{_ticks(cap)}</duration>'
                "<voice>1</voice></note>"
            )
        out.append(first)
        second = _voice_xml(v2, 2, cap, beat_length(time), mapping)
        if second:
            out.append(f"<backup><duration>{_ticks(cap)}</duration></backup>{second}")
        out.append("</measure>")
    out.append("</part></score-partwise>")
    return "\n".join(out)


# ------------------------------------------------------------------------------ MIDI


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _track(events: list[tuple[int, int, bytes]]) -> bytes:
    """events: (tick, order, message bytes); written with delta times, closed properly."""
    data = bytearray()
    last = 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        data += _vlq(tick - last) + msg
        last = tick
    data += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def _meta(kind: int, payload: bytes) -> bytes:
    return bytes([0xFF, kind]) + _vlq(len(payload)) + payload


def midi(score: DrumScore, mapping: Mapping | None = None) -> bytes:
    """SMF type 1: a tempo/meter track and one drum track on channel 10 (0-based 9)."""
    mapping = mapping or Mapping()
    tempo = max(20, min(400, score.tempo or 120))
    conductor: list[tuple[int, int, bytes]] = [
        (0, 0, _meta(0x03, (score.title or "Drums").encode("utf-8")[:120])),
        (0, 1, _meta(0x51, (60_000_000 // tempo).to_bytes(3, "big"))),
    ]
    drums: list[tuple[int, int, bytes]] = [(0, 0, _meta(0x03, b"Drums"))]
    start = Fraction(0)
    prev_time = None
    for m in score.measures:
        time = m.time or score.time
        cap = capacity(time)
        tick0 = int(round(start * 4 * PPQ))
        if time != prev_time:
            den_pow = max(0, time[1].bit_length() - 1)
            conductor.append((tick0, 2, _meta(0x58, bytes([time[0], den_pow, 24, 8]))))
            prev_time = time
        for voice in m.voices:
            for p in place(voice, cap):
                if p.rest:
                    continue
                on = tick0 + int(round(p.start * 4 * PPQ))
                off = on + max(1, int(round(min(p.length, GATE) * 4 * PPQ)))
                for n in p.notes:
                    key = mapping.resolve(n)
                    vel = VELOCITY["ghost" if n.ghost else "accent" if n.accent else "normal"]
                    drums.append((on, 2, bytes([0x99, key, vel])))
                    drums.append((off, 1, bytes([0x89, key, 0])))
        start += cap
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, PPQ)
    return header + _track(conductor) + _track(drums)
