"""Score recognized MusicXML against ground truth (ported from the piano spike's
evaluate.py): measures are aligned by Needleman-Wunsch on their pitch content, then notes
are matched as multisets per aligned measure (both staves pooled)."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction


def measures_of(score) -> list[dict]:
    from music21 import key, meter

    parts = list(score.parts)
    per_part = [list(p.getElementsByClass("Measure")) for p in parts]
    out = []
    for i in range(max((len(m) for m in per_part), default=0)):
        events = []
        ks = ts = None
        for si, ms in enumerate(per_part):
            if i >= len(ms):
                continue
            m = ms[i]
            for k in m.recurse().getElementsByClass(key.KeySignature):
                ks = k.sharps if ks is None else ks
            for t in m.recurse().getElementsByClass(meter.TimeSignature):
                ts = t.ratioString if ts is None else ts
            for n in m.recurse().notes:
                if n.duration.isGrace:
                    continue
                off = Fraction(n.getOffsetInHierarchy(m)).limit_denominator(64)
                ql = Fraction(n.quarterLength).limit_denominator(64)
                for p in n.pitches:
                    events.append((si, off, p.nameWithOctave, p.midi, ql))
        out.append({"events": events, "ks": ks, "ts": ts})
    return out


def _sim(a: dict, b: dict) -> float:
    ca = Counter(e[3] for e in a["events"])
    cb = Counter(e[3] for e in b["events"])
    return sum((ca & cb).values()) / max(sum(ca.values()), sum(cb.values()), 1)


def align(gt: list[dict], pr: list[dict]) -> list[tuple[int | None, int | None]]:
    G, P, gap = len(gt), len(pr), -0.3
    D = [[0.0] * (P + 1) for _ in range(G + 1)]
    B = [[""] * (P + 1) for _ in range(G + 1)]
    for i in range(1, G + 1):
        D[i][0], B[i][0] = D[i - 1][0] + gap, "u"
    for j in range(1, P + 1):
        D[0][j], B[0][j] = D[0][j - 1] + gap, "l"
    for i in range(1, G + 1):
        for j in range(1, P + 1):
            D[i][j], B[i][j] = max(
                (D[i - 1][j - 1] + _sim(gt[i - 1], pr[j - 1]), "d"),
                (D[i - 1][j] + gap, "u"),
                (D[i][j - 1] + gap, "l"),
            )
    i, j, path = G, P, []
    while i > 0 or j > 0:
        b = B[i][j]
        if b == "d":
            path.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif b == "u":
            path.append((i - 1, None))
            i -= 1
        else:
            path.append((None, j - 1))
            j -= 1
    return path[::-1]


def _inter(a, b) -> int:
    return sum((Counter(a) & Counter(b)).values())


def evaluate(gt: list[dict], pr: list[dict]) -> dict:
    c = Counter()
    for gi, pi in align(gt, pr):
        g = gt[gi]["events"] if gi is not None else []
        p = pr[pi]["events"] if pi is not None else []
        c["gt"] += len(g)
        c["pr"] += len(p)
        c["pitch"] += _inter([e[2] for e in g], [e[2] for e in p])
        c["dur"] += _inter([(e[2], e[4]) for e in g], [(e[2], e[4]) for e in p])
    return {
        "measures_gt": len(gt),
        "measures_pr": len(pr),
        "notes_gt": c["gt"],
        "notes_pr": c["pr"],
        "pitch_recall": round(c["pitch"] / max(c["gt"], 1), 3),
        "pitch_precision": round(c["pitch"] / max(c["pr"], 1), 3),
        "duration_of_matched": round(c["dur"] / max(c["pitch"], 1), 3),
    }
