"""Regenerate the drum test fixture in tests/data/drums.

Run with an environment that has verovio, cairosvg and pillow (dev-only tools, not
project dependencies) and optionally LilyPond, for example:

    python tests/make_drum_fixture.py [path/to/lilypond]

Pieces are written in a tiny DSL (below) and become:
- pieces.json: the ground truth events of every piece and the systems of its clean page;
- <piece>_clean.png: Verovio, 1920 px page (staff space about 12 px);
- <piece>_deg.jpg: the same, blurred (0.8 px) and saved as JPEG quality 60;
- <piece>_1280.jpg: Verovio, 1280 px page (staff space about 10 px), blurred, JPEG 60;
- <piece>_lily.png: LilyPond 2.24 drummode, 216 dpi (staff space about 10.5 px);
- strip.png + strip.json: some pieces as one long line (the Guitar Pro strip of the
  synthetic step-scrolling video), with its bar lines.
Pages are cropped to their ink and stored in grey to keep the fixture small.

The DSL: per measure a (hands, feet) pair of space separated tokens DUR:INST[+INST],
DUR:r (a rest) or DUR:R (a rest that is not drawn, as Guitar Pro leaves them out), DUR one
of w h q e s ('.' = dotted). Units in the events are 16ths.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg
import numpy as np
import verovio
from PIL import Image, ImageFilter

OUT = Path(__file__).resolve().parent / "data" / "drums"

# name: (GM, display step, octave, notehead, lily name, lily long name)
INST = {
    "cr": (49, "A", 5, "x", "cymc", "crashcymbal"),
    "hh": (42, "G", 5, "x", "hh", "hihat"),
    "ohh": (46, "G", 5, "x", "hho", "openhihat"),  # x + 'o' above
    "rd": (51, "F", 5, "x", "cymr", "ridecymbal"),
    "t1": (50, "E", 5, "normal", "tomh", "hightom"),
    "t2": (47, "D", 5, "normal", "tommh", "highmidtom"),
    "sn": (38, "C", 5, "normal", "sn", "snare"),
    "gs": (38, "C", 5, "normal", "sn", "snare"),  # ghost: parenthesized
    "ft": (43, "A", 4, "normal", "tomfh", "highfloortom"),
    "bd": (36, "F", 4, "normal", "bd", "bassdrum"),
    "ph": (44, "D", 4, "x", "hhp", "pedalhihat"),
}
STEP = {k: "CDEFGAB".index(v[1]) + 7 * v[2] - (2 + 7 * 4) for k, v in INST.items()}
UNITS = {"w": 16, "h": 8, "q": 4, "e": 2, "s": 1}
TYPES = {16: ("whole", 0), 8: ("half", 0), 4: ("quarter", 0), 2: ("eighth", 0), 1: ("16th", 0)}
TYPES |= {12: ("half", 1), 6: ("quarter", 1), 3: ("eighth", 1), 24: ("whole", 1)}
LILY = {16: "1", 8: "2", 4: "4", 2: "8", 1: "16", 12: "2.", 6: "4.", 3: "8.", 24: "1."}


def rep(token: str, n: int) -> str:
    return " ".join([token] * n)


ROCK = "e:hh e:hh e:hh+sn e:hh e:hh e:hh e:hh+sn e:hh"
PIECES: dict[str, dict] = {
    "rock8": {
        "time": (4, 4),
        "measures": [
            ("e:cr" + ROCK[4:], "q:bd q:r e:bd e:bd q:r"),
            (ROCK, "q:bd q:r e:bd e:bd q:r"),
            (ROCK, "q:bd q:r e:bd e:bd q:r"),
            ("e:hh e:hh e:hh+sn e:hh e:hh e:hh s:sn s:sn s:sn s:sn", "q:bd q:r e:bd e:bd q:r"),
            ("e:cr" + ROCK[4:], "q:bd q:r q:bd q:r"),
            (ROCK, "e:bd e:bd q:r e:bd e:bd q:r"),
            (ROCK, "q:bd q:r e:bd e:bd q:r"),
            ("q:cr+sn q:r h:r", "q:bd h.:r"),
        ],
    },
    "hh16": {
        "time": (4, 4),
        "measures": [
            (
                rep("s:hh", 4) + " s:hh+sn " + rep("s:hh", 7) + " s:hh+sn " + rep("s:hh", 3),
                "e:bd s:r s:bd q:r e.:r s:bd q:r",
            ),
        ]
        * 3
        + [
            (
                rep("s:hh", 4)
                + " s:hh+sn "
                + rep("s:hh", 3)
                + " s:sn s:sn s:t1 s:t1 s:t2 s:t2 s:ft s:ft",
                "e:bd s:r s:bd q:r q:bd q:r",
            ),
        ],
    },
    "shuffle": {
        "time": (12, 8),
        "measures": [
            ("q:rd e:rd q:rd+sn e:rd q:rd e:rd q:rd+sn e:rd", "q:bd e:r q.:r q:bd e:bd q.:r"),
        ]
        * 3
        + [
            ("q:rd e:rd q:rd+sn e:rd e:sn e:sn e:sn e:t1 e:t2 e:ft", "q:bd e:r q.:r q.:bd q.:r"),
        ],
    },
    "fills": {
        "time": (4, 4),
        "measures": [
            (ROCK, "q:bd q:r q:bd q:r"),
            ("e:hh e:hh e:hh+sn e:hh s:sn s:sn s:t1 s:t1 s:t2 s:t2 s:ft s:ft", "q:bd q:r q:bd q:r"),
            ("e:cr" + ROCK[4:], "q:bd q:r e:bd e:bd q:r"),
            ("e:t1 s:t1 s:t1 e:t2 s:t2 s:t2 e:ft s:ft s:ft q:sn", "q:bd q:bd q:bd q:bd"),
            ("q:cr q:r h:r", "q:bd q:r h:r"),
        ],
    },
    "ride": {
        "time": (4, 4),
        "measures": [
            ("q:cr q:rd+sn q:rd q:rd+sn", "q:bd q:ph q:bd q:ph"),
            ("q:rd e:rd e:rd q:rd+sn q:rd", "q:bd q:ph e:bd e:bd q:ph"),
            ("q:rd q:rd+sn e:rd e:rd q:rd+sn", "q:bd q:ph q:bd q:ph"),
            ("q:cr+sn q:rd+sn q:cr+sn q:rd+sn", "q:bd q:ph q:bd q:ph"),
            ("h:cr h:r", "h:bd h:r"),
        ],
    },
    "openhh": {
        "time": (4, 4),
        "measures": [
            ("e:hh e:hh e:hh+sn e:hh e:hh e:hh e:hh+sn e:ohh", "q:bd q:r e:bd e:bd q:r"),
            ("e:hh e:hh e:hh+sn e:hh e:hh e:ohh e:hh+sn e:hh", "q:bd q:ph q:bd q:ph"),
            ("e:hh e:ohh e:hh+sn e:ohh e:hh e:ohh e:hh+sn e:ohh", "q:bd q:r q:bd q:r"),
            ("q:ohh q:sn q:ohh q:sn", "e:bd e:ph q:ph e:bd e:ph q:ph"),
        ],
    },
    "ghost": {
        "time": (4, 4),
        "measures": [
            ("s:hh s:gs e:hh s:hh+sn s:gs s:hh s:gs e:hh s:hh+gs s:hh e:hh+sn s:hh s:gs", feet)
            for feet in (
                "e:bd s:r s:bd h.:r",
                "e:bd s:r s:bd q:r e:bd e:bd q:r",
                "e:bd s:r s:bd h.:r",
            )
        ],
    },
    "rests": {
        "time": (4, 4),
        "measures": [
            ("q:sn q:r q:sn q:r", "w:r"),
            ("e:r e:hh e:r e:hh e:r e:hh e:r e:hh", "q:bd q:bd q:bd q:bd"),
            ("q.:sn e:sn h:r", "h:bd h:bd"),
            ("e.:sn s:sn q:r e.:sn s:sn q:r", "q:r q:bd q:r q:bd"),
            ("h:cr h:r", "w:bd"),
        ],
    },
    # Guitar Pro's single-voice layout: the kick shares the hands' up stems and the
    # pedal hi-hat voice has no rests (its gaps are invisible <forward>s)
    "gpsingle": {
        "time": (4, 4),
        "gp": True,
        "measures": [
            ("e:hh+bd e:hh e:hh+sn e:hh e:hh+bd e:hh+bd e:hh+sn e:hh", "q:r q:ph q:r q:ph"),
            ("e:hh+bd e:hh e:hh+sn e:hh+bd e:hh e:hh+bd e:hh+sn e:hh", rep("e:r e:ph", 4)),
            ("q:cr+bd q:sn q:bd q:sn", "e:r e:ph q:r e:r e:ph q:r"),
            ("e:hh+bd e:hh e:hh+sn e:hh s:sn s:sn s:t1 s:t1 s:t2 s:t2 s:ft s:ft", "h:r q:ph q:r"),
            # the hands start on beat 2 without a rest, the kick pair is on down stems
            ("q:R q:cr+sn e:hh+bd e:hh e:hh+sn e:hh+bd", "e:bd+ph e:bd h.:R"),
        ],
    },
}
ACCURACY = ["rock8", "hh16", "shuffle", "fills", "ride", "openhh", "ghost", "rests"]
STRIP = ["rock8", "fills"]  # the step-scrolling video's content, as one line


def parse_voice(text: str) -> list[tuple[int, list[str]]]:
    out = []
    for tok in text.split():
        d, inst = tok.split(":")
        dur = UNITS[d[0]] * (3 if d.endswith(".") else 2) // 2
        out.append((dur, [] if inst in ("r", "R") else inst.split("+"), inst == "R"))
    return out


def events(piece: dict) -> list[list]:
    """[measure, voice, onset16, dur16, instrument or 'rest']"""
    num, den = piece["time"]
    cap = num * 16 // den
    ev = []
    for mi, pair in enumerate(piece["measures"]):
        for vi, text in enumerate(pair, 1):
            t = 0
            for dur, insts, _ in parse_voice(text):
                for i in insts or ["rest"]:
                    ev.append([mi, vi, t, dur, i])
                t += dur
            assert t == cap, (mi, vi, t, cap)
    return ev


def beams(voice: list, beat: int) -> list[list[tuple[int, str]]]:
    """Beam tags per note: notes shorter than a quarter within one beat are joined."""
    tags: list[list[tuple[int, str]]] = [[] for _ in voice]
    t, groups, cur, cur_beat = 0, [], [], None
    for i, (dur, insts, _) in enumerate(voice):
        b = t // beat
        if insts and dur < 4 and (t + dur - 1) // beat == b:
            if cur and cur_beat == b and cur[-1] == i - 1:
                cur.append(i)
            else:
                if len(cur) > 1:
                    groups.append(cur)
                cur, cur_beat = [i], b
        else:
            if len(cur) > 1:
                groups.append(cur)
            cur = []
        t += dur
    if len(cur) > 1:
        groups.append(cur)
    for g in groups:
        for k, i in enumerate(g):
            tags[i].append((1, "begin" if k == 0 else "end" if k == len(g) - 1 else "continue"))
        runs: list[list[int]] = []
        for i in g:
            if voice[i][0] == 1:
                if runs and runs[-1][-1] == i - 1:
                    runs[-1].append(i)
                else:
                    runs.append([i])
        for run in runs:
            if len(run) == 1:
                tags[run[0]].append((2, "backward hook" if run[0] != g[0] else "forward hook"))
            else:
                for k, i in enumerate(run):
                    kind = "begin" if k == 0 else "end" if k == len(run) - 1 else "continue"
                    tags[i].append((2, kind))
    return tags


def musicxml(piece: dict) -> str:
    num, den = piece["time"]
    beat = 6 if den == 8 else 4
    cap = num * 16 // den
    used = sorted({e[4] for e in events(piece) if e[4] != "rest"}, key=lambda i: INST[i][0])
    ids = {i: f"P1-I{INST[i][0]}" + ("o" if i == "ohh" else "") for i in used}
    decl, seen = "", set()
    for i in used:
        if ids[i] not in seen:
            seen.add(ids[i])
            decl += (
                f'<score-instrument id="{ids[i]}"><instrument-name>{INST[i][5]}'
                "</instrument-name></score-instrument>"
            )
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<score-partwise version="4.0"><part-list><score-part id="P1">',
        f'<part-name>Drumset</part-name>{decl}</score-part></part-list><part id="P1">',
    ]
    for mi, (hands, feet) in enumerate(piece["measures"]):
        out.append(f'<measure number="{mi + 1}">')
        if mi == 0:
            out.append(
                f"<attributes><divisions>4</divisions><key><fifths>0</fifths></key>"
                f"<time><beats>{num}</beats><beat-type>{den}</beat-type></time>"
                "<clef><sign>percussion</sign></clef></attributes>"
            )
        for vi, text in enumerate((hands, feet), 1):
            if vi == 2:
                out.append(f"<backup><duration>{cap}</duration></backup>")
            voice = parse_voice(text)
            for (dur, insts, hidden), bt in zip(voice, beams(voice, beat), strict=True):
                typ, dots = TYPES[dur]
                if not insts:
                    if hidden or (vi == 2 and piece.get("gp")):
                        out.append(
                            f"<forward><duration>{dur}</duration><voice>{vi}</voice></forward>"
                        )
                    elif dur == cap:
                        out.append(
                            f'<note><rest measure="yes"/><duration>{dur}</duration>'
                            f"<voice>{vi}</voice></note>"
                        )
                    else:
                        out.append(
                            f"<note><rest/><duration>{dur}</duration><voice>{vi}</voice>"
                            f"<type>{typ}</type>{'<dot/>' * dots}</note>"
                        )
                    continue
                for k, i in enumerate(sorted(insts, key=lambda i: STEP[i])):
                    gm, step, octave, head, _, _ = INST[i]
                    xml = "<note>" + ("<chord/>" if k else "")
                    xml += (
                        f"<unpitched><display-step>{step}</display-step>"
                        f"<display-octave>{octave}</display-octave></unpitched>"
                        f'<duration>{dur}</duration><instrument id="{ids[i]}"/>'
                        f"<voice>{vi}</voice><type>{typ}</type>{'<dot/>' * dots}"
                        f"<stem>{'up' if vi == 1 else 'down'}</stem>"
                    )
                    if head == "x" or i == "gs":
                        par = ' parentheses="yes"' if i == "gs" else ""
                        xml += f"<notehead{par}>{head}</notehead>"
                    if k == 0:
                        xml += "".join(f'<beam number="{lv}">{v}</beam>' for lv, v in bt)
                    if i == "ohh":  # Verovio draws <open-string/> as the "o", not <open/>
                        xml += "<notations><technical><open-string/></technical></notations>"
                    out.append(xml + "</note>")
        out.append("</measure>")
    out.append("</part></score-partwise>")
    return "\n".join(out)


def lily(piece: dict) -> str:
    num, den = piece["time"]
    table = "\n".join(
        f"    ({v[5]} {'cross' if v[3] == 'x' else 'default'} "
        f"{'open' if k == 'ohh' else '#f'} {STEP[k] - 4})"
        for k, v in INST.items()
        if k != "gs"
    )

    def voice(idx: int) -> str:
        toks = []
        for pair in piece["measures"]:
            for dur, insts, _ in parse_voice(pair[idx]):
                if not insts:
                    toks.append("r" + LILY[dur])
                    continue
                names = [("\\parenthesize " if i == "gs" else "") + INST[i][4] for i in insts]
                one = "<" + " ".join(names) + ">" if len(names) > 1 else names[0]
                toks.append(one + LILY[dur])
            toks.append("|")
        return " ".join(toks)

    return f"""\\version "2.24.4"
#(define mydrums '(
{table}
    ))
#(set-global-staff-size 17)
\\paper {{ paper-width = 225.8\\mm paper-height = 127\\mm top-margin = 6\\mm
  bottom-margin = 6\\mm left-margin = 10\\mm right-margin = 8\\mm
  print-page-number = ##f tagline = ##f oddHeaderMarkup = ##f evenHeaderMarkup = ##f }}
\\header {{ tagline = ##f }}
\\new DrumStaff \\with {{ drumStyleTable = #(alist->hash-table mydrums) instrumentName = "" }}
\\drummode {{ \\time {num}/{den}
  << \\new DrumVoice {{ \\voiceOne {voice(0)} }}
     \\new DrumVoice {{ \\voiceTwo {voice(1)} }} >> }}
"""


def toolkit(width: int, scale: int, breaks: str = "auto", height: int | None = None):
    tk = verovio.toolkit()
    tk.setOptions(
        {
            "pageWidth": int(width * 100 / scale),
            "pageHeight": int((height or width * 9 // 16) * 100 / scale),
            "scale": scale,
            "adjustPageHeight": False,
            "adjustPageWidth": breaks == "none",
            "breaks": breaks,
            "header": "none",
            "footer": "none",
            "pageMarginTop": 60,
            "pageMarginBottom": 60,
            "pageMarginLeft": 100,
            "pageMarginRight": 100,
        }
    )
    return tk


def render(xml: str, width: int, scale: int, breaks: str = "auto") -> tuple[Image.Image, list]:
    """The piece's single page and the measure count of each of its systems."""
    tk = toolkit(width, scale, breaks)
    tk.loadData(xml)
    assert tk.getPageCount() == 1, "a piece must fit on one page"
    svg = tk.renderToSVG(1)
    png = cairosvg.svg2png(
        bytestring=svg.encode(),
        output_width=None if breaks == "none" else width,
        background_color="white",
    )
    root = ET.fromstring(svg)
    counts = [
        sum(1 for m in g.iter() if "measure" in (m.get("class") or "").split())
        for g in root.iter()
        if "system" in (g.get("class") or "").split()
    ]
    return Image.open(io.BytesIO(png)).convert("L"), counts


def crop(img: Image.Image, pad: int = 24) -> tuple[Image.Image, int]:
    """Cut to the ink, keeping `pad` px of paper; also returns the top row cut away."""
    a = np.asarray(img)
    rows = np.flatnonzero((a < 200).any(axis=1))
    cols = np.flatnonzero((a < 200).any(axis=0))
    y0, y1 = max(0, rows[0] - pad), min(a.shape[0], rows[-1] + pad + 1)
    x0, x1 = max(0, cols[0] - pad), min(a.shape[1], cols[-1] + pad + 1)
    return img.crop((x0, y0, x1, y1)), y0


def degrade(img: Image.Image, path: Path) -> None:
    img.filter(ImageFilter.GaussianBlur(0.8)).save(path, quality=60)


def systems(img: Image.Image, counts: list[int]) -> list[dict]:
    """Ink rows of each system (the widest blank gaps split them) and its measures."""
    a = np.asarray(img)
    rows = np.flatnonzero((a < 160).any(axis=1))
    gaps = np.diff(rows)
    cuts = sorted(np.argsort(gaps)[::-1][: len(counts) - 1])
    starts = [rows[0], *(rows[c + 1] for c in cuts)]
    ends = [*(rows[c] for c in cuts), rows[-1]]
    return [
        {"y0": int(a_), "y1": int(b_), "measures": n}
        for a_, b_, n in zip(starts, ends, counts, strict=True)
    ]


def bar_lines(img: Image.Image) -> tuple[list[int], list[int]]:
    """Staff line rows and bar line columns of a one-line strip."""
    a = np.asarray(img) < 128
    cover = a.mean(axis=1)
    rows = np.flatnonzero(cover > 0.5)
    lines = [int(g.mean()) for g in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)]
    assert len(lines) == 5, lines
    band = a[lines[0] : lines[-1] + 1]
    cols = np.flatnonzero(band.mean(axis=0) >= 0.95)
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > 12) + 1)
    return lines, [int(g[0]) for g in groups]


def main(lilypond: str | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta: dict = {"pieces": {}}
    for name, piece in PIECES.items():
        xml = musicxml(piece)
        clean, counts = render(xml, 1920, 70)
        clean, _ = crop(clean)
        clean.save(OUT / f"{name}_clean.png", optimize=True)
        degrade(clean, OUT / f"{name}_deg.jpg")
        small, _ = render(xml, 1280, 60)
        degrade(crop(small)[0], OUT / f"{name}_1280.jpg")
        entry = {
            "time": list(piece["time"]),
            "measures": len(piece["measures"]),
            "events": events(piece),
            "systems": systems(clean, counts),
            "gp": bool(piece.get("gp")),
        }
        if lilypond and not piece.get("gp"):
            with tempfile.TemporaryDirectory() as tmp:
                ly = Path(tmp) / f"{name}.ly"
                ly.write_text(lily(piece))
                subprocess.run(
                    [lilypond, "-dresolution=216", "--png", "-o", str(Path(tmp) / name), str(ly)],
                    check=True,
                    capture_output=True,
                )
                page = Image.open(Path(tmp) / f"{name}.png").convert("L")
                crop(page)[0].save(OUT / f"{name}_lily.png", optimize=True)
            entry["lily"] = True
        meta["pieces"][name] = entry
        print(name, len(piece["measures"]), "measures", counts, clean.size)
    strip_piece = {
        "time": (4, 4),
        "measures": [m for p in STRIP for m in PIECES[p]["measures"]],
    }
    img, counts = render(musicxml(strip_piece), 8000, 70, breaks="none")
    img, _ = crop(img, pad=40)
    img.save(OUT / "strip.png", optimize=True)
    lines, bars = bar_lines(img)
    assert len(bars) == len(strip_piece["measures"]), (len(bars), counts)
    (OUT / "strip.json").write_text(
        json.dumps({"pieces": STRIP, "lines": lines, "bars": bars, "events": events(strip_piece)})
    )
    meta["accuracy"] = ACCURACY
    text = json.dumps(meta, indent=None, separators=(",", ":"))
    (OUT / "pieces.json").write_text(re.sub(r'(,"[a-z0-9]+":\{)', r"\n\1", text) + "\n")
    print("strip", img.size, "bars", bars)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
