"""Score recognition against a Guitar Pro file.

    python -m app.omr.evaluate VIDEO_OR_PAGE_DIR GP --track NAME [--from N --to M] [--staff K]

VIDEO_OR_PAGE_DIR is a video (the existing pipeline runs first) or a directory of
line images (page_*.png as written by `app.cli`). Staff K of every line (0 = top) is
the recognized track compared with the GP track. Measures are aligned by recognized
measure number; beats inside a measure are aligned by a DP that maximizes shared notes.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.omr.glyphs import MODEL_PATH, GlyphClassifier
from app.omr.gpif import read_track
from app.omr.model import Beat, Measure, Score
from app.omr.recognize import build_song, number_measures, recognize_lines


def load_images(src: Path) -> list[np.ndarray]:
    if src.is_dir():
        return [cv2.imread(str(p)) for p in sorted(src.glob("page_*.png"))]
    from app.frames import grab_frames
    from app.pipeline import analyze
    from app.region import detect_region

    roi = detect_region(grab_frames(src, 20)).roi
    return [p.image for p in analyze(src, roi) if p.duplicate_of is None]


def _notes(b: Beat) -> frozenset:
    """(string, fret) pairs; a dead note shows only an "x", so its fret is not compared."""
    return frozenset((n.string, "x" if n.dead else n.fret) for n in b.notes)


def _tied(b: Beat) -> dict:
    return {(n.string, "x" if n.dead else n.fret): n.tied for n in b.notes}


def _by_key(b: Beat) -> dict:
    return {(n.string, "x" if n.dead else n.fret): n for n in b.notes}


# technique -> whether it carries a value (bend amount, slide or harmonic kind) that is
# compared too; bend_release is counted with the bend's value
TECHNIQUES = {
    "bend": True,
    "slide": True,
    "slide_in": True,
    "hopo": False,
    "harmonic": True,
    "vibrato": False,
    "palm_mute": False,
    "staccato": False,
}


def _technique(n, name: str):
    v = getattr(n, name)
    if name == "bend" and v is not None:
        return (v, n.bend_release)
    return v or None


def _rhythm(b: Beat) -> tuple:
    return (b.duration, b.dots, b.tuplet or None)


def align(gt: list[Beat], rec: list[Beat]) -> list[tuple[int, int]]:
    """Monotone pairing of gt and rec beats maximizing matched notes (rests match rests)."""

    def sim(g: Beat, r: Beat) -> float:
        if g.rest and r.rest:
            return 1.0
        common = len(_notes(g) & _notes(r))
        if common:
            return common + (0.5 if _notes(g) == _notes(r) else 0.0)
        # same string, different fret: still the same beat position
        same_string = {s for s, _ in _notes(g)} & {s for s, _ in _notes(r)}
        return 0.2 if same_string else 0.0

    n, m = len(gt), len(rec)
    dp = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1, j - 1] + sim(gt[i - 1], rec[j - 1])
            dp[i, j] = max(dp[i - 1, j], dp[i, j - 1], diag)
    pairs = []
    i, j = n, m
    while i and j:
        s = sim(gt[i - 1], rec[j - 1])
        if s > 0 and dp[i, j] == dp[i - 1, j - 1] + s:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif dp[i, j] == dp[i - 1, j]:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _fmt(b: Beat) -> str:
    r = f"{b.duration}{'.' * b.dots}" + (f"/{b.tuplet}" if b.tuplet else "")
    body = "R" if b.rest else "+".join(f"{n.string}:{'~' * n.tied}{n.fret}" for n in b.notes)
    return f"{r}:{body}"


@dataclass
class Report:
    measures: int = 0
    found: int = 0
    notes: int = 0
    notes_hit: int = 0
    rec_notes: int = 0
    beats: int = 0
    grouped: int = 0
    timed: int = 0
    measures_sum_ok: int = 0
    extra_measures: int = 0  # recognized measures with no ground-truth counterpart
    # ties, on notes found in both (same beat, string and fret)
    tie_agree: int = 0
    gt_ties: int = 0
    rec_ties: int = 0
    ties_hit: int = 0
    # per technique, on notes found in both: gt / rec / hit (both marked) / value_ok
    tech: dict = field(default_factory=lambda: {t: Counter() for t in TECHNIQUES})
    fret_errors: Counter = field(default_factory=Counter)
    group_errors: Counter = field(default_factory=Counter)
    time_errors: Counter = field(default_factory=Counter)
    confusions: Counter = field(default_factory=Counter)
    per_measure: list = field(default_factory=list)

    def summary(self) -> dict:
        def pct(a, b):
            return round(100 * a / b, 2) if b else None

        return {
            "measures": self.measures,
            "measure_alignment": pct(self.found, self.measures),
            "fret_recall": pct(self.notes_hit, self.notes),
            "fret_precision": pct(self.notes_hit, self.rec_notes),
            "beat_grouping": pct(self.grouped, self.beats),
            "duration_on_grouped": pct(self.timed, self.grouped),
            "measures_summing": pct(self.measures_sum_ok, self.found),
            "tie_accuracy": pct(self.tie_agree, self.notes_hit),
            "tie_recall": pct(self.ties_hit, self.gt_ties),
            "tie_precision": pct(self.ties_hit, self.rec_ties),
            "techniques": {
                t: {
                    "gt": c["gt"],
                    "rec": c["rec"],
                    "hit": c["hit"],
                    "recall": pct(c["hit"], c["gt"]),
                    "precision": pct(c["hit"], c["rec"]),
                    **({"value_ok": c["value_ok"]} if TECHNIQUES[t] else {}),
                }
                for t, c in self.tech.items()
            },
            "extra_measures": self.extra_measures,
            "counts": {"notes": self.notes, "beats": self.beats, "ties": self.gt_ties},
            "fret_errors": dict(self.fret_errors.most_common()),
            "group_errors": dict(self.group_errors.most_common()),
            "duration_errors": dict(self.time_errors.most_common()),
            "fret_confusions": dict(self.confusions.most_common(12)),
        }


def _rest_measure(m: Measure) -> list[Beat]:
    return m.beats or [Beat(1, 0, None, True, [])]


def _duration_error(g: Beat, r: Beat) -> str:
    if g.tuplet != r.tuplet:
        return "tuplet"
    if g.dots != r.dots and g.duration == r.duration:
        return "dot"
    if {g.duration, r.duration} == {2, 4}:
        return "half/quarter"
    if {g.duration, r.duration} == {1, 2}:
        return "whole/half"
    if g.duration != r.duration:
        return f"value {g.duration}->{r.duration}"
    return "other"


def compare(gt: Score, rec: Score, lo: int, hi: int) -> Report:
    rep = Report()
    by_number: dict[int, Measure] = {}
    for m in rec.measures:
        if m.number is not None and m.number not in by_number:
            by_number[m.number] = m
    for gm in gt.measures:
        if not lo <= gm.number <= hi:
            continue
        rep.measures += 1
        g_beats = _rest_measure(gm)
        rm = by_number.get(gm.number)
        r_beats = rm.beats if rm else []
        if rm:
            rep.found += 1
            total = sum(b.length() for b in r_beats)
            rep.measures_sum_ok += total == rm.capacity()
        pairs = align(g_beats, r_beats)
        matched_g = {i for i, _ in pairs}
        matched_r = {j for _, j in pairs}
        errs = 0
        n_notes = sum(len(b.notes) for b in g_beats)
        rep.notes += n_notes
        rep.rec_notes += sum(len(b.notes) for b in r_beats)
        rep.beats += len(g_beats)
        hit = 0
        for i, j in pairs:
            g, r = g_beats[i], r_beats[j]
            common = _notes(g) & _notes(r)
            hit += len(common)
            g_tied, r_tied = _tied(g), _tied(r)
            g_notes, r_notes = _by_key(g), _by_key(r)
            for key in common:
                for t, c in rep.tech.items():
                    gv, rv = _technique(g_notes[key], t), _technique(r_notes[key], t)
                    c["gt"] += gv is not None
                    c["rec"] += rv is not None
                    c["hit"] += gv is not None and rv is not None
                    c["value_ok"] += gv is not None and gv == rv
                rep.tie_agree += g_tied[key] == r_tied[key]
                rep.gt_ties += g_tied[key]
                rep.rec_ties += r_tied[key]
                rep.ties_hit += g_tied[key] and r_tied[key]
            for s, f in _notes(g) - common:
                rf = [rf for rs, rf in _notes(r) if rs == s]
                if rf:
                    rep.fret_errors["wrong fret"] += 1
                    rep.confusions[f"{f}->{rf[0]}"] += 1
                elif any(rf == f for _, rf in _notes(r)):
                    rep.fret_errors["wrong string"] += 1
                else:
                    rep.fret_errors["missed note in beat"] += 1
            if _notes(g) == _notes(r) and g.rest == r.rest:
                rep.grouped += 1
                if _rhythm(g) == _rhythm(r):
                    rep.timed += 1
                else:
                    errs += 1
                    rep.time_errors[_duration_error(g, r)] += 1
            else:
                errs += 1
                if g.rest != r.rest:
                    rep.group_errors["rest vs note"] += 1
                elif _notes(r) < _notes(g):
                    rep.group_errors["beat missing notes"] += 1
                elif _notes(r) > _notes(g):
                    rep.group_errors["beat has extra notes"] += 1
                else:
                    rep.group_errors["different notes"] += 1
        for i in set(range(len(g_beats))) - matched_g:
            errs += 1
            rep.group_errors["beat not found" if rm else "measure not found"] += 1
            rep.fret_errors["beat not found" if rm else "measure not found"] += len(
                g_beats[i].notes
            )
        extra = len(set(range(len(r_beats))) - matched_r)
        if extra:
            rep.group_errors["extra beat (count)"] += extra
            errs += extra
        rep.notes_hit += hit
        rep.per_measure.append(
            (
                errs,
                gm.number,
                " ".join(map(_fmt, g_beats)),
                " ".join(map(_fmt, r_beats)),
                rm.line if rm else None,
            )
        )
    # phantom measures: recognized inside the window or past the ground truth's end, but
    # absent from it; their notes count against precision
    gt_numbers = {m.number for m in gt.measures}
    last = max(gt_numbers, default=hi)
    for m in rec.measures:
        if m.number in gt_numbers or not (lo <= (m.number or lo) <= hi or (m.number or 0) > last):
            continue
        rep.extra_measures += 1
        rep.rec_notes += sum(len(b.notes) for b in m.beats)
    return rep


def run(
    src: Path,
    gp: Path,
    track: str,
    lo: int,
    hi: int,
    first: int | None,
    show: int,
    model: Path = MODEL_PATH,
    staff: int = 0,
) -> dict:
    t0 = time.time()
    images = load_images(src)
    t1 = time.time()
    clf = GlyphClassifier.load(model)
    pages, strings = recognize_lines(images, clf)
    song = build_song(pages, strings)
    if not 0 <= staff < len(song.tracks):
        raise SystemExit(f"--staff {staff}: the lines have {len(song.tracks)} staves")
    score = song.tracks[staff]
    t2 = time.time()
    gt = read_track(gp, track)
    rep = compare(gt, score, lo, hi)
    out = rep.summary()
    raw = [m for page in pages for m in page[0].measures]
    numbers = number_measures(raw)
    read = [m.number for m in raw]
    out["numbering"] = {
        "measures_recognized": len(raw),
        "ocr_read": sum(n is not None for n in read),
        "ocr_agrees_with_final": sum(a == b for a, b in zip(read, numbers, strict=True)),
        "duplicate_numbers": len(numbers) - len(set(numbers)),
    }
    if first is not None:
        expected = list(range(first, first + len(raw)))
        out["numbering"]["final_matches_sequence"] = sum(
            a == b for a, b in zip(numbers, expected, strict=True)
        )
        out["numbering"]["ocr_correct_vs_sequence"] = sum(
            a == b for a, b in zip(read, expected, strict=True)
        )
    out["seconds"] = {"extract": round(t1 - t0, 1), "recognize": round(t2 - t1, 1)}
    worst = sorted(rep.per_measure, key=lambda t: -t[0])[:show]
    out["worst"] = [
        {"measure": n, "line": ln, "errors": e, "gt": g, "rec": r} for e, n, g, r, ln in worst if e
    ]
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="video file or directory of page_*.png")
    parser.add_argument("gp", type=Path)
    parser.add_argument("--track", required=True)
    parser.add_argument("--from", dest="lo", type=int, default=1)
    parser.add_argument("--to", dest="hi", type=int, default=10**6)
    parser.add_argument("--first", type=int, help="expected number of the first measure shown")
    parser.add_argument("--show", type=int, default=15, help="worst measures to list")
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--staff", type=int, default=0, help="staff of each line (0 = top)")
    args = parser.parse_args(argv)
    out = run(
        args.source,
        args.gp,
        args.track,
        args.lo,
        args.hi,
        args.first,
        args.show,
        args.model,
        args.staff,
    )
    if args.json:
        args.json.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    worst = out.pop("worst")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    for w in worst:
        print(f"m{w['measure']} (line {w['line']}) errors={w['errors']}")
        print(f"   gt : {w['gt']}")
        print(f"   rec: {w['rec']}")


if __name__ == "__main__":
    main()
