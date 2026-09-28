# Tab Recognition (OMR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize the stitched tab line images this app already produces into a structured score (strings, frets, dead notes, rests, beats and durations), and ship an evaluation CLI that measures accuracy against a Guitar Pro 7/8 file.

**Architecture:** A new package `backend/app/omr/`, built in four layers.
1. **Data model and ground truth:** `model.py` holds the data model; `gpif.py` reads GP7/8 files as ground truth.
2. **Glyph classifier:** `glyphs.py` combines NumPy HOG with an MLP, trained on multi-font synthetic glyphs by `train.py`. The trained model is committed.
3. **Rhythm:** `rhythm.py` reads stems, beams and dots below the staff. `solve.py` turns that evidence into durations, choosing the combination that fills each measure exactly.
4. **Recognition and evaluation:** `recognize.py` recognizes each line and numbers the measures; `evaluate.py` is the command-line accuracy report.

All of this code was prototyped and measured before the plan was written.

**Tech Stack:** Python 3.12, NumPy, OpenCV 5 (no `cv2.ml`), Pillow (training only; already installed via img2pdf), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-29-tab-recognition-design.md` (read its final section "原型阶段的修订", which supersedes earlier sections where they differ)

## Global Constraints

- No new runtime or dev dependencies. `cv2.ml` / `cv2.HOGDescriptor` do not exist in the locked OpenCV 5.0; the classifier is NumPy.
- Package layout: `backend/app/omr/{model,gpif,glyphs,train,rhythm,solve,recognize,evaluate}.py`, `backend/app/omr/fonts/` (subset fonts + licenses + README), `backend/app/omr/models/glyphs.xml.gz`.
- `Note.string` 0 = lowest string = bottom tab line. Default tunings: 6 strings `[40,45,50,55,59,64]`, 7 strings `[35,40,45,50,55,59,64]`.
- User-facing CLI output may be English (developer tools); no existing app/API/frontend behavior changes.
- Ground-truth files live under `data/` (gitignored). Tests that need them must `skipif` when absent; CI (release workflow) runs `pytest` without them.
- Backend commands run from `backend/` via `uv run …`. `ruff check` + `ruff format --check` clean (line length 100); test output has zero warnings.

## Review Focus

The inputs most likely to hurt a user that the spec implies but the evaluation sample never exercises. Each is pinned by a test in the task that owns the code.

1. **A standard 6-string tab** must be read as 6 strings with standard tuning. `detect_staves`'s inverted pass can report the gaps between lines as a fake 7-line staff; the prototype hit exactly this. → Task 4, `test_six_string_line_with_two_digit_frets_and_chords`.
2. **Two-digit frets (10–17) and chords on one beat** must become one number per string, not separate digits or separate beats. → Task 4, same test.
3. **A tab without rhythm marks** must still produce beats whose durations fill each measure, with low beat confidence (below 0.7) so the review UI can flag them. → Task 4, `test_line_without_rhythm_marks_still_fills_each_measure`.
4. **An image without any tab**, or the blank margin after a final bar line, must give no measures rather than a crash or a phantom whole-rest measure. → Task 4, `test_image_without_tab_gives_empty_score`; the margin case is exercised by the synthetic line's 20 px tail.
5. **A GP file that lacks the requested track name** must raise a `ValueError` that lists the available track names. → Task 1, `test_unknown_track_name_is_a_clear_error`.

## Prototype evidence

Measured on `/tmp/vtt/gp1/out`, i.e. the pipeline's 39 line images of bilibili BV1yBcEeXEVn, against the Guitar Mutsumi track for measures 13–148 (136 measures, 822 beats, 1296 notes):

| Metric | Result |
|---|---|
| Measure alignment | 100% |
| Fret recall | 99.92% |
| Fret precision | 99.77% |
| Beat grouping | 99.76% |
| Duration on grouped beats | 99.88% |

Training takes about 160 s. Recognizing the whole video takes about 3 s on top of the existing pipeline.

## File Structure

```
backend/app/omr/__init__.py        # empty package marker
backend/app/omr/model.py           # Score / Measure / Beat / Note dataclasses, JSON round trip, tunings
backend/app/omr/gpif.py            # read GP7/8 (.gp zip → Content/score.gpif) into Score
backend/app/omr/glyphs.py          # ink extraction, blobs, HOG+MLP GlyphClassifier, synthetic glyph generator
backend/app/omr/train.py           # CLI: train the classifier → models/glyphs.xml.gz
backend/app/omr/fonts/             # subset training fonts, licenses, README (copied in Task 2)
backend/app/omr/models/glyphs.xml.gz   # trained model (generated in Task 2, committed)
backend/app/omr/rhythm.py          # stems / beams / flags / dots / tuplet digits below the staff
backend/app/omr/solve.py           # duration candidates + measure-sum dynamic program
backend/app/omr/recognize.py       # per-line recognition, measure numbering (Viterbi), build_score
backend/app/omr/evaluate.py        # CLI: accuracy report against a GP file
backend/tests/test_omr_model.py    # Task 1
backend/tests/test_omr_glyphs.py   # Task 2
backend/tests/test_omr_solve.py    # Task 3
backend/tests/test_omr_recognize.py  # Task 4
README.md                          # Task 4: OMR section
```

Expected full-suite counts after each task (from `backend/`, `uv run pytest -q`):

| After task | Passed | Deselected |
|---|---|---|
| 1 | 84 | 1 |
| 2 | 85 | 1 |
| 3 | 89 | 1 |
| 4 | 92 | 1 |

If `data/tabs/[7弦]AveMujica+KiLLKiSS.gp` is absent, one test is skipped instead.

---

### Task 1: Score model and Guitar Pro ground-truth reader

**Files:**
- Create: `backend/app/omr/__init__.py` (empty), `backend/app/omr/model.py`, `backend/app/omr/gpif.py`
- Test: `backend/tests/test_omr_model.py`

**Interfaces:**
- Produces (`model.py`):
  - `STANDARD_TUNINGS: dict[int, list[int]]`
  - `TUPLET_RATIO`
  - `Note(string, fret, confidence=1.0, dead=False)`
  - `Beat(duration=4, dots=0, tuplet=None, rest=False, notes=[], x=0, confidence=1.0)`, with `.length() -> Fraction` (in whole notes)
  - `Measure(number=None, time=(4,4), beats=[], line=0, x0=0, x1=0, confidence=1.0)`, with `.capacity() -> Fraction`
  - `Score(strings=6, tuning=[], tempo=None, measures=[])`, with `.to_dict()` and `Score.from_dict(d)`
- Produces (`gpif.py`):
  - `NOTE_VALUES`
  - `track_names(path) -> list[str]`
  - `read_track(path, track_name) -> Score`: reads the first voice; the tuning comes from the track; dead notes from `Muted`. Raises `ValueError("track 'X' not in [...]")` when the track name is not in the file.

- [ ] **Step 1: Write the failing test `backend/tests/test_omr_model.py`**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_omr_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.omr'`

- [ ] **Step 3: Write the implementation**

Create an empty `backend/app/omr/__init__.py`.

`backend/app/omr/model.py`:

```python
"""Recognized-score data model, shared by recognition, evaluation and (later) the editor UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Score:
        measures = []
        for m in d.get("measures", []):
            beats = [
                Beat(**{**b, "notes": [Note(**n) for n in b.get("notes", [])]})
                for b in m.get("beats", [])
            ]
            measures.append(Measure(**{**m, "time": tuple(m.get("time", (4, 4))), "beats": beats}))
        return Score(d.get("strings", 6), d.get("tuning", []), d.get("tempo"), measures)
```

`backend/app/omr/gpif.py`:

```python
"""Read one track of a Guitar Pro 7/8 file (a zip holding Content/score.gpif) as a Score."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from app.omr.model import Beat, Measure, Note, Score

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


def read_track(path: Path, track_name: str) -> Score:
    """Notes (String/Fret), durations (NoteValue, dots, PrimaryTuplet); first voice only."""
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
                    beat_notes.append(note)
                beat_notes.sort(key=lambda n: n.string)
                out.append(Beat(duration, dots, tuplet, not beat_notes, beat_notes))
        measures.append(Measure(number, (num, den), out))
    return Score(len(tuning), tuning, tempo, measures)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_omr_model.py -v`
Expected: 3 passed. If the GP file is absent, 2 passed and 1 skipped.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 84 passed, 1 deselected; lint clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/omr/__init__.py backend/app/omr/model.py backend/app/omr/gpif.py backend/tests/test_omr_model.py
git commit -m "feat: add OMR score model and Guitar Pro ground-truth reader

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Glyph classifier, training script, fonts and trained model

**Files:**
- Create: `backend/app/omr/glyphs.py`, `backend/app/omr/train.py`
- Create (copied assets): `backend/app/omr/fonts/` (29 files: subset `.ttf` files, `LICENSE-*.txt`, `README.md`)
- Create (generated): `backend/app/omr/models/glyphs.xml.gz`
- Test: `backend/tests/test_omr_glyphs.py`

**Interfaces:**
- Consumes: `app.stitch.INK_LEVEL`.
- Produces (`glyphs.py`):
  - Constants:
    - `CLASSES`: 17 labels, `0`–`9`, `x`, `paren`, `rest_block`, `rest_4`, `rest_8`, `rest_16` and `other`
    - `DIGITS`
    - `MODEL_PATH = app/omr/models/glyphs.xml.gz`
    - `FONT_DIR`
    - `HERSHEY`
  - Ink extraction:
    - `gray_of(img)`
    - `staff_ink(gray, spacing, lines=None) -> uint8 mask`
    - `otsu_ink(crop)`
  - Blobs:
    - `Blob(x, y, w, h, mask)`, with `.cx` and `.cy`
    - `components(ink, min_area=3) -> list[Blob]`
    - `union(blobs)`
    - `merge_pieces(blobs, spacing)`
  - Features:
    - `normalize(mask)`
    - `hog(images)`
    - `shape_features(blob, spacing)`
    - `features(blobs, spacings)`
  - Classifier:
    - `GlyphClassifier`: `.fit(...)`, `.save(path)`, `GlyphClassifier.load(path=MODEL_PATH)`, and `.classify(blobs, spacing) -> list[(label, prob)]`
    - `default_classifier()`: the model, loaded once and cached
  - Synthetic data:
    - `font_files(system=False, exclude=())`
    - `render_text`, `render_rest`, `render_other`
    - `synth_sample(label, rng, fonts) -> (Blob, spacing) | None`
    - `synth_dataset(...)`
    - `debug_sheet(...)`
- Produces (`train.py`): `python -m app.omr.train [--per-class N --epochs E --seed S --system-fonts --exclude ... --out PATH]`.

- [ ] **Step 1: Copy the training fonts**

The fonts are binary files, so they are copied rather than written out. They are open-licensed and were subset to the few characters the generator draws; `README.md` inside the folder records how.

```bash
mkdir -p backend/app/omr/fonts
cp /tmp/vtt/omr-assets/fonts/* backend/app/omr/fonts/
ls backend/app/omr/fonts | wc -l      # expect 29
du -sh backend/app/omr/fonts          # expect about 276K
```

If `/tmp/vtt/omr-assets/fonts` is missing, stop and report NEEDS_CONTEXT.

- [ ] **Step 2: Write the failing test `backend/tests/test_omr_glyphs.py`**

```python
import numpy as np
import pytest

from app.omr.glyphs import CLASSES, MODEL_PATH, GlyphClassifier, font_files, synth_sample


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_classifier_on_fresh_synthetic_glyphs():
    clf = GlyphClassifier.load()
    rng = np.random.default_rng(123)
    fonts = font_files()
    hits = total = 0
    for label in CLASSES[:10]:
        for _ in range(20):
            r = synth_sample(label, rng, fonts)
            if r is None:
                continue
            total += 1
            hits += clf.classify([r[0]], r[1])[0][0] == label
    assert hits / total > 0.9
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_omr_glyphs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.omr.glyphs'`

- [ ] **Step 4: Write `backend/app/omr/glyphs.py`**

```python
"""Glyph features, classifier and synthetic training data.

OpenCV 5 moved `cv2.ml` and `cv2.HOGDescriptor` to contrib, so HOG and the linear
classifier are implemented here with NumPy. The model is a softmax-regression layer on
top of HOG plus a few size/shape features, trained on synthetic glyphs that go through
exactly the same ink extraction as real tab images (see `staff_ink` and `glyph_crops`).
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.stitch import INK_LEVEL

CLASSES = (
    *"0123456789",
    "x",  # dead note
    "paren",  # ( or ) around a tied note
    "rest_block",  # whole / half rest: filled bar hanging from or sitting on a line
    "rest_4",
    "rest_8",
    "rest_16",
    "other",  # anything else: dashes, slides, arcs, brackets, dots, fragments
)
DIGITS = CLASSES[:10]
GLYPH_W, GLYPH_H = 24, 32
CELL, NBINS = 4, 9
MODEL_PATH = Path(__file__).parent / "models" / "glyphs.xml.gz"
FONT_DIR = Path(__file__).parent / "fonts"


# ---------------------------------------------------------------- ink extraction


def gray_of(img: np.ndarray) -> np.ndarray:
    """Grayscale with dark ink on a light background (a dark theme is inverted)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return 255 - gray if np.median(gray) < 128 else gray


def staff_ink(gray: np.ndarray, spacing: float, lines: list[int] | None = None) -> np.ndarray:
    """Ink (uint8 0/1) without staff lines.

    Long horizontal runs are removed everywhere. On the known staff lines, the short
    segments left between glyphs are removed too: a pixel in a line's band goes unless
    ink continues directly above and below the band (a glyph stroke crossing the line)."""
    ink = (gray < INK_LEVEL).astype(np.uint8)
    h = ink.shape[0]
    k = max(9, int(round(spacing * 1.2)))
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    rest = ink & (1 - horiz)
    up = np.zeros_like(rest)
    down = np.zeros_like(rest)
    up[2:] = rest[1:-1] | rest[:-2]
    down[:-2] = rest[1:-1] | rest[2:]
    rest |= horiz & up & down  # keep strokes that cross a removed line
    for y in lines or []:
        lo, hi = max(0, y - 3), min(h, y + 4)
        dark = np.flatnonzero(ink[lo:hi].mean(axis=1) > 0.25) + lo
        if dark.size == 0:
            continue
        top, bottom = int(dark.min()), int(dark.max())
        above = rest[top - 1] if top >= 1 else np.zeros(ink.shape[1], np.uint8)
        below = rest[bottom + 1] if bottom + 1 < h else np.zeros(ink.shape[1], np.uint8)
        # slanted strokes shift a pixel or two across the band
        spread = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        crossing = cv2.dilate(above[None, :], spread)[0] & cv2.dilate(below[None, :], spread)[0]
        rest[top : bottom + 1] &= crossing[None, :]
    return rest


def otsu_ink(crop: np.ndarray) -> np.ndarray:
    """Otsu threshold on a small crop (uint8 0/1); empty when there is no real contrast.
    Used where no staff lines interfere, e.g. thin light-gray measure numbers."""
    thr, ink = cv2.threshold(crop, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if np.median(crop) - thr < 25:
        return np.zeros_like(crop)
    return ink


@dataclass
class Blob:
    x: int
    y: int
    w: int
    h: int
    mask: np.ndarray  # bool crop

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def components(ink: np.ndarray, min_area: int = 3) -> list[Blob]:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area:
            continue
        out.append(Blob(x, y, w, h, labels[y : y + h, x : x + w] == i))
    return out


def union(blobs: list[Blob]) -> Blob:
    x0 = min(b.x for b in blobs)
    y0 = min(b.y for b in blobs)
    x1 = max(b.x + b.w for b in blobs)
    y1 = max(b.y + b.h for b in blobs)
    mask = np.zeros((y1 - y0, x1 - x0), bool)
    for b in blobs:
        mask[b.y - y0 : b.y - y0 + b.h, b.x - x0 : b.x - x0 + b.w] |= b.mask
    return Blob(x0, y0, x1 - x0, y1 - y0, mask)


def merge_pieces(blobs: list[Blob], spacing: float) -> list[Blob]:
    """Join pieces of one glyph (a stroke cut by line removal): boxes that overlap
    horizontally by most of the narrower one and are vertically close."""
    blobs = sorted(blobs, key=lambda b: b.x)
    groups: list[list[Blob]] = []
    for b in blobs:
        for g in groups:
            u = union(g)
            ov = min(u.x + u.w, b.x + b.w) - max(u.x, b.x)
            gap = max(u.y, b.y) - min(u.y + u.h, b.y + b.h)
            height = max(u.y + u.h, b.y + b.h) - min(u.y, b.y)
            # never stack two glyphs: a merged piece stays within one line spacing
            if ov >= 0.6 * min(u.w, b.w) and gap <= 0.15 * spacing + 1 and height <= spacing:
                g.append(b)
                break
        else:
            groups.append([b])
    return [union(g) for g in groups]


# ---------------------------------------------------------------- features


def normalize(mask: np.ndarray) -> np.ndarray:
    """Binary crop -> GLYPH_H x GLYPH_W float image, aspect ratio kept, centered."""
    h, w = mask.shape
    scale = min((GLYPH_W - 4) / w, (GLYPH_H - 4) / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    small = cv2.resize(mask.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((GLYPH_H, GLYPH_W), np.float32)
    y0, x0 = (GLYPH_H - nh) // 2, (GLYPH_W - nw) // 2
    out[y0 : y0 + nh, x0 : x0 + nw] = small
    return out


def hog(images: np.ndarray) -> np.ndarray:
    """HOG for a batch (N, H, W): 4x4 cells, 9 unsigned bins with linear interpolation,
    2x2-cell blocks at 1-cell stride, L2-Hys normalized."""
    n, h, w = images.shape
    gx = np.zeros_like(images)
    gy = np.zeros_like(images)
    gx[:, :, 1:-1] = images[:, :, 2:] - images[:, :, :-2]
    gy[:, 1:-1, :] = images[:, 2:, :] - images[:, :-2, :]
    mag = np.hypot(gx, gy)
    ang = (np.degrees(np.arctan2(gy, gx)) % 180.0) / (180.0 / NBINS)
    lo = np.floor(ang).astype(int) % NBINS
    hi = (lo + 1) % NBINS
    frac = ang - np.floor(ang)
    ch, cw = h // CELL, w // CELL
    hist = np.zeros((n, ch, cw, NBINS), np.float32)
    cell_y = (np.arange(h) // CELL)[None, :, None]
    cell_x = (np.arange(w) // CELL)[None, None, :]
    idx_n = np.arange(n)[:, None, None]
    shape = (n, h, w)
    cy = np.broadcast_to(cell_y, shape)
    cx = np.broadcast_to(cell_x, shape)
    nn = np.broadcast_to(idx_n, shape)
    np.add.at(hist, (nn, cy, cx, lo), mag * (1 - frac))
    np.add.at(hist, (nn, cy, cx, hi), mag * frac)
    blocks = []
    for by in range(ch - 1):
        for bx in range(cw - 1):
            v = hist[:, by : by + 2, bx : bx + 2].reshape(n, -1)
            v = v / np.sqrt((v**2).sum(axis=1, keepdims=True) + 1e-6)
            v = np.minimum(v, 0.2)
            v = v / np.sqrt((v**2).sum(axis=1, keepdims=True) + 1e-6)
            blocks.append(v)
    return np.concatenate(blocks, axis=1)


def shape_features(blob: Blob, spacing: float) -> np.ndarray:
    return np.array(
        [
            blob.h / spacing,
            blob.w / spacing,
            np.log(blob.w / blob.h),
            blob.mask.mean(),
        ],
        np.float32,
    )


def features(blobs: list[Blob], spacings: list[float]) -> np.ndarray:
    if not blobs:
        return np.zeros((0, 1), np.float32)
    imgs = np.stack([normalize(b.mask) for b in blobs])
    extra = np.stack([shape_features(b, s) for b, s in zip(blobs, spacings, strict=True)])
    return np.concatenate([hog(imgs), extra], axis=1).astype(np.float32)


# ---------------------------------------------------------------- classifier


class GlyphClassifier:
    """One-hidden-layer perceptron (ReLU, softmax output) on standardized features.

    Parameters: W1 (D, H), b1 (H,), W2 (H, C), b2 (C,). The softmax output doubles as
    the per-glyph confidence."""

    def __init__(self, mean, std, W1, b1, W2, b2):
        self.mean, self.std = mean, std
        self.W1, self.b1, self.W2, self.b2 = W1, b1, W2, b2

    def proba(self, X: np.ndarray) -> np.ndarray:
        h = np.maximum(((X - self.mean) / self.std) @ self.W1 + self.b1, 0)
        z = h @ self.W2 + self.b2
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def classify(self, blobs: list[Blob], spacing: float) -> list[tuple[str, float]]:
        if not blobs:
            return []
        p = self.proba(features(blobs, [spacing] * len(blobs)))
        best = p.argmax(axis=1)
        return [(CLASSES[i], float(p[k, i])) for k, i in enumerate(best)]

    _KEYS = ("mean", "std", "W1", "b1", "W2", "b2")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fs = cv2.FileStorage(str(path), cv2.FILE_STORAGE_WRITE)
        fs.write("classes", ",".join(CLASSES))
        for k in self._KEYS:
            v = getattr(self, k)
            fs.write(k, v[None, :] if v.ndim == 1 else v)
        fs.release()

    @staticmethod
    def load(path: Path = MODEL_PATH) -> GlyphClassifier:
        fs = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
        if fs.getNode("classes").string() != ",".join(CLASSES):
            raise ValueError("glyph model classes do not match; retrain with app.omr.train")
        m = [fs.getNode(k).mat() for k in GlyphClassifier._KEYS]
        fs.release()
        m = [
            v[0] if k in ("mean", "std", "b1", "b2") else v
            for k, v in zip(GlyphClassifier._KEYS, m, strict=True)
        ]
        return GlyphClassifier(*m)

    @staticmethod
    def fit(
        X: np.ndarray,
        y: np.ndarray,
        hidden: int = 192,
        epochs: int = 30,
        l2: float = 1e-4,
        seed: int = 0,
    ) -> GlyphClassifier:
        rng = np.random.default_rng(seed)
        mean = X.mean(axis=0).astype(np.float32)
        std = (X.std(axis=0) + 1e-3).astype(np.float32)
        Xs = ((X - mean) / std).astype(np.float32)
        n, d = Xs.shape
        c = len(CLASSES)
        params = [
            (rng.normal(0, np.sqrt(2 / d), (d, hidden))).astype(np.float32),
            np.zeros(hidden, np.float32),
            (rng.normal(0, np.sqrt(2 / hidden), (hidden, c))).astype(np.float32),
            np.zeros(c, np.float32),
        ]
        m1 = [np.zeros_like(p) for p in params]
        m2 = [np.zeros_like(p) for p in params]
        Y = np.eye(c, dtype=np.float32)[y]
        b1, b2, t = 0.9, 0.999, 0
        steps = epochs * ((n + 127) // 128)
        for _ in range(epochs):
            order = rng.permutation(n)
            for s in range(0, n, 128):
                i = order[s : s + 128]
                W1, c1, W2, c2 = params
                a = Xs[i] @ W1 + c1
                h = np.maximum(a, 0)
                z = h @ W2 + c2
                z -= z.max(axis=1, keepdims=True)
                p = np.exp(z)
                p /= p.sum(axis=1, keepdims=True)
                g = (p - Y[i]) / len(i)
                gW2 = h.T @ g + l2 * W2
                gc2 = g.sum(axis=0)
                gh = (g @ W2.T) * (a > 0)
                gW1 = Xs[i].T @ gh + l2 * W1
                gc1 = gh.sum(axis=0)
                t += 1
                lr = 1e-3 * 0.5 * (1 + np.cos(np.pi * t / steps))  # cosine decay
                for k, grad in enumerate((gW1, gc1, gW2, gc2)):
                    m1[k] = b1 * m1[k] + (1 - b1) * grad
                    m2[k] = b2 * m2[k] + (1 - b2) * grad**2
                    corr = np.sqrt(1 - b2**t) / (1 - b1**t)
                    params[k] -= lr * corr * m1[k] / (np.sqrt(m2[k]) + 1e-8)
        return GlyphClassifier(mean, std, *params)


_CACHED: GlyphClassifier | None = None


def default_classifier() -> GlyphClassifier:
    global _CACHED
    if _CACHED is None:
        _CACHED = GlyphClassifier.load()
    return _CACHED


# ---------------------------------------------------------------- synthetic data

HERSHEY = [
    cv2.FONT_HERSHEY_SIMPLEX,
    cv2.FONT_HERSHEY_DUPLEX,
    cv2.FONT_HERSHEY_COMPLEX,
    cv2.FONT_HERSHEY_TRIPLEX,
    cv2.FONT_HERSHEY_PLAIN,
    cv2.FONT_HERSHEY_COMPLEX_SMALL,
]


def font_files(system: bool = False, exclude: tuple[str, ...] = ()) -> list[str]:
    """Bundled fonts (reproducible training); optionally also system fonts with digits."""
    files = sorted(glob.glob(str(FONT_DIR / "*.[ot]tf")))
    if system:
        for pattern in (
            "/usr/share/fonts/**/*.ttf",
            "/usr/share/fonts/**/*.otf",
            "C:/Windows/Fonts/*.ttf",
            "/Library/Fonts/*.ttf",
        ):
            files += sorted(glob.glob(pattern, recursive=True))
    skip = ("mono", "symbol", "emoji", "wingding", "webding", "dingbat", "math", *exclude)
    out, seen = [], set()
    for f in files:
        key = Path(f).name.lower()
        if key in seen or any(s.lower() in key for s in skip):
            continue
        seen.add(key)
        out.append(f)
    return out


def _crop_alpha(a: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(a > 20)
    if ys.size == 0:
        return np.zeros((1, 1), np.uint8)
    return a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def render_text(text: str, font, rng: np.random.Generator) -> np.ndarray:
    """Hi-res alpha (uint8) of text; font is a TTF path or a Hershey id."""
    if isinstance(font, int):
        canvas = np.zeros((200, 100 + 90 * len(text)), np.uint8)
        scale = 3.0 if font != cv2.FONT_HERSHEY_COMPLEX_SMALL else 4.0
        thick = int(rng.integers(2, 8))
        cv2.putText(canvas, text, (20, 150), font, scale, 255, thick, cv2.LINE_AA)
        return _crop_alpha(canvas)
    from PIL import Image, ImageDraw, ImageFont

    f = ImageFont.truetype(font, 96)
    img = Image.new("L", (100 + 80 * len(text), 180), 0)
    ImageDraw.Draw(img).text((20, 20), text, font=f, fill=255)
    return _crop_alpha(_reweight(np.asarray(img), rng))


def _reweight(alpha: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Thinner or bolder strokes: erode/dilate the hi-res rendering."""
    k = int(rng.choice([-3, -2, -1, 0, 0, 0, 1, 2]))
    if k == 0:
        return alpha
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(k) + 1, 2 * abs(k) + 1))
    return cv2.erode(alpha, kernel) if k < 0 else cv2.dilate(alpha, kernel)


def _thick_line(canvas, pts, t):
    cv2.polylines(canvas, [np.int32(pts)], False, 255, t, cv2.LINE_AA)


def render_rest(kind: str, rng: np.random.Generator) -> np.ndarray:
    """Procedural hi-res rest symbols (sizes relative to a 100 px staff spacing)."""
    c = np.zeros((260, 200), np.uint8)
    t = int(rng.integers(8, 16))
    if kind == "rest_block":
        w, h = int(rng.uniform(40, 80)), int(rng.uniform(18, 50))
        cv2.rectangle(c, (60, 100), (60 + w, 100 + h), 255, -1)
    elif kind == "rest_8" or kind == "rest_16":
        heads = 1 if kind == "rest_8" else 2
        top, dx = 40, rng.uniform(40, 60)
        r = int(rng.uniform(11, 18))
        for k in range(heads):
            y = top + k * 45
            cx = 80 - k * 10
            cv2.circle(c, (cx, y + r), r, 255, -1, cv2.LINE_AA)
            curve = [(cx, y + 2 * r - 3), (cx + dx * 0.5, y + 2 * r), (cx + dx, y)]
            _thick_line(c, curve, max(4, t // 2))
        x_top = 80 + dx
        length = rng.uniform(90, 130) + 45 * (heads - 1)
        _thick_line(c, [(x_top, top), (x_top - length * 0.3, top + length)], t)
    elif kind == "rest_4":
        x, y = 90.0, 20.0
        pts = [
            (x, y),
            (x + 35, y + 45),
            (x + 5, y + 80),
            (x + 40, y + 125),
            (x + 10, y + 125),
            (x + 25, y + 170),
        ]
        pts = [(px + rng.normal(0, 3), py + rng.normal(0, 3)) for px, py in pts]
        _thick_line(c, pts[:4], t + 6)
        _thick_line(c, pts[3:], t)
    return _crop_alpha(c)


def render_other(rng: np.random.Generator, fonts: list) -> np.ndarray:
    c = np.zeros((200, 200), np.uint8)
    t = int(rng.integers(4, 14))
    kind = rng.integers(0, 9)
    if kind == 0:  # dash
        w = int(rng.uniform(20, 80))
        cv2.rectangle(c, (50, 100), (50 + w, 100 + t), 255, -1)
    elif kind == 1:  # slide / slash
        dx, dy = rng.uniform(30, 90), rng.uniform(30, 90) * rng.choice([-1, 1])
        _thick_line(c, [(60, 100), (60 + dx, 100 + dy)], t)
    elif kind == 2:  # dot
        cv2.circle(c, (100, 100), int(rng.uniform(5, 14)), 255, -1)
    elif kind == 3:  # arc (tie fragment)
        cv2.ellipse(
            c,
            (100, 60),
            (int(rng.uniform(40, 90)), int(rng.uniform(10, 40))),
            0,
            int(rng.uniform(0, 60)),
            int(rng.uniform(100, 180)),
            255,
            max(3, t // 2),
            cv2.LINE_AA,
        )
    elif kind == 4:  # vertical tick (stem end, bar fragment)
        cv2.rectangle(c, (100, 40), (100 + max(3, t // 2), 40 + int(rng.uniform(30, 120))), 255, -1)
    elif kind == 5:  # fragment of a digit
        a = render_text(str(rng.integers(0, 10)), fonts[rng.integers(len(fonts))], rng)
        h, w = a.shape
        if rng.random() < 0.5:
            return a[: max(2, int(h * rng.uniform(0.25, 0.5)))]
        return a[:, : max(2, int(w * rng.uniform(0.25, 0.5)))]
    else:  # other characters that appear near tab staves
        ch = str(rng.choice(list("<>~^vPMhpbrsHT/\\*+=")))
        return render_text(ch, fonts[rng.integers(len(fonts))], rng)
    return _crop_alpha(c)


def _jpeg(img: np.ndarray, q: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if ok else img


def synth_sample(label: str, rng: np.random.Generator, fonts: list) -> tuple[Blob, float] | None:
    """Draw one glyph onto a small patch of staff lines, degrade it, and extract it with
    the same code the recognizer uses. Returns the extracted blob and the spacing."""
    s = float(rng.uniform(11, 40))  # staff spacing in px
    if label in DIGITS or label in ("paren", "x"):
        if label == "paren":
            text = str(rng.choice(["(", ")"]))
        elif label == "x":
            text = str(rng.choice(["x", "X", "\u00d7"]))
        else:
            text = label
        alpha = render_text(text, fonts[rng.integers(len(fonts))], rng)
        target_h = s * rng.uniform(0.45, 0.95)
        if label == "paren":
            target_h *= rng.uniform(1.05, 1.35)
        target_h = max(target_h, 7.0)
    elif label.startswith("rest"):
        alpha = render_rest(label, rng)
        target_h = alpha.shape[0] / 100 * s * rng.uniform(0.8, 1.2)
    else:
        alpha = render_other(rng, fonts)
        target_h = alpha.shape[0] / 100 * s * rng.uniform(0.5, 1.4)
    target_h = float(np.clip(target_h, 3, 40))
    scale = target_h / alpha.shape[0]
    gw = max(1, round(alpha.shape[1] * scale))
    gh = max(1, round(alpha.shape[0] * scale))
    if gw > 3 * s + 20:
        return None
    glyph = cv2.resize(alpha, (gw, gh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255

    ph, pw = int(4 * s) + gh, int(3 * s) + gw
    bg = rng.uniform(215, 255)
    patch = np.full((ph, pw), bg, np.float32)
    mid = ph // 2
    free = label in DIGITS and rng.random() < 0.25  # like a measure number: Otsu, no lines
    lines_on = not free and rng.random() < 0.85
    line_val = rng.uniform(0, 150)
    lt = 1 if rng.random() < 0.8 else 2
    line_ys = []
    if lines_on:
        for k in range(-3, 4):
            y = int(round(mid + k * s))
            if 0 <= y < ph:
                patch[y : y + lt] = line_val
                line_ys.append(y)
    gx = (pw - gw) // 2 + int(rng.integers(-2, 3))
    if label.startswith("rest"):
        gy = mid - gh // 2 + int(rng.normal(0, s * 0.3))
    else:
        gy = mid - gh // 2 + int(rng.normal(0, s * 0.06))
    gy = int(np.clip(gy, 0, ph - gh))
    if lines_on and rng.random() < 0.65:  # white box behind the glyph (GP, MuseScore...)
        pad = int(rng.integers(0, 4))
        patch[max(0, gy - pad) : gy + gh + pad, max(0, gx - pad) : gx + gw + pad] = bg
    ink = rng.uniform(0, 130 if free else 90)
    region = patch[gy : gy + gh, gx : gx + gw]
    patch[gy : gy + gh, gx : gx + gw] = region * (1 - glyph) + ink * glyph

    if rng.random() < 0.5:
        patch = cv2.GaussianBlur(patch, (0, 0), rng.uniform(0.3, 0.8))
    patch += rng.normal(0, rng.uniform(0, 6), patch.shape)
    img = np.clip(patch, 0, 255).astype(np.uint8)
    if rng.random() < 0.6:
        img = _jpeg(img, int(rng.integers(35, 95)))

    blobs = components(otsu_ink(img) if free else staff_ink(img, s, line_ys), min_area=2)
    near = [
        b
        for b in blobs
        if b.x < gx + gw + 1 and b.x + b.w > gx - 1 and b.y < gy + gh + 1 and b.y + b.h > gy - 1
    ]
    if not near:
        return None
    merged = merge_pieces(near, s)
    blob = max(merged, key=lambda b: b.mask.sum())
    # reject samples the extraction destroyed (glyph faded out, swallowed by a line...)
    ys, xs = np.nonzero(glyph > 0.5)
    if ys.size == 0:
        return None
    t = (gx + xs.min(), gy + ys.min(), gx + xs.max() + 1, gy + ys.max() + 1)
    ix = max(0, min(t[2], blob.x + blob.w) - max(t[0], blob.x))
    iy = max(0, min(t[3], blob.y + blob.h) - max(t[1], blob.y))
    inter = ix * iy
    iou = inter / ((t[2] - t[0]) * (t[3] - t[1]) + blob.w * blob.h - inter)
    if iou < 0.7:
        return None
    return blob, s


def synth_dataset(
    n_per_class: int, seed: int = 0, fonts: list | None = None
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    fonts = fonts or [*font_files(), *HERSHEY]
    blobs, spacings, labels = [], [], []
    for ci, label in enumerate(CLASSES):
        count = n_per_class * (2 if label == "other" else 1)
        made = 0
        while made < count:
            r = synth_sample(label, rng, fonts)
            if r is None:
                continue
            blobs.append(r[0])
            spacings.append(r[1])
            labels.append(ci)
            made += 1
    X = np.concatenate(
        [features(blobs[i : i + 2000], spacings[i : i + 2000]) for i in range(0, len(blobs), 2000)]
    )
    return X, np.array(labels)


def debug_sheet(n: int = 8, seed: int = 1) -> np.ndarray:
    """Grid of normalized synthetic glyphs (rows = classes), for eyeballing."""
    rng = np.random.default_rng(seed)
    fonts: list = [*font_files(), *HERSHEY]
    rows = []
    for label in CLASSES:
        row = []
        while len(row) < n:
            r = synth_sample(label, rng, fonts)
            if r:
                row.append((normalize(r[0].mask) * 255).astype(np.uint8))
        rows.append(np.hstack(row))
    return 255 - np.vstack(rows)
```

- [ ] **Step 5: Write `backend/app/omr/train.py`**

```python
"""Train the glyph classifier on synthetic data: python -m app.omr.train [--per-class N]"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from app.omr.glyphs import CLASSES, HERSHEY, MODEL_PATH, GlyphClassifier, font_files, synth_dataset


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-class", type=int, default=1500)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=MODEL_PATH)
    parser.add_argument("--system-fonts", action="store_true", help="also use installed fonts")
    parser.add_argument("--exclude", nargs="*", default=[], help="skip fonts matching these")
    args = parser.parse_args(argv)
    fonts = [*font_files(args.system_fonts, tuple(args.exclude)), *HERSHEY]
    print("fonts:", ", ".join(f if isinstance(f, str) else f"hershey{f}" for f in fonts))

    t0 = time.time()
    X, y = synth_dataset(args.per_class, args.seed, fonts)
    Xv, yv = synth_dataset(max(50, args.per_class // 10), args.seed + 1000, fonts)
    print(f"synthesized {len(y)} train / {len(yv)} val samples in {time.time() - t0:.0f}s")
    t1 = time.time()
    model = GlyphClassifier.fit(X, y, epochs=args.epochs, seed=args.seed)
    print(f"trained in {time.time() - t1:.0f}s")
    for name, (A, b) in {"train": (X, y), "val": (Xv, yv)}.items():
        pred = model.proba(A).argmax(axis=1)
        print(f"{name} accuracy {np.mean(pred == b):.4f}")
    pred = model.proba(Xv).argmax(axis=1)
    for ci, c in enumerate(CLASSES):
        m = yv == ci
        wrong = np.bincount(pred[m][pred[m] != ci], minlength=len(CLASSES))
        top = ", ".join(f"{CLASSES[k]}:{wrong[k]}" for k in np.argsort(-wrong)[:3] if wrong[k])
        print(f"  {c:>10} {np.mean(pred[m] == ci):.3f}  {top}")
    model.save(args.out)
    print(f"wrote {args.out} ({time.time() - t0:.0f}s total)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Train the model**

Run: `cd backend && uv run python -m app.omr.train --per-class 2000`
Expected: a per-class validation table, with the digit rows around 0.97–1.00, then `wrote …/app/omr/models/glyphs.xml.gz`. It takes about 160 s. The file is about 1.5 MB.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_omr_glyphs.py -v`
Expected: 1 passed. The test must not be skipped; if it is, the model file is missing.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 85 passed, 1 deselected; lint clean.

- [ ] **Step 8: Commit**

```bash
git add backend/app/omr/glyphs.py backend/app/omr/train.py backend/app/omr/fonts backend/app/omr/models/glyphs.xml.gz backend/tests/test_omr_glyphs.py
git commit -m "feat: add HOG+MLP glyph classifier trained on multi-font synthetic glyphs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Rhythm marks and measure-sum duration solver

**Files:**
- Create: `backend/app/omr/rhythm.py`, `backend/app/omr/solve.py`
- Test: `backend/tests/test_omr_solve.py`

**Interfaces:**
- Consumes: from Task 2, `GlyphClassifier` and `components`; from Task 1, `Beat` and `TUPLET_RATIO`; from the existing code, `app.region.Staff`.
- Produces (`rhythm.py`):
  - `MIN_STEM`
  - `stem_positions(raw_ink, staff, span) -> list[(x, length)]`
  - `BeatMarks(stem, stem_top, stem_len, beams, …, dot, …)`: the evidence below one beat
  - `read_rhythm(raw_ink, staff, xs, span, clf) -> list[BeatMarks]`
- Produces (`solve.py`):
  - `DURATIONS`
  - `Option(duration, dots, tuplet, …)`
  - `BeatEvidence(marks, short_stem=False, …)`
  - `candidates(ev) -> list[Option]`
  - `TUPLET_GROUP_P`
  - `solve_measure(evidence, capacity) -> (list[Option], ok)`
  - `apply(beats, evidence, capacity) -> bool`: writes the chosen durations and confidences into the beats

- [ ] **Step 1: Write the failing test `backend/tests/test_omr_solve.py`**

```python
from fractions import Fraction

from app.omr.rhythm import BeatMarks
from app.omr.solve import BeatEvidence, solve_measure


def stem(beams=0, dot=False, short=False):
    marks = BeatMarks(True, 0.7, 1.0 if short else 1.8, beams, 1.0, dot)
    return BeatEvidence(marks, short_stem=short)


def durations(opts):
    return [(o.duration, o.dots, o.tuplet) for o in opts]


def test_solver_keeps_a_consistent_reading():
    ev = [stem(1)] * 8
    opts, ok = solve_measure(ev, Fraction(1))
    assert ok and durations(opts) == [(8, 0, None)] * 8


def test_solver_fixes_one_misread_beam():
    ev = [stem(1)] * 7 + [stem(2)]  # last beat misread as a 16th
    opts, ok = solve_measure(ev, Fraction(1))
    assert ok and durations(opts)[-1] == (8, 0, None)


def test_solver_dotted_and_short_stem_half():
    opts, ok = solve_measure([stem(0, dot=True, short=True), stem(1), stem(1)], Fraction(1))
    assert ok and durations(opts) == [(2, 1, None), (8, 0, None), (8, 0, None)]


def test_solver_infers_triplet_group_without_visible_number():
    ev = [stem(0, short=True), stem(0), stem(0), stem(0)]
    opts, ok = solve_measure(ev, Fraction(1))
    assert ok and durations(opts) == [(2, 0, None)] + [(4, 0, 3)] * 3
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_omr_solve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.omr.rhythm'`

- [ ] **Step 3: Write `backend/app/omr/rhythm.py`**

```python
"""Rhythm marks below the tab staff: stems, beams/flags, dots and tuplet numbers.

For every beat position the marks are measured, not interpreted; `solve.py` turns them
into duration candidates. Beams and flags are counted the same way: every column just
beside a stem crosses each beam (horizontal) or each flag (diagonal curve) once.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.omr.glyphs import GlyphClassifier, components
from app.region import Staff

MIN_STEM = 0.6  # in s


def stem_positions(
    ink: np.ndarray, staff: Staff, span: tuple[int, int]
) -> list[tuple[float, float]]:
    """(x center, length in s) of all vertical strokes below the staff within span."""
    s = staff.spacing
    y0 = int(staff.lines[-1] + 0.25 * s)
    y1 = min(ink.shape[0], int(staff.lines[-1] + 4.5 * s))
    x0, x1 = max(0, span[0] + 3), min(ink.shape[1], span[1] - 3)
    if y1 - y0 < 3 or x1 <= x0:
        return []
    k = max(5, int(MIN_STEM * s))
    region = ink[y0:y1, x0:x1].astype(np.uint8)
    vert = cv2.morphologyEx(
        region, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k))
    )
    cols = np.flatnonzero(vert.any(axis=0))
    if cols.size == 0:
        return []
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    out = []
    for r in runs:
        if len(r) > max(3, 0.25 * s):
            continue
        rows = np.flatnonzero(vert[:, r[0] : r[-1] + 1].any(axis=1))
        out.append((float(r.mean()) + x0, (rows[-1] - rows[0] + 1) / s))
    return out


@dataclass
class BeatMarks:
    stem: bool = False
    stem_top: float = 0.0  # in s below the bottom line
    stem_len: float = 0.0  # in s
    beams: int = 0
    beam_conf: float = 0.0  # share of beside-stem columns that agree with `beams`
    dot: bool = False
    tuplet: int | None = None


def _runs(col: np.ndarray) -> int:
    col = col.astype(np.int8)
    return int(np.count_nonzero(np.diff(np.concatenate([[0], col])) == 1))


def _stem_near(vert: np.ndarray, x: float, s: float) -> tuple[int, int] | None:
    """Columns [c0, c1) of the stem run closest to x within +-0.45 s."""
    w = vert.shape[1]
    lo, hi = max(0, int(x - 0.45 * s)), min(w, int(x + 0.45 * s) + 1)
    cols = np.flatnonzero(vert[:, lo:hi].any(axis=0)) + lo
    if cols.size == 0:
        return None
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    run = min(runs, key=lambda r: abs(r.mean() - x))
    if len(run) > max(3, 0.25 * s):  # too thick for a stem
        return None
    return int(run[0]), int(run[-1]) + 1


def _count_beams(ink: np.ndarray, c0: int, c1: int, top: int, bottom: int, s: float):
    """Beams/flags crossing the columns beside the stem, near the stem's end."""
    h, w = ink.shape
    r0, r1 = max(0, int(bottom - 1.1 * s)), min(h, bottom + 2)
    r0 = max(r0, top + 1)
    best = (0, 0.0)
    for a, b in ((c0 - int(0.45 * s), c0 - 2), (c1 + 2, c1 + int(0.45 * s))):
        a, b = max(0, a), min(w, b)
        if b - a < 2:
            continue
        counts = [_runs(ink[r0:r1, c]) for c in range(a, b)]
        vals, freq = np.unique(counts, return_counts=True)
        k = int(vals[np.argmax(freq)])
        conf = float(freq.max() / len(counts))
        if k > best[0] or (k == best[0] and conf > best[1]):
            best = (k, conf)
    return best


def read_rhythm(
    ink: np.ndarray,
    staff: Staff,
    xs: list[float],
    span: tuple[int, int],
    clf: GlyphClassifier,
) -> list[BeatMarks]:
    s = staff.spacing
    base = staff.lines[-1]
    y0 = int(base + 0.25 * s)
    y1 = min(ink.shape[0], int(base + 4.5 * s))
    if y1 - y0 < 3 or not xs:
        return [BeatMarks() for _ in xs]
    region = ink[y0:y1].astype(np.uint8)
    k = max(5, int(0.5 * s))
    vert = cv2.morphologyEx(
        region, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k))
    )
    blobs = components(region, min_area=3)
    out = []
    stems: list[tuple[int, int, int]] = []
    for x in xs:
        m = BeatMarks()
        stem = _stem_near(vert, x, s)
        if stem is not None:
            c0, c1 = stem
            rows = np.flatnonzero(vert[:, c0:c1].any(axis=1))
            runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
            run = max(runs, key=len)
            top, bottom = int(run[0]), int(run[-1])
            if (bottom - top + 1) < MIN_STEM * s:
                out.append(m)
                continue
            m.stem = True
            m.stem_top = (top + y0 - base) / s
            m.stem_len = (bottom - top + 1) / s
            m.beams, m.beam_conf = _count_beams(region, c0, c1, top, bottom, s)
            m.dot = any(
                c1 + 0.05 * s <= b.x <= c1 + 0.9 * s
                and bottom - 0.7 * s <= b.cy <= bottom + 0.5 * s
                and 0.08 * s <= b.w <= 0.4 * s
                and 0.08 * s <= b.h <= 0.4 * s
                and b.mask.mean() > 0.5
                for b in blobs
            )
            stems.append((c0, c1, bottom))
        out.append(m)
    # tuplet numbers below the stems' ends
    if stems:
        lowest = max(b for _, _, b in stems)
        cand = [b for b in blobs if b.y > lowest + 0.05 * s and 0.3 * s <= b.h <= 1.0 * s]
        if cand:
            labels = clf.classify(cand, s)
            for b, (lab, conf) in zip(cand, labels, strict=True):
                if lab in ("3", "5", "6", "7") and conf > 0.6:
                    near = sorted(range(len(xs)), key=lambda i: abs(xs[i] - b.cx))[: int(lab)]
                    for i in near:
                        out[i].tuplet = int(lab)
    return out
```

- [ ] **Step 4: Write `backend/app/omr/solve.py`**

```python
"""Measure-sum solver: pick one duration per beat so the measure adds up to its time
signature, maximizing the joint probability of the per-beat candidates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from app.omr.model import TUPLET_RATIO, Beat
from app.omr.rhythm import BeatMarks

DURATIONS = (1, 2, 4, 8, 16, 32)


@dataclass(frozen=True)
class Option:
    duration: int
    dots: int
    tuplet: int | None
    p: float

    def length(self) -> Fraction:
        value = Fraction(1, self.duration) * (2 - Fraction(1, 2**self.dots))
        if self.tuplet:
            n, m = TUPLET_RATIO.get(self.tuplet, (self.tuplet, self.tuplet))
            value *= Fraction(m, n)
        return value


@dataclass
class BeatEvidence:
    marks: BeatMarks
    circled: bool = False
    rest_kind: str | None = None
    short_stem: bool = False  # stem clearly shorter than the typical one (GP half notes)
    spacing_guess: int | None = None  # duration from horizontal spacing, if no marks


def _add(opts: dict, d: int, dots: int, tup: int | None, p: float) -> None:
    if d not in DURATIONS or p <= 0:
        return
    key = (d, dots, tup)
    opts[key] = max(opts.get(key, 0.0), p)


def candidates(ev: BeatEvidence) -> list[Option]:
    """Primary reading plus the likely misreadings, with rough prior probabilities."""
    m = ev.marks
    opts: dict = {}
    if ev.rest_kind:
        base = {
            "rest_block": [(1, 0.5), (2, 0.45)],
            "rest_4": [(4, 0.9)],
            "rest_8": [(8, 0.9)],
            "rest_16": [(16, 0.9)],
        }[ev.rest_kind]
        for d, p in base:
            _add(opts, d, 0, None, p)
            _add(opts, d, 1, None, p * 0.08)
            _add(opts, d * 2, 0, None, p * 0.05)
            _add(opts, d // 2 if d > 1 else 0, 0, None, p * 0.05)
    elif m.stem:
        d = 4 * 2**m.beams
        if m.beams == 0 and (ev.short_stem or ev.circled):
            d = 2
        dots = 1 if m.dot else 0
        tup = m.tuplet
        pc = 0.9 if m.beam_conf >= 0.7 else 0.7
        _add(opts, d, dots, tup, pc)
        _add(opts, d, 1 - dots, tup, 0.03)
        beamed = 4 * 2**m.beams  # one beam/flag more or less than counted
        _add(opts, beamed * 2, dots, tup, (1 - pc) * 0.5)
        if m.beams:
            _add(opts, beamed // 2, dots, tup, (1 - pc) * 0.5)
        if m.beams == 0:  # half vs quarter is only a stem-length / circle cue
            _add(opts, 4 if d == 2 else 2, dots, tup, 0.01 if d == 2 else 0.08)
        if tup is not None:
            _add(opts, d, dots, None, 0.05)
    elif ev.circled:
        _add(opts, 1, 0, None, 0.85)
        _add(opts, 2, 0, None, 0.08)
        _add(opts, 1, 1, None, 0.02)
        _add(opts, 2, 1, None, 0.02)
    else:  # no rhythm marks: horizontal spacing only
        guess = ev.spacing_guess or 4
        for d in DURATIONS:
            steps = abs(math.log2(d) - math.log2(guess))
            _add(opts, d, 0, None, 0.4 * 0.25**steps)
            _add(opts, d, 1, None, 0.05 * 0.25**steps)
    return [Option(d, dots, t, p) for (d, dots, t), p in opts.items()]


TUPLET_GROUP_P = 0.02  # a whole group of 3 read as a triplet without a visible "3"


def solve_measure(evidence: list[BeatEvidence], capacity: Fraction) -> tuple[list[Option], bool]:
    """Best exact-sum assignment (DP over beat index and running sum); falls back to the
    per-beat best. A run of 3 equal plain durations may also become one triplet group
    (the "3" is often cut off or faint), at a single penalty for the group."""
    cands = [sorted(candidates(ev), key=lambda o: -o.p) for ev in evidence]
    if not cands:
        return [], True
    n = len(cands)
    # states[i]: {total: (logp, chosen)} after the first i beats
    states: list[dict] = [dict() for _ in range(n + 1)]
    states[0][Fraction(0)] = (0.0, [])

    def push(i: int, total: Fraction, lp: float, chosen: list[Option]) -> None:
        if total <= capacity and (total not in states[i] or states[i][total][0] < lp):
            states[i][total] = (lp, chosen)

    for i in range(n):
        for total, (lp, chosen) in states[i].items():
            for o in cands[i]:
                push(i + 1, total + o.length(), lp + math.log(o.p), [*chosen, o])
            if i + 3 <= n:
                firsts = [cands[k][0] for k in range(i, i + 3)]
                d = firsts[0].duration
                if all(f.duration == d and f.tuplet is None and f.dots == 0 for f in firsts):
                    group = [Option(d, 0, 3, f.p) for f in firsts]
                    glp = math.log(TUPLET_GROUP_P) + sum(math.log(f.p) for f in firsts)
                    push(i + 3, total + sum(g.length() for g in group), lp + glp, [*chosen, *group])
    if capacity in states[n]:
        return states[n][capacity][1], True
    return [opts[0] for opts in cands], False


def apply(beats: list[Beat], evidence: list[BeatEvidence], capacity: Fraction) -> bool:
    """Fill in durations on `beats` in place; returns whether the measure sums up."""
    chosen, ok = solve_measure(evidence, capacity)
    for beat, ev, o in zip(beats, evidence, chosen, strict=True):
        total = sum(c.p for c in candidates(ev)) or 1.0
        beat.duration, beat.dots, beat.tuplet = o.duration, o.dots, o.tuplet
        note_conf = min((n.confidence for n in beat.notes), default=1.0)
        beat.confidence = round((o.p / total) * note_conf * (1.0 if ok else 0.5), 3)
    return ok
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_omr_solve.py -v`
Expected: 4 passed.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 89 passed, 1 deselected; lint clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/omr/rhythm.py backend/app/omr/solve.py backend/tests/test_omr_solve.py
git commit -m "feat: read rhythm marks and solve durations per measure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Line recognition, measure numbering, evaluation CLI and README

**Files:**
- Create: `backend/app/omr/recognize.py`, `backend/app/omr/evaluate.py`
- Modify: `README.md` (append a section)
- Test: `backend/tests/test_omr_recognize.py`

**Interfaces:**
- Consumes: from Task 1, `Score`, `Measure`, `Beat`, `Note`, `STANDARD_TUNINGS` and `read_track`. From Task 2, `glyphs.*`. From Task 3, `rhythm.*` and `solve.*`. From the existing code, `app.region.detect_staves` and `Staff`; `app.stitch.BAR_COVERAGE`, `BAR_MERGE_GAP` and `INK_LEVEL`; and `app.pipeline.analyze`, `app.region.detect_region` and `app.frames.grab_frames`, which `evaluate.py` uses for video input.
- Produces (`recognize.py`):
  - Types: `Glyph`, `Fret`, `LineResult`, `RestMark`, `BeatGroup`, `RawMeasure`
  - Staff and bars: `staff_candidates(gray)`, which includes the fake-staff check `_lines_are_ink`; `pick_staff(gray, strings=None)`; `find_bar_lines(gray, staff)`
  - Glyphs and notes: `peel_ring`, `staff_band`, `staff_glyphs`, `frets_from_glyphs`, `rests_from_glyphs`, `group_beats`
  - Measures: `measure_spans`, `read_measure_number`
  - Per line: `recognize_line(img, line=0, clf=None, strings=None) -> LineResult | None`
  - Numbering: `number_measures(raw, min_conf=0.5) -> list[int]`
  - Assembly: `build_score(lines, strings) -> Score`, `common_strings(images)`, `recognize_lines(images, clf=None) -> (list[LineResult], strings)`, `recognize_images(images, clf=None) -> Score`, `consistent_lines(lines)`
- Produces (`evaluate.py`):
  - `load_images(src)` (a directory of `page_*.png`, or a video)
  - `align`, `Report`, `compare(gt, rec, lo, hi) -> Report`, `run(...)`
  - CLI: `python -m app.omr.evaluate VIDEO_OR_PAGE_DIR GP --track NAME [--from --to --first --model --json]`

- [ ] **Step 1: Write the failing test `backend/tests/test_omr_recognize.py`**

```python
"""Recognition on synthetic tab lines drawn in the Guitar Pro style (no ground-truth file)."""

import cv2
import numpy as np
import pytest

from app.omr.glyphs import MODEL_PATH
from app.omr.recognize import recognize_images

SPACING = 24  # px between strings
TOP = 60


def draw_line(measures, strings=6, stems=True):
    """measures: list of measures, each a list of 4 beats, each a list of (string, fret).
    Draws one tab line with quarter-note stems below every beat."""
    beat_w, pad = 90, 30
    width = pad + len(measures) * (4 * beat_w + pad) + 20
    height = TOP + (strings - 1) * SPACING + 140
    img = np.full((height, width, 3), 255, np.uint8)
    ys = [TOP + (strings - 1 - s) * SPACING for s in range(strings)]  # string 0 at the bottom
    for y in ys:
        cv2.line(img, (0, y), (width - 1, y), (0, 0, 0), 1)
    x = 10
    for measure in measures:
        cv2.line(img, (x, ys[-1]), (x, ys[0]), (0, 0, 0), 2)
        for k, beat in enumerate(measure):
            bx = x + pad + k * beat_w
            for string, fret in beat:
                text = str(fret)
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                y = ys[string]
                cv2.rectangle(
                    img,
                    (bx - 2, y - th // 2 - 3),
                    (bx + tw + 2, y + th // 2 + 3),
                    (255, 255, 255),
                    -1,
                )
                cv2.putText(
                    img,
                    text,
                    (bx, y + th // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
            if stems and beat:
                cx = bx + 6
                cv2.line(img, (cx, ys[0] + 14), (cx, ys[0] + 60), (0, 0, 0), 2)
        x += 4 * beat_w + pad
    cv2.line(img, (x, ys[-1]), (x, ys[0]), (0, 0, 0), 2)
    return img


MEASURES = [
    [[(0, 3)], [(1, 5), (2, 7)], [(3, 12)], [(5, 0)]],
    [[(4, 10)], [(2, 2)], [(0, 15), (1, 17)], [(5, 8)]],
]


def notes_of(score):
    return [[sorted((n.string, n.fret) for n in b.notes) for b in m.beats] for m in score.measures]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_six_string_line_with_two_digit_frets_and_chords():
    score = recognize_images([draw_line(MEASURES)])
    assert score.strings == 6
    assert score.tuning == [40, 45, 50, 55, 59, 64]
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]
    assert all(b.duration == 4 for m in score.measures for b in m.beats)
    assert all(b.confidence >= 0.7 for m in score.measures for b in m.beats)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_line_without_rhythm_marks_still_fills_each_measure():
    score = recognize_images([draw_line(MEASURES, stems=False)])
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]
    for m in score.measures:
        assert sum(b.length() for b in m.beats) == m.capacity()
        assert all(b.confidence < 0.7 for b in m.beats)  # guessed rhythm is flagged


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_image_without_tab_gives_empty_score():
    blank = np.full((300, 800, 3), 255, np.uint8)
    score = recognize_images([blank])
    assert score.measures == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_omr_recognize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.omr.recognize'`

- [ ] **Step 3: Write `backend/app/omr/recognize.py`**

```python
"""Per-line recognition: staff, bars, fret numbers, rests, beats and measure numbers.

Everything is measured in units of the staff line spacing `s`, so the same rules apply
at any resolution and to any tab software.
"""

from __future__ import annotations

from collections import Counter
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


def find_bar_lines(gray: np.ndarray, staff: Staff) -> list[int]:
    """Like stitch.find_bars, but for a given staff."""
    dark = gray[staff.lines[0] : staff.lines[-1] + 1] < INK_LEVEL
    cols = np.flatnonzero(dark.mean(axis=0) >= BAR_COVERAGE)
    if cols.size == 0:
        return []
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > BAR_MERGE_GAP) + 1)
    return [int(g[0]) for g in groups]


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


def staff_glyphs(ink: np.ndarray, staff: Staff, bars: list[int], clf: GlyphClassifier):
    """Classified glyphs inside the staff band plus the enclosure (circle) blobs."""
    s = staff.spacing
    y0, y1 = staff_band(staff)
    y0, y1 = max(0, y0), min(ink.shape[0], y1)
    band = ink[y0:y1].copy()
    for b in bars:  # bar lines are not glyphs
        band[:, max(0, b - 2) : b + 5] = 0
    blobs = components(band, min_area=4)
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
    bars = find_bar_lines(gray, staff)
    ink = staff_ink(gray, s, staff.lines)
    glyphs, circles = staff_glyphs(ink, staff, bars, clf)
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
    images: list[np.ndarray], clf: GlyphClassifier | None = None
) -> tuple[list[LineResult], int]:
    clf = clf or default_classifier()
    strings = common_strings(images)
    lines = [r for i, img in enumerate(images) if (r := recognize_line(img, i, clf, strings))]
    return consistent_lines(lines)


def recognize_images(images: list[np.ndarray], clf: GlyphClassifier | None = None) -> Score:
    return build_score(*recognize_lines(images, clf))


def consistent_lines(lines: list[LineResult]) -> tuple[list[LineResult], int]:
    """Keep the lines whose staff has the most common number of strings."""
    counts = Counter(len(r.staff.lines) for r in lines)
    strings = counts.most_common(1)[0][0] if counts else 6
    return [r for r in lines if len(r.staff.lines) == strings], strings
```

- [ ] **Step 4: Write `backend/app/omr/evaluate.py`**

```python
"""Score recognition against a Guitar Pro file.

    python -m app.omr.evaluate VIDEO_OR_PAGE_DIR GP --track NAME [--from N --to M]

VIDEO_OR_PAGE_DIR is a video (the existing pipeline runs first) or a directory of
line images (page_*.png as written by `app.cli`). Measures are aligned by recognized
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
from app.omr.recognize import build_score, number_measures, recognize_lines


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
    body = "R" if b.rest else "+".join(f"{n.string}:{n.fret}" for n in b.notes)
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
            "counts": {"notes": self.notes, "beats": self.beats},
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
) -> dict:
    t0 = time.time()
    images = load_images(src)
    t1 = time.time()
    clf = GlyphClassifier.load(model)
    lines, strings = recognize_lines(images, clf)
    score = build_score(lines, strings)
    t2 = time.time()
    gt = read_track(gp, track)
    rep = compare(gt, score, lo, hi)
    out = rep.summary()
    raw = [m for ln in lines for m in ln.measures]
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
    args = parser.parse_args(argv)
    out = run(args.source, args.gp, args.track, args.lo, args.hi, args.first, args.show, args.model)
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_omr_recognize.py -v`
Expected: 3 passed.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 92 passed, 1 deselected; lint clean.

- [ ] **Step 6: Real-data evaluation**

The line images are cached at `/tmp/vtt/gp1/out`. If they are missing, regenerate them with `cd backend && uv run python -m app.cli /tmp/vtt/gp1/source.mp4 --out /tmp/vtt/gp1/out`. That video is bilibili `BV1yBcEeXEVn`; download it with `app.source.download_url` if needed.

Run:
```bash
cd backend
uv run python -m app.omr.evaluate /tmp/vtt/gp1/out "../data/tabs/[7弦]AveMujica+KiLLKiSS.gp" --track "Guitar Mutsumi" --from 13 --to 148 --first 13
```
Expected: the JSON summary shows `measure_alignment` 100.0, `fret_recall` ≥ 99.5, `beat_grouping` ≥ 99.5 and `duration_on_grouped` ≥ 99.5. The prototype measured 100.0, 99.92, 99.76 and 99.88.

A result more than 1 point lower means the code was not transcribed exactly: diff it against the plan before going on.

- [ ] **Step 7: Append the README section**

Append to the end of `README.md`:

```markdown
## 识谱（实验中）

把截图拼接得到的 tab 行图识别成结构化乐谱（弦、品格、休止、时值），并可以用 Guitar Pro 文件评测准确率：

    cd backend
    uv run python -m app.omr.evaluate VIDEO_OR_PAGE_DIR 谱.gp --track "声部名" [--from 13 --to 148]
    uv run python -m app.omr.train --per-class 2000   # 重新训练字形分类器（约 3 分钟）

识别结果是 `app.omr.model.Score`（可转为 JSON），后续用于识谱界面和导出 .gp。
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/omr/recognize.py backend/app/omr/evaluate.py backend/tests/test_omr_recognize.py README.md
git commit -m "feat: recognize tab lines into a score and evaluate against Guitar Pro files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Out of scope (sub-project 2 and later)

- Review/correction UI, alphaTab rendering, `.gp` export.
- Bundling the model and fonts into the PyInstaller release: add this when the UI uses recognition.
- Playing techniques, time-signature reading, multi-staff systems.
