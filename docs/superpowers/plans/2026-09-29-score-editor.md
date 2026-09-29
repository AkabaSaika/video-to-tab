# Score Editor and .gp Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After page review, recognize the tab into a Score, then let the user preview it with alphaTab against the source image, correct it beat by beat (the edits autosave), and export a Guitar Pro 7/8 `.gp` file.

**Architecture:**
- **Backend:** recognizes in the background (`POST /recognize`) and stores `score.json`; the frontend reads and saves it through `GET`/`PUT /score`.
  - Measures are padded so that the numbers match the source score.
  - Jobs survive restarts (reloaded from `state.json`).
- **Frontend:** everything runs in the browser.
  - Pure libraries: `tuning`, `alphatex` (Score → alphaTex), `scoreEdit` (immutable edits) and `source` (which page image a measure came from).
  - Components: `TabRenderer` (alphaTab rendering, flag overlays, clicks, `.gp` export), `BeatEditor` (the editing panel with the source crop) and `ScoreView` (the page).

**Tech Stack:** FastAPI, Python 3.12, pytest; Vue 3.5, Vite 7, Vitest 3, and `@coderline/alphatab` 1.8.4 (exact).

**Spec:** `docs/superpowers/specs/2026-09-29-score-editor-design.md`

## Global Constraints

- The only new dependency is `@coderline/alphatab`, pinned to exactly `1.8.4`, as a frontend runtime dependency. Do not add `@coderline/alphatab-vite`, Playwright or any other package.
- String numbering: in the Score, 0 = lowest string; in alphaTex, 1 = highest string. Convert with `tex_string = strings − string`.
- Every user-facing message is in Chinese.
- Deliberately out of scope:
  - playback
  - technique editing
  - multiple voices
  - reading tempo or time signature (always 4/4)
  - keyboard shortcuts
- Backend commands run from `backend/` via `uv run …`, frontend commands from `frontend/` via `npm …`.
- ruff check and format must be clean (line length 100), including `packaging/`. Test output has zero warnings.

## Decisions made while prototyping (they refine the spec)

1. **No alphaTab Vite plugin.** `@coderline/alphatab/vite` is broken in 1.8.4: it imports a missing file and says the plugin moved to another package. The editor instead:
   - imports Bravura via `?url` into `core.smuflFontSources`;
   - sets `useWorkers: false`, which is enough without playback;
   - sets `ScrollMode.Off`, because otherwise alphaTab scrolls to the top after every edit.
2. **Measure numbering matches the source score.** This was the user's decision. After recognition, `pad_numbers` inserts whole-rest measures so that `measures[i].number == i + 1`, but only when the recognized numbers are strictly increasing:
   - measures before the first recognized one get `line = -1` and confidence 1, so they are not flagged;
   - measures missing between recognized ones get `line = -1` and confidence 0, so they are flagged.
3. **"确认无误" also clears the measure flag** when the measure's durations fill it exactly. Otherwise a beat inside a flagged measure could never be cleared.
4. **Validation split.** `Score.from_dict` only checks types. The 0–30 fret range is enforced in `scoreEdit.setFret` and in the UI, because recognition itself can produce a fret such as 40, which the user needs to be able to see and correct.
5. **The job records the recognized page files** (`score_files`) as well as their order (`score_order`). A later re-analysis deletes those files, so the editor then shows "原图已更新，请重新识谱以对照" instead of silently showing a different page.

## Review Focus

These are the inputs most likely to hurt a user that the evaluation sample does not exercise. Each is pinned by a test in the task that owns the code.

1. **Program closed or restarted while recognizing.** The job must come back as `failed` with "程序重启，处理被中断，请重试", and any saved `score.json` must be kept. → Task 2, `test_restart_restores_jobs_and_fails_interrupted_ones`.
2. **A malformed or interrupted save.** `PUT /score` with bad data returns 422 with a Chinese message and leaves the previous score intact, as does a write that fails partway. → Task 2, `test_put_score_validates_and_writes_atomically` and `test_failed_atomic_write_keeps_old_score`.
3. **Pages without any tab sent to recognition.** The job must fail with "没有识别到谱表" instead of producing an empty editor. → Task 2, `test_recognize_without_staff_fails_in_chinese`.
4. **Measures the recognizer missed in the middle of the piece.** They must appear as flagged rest measures, and the numbering after them must stay aligned with the source. → Task 1, `test_pad_numbers_fills_gaps_with_flagged_rests`.
5. **Re-analyzing the region after recognizing.** The editor must not show a crop from a different page. → Task 2, `test_recognize_records_page_files_that_reanalysis_replaces`; Task 3, the `source.test.js` case "uses the file recorded at recognition, not the current page list".

## Prototype evidence

The prototype ran end to end on bilibili BV1yBcEeXEVn in headless Chromium: upload, region, analysis, then 识谱. It produced 148 measures (1–12 padded).
- **Export with no edits:** compared with the ground truth over measures 13–148, it scores alignment 100, fret recall 99.92, precision 99.77, grouping 99.76 and duration 99.88, which is identical to recognition alone.
- **Export after one edit** (measure 60, beat 7: fret 40 → 10): fret recall 100 and grouping 99.88.
- **Other checks:**
  - a reload with `#job=<id>` restores the editor;
  - a restart restores the job;
  - the frozen Linux build serves the editor and exports.

The acceptance scripts in `/tmp/vtt/accept/` reproduce the numbers without a browser.

## File Structure

```
backend/app/omr/model.py          # Task 1: Score.title, from_dict validation, pad_numbers
backend/app/omr/recognize.py      # Task 1: progress callback for recognize_images
backend/app/jobs.py               # Task 2: new statuses/fields, atomic writes, reload, recent()
backend/app/workflow.py           # Task 2: page_images, recognize, save_score
backend/app/main.py               # Task 2: /recognize, GET/PUT /score, GET /api/jobs
backend/tests/test_omr_model.py   # Task 1 (replaced)
backend/tests/test_score_api.py   # Task 2 (new)
frontend/package.json, package-lock.json   # Task 3: @coderline/alphatab 1.8.4
frontend/src/lib/{tuning,alphatex,scoreEdit,source}.js + *.test.js, gpExport.test.js  # Task 3
frontend/src/components/{TabRenderer,BeatEditor}.vue, src/views/ScoreView.vue          # Task 4
frontend/src/{App.vue,api.js}, src/views/{InputView,ReviewView}.vue, vite.config.js    # Task 4 (replaced)
packaging/build.py, README.md     # Task 5
```

**Expected test counts** (backend pytest: passed / deselected; with `data/tabs` present, the GP test runs instead of being skipped):

| After task | Backend | Frontend |
|---|---|---|
| 1 | 113 passed, 1 deselected | — |
| 2 | 124 passed, 1 deselected | — |
| 3 | — | 29 passed |
| 4 | — | 29 passed, and `npm run build` succeeds |

---

### Task 1: Score model: title, validation and measure padding

**Files:**
- Modify (replace whole file): `backend/app/omr/model.py`, `backend/app/omr/recognize.py`, `backend/tests/test_omr_model.py`

**Interfaces:**
- Produces:
  - `Score.title: str = ""`.
  - `Score.from_dict(d)`: fills missing fields with defaults. On a wrong type it raises a `ValueError` with a Chinese message that names the location.
  - `pad_numbers(score) -> Score`: pads measures with whole rests, as described in Decision 2. Padded measures have `line = -1`; leading ones have confidence 1 and gap ones confidence 0. A score whose numbers are not strictly increasing is returned unchanged.
  - `recognize_images(images, clf=None, progress=None)`: `progress(frac)` is called once per line.

- [ ] **Step 1: Replace `backend/tests/test_omr_model.py` with the new tests (RED)**

Replace `backend/tests/test_omr_model.py`:

```python
import re
from pathlib import Path

import pytest

from app.omr.model import Beat, Measure, Note, Score

GP = Path(__file__).parents[2] / "data" / "tabs" / "[7弦]AveMujica+KiLLKiSS.gp"


def test_score_round_trips_through_dict():
    score = Score(7, [35], 120, [Measure(5, (4, 4), [Beat(8, 0, None, False, [Note(0, 3)])])])
    assert Score.from_dict(score.to_dict()) == score


@pytest.mark.skipif(not GP.exists(), reason="ground-truth file not available")
def test_gpif_reads_known_measures():
    from app.omr.gpif import read_track

    score = read_track(GP, "Guitar Mutsumi")
    assert score.strings == 7 and score.tuning[0] == 33
    m14 = score.measures[13]
    assert [b.duration for b in m14.beats] == [4, 8, 4, 8, 4]
    assert {(n.string, n.fret) for n in m14.beats[0].notes} == {(0, 7), (1, 7)}
    assert all(sum(b.length() for b in m.beats) in (0, 1) for m in score.measures)


def test_unknown_track_name_is_a_clear_error(tmp_path):
    import zipfile

    from app.omr.gpif import read_track

    gp = tmp_path / "t.gp"
    with zipfile.ZipFile(gp, "w") as z:
        z.writestr(
            "Content/score.gpif",
            "<GPIF><Tracks><Track id='0'><Name>Lead</Name></Track>"
            "</Tracks><MasterBars/><Bars/><Voices/><Beats/><Notes/><Rhythms/></GPIF>",
        )
    with pytest.raises(ValueError, match="Lead"):
        read_track(gp, "Bass")


def test_score_title_round_trips_and_defaults():
    assert Score.from_dict({}).title == ""
    assert Score.from_dict({}) == Score()
    score = Score(6, [40, 45, 50, 55, 59, 64], None, [], "My Song")
    assert Score.from_dict(score.to_dict()) == score


def test_from_dict_fills_missing_fields_with_defaults():
    score = Score.from_dict({"measures": [{"beats": [{"notes": [{"string": 2, "fret": 5}]}]}]})
    beat = score.measures[0].beats[0]
    assert beat.duration == 4 and beat.confidence == 1.0 and not beat.rest
    assert beat.notes == [Note(2, 5)]
    assert score.measures[0].time == (4, 4)


@pytest.mark.parametrize(
    ("data", "where"),
    [
        ([], "乐谱"),
        ({"strings": "7"}, "strings"),
        ({"strings": True}, "strings"),
        ({"tuning": [40, "A"]}, "tuning"),
        ({"title": 3}, "title"),
        ({"measures": {}}, "measures"),
        ({"measures": [{"time": [4]}]}, "measures[0].time"),
        ({"measures": [{"beats": [{"duration": 4.5}]}]}, "measures[0].beats[0].duration"),
        ({"measures": [{"beats": [{"rest": 1}]}]}, "measures[0].beats[0].rest"),
        ({"measures": [{"beats": [{"notes": [{"fret": None}]}]}]}, "notes[0].fret"),
        ({"measures": [{"beats": [{"notes": [{"confidence": "x"}]}]}]}, "confidence"),
    ],
)
def test_from_dict_rejects_wrong_types(data, where):
    with pytest.raises(ValueError, match=re.escape(where)):
        Score.from_dict(data)


def _numbered(*numbers):
    return Score(
        7, [], None, [Measure(n, (4, 4), [Beat(4, notes=[Note(0, n)])], line=0) for n in numbers]
    )


def test_pad_numbers_adds_unflagged_leading_rests():
    from app.omr.model import pad_numbers

    score = _numbered(3, 4)
    padded = pad_numbers(score)
    assert [m.number for m in padded.measures] == [1, 2, 3, 4]
    for m in padded.measures[:2]:
        assert m.line == -1 and m.confidence == 1.0
        assert [(b.duration, b.rest, b.notes) for b in m.beats] == [(1, True, [])]
    assert padded.measures[2:] == score.measures
    assert [m.number for m in score.measures] == [3, 4]  # input untouched


def test_pad_numbers_fills_gaps_with_flagged_rests():
    from app.omr.model import pad_numbers

    padded = pad_numbers(_numbered(1, 2, 5))
    assert [m.number for m in padded.measures] == [1, 2, 3, 4, 5]
    assert [(m.line, m.confidence) for m in padded.measures[2:4]] == [(-1, 0.0), (-1, 0.0)]
    assert padded.measures[4].beats[0].notes == [Note(0, 5)]


def test_pad_numbers_leaves_non_increasing_numbers_alone():
    from app.omr.model import pad_numbers

    for numbers in [(3, 3, 4), (5, 4), (2, None, 4), (0, 1)]:
        score = _numbered(*numbers)
        assert pad_numbers(score) == score


def test_pad_numbers_on_empty_score():
    from app.omr.model import pad_numbers

    assert pad_numbers(Score()) == Score()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_omr_model.py -v`
Expected: FAIL. The new tests fail with `ImportError: cannot import name 'pad_numbers'`, or with assertion errors on `title` and `from_dict`.

- [ ] **Step 3: Replace the implementation files**

Replace `backend/app/omr/model.py`:

```python
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
```

Replace `backend/app/omr/recognize.py`:

```python
"""Per-line recognition: staff, bars, fret numbers, rests, beats and measure numbers.

Everything is measured in units of the staff line spacing `s`, so the same rules apply
at any resolution and to any tab software.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.omr import solve
from app.omr.glyphs import (
    DIGITS,
    Blob,
    GlyphClassifier,
    components,
    default_classifier,
    gray_of,
    merge_pieces,
    otsu_ink,
    staff_ink,
)
from app.omr.model import STANDARD_TUNINGS, Beat, Measure, Note, Score
from app.omr.rhythm import BeatMarks, read_rhythm, stem_positions
from app.omr.solve import BeatEvidence
from app.region import Staff, detect_staves
from app.stitch import BAR_COVERAGE, BAR_MERGE_GAP, INK_LEVEL

MIN_DIGIT_CONF = 0.4
SMALL_DIGIT = 0.72  # digits smaller than this fraction of the typical height are annotations
HIDDEN_STEM = 0.95  # min stem length (in s) for a beat without a number
STRING_TOL = 0.33  # max distance (in s) from a digit's center to its string line


@dataclass
class Glyph:
    blob: Blob
    label: str
    conf: float


@dataclass
class Fret:
    x: float  # center
    y: float
    w: int
    h: int
    string: int
    fret: int
    conf: float
    circled: bool = False
    dead: bool = False


@dataclass
class LineResult:
    staff: Staff
    bars: list[int]
    measures: list[RawMeasure]
    debug: dict = field(default_factory=dict)


def staff_candidates(gray: np.ndarray) -> list[Staff]:
    """Evenly spaced staves found at several line coverages (faded or partly covered
    lines can drop below the default coverage)."""
    found = []
    for ratio in (0.4, 0.3, 0.2):
        for st in detect_staves(gray, ratio):
            gaps = np.diff(st.lines)
            if (
                len(st.lines) >= 4
                and np.std(gaps) <= 0.12 * np.mean(gaps) + 0.5
                and _lines_are_ink(gray, st)
            ):
                found.append(st)
    return found


def _lines_are_ink(gray: np.ndarray, staff: Staff) -> bool:
    """Reject 'staves' made of the gaps between real lines: detect_staves also tries the
    inverted image, where the background bands between lines can look like evenly spaced
    lines. Every real line row is clearly darker than the rows halfway to its neighbours.
    Darkness is relative to the background, so thin light-grey lines still count."""
    g = 255 - gray if np.median(gray) < 128 else gray  # dark theme: make lines dark
    darkness = 255.0 - g[:, staff.x0 : staff.x1 + 1].mean(axis=1)

    def dark(y: float) -> float:
        y = int(round(y))
        rows = darkness[max(0, y - 1) : y + 2]
        return float(rows.max()) if rows.size else 0.0

    lines = staff.lines
    mids = [(a + b) / 2 for a, b in zip(lines, lines[1:], strict=False)]
    # median, not max: dense chords can darken a few in-between rows
    typical_gap = float(np.median([dark(y) for y in mids]))
    return min(dark(y) for y in lines) - typical_gap >= 8


def pick_staff(gray: np.ndarray, strings: int | None = None) -> Staff | None:
    """The staff with the requested number of lines if there is one, else the most lines;
    ties go to the lowest staff."""
    found = staff_candidates(gray)
    if strings is not None and any(len(st.lines) == strings for st in found):
        found = [st for st in found if len(st.lines) == strings]
    if not found:
        return None
    return max(found, key=lambda st: (len(st.lines), -np.std(np.diff(st.lines)), st.lines[0]))


def bar_extents(gray: np.ndarray, staff: Staff) -> list[tuple[int, int]]:
    """(first, last) column of each bar line, a double or final bar counting as one
    (Guitar Pro's final bar is a thin line, a gap and a thick line)."""
    dark = gray[staff.lines[0] : staff.lines[-1] + 1] < INK_LEVEL
    cols = np.flatnonzero(dark.mean(axis=0) >= BAR_COVERAGE)
    if cols.size == 0:
        return []
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > BAR_MERGE_GAP) + 1)
    return [(int(g[0]), int(g[-1])) for g in groups]


def find_bar_lines(gray: np.ndarray, staff: Staff) -> list[int]:
    """Like stitch.find_bars, but for a given staff."""
    return [a for a, _ in bar_extents(gray, staff)]


def _is_enclosure(b: Blob, others: list[Blob], s: float) -> bool:
    """A ring (circled note) around at least one other blob."""
    if b.h < 0.8 * s or b.w < 0.5 * s or b.mask.mean() > 0.45:
        return False
    inside = [
        o
        for o in others
        if o is not b
        and o.x >= b.x - 1
        and o.x + o.w <= b.x + b.w + 1
        and o.y >= b.y - 1
        and o.y + o.h <= b.y + b.h + 1
    ]
    if inside:
        return True
    # a digit touching its ring: the ring is taller than any fret number
    return b.h >= 1.1 * s and any(p.h >= 0.5 * s for p in peel_ring(b, s))


def peel_ring(ring: Blob, s: float) -> list[Blob]:
    """Blobs inside a ring once the ring itself (its outer band) is removed."""
    m = ring.mask.astype(np.uint8)
    # rings are convex; the hull is robust to small gaps left by staff-line removal
    pts = cv2.findNonZero(m)
    filled = np.zeros_like(m)
    cv2.fillConvexPoly(filled, cv2.convexHull(pts), 1)
    # erode by the ring's stroke width: leftmost run length in the middle rows
    rows = m[m.shape[0] // 4 : 3 * m.shape[0] // 4]
    runs = [
        int(np.argmin(r[np.argmax(r) :])) for r in rows if r.any() and not r[np.argmax(r) :].all()
    ]
    t = max(2, int(np.median(runs)) + 1) if runs else max(2, int(round(0.1 * s)))
    inner = cv2.erode(filled, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * t + 1, 2 * t + 1)))
    out = components(m & inner, min_area=4)
    for b in out:
        b.x += ring.x
        b.y += ring.y
    return [b for b in out if b.h >= 0.3 * s]


def staff_band(staff: Staff) -> tuple[int, int]:
    """Rows searched for fret numbers and rests."""
    s = staff.spacing
    return int(staff.lines[0] - 0.6 * s), int(staff.lines[-1] + 0.5 * s)


def _string_of(cy: float, lines: list[int], s: float) -> int | None:
    d = [abs(cy - y) for y in lines]
    i = int(np.argmin(d))
    if d[i] > STRING_TOL * s:
        return None
    return len(lines) - 1 - i


def staff_glyphs(ink: np.ndarray, staff: Staff, bars: list[tuple[int, int]], clf: GlyphClassifier):
    """Classified glyphs inside the staff band plus the enclosure (circle) blobs.
    `bars` are bar-line extents; glyphs left or right of the staff's lines (a track label
    such as "Gt.1") are not notes, because a fret number always sits on a string."""
    s = staff.spacing
    y0, y1 = staff_band(staff)
    y0, y1 = max(0, y0), min(ink.shape[0], y1)
    band = ink[y0:y1].copy()
    for a, b in bars:  # bar lines are not glyphs; blank the whole (double/final) bar
        band[:, max(0, a - 2) : b + 5] = 0
    blobs = components(band, min_area=4)
    blobs = [b for b in blobs if staff.x0 - 0.5 * s <= b.cx <= staff.x1 + 0.5 * s]
    for b in blobs:
        b.y += y0
    circles = [b for b in blobs if _is_enclosure(b, blobs, s)]
    rest = [b for b in blobs if b not in circles]
    for c in circles:  # digits touching the ring are part of the ring's blob
        rest += peel_ring(c, s)
    # ties/slurs: long and flat; bar-like: tall and thin
    rest = [b for b in rest if not (b.w > 1.3 * s and b.h < 0.6 * s)]
    rest = [b for b in rest if not (b.h > 1.6 * s and b.w < 0.25 * s)]
    rest = merge_pieces(rest, s)
    labels = clf.classify(rest, s)
    return [Glyph(b, lab, c) for b, (lab, c) in zip(rest, labels, strict=True)], circles


def _is_stem_piece(g: Glyph, digits: list[Glyph], s: float, band: tuple[int, int]) -> bool:
    """A stem drawn through the staff leaves thin, solid pieces between the lines that
    look like a "1". Such a piece touches a number above or below it, or the band edge."""
    b = g.blob
    if b.w > 0.25 * s:  # a real "1" has a flag or serifs
        return False

    def touches(o: Blob, above: bool) -> bool:
        gap = b.y - (o.y + o.h) if above else o.y - (b.y + b.h)
        return o is not b and abs(o.cx - b.cx) < 0.4 * s and -2 <= gap <= 0.25 * s

    at_edge = (b.y <= band[0] + 1 or b.y + b.h >= band[1] - 1) and b.mask.mean() > 0.8
    return at_edge or any(touches(o.blob, up) for o in digits for up in (True, False))


def frets_from_glyphs(glyphs: list[Glyph], circles: list[Blob], staff: Staff) -> list[Fret]:
    s = staff.spacing
    digits = [g for g in glyphs if g.label in (*DIGITS, "x") and g.conf >= MIN_DIGIT_CONF]
    if digits:  # annotations (harmonic frets...) and specks are smaller than fret numbers
        typical = float(np.median([g.blob.h for g in digits]))
        digits = [g for g in digits if g.blob.h >= SMALL_DIGIT * typical]
    band = staff_band(staff)
    digits = [g for g in digits if not _is_stem_piece(g, digits, s, band)]
    digits.sort(key=lambda g: g.blob.x)
    # join neighbouring digits on the same row into multi-digit numbers
    groups: list[list[Glyph]] = []
    for g in digits:
        for grp in groups:
            last = grp[-1].blob
            gap = g.blob.x - (last.x + last.w)
            if (
                -1 <= gap <= 0.3 * s
                and abs(g.blob.cy - last.cy) <= 0.25 * s
                and "x" not in (g.label, grp[-1].label)
            ):
                grp.append(g)
                break
        else:
            groups.append([g])
    frets = []
    for grp in groups:
        x0 = grp[0].blob.x
        x1 = max(g.blob.x + g.blob.w for g in grp)
        cy = float(np.mean([g.blob.cy for g in grp]))
        h = max(g.blob.h for g in grp)
        string = _string_of(cy, staff.lines, s)
        if string is None:
            continue
        dead = grp[0].label == "x"
        value = 0 if dead else int("".join(g.label for g in grp))
        conf = float(min(g.conf for g in grp))
        circled = any(c.x <= x0 and c.x + c.w >= x1 and c.y <= cy <= c.y + c.h for c in circles)
        frets.append(Fret((x0 + x1) / 2, cy, x1 - x0, h, string, value, conf, circled, dead))
    # one note per string per position: keep the more confident one
    frets.sort(key=lambda f: -f.conf)
    kept: list[Fret] = []
    for f in frets:
        if all(not (k.string == f.string and abs(k.x - f.x) < 0.5 * s) for k in kept):
            kept.append(f)
    return sorted(kept, key=lambda f: f.x)


@dataclass
class RestMark:
    x: float
    kind: str
    conf: float
    blob: Blob


def rests_from_glyphs(glyphs: list[Glyph], frets: list[Fret], staff: Staff) -> list[RestMark]:
    s = staff.spacing
    band = staff_band(staff)
    out = []
    for g in glyphs:
        if not g.label.startswith("rest") or g.conf < 0.5:
            continue
        b = g.blob
        if b.y <= band[0] or b.y + b.h >= band[1] or b.h > 2.5 * s:
            continue  # clipped by the band: part of something bigger (bend arrow, text)
        # parentheses/marks hugging a fret number are not rests
        if any(
            max(b.x - (f.x + f.w / 2), (f.x - f.w / 2) - (b.x + b.w)) < 0.35 * s
            and b.y < f.y + f.h / 2
            and b.y + b.h > f.y - f.h / 2
            for f in frets
        ):
            continue
        out.append(RestMark(g.blob.cx, g.label, g.conf, g.blob))
    return out


@dataclass
class BeatGroup:
    x: float
    frets: list[Fret]
    rest: RestMark | None = None
    hidden: bool = False  # a stem without a number: tied continuation of the previous beat


def group_beats(frets: list[Fret], rests: list[RestMark], s: float) -> list[BeatGroup]:
    widths = [f.w / max(1, len(str(f.fret))) for f in frets]
    digit_w = float(np.median(widths)) if widths else 0.5 * s
    tol = max(0.6 * digit_w, 0.25 * s)
    beats: list[BeatGroup] = []
    for f in sorted(frets, key=lambda f: f.x):
        near = beats and abs(f.x - np.median([g.x for g in beats[-1].frets])) <= tol
        if near:
            beats[-1].frets.append(f)
        else:
            beats.append(BeatGroup(f.x, [f]))
    for b in beats:
        b.x = float(np.median([f.x for f in b.frets]))
    beats += [BeatGroup(r.x, [], r) for r in rests]
    return sorted(beats, key=lambda b: b.x)


def measure_spans(bars: list[int], width: int, s: float) -> list[tuple[int, int]]:
    edges = sorted(set(bars))
    spans = []
    if not edges or edges[0] > 2 * s:
        spans.append((0, edges[0] if edges else width))
    for a, b in zip(edges, [*edges[1:], width], strict=False):
        spans.append((a, b))
    return [(a, b) for a, b in spans if b - a >= 1.5 * s]


def read_measure_number(
    gray: np.ndarray, staff: Staff, bar_x: int, clf: GlyphClassifier
) -> tuple[int | None, float]:
    """Small digits just above the top line, around the bar line."""
    s = staff.spacing
    y0 = max(0, int(staff.lines[0] - 1.0 * s))
    y1 = max(0, staff.lines[0] - 2)
    x0 = max(0, int(bar_x - 1.2 * s))
    x1 = min(gray.shape[1], int(bar_x + 1.6 * s))
    if y1 - y0 < 3 or x1 - x0 < 3:
        return None, 0.0
    blobs = components(otsu_ink(gray[y0:y1, x0:x1]), min_area=3)
    blobs = [b for b in blobs if b.h >= 0.25 * s and b.y + b.h >= (y1 - y0) - 0.5 * s]
    if not blobs or (x0 == 0 and any(b.x == 0 for b in blobs)):  # cut by the image edge
        return None, 0.0
    for b in blobs:
        b.x += x0
        b.y += y0
    blobs = merge_pieces(blobs, s)
    labels = clf.classify(blobs, s)
    items = sorted(
        [(b, lab, c) for b, (lab, c) in zip(blobs, labels, strict=True)], key=lambda t: t[0].x
    )
    # chains of adjacent glyphs; the one closest to the bar is the number
    chains: list[list] = [[items[0]]]
    for d in items[1:]:
        prev = chains[-1][-1][0]
        if d[0].x - (prev.x + prev.w) <= 0.35 * s:
            chains[-1].append(d)
        else:
            chains.append([d])

    def dist(ch):
        a = ch[0][0].x
        b = ch[-1][0].x + ch[-1][0].w
        return 0 if a <= bar_x <= b else min(abs(a - bar_x), abs(b - bar_x))

    chain = min(chains, key=dist)
    if any(lab not in DIGITS for _, lab, _ in chain):  # a digit not read: don't guess
        return None, 0.0
    return int("".join(lab for _, lab, _ in chain)), float(min(c for _, _, c in chain))


@dataclass
class RawMeasure:
    line: int
    x0: int
    x1: int
    groups: list[BeatGroup]
    marks: list[BeatMarks]
    number: int | None  # OCR'd measure number
    number_conf: float


def recognize_line(
    img: np.ndarray,
    line: int = 0,
    clf: GlyphClassifier | None = None,
    strings: int | None = None,
) -> LineResult | None:
    clf = clf or default_classifier()
    gray = gray_of(img)
    staff = pick_staff(gray, strings)
    if staff is None:
        return None
    s = staff.spacing
    extents = bar_extents(gray, staff)
    bars = [a for a, _ in extents]
    ink = staff_ink(gray, s, staff.lines)
    glyphs, circles = staff_glyphs(ink, staff, extents, clf)
    frets = frets_from_glyphs(glyphs, circles, staff)
    rests = rests_from_glyphs(glyphs, frets, staff)
    raw_ink = (gray < INK_LEVEL).astype(np.uint8)

    measures = []
    spans = measure_spans(bars, img.shape[1], s)
    for i, (x0, x1) in enumerate(spans):
        mf = [f for f in frets if x0 < f.x < x1]
        mr = [r for r in rests if x0 < r.x < x1]
        if (
            i in (0, len(spans) - 1)
            and not mf
            and not mr
            and not any(x0 < g.blob.cx < x1 for g in glyphs)
        ):
            continue  # blank margin before the first or after the final bar line
        groups = group_beats(mf, mr, s)
        stems = stem_positions(raw_ink, staff, (x0, x1))
        for x, length in stems:
            # a flag's straight part is shorter than the stem it hangs from
            flag = any(abs(x - o) <= 0.8 * s and ol > length for o, ol in stems)
            real = length >= HIDDEN_STEM and not flag
            if real and all(abs(x - g.x) > 0.6 * s for g in groups):
                groups.append(BeatGroup(x, [], None, hidden=True))
        groups.sort(key=lambda g: g.x)
        marks = read_rhythm(raw_ink, staff, [g.x for g in groups], (x0, x1), clf)
        num, conf = read_measure_number(gray, staff, x0, clf) if x0 in bars else (None, 0.0)
        measures.append(RawMeasure(line, int(x0), int(x1), groups, marks, num, conf))
    debug = {"glyphs": glyphs, "circles": circles, "frets": frets, "rests": rests}
    return LineResult(staff, bars, measures, debug)


NUMBER_JUMP = 2.5  # cost of a numbering discontinuity (missing or repeated measures)


def number_measures(raw: list[RawMeasure], min_conf: float = 0.5) -> list[int]:
    """Measure numbers in reading order, as index + offset with a piecewise-constant
    offset chosen by Viterbi: every OCR'd number votes for its offset (weighted by
    confidence), and changing the offset costs NUMBER_JUMP. A single misread, or two
    consistent misreads in a row, cannot outvote the counting of the measures around it."""
    ocr = [
        (m.number, m.number_conf)
        if m.number is not None and m.number_conf >= min_conf
        else (None, 0.0)
        for m in raw
    ]
    offsets = sorted({n - i for i, (n, _) in enumerate(ocr) if n is not None} or {1})
    if not raw:
        return []

    def emit(i: int, o: int) -> float:
        n, c = ocr[i]
        if n is None:
            return 0.0
        return c if n == i + o else -0.5 * c

    score = {o: emit(0, o) for o in offsets}
    back: list[dict[int, int]] = []
    for i in range(1, len(raw)):
        best_prev = max(score, key=score.get)
        new, ptr = {}, {}
        for o in offsets:
            stay = score[o]
            jump = score[best_prev] - NUMBER_JUMP
            new[o], ptr[o] = (stay, o) if stay >= jump else (jump, best_prev)
            new[o] += emit(i, o)
        score = new
        back.append(ptr)
    o = max(score, key=score.get)
    path = [o]
    for ptr in reversed(back):
        o = ptr[o]
        path.append(o)
    path.reverse()
    return [i + o for i, o in enumerate(path)]


def _evidence(g: BeatGroup, m: BeatMarks, typical_stem: float) -> BeatEvidence:
    short = m.stem and typical_stem > 0 and m.stem_len < 0.75 * typical_stem
    return BeatEvidence(
        m, any(f.circled for f in g.frets), g.rest.kind if g.rest else None, bool(short)
    )


def build_score(lines: list[LineResult], strings: int) -> Score:
    raw = [m for ln in lines for m in ln.measures]
    numbers = number_measures(raw)
    stems = [k.stem_len for m in raw for k in m.marks if k.stem]
    typical = float(np.median(stems)) if stems else 0.0
    measures = []
    previous: list[Note] = []
    for m, number in zip(raw, numbers, strict=True):
        beats, evidence = [], []
        for g, mk in zip(m.groups, m.marks, strict=True):
            notes = [
                Note(f.string, f.fret, round(f.conf, 3), f.dead)
                for f in sorted(g.frets, key=lambda f: f.string)
            ]
            if g.hidden:  # tied continuation: same notes as the beat before, low confidence
                notes = [Note(n.string, n.fret, 0.3, n.dead) for n in previous]
            if notes:
                previous = notes
            beats.append(Beat(4, 0, None, g.rest is not None or not notes, notes, int(g.x)))
            evidence.append(_evidence(g, mk, typical))
        measure = Measure(number, (4, 4), beats, m.line, m.x0, m.x1)
        if not beats:  # an empty measure is a whole-measure rest
            measure.beats = [Beat(1, 0, None, True, [], (m.x0 + m.x1) // 2, 0.5)]
        else:
            ok = solve.apply(beats, evidence, measure.capacity())
            measure.confidence = 1.0 if ok else 0.3
        measures.append(measure)
    tuning = STANDARD_TUNINGS.get(strings, [])
    return Score(strings, tuning, None, measures)


def common_strings(images: list[np.ndarray]) -> int | None:
    """Most common line count of the best staff per image (the tab's string count)."""
    counts = Counter(len(st.lines) for img in images if (st := pick_staff(gray_of(img))))
    return counts.most_common(1)[0][0] if counts else None


def recognize_lines(
    images: list[np.ndarray],
    clf: GlyphClassifier | None = None,
    progress: Callable[[float], None] | None = None,
) -> tuple[list[LineResult], int]:
    clf = clf or default_classifier()
    strings = common_strings(images)
    lines = []
    for i, img in enumerate(images):
        if r := recognize_line(img, i, clf, strings):
            lines.append(r)
        if progress:
            progress((i + 1) / len(images))
    return consistent_lines(lines)


def recognize_images(
    images: list[np.ndarray],
    clf: GlyphClassifier | None = None,
    progress: Callable[[float], None] | None = None,
) -> Score:
    """`progress(fraction)` is called after each image."""
    return build_score(*recognize_lines(images, clf, progress))


def consistent_lines(lines: list[LineResult]) -> tuple[list[LineResult], int]:
    """Keep the lines whose staff has the most common number of strings."""
    counts = Counter(len(r.staff.lines) for r in lines)
    strings = counts.most_common(1)[0][0] if counts else 6
    return [r for r in lines if len(r.staff.lines) == strings], strings
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_omr_model.py -v`
Expected: all pass. The GP test is skipped only when `data/tabs` is absent.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests ../packaging && uv run ruff format --check app tests ../packaging`
Expected: 113 passed, 1 deselected; lint clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/omr/model.py backend/app/omr/recognize.py backend/tests/test_omr_model.py
git commit -m "feat: add score title, validation and source-aligned measure padding

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Jobs and API: recognize, score read/write, job list, restart recovery

**Files:**
- Modify (replace whole file): `backend/app/jobs.py`, `backend/app/workflow.py`, `backend/app/main.py`
- Create: `backend/tests/test_score_api.py`

**Interfaces:**
- Consumes: from Task 1, `Score.from_dict`, `pad_numbers` and `recognize_images(..., progress=)`.
- Produces (`jobs.py`):
  - `Status.RECOGNIZING` and `Status.READY_FOR_SCORE`.
  - New `Job` fields: `created`, `source`, `title`, `score_order`, `score_files`.
  - `write_atomic(path, text)`.
  - `JobStore` reloads jobs from each `state.json` on construction. Jobs that were downloading, analyzing or recognizing become `failed` with "程序重启，处理被中断，请重试".
  - `JobStore.recent(limit=20)`.
- Produces (`workflow.py`): `page_images(job, order)`, `recognize(store, job, order)` and `save_score(job, data)`.
- Produces (routes):
  - `POST /api/jobs/{id}/recognize` with body `{order: [page ids]}`. It returns 400 on unknown pages and 409 on the wrong status.
  - `GET /api/jobs/{id}/score` returns 404 before recognition.
  - `PUT /api/jobs/{id}/score` returns 422 with a Chinese message on bad data, and 409 while recognizing.
  - `GET /api/jobs` returns `[{id, created, status, title, source}]`, newest first.
  - Region re-analysis is also allowed from `ready_for_score`.

- [ ] **Step 1: Write the failing test `backend/tests/test_score_api.py`**

Create `backend/tests/test_score_api.py`:

```python
import json
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.jobs import INTERRUPTED, JobStore, Status
from app.main import create_app
from tests.test_api import wait_for


def upload(client, synth_video):
    with synth_video.path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("my.avi", f, "video/x-msvideo")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def analyzed(client, synth_video):
    job = wait_for(client, upload(client, synth_video), "ready_for_region")
    r = client.put(f"/api/jobs/{job['id']}/region", json=job["region"]["roi"])
    assert r.status_code == 200, r.text
    return wait_for(client, job["id"], "ready_for_review")


def test_recognize_writes_score_and_moves_to_ready_for_score(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job = analyzed(client, synth_video)
    assert client.get(f"/api/jobs/{job['id']}/score").status_code == 404

    order = [2, 0]  # page C then page A; each synthetic page is one measure
    r = client.post(f"/api/jobs/{job['id']}/recognize", json={"order": order})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "recognizing"
    assert r.json()["stage"] == "recognize"
    job = wait_for(client, job["id"], "ready_for_score")
    assert job["score_order"] == order
    assert job["progress"] == 1.0

    score = client.get(f"/api/jobs/{job['id']}/score").json()
    assert score["strings"] == 6 and score["title"] == ""
    assert [m["line"] for m in score["measures"]] == [0, 1]
    assert all(m["beats"] for m in score["measures"])
    assert json.loads((tmp_path / job["id"] / "score.json").read_text()) == score

    # recognizing again is allowed from ready_for_score
    r = client.post(f"/api/jobs/{job['id']}/recognize", json={"order": [0]})
    assert r.status_code == 200, r.text
    job = wait_for(client, job["id"], "ready_for_score")
    assert job["score_order"] == [0]


def test_recognize_rejects_bad_order_and_wrong_status(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job_id = upload(client, synth_video)
    wait_for(client, job_id, "ready_for_region")
    r = client.post(f"/api/jobs/{job_id}/recognize", json={"order": []})
    assert r.status_code == 400

    job = analyzed(client, synth_video)
    r = client.post(f"/api/jobs/{job['id']}/recognize", json={"order": [0, 99]})
    assert r.status_code == 400
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "ready_for_review"

    app = create_app(tmp_path / "other")
    store = app.state.store
    busy = store.create()
    busy.pages = [{"id": 0, "file": "pages/a.png"}]
    store.update(busy, status=Status.ANALYZING)
    r = TestClient(app).post(f"/api/jobs/{busy.id}/recognize", json={"order": [0]})
    assert r.status_code == 409


def blank_job(app, status=Status.READY_FOR_REVIEW):
    store = app.state.store
    job = store.create()
    (job.dir / "pages").mkdir()
    cv2.imwrite(str(job.dir / "pages" / "blank.png"), np.full((120, 400, 3), 255, np.uint8))
    store.update(job, pages=[{"id": 0, "file": "pages/blank.png"}], status=status)
    return job


def test_recognize_without_staff_fails_in_chinese(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    job = blank_job(app)
    r = client.post(f"/api/jobs/{job.id}/recognize", json={"order": [0]})
    assert r.status_code == 200, r.text
    failed = wait_for_status(client, job.id, "failed")
    assert failed["error"] == "没有识别到谱表"
    assert not (job.dir / "score.json").exists()

    # a failed job can be retried
    r = client.post(f"/api/jobs/{job.id}/recognize", json={"order": [0]})
    assert r.status_code == 200


def wait_for_status(client, job_id, status, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {status}")


def scored_job(app):
    job = blank_job(app, Status.READY_FOR_SCORE)
    score = {
        "strings": 6,
        "tuning": [40, 45, 50, 55, 59, 64],
        "measures": [{"beats": [{"duration": 1, "notes": [{"string": 0, "fret": 3}]}]}],
    }
    (job.dir / "score.json").write_text(json.dumps(score))
    return job


def test_put_score_validates_and_writes_atomically(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    job = scored_job(app)
    url = f"/api/jobs/{job.id}/score"

    score = client.get(url).json()
    score["title"] = "我的谱"
    score["tempo"] = 180
    score["measures"][0]["beats"][0]["notes"][0]["fret"] = 5
    r = client.put(url, json=score)
    assert r.status_code == 200, r.text
    saved = client.get(url).json()
    assert saved["title"] == "我的谱" and saved["tempo"] == 180
    assert saved["measures"][0]["beats"][0]["notes"][0]["fret"] == 5
    assert saved["measures"][0]["beats"][0]["confidence"] == 1.0  # normalized with defaults
    assert client.get(f"/api/jobs/{job.id}").json()["title"] == "我的谱"
    assert sorted(p.name for p in job.dir.iterdir()) == ["pages", "score.json", "state.json"]

    bad = {**score, "measures": [{"beats": [{"duration": "4"}]}]}
    r = client.put(url, json=bad)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("乐谱数据不合法")
    assert "duration" in r.json()["detail"]
    assert client.get(url).json() == saved  # a rejected PUT leaves the file alone

    assert client.put(url, json=[1, 2]).status_code == 422


def test_put_score_refused_while_recognizing_or_before_recognition(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    fresh = blank_job(app)
    assert client.put(f"/api/jobs/{fresh.id}/score", json={}).status_code == 404
    job = scored_job(app)
    app.state.store.update(job, status=Status.RECOGNIZING)
    assert client.put(f"/api/jobs/{job.id}/score", json={}).status_code == 409


def test_failed_atomic_write_keeps_old_score(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    client = TestClient(app)
    job = scored_job(app)
    before = (job.dir / "score.json").read_text()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("app.jobs.os.replace", boom)
    with pytest.raises(OSError):
        client.put(f"/api/jobs/{job.id}/score", json={"title": "x"})
    assert (job.dir / "score.json").read_text() == before
    assert sorted(p.name for p in job.dir.iterdir()) == ["pages", "score.json", "state.json"]


def test_list_jobs_newest_first(tmp_path, synth_video):
    app = create_app(tmp_path)
    client = TestClient(app)
    first = upload(client, synth_video)
    second = app.state.store.create()
    app.state.store.update(second, source="https://www.bilibili.com/video/BV1yBcEeXEVn")
    jobs = client.get("/api/jobs").json()
    assert [j["id"] for j in jobs] == [second.id, first]
    assert jobs[1]["source"] == "my.avi"
    assert jobs[0]["source"].endswith("BV1yBcEeXEVn")
    assert set(jobs[0]) == {"id", "created", "status", "title", "source"}


def test_restart_restores_jobs_and_fails_interrupted_ones(tmp_path):
    store = JobStore(tmp_path)
    done = store.create()
    store.update(done, status=Status.READY_FOR_SCORE, title="t", score_order=[1, 0])
    busy = {}
    for status in (Status.DOWNLOADING, Status.ANALYZING, Status.RECOGNIZING):
        busy[status] = store.create()
        store.update(busy[status], status=status, stage="scan")
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk" / "state.json").write_text("{not json")

    reloaded = JobStore(tmp_path)
    again = reloaded.get(done.id)
    assert again.status == Status.READY_FOR_SCORE
    assert again.title == "t" and again.score_order == [1, 0]
    assert again.dir == done.dir and again.created == done.created
    for job in busy.values():
        restored = reloaded.get(job.id)
        assert restored.status == Status.FAILED
        assert restored.error == INTERRUPTED == "程序重启，处理被中断，请重试"
        on_disk = json.loads((job.dir / "state.json").read_text())
        assert on_disk["status"] == "failed"
    assert reloaded.get("junk") is None
    assert len(reloaded.recent()) == 4


def test_restart_through_the_api(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job = analyzed(client, synth_video)
    client.post(f"/api/jobs/{job['id']}/recognize", json={"order": [0, 1]})
    wait_for(client, job["id"], "ready_for_score")

    client = TestClient(create_app(tmp_path))
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "ready_for_score"
    assert client.get(f"/api/jobs/{job['id']}/score").status_code == 200
    assert [j["id"] for j in client.get("/api/jobs").json()] == [job["id"]]


def test_recognize_pads_measure_numbers(tmp_path, monkeypatch):
    from app.omr.model import Beat, Measure, Score

    def fake(images, progress=None):
        return Score(6, [], None, [Measure(n, beats=[Beat(4)]) for n in (3, 5)])

    monkeypatch.setattr("app.workflow.recognize_images", fake)
    app = create_app(tmp_path)
    client = TestClient(app)
    job = blank_job(app)
    client.post(f"/api/jobs/{job.id}/recognize", json={"order": [0]})
    wait_for_status(client, job.id, "ready_for_score")
    score = client.get(f"/api/jobs/{job.id}/score").json()
    assert [m["number"] for m in score["measures"]] == [1, 2, 3, 4, 5]
    assert [m["line"] for m in score["measures"]] == [-1, -1, 0, -1, 0]
    assert [m["confidence"] for m in score["measures"]] == [1.0, 1.0, 1.0, 0.0, 1.0]


def test_recognize_records_page_files_that_reanalysis_replaces(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job = analyzed(client, synth_video)
    order = [2, 0]
    client.post(f"/api/jobs/{job['id']}/recognize", json={"order": order})
    job = wait_for(client, job["id"], "ready_for_score")
    by_id = {p["id"]: p["file"] for p in job["pages"]}
    assert job["score_files"] == [by_id[2], by_id[0]]
    job_dir = tmp_path / job["id"]
    assert all((job_dir / f).is_file() for f in job["score_files"])

    r = client.put(f"/api/jobs/{job['id']}/region", json=job["region"]["roi"])
    assert r.status_code == 200, r.text
    after = wait_for(client, job["id"], "ready_for_review")
    assert after["score_files"] == job["score_files"]  # still what was recognized
    assert not any((job_dir / f).exists() for f in after["score_files"])
    assert set(after["score_files"]).isdisjoint(p["file"] for p in after["pages"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_score_api.py -v`
Expected: FAIL. The new routes return 404/405, and `ImportError` is raised for `write_atomic`.

- [ ] **Step 3: Replace the implementation files**

Replace `backend/app/jobs.py`:

```python
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from app.frames import DecodeError
from app.pipeline import NoPagesFound
from app.source import SourceError

INTERRUPTED = "程序重启，处理被中断，请重试"


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder + rename, so readers never see half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Status(StrEnum):
    DOWNLOADING = "downloading"
    READY_FOR_REGION = "ready_for_region"
    ANALYZING = "analyzing"
    READY_FOR_REVIEW = "ready_for_review"
    RECOGNIZING = "recognizing"
    READY_FOR_SCORE = "ready_for_score"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    dir: Path
    status: Status = Status.DOWNLOADING
    stage: str = ""  # download | probe | scan | compose | recognize
    progress: float = 0.0
    error: str | None = None
    video: str | None = None  # file name inside dir
    width: int = 0
    height: int = 0
    duration: float = 0.0
    region: dict | None = None  # {"roi": {...}, "confidence": float}
    pages: list[dict] = field(default_factory=list)
    # page dict: {"id", "file", "start", "end", "duplicate_of"}
    created: float = 0.0  # unix time
    source: str = ""  # uploaded file name or URL
    title: str = ""  # score title, mirrored from score.json on save
    score_order: list[int] = field(default_factory=list)
    # page ids given to the last recognition; Measure.line indexes into this list
    score_files: list[str] = field(default_factory=list)
    # their page files at recognition time; re-analysis deletes these, so a stale score
    # never shows a different page's image

    def to_dict(self) -> dict:
        d = asdict(self)
        del d["dir"]  # absolute filesystem path; not for clients or state.json
        return d

    @staticmethod
    def from_dict(d: dict, job_dir: Path) -> Job:
        known = {f.name for f in fields(Job)} - {"dir"}
        job = Job(**{k: v for k, v in d.items() if k in known}, dir=job_dir)
        job.status = Status(job.status)
        return job

    def summary(self) -> dict:
        return {
            "id": self.id,
            "created": self.created,
            "status": self.status,
            "title": self.title,
            "source": self.source,
        }


class JobStore:
    # Keys that only carry incremental progress info; updates touching only these are
    # throttled (see update()) since analysis can emit thousands of them per job.
    _PROGRESS_ONLY_KEYS = frozenset({"progress", "stage"})
    _PROGRESS_SAVE_INTERVAL = 0.5  # seconds

    def __init__(self, root: Path):
        self.root = root
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._last_save: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        """Restore jobs from <root>/*/state.json; work cut short by a restart is failed."""
        busy = (Status.DOWNLOADING, Status.ANALYZING, Status.RECOGNIZING)
        for state in self.root.glob("*/state.json"):
            try:
                job = Job.from_dict(json.loads(state.read_text(encoding="utf-8")), state.parent)
            except (OSError, ValueError, TypeError) as exc:
                logging.getLogger(__name__).warning("skipping %s: %s", state, exc)
                continue
            if job.id != state.parent.name:
                continue
            if not job.created:
                job.created = state.stat().st_mtime
            if job.status in busy:
                job.status, job.error, job.stage = Status.FAILED, INTERRUPTED, ""
                self.save(job)
            self._jobs[job.id] = job

    def create(self) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, dir=self.root / job_id, created=time.time())
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        self.save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
        return jobs[:limit]

    def save(self, job: Job) -> None:
        text = json.dumps(job.to_dict(), ensure_ascii=False, indent=2)
        write_atomic(job.dir / "state.json", text)

    def update(self, job: Job, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)
            if changes.keys() <= self._PROGRESS_ONLY_KEYS:
                now = time.monotonic()
                if now - self._last_save.get(job.id, 0.0) < self._PROGRESS_SAVE_INTERVAL:
                    return
            self._last_save[job.id] = time.monotonic()
            self.save(job)

    def transition(self, job: Job, allowed: tuple[Status, ...], **changes) -> bool:
        """Atomically apply `changes` iff job.status is currently in `allowed`.

        Guards against two concurrent callers both passing a status check and
        launching duplicate work (e.g. two PUT /region requests racing).
        """
        with self._lock:
            if job.status not in allowed:
                return False
            for key, value in changes.items():
                setattr(job, key, value)
            self.save(job)
            return True

    def run(self, job: Job, fn: Callable[[], None]) -> threading.Thread:
        """Run fn in a daemon thread; any exception marks the job failed.

        App-level errors (already Chinese, or yt-dlp errors wrapped in Chinese by
        SourceError) are surfaced verbatim. Anything else is an unexpected bug, so
        it's wrapped in a generic Chinese message and the traceback is logged.
        """

        def target() -> None:
            try:
                fn()
            except (SourceError, DecodeError, NoPagesFound, ValueError) as exc:
                logging.getLogger(__name__).exception("job %s failed", job.id)
                self.update(job, status=Status.FAILED, error=str(exc))
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any bug must fail the job
                logging.getLogger(__name__).exception("job %s failed", job.id)
                self.update(
                    job, status=Status.FAILED, error=f"处理失败（{type(exc).__name__}）：{exc}"
                )

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread
```

Replace `backend/app/workflow.py`:

```python
"""Job-level steps glued to the pipeline; each runs inside JobStore.run()."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import cv2

from app.export import export_pdf, export_png
from app.frames import grab_frames, probe
from app.jobs import Job, JobStore, Status, write_atomic
from app.models import Roi
from app.omr.model import Score, pad_numbers
from app.omr.recognize import recognize_images
from app.pipeline import AnalyzeParams, analyze
from app.region import detect_region
from app.source import download_url


def prepare(store: JobStore, job: Job, url: str | None = None) -> None:
    """Download (if url) then probe the video and guess the tab region."""
    if url:
        store.update(job, status=Status.DOWNLOADING, stage="download")
        cookies = os.environ.get("VTT_COOKIES_FILE")
        path = download_url(
            url,
            job.dir,
            Path(cookies) if cookies else None,
            lambda f: store.update(job, progress=f),
        )
        store.update(job, video=path.name)
    video = job.dir / job.video
    store.update(job, stage="probe", progress=0.0)
    info = probe(video)
    frames = grab_frames(video, 20)
    guess = detect_region(frames)
    cv2.imwrite(str(job.dir / "frame.jpg"), frames[len(frames) // 2])
    store.update(
        job,
        width=info.width,
        height=info.height,
        duration=info.duration,
        region={"roi": guess.roi.to_dict(), "confidence": guess.confidence},
        status=Status.READY_FOR_REGION,
        stage="",
        progress=1.0,
    )


def run_analysis(store: JobStore, job: Job, roi: Roi, params: AnalyzeParams) -> None:
    store.update(job, status=Status.ANALYZING, stage="scan", progress=0.0, error=None)
    pages = analyze(
        job.dir / job.video,
        roi.clamp(job.width, job.height),
        params,
        lambda stage, frac: store.update(job, stage=stage, progress=frac),
    )
    pages_dir = job.dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for old in job.pages:
        old_path = (job.dir / old["file"]).resolve()
        if old_path.is_relative_to(pages_dir.resolve()) and old_path.is_file():
            old_path.unlink()
    run = uuid.uuid4().hex[:8]
    meta = []
    for i, page in enumerate(pages):
        name = f"pages/{run}_{i:03d}.png"
        cv2.imwrite(str(job.dir / name), page.image)
        meta.append(
            {
                "id": i,
                "file": name,
                "start": page.start,
                "end": page.end,
                "duplicate_of": page.duplicate_of,
            }
        )
    store.update(job, pages=meta, status=Status.READY_FOR_REVIEW, stage="", progress=1.0)


def page_images(job: Job, order: list[int]) -> list:
    """The page images for page ids `order` (unknown ids are skipped), in that order."""
    by_id = {p["id"]: p for p in job.pages}
    images = []
    for i in order:
        if i not in by_id:
            continue
        file = by_id[i]["file"]
        image = cv2.imread(str(job.dir / file))
        if image is None:
            raise ValueError(f"页面文件缺失：{file}")
        images.append(image)
    if not images:
        raise ValueError("没有选中任何页面")
    return images


def save_score(job: Job, score: Score) -> None:
    text = json.dumps(score.to_dict(), ensure_ascii=False)
    write_atomic(job.dir / "score.json", text)


def recognize(store: JobStore, job: Job, order: list[int]) -> None:
    """Read the tab from the pages in `order`; Measure.line indexes into `order`."""
    store.update(job, status=Status.RECOGNIZING, stage="recognize", progress=0.0, error=None)
    images = page_images(job, order)
    score = recognize_images(images, progress=lambda f: store.update(job, progress=f))
    if not score.measures:
        raise ValueError("没有识别到谱表")
    score = pad_numbers(score)  # bar k of the editor and the export is measure k
    score.title = job.title  # keep a title the user already typed
    save_score(job, score)
    by_id = {p["id"]: p["file"] for p in job.pages}
    store.update(
        job,
        score_order=list(order),
        score_files=[by_id[i] for i in order],
        status=Status.READY_FOR_SCORE,
        stage="",
        progress=1.0,
    )


def export(job: Job, order: list[int], fmt: str) -> str:
    images = page_images(job, order)
    name = f"tab.{fmt}"
    (export_png if fmt == "png" else export_pdf)(images, job.dir / name)
    return name
```

Replace `backend/app/main.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import cv2
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import workflow
from app.frames import DecodeError, frame_at
from app.jobs import Job, JobStore, Status
from app.models import Roi
from app.omr.model import Score
from app.pipeline import AnalyzeParams
from app.source import VIDEO_EXTS, SourceError, normalize_url, save_upload

REPO_ROOT = Path(__file__).resolve().parents[2]


def safe_path(root: Path, name: str) -> Path | None:
    path = (root / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


class RegionIn(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    fps: float = Field(default=5.0, gt=0, le=60)
    diff_threshold: float = Field(default=0.15, gt=0, lt=1)
    min_duration: float = Field(default=0.8, ge=0)


class RecognizeIn(BaseModel):
    order: list[int]


class ExportIn(BaseModel):
    order: list[int]
    fmt: Literal["png", "pdf"]


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = data_dir or Path(os.environ.get("VTT_DATA_DIR", REPO_ROOT / "data" / "jobs"))
    store = JobStore(data_dir)
    app = FastAPI(title="video-to-tab")
    app.state.store = store

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        detail = "参数不合法：" + "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:])} {e['msg']}" for e in exc.errors()
        )
        return JSONResponse(status_code=422, content={"detail": detail})

    def get_job(job_id: str) -> Job:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return job

    @app.post("/api/jobs")
    def create_job(file: UploadFile | None = File(None), url: str | None = Form(None)) -> dict:
        if (file is None) == (not url):
            raise HTTPException(400, "请上传视频文件或填写链接（二选一）")
        try:
            clean_url = normalize_url(url) if url else None
            if file is not None:
                ext = Path(file.filename or "").suffix.lower()
                if ext not in VIDEO_EXTS:
                    raise SourceError(f"不支持的文件类型：{ext or '无扩展名'}")
            job = store.create()
            if file is not None:
                path = save_upload(file.file, file.filename or "", job.dir)
                store.update(job, video=path.name, source=file.filename or "")
            else:
                store.update(job, source=clean_url)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.run(job, lambda: workflow.prepare(store, job, clean_url))
        return job.to_dict()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return [job.summary() for job in store.recent()]

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict:
        return get_job(job_id).to_dict()

    @app.put("/api/jobs/{job_id}/region")
    def set_region(job_id: str, body: RegionIn) -> dict:
        job = get_job(job_id)
        if not job.region:
            raise HTTPException(409, "视频尚未就绪")
        roi = Roi(body.x, body.y, body.w, body.h)
        params = AnalyzeParams(body.fps, body.diff_threshold, body.min_duration)
        allowed = (
            Status.READY_FOR_REGION,
            Status.READY_FOR_REVIEW,
            Status.READY_FOR_SCORE,
            Status.FAILED,
        )
        if not store.transition(job, allowed, status=Status.ANALYZING, error=None):
            raise HTTPException(409, f"当前状态不能开始分析：{job.status}")
        store.run(job, lambda: workflow.run_analysis(store, job, roi, params))
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/recognize")
    def recognize(job_id: str, body: RecognizeIn) -> dict:
        job = get_job(job_id)
        known = {p["id"] for p in job.pages}
        if not body.order:
            raise HTTPException(400, "没有选中任何页面")
        if not set(body.order) <= known:
            raise HTTPException(400, "页面不存在，请刷新后重试")
        allowed = (Status.READY_FOR_REVIEW, Status.READY_FOR_SCORE, Status.FAILED)
        changes = {"status": Status.RECOGNIZING, "stage": "recognize", "progress": 0.0}
        if not store.transition(job, allowed, **changes, error=None):
            raise HTTPException(409, f"当前状态不能开始识谱：{job.status}")
        store.run(job, lambda: workflow.recognize(store, job, body.order))
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/score")
    def read_score(job_id: str) -> dict:
        job = get_job(job_id)
        path = job.dir / "score.json"
        if not path.is_file():
            raise HTTPException(404, "还没有识谱结果")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.put("/api/jobs/{job_id}/score")
    def write_score(job_id: str, body: Annotated[Any, Body()]) -> dict:
        job = get_job(job_id)
        if job.status == Status.RECOGNIZING:
            raise HTTPException(409, "正在识谱，请稍后再保存")
        if not (job.dir / "score.json").is_file():
            raise HTTPException(404, "还没有识谱结果")
        try:
            score = Score.from_dict(body)
        except ValueError as exc:
            raise HTTPException(422, f"乐谱数据不合法：{exc}") from exc
        workflow.save_score(job, score)
        if score.title != job.title:
            store.update(job, title=score.title)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/export")
    def export(job_id: str, body: ExportIn) -> dict:
        job = get_job(job_id)
        try:
            name = workflow.export(job, body.order, body.fmt)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"url": f"/api/jobs/{job_id}/files/{name}"}

    @app.get("/api/jobs/{job_id}/frame")
    def frame(job_id: str, t: float = 0.0) -> Response:
        job = get_job(job_id)
        if not job.video:
            raise HTTPException(409, "视频尚未就绪")
        try:
            img = frame_at(job.dir / job.video, t)
        except DecodeError as exc:
            raise HTTPException(400, str(exc)) from exc
        ok, buf = cv2.imencode(".jpg", img)
        if not ok:
            raise HTTPException(500, "帧图像编码失败")
        return Response(buf.tobytes(), media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/files/{name:path}")
    def files(job_id: str, name: str) -> FileResponse:
        job = get_job(job_id)
        path = safe_path(job.dir, name)
        if path is None:
            raise HTTPException(404, "文件不存在")
        return FileResponse(path)

    dist = Path(os.environ.get("VTT_FRONTEND_DIR", REPO_ROOT / "frontend" / "dist"))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_score_api.py -v`
Expected: 11 passed.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests ../packaging && uv run ruff format --check app tests ../packaging`
Expected: 124 passed, 1 deselected; lint clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs.py backend/app/workflow.py backend/app/main.py backend/tests/test_score_api.py
git commit -m "feat: recognize jobs into a saved score, list jobs, recover them after restart

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Frontend libraries: tuning, Score → alphaTex, immutable edits, source lookup; the alphaTab dependency

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json` (both via npm)
- Create: `frontend/src/lib/{tuning,alphatex,scoreEdit,source}.js`, their `*.test.js`, and `frontend/src/lib/gpExport.test.js`

**Interfaces:**
- Produces:
  - `tuning.js`: `midiToName`, `nameToMidi`, `PRESETS`, `parseTuning(text, strings)` and `defaultTuning(strings)`.
  - `alphatex.js`: `scoreToTex(score) -> string`. It throws on data alphaTab would misread.
  - `scoreEdit.js`, where every function returns a new Score:
    - `setFret(score, m, b, string, value)`, where `value` is `null`, `'x'` or 0–30
    - `setDuration`, `toggleDot`, `toggleTriplet`, `toggleRest`
    - `insertBeat(score, m, b, 'before' | 'after')`
    - `deleteBeat`
    - `confirmBeat`, which also clears the measure flag when the measure fills exactly
    - `measureFill(measure) -> {used, capacity}`
    - `needsReview(measure, beat)`
    - `nextToReview(score, from)`
  - `source.js`: `measureSource(job, measure) -> {kind: 'page' | 'absent' | 'missing', ...}`.

- [ ] **Step 1: Add the alphaTab dependency**

Run: `cd frontend && npm install --save-exact @coderline/alphatab@1.8.4`
Expected: `package.json` gains `"@coderline/alphatab": "1.8.4"` under dependencies, and `package-lock.json` is updated.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/lib/tuning.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { PRESETS, defaultTuning, midiToName, nameToMidi, parseTuning, tuningText } from './tuning.js'

describe('tuning', () => {
  it('converts names and MIDI both ways', () => {
    expect(midiToName(64)).toBe('E4')
    expect(midiToName(33)).toBe('A1')
    expect(midiToName(42)).toBe('F#2')
    expect(nameToMidi('E4')).toBe(64)
    expect(nameToMidi('e2')).toBe(40)
    expect(nameToMidi('Bb1')).toBe(34)
    expect(nameToMidi('F#2')).toBe(42)
    for (let midi = 12; midi < 120; midi++) expect(nameToMidi(midiToName(midi))).toBe(midi)
  })

  it('rejects bad note names', () => {
    for (const bad of ['', 'H2', 'E', '4', 'E#', 'Ex4', 'E10', 'E-1']) {
      expect(nameToMidi(bad)).toBeNull()
    }
  })

  it('has the presets named in the spec, lowest string first', () => {
    expect(PRESETS[6].map((p) => p.name)).toEqual(['E 标准', 'Drop D', '降半音'])
    expect(PRESETS[7].map((p) => p.name)).toEqual(['B 标准', 'Drop A'])
    expect(tuningText(PRESETS[7][1].tuning)).toBe('E4 B3 G3 D3 A2 E2 A1')
    expect(tuningText(PRESETS[6][2].tuning)).toBe('D#4 A#3 F#3 C#3 G#2 D#2')
    for (const [strings, list] of Object.entries(PRESETS)) {
      for (const p of list) expect(p.tuning).toHaveLength(Number(strings))
    }
  })

  it('parses custom tunings written from the highest string', () => {
    expect(parseTuning('E4 B3 G3 D3 A2 D2', 6)).toEqual([38, 45, 50, 55, 59, 64])
    expect(parseTuning('  e4,b3 g3  d3 a2 e2 ', 6)).toEqual([40, 45, 50, 55, 59, 64])
    expect(() => parseTuning('E4 B3 G3', 6)).toThrow('需要 6 个音名')
    expect(() => parseTuning('E4 B3 G3 D3 A2 X2', 6)).toThrow('X2')
  })

  it('falls back to standard tuning for any string count', () => {
    expect(defaultTuning(6)).toEqual([40, 45, 50, 55, 59, 64])
    expect(defaultTuning(7)).toEqual([35, 40, 45, 50, 55, 59, 64])
    expect(tuningText(defaultTuning(8))).toBe('E4 B3 G3 D3 A2 E2 B1 F#1')
    expect(defaultTuning(4)).toHaveLength(4)
  })
})
```

Create `frontend/src/lib/alphatex.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { scoreToTex, texString } from './alphatex.js'

const note = (string, fret, extra = {}) => ({ string, fret, confidence: 1, dead: false, ...extra })
const beat = (notes, extra = {}) => ({
  duration: 4,
  dots: 0,
  tuplet: null,
  rest: notes.length === 0,
  notes,
  x: 0,
  confidence: 1,
  ...extra,
})
const measure = (beats) => ({ number: 1, time: [4, 4], beats, line: 0, x0: 0, x1: 100, confidence: 1 })
const score7 = (measures, extra = {}) => ({
  strings: 7,
  tuning: [33, 40, 45, 50, 55, 59, 64],
  tempo: null,
  title: '',
  measures,
  ...extra,
})
const body = (tex) => tex.split('\\ts 4 4\n')[1]

describe('scoreToTex', () => {
  it('numbers strings from the highest (1) where the Score counts from the lowest (0)', () => {
    expect(texString(7, 0)).toBe(7)
    expect(texString(7, 6)).toBe(1)
    expect(texString(6, 0)).toBe(6)
    expect(body(scoreToTex(score7([measure([beat([note(0, 3)])])])))).toBe('3.7.4')
  })

  it('writes the header: title, tempo, tab staff, tuning from the highest string', () => {
    const tex = scoreToTex(score7([measure([beat([note(6, 0)])])], { title: 'Ave "M"', tempo: 200 }))
    const lines = tex.split('\n')
    expect(lines.slice(0, 7)).toEqual([
      '\\title "Ave \\"M\\""',
      '\\tempo 200',
      '.',
      '\\track "Guitar"',
      '\\staff {tabs}',
      '\\tuning (E4 B3 G3 D3 A2 E2 A1)',
      '\\ts 4 4',
    ])
  })

  it('defaults the tempo to 120 and a missing tuning to standard', () => {
    const tex = scoreToTex({ strings: 6, tuning: [], tempo: null, measures: [measure([])] })
    expect(tex).toContain('\\tempo 120')
    expect(tex).toContain('\\tuning (E4 B3 G3 D3 A2 E2)')
    expect(tex).toContain('\\title ""')
  })

  it('writes chords, dead notes, rests, dots, triplets and empty measures', () => {
    const tex = scoreToTex(
      score7([
        measure([
          beat([note(0, 7), note(1, 7)], { duration: 8 }),
          beat([note(0, 0, { dead: true })], { duration: 8 }),
          beat([], { duration: 4 }),
          beat([note(0, 5)], { duration: 8, dots: 1 }),
          beat([note(2, 12)], { duration: 8, tuplet: 3 }),
          beat([note(2, 12), note(3, 0, { dead: true })], { duration: 16, dots: 1, tuplet: 3 }),
        ]),
        measure([]),
        measure([beat([note(0, 1)], { rest: true, duration: 1 })]),
      ]),
    )
    expect(body(tex)).toBe(
      '(7.7 7.6).8 x.7.8 r.4 5.7.8{d} 12.5.8{tu 3} (12.5 x.4).16{d tu 3} |\nr.1 |\nr.1',
    )
  })

  it('refuses data alphaTab would misread', () => {
    expect(() => scoreToTex(score7([measure([beat([note(7, 1)])])]))).toThrow('弦号')
    expect(() => scoreToTex(score7([measure([beat([note(0, 1)], { duration: 3 })])]))).toThrow('时值')
  })
})
```

Create `frontend/src/lib/scoreEdit.test.js`:

```js
import { describe, expect, it } from 'vitest'
import {
  beatLength,
  confirmBeat,
  deleteBeat,
  insertBeat,
  measureFill,
  needsReview,
  nextToReview,
  setDuration,
  setFret,
  toggleDot,
  toggleRest,
  toggleTriplet,
} from './scoreEdit.js'

const note = (string, fret, confidence = 1) => ({ string, fret, confidence, dead: false })
const beat = (notes, extra = {}) => ({
  duration: 4,
  dots: 0,
  tuplet: null,
  rest: notes.length === 0,
  notes,
  x: 10,
  confidence: 1,
  ...extra,
})
const measure = (beats, extra = {}) => ({
  number: 1,
  time: [4, 4],
  beats,
  line: 0,
  x0: 0,
  x1: 100,
  confidence: 1,
  ...extra,
})

function sample() {
  return {
    strings: 6,
    tuning: [40, 45, 50, 55, 59, 64],
    tempo: null,
    title: '',
    measures: [
      measure([beat([note(0, 3)]), beat([note(1, 5), note(2, 7)]), beat([]), beat([note(0, 1)])]),
      measure([beat([note(0, 3, 0.5)], { duration: 2 }), beat([note(1, 2)], { duration: 2 })]),
      measure([beat([note(0, 3)], { duration: 1 })], { confidence: 0.3 }),
    ],
  }
}

// every edit must leave the input untouched
function frozen() {
  const s = sample()
  const deepFreeze = (o) => {
    Object.values(o).forEach((v) => v && typeof v === 'object' && deepFreeze(v))
    return Object.freeze(o)
  }
  return deepFreeze(s)
}

describe('scoreEdit', () => {
  it('setFret adds, changes, mutes and removes notes', () => {
    const s = frozen()
    let t = setFret(s, 0, 1, 4, 12)
    expect(t.measures[0].beats[1].notes.map((n) => [n.string, n.fret])).toEqual([
      [1, 5],
      [2, 7],
      [4, 12],
    ])
    t = setFret(t, 0, 1, 2, 9)
    expect(t.measures[0].beats[1].notes[1]).toEqual({ string: 2, fret: 9, confidence: 1, dead: false })
    t = setFret(t, 0, 1, 1, 'x')
    expect(t.measures[0].beats[1].notes[0]).toEqual({ string: 1, fret: 0, confidence: 1, dead: true })
    t = setFret(s, 0, 0, 0, null)
    expect(t.measures[0].beats[0]).toMatchObject({ notes: [], rest: true })
    t = setFret(s, 0, 2, 3, 0)
    expect(t.measures[0].beats[2]).toMatchObject({ notes: [note(3, 0)], rest: false })
    expect(s).toEqual(sample())
  })

  it('setFret rejects frets outside 0..30', () => {
    const s = frozen()
    for (const bad of [-1, 31, 2.5, NaN]) expect(() => setFret(s, 0, 0, 0, bad)).toThrow('品格')
    expect(setFret(s, 0, 0, 0, 30).measures[0].beats[0].notes[0].fret).toBe(30)
  })

  it('changes duration, dot, triplet and rest', () => {
    const s = frozen()
    expect(setDuration(s, 0, 0, 16).measures[0].beats[0].duration).toBe(16)
    expect(() => setDuration(s, 0, 0, 3)).toThrow()
    const dotted = toggleDot(s, 0, 0)
    expect(dotted.measures[0].beats[0].dots).toBe(1)
    expect(toggleDot(dotted, 0, 0).measures[0].beats[0].dots).toBe(0)
    const trip = toggleTriplet(s, 0, 0)
    expect(trip.measures[0].beats[0].tuplet).toBe(3)
    expect(toggleTriplet(trip, 0, 0).measures[0].beats[0].tuplet).toBeNull()
    const rest = toggleRest(s, 0, 1)
    expect(rest.measures[0].beats[1]).toMatchObject({ rest: true, notes: [] })
    expect(toggleRest(rest, 0, 1).measures[0].beats[1].rest).toBe(false)
    expect(s).toEqual(sample())
  })

  it('inserts a rest beat before or after', () => {
    const s = frozen()
    const before = insertBeat(s, 1, 1, 'before')
    expect(before.measures[1].beats).toHaveLength(3)
    expect(before.measures[1].beats[1]).toMatchObject({ rest: true, notes: [], duration: 2 })
    expect(before.measures[1].beats[2]).toBe(s.measures[1].beats[1])
    const after = insertBeat(s, 1, 1, 'after')
    expect(after.measures[1].beats[2]).toMatchObject({ rest: true, duration: 2 })
    expect(after.measures[0]).toBe(s.measures[0]) // untouched measures are shared
    expect(s).toEqual(sample())
  })

  it('deletes a beat; the last one becomes a whole rest', () => {
    const s = frozen()
    const t = deleteBeat(s, 0, 1)
    expect(t.measures[0].beats.map((b) => b.notes.length)).toEqual([1, 0, 1])
    const u = deleteBeat(s, 2, 0)
    expect(u.measures[2].beats).toEqual([
      { duration: 1, dots: 0, tuplet: null, rest: true, notes: [], x: 50, confidence: 1 },
    ])
    expect(s).toEqual(sample())
  })

  it('confirmBeat sets the beat and note confidence to 1', () => {
    const s = frozen()
    const t = confirmBeat(s, 1, 0)
    expect(t.measures[1].beats[0].confidence).toBe(1)
    expect(t.measures[1].beats[0].notes[0].confidence).toBe(1)
    expect(needsReview(t.measures[1], t.measures[1].beats[0])).toBe(false)
    // a measure that adds up is checked too; one that does not stays flagged
    expect(confirmBeat(s, 2, 0).measures[2].confidence).toBe(1)
    const short = setDuration(s, 2, 0, 2)
    expect(confirmBeat(short, 2, 0).measures[2].confidence).toBe(0.3)
    expect(s).toEqual(sample())
  })

  it('measureFill adds beat lengths as fractions', () => {
    expect(beatLength(beat([], { duration: 8, dots: 1 }))).toEqual({ n: 3, d: 16 })
    expect(beatLength(beat([], { duration: 8, tuplet: 3 }))).toEqual({ n: 1, d: 12 })
    expect(beatLength(beat([], { duration: 4, dots: 2 }))).toEqual({ n: 7, d: 16 })
    const full = measureFill(sample().measures[0])
    expect(full).toEqual({ used: { n: 1, d: 1 }, capacity: { n: 1, d: 1 } })
    const trip = measure([
      ...[0, 1, 2].map(() => beat([], { duration: 8, tuplet: 3 })),
      beat([], { duration: 4 }),
      beat([], { duration: 2 }),
    ])
    expect(measureFill(trip).used).toEqual({ n: 1, d: 1 })
    expect(measureFill(measure([beat([])])).used).toEqual({ n: 1, d: 4 })
    expect(measureFill(measure([], { time: [3, 4] })).capacity).toEqual({ n: 3, d: 4 })
  })

  it('needsReview flags low beat, note or measure confidence', () => {
    const m = measure([])
    expect(needsReview(m, beat([note(0, 1)]))).toBe(false)
    expect(needsReview(m, beat([note(0, 1)], { confidence: 0.69 }))).toBe(true)
    expect(needsReview(m, beat([note(0, 1, 0.6)]))).toBe(true)
    expect(needsReview(m, beat([note(0, 1, 0.7)]))).toBe(false)
    expect(needsReview(measure([], { confidence: 0.99 }), beat([]))).toBe(true)
  })

  it('nextToReview walks the flagged beats in order and wraps around', () => {
    const s = sample()
    expect(nextToReview(s, null)).toEqual({ m: 1, b: 0 })
    expect(nextToReview(s, { m: 1, b: 0 })).toEqual({ m: 2, b: 0 })
    expect(nextToReview(s, { m: 2, b: 0 })).toEqual({ m: 1, b: 0 })
    expect(nextToReview(s, { m: 0, b: 3 })).toEqual({ m: 1, b: 0 })
    const clean = confirmBeat(confirmBeat(s, 1, 0), 2, 0)
    expect(nextToReview(clean, null)).toBeNull()
  })
})
```

Create `frontend/src/lib/source.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { measureSource } from './source.js'

const job = {
  score_order: [4, 2],
  pages: [
    { id: 2, file: 'pages/b.png' },
    { id: 4, file: 'pages/a.png' },
  ],
}

describe('measureSource', () => {
  it('finds the page a measure was read from via score_order', () => {
    expect(measureSource(job, { line: 0 })).toEqual({ kind: 'page', file: 'pages/a.png' })
    expect(measureSource(job, { line: 1 })).toEqual({ kind: 'page', file: 'pages/b.png' })
  })

  it('reports measures that were never shown in the video', () => {
    expect(measureSource(job, { line: -1 })).toEqual({ kind: 'absent' })
  })

  it('reports a page that no longer exists', () => {
    expect(measureSource(job, { line: 5 })).toEqual({ kind: 'missing' })
    expect(measureSource({ ...job, pages: [] }, { line: 0 })).toEqual({ kind: 'missing' })
  })
})

describe('measureSource with recorded files', () => {
  it('uses the file recorded at recognition, not the current page list', () => {
    const reanalyzed = {
      score_order: [4, 2],
      score_files: ['pages/run1_004.png', 'pages/run1_002.png'],
      pages: [
        { id: 2, file: 'pages/run2_002.png' },
        { id: 4, file: 'pages/run2_004.png' },
      ],
    }
    expect(measureSource(reanalyzed, { line: 0 })).toEqual({
      kind: 'page',
      file: 'pages/run1_004.png',
    })
    expect(measureSource(reanalyzed, { line: 1 }).file).toBe('pages/run1_002.png')
    expect(measureSource(reanalyzed, { line: 2 })).toEqual({ kind: 'missing' })
    expect(measureSource(reanalyzed, { line: -1 })).toEqual({ kind: 'absent' })
  })
})
```

Create `frontend/src/lib/gpExport.test.js`:

```js
// Round trip in Node: Score -> alphaTex -> alphaTab -> Gp7Exporter bytes -> ScoreLoader.
import * as alphaTab from '@coderline/alphatab'
import { describe, expect, it } from 'vitest'
import { scoreToTex } from './alphatex.js'

const note = (string, fret, dead = false) => ({ string, fret, confidence: 1, dead })
const beat = (notes, duration, extra = {}) => ({
  duration,
  dots: 0,
  tuplet: null,
  rest: notes.length === 0,
  notes,
  x: 0,
  confidence: 1,
  ...extra,
})
const measure = (beats) => ({ number: 1, time: [4, 4], beats, line: 0, x0: 0, x1: 0, confidence: 1 })

const SCORE = {
  strings: 7,
  tuning: [33, 40, 45, 50, 55, 59, 64],
  tempo: 200,
  title: 'KiLLKiSS 测试',
  measures: [
    measure([
      beat([note(0, 7), note(1, 7)], 4),
      beat([note(0, 7), note(1, 7)], 8),
      beat([note(0, 0, true)], 8),
      beat([], 4),
      beat([note(0, 5)], 8, { dots: 1 }),
      beat([note(0, 5)], 16),
    ]),
    measure([
      beat([note(0, 3)], 8, { tuplet: 3 }),
      beat([note(0, 3)], 8, { tuplet: 3 }),
      beat([note(6, 3)], 8, { tuplet: 3 }),
      beat([note(2, 12), note(5, 15)], 4),
      beat([], 2),
    ]),
    measure([]),
  ],
}

// alphaTab's model numbers strings from the lowest, starting at 1
function summary(score) {
  const bars = score.tracks[0].staves[0].bars
  return bars.map((bar) =>
    bar.voices[0].beats.map((b) => ({
      duration: b.duration,
      dots: b.dots,
      tuplet: b.tupletNumerator > 0 ? b.tupletNumerator : null,
      rest: b.isRest,
      notes: b.notes.map((n) => [n.string - 1, n.isDead ? 'x' : n.fret]).sort(),
    })),
  )
}

function expected(score) {
  return score.measures.map((m) =>
    (m.beats.length ? m.beats : [beat([], 1)]).map((b) => ({
      duration: b.duration,
      dots: b.dots,
      tuplet: b.tuplet,
      rest: b.rest,
      notes: b.notes.map((n) => [n.string, n.dead ? 'x' : n.fret]).sort(),
    })),
  )
}

describe('alphaTab round trip', () => {
  it('exports .gp bytes that read back with the same beats and frets', () => {
    const settings = new alphaTab.Settings()
    const importer = new alphaTab.importer.AlphaTexImporter()
    importer.initFromString(scoreToTex(SCORE), settings)
    const imported = importer.readScore()
    expect(summary(imported)).toEqual(expected(SCORE))

    const bytes = new alphaTab.exporter.Gp7Exporter().export(imported, settings)
    expect(bytes).toBeInstanceOf(Uint8Array)
    expect(bytes.length).toBeGreaterThan(1000)
    expect(String.fromCharCode(bytes[0], bytes[1])).toBe('PK') // a zip, like Guitar Pro's .gp

    const back = alphaTab.importer.ScoreLoader.loadScoreFromBytes(bytes, settings)
    expect(summary(back)).toEqual(expected(SCORE))
    expect(back.title).toBe('KiLLKiSS 测试')
    expect(back.tempo).toBe(200)
    expect(back.tracks[0].staves[0].stringTuning.tunings).toEqual([64, 59, 55, 50, 45, 40, 33])
  })
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL. Vitest reports that it failed to resolve the imports `./tuning.js`, `./alphatex.js`, `./scoreEdit.js` and `./source.js`.

- [ ] **Step 4: Write the libraries**

Create `frontend/src/lib/tuning.js`:

```js
// Tunings as MIDI numbers, lowest string first (the Score's string order: 0 = lowest).
// Text form lists note names from the highest string down, like alphaTex's \tuning.

const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
const STEPS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }

export const PRESETS = {
  6: [
    { name: 'E 标准', tuning: [40, 45, 50, 55, 59, 64] },
    { name: 'Drop D', tuning: [38, 45, 50, 55, 59, 64] },
    { name: '降半音', tuning: [39, 44, 49, 54, 58, 63] },
  ],
  7: [
    { name: 'B 标准', tuning: [35, 40, 45, 50, 55, 59, 64] },
    { name: 'Drop A', tuning: [33, 40, 45, 50, 55, 59, 64] },
  ],
}

export function midiToName(midi) {
  return `${NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`
}

// 'E4' / 'F#2' / 'Bb1' (case-insensitive letter) -> MIDI number, or null if not a note name
export function nameToMidi(name) {
  const m = /^([A-Ga-g])(#|b)?(\d)$/.exec(String(name).trim())
  if (!m) return null
  const shift = m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0
  const midi = (Number(m[3]) + 1) * 12 + STEPS[m[1].toUpperCase()] + shift
  return midi >= 0 && midi <= 127 ? midi : null
}

// 'E4 B3 G3 D3 A2 E2' (highest string first) -> [40, 45, ...] (lowest first); throws on bad input
export function parseTuning(text, strings) {
  const parts = String(text).trim().split(/[\s,]+/).filter(Boolean)
  if (parts.length !== strings) {
    throw new Error(`需要 ${strings} 个音名（从最高音弦写到最低音弦），实际 ${parts.length} 个`)
  }
  const midi = parts.map((p) => {
    const v = nameToMidi(p)
    if (v === null) throw new Error(`无法识别的音名：${p}（例如 E4、F#2、Bb1）`)
    return v
  })
  return midi.reverse()
}

export function tuningText(tuning) {
  return tuning.slice().reverse().map(midiToName).join(' ')
}

// The first preset for this string count; other counts stack fourths (one major third)
// down from E4, which gives standard tuning for 6, 7 and 8 strings.
export function defaultTuning(strings) {
  if (PRESETS[strings]) return PRESETS[strings][0].tuning.slice()
  const gaps = [5, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
  const high = [64]
  for (let i = 1; i < strings; i++) high.push(high[i - 1] - gaps[i - 1])
  return high.reverse()
}
```

Create `frontend/src/lib/alphatex.js`:

```js
// Score JSON (see backend app/omr/model.py) -> alphaTex text for alphaTab.
import { defaultTuning, midiToName } from './tuning.js'

export const DURATIONS = [1, 2, 4, 8, 16, 32]

function quote(text) {
  return `"${String(text).replace(/[\r\n]+/g, ' ').replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

// alphaTex numbers strings from the highest (1); the Score from the lowest (0).
export function texString(strings, string) {
  return strings - string
}

export function scoreTuning(score) {
  const t = score.tuning || []
  return t.length === score.strings ? t : defaultTuning(score.strings)
}

function beatTex(score, beat) {
  if (!DURATIONS.includes(beat.duration)) throw new Error(`不支持的时值：${beat.duration}`)
  let body
  if (beat.rest || !beat.notes.length) body = 'r'
  else {
    const notes = beat.notes.map((n) => {
      if (!(n.string >= 0 && n.string < score.strings)) throw new Error(`弦号超出范围：${n.string}`)
      return `${n.dead ? 'x' : n.fret}.${texString(score.strings, n.string)}`
    })
    body = notes.length === 1 ? notes[0] : `(${notes.join(' ')})`
  }
  const effects = []
  if (beat.dots) effects.push('d'.repeat(beat.dots))
  if (beat.tuplet) effects.push(`tu ${beat.tuplet}`)
  return `${body}.${beat.duration}${effects.length ? `{${effects.join(' ')}}` : ''}`
}

export function scoreToTex(score) {
  const tuning = scoreTuning(score).slice().reverse().map(midiToName).join(' ')
  const bars = score.measures.map((m) =>
    m.beats.length ? m.beats.map((b) => beatTex(score, b)).join(' ') : 'r.1',
  )
  return [
    `\\title ${quote(score.title || '')}`,
    `\\tempo ${score.tempo || 120}`,
    '.',
    '\\track "Guitar"',
    '\\staff {tabs}',
    `\\tuning (${tuning})`,
    '\\ts 4 4',
    bars.join(' |\n'),
  ].join('\n')
}
```

Create `frontend/src/lib/scoreEdit.js`:

```js
// Pure edits of the Score JSON: every function returns a new score and leaves its input alone.
import { DURATIONS } from './alphatex.js'

export const LOW_CONFIDENCE = 0.7
export const MAX_FRET = 30
const TUPLET_RATIO = { 3: [3, 2], 5: [5, 4], 6: [6, 4], 7: [7, 4], 9: [9, 8] }

function mapAt(list, index, fn) {
  return list.map((item, i) => (i === index ? fn(item) : item))
}

function updateMeasure(score, m, fn) {
  return { ...score, measures: mapAt(score.measures, m, fn) }
}

function updateBeat(score, m, b, fn) {
  return updateMeasure(score, m, (measure) => ({ ...measure, beats: mapAt(measure.beats, b, fn) }))
}

function restBeat(duration, x) {
  return { duration, dots: 0, tuplet: null, rest: true, notes: [], x, confidence: 1 }
}

// value: null (no note on this string), 'x' (dead note) or a fret number 0..MAX_FRET
export function setFret(score, m, b, string, value) {
  let note = null
  if (value === 'x') note = { string, fret: 0, confidence: 1, dead: true }
  else if (value !== null) {
    if (!Number.isInteger(value) || value < 0 || value > MAX_FRET) {
      throw new RangeError(`品格应为 0–${MAX_FRET} 的整数`)
    }
    note = { string, fret: value, confidence: 1, dead: false }
  }
  return updateBeat(score, m, b, (beat) => {
    const notes = beat.notes.filter((n) => n.string !== string)
    if (note) notes.push(note)
    notes.sort((p, q) => p.string - q.string)
    return { ...beat, notes, rest: notes.length === 0 }
  })
}

export function setDuration(score, m, b, duration) {
  if (!DURATIONS.includes(duration)) throw new RangeError(`不支持的时值：${duration}`)
  return updateBeat(score, m, b, (beat) => ({ ...beat, duration }))
}

export function toggleDot(score, m, b) {
  return updateBeat(score, m, b, (beat) => ({ ...beat, dots: beat.dots ? 0 : 1 }))
}

export function toggleTriplet(score, m, b) {
  return updateBeat(score, m, b, (beat) => ({ ...beat, tuplet: beat.tuplet ? null : 3 }))
}

// A rest loses its notes; turning a rest off leaves an empty beat to type frets into.
export function toggleRest(score, m, b) {
  return updateBeat(score, m, b, (beat) =>
    beat.rest ? { ...beat, rest: false } : { ...beat, rest: true, notes: [] },
  )
}

// where: 'before' | 'after'; the new beat is a rest with the neighbour's duration
export function insertBeat(score, m, b, where) {
  return updateMeasure(score, m, (measure) => {
    const ref = measure.beats[b]
    const beats = measure.beats.slice()
    beats.splice(where === 'before' ? b : b + 1, 0, restBeat(ref?.duration ?? 4, ref?.x ?? 0))
    return { ...measure, beats }
  })
}

// Deleting a measure's only beat leaves a whole-measure rest.
export function deleteBeat(score, m, b) {
  return updateMeasure(score, m, (measure) => {
    const beats = measure.beats.filter((_, i) => i !== b)
    const x = Math.round((measure.x0 + measure.x1) / 2)
    return { ...measure, beats: beats.length ? beats : [restBeat(1, x)] }
  })
}

// Marks the beat and its notes as checked. A measure whose beats now add up exactly is
// also marked checked (its low confidence means "durations did not add up").
export function confirmBeat(score, m, b) {
  const next = updateBeat(score, m, b, (beat) => ({
    ...beat,
    confidence: 1,
    notes: beat.notes.map((n) => ({ ...n, confidence: 1 })),
  }))
  const measure = next.measures[m]
  const { used, capacity } = measureFill(measure)
  if (fracCompare(used, capacity) !== 0 || measure.confidence >= 1) return next
  return updateMeasure(next, m, (mm) => ({ ...mm, confidence: 1 }))
}

// ---------------------------------------------------------------- fractions

function gcd(a, b) {
  return b ? gcd(b, a % b) : Math.abs(a)
}

function frac(n, d) {
  const g = gcd(n, d) || 1
  return { n: n / g, d: d / g }
}

export function fracCompare(a, b) {
  return Math.sign(a.n * b.d - b.n * a.d)
}

export function beatLength(beat) {
  let n = 2 ** (beat.dots + 1) - 1 // 1 + 1/2 + ... as a fraction over 2^dots
  let d = beat.duration * 2 ** beat.dots
  if (beat.tuplet) {
    const [count, time] = TUPLET_RATIO[beat.tuplet] ?? [beat.tuplet, beat.tuplet]
    n *= time
    d *= count
  }
  return frac(n, d)
}

// Length of the measure's beats vs. its time signature, both in whole notes.
export function measureFill(measure) {
  let used = { n: 0, d: 1 }
  for (const beat of measure.beats) {
    const len = beatLength(beat)
    used = frac(used.n * len.d + len.n * used.d, used.d * len.d)
  }
  const [num, den] = measure.time ?? [4, 4]
  return { used, capacity: frac(num, den) }
}

// ---------------------------------------------------------------- review

export function needsReview(measure, beat) {
  return (
    beat.confidence < LOW_CONFIDENCE ||
    beat.notes.some((n) => n.confidence < LOW_CONFIDENCE) ||
    measure.confidence < 1
  )
}

// The next flagged beat after `from` ({m, b} or null = before the start), wrapping around.
export function nextToReview(score, from) {
  const flagged = []
  score.measures.forEach((measure, m) =>
    measure.beats.forEach((beat, b) => {
      if (needsReview(measure, beat)) flagged.push({ m, b })
    }),
  )
  if (!from) return flagged[0] ?? null
  const after = flagged.find((p) => p.m > from.m || (p.m === from.m && p.b > from.b))
  return after ?? flagged[0] ?? null
}
```

Create `frontend/src/lib/source.js`:

```js
// Which page image a measure was recognized from. Measure.line indexes job.score_files
// (the files recorded at recognition; older jobs only have score_order page ids).
// kind: 'page' (with file) | 'absent' (padding: not in the video) | 'missing'
export function measureSource(job, measure) {
  if (measure.line < 0) return { kind: 'absent' }
  if (job.score_files?.length) {
    const file = job.score_files[measure.line]
    return file ? { kind: 'page', file } : { kind: 'missing' }
  }
  const id = job.score_order?.[measure.line]
  const page = job.pages.find((p) => p.id === id)
  return page ? { kind: 'page', file: page.file } : { kind: 'missing' }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm test && npm run build`
Expected: 29 passed, and the build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/tuning.js frontend/src/lib/alphatex.js frontend/src/lib/scoreEdit.js frontend/src/lib/source.js frontend/src/lib/tuning.test.js frontend/src/lib/alphatex.test.js frontend/src/lib/scoreEdit.test.js frontend/src/lib/source.test.js frontend/src/lib/gpExport.test.js
git commit -m "feat: add score-to-alphaTex conversion, score edits and tunings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Editor UI: TabRenderer, BeatEditor, ScoreView and app wiring

**Files:**
- Create: `frontend/src/components/TabRenderer.vue`, `frontend/src/components/BeatEditor.vue`, `frontend/src/views/ScoreView.vue`
- Modify (replace whole file): `frontend/src/api.js`, `frontend/src/App.vue`, `frontend/src/views/InputView.vue`, `frontend/src/views/ReviewView.vue`, `frontend/vite.config.js`

**Interfaces:**
- Consumes: the Task 2 routes and the Task 3 libraries.
- Produces:
  - **api.js:** adds `listJobs`, `recognize(id, order)`, `getScore(id)` and `saveScore(id, score)`.
  - **App.vue:**
    - handles the statuses `recognizing` and `ready_for_score`;
    - keeps `#job=<id>` in the URL hash and restores the job on load.
  - **InputView:** shows "最近的任务".
  - **ReviewView:** adds a "识谱" button, and "继续编辑识谱结果" when a score exists.
  - **TabRenderer:**
    - props `score` and `selected`;
    - emits `select({m, b})`;
    - exposes `exportGp() -> Uint8Array`.

These components have no unit tests; they are verified by the build and by the end-to-end check in Task 5.

- [ ] **Step 1: Write the components and replace the wiring files**

Create `frontend/src/components/TabRenderer.vue`:

```vue
<script setup>
// alphaTab wrapper: renders a Score, marks beats that need review and the selected beat,
// and reports clicks as { m, b } (measure and beat indices of the Score).
import * as alphaTab from '@coderline/alphatab'
import bravuraWoff from '@coderline/alphatab/font/Bravura.woff?url'
import bravuraWoff2 from '@coderline/alphatab/font/Bravura.woff2?url'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { scoreToTex } from '../lib/alphatex.js'
import { needsReview } from '../lib/scoreEdit.js'

const props = defineProps({
  score: { type: Object, required: true },
  selected: { type: Object, default: null },
})
const emit = defineEmits(['select', 'error', 'rendered'])

const wrap = ref(null)
const host = ref(null)
const boxes = shallowRef(new Map()) // "m:b" -> { left, top, width, height } in px
const rendering = ref(true)
let api = null

function key(m, b) {
  return `${m}:${b}`
}

function style(box) {
  return { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` }
}

const flagged = computed(() => {
  const out = []
  props.score.measures.forEach((measure, m) =>
    measure.beats.forEach((beat, b) => {
      const box = boxes.value.get(key(m, b))
      if (box && needsReview(measure, beat)) out.push({ id: key(m, b), style: style(box) })
    }),
  )
  return out
})

const selectedBox = computed(() => {
  const box = props.selected && boxes.value.get(key(props.selected.m, props.selected.b))
  return box ? style(box) : null
})

// Beat columns in wrapper coordinates: x/width from the beat, y/height from its bar.
function collectBounds() {
  const lookup = api.renderer.boundsLookup
  const surface = host.value.querySelector('.at-surface')
  if (!lookup || !surface || !api.score) return
  const inner = surface.getBoundingClientRect()
  const outer = wrap.value.getBoundingClientRect()
  const dx = inner.left - outer.left
  const dy = inner.top - outer.top
  const map = new Map()
  api.score.tracks[0].staves[0].bars.forEach((bar, m) =>
    bar.voices[0].beats.forEach((beat, i) => {
      const bounds = lookup.findBeat(beat)
      if (!bounds) return
      const r = bounds.realBounds
      const col = bounds.barBounds.realBounds
      map.set(key(m, i), { x: r.x + dx, y: col.y + dy, w: r.w, h: col.h })
    }),
  )
  boxes.value = map
}

function render() {
  rendering.value = true
  try {
    api.tex(scoreToTex(props.score))
  } catch (e) {
    rendering.value = false
    emit('error', e.message)
  }
}

onMounted(() => {
  api = new alphaTab.AlphaTabApi(host.value, {
    core: {
      useWorkers: false, // only rendering, no playback: keep everything on the main thread
      enableLazyLoading: false, // all beats need bounds for the overlays
      smuflFontSources: new Map([
        ['woff2', bravuraWoff2],
        ['woff', bravuraWoff],
      ]),
    },
    // no playback; ScrollMode.Off stops alphaTab scrolling the page to the top on re-render
    player: { playerMode: alphaTab.PlayerMode.Disabled, scrollMode: alphaTab.ScrollMode.Off },
  })
  api.postRenderFinished.on(() => {
    collectBounds()
    rendering.value = false
    emit('rendered')
  })
  api.beatMouseDown.on((beat) => emit('select', { m: beat.voice.bar.index, b: beat.index }))
  api.error.on((e) => {
    rendering.value = false
    emit('error', e?.message || String(e))
  })
  render()
})

onBeforeUnmount(() => api?.destroy())

watch(() => props.score, render)

// keep the selected beat in view (e.g. after "下一个待检查")
watch(
  () => props.selected,
  async () => {
    await nextTick()
    wrap.value?.querySelector('.sel')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  },
)

function exportGp() {
  if (!api?.score) throw new Error('谱面尚未渲染完成')
  return new alphaTab.exporter.Gp7Exporter().export(api.score, api.settings)
}

defineExpose({ exportGp })
</script>

<template>
  <div ref="wrap" class="tab-wrap">
    <div ref="host" class="tab-host" />
    <div class="layer">
      <div v-for="f in flagged" :key="f.id" class="flag" :style="f.style" />
      <div v-if="selectedBox" class="sel" :style="selectedBox" />
    </div>
    <p v-if="rendering" class="busy">正在渲染谱面…</p>
  </div>
</template>

<style scoped>
.tab-wrap { position: relative; min-height: 120px; }
.layer { position: absolute; inset: 0; pointer-events: none; }
.flag { position: absolute; background: rgba(245, 158, 11, 0.28); border-radius: 3px; }
.sel { position: absolute; border: 2px solid #2563eb; border-radius: 3px; background: rgba(37, 99, 235, 0.1); }
.busy { position: absolute; top: 0; right: 0; margin: 0; font-size: 13px; color: #666; }
</style>
```

Create `frontend/src/components/BeatEditor.vue`:

```vue
<script setup>
// Edit panel for one beat: the measure's source image, one fret box per string,
// duration / dot / triplet / rest, insert / delete / confirm, and the measure-fill check.
import { computed, ref, watch } from 'vue'
import { api } from '../api.js'
import { scoreTuning } from '../lib/alphatex.js'
import {
  MAX_FRET,
  confirmBeat,
  deleteBeat,
  fracCompare,
  insertBeat,
  measureFill,
  setDuration,
  setFret,
  toggleDot,
  toggleRest,
  toggleTriplet,
} from '../lib/scoreEdit.js'
import { measureSource } from '../lib/source.js'
import { midiToName } from '../lib/tuning.js'

const props = defineProps({
  job: { type: Object, required: true },
  score: { type: Object, required: true },
  m: { type: Number, required: true },
  b: { type: Number, required: true },
})
// change: (newScore, newSelection)
const emit = defineEmits(['change', 'close'])

const DURATIONS = [
  [1, '全'],
  [2, '2分'],
  [4, '4分'],
  [8, '8分'],
  [16, '16分'],
  [32, '32分'],
]
const CROP_WIDTH = 320 // px shown in the panel
const CROP_HEIGHT = 220 // max px
const PAD = 12 // source px kept on both sides of the measure

const measure = computed(() => props.score.measures[props.m])
const beat = computed(() => measure.value.beats[props.b] ?? null)
const invalid = ref({}) // string -> text the user typed that is not a fret

watch(
  () => [props.m, props.b],
  () => (invalid.value = {}),
)

// strings listed from the highest (top line of the tab) down
const strings = computed(() => {
  const tuning = scoreTuning(props.score)
  const out = []
  for (let s = props.score.strings - 1; s >= 0; s--) {
    const note = beat.value?.notes.find((n) => n.string === s)
    out.push({
      string: s,
      label: `${props.score.strings - s} 弦 ${midiToName(tuning[s])}`,
      value: note ? (note.dead ? 'x' : String(note.fret)) : '',
      low: note && note.confidence < 0.7,
    })
  }
  return out
})

// ------------------------------------------------------------------ source image crop

const source = computed(() => measureSource(props.job, measure.value))
const pageUrl = computed(() =>
  source.value.kind === 'page' ? api.fileUrl(props.job.id, source.value.file) : '',
)
const natural = ref(null) // { w, h } of the page image
const broken = ref(false) // the page file is gone (pages re-analyzed after recognition)

watch(
  pageUrl,
  (url) => {
    natural.value = null
    broken.value = false
    if (!url) return
    const img = new Image()
    img.onload = () => {
      if (url === pageUrl.value) natural.value = { w: img.naturalWidth, h: img.naturalHeight }
    }
    img.onerror = () => {
      if (url === pageUrl.value) broken.value = true
    }
    img.src = url
  },
  { immediate: true },
)

const crop = computed(() => {
  if (!natural.value) return null
  const mm = measure.value
  const x0 = Math.max(0, mm.x0 - PAD)
  const x1 = Math.min(natural.value.w, Math.max(mm.x1, mm.x0 + 1) + PAD)
  const scale = Math.min(1.5, CROP_WIDTH / (x1 - x0), CROP_HEIGHT / natural.value.h)
  const marker = beat.value ? (beat.value.x - x0) * scale : null
  return {
    box: {
      width: `${(x1 - x0) * scale}px`,
      height: `${natural.value.h * scale}px`,
      backgroundImage: `url("${pageUrl.value}")`,
      backgroundSize: `${natural.value.w * scale}px auto`,
      backgroundPosition: `${-x0 * scale}px 0`,
    },
    marker: marker === null ? null : { left: `${marker}px` },
  }
})

// ------------------------------------------------------------------ edits

function change(score, sel = { m: props.m, b: props.b }) {
  emit('change', score, sel)
}

function onFret(string, event) {
  const text = event.target.value.trim()
  let value
  if (text === '') value = null
  else if (text.toLowerCase() === 'x') value = 'x'
  else if (/^\d+$/.test(text) && Number(text) <= MAX_FRET) value = Number(text)
  else {
    invalid.value = { ...invalid.value, [string]: text }
    return
  }
  const { [string]: _, ...rest } = invalid.value
  invalid.value = rest
  change(setFret(props.score, props.m, props.b, string, value))
}

function insert(where) {
  change(insertBeat(props.score, props.m, props.b, where), {
    m: props.m,
    b: where === 'before' ? props.b : props.b + 1,
  })
}

function remove() {
  const next = deleteBeat(props.score, props.m, props.b)
  change(next, { m: props.m, b: Math.min(props.b, next.measures[props.m].beats.length - 1) })
}

const fill = computed(() => {
  const { used, capacity } = measureFill(measure.value)
  const cmp = fracCompare(used, capacity)
  if (cmp === 0) return null
  const text = (f) => (f.d === 1 ? `${f.n}` : `${f.n}/${f.d}`)
  const what = cmp < 0 ? '没填满' : '超出了'
  return `本小节时值${what}拍号：共 ${text(used)} 个全音符，应为 ${text(capacity)}`
})
</script>

<template>
  <div class="card editor">
    <div class="row head">
      <!-- m + 1 is the bar number alphaTab draws; after padding it equals measure.number -->
      <strong>第 {{ m + 1 }} 小节 · 第 {{ b + 1 }} 拍</strong>
      <button class="close" title="关闭" @click="emit('close')">×</button>
    </div>
    <div v-if="crop" class="crop" :style="crop.box">
      <div v-if="crop.marker" class="marker" :style="crop.marker" />
    </div>
    <p v-else-if="source.kind === 'absent'" class="hint">视频中没有这一小节</p>
    <p v-else-if="broken || source.kind === 'missing'" class="hint">
      原图已更新，请重新识谱以对照
    </p>
    <p v-if="fill" class="warn">{{ fill }}</p>

    <template v-if="beat">
      <div class="frets">
        <label v-for="s in strings" :key="s.string" :class="{ low: s.low }">
          <span>{{ s.label }}</span>
          <input
            type="text"
            inputmode="numeric"
            maxlength="2"
            :data-string="s.string"
            :value="invalid[s.string] ?? s.value"
            :class="{ bad: s.string in invalid }"
            @change="onFret(s.string, $event)"
          />
        </label>
      </div>
      <p v-if="Object.keys(invalid).length" class="error">品格应为 0–{{ MAX_FRET }}，或 x 表示闷音</p>
      <p class="hint">留空 = 没有音，x = 闷音</p>

      <div class="row">
        <button
          v-for="[d, label] in DURATIONS"
          :key="d"
          :class="{ on: beat.duration === d }"
          @click="change(setDuration(score, m, b, d))"
        >
          {{ label }}
        </button>
      </div>
      <div class="row">
        <button :class="{ on: beat.dots }" @click="change(toggleDot(score, m, b))">附点</button>
        <button :class="{ on: beat.tuplet }" @click="change(toggleTriplet(score, m, b))">三连音</button>
        <button :class="{ on: beat.rest }" @click="change(toggleRest(score, m, b))">休止</button>
      </div>
      <div class="row">
        <button @click="insert('before')">前插一拍</button>
        <button @click="insert('after')">后插一拍</button>
        <button @click="remove">删除此拍</button>
        <button class="primary" @click="change(confirmBeat(score, m, b))">确认无误</button>
      </div>
    </template>
    <p v-else class="hint">这一小节没有拍</p>
  </div>
</template>

<style scoped>
.editor { width: 340px; box-sizing: border-box; }
.head { justify-content: space-between; margin-bottom: 8px; }
.close { padding: 2px 10px; }
.crop { position: relative; background-repeat: no-repeat; border: 1px solid #ddd; margin-bottom: 8px; }
.marker { position: absolute; top: 0; bottom: 0; width: 2px; background: rgba(37, 99, 235, 0.7); }
.frets { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; margin-bottom: 4px; }
.frets label { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-size: 13px; }
.frets input { width: 44px; text-align: center; }
.frets .low span { background: rgba(245, 158, 11, 0.35); border-radius: 3px; padding: 0 3px; }
.bad { border-color: #b91c1c !important; background: #fee2e2; }
.row { margin-bottom: 8px; }
.on { background: #dbeafe; border-color: #2563eb; }
.hint { color: #666; font-size: 13px; margin: 4px 0 8px; }
</style>
```

Create `frontend/src/views/ScoreView.vue`:

```vue
<script setup>
// The score page: settings (title, tempo, tuning), the rendered tab, the beat editor,
// autosave to the backend and .gp export.
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { api } from '../api.js'
import BeatEditor from '../components/BeatEditor.vue'
import TabRenderer from '../components/TabRenderer.vue'
import { scoreTuning } from '../lib/alphatex.js'
import { needsReview, nextToReview } from '../lib/scoreEdit.js'
import { PRESETS, parseTuning, tuningText } from '../lib/tuning.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['back'])

const SAVE_DELAY = 1000 // ms of quiet before an autosave
const score = shallowRef(null)
const selected = ref(null)
const loadError = ref('')
const renderError = ref('')
const exportError = ref('')
const saveState = ref('saved') // saved | pending | saving | unsaved
const renderer = ref(null)
let saveTimer = null

onMounted(async () => {
  try {
    score.value = await api.getScore(props.job.id)
  } catch (e) {
    loadError.value = e.message
  }
})

// ------------------------------------------------------------------ autosave

async function save() {
  clearTimeout(saveTimer)
  saveTimer = null
  const sent = score.value
  saveState.value = 'saving'
  try {
    await api.saveScore(props.job.id, sent)
    if (score.value === sent && !saveTimer) saveState.value = 'saved'
  } catch {
    saveState.value = 'unsaved' // retried with the next edit
  }
}

function update(next, sel) {
  score.value = next
  if (sel !== undefined) selected.value = sel
  saveState.value = 'pending'
  clearTimeout(saveTimer)
  saveTimer = setTimeout(save, SAVE_DELAY)
}

onBeforeUnmount(() => {
  if (saveTimer) save()
})

const SAVE_TEXT = { saved: '已保存', pending: '待保存…', saving: '保存中…', unsaved: '未保存' }

// ------------------------------------------------------------------ settings

const title = computed({
  get: () => score.value.title,
  set: (title) => update({ ...score.value, title: title.trim() }),
})

const tempo = computed({
  get: () => score.value.tempo ?? 120,
  set: (v) => {
    const t = Math.round(Number(v))
    if (t >= 20 && t <= 400) update({ ...score.value, tempo: t })
  },
})

const presets = computed(() => PRESETS[score.value.strings] ?? [])
const tuningNow = computed(() => tuningText(scoreTuning(score.value)))
const presetName = computed(() => {
  const hit = presets.value.find((p) => tuningText(p.tuning) === tuningNow.value)
  return hit ? hit.name : 'custom'
})
const tuningError = ref('')

function choosePreset(event) {
  const preset = presets.value.find((p) => p.name === event.target.value)
  if (preset) update({ ...score.value, tuning: preset.tuning.slice() })
}

function customTuning(event) {
  try {
    update({ ...score.value, tuning: parseTuning(event.target.value, score.value.strings) })
    tuningError.value = ''
  } catch (e) {
    tuningError.value = e.message
  }
}

// ------------------------------------------------------------------ review + export

const toReview = computed(() => {
  let n = 0
  for (const m of score.value.measures) for (const b of m.beats) n += needsReview(m, b) ? 1 : 0
  return n
})

function next() {
  const pos = nextToReview(score.value, selected.value)
  if (pos) selected.value = pos
}

function exportGp() {
  exportError.value = ''
  try {
    const bytes = renderer.value.exportGp()
    const name = `${(score.value.title || 'tab').replace(/[\\/:*?"<>|]/g, '_')}.gp`
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }))
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    exportError.value = `导出失败：${e.message}`
  }
}
</script>

<template>
  <div v-if="loadError" class="card">
    <p class="error">{{ loadError }}</p>
    <button @click="emit('back')">回到校对页</button>
  </div>
  <template v-else-if="score">
    <div class="card">
      <h2>4. 识谱结果（{{ score.measures.length }} 小节，{{ score.strings }} 弦）</h2>
      <div class="row settings">
        <label>标题 <input v-model.lazy="title" type="text" placeholder="未命名" size="24" /></label>
        <label>速度 <input v-model.lazy="tempo" type="number" min="20" max="400" /></label>
        <label>
          定弦
          <select :value="presetName" @change="choosePreset">
            <option v-for="p in presets" :key="p.name" :value="p.name">{{ p.name }}</option>
            <option value="custom">自定义</option>
          </select>
        </label>
        <input
          :key="tuningNow"
          type="text"
          :value="tuningNow"
          size="26"
          title="从最高音弦写到最低音弦，例如 E4 B3 G3 D3 A2 E2"
          @change="customTuning"
        />
      </div>
      <p v-if="tuningError" class="error">{{ tuningError }}</p>
      <div class="row">
        <button :disabled="!toReview" @click="next">下一个待检查（{{ toReview }}）</button>
        <button class="primary" @click="exportGp">导出 .gp</button>
        <button @click="emit('back')">回到校对页</button>
        <span class="save" :class="saveState">{{ SAVE_TEXT[saveState] }}</span>
      </div>
      <p class="hint">橙色 = 需要检查的拍；点击任意一拍即可修改。</p>
      <p v-if="exportError" class="error">{{ exportError }}</p>
      <p v-if="renderError" class="error">{{ renderError }}</p>
    </div>
    <div class="workspace">
      <div class="card sheet">
        <TabRenderer
          ref="renderer"
          :score="score"
          :selected="selected"
          @select="selected = $event"
          @error="renderError = $event"
          @rendered="renderError = ''"
        />
      </div>
      <BeatEditor
        v-if="selected && score.measures[selected.m]"
        class="side"
        :job="job"
        :score="score"
        :m="selected.m"
        :b="selected.b"
        @change="update"
        @close="selected = null"
      />
    </div>
  </template>
  <p v-else class="card">正在加载识谱结果…</p>
</template>

<style scoped>
.settings label input[type='number'] { width: 70px; }
.workspace { display: flex; gap: 16px; align-items: flex-start; }
.sheet { flex: 1; min-width: 0; }
.side { position: sticky; top: 8px; flex: none; max-height: calc(100vh - 16px); overflow: auto; }
.save { margin-left: auto; font-size: 13px; color: #15803d; }
.save.pending, .save.saving { color: #666; }
.save.unsaved { color: #b91c1c; font-weight: 600; }
.hint { color: #666; font-size: 13px; margin: 8px 0 0; }
</style>
```

Replace `frontend/src/api.js`:

```js
async function request(method, url, body) {
  const init = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await fetch(url, init)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${res.status})`)
  }
  return data
}

export const api = {
  createFromFile(file) {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/api/jobs', form)
  },
  createFromUrl(url) {
    const form = new FormData()
    form.append('url', url)
    return request('POST', '/api/jobs', form)
  },
  listJobs: () => request('GET', '/api/jobs'),
  getJob: (id) => request('GET', `/api/jobs/${id}`),
  recognize: (id, order) => request('POST', `/api/jobs/${id}/recognize`, { order }),
  getScore: (id) => request('GET', `/api/jobs/${id}/score`),
  saveScore: (id, score) => request('PUT', `/api/jobs/${id}/score`, score),
  setRegion: (id, region) => request('PUT', `/api/jobs/${id}/region`, region),
  exportPages: (id, order, fmt) => request('POST', `/api/jobs/${id}/export`, { order, fmt }),
  fileUrl: (id, name) => `/api/jobs/${id}/files/${name}`,
  frameUrl: (id, t) => `/api/jobs/${id}/frame?t=${t}`,
}
```

Replace `frontend/src/App.vue`:

```vue
<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from './api.js'
import InputView from './views/InputView.vue'
import RegionEditor from './views/RegionEditor.vue'
import ReviewView from './views/ReviewView.vue'

// alphaTab is large: load the score page only when it is first shown
const ScoreView = defineAsyncComponent(() => import('./views/ScoreView.vue'))

const job = ref(null)
const restoreError = ref('')
const STAGES = {
  download: '下载视频',
  probe: '检测谱面区域',
  scan: '扫描换页',
  compose: '合成页面',
  recognize: '识谱',
}
const BUSY = ['downloading', 'analyzing', 'recognizing']
let timer = null

function setHash(id) {
  const hash = id ? `#job=${id}` : ''
  if (location.hash !== hash) history.replaceState(null, '', `${location.pathname}${location.search}${hash}`)
}

function track(next) {
  job.value = next
  setHash(next.id)
  clearTimeout(timer)
  if (BUSY.includes(next.status)) {
    timer = setTimeout(async () => {
      try {
        track(await api.getJob(next.id))
      } catch (e) {
        track({ ...next, status: 'failed', error: e.message })
      }
    }, 800)
  }
}

function restart() {
  clearTimeout(timer)
  job.value = null
  setHash(null)
}

onMounted(async () => {
  const id = /^#job=([\w-]+)$/.exec(location.hash)?.[1]
  if (!id) return
  try {
    track(await api.getJob(id))
  } catch (e) {
    restoreError.value = `无法恢复任务 ${id}：${e.message}`
    setHash(null)
  }
})

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <main>
    <h1>Video → Tab</h1>
    <template v-if="!job">
      <p v-if="restoreError" class="error card">{{ restoreError }}</p>
      <InputView @created="track" />
    </template>
    <template v-else>
      <div v-if="BUSY.includes(job.status)" class="card">
        <p>{{ STAGES[job.stage] || '处理中' }}…</p>
        <progress :value="job.progress" max="1" />
      </div>
      <div v-else-if="job.status === 'failed'" class="card">
        <p class="error">{{ job.error }}</p>
        <div class="row">
          <button v-if="job.pages.length" @click="track({ ...job, status: 'ready_for_review' })">
            回到校对页
          </button>
          <button v-if="job.region" @click="track({ ...job, status: 'ready_for_region' })">
            调整区域重试
          </button>
          <button @click="restart">重新开始</button>
        </div>
      </div>
      <RegionEditor v-else-if="job.status === 'ready_for_region'" :job="job" @started="track" />
      <ReviewView
        v-else-if="job.status === 'ready_for_review'"
        :job="job"
        @back="track({ ...job, status: 'ready_for_region' })"
        @restart="restart"
        @started="track"
        @score="track({ ...job, status: 'ready_for_score' })"
      />
      <ScoreView
        v-else-if="job.status === 'ready_for_score'"
        :key="job.id"
        :job="job"
        @back="track({ ...job, status: 'ready_for_review' })"
      />
    </template>
  </main>
</template>
```

Replace `frontend/src/views/InputView.vue`:

```vue
<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['created'])
const url = ref('')
const error = ref('')
const busy = ref(false)
const recent = ref([])
const STATUS = {
  downloading: '下载中',
  ready_for_region: '待框选',
  analyzing: '分析中',
  ready_for_review: '待校对',
  recognizing: '识谱中',
  ready_for_score: '已识谱',
  failed: '失败',
}

onMounted(async () => {
  try {
    recent.value = await api.listJobs()
  } catch {
    recent.value = [] // the list is a convenience; never block starting a new job
  }
})

async function submit(action) {
  error.value = ''
  busy.value = true
  try {
    emit('created', await action())
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

function onFile(event) {
  const file = event.target.files[0]
  if (file) submit(() => api.createFromFile(file))
}

function when(seconds) {
  return new Date(seconds * 1000).toLocaleString()
}
</script>

<template>
  <div class="card">
    <h2>1. 选择视频</h2>
    <p>上传本地视频（mp4 / mkv / webm / mov / avi / flv …）</p>
    <input type="file" accept="video/*,.mkv,.flv" :disabled="busy" @change="onFile" />
    <p>或粘贴 bilibili / YouTube 链接、BV 号：</p>
    <form class="row" @submit.prevent="submit(() => api.createFromUrl(url))">
      <input v-model="url" type="text" placeholder="https://www.bilibili.com/video/BV..." size="50" />
      <button class="primary" :disabled="busy || !url.trim()">解析</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <div v-if="recent.length" class="card">
    <h2>最近的任务</h2>
    <ul class="recent">
      <li v-for="j in recent" :key="j.id">
        <button :disabled="busy" @click="submit(() => api.getJob(j.id))">
          {{ j.title || j.source || j.id }}
        </button>
        <span class="meta">{{ STATUS[j.status] || j.status }} · {{ when(j.created) }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.recent { list-style: none; padding: 0; margin: 0; }
.recent li { display: flex; gap: 12px; align-items: center; padding: 4px 0; }
.recent button { max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.meta { color: #666; font-size: 13px; }
</style>
```

Replace `frontend/src/views/ReviewView.vue`:

```vue
<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import { formatTime, moveItem } from '../lib/pages.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['back', 'restart', 'started', 'score'])

const pages = ref(props.job.pages.slice())
const dragFrom = ref(null)
const links = ref({})
const error = ref('')

function remove(index) {
  pages.value = pages.value.filter((_, i) => i !== index)
}

function onDragStart(event, index) {
  dragFrom.value = index
  // Firefox refuses to start a drag unless data is set on the dataTransfer.
  event.dataTransfer.setData('text/plain', '')
}

function onDrop(index) {
  if (dragFrom.value !== null) pages.value = moveItem(pages.value, dragFrom.value, index)
  dragFrom.value = null
}

function duplicateLabel(dupId) {
  const original = props.job.pages.find((p) => p.id === dupId)
  return original ? `重复：同 ${formatTime(original.start)} 段` : '重复'
}

async function recognize() {
  error.value = ''
  if (props.job.score_order.length && !confirm('重新识谱会覆盖已保存的识谱结果和修改，继续吗？')) return
  try {
    emit('started', await api.recognize(props.job.id, pages.value.map((p) => p.id)))
  } catch (e) {
    error.value = e.message
  }
}

async function exportAs(fmt) {
  error.value = ''
  try {
    const res = await api.exportPages(props.job.id, pages.value.map((p) => p.id), fmt)
    links.value = { ...links.value, [fmt]: `${res.url}?v=${Date.now()}` }
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="card">
    <h2>3. 校对并导出（共 {{ pages.length }} 页）</h2>
    <p>拖动调整顺序，点 × 删除多余页面。标记"重复"的页面与前面某页内容相同（例如副歌重现）。</p>
    <div class="row">
      <button class="primary" :disabled="!pages.length" @click="recognize">识谱</button>
      <button v-if="job.score_order.length" @click="emit('score')">继续编辑识谱结果</button>
      <button class="primary" :disabled="!pages.length" @click="exportAs('png')">导出长图 PNG</button>
      <button class="primary" :disabled="!pages.length" @click="exportAs('pdf')">导出 PDF</button>
      <a v-if="links.png" :href="links.png" target="_blank">打开 PNG</a>
      <a v-if="links.pdf" :href="links.pdf" target="_blank">打开 PDF</a>
      <button @click="pages = job.pages.slice()">恢复全部</button>
      <button @click="emit('back')">重新框选</button>
      <button @click="emit('restart')">换一个视频</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <div
    v-for="(page, i) in pages"
    :key="page.id"
    class="card page"
    draggable="true"
    @dragstart="onDragStart($event, i)"
    @dragover.prevent
    @drop="onDrop(i)"
  >
    <div class="row meta">
      <strong>#{{ i + 1 }}</strong>
      <a :href="api.frameUrl(job.id, page.start)" target="_blank">
        {{ formatTime(page.start) }} – {{ formatTime(page.end) }}
      </a>
      <span v-if="page.duplicate_of !== null" class="dup">{{ duplicateLabel(page.duplicate_of) }}</span>
      <button class="remove" title="删除" @click="remove(i)">×</button>
    </div>
    <img :src="api.fileUrl(job.id, page.file)" draggable="false" />
  </div>
</template>

<style scoped>
.page { cursor: grab; }
.page img { display: block; max-width: 100%; }
.meta { margin-bottom: 8px; }
.dup { background: #e0e7ff; padding: 2px 8px; border-radius: 4px; font-size: 13px; }
.remove { margin-left: auto; }
</style>
```

Replace `frontend/vite.config.js`:

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { chunkSizeWarningLimit: 1500 }, // the lazily loaded alphaTab chunk is ~1.2 MB
  test: { environment: 'node' },
})
```

- [ ] **Step 2: Build and test**

Run: `cd frontend && npm test && npm run build`
Expected: 29 passed. The build succeeds and emits a separate alphaTab chunk of about 1.2 MB, and `dist/assets` contains `Bravura*.woff2`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TabRenderer.vue frontend/src/components/BeatEditor.vue frontend/src/views/ScoreView.vue frontend/src/api.js frontend/src/App.vue frontend/src/views/InputView.vue frontend/src/views/ReviewView.vue frontend/vite.config.js
git commit -m "feat: add the score editor with alphaTab preview, beat editing and .gp export

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Packaging, README and end-to-end acceptance

**Files:**
- Modify (replace whole file): `packaging/build.py` (it adds `--add-data` for `app/omr/models`)
- Modify: `README.md` (append a section)

- [ ] **Step 1: Replace `packaging/build.py`**

Replace `packaging/build.py`:

```python
"""Build the self-contained release folder and zip for the current OS.

Usage (from the repository root, after `cd frontend && npm ci && npm run build`):
    cd backend && uv run --group build python ../packaging/build.py v0.01
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"
OUT = ROOT / "build-release"
NAME = "video-to-tab"


def os_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    machine = platform.machine().lower()
    arches = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}
    arch = arches.get(machine, machine)
    return f"{system}-{arch}"


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if not (FRONTEND_DIST / "index.html").is_file():
        sys.exit("frontend/dist is missing: run `npm ci && npm run build` in frontend/ first")
    shutil.rmtree(OUT, ignore_errors=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            NAME,
            "--paths",
            str(BACKEND),
            "--distpath",
            str(OUT / "dist"),
            "--workpath",
            str(OUT / "work"),
            "--specpath",
            str(OUT),
            "--add-data",
            f"{FRONTEND_DIST}{os.pathsep}frontend/dist",
            "--add-data",  # the glyph classifier; the training fonts are not needed at runtime
            f"{BACKEND / 'app' / 'omr' / 'models'}{os.pathsep}app/omr/models",
            "--collect-submodules",
            "uvicorn",
            "--collect-submodules",
            "app",
            "--collect-all",
            "av",
            "--collect-all",
            "yt_dlp",
            str(BACKEND / "app" / "launcher.py"),
        ],
        check=True,
    )
    folder = OUT / "dist" / NAME
    shutil.copy(ROOT / "packaging" / "README-release.txt", folder / "README.txt")
    archive = shutil.make_archive(
        str(OUT / f"{NAME}-{version}-{os_tag()}"), "zip", OUT / "dist", NAME
    )
    print(f"built {archive}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Append the README section**

Append to the end of `README.md`:

```markdown
## 识谱与导出 .gp

在校对页点“识谱”，识别完成后进入识谱页：

- 顶部可设置标题、速度（识别不读速度，默认 120）和定弦（按弦数给预设，也可自定义音名）。
- 橙色块是需要检查的拍；“下一个待检查”逐个跳转。点击任意一拍打开编辑面板：对照原图片段修改各弦品格（留空 = 无音，x = 闷音）、时值、附点、三连音、休止，前后插入或删除拍，“确认无误”清除标记。
- 修改自动保存；刷新页面或重启程序后，可在首页“最近的任务”中继续。
- 小节编号与原谱一致：视频未出现的开头小节补为休止；中间漏识别的小节补为休止并标为待检查。
- “导出 .gp”生成 Guitar Pro 7/8 文件。
```

- [ ] **Step 3: End-to-end acceptance (no browser needed)**

The helper scripts are in `/tmp/vtt/accept/`:
- `api_flow.sh BASE VIDEO` drives upload → region → analysis → recognize through the API and prints the job id.
- `export_gp.mjs FRONTEND score.json OUT.gp` runs the editor's own `scoreToTex` with alphaTab's `Gp7Exporter`.
- `compare.py EXPORT GT TRACK LO HI` reads the export with `gpif.read_track`, numbering bar k as measure k, and compares it with the ground truth.

If any script is missing, stop and report NEEDS_CONTEXT.

```bash
cd frontend && npm run build && cd ../backend
rm -rf /tmp/vtt/accept/data
(VTT_DATA_DIR=/tmp/vtt/accept/data nohup uv run uvicorn app.main:app --port 8791 > /tmp/vtt/accept/uv.log 2>&1 &)
sleep 3
ID=$(/tmp/vtt/accept/api_flow.sh http://127.0.0.1:8791 /tmp/vtt/gp1/source.mp4); echo "job $ID"
node /tmp/vtt/accept/export_gp.mjs ../frontend /tmp/vtt/accept/data/$ID/score.json /tmp/vtt/accept/export.gp
PYTHONPATH=. uv run python /tmp/vtt/accept/compare.py /tmp/vtt/accept/export.gp "../data/tabs/[7弦]AveMujica+KiLLKiSS.gp" "Guitar Mutsumi" 13 148
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8791/          # expect 200 (built editor served)
pkill -f "port 8791"
```

Expected:
- `compare.py` prints `measure_alignment` 100.0, `fret_recall` 99.92, `fret_precision` 99.77, `beat_grouping` 99.76, `duration_on_grouped` 99.88 and `extra_measures` 0. These are the recognition-only numbers, which shows the export is lossless.
- The last `curl` returns `200`.

- [ ] **Step 4: Build the release package once and smoke-test it**

Run:
```bash
cd backend && uv run --group build python ../packaging/build.py dev 2>&1 | tail -1
ls ../build-release/dist/video-to-tab/_internal/app/omr/models/   # expect glyphs.xml.gz
```
Expected: `built …/build-release/video-to-tab-dev-linux-x64.zip`, and `glyphs.xml.gz` inside the bundle.

- [ ] **Step 5: Commit**

```bash
git add packaging/build.py README.md
git commit -m "build: bundle the OMR model in releases; document the score editor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Manual check for the user (after merge)

Open the app, run the sample video through 识谱, correct one flagged beat, export the `.gp`, and open it in Guitar Pro 8.
