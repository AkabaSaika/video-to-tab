# Measure Stitch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For tab videos that scroll left in steps, stitch overlapping consecutive pages into one strip and re-flow it into lines of whole measures, so every measure appears exactly once. Page-switching videos must be unaffected.

**Architecture:** A new pure module `backend/app/stitch.py` runs inside `pipeline.analyze()` between `merge_adjacent` and `mark_repeats`.
1. Consecutive pages are compared by horizontal ink alignment. Staff lines are removed first, because they match at every shift.
2. Pages scoring at least 0.35 are grouped and joined into one strip.
3. The strip is cut just left of each bar line and packed greedily into lines no wider than the original page.

`Page`, the API, the frontend and export are unchanged.

**Tech Stack:** Python 3.12, NumPy, OpenCV (existing deps only), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-27-measure-stitch-design.md`

## Global Constraints

- No new dependencies. No OCR.
- `Page(image, start, end, duplicate_of)` and all API/frontend contracts stay unchanged.
- Page-switching videos (pages that don't overlap) must pass through `stitch_pages` unchanged (same objects).
- Constants, verbatim: `INK_LEVEL = 140`, `MIN_SHIFT = 50`, `MIN_OVERLAP = 200`, `OVERLAP_THRESHOLD = 0.35`, `BAR_COVERAGE = 0.9`, `BAR_MERGE_GAP = 12`, `BAR_MARGIN = 3`.
- Re-flowed lines keep their real width (no padding); export already pads narrower images.
- Backend commands run from `backend/` via `uv run …`. `ruff check` + `ruff format --check` must be clean (line length 100). Test output must have zero warnings.

## Prototype evidence

This code was run before the plan was written.
- **Video b** (YouTube `U2m8IatzpAM`, step scrolling): 23 overlapping pages became 20 lines. Measures 1–34 are continuous with none repeated; each line starts at a bar line. Two lines covering measures 29–32 are marked as repeats, and they really are repeated music.
- **Video a** (`2Ed7UsJd3Es`, page switching): unchanged, 16 pages.
- **Speed:** about 9 s per 3-minute 1080p video.
- **Overlap scores after removing staff lines:** b 0.47–0.58, a ≤ 0.19, synthetic page-switch panels 0.08. Without removing staff lines, the synthetic panels scored 0.7, which is why lines are removed.

## File Structure

```
backend/app/stitch.py          # new: ink_mask, overlap_shift, find_bars, build_strip, line_ranges, reflow, stitch_pages
backend/app/pipeline.py        # modify: call stitch_pages between merge_adjacent and mark_repeats
backend/tests/synth.py         # modify: append step-scrolling generators
backend/tests/conftest.py      # modify: add scroll_video fixture
backend/tests/test_stitch.py   # new
README.md                      # modify: one line about scrolling videos
```

---

### Task 1: Stitch module with synthetic step-scrolling data

**Files:**
- Create: `backend/app/stitch.py`
- Modify: `backend/tests/synth.py` (append at end of file)
- Test: `backend/tests/test_stitch.py`

**Interfaces:**
- Consumes: `app.models.Page`; `app.region.detect_staves(img) -> list[Staff]` (a `Staff` has `.lines: list[int]`, ordered top to bottom). From `tests.synth`: `LINE_YS`, `ROI_TRUTH` (a `Roi(20, 300, 600, 180)`), `render_panel(seed)`, and `np`, `cv2`, `Path`, which synth.py already imports.
- Produces (`stitch.py`):
  - the constants above
  - `ink_mask(img) -> bool ndarray`
  - `overlap_shift(a, b) -> (shift: int, score: float)`, which returns `(0, 0.0)` when shapes differ
  - `find_bars(strip) -> list[int]`
  - `build_strip(group: list[Page], shifts: list[int]) -> (ndarray, spans)`, where each span is `(x0, x1, start, end)`
  - `line_ranges(strip_width, bars, width) -> list[(x0, x1)]`
  - `reflow(strip, spans, width) -> list[Page]`
  - `stitch_pages(pages: list[Page]) -> list[Page]`
- Produces (`tests/synth.py`): `SCROLL_MEASURES = 12`, `SCROLL_MEASURE_W = 180`, `SCROLL_X0 = 20`, `SCROLL_STEP = 360`, `HIGHLIGHT`, `scroll_bar_xs() -> list[int]`, `render_scroll_strip(seed=7) -> ndarray` (width 2400, so the last page reaches the end), and `scroll_pages(strip, highlight=True) -> list[ndarray]` (600 px wide pages, each 360 px further right, with a yellow highlight on one measure).

- [ ] **Step 1: Append the step-scrolling generators to `backend/tests/synth.py`**

Append the following at the end of the file, after one blank line. It uses `np` and `cv2`, which the file already imports.

```python
# --- step-scrolling tab (Songsterr style) -------------------------------------------

SCROLL_MEASURES = 12
SCROLL_MEASURE_W = 180
SCROLL_X0 = 20  # x of the first bar line in the strip
SCROLL_STEP = 360  # px the tab jumps per page; pages are ROI_TRUTH.w = 600 wide
HIGHLIGHT = (170, 240, 250)  # light yellow (BGR), grey ~230


def scroll_bar_xs() -> list[int]:
    return [SCROLL_X0 + i * SCROLL_MEASURE_W for i in range(SCROLL_MEASURES + 1)]


def render_scroll_strip(seed: int = 7) -> np.ndarray:
    """One long tab line: staff, a bar line at every measure start and at the end,
    fret numbers on white boxes."""
    oy = ROI_TRUTH.y
    content = SCROLL_X0 + SCROLL_MEASURES * SCROLL_MEASURE_W + SCROLL_X0
    steps = -(-(content - ROI_TRUTH.w) // SCROLL_STEP)  # ceil: last page reaches the end
    width = ROI_TRUTH.w + steps * SCROLL_STEP
    strip = np.full((ROI_TRUTH.h, width, 3), 255, np.uint8)
    for y in LINE_YS:
        cv2.line(strip, (0, y - oy), (width - 1, y - oy), (0, 0, 0), 1)
    for x in scroll_bar_xs():
        cv2.line(strip, (x, LINE_YS[0] - oy), (x, LINE_YS[-1] - oy), (0, 0, 0), 2)
    rng = np.random.default_rng(seed)
    for m in range(SCROLL_MEASURES):
        for k in range(5):
            x = SCROLL_X0 + m * SCROLL_MEASURE_W + 20 + k * 32
            y = LINE_YS[int(rng.integers(0, 6))] - oy
            text = str(int(rng.integers(0, 20)))
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            box = ((x - 1, y - th // 2 - 2), (x + tw + 1, y + th // 2 + 2))
            cv2.rectangle(strip, *box, (255,) * 3, -1)
            cv2.putText(strip, text, (x, y + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,) * 3, 1)
    return strip


def scroll_pages(strip: np.ndarray, highlight: bool = True) -> list[np.ndarray]:
    """Page crops as the video shows them: each jumps SCROLL_STEP px further right and
    (optionally) highlights the measure being played in yellow."""
    width = ROI_TRUTH.w
    pages = []
    for x in range(0, strip.shape[1] - width + 1, SCROLL_STEP):
        page = strip[:, x : x + width].copy()
        if highlight:
            bar = next(b for b in scroll_bar_xs() if b >= x + 40) - x
            sub = page[:, bar : min(width, bar + SCROLL_MEASURE_W)]
            sub[(sub == 255).all(axis=2)] = HIGHLIGHT
        pages.append(page)
    return pages
```

- [ ] **Step 2: Write the failing test `backend/tests/test_stitch.py`**

```python
from app.models import Page
from app.stitch import (
    OVERLAP_THRESHOLD,
    find_bars,
    ink_mask,
    line_ranges,
    overlap_shift,
    stitch_pages,
)
from tests.synth import (
    LINE_YS,
    ROI_TRUTH,
    SCROLL_MEASURES,
    SCROLL_STEP,
    render_panel,
    render_scroll_strip,
    scroll_bar_xs,
    scroll_pages,
)


def as_pages(images, seconds=1.0):
    return [Page(img, i * seconds, (i + 1) * seconds) for i, img in enumerate(images)]


def test_ink_mask_drops_staff_lines_keeps_digits():
    panel = render_panel(1)
    mask = ink_mask(panel)
    for y in LINE_YS:
        assert mask[y - ROI_TRUTH.y].mean() < 0.3  # only digit strokes remain on the row
    assert mask.sum() > 200  # fret numbers are still there


def test_overlap_shift_finds_scroll_step_despite_highlight():
    pages = scroll_pages(render_scroll_strip())
    for a, b in zip(pages, pages[1:], strict=False):
        shift, score = overlap_shift(a, b)
        assert abs(shift - SCROLL_STEP) <= 3
        assert score >= OVERLAP_THRESHOLD


def test_page_switch_panels_do_not_overlap():
    panels = [render_panel(seed) for seed in (1, 2, 3)]
    for a, b in zip(panels, panels[1:], strict=False):
        assert overlap_shift(a, b)[1] < OVERLAP_THRESHOLD
    assert overlap_shift(panels[0], panels[0][:, :300])[1] == 0.0  # size mismatch


def test_find_bars_on_strip():
    bars = find_bars(render_scroll_strip())
    assert len(bars) == len(scroll_bar_xs())
    assert all(abs(b - x) <= 2 for b, x in zip(bars, scroll_bar_xs(), strict=True))


def test_line_ranges_packs_whole_measures():
    assert line_ranges(1000, [100, 300, 500, 900], 450) == [
        (0, 297),
        (297, 497),
        (497, 897),
        (897, 1000),
    ]
    assert line_ranges(1000, [], 450) == [(0, 450), (450, 900), (900, 1000)]
    assert line_ranges(1000, [100], 50) == [(0, 97), (97, 1000)]  # oversized measure


def test_stitch_pages_rebuilds_every_measure_once():
    pages = as_pages(scroll_pages(render_scroll_strip()))
    lines = stitch_pages(pages)
    assert len(lines) < len(pages)
    assert all(line.image.shape[1] <= ROI_TRUTH.w for line in lines)
    bars = sum(len(find_bars(line.image)) for line in lines)
    assert bars == SCROLL_MEASURES + 1  # every bar line exactly once
    assert lines[0].start == pages[0].start and lines[-1].end == pages[-1].end


def test_stitch_pages_passes_page_switch_through():
    pages = as_pages([render_panel(seed) for seed in (1, 2, 3)])
    assert all(a is b for a, b in zip(stitch_pages(pages), pages, strict=True))
    assert stitch_pages([]) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_stitch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.stitch'`

- [ ] **Step 4: Write `backend/app/stitch.py`**

```python
"""Stitch step-scrolling tab pages into one strip and re-flow it by measure.

Some videos scroll the tab left in jumps, so consecutive pages overlap by about one
measure. Overlapping neighbours are aligned horizontally, joined into one long strip,
cut at bar lines and packed into lines as wide as the original page.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models import Page
from app.region import detect_staves

INK_LEVEL = 140  # darker than this is ink; white and the yellow highlight are background
MIN_SHIFT = 50
MIN_OVERLAP = 200
OVERLAP_THRESHOLD = 0.35
BAR_COVERAGE = 0.9
BAR_MERGE_GAP = 12  # px; the two strokes of a double bar line become one
BAR_MARGIN = 3  # px kept left of a bar line so each measure starts with its bar


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def ink_mask(img: np.ndarray) -> np.ndarray:
    """Ink pixels without the staff lines: those match at every shift and would make
    any two pages of the same layout look like an overlap."""
    ink = (_gray(img) < INK_LEVEL).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (41, 1))
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
    return (ink & (1 - lines)).astype(bool)


def overlap_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Best shift s where b's left part repeats a from column s, with its IoU score."""
    if a.shape != b.shape:
        return 0, 0.0
    ma, mb = ink_mask(a), ink_mask(b)
    width = ma.shape[1]
    best = (0, 0.0)
    for s in range(MIN_SHIFT, width - MIN_OVERLAP + 1):
        x, y = ma[:, s:], mb[:, : width - s]
        union = np.count_nonzero(x | y)
        score = np.count_nonzero(x & y) / union if union else 0.0
        if score > best[1]:
            best = (s, score)
    return best


def find_bars(strip: np.ndarray) -> list[int]:
    """x of bar lines: columns inked over >=90% of the tab staff's height."""
    staves = detect_staves(strip)
    if not staves:
        return []
    staff = max(staves, key=lambda st: (len(st.lines), st.lines[0]))
    dark = _gray(strip)[staff.lines[0] : staff.lines[-1] + 1] < INK_LEVEL
    cols = np.flatnonzero(dark.mean(axis=0) >= BAR_COVERAGE)
    if cols.size == 0:
        return []
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > BAR_MERGE_GAP) + 1)
    return [int(round(g.mean())) for g in groups]


def build_strip(group: list[Page], shifts: list[int]) -> tuple[np.ndarray, list[tuple]]:
    """Join a group left to right; spans record (x0, x1, start, end) per source page."""
    parts, spans, x = [], [], 0
    for page, shift in zip(group, [*shifts, None], strict=True):
        part = page.image if shift is None else page.image[:, :shift]
        parts.append(part)
        spans.append((x, x + part.shape[1], page.start, page.end))
        x += part.shape[1]
    return np.hstack(parts), spans


def line_ranges(strip_width: int, bars: list[int], width: int) -> list[tuple[int, int]]:
    """Greedy packing of measures into [x0, x1) lines no wider than `width`
    (a single wider measure gets its own line). Without bars, cut every `width` px."""
    if not bars:
        return [(x, min(x + width, strip_width)) for x in range(0, strip_width, width)]
    cuts = sorted({0, strip_width, *(max(0, b - BAR_MARGIN) for b in bars)})
    lines: list[tuple[int, int]] = []
    start, end = cuts[0], cuts[0]
    for cut in cuts[1:]:
        if cut - start > width and end > start:
            lines.append((start, end))
            start = end
        end = cut
    lines.append((start, end))
    return lines


def reflow(strip: np.ndarray, spans: list[tuple], width: int) -> list[Page]:
    pages = []
    for x0, x1 in line_ranges(strip.shape[1], find_bars(strip), width):
        covered = [s for s in spans if s[0] < x1 and s[1] > x0]
        image = strip[:, x0:x1].copy()  # narrower last lines are padded at export time
        pages.append(Page(image, min(s[2] for s in covered), max(s[3] for s in covered)))
    return pages


def stitch_pages(pages: list[Page]) -> list[Page]:
    """Replace each run of overlapping pages with measure-aligned lines; pages that do
    not overlap their neighbours (page-switching videos) pass through unchanged."""
    if not pages:
        return []
    result: list[Page] = []
    group, shifts = [pages[0]], []

    def flush() -> None:
        if len(group) == 1:
            result.append(group[0])
        else:
            strip, spans = build_strip(group, shifts)
            result.extend(reflow(strip, spans, group[0].image.shape[1]))

    for prev, cur in zip(pages, pages[1:], strict=False):
        shift, score = overlap_shift(prev.image, cur.image)
        if score >= OVERLAP_THRESHOLD:
            group.append(cur)
            shifts.append(shift)
        else:
            flush()
            group, shifts = [cur], []
    flush()
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_stitch.py -v`
Expected: 7 passed.
Then: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 69 passed, 1 deselected, zero warnings; lint clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/stitch.py backend/tests/synth.py backend/tests/test_stitch.py
git commit -m "feat: stitch overlapping scroll pages and re-flow by measure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Wire stitching into the pipeline, integration test, README

**Files:**
- Modify: `backend/app/pipeline.py` (imports; the line `pages = mark_repeats(merge_adjacent(pages))`)
- Modify: `backend/tests/synth.py` (append at end), `backend/tests/conftest.py`
- Modify: `backend/tests/test_stitch.py` (imports + one new test)
- Modify: `README.md`

**Interfaces:**
- Consumes: `stitch_pages` and `find_bars` (Task 1); `analyze(video, roi, params=None, progress=...)` in `app/pipeline.py`; `FPS, W, H, ROI_TRUTH, scroll_pages, render_scroll_strip` from `tests/synth.py`.
- Produces: `tests.synth.make_scroll_video(path, page_seconds=1.2) -> list[ndarray]` (an MJPG .avi with noise above and the scroll pages below, hard cuts, and a red cursor sweeping each page); the pytest fixture `scroll_video` (session-scoped path). `analyze()` now returns stitched lines for scrolling videos.

- [ ] **Step 1: Append the video generator to `backend/tests/synth.py`**

Append the following at the end of the file, after one blank line:

```python
def make_scroll_video(path: Path, page_seconds: float = 1.2) -> list[np.ndarray]:
    """Video whose tab panel shows scroll_pages() one after another (hard cuts)."""
    pages = scroll_pages(render_scroll_strip())
    rng = np.random.default_rng(1)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    per_page = int(round(page_seconds * FPS))
    r = ROI_TRUTH
    for page in pages:
        for f in range(per_page):
            frame = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
            frame[r.y :, :] = 90
            panel = page.copy()
            cx = int(f / per_page * (r.w - 1))
            cv2.line(panel, (cx, 0), (cx, r.h - 1), (0, 0, 255), 3)
            frame[r.y : r.y + r.h, r.x : r.x + r.w] = panel
            writer.write(frame)
    writer.release()
    return pages
```

- [ ] **Step 2: Add the fixture to `backend/tests/conftest.py`**

Change the import line to `from tests.synth import make_scroll_video, make_video` and append:

```python
@pytest.fixture(scope="session")
def scroll_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("scroll") / "scroll.avi"
    make_scroll_video(path)
    return path
```

- [ ] **Step 3: Write the failing integration test**

In `backend/tests/test_stitch.py`, change `from app.models import Page` to:

```python
from app.models import Page, Roi
from app.pipeline import analyze
```

and append:

```python
def test_analyze_scroll_video(scroll_video):
    lines = analyze(scroll_video, Roi(ROI_TRUTH.x, ROI_TRUTH.y, ROI_TRUTH.w, ROI_TRUTH.h))
    bars = sum(len(find_bars(line.image)) for line in lines)
    assert bars == SCROLL_MEASURES + 1
    assert all(line.duplicate_of is None for line in lines)
    assert all(line.start < line.end for line in lines)
```

- [ ] **Step 4: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_stitch.py::test_analyze_scroll_video -v`
Expected: FAIL. Without stitching, the overlapping pages repeat bar lines, so `assert bars == SCROLL_MEASURES + 1` fails with a count larger than 13.

- [ ] **Step 5: Wire `stitch_pages` into `backend/app/pipeline.py`**

Add the import after `from app.segment import SegmentParams, find_segments, prep_gray`:

```python
from app.stitch import stitch_pages
```

and replace `pages = mark_repeats(merge_adjacent(pages))` with:

```python
    pages = mark_repeats(stitch_pages(merge_adjacent(pages)))
```

- [ ] **Step 6: Add one line to `README.md`**

Under `## 使用`, after the line starting `浏览器打开`, add:

```markdown
- 分段横向滚动的谱面（相邻页有重叠）会自动拼接去重，并按小节重新排成行；整页切换的谱面保持原样。
```

- [ ] **Step 7: Run all tests and lint**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 70 passed, 1 deselected, zero warnings; lint clean.

- [ ] **Step 8: Real-video check (CLI)**

The videos are cached at `/tmp/vtt/{a,b}/source.mp4`. If they are missing, download them with `uv run python -c "from pathlib import Path; from app.source import download_url; print(download_url('<url>', Path('/tmp/vtt/<n>')))"`, using `https://www.youtube.com/watch?v=U2m8IatzpAM` for b and `https://www.youtube.com/watch?v=2Ed7UsJd3Es` for a.

Run:
```bash
cd backend
uv run python -m app.cli /tmp/vtt/b/source.mp4 --out /tmp/vtt/b/out_stitch
uv run python -m app.cli /tmp/vtt/a/source.mp4 --out /tmp/vtt/a/out_stitch
```
Expected:
- **b:** `wrote 20 pages` (was 23). Stack the first 6 page PNGs vertically, downscale by 2, and view them: measure numbers 1, 2, 3 | 4, 5, 6 | 7, 8 | 9, 10 | 11, 12 | 13, 14 should run on with nothing repeated, and each line should start with a bar line.
- **a:** `wrote 16 pages`, identical to before.

- [ ] **Step 9: Commit**

```bash
git add backend/app/pipeline.py backend/tests/synth.py backend/tests/conftest.py backend/tests/test_stitch.py README.md
git commit -m "feat: stitch step-scrolling tab pages in the analysis pipeline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Follow-ups (out of scope)

- Remove the yellow current-measure highlight, which is still baked into the stitched lines.
- Continuous (smooth) horizontal scrolling.
