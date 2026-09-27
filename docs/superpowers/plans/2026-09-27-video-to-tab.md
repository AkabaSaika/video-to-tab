# video-to-tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app that takes a guitar video (file upload or bilibili/YouTube link), finds the tab panel at the bottom, detects each page of tab, removes the moving cursor, and exports all pages stitched into a PNG and a PDF.

**Architecture:** Python backend (FastAPI) runs a classic-CV pipeline: PyAV decodes frames → `region` finds staff lines to propose the tab ROI → `segment` splits the ROI stream into stable pages using a column-change metric that ignores narrow cursors → `compose` takes a per-pixel temporal median per page (erasing the cursor) and merges/marks duplicates → `export` stitches PNG/PDF. Jobs run in background threads with state on disk. A Vite + Vue 3 SPA drives the flow: input → adjust region → review/reorder → export.

**Tech Stack:** Python 3.12, uv, FastAPI, PyAV, OpenCV (headless), NumPy, yt-dlp, img2pdf, pytest, ruff; Node 24, Vite 7, Vue 3.5, Vitest 3.

**Spec:** `docs/superpowers/specs/2026-09-27-video-to-tab-design.md`

## Global Constraints

- Local single-user app: no database, no queue; job state lives in memory and in `data/jobs/<id>/state.json`.
- Tab scroll mode supported: whole-page/line switching only (no continuous horizontal scrolling).
- Output: stitched PNG long image + PDF (A4, never splitting a page image). No symbol OCR.
- Region: automatic detection + manual adjustment in the UI.
- Download ≤1080p **video-only** streams with yt-dlp (no merge step → system ffmpeg is not required). Surface yt-dlp errors verbatim with a hint to use cookies (`VTT_COOKIES_FILE`) or upload the file.
- All user-facing messages are in Chinese.
- Backend commands run from `backend/` via `uv run …`; frontend commands from `frontend/` via `npm …`.
- Lint: `ruff check` + `ruff format --check` clean on `app` and `tests` (line length 100).

## Deviations from the spec (decided while prototyping)

The whole pipeline was prototyped and run on two real YouTube tab videos before this plan was written. These changes came out of that:

1. **Duplicate detection uses the same column-change metric as page segmentation, not pHash/SSIM.** Two tab pages are mostly white paper plus identical staff lines, so pHash and SSIM rate different pages as near-identical. The column-change metric separates them cleanly: 0.46 between different pages versus 0.02 for a cursor move. `imagehash` is therefore not a dependency; `scikit-image` is used only in tests.
2. **Region detection runs on each frame separately, then votes on staves.** The spec's temporal median doesn't work because the staff sits at a different height on each page (860–892 px in a real video), which blurs the lines. Other changes:
   - Horizontal extent comes from columns where at least half the staff lines have ink, so chord diagrams are excluded.
   - When several staves are found, the ones with the most lines are kept, so a level guitar neck is ignored.
   - The top and bottom edges are trimmed back to the panel background.
3. **Page order and deletions are sent with the export request.** `POST /export {order, fmt}` replaces a separate `PUT /pages`. Merging in the UI is simply deleting one of the two pages.
4. **Duplicate labels depend on position.** Adjacent identical pages are merged; non-adjacent repeats are kept and labeled "重复：同第 N 段".

## File Structure

```
.gitignore
README.md
backend/
  pyproject.toml
  app/
    __init__.py
    models.py      # Roi / Segment / Page dataclasses
    frames.py      # PyAV: probe, sample_frames(fps, roi), grab_frames, frame_at
    segment.py     # prep_gray, frame_change (cursor-robust), find_segments
    compose.py     # median_page, same_content, merge_adjacent, mark_repeats, build_pages
    export.py      # stitch_vertical, paginate, export_png, export_pdf
    region.py      # detect_staves, has_staff_lines, trim_to_panel, detect_region
    pipeline.py    # analyze(video, roi, params, progress) -> list[Page]
    cli.py         # python -m app.cli VIDEO [--roi x,y,w,h] --out DIR
    source.py      # save_upload, normalize_url, download_url (yt-dlp)
    jobs.py        # Job, Status, JobStore (threads + state.json)
    workflow.py    # prepare / run_analysis / export glue per job
    main.py        # FastAPI app factory + routes + static frontend
  tests/
    __init__.py
    synth.py       # synthetic guitar-video generator (fixtures)
    conftest.py
    test_models.py test_frames.py test_segment.py test_compose.py test_export.py
    test_region.py test_pipeline.py test_source.py test_api.py
frontend/
  package.json vite.config.js index.html
  src/main.js src/style.css src/api.js src/App.vue
  src/lib/roi.js src/lib/roi.test.js src/lib/pages.js src/lib/pages.test.js
  src/views/InputView.vue src/views/RegionEditor.vue src/views/ReviewView.vue
```

(Views are named `*View.vue` rather than the spec's `Input.vue`, because `Input` collides with the built-in `<input>` element.)

---

### Task 1: Project scaffold, models, synthetic video fixture

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/app/__init__.py` (empty), `backend/app/models.py`, `backend/tests/__init__.py` (empty), `backend/tests/synth.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Roi(x, y, w, h)` with `.crop(frame)`, `.clamp(width, height) -> Roi`, `.iou(other) -> float`, `.to_dict()`; `Segment(start_idx, end_idx, start, end)`; `Page(image, start, end, duplicate_of=None)`.
- Produces (tests): `tests.synth` constants `W=640, H=480, FPS=25, ROI_TRUTH=Roi(20,300,600,180), LINE_YS, TIMELINE, EXPECTED_PAGES`, `render_panel(seed|None, dark=False)`, `make_video(path, dark=False) -> SynthVideo(path, roi, panels)`; pytest fixtures `synth_video`, `synth_video_dark` (session-scoped MJPG .avi files).

The synthetic video has a random-noise "performance" area on top and a white tab panel below. The panel contains 6 staff lines, fret numbers on white boxes (these interrupt the lines, as real tabs do), and a 3 px red cursor sweeping across each page. Its timeline is: blank panel (0–1 s) → A → 0.4 s fade → B → 0.2 s black flash → B → C (hard cut) → A. The expected result is the pages A, B, C, A, with the final A marked as a duplicate of page 0.

- [ ] **Step 1: Create `.gitignore` and `backend/pyproject.toml`**

`.gitignore`:

```gitignore
__pycache__/
.venv/
.pytest_cache/
.ruff_cache/
node_modules/
frontend/dist/
data/
```

`backend/pyproject.toml`:

```toml
[project]
name = "video-to-tab"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "python-multipart>=0.0.9",
  "opencv-python-headless>=4.10",
  "av>=13",
  "numpy>=2",
  "yt-dlp>=2025.1.1",
  "img2pdf>=0.5",
]

[dependency-groups]
dev = ["pytest>=8", "httpx>=0.27", "scikit-image>=0.24", "ruff>=0.6"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["network: needs internet access (deselect with -m 'not network')"]
addopts = "-m 'not network'"

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.File", "fastapi.Form"]
```

Run: `cd backend && uv sync`
Expected: creates `backend/.venv` and `backend/uv.lock` and installs all packages (PyAV wheels bundle FFmpeg libraries).

- [ ] **Step 2: Write the fixture generator and the failing test**

`backend/tests/synth.py`:

```python
"""Synthetic guitar-video generator used by the tests.

Layout (640x480, 25 fps): random noise "performance" on top, white tab panel at
ROI_TRUTH with 6 staff lines and random fret numbers, a red cursor sweeping each page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.models import Roi

W, H, FPS = 640, 480, 25
ROI_TRUTH = Roi(20, 300, 600, 180)
LINE_YS = [350 + 16 * i for i in range(6)]  # absolute y of staff lines
LINE_X0, LINE_X1 = 30, 610

# (kind, page, start, end); kind: blank | page | fade | flash
TIMELINE = [
    ("blank", None, 0.0, 1.0),
    ("page", "A", 1.0, 3.0),
    ("fade", ("A", "B"), 3.0, 3.4),
    ("page", "B", 3.4, 5.4),
    ("flash", None, 5.4, 5.6),
    ("page", "B", 5.6, 7.6),
    ("page", "C", 7.6, 9.6),
    ("page", "A", 9.6, 11.6),
]
EXPECTED_PAGES = [  # (page, start, end, duplicate_of) after merge + repeat marking
    ("A", 1.0, 3.0, None),
    ("B", 3.4, 7.6, None),
    ("C", 7.6, 9.6, None),
    ("A", 9.6, 11.6, 0),
]


def render_panel(seed: int | None, dark: bool = False) -> np.ndarray:
    """Return a clean ROI-sized BGR panel. seed=None gives an empty panel (no staff)."""
    bg, ink = (30, 255) if dark else (255, 0)
    panel = np.full((ROI_TRUTH.h, ROI_TRUTH.w, 3), bg, np.uint8)
    if seed is None:
        return panel
    ox, oy = ROI_TRUTH.x, ROI_TRUTH.y
    for y in LINE_YS:
        cv2.line(panel, (LINE_X0 - ox, y - oy), (LINE_X1 - ox, y - oy), (ink,) * 3, 1)
    rng = np.random.default_rng(seed)
    for k in range(16):
        x = 50 + k * 34 + int(rng.integers(-4, 5)) - ox
        y = LINE_YS[int(rng.integers(0, 6))] - oy
        text = str(int(rng.integers(0, 20)))
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(panel, (x - 1, y - th // 2 - 2), (x + tw + 1, y + th // 2 + 2), (bg,) * 3, -1)
        cv2.putText(panel, text, (x, y + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (ink,) * 3, 1)
    return panel


PANELS = {"A": 1, "B": 2, "C": 3}


@dataclass
class SynthVideo:
    path: Path
    roi: Roi
    panels: dict[str, np.ndarray]


def make_video(path: Path, dark: bool = False) -> SynthVideo:
    panels = {name: render_panel(seed, dark) for name, seed in PANELS.items()}
    blank = render_panel(None, dark)
    rng = np.random.default_rng(0)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    total = int(round(TIMELINE[-1][3] * FPS))
    for f in range(total):
        t = f / FPS
        frame = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
        frame[ROI_TRUTH.y :, :] = 90
        kind, page, start, end = next(e for e in TIMELINE if e[2] <= t + 1e-9 < e[3])
        if kind == "blank":
            panel = blank
        elif kind == "flash":
            panel = np.zeros_like(blank)
        elif kind == "fade":
            a = (t - start) / (end - start)
            panel = cv2.addWeighted(panels[page[0]], 1 - a, panels[page[1]], a, 0)
        else:
            panel = panels[page].copy()
            cx = int((t - start) / (end - start) * (ROI_TRUTH.w - 1))
            cv2.line(panel, (cx, 0), (cx, ROI_TRUTH.h - 1), (0, 0, 255), 3)
        r = ROI_TRUTH
        frame[r.y : r.y + r.h, r.x : r.x + r.w] = panel
        writer.write(frame)
    writer.release()
    return SynthVideo(path, ROI_TRUTH, panels)
```

`backend/tests/conftest.py`:

```python
import pytest

from tests.synth import make_video


@pytest.fixture(scope="session")
def synth_video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("synth") / "synth.avi")


@pytest.fixture(scope="session")
def synth_video_dark(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("synth_dark") / "synth_dark.avi", dark=True)
```

`backend/tests/test_models.py`:

```python
import cv2
import numpy as np

from app.models import Roi
from tests.synth import FPS, TIMELINE, H, W


def test_roi_crop_clamp_iou():
    frame = np.arange(100 * 200).reshape(100, 200)
    roi = Roi(10, 20, 30, 40)
    assert roi.crop(frame).shape == (40, 30)
    assert roi.crop(frame)[0, 0] == frame[20, 10]
    assert Roi(-5, 90, 500, 50).clamp(200, 100) == Roi(0, 90, 200, 10)
    assert roi.iou(roi) == 1.0
    assert Roi(0, 0, 10, 10).iou(Roi(5, 0, 10, 10)) == 50 / 150
    assert Roi(0, 0, 10, 10).iou(Roi(20, 20, 5, 5)) == 0.0


def test_synth_video_is_readable(synth_video):
    cap = cv2.VideoCapture(str(synth_video.path))
    assert (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == (W, H)
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == round(TIMELINE[-1][3] * FPS)
    cap.release()
```

Also create empty `backend/app/__init__.py` and `backend/tests/__init__.py`.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_models.py -v`
Expected: FAIL — `ImportError while loading conftest` … `ModuleNotFoundError: No module named 'app.models'` (conftest imports `tests.synth`, which imports `app.models`)

- [ ] **Step 4: Write `backend/app/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    w: int
    h: int

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y : self.y + self.h, self.x : self.x + self.w]

    def clamp(self, width: int, height: int) -> Roi:
        x = min(max(self.x, 0), width - 1)
        y = min(max(self.y, 0), height - 1)
        w = max(1, min(self.w, width - x))
        h = max(1, min(self.h, height - y))
        return Roi(x, y, w, h)

    def iou(self, other: Roi) -> float:
        ix = max(0, min(self.x + self.w, other.x + other.w) - max(self.x, other.x))
        iy = max(0, min(self.y + self.h, other.y + other.h) - max(self.y, other.y))
        inter = ix * iy
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union else 0.0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class Segment:
    start_idx: int  # first sample index (inclusive)
    end_idx: int  # last sample index (inclusive)
    start: float  # seconds
    end: float  # seconds (end of last sample's interval)


@dataclass
class Page:
    image: np.ndarray  # BGR crop of the ROI, cursor removed
    start: float
    end: float
    duplicate_of: int | None = None  # index of an earlier page with identical content
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_models.py -v && uv run ruff check app tests && uv run ruff format --check app tests`
Expected: 2 passed, lint clean.

- [ ] **Step 6: Commit**

```bash
git add .gitignore backend/pyproject.toml backend/uv.lock backend/app backend/tests
git commit -m "feat: scaffold backend with models and synthetic video fixture

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Frame decoding (PyAV)

**Files:**
- Create: `backend/app/frames.py`
- Test: `backend/tests/test_frames.py`

**Interfaces:**
- Consumes: `Roi` (Task 1).
- Produces: `DecodeError(Exception)`; `VideoInfo(width, height, duration, fps)`; `probe(path) -> VideoInfo`; `sample_frames(path, fps=5.0, roi=None) -> Iterator[(t_seconds, BGR ndarray)]` with t relative to the first frame and deterministic sampling (the same indices on every pass); `grab_frames(path, count=20) -> list[BGR]` full frames spread over the video; `frame_at(path, t) -> BGR` (seek + decode forward).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_frames.py`:

```python
import numpy as np
import pytest

from app.frames import DecodeError, frame_at, grab_frames, probe, sample_frames
from tests.synth import ROI_TRUTH


def test_probe(synth_video):
    info = probe(synth_video.path)
    assert (info.width, info.height) == (640, 480)
    assert abs(info.duration - 11.6) < 0.1
    assert abs(info.fps - 25) < 0.01


def test_sample_frames_rate_and_crop(synth_video):
    samples = list(sample_frames(synth_video.path, fps=5, roi=ROI_TRUTH))
    times = [t for t, _ in samples]
    assert len(samples) == 58  # 11.6 s * 5 fps
    assert times[:3] == pytest.approx([0.0, 0.2, 0.4])
    assert samples[0][1].shape == (ROI_TRUTH.h, ROI_TRUTH.w, 3)


def test_grab_frames_spreads_over_video(synth_video):
    frames = grab_frames(synth_video.path, 10)
    assert len(frames) == 10
    assert frames[0].shape == (480, 640, 3)


def test_frame_at_matches_sequential_decode(synth_video):
    expected = [img for t, img in sample_frames(synth_video.path, fps=25) if abs(t - 5.0) < 1e-3]
    assert np.array_equal(frame_at(synth_video.path, 5.0), expected[0])


def test_decode_error_for_non_video(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(DecodeError):
        probe(bad)
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_frames.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.frames'`

- [ ] **Step 3: Write the implementation**

`backend/app/frames.py`:

```python
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from app.models import Roi


class DecodeError(Exception):
    pass


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float


def _open(path: Path):
    try:
        return av.open(str(path))
    except av.error.FFmpegError as exc:  # type: ignore[attr-defined]
        raise DecodeError(f"无法解码视频：{exc}") from exc


def probe(path: Path) -> VideoInfo:
    with _open(path) as container:
        if not container.streams.video:
            raise DecodeError("文件中没有视频流")
        stream = container.streams.video[0]
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = container.duration / 1_000_000
        else:
            duration = 0.0
        fps = float(stream.average_rate or stream.guessed_rate or 0)
        return VideoInfo(stream.codec_context.width, stream.codec_context.height, duration, fps)


def sample_frames(
    path: Path, fps: float = 5.0, roi: Roi | None = None
) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (t_seconds, BGR frame) roughly every 1/fps seconds, t relative to first frame."""
    step = 1.0 / fps
    with _open(path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        t0: float | None = None
        next_t = 0.0
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            if t0 is None:
                t0 = frame.time
            t = frame.time - t0
            if t + 1e-6 < next_t:
                continue
            while next_t <= t + 1e-6:
                next_t += step
            img = frame.to_ndarray(format="bgr24")
            if roi is not None:
                img = roi.crop(img).copy()
            yield t, img


def grab_frames(path: Path, count: int = 20) -> list[np.ndarray]:
    """Return about `count` full frames spread evenly over the video."""
    info = probe(path)
    fps = count / info.duration if info.duration > 0 else 1.0
    return [img for _, img in sample_frames(path, fps=fps)][:count]


def frame_at(path: Path, t: float) -> np.ndarray:
    """Return the first full BGR frame at or after t seconds (seeks, then decodes forward)."""
    with _open(path) as container:
        stream = container.streams.video[0]
        start = float(stream.start_time * stream.time_base) if stream.start_time else 0.0
        container.seek(int((start + t) / stream.time_base), stream=stream, backward=True)
        last = None
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            last = frame
            if frame.time - start + 1e-6 >= t:
                break
        if last is None:
            raise DecodeError("视频没有可解码的帧")
        return last.to_ndarray(format="bgr24")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_frames.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/frames.py backend/tests/test_frames.py
git commit -m "feat: add PyAV frame sampling, probing and seeking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Page-change segmentation

**Files:**
- Create: `backend/app/segment.py`
- Test: `backend/tests/test_segment.py`

**Interfaces:**
- Consumes: `Segment` (Task 1), `sample_frames` (Task 2, test only).
- Produces: `SEG_WIDTH = 480`; `SegmentParams(diff_threshold=0.15, min_duration=0.8, pixel_delta=40)`; `prep_gray(img, width=480) -> uint8 gray`; `frame_change(a, b, pixel_delta=40) -> float` (fraction of columns with ≥2 pixels changed by >pixel_delta); `find_segments(times, grays, fps, params=None) -> list[Segment]`.

Why a column metric: a moving cursor or note highlight changes only a few narrow columns (~2%), whereas a page turn changes digits spread across the whole width (>40%). Every sample whose change from the previous sample exceeds the threshold starts a new run. Runs shorter than `min_duration`, such as fade-transition frames and short flashes, are dropped.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_segment.py`:

```python
import numpy as np

from app.frames import sample_frames
from app.segment import SegmentParams, find_segments, frame_change, prep_gray
from tests.synth import ROI_TRUTH, render_panel


def gray_panel(seed, cursor_x=None):
    panel = render_panel(seed)
    if cursor_x is not None:
        panel[:, cursor_x : cursor_x + 3] = (0, 0, 255)
    return prep_gray(panel)


def test_prep_gray_resizes_to_fixed_width():
    assert prep_gray(render_panel(1)).shape == (144, 480)


def test_cursor_movement_is_small_change_page_turn_is_large():
    cursor = frame_change(gray_panel(1, 100), gray_panel(1, 160))
    turn = frame_change(gray_panel(1, 100), gray_panel(2, 160))
    assert cursor < 0.05
    assert turn > 0.3


def test_find_segments_splits_on_changes_and_drops_short_runs():
    a, b = gray_panel(1), gray_panel(2)
    blank = np.zeros_like(a)
    grays = [a] * 5 + [blank] + [b] * 5  # a 0.2 s flash between two pages
    times = [i * 0.2 for i in range(len(grays))]
    segs = find_segments(times, grays, fps=5, params=SegmentParams(min_duration=0.8))
    assert [(s.start_idx, s.end_idx) for s in segs] == [(0, 4), (6, 10)]
    assert segs[0].start == 0.0 and abs(segs[0].end - 1.0) < 1e-9


def test_segments_on_synth_video(synth_video):
    times, grays = [], []
    for t, img in sample_frames(synth_video.path, fps=5, roi=ROI_TRUTH):
        times.append(t)
        grays.append(prep_gray(img))
    segs = find_segments(times, grays, fps=5)
    # blank intro, A, B, B (after flash), C, A -- fade and flash frames are dropped
    starts = [round(s.start, 1) for s in segs]
    assert starts == [0.0, 1.0, 3.4, 5.6, 7.6, 9.6]
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_segment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.segment'`

- [ ] **Step 3: Write the implementation**

`backend/app/segment.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models import Segment

SEG_WIDTH = 480


@dataclass(frozen=True)
class SegmentParams:
    diff_threshold: float = 0.15  # fraction of changed columns that counts as a page change
    min_duration: float = 0.8  # seconds; shorter stable runs are dropped
    pixel_delta: int = 40  # grey-level change that counts as "changed"


def prep_gray(img: np.ndarray, width: int = SEG_WIDTH) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    if w == width:
        return gray
    return cv2.resize(gray, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)


def frame_change(a: np.ndarray, b: np.ndarray, pixel_delta: int = 40) -> float:
    """Fraction of columns containing a real change between two grey images.

    A moving cursor or note highlight touches only a few narrow columns, while a page
    turn changes digits spread across the whole width, so this separates the two.
    """
    changed = cv2.absdiff(a, b) > pixel_delta
    return float((changed.sum(axis=0) >= 2).mean())


def find_segments(
    times: list[float], grays: list[np.ndarray], fps: float, params: SegmentParams | None = None
) -> list[Segment]:
    params = params or SegmentParams()
    if not grays:
        return []
    breaks = [0]
    for i in range(1, len(grays)):
        if frame_change(grays[i - 1], grays[i], params.pixel_delta) >= params.diff_threshold:
            breaks.append(i)
    breaks.append(len(grays))
    segments = []
    for start, stop in zip(breaks, breaks[1:], strict=False):
        end_idx = stop - 1
        end_t = times[end_idx] + 1.0 / fps
        if end_t - times[start] >= params.min_duration:
            segments.append(Segment(start, end_idx, times[start], end_t))
    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_segment.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/segment.py backend/tests/test_segment.py
git commit -m "feat: segment ROI stream into stable pages with cursor-robust change metric

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Page composition and de-duplication

**Files:**
- Create: `backend/app/compose.py`
- Test: `backend/tests/test_compose.py`

**Interfaces:**
- Consumes: `Page`, `Roi`, `Segment` (Task 1); `sample_frames` (Task 2); `frame_change`, `prep_gray` (Task 3).
- Produces: `MAX_MEDIAN_FRAMES = 25`; `SAME_PAGE_THRESHOLD = 0.05`; `median_page(frames) -> BGR`; `same_content(a, b) -> bool`; `merge_adjacent(pages) -> list[Page]`; `mark_repeats(pages) -> list[Page]` (sets `duplicate_of` to the index of the first earlier identical non-duplicate page); `build_pages(video, roi, segments, fps, on_progress=lambda i: None) -> list[Page]` (second decode pass, ≤25 evenly spread frames per segment).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_compose.py`:

```python
import numpy as np

from app.compose import build_pages, mark_repeats, median_page, merge_adjacent, same_content
from app.models import Page, Segment
from tests.synth import ROI_TRUTH, render_panel


def with_cursor(panel, x):
    out = panel.copy()
    out[:, x : x + 3] = (0, 0, 255)
    return out


def test_median_page_removes_moving_cursor():
    panel = render_panel(1)
    frames = [with_cursor(panel, x) for x in range(0, 600, 60)]
    assert np.array_equal(median_page(frames), panel)


def test_median_page_with_two_frames_picks_a_real_frame():
    a, b = render_panel(1), render_panel(2)
    result = median_page([a, b])
    assert np.array_equal(result, a) or np.array_equal(result, b)


def test_same_content_ignores_cursor_but_not_different_notes():
    panel = render_panel(1)
    assert same_content(panel, with_cursor(panel, 300))
    assert not same_content(panel, render_panel(2))
    assert not same_content(panel, panel[:, :100])


def page(seed, start, end):
    return Page(render_panel(seed), start, end)


def test_merge_adjacent_joins_identical_neighbours():
    pages = merge_adjacent([page(1, 0, 2), page(2, 2, 4), page(2, 4, 7), page(1, 7, 9)])
    assert [(p.start, p.end) for p in pages] == [(0, 2), (2, 7), (7, 9)]


def test_mark_repeats_points_to_first_occurrence():
    pages = mark_repeats([page(1, 0, 2), page(2, 2, 4), page(1, 4, 6), page(1, 6, 8)])
    assert [p.duplicate_of for p in pages] == [None, None, 0, 0]


def test_build_pages_from_video(synth_video):
    segs = [Segment(5, 14, 1.0, 3.0), Segment(38, 47, 7.6, 9.6)]  # page A and page C
    pages = build_pages(synth_video.path, ROI_TRUTH, segs, fps=5)
    assert [(p.start, p.end) for p in pages] == [(1.0, 3.0), (7.6, 9.6)]
    assert same_content(pages[0].image, synth_video.panels["A"])
    assert same_content(pages[1].image, synth_video.panels["C"])
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_compose.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.compose'`

- [ ] **Step 3: Write the implementation**

`backend/app/compose.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.frames import sample_frames
from app.models import Page, Roi, Segment
from app.segment import frame_change, prep_gray

MAX_MEDIAN_FRAMES = 25
SAME_PAGE_THRESHOLD = 0.05  # frame_change below this means identical content


def median_page(frames: list[np.ndarray]) -> np.ndarray:
    """Per-pixel temporal median: a cursor that keeps moving never wins the vote."""
    stack = np.stack(frames)
    median = np.median(stack, axis=0).astype(np.uint8)
    if len(frames) >= 3:
        return median
    errors = [np.abs(f.astype(np.int16) - median).mean() for f in frames]
    return frames[int(np.argmin(errors))]


def same_content(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return False
    return frame_change(prep_gray(a), prep_gray(b)) < SAME_PAGE_THRESHOLD


def merge_adjacent(pages: list[Page]) -> list[Page]:
    merged: list[Page] = []
    for page in pages:
        if merged and same_content(merged[-1].image, page.image):
            prev = merged[-1]
            keep = prev.image if prev.end - prev.start >= page.end - page.start else page.image
            merged[-1] = Page(keep, prev.start, page.end)
        else:
            merged.append(page)
    return merged


def mark_repeats(pages: list[Page]) -> list[Page]:
    for i, page in enumerate(pages):
        page.duplicate_of = None
        for j in range(i):
            if pages[j].duplicate_of is None and same_content(pages[j].image, page.image):
                page.duplicate_of = j
                break
    return pages


def build_pages(
    video: Path,
    roi: Roi,
    segments: list[Segment],
    fps: float,
    on_progress: Callable[[int], None] = lambda i: None,
) -> list[Page]:
    """Second decoding pass: gather ROI frames of each segment and median them."""
    wanted: dict[int, int] = {}  # sample index -> segment index
    for s_i, seg in enumerate(segments):
        n = seg.end_idx - seg.start_idx + 1
        picks = np.linspace(seg.start_idx, seg.end_idx, min(n, MAX_MEDIAN_FRAMES))
        for idx in np.unique(picks.round().astype(int)):
            wanted[int(idx)] = s_i
    buckets: list[list[np.ndarray]] = [[] for _ in segments]
    for idx, (_, img) in enumerate(sample_frames(video, fps=fps, roi=roi)):
        on_progress(idx)
        if idx in wanted:
            buckets[wanted[idx]].append(img)
    return [
        Page(median_page(frames), seg.start, seg.end)
        for seg, frames in zip(segments, buckets, strict=True)
        if frames
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_compose.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/compose.py backend/tests/test_compose.py
git commit -m "feat: compose clean pages via temporal median and de-duplicate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: PNG / PDF export

**Files:**
- Create: `backend/app/export.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Produces: `GAP = 24`; `stitch_vertical(images, gap=GAP) -> BGR` (white gaps, right-pads narrower images with white; raises `ValueError` on empty); `paginate(images, gap=GAP) -> list[BGR]` (A4-proportioned sheets of the max width; never splits an image); `export_png(images, out) -> Path`; `export_pdf(images, out) -> Path` (one A4 PDF page per sheet via img2pdf).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_export.py`:

```python
import re

import numpy as np

from app.export import GAP, export_pdf, export_png, paginate, stitch_vertical


def img(h, w, value=0):
    return np.full((h, w, 3), value, np.uint8)


def test_stitch_pads_width_and_adds_gaps():
    out = stitch_vertical([img(10, 100), img(20, 80)])
    assert out.shape == (10 + GAP + 20, 100, 3)
    assert (out[10 : 10 + GAP] == 255).all()  # white gap
    assert (out[10 + GAP :, 80:] == 255).all()  # right padding of the narrow image


def test_paginate_never_splits_an_image():
    sheets = paginate([img(100, 100)] * 3)  # A4 sheet of width 100 is 141 tall
    assert len(sheets) == 3
    assert all(s.shape == (141, 100, 3) for s in sheets)
    assert len(paginate([img(30, 100)] * 3)) == 1


def test_export_files(tmp_path):
    png = export_png([img(10, 50), img(10, 50)], tmp_path / "t.png")
    assert png.read_bytes()[:4] == b"\x89PNG"
    pdf = export_pdf([img(100, 100)] * 3, tmp_path / "t.pdf")
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page(?!s)", data)) == 3
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.export'`

- [ ] **Step 3: Write the implementation**

`backend/app/export.py`:

```python
from __future__ import annotations

import io
import math
from pathlib import Path

import cv2
import img2pdf
import numpy as np

GAP = 24
A4_RATIO = math.sqrt(2)  # height / width


def _pad_width(img: np.ndarray, width: int) -> np.ndarray:
    if img.shape[1] == width:
        return img
    pad = np.full((img.shape[0], width - img.shape[1], 3), 255, np.uint8)
    return np.hstack([img, pad])


def stitch_vertical(images: list[np.ndarray], gap: int = GAP) -> np.ndarray:
    if not images:
        raise ValueError("没有可导出的页面")
    width = max(i.shape[1] for i in images)
    parts: list[np.ndarray] = []
    for i, img in enumerate(images):
        if i:
            parts.append(np.full((gap, width, 3), 255, np.uint8))
        parts.append(_pad_width(img, width))
    return np.vstack(parts)


def export_png(images: list[np.ndarray], out: Path) -> Path:
    cv2.imwrite(str(out), stitch_vertical(images))
    return out


def paginate(images: list[np.ndarray], gap: int = GAP) -> list[np.ndarray]:
    """Pack images top-to-bottom into A4-proportioned sheets without splitting an image."""
    width = max(i.shape[1] for i in images)
    sheet_h = int(width * A4_RATIO)
    sheets: list[list[np.ndarray]] = [[]]
    used = 0
    for img in images:
        need = img.shape[0] + (gap if sheets[-1] else 0)
        if sheets[-1] and used + need > sheet_h:
            sheets.append([])
            used = 0
            need = img.shape[0]
        sheets[-1].append(img)
        used += need
    result = []
    for group in sheets:
        body = stitch_vertical(group, gap)
        height = max(sheet_h, body.shape[0])
        canvas = np.full((height, width, 3), 255, np.uint8)
        canvas[: body.shape[0]] = body
        result.append(canvas)
    return result


def export_pdf(images: list[np.ndarray], out: Path) -> Path:
    blobs = []
    for sheet in paginate(images):
        ok, buf = cv2.imencode(".png", sheet)
        blobs.append(io.BytesIO(buf.tobytes()).getvalue())
    layout = img2pdf.get_layout_fun((img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)))
    out.write_bytes(img2pdf.convert(blobs, layout_fun=layout))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_export.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export.py backend/tests/test_export.py
git commit -m "feat: export stitched PNG and paginated A4 PDF

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Tab region detection

**Files:**
- Create: `backend/app/region.py`
- Test: `backend/tests/test_region.py`

**Interfaces:**
- Consumes: `Roi` (Task 1); `grab_frames` (Task 2, test only).
- Produces: `Staff(lines, x0, x1)` with `.spacing`; `RegionGuess(roi, confidence)`; `detect_staves(img, min_len_ratio=0.4) -> list[Staff]`; `has_staff_lines(img) -> bool`; `staves_bbox(staves, width, height) -> Roi`; `trim_to_panel(gray, roi, tolerance=25, min_bg=0.6) -> Roi`; `detect_region(frames) -> RegionGuess` (fallback: bottom third, confidence 0).

The details in this code were settled against real videos; keep them as written:
- **Line detection:** an adaptive threshold with a 31 px block, followed by an opening with a 15 px horizontal kernel. A row counts as a line when its total coverage reaches 40% of the width. Fret numbers on white boxes cut tab lines into short pieces, so a single long-kernel opening fails.
- **Polarity:** both polarities are tried and the one with more lines in total wins. With the wrong polarity, the gaps *between* lines are detected instead, which gives n−1 lines.
- **Line extent:** a line's horizontal extent is the longest run of columns where at least half of the staff's lines have ink, with gaps up to 2× the line spacing bridged. This excludes chord-diagram grids that happen to share a row.
- **Voting across frames:** detection runs on each frame. A staff needs a vertically overlapping staff in at least half of the frames, and among those only the staves with the most lines are kept. The vertical extent is the union of those staves plus 3× spacing for chord names and stems; the horizontal extent is the median. The box is then trimmed to the panel background on the per-pixel median frame.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_region.py`:

```python
import cv2
import numpy as np

from app.frames import grab_frames
from app.models import Roi
from app.region import detect_region, detect_staves, has_staff_lines, trim_to_panel
from tests.synth import LINE_YS, ROI_TRUTH, H, W, render_panel


def test_detect_staves_light_and_dark():
    for dark in (False, True):
        staves = detect_staves(render_panel(1, dark=dark))
        assert len(staves) == 1
        assert [y + ROI_TRUTH.y for y in staves[0].lines] == LINE_YS


def test_has_staff_lines():
    assert has_staff_lines(render_panel(2))
    assert not has_staff_lines(render_panel(None))


def test_trim_to_panel_cuts_rows_that_are_not_panel():
    gray = np.full((100, 50), 255, np.uint8)
    gray[:20] = 60  # video above the panel
    assert trim_to_panel(gray, Roi(0, 0, 50, 100)) == Roi(0, 20, 50, 80)


def test_detect_region_on_videos(synth_video, synth_video_dark):
    for video in (synth_video, synth_video_dark):
        guess = detect_region(grab_frames(video.path, 20))
        assert guess.roi.iou(ROI_TRUTH) > 0.9
        assert guess.confidence > 0.7


def frame_with_panel(seed, distractor=False):
    frame = np.full((H, W, 3), 120, np.uint8)
    r = ROI_TRUTH
    frame[r.y : r.y + r.h, r.x : r.x + r.w] = render_panel(seed)
    if distractor:  # four "guitar strings" that happen to be level in this frame
        for i in range(4):
            cv2.line(frame, (40, 60 + 10 * i), (600, 60 + 10 * i), (20, 20, 20), 1)
    return frame


def test_ignores_staff_like_lines_seen_in_few_frames():
    frames = [frame_with_panel(i % 3 + 1, distractor=(i < 3)) for i in range(10)]
    guess = detect_region(frames)
    assert guess.roi.iou(ROI_TRUTH) > 0.9
    assert guess.confidence == 1.0


def test_falls_back_to_bottom_third_without_tab():
    guess = detect_region([np.full((H, W, 3), 200, np.uint8) for _ in range(5)])
    assert guess.confidence == 0.0
    assert guess.roi == Roi(0, H * 2 // 3, W, H - H * 2 // 3)
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_region.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.region'`

- [ ] **Step 3: Write the implementation**

`backend/app/region.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models import Roi


@dataclass(frozen=True)
class Staff:
    lines: list[int]  # y of each line, top to bottom
    x0: int
    x1: int

    @property
    def spacing(self) -> float:
        return float(np.mean(np.diff(self.lines)))


@dataclass(frozen=True)
class RegionGuess:
    roi: Roi
    confidence: float  # 0..1; 0 means fallback guess


def _to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _line_mask(gray: np.ndarray) -> np.ndarray:
    """Pixels that are darker than their surroundings and part of a >=15px horizontal run.

    The 31px adaptive block keeps a thin line from lifting the local mean enough to
    flag the background next to it."""
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel) > 0


def _line_rows(mask: np.ndarray, min_len_ratio: float) -> list[np.ndarray]:
    """Row-index groups of lines covering >= min_len_ratio of the width.

    Coverage is counted over the whole row, so lines broken by fret numbers still count."""
    rows = np.flatnonzero(mask.sum(axis=1) >= mask.shape[1] * min_len_ratio)
    if rows.size == 0:
        return []
    return np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)


def _staff_extent(mask: np.ndarray, groups: list[np.ndarray], spacing: float) -> tuple[int, int]:
    """Longest column run where at least half of the staff's lines have ink.

    Other overlays (chord diagrams, logos) rarely line up with most staff lines."""
    coverage = np.mean([mask[g].any(axis=0) for g in groups], axis=0) >= 0.5
    bridge = int(2 * spacing) | 1  # close gaps left by fret numbers
    closed = cv2.morphologyEx(
        coverage.astype(np.uint8)[None, :],
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (bridge, 1)),
    )[0]
    cols = np.flatnonzero(closed)
    if cols.size == 0:
        return 0, mask.shape[1] - 1
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    longest = max(runs, key=len)
    return int(longest[0]), int(longest[-1])


def _make_staff(mask: np.ndarray, groups: list[np.ndarray]) -> Staff:
    lines = [int(round(g.mean())) for g in groups]
    x0, x1 = _staff_extent(mask, groups, float(np.mean(np.diff(lines))))
    return Staff(lines, x0, x1)


def _group_staves(mask: np.ndarray, rows: list[np.ndarray]) -> list[Staff]:
    """Group consecutive lines with (nearly) equal gaps; >=4 lines make a staff."""
    staves: list[Staff] = []
    group: list[np.ndarray] = []
    for line in rows:
        if not group:
            group = [line]
            continue
        gap = line.mean() - group[-1].mean()
        if len(group) == 1:
            ok = gap >= 4
        else:
            prev_gap = group[-1].mean() - group[-2].mean()
            ok = abs(gap - prev_gap) <= 0.2 * prev_gap + 1
        if ok:
            group.append(line)
        elif len(group) >= 4:
            staves.append(_make_staff(mask, group))
            group = [line]
        else:
            # the previous line may still start a new staff with this one
            group = [group[-1], line] if gap >= 4 else [line]
    if len(group) >= 4:
        staves.append(_make_staff(mask, group))
    return staves


def detect_staves(img: np.ndarray, min_len_ratio: float = 0.4) -> list[Staff]:
    """Find staves: groups of >=4 evenly spaced long horizontal lines (tab = 6, bass = 4).

    Both polarities are tried (dark lines on a light panel, light lines on a dark one).
    With the wrong polarity the gaps *between* lines show up instead, which yields one
    line fewer per staff, so the polarity with more lines in total wins."""
    gray = _to_gray(img)
    candidates = []
    for g in (gray, 255 - gray):
        mask = _line_mask(g)
        candidates.append(_group_staves(mask, _line_rows(mask, min_len_ratio)))
    return max(candidates, key=lambda staves: sum(len(st.lines) for st in staves))


def has_staff_lines(img: np.ndarray) -> bool:
    return len(detect_staves(img)) > 0


def _overlaps(a: Staff, b: Staff) -> bool:
    return a.lines[0] <= b.lines[-1] and b.lines[0] <= a.lines[-1]


def staves_bbox(staves: list[Staff], width: int, height: int) -> Roi:
    """Box around all staves, with room for chord names above and note stems below.

    Vertical extent is the union; horizontal extent is the median over detections."""
    s = max(st.spacing for st in staves)
    x0 = np.median([st.x0 for st in staves]) - s
    x1 = np.median([st.x1 for st in staves]) + s
    y0 = min(st.lines[0] for st in staves) - 3 * s
    y1 = max(st.lines[-1] for st in staves) + 3 * s
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(width, int(x1)), min(height, int(y1))
    return Roi(x0, y0, x1 - x0, y1 - y0)


def trim_to_panel(gray: np.ndarray, roi: Roi, tolerance: int = 25, min_bg: float = 0.6) -> Roi:
    """Shrink the top/bottom edges until rows look like the tab panel background,
    so the margin reserved for chord names does not swallow part of the video."""
    crop = roi.crop(gray)
    bg = np.median(crop)
    is_panel = (np.abs(crop.astype(np.int16) - bg) < tolerance).mean(axis=1) >= min_bg
    rows = np.flatnonzero(is_panel)
    if rows.size == 0:
        return roi
    top, bottom = int(rows[0]), int(rows[-1])
    return Roi(roi.x, roi.y + top, roi.w, bottom - top + 1)


def detect_region(frames: list[np.ndarray]) -> RegionGuess:
    """Locate the tab area from several frames.

    Each frame is detected on its own (the staff may sit a little higher or lower on
    every page). A staff is trusted only if some staff overlaps it vertically in at
    least half of the frames, and among trusted staves only those with the most lines
    are kept: a guitar neck held level can mimic a partial staff, but tab is 6 lines.
    """
    h, w = frames[0].shape[:2]
    per_frame = [detect_staves(f) for f in frames]

    def support(st: Staff) -> int:
        return sum(any(_overlaps(st, o) for o in found) for found in per_frame)

    stable = [st for found in per_frame for st in found if support(st) * 2 >= len(frames)]
    if not stable:
        return RegionGuess(Roi(0, h * 2 // 3, w, h - h * 2 // 3), 0.0)
    most = max(len(st.lines) for st in stable)
    stable = [st for st in stable if len(st.lines) == most]
    hits = sum(any(_overlaps(st, o) for st in stable for o in found) for found in per_frame)
    median = np.median(np.stack([_to_gray(f) for f in frames]), axis=0).astype(np.uint8)
    roi = trim_to_panel(median, staves_bbox(stable, w, h))
    return RegionGuess(roi, hits / len(frames))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_region.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/region.py backend/tests/test_region.py
git commit -m "feat: auto-detect tab region from staff lines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Analysis pipeline and debug CLI

**Files:**
- Create: `backend/app/pipeline.py`
- Create: `backend/app/cli.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `probe`, `sample_frames`, `grab_frames` (Task 2); `SegmentParams`, `find_segments`, `prep_gray` (Task 3); `build_pages`, `merge_adjacent`, `mark_repeats` (Task 4); `export_png`, `export_pdf` (Task 5); `has_staff_lines`, `detect_region` (Task 6).
- Produces: `AnalyzeParams(fps=5.0, diff_threshold=0.15, min_duration=0.8)`; `NoPagesFound(Exception)`; `analyze(video, roi, params=None, progress=lambda stage, frac: None) -> list[Page]`, which reports stages `"scan"` and `"compose"`, drops pages without staff lines, merges adjacent duplicates, then marks repeats. CLI: `python -m app.cli VIDEO [--roi x,y,w,h] [--out DIR] [--fps] [--diff-threshold] [--min-duration]` writes `page_NNN.png`, `tab.png` and `tab.pdf`, and prints `wrote N pages to DIR`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pipeline.py`:

```python
import pytest
from skimage.metrics import structural_similarity

from app.cli import main
from app.models import Roi
from app.pipeline import NoPagesFound, analyze
from tests.synth import EXPECTED_PAGES, ROI_TRUTH


def test_analyze_synth_video(synth_video):
    stages = set()
    pages = analyze(synth_video.path, ROI_TRUTH, progress=lambda s, f: stages.add(s))
    assert stages == {"scan", "compose"}
    assert len(pages) == len(EXPECTED_PAGES)
    for p, (name, start, end, dup) in zip(pages, EXPECTED_PAGES, strict=True):
        assert abs(p.start - start) < 0.5 and abs(p.end - end) < 0.5
        assert p.duplicate_of == dup
        ssim = structural_similarity(p.image, synth_video.panels[name], channel_axis=2)
        assert ssim > 0.95  # cursor removed, content intact


def test_analyze_without_tab_raises(synth_video):
    with pytest.raises(NoPagesFound):
        analyze(synth_video.path, Roi(0, 0, 640, 200))  # the noise area


def test_cli_writes_outputs(synth_video, tmp_path, capsys):
    main([str(synth_video.path), "--out", str(tmp_path)])
    assert "wrote 4 pages" in capsys.readouterr().out
    assert (tmp_path / "tab.png").exists() and (tmp_path / "tab.pdf").exists()
    assert len(list(tmp_path.glob("page_*.png"))) == 4
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cli'`

- [ ] **Step 3: Write the implementation**

`backend/app/pipeline.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.compose import build_pages, mark_repeats, merge_adjacent
from app.frames import probe, sample_frames
from app.models import Page, Roi
from app.region import has_staff_lines
from app.segment import SegmentParams, find_segments, prep_gray

Progress = Callable[[str, float], None]


@dataclass(frozen=True)
class AnalyzeParams:
    fps: float = 5.0
    diff_threshold: float = 0.15
    min_duration: float = 0.8


class NoPagesFound(Exception):
    pass


def analyze(
    video: Path,
    roi: Roi,
    params: AnalyzeParams | None = None,
    progress: Progress = lambda stage, frac: None,
) -> list[Page]:
    params = params or AnalyzeParams()
    total = max(1, int(probe(video).duration * params.fps))
    times, grays = [], []
    for t, img in sample_frames(video, fps=params.fps, roi=roi):
        times.append(t)
        grays.append(prep_gray(img))
        progress("scan", min(1.0, len(times) / total))
    segments = find_segments(
        times,
        grays,
        params.fps,
        SegmentParams(diff_threshold=params.diff_threshold, min_duration=params.min_duration),
    )
    pages = build_pages(
        video, roi, segments, params.fps, lambda i: progress("compose", min(1.0, i / total))
    )
    pages = [p for p in pages if has_staff_lines(p.image)]
    pages = mark_repeats(merge_adjacent(pages))
    if not pages:
        raise NoPagesFound("没有找到稳定的谱面，请检查框选区域或降低变化阈值")
    return pages
```

`backend/app/cli.py`:

```python
"""Debug entry point: python -m app.cli VIDEO [--roi x,y,w,h] [--out DIR]"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from app.export import export_pdf, export_png
from app.frames import grab_frames
from app.models import Roi
from app.pipeline import AnalyzeParams, analyze
from app.region import detect_region


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Extract stitched tab pages from a video")
    parser.add_argument("video", type=Path)
    parser.add_argument("--roi", help="x,y,w,h (default: auto-detect)")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--diff-threshold", type=float, default=0.15)
    parser.add_argument("--min-duration", type=float, default=0.8)
    args = parser.parse_args(argv)

    if args.roi:
        roi = Roi(*(int(v) for v in args.roi.split(",")))
    else:
        guess = detect_region(grab_frames(args.video, 20))
        roi = guess.roi
        print(f"auto ROI {roi.to_dict()} confidence={guess.confidence:.2f}")
    params = AnalyzeParams(args.fps, args.diff_threshold, args.min_duration)
    pages = analyze(args.video, roi, params)
    args.out.mkdir(parents=True, exist_ok=True)
    for i, page in enumerate(pages):
        cv2.imwrite(str(args.out / f"page_{i:03d}.png"), page.image)
        dup = f" (= page {page.duplicate_of})" if page.duplicate_of is not None else ""
        print(f"page {i}: {page.start:7.2f}s - {page.end:7.2f}s{dup}")
    images = [p.image for p in pages]
    export_png(images, args.out / "tab.png")
    export_pdf(images, args.out / "tab.pdf")
    print(f"wrote {len(pages)} pages to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_pipeline.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/app/cli.py backend/tests/test_pipeline.py
git commit -m "feat: add end-to-end analysis pipeline and debug CLI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Video sources: upload and yt-dlp download

**Files:**
- Create: `backend/app/source.py`
- Test: `backend/tests/test_source.py`

**Interfaces:**
- Produces: `VIDEO_EXTS`; `SourceError(Exception)`; `save_upload(fileobj, filename, dest_dir) -> Path` (saves as `source<ext>`, rejects non-video extensions); `normalize_url(text) -> str` (accepts bare `BV…` ids, bilibili.com / b23.tv / youtube.com / youtu.be incl. subdomains, adds `https://`; otherwise raises `SourceError`); `download_url(url, dest_dir, cookies_file=None, on_progress=lambda f: None) -> Path` (video-only ≤1080p, H.264 preferred, `noplaylist`, wraps `DownloadError` in `SourceError` with the cookies/upload hint).

The test marked `network` downloads a real 19-second YouTube video and is deselected by default. Run it with `uv run pytest -m network`. During prototyping it passed for YouTube. Bilibili returned HTTP 412 (risk control) or a geo-block from the prototyping network, so Bilibili is checked manually in Task 12.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_source.py`:

```python
import io

import pytest

from app import source
from app.source import SourceError, download_url, normalize_url, save_upload


@pytest.mark.parametrize(
    "text, expected",
    [
        ("BV1xx411c7mD", "https://www.bilibili.com/video/BV1xx411c7mD"),
        (
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2",
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2",
        ),
        ("b23.tv/abc123", "https://b23.tv/abc123"),
        ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
        (
            "  https://m.youtube.com/watch?v=dQw4w9WgXcQ ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
    ],
)
def test_normalize_url_accepts(text, expected):
    assert normalize_url(text) == expected


@pytest.mark.parametrize("text", ["https://example.com/v", "https://notyoutube.com/x", "hello"])
def test_normalize_url_rejects(text):
    with pytest.raises(SourceError):
        normalize_url(text)


def test_save_upload(tmp_path):
    path = save_upload(io.BytesIO(b"data"), "My Video.MKV", tmp_path)
    assert path == tmp_path / "source.mkv" and path.read_bytes() == b"data"
    with pytest.raises(SourceError):
        save_upload(io.BytesIO(b"x"), "notes.txt", tmp_path)


class FakeYDL:
    last_opts: dict = {}

    def __init__(self, opts):
        FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        for hook in self.last_opts["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        out = self.last_opts["outtmpl"].replace("%(ext)s", "mp4")
        open(out, "wb").write(b"video")
        return {"ext": "mp4"}

    def prepare_filename(self, info):
        return self.last_opts["outtmpl"].replace("%(ext)s", info["ext"])


def test_download_url_uses_video_only_format(tmp_path, monkeypatch):
    monkeypatch.setattr(source.yt_dlp, "YoutubeDL", FakeYDL)
    seen = []
    path = download_url("https://youtu.be/x", tmp_path, tmp_path / "c.txt", seen.append)
    assert path == tmp_path / "source.mp4"
    assert seen == [0.5]
    assert FakeYDL.last_opts["noplaylist"] is True
    assert FakeYDL.last_opts["cookiefile"] == str(tmp_path / "c.txt")
    assert FakeYDL.last_opts["format"].startswith("bv*[height<=1080]")


def test_download_url_wraps_errors(tmp_path, monkeypatch):
    class Boom(FakeYDL):
        def extract_info(self, url, download):
            raise source.yt_dlp.utils.DownloadError("geo blocked")

    monkeypatch.setattr(source.yt_dlp, "YoutubeDL", Boom)
    with pytest.raises(SourceError, match="geo blocked"):
        download_url("https://youtu.be/x", tmp_path)


@pytest.mark.network
def test_download_real_youtube(tmp_path):
    # "Me at the zoo", 19 seconds; run with: pytest -m network
    path = download_url("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)
    assert path.stat().st_size > 0
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.source'`

- [ ] **Step 3: Write the implementation**

`backend/app/source.py`:

```python
from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import yt_dlp

VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".flv",
    ".m4v",
    ".ts",
    ".wmv",
    ".mpg",
    ".mpeg",
}
ALLOWED_HOSTS = ("bilibili.com", "b23.tv", "youtube.com", "youtu.be")
BV_RE = re.compile(r"^(BV[0-9A-Za-z]{10})$")
# Video-only stream: no merge step, so no system ffmpeg is needed. Prefer H.264.
FORMAT = "bv*[height<=1080][vcodec^=avc]/bv*[height<=1080]/b[height<=1080]/bv*/b"


class SourceError(Exception):
    pass


def save_upload(fileobj: BinaryIO, filename: str, dest_dir: Path) -> Path:
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise SourceError(f"不支持的文件类型：{ext or '无扩展名'}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"source{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(fileobj, out)
    return dest


def normalize_url(text: str) -> str:
    text = text.strip()
    if m := BV_RE.match(text):
        return f"https://www.bilibili.com/video/{m.group(1)}"
    if not re.match(r"^https?://", text):
        text = "https://" + text
    host = re.sub(r"^https?://", "", text).split("/")[0].split(":")[0].lower()
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise SourceError("只支持 bilibili / YouTube 链接或 BV 号")
    return text


def download_url(
    url: str,
    dest_dir: Path,
    cookies_file: Path | None = None,
    on_progress: Callable[[float], None] = lambda f: None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "format": FORMAT,
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as exc:
        raise SourceError(f"下载失败：{exc}（可尝试配置 cookies 或直接上传视频文件）") from exc
    if not path.exists():
        raise SourceError("下载完成但找不到视频文件")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_source.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/source.py backend/tests/test_source.py
git commit -m "feat: accept uploads and bilibili/YouTube links via yt-dlp

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: Jobs, workflow and HTTP API

**Files:**
- Create: `backend/app/jobs.py`
- Create: `backend/app/workflow.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces (`jobs.py`): `Status` StrEnum with the values `downloading`, `ready_for_region`, `analyzing`, `ready_for_review`, `failed`. `Job` dataclass with fields `id, dir, status, stage, progress, error, video, width, height, duration, region, pages`, plus `.to_dict()`. `JobStore(root)` with `.create()`, `.get(id)`, `.save(job)`, `.update(job, **changes)` and `.run(job, fn) -> Thread`; `run` marks the job failed with `str(exc)` if `fn` raises.
- Produces (`workflow.py`): `prepare(store, job, url=None)`, which downloads if needed, probes, saves `frame.jpg` and the region guess, and sets the status to ready_for_region. `run_analysis(store, job, roi, params)` writes `pages/NNN.png` and `job.pages = [{id, file, start, end, duplicate_of}]`. `export(job, order, fmt) -> "tab.png" | "tab.pdf"`, which raises `ValueError` when nothing is selected.
- Produces (`main.py`): `create_app(data_dir=None) -> FastAPI` (default data dir `$VTT_DATA_DIR` or `<repo>/data/jobs`); `safe_path(root, name) -> Path | None`; module-level `app`. Routes:
  - `POST /api/jobs` — multipart: exactly one of `file` or `url`; 400 on bad input.
  - `GET /api/jobs/{id}`
  - `PUT /api/jobs/{id}/region` — body `{x, y, w, h, fps?, diff_threshold?, min_duration?}`; 409 while busy.
  - `POST /api/jobs/{id}/export` — body `{order: [page ids], fmt: "png" | "pdf"}`; returns `{url}`.
  - `GET /api/jobs/{id}/frame?t=` — JPEG.
  - `GET /api/jobs/{id}/files/{name}` — path-traversal safe.
  - `/` serves `frontend/dist` when it has been built.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py`:

```python
import time

from fastapi.testclient import TestClient

from app.main import create_app, safe_path


def wait_for(client, job_id, status, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        assert job["status"] != "failed", job["error"]
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {status}: {job}")


def test_full_flow(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    with synth_video.path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("x.avi", f, "video/x-msvideo")})
    assert r.status_code == 200, r.text
    job = wait_for(client, r.json()["id"], "ready_for_region")
    assert job["region"]["confidence"] > 0.7
    assert client.get(f"/api/jobs/{job['id']}/files/frame.jpg").status_code == 200

    r = client.put(f"/api/jobs/{job['id']}/region", json=job["region"]["roi"])
    assert r.status_code == 200, r.text
    job = wait_for(client, job["id"], "ready_for_review")
    assert [p["duplicate_of"] for p in job["pages"]] == [None, None, None, 0]

    r = client.post(f"/api/jobs/{job['id']}/export", json={"order": [2, 0], "fmt": "pdf"})
    assert r.status_code == 200, r.text
    pdf = client.get(r.json()["url"])
    assert pdf.content.startswith(b"%PDF")


def test_rejects_bad_input(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/api/jobs").status_code == 400
    r = client.post("/api/jobs", data={"url": "https://example.com/v"})
    assert r.status_code == 400
    r = client.post("/api/jobs", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 400
    assert client.get("/api/jobs/nope").status_code == 404


def test_safe_path(tmp_path):
    (tmp_path / "job").mkdir()
    (tmp_path / "job" / "a.png").write_bytes(b"x")
    (tmp_path / "secret").write_bytes(b"x")
    assert safe_path(tmp_path / "job", "a.png") == (tmp_path / "job" / "a.png").resolve()
    assert safe_path(tmp_path / "job", "../secret") is None
    assert safe_path(tmp_path / "job", "missing.png") is None
```
- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write the implementation**

`backend/app/jobs.py`:

```python
from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


class Status(StrEnum):
    DOWNLOADING = "downloading"
    READY_FOR_REGION = "ready_for_region"
    ANALYZING = "analyzing"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    dir: Path
    status: Status = Status.DOWNLOADING
    stage: str = ""
    progress: float = 0.0
    error: str | None = None
    video: str | None = None  # file name inside dir
    width: int = 0
    height: int = 0
    duration: float = 0.0
    region: dict | None = None  # {"roi": {...}, "confidence": float}
    pages: list[dict] = field(default_factory=list)
    # page dict: {"id", "file", "start", "end", "duplicate_of"}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dir"] = str(self.dir)
        return d


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, dir=self.root / job_id)
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        self.save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def save(self, job: Job) -> None:
        (job.dir / "state.json").write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))

    def update(self, job: Job, **changes) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        self.save(job)

    def run(self, job: Job, fn: Callable[[], None]) -> threading.Thread:
        """Run fn in a daemon thread; any exception marks the job failed."""

        def target() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
                self.update(job, status=Status.FAILED, error=str(exc))

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread
```

`backend/app/workflow.py`:

```python
"""Job-level steps glued to the pipeline; each runs inside JobStore.run()."""

from __future__ import annotations

import os
from pathlib import Path

import cv2

from app.export import export_pdf, export_png
from app.frames import grab_frames, probe
from app.jobs import Job, JobStore, Status
from app.models import Roi
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
    meta = []
    for i, page in enumerate(pages):
        name = f"pages/{i:03d}.png"
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


def export(job: Job, order: list[int], fmt: str) -> str:
    by_id = {p["id"]: p for p in job.pages}
    images = [cv2.imread(str(job.dir / by_id[i]["file"])) for i in order if i in by_id]
    if not images:
        raise ValueError("没有选中任何页面")
    name = f"tab.{fmt}"
    (export_png if fmt == "png" else export_pdf)(images, job.dir / name)
    return name
```

`backend/app/main.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import workflow
from app.frames import frame_at
from app.jobs import Job, JobStore, Status
from app.models import Roi
from app.pipeline import AnalyzeParams
from app.source import SourceError, normalize_url, save_upload

REPO_ROOT = Path(__file__).resolve().parents[2]


def safe_path(root: Path, name: str) -> Path | None:
    path = (root / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


class RegionIn(BaseModel):
    x: int
    y: int
    w: int
    h: int
    fps: float = 5.0
    diff_threshold: float = 0.15
    min_duration: float = 0.8


class ExportIn(BaseModel):
    order: list[int]
    fmt: Literal["png", "pdf"]


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = data_dir or Path(os.environ.get("VTT_DATA_DIR", REPO_ROOT / "data" / "jobs"))
    store = JobStore(data_dir)
    app = FastAPI(title="video-to-tab")
    app.state.store = store

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
            job = store.create()
            if file is not None:
                path = save_upload(file.file, file.filename or "", job.dir)
                store.update(job, video=path.name)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.run(job, lambda: workflow.prepare(store, job, clean_url))
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict:
        return get_job(job_id).to_dict()

    @app.put("/api/jobs/{job_id}/region")
    def set_region(job_id: str, body: RegionIn) -> dict:
        job = get_job(job_id)
        if job.status not in (Status.READY_FOR_REGION, Status.READY_FOR_REVIEW, Status.FAILED):
            raise HTTPException(409, f"当前状态不能开始分析：{job.status}")
        if not job.video:
            raise HTTPException(409, "视频尚未就绪")
        roi = Roi(body.x, body.y, body.w, body.h)
        params = AnalyzeParams(body.fps, body.diff_threshold, body.min_duration)
        store.update(job, status=Status.ANALYZING, error=None)
        store.run(job, lambda: workflow.run_analysis(store, job, roi, params))
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/export")
    def export(job_id: str, body: ExportIn) -> dict:
        job = get_job(job_id)
        try:
            name = workflow.export(job, body.order, body.fmt)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"url": f"/api/jobs/{job_id}/files/{name}"}

    @app.get("/api/jobs/{job_id}/frame")
    def frame(job_id: str, t: float = 0.0) -> Response:
        job = get_job(job_id)
        if not job.video:
            raise HTTPException(409, "视频尚未就绪")
        ok, buf = cv2.imencode(".jpg", frame_at(job.dir / job.video, t))
        return Response(buf.tobytes(), media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/files/{name:path}")
    def files(job_id: str, name: str) -> FileResponse:
        job = get_job(job_id)
        path = safe_path(job.dir, name)
        if path is None:
            raise HTTPException(404, "文件不存在")
        return FileResponse(path)

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: all PASS.
Then: `cd backend && uv run ruff check app tests && uv run ruff format --check app tests` → no findings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs.py backend/app/workflow.py backend/app/main.py backend/tests/test_api.py
git commit -m "feat: add background jobs and REST API

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Frontend scaffold and pure helpers

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/src/lib/roi.js`, `frontend/src/lib/pages.js`
- Test: `frontend/src/lib/roi.test.js`, `frontend/src/lib/pages.test.js`

**Interfaces:**
- Produces: `normalizeRect(x0, y0, x1, y1) -> {x,y,w,h}`, `displayToVideo(rect, scale)`, `videoToDisplay(roi, scale)` (`scale` = video px per display px), `clampRoi(roi, width, height)`; `moveItem(list, from, to) -> new list`, `formatTime(seconds) -> "m:ss.s"`.

- [ ] **Step 1: Create `frontend/package.json` and `frontend/vite.config.js`, install**

`frontend/package.json`:

```json
{
  "name": "video-to-tab-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run"
  }
}
```

Run: `cd frontend && npm install vue@^3.5 && npm install -D vite@^7 @vitejs/plugin-vue@^6 vitest@^3`
Expected: `package.json` gains `dependencies.vue` and the three devDependencies; `package-lock.json` created.

`frontend/vite.config.js` (dev server proxies `/api` to the backend on port 8000):

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'node' },
})
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/roi.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { clampRoi, displayToVideo, normalizeRect, videoToDisplay } from './roi.js'

describe('roi helpers', () => {
  it('normalizes a rectangle dragged in any direction', () => {
    expect(normalizeRect(50, 40, 10, 20)).toEqual({ x: 10, y: 20, w: 40, h: 20 })
  })

  it('round-trips between display and video coordinates', () => {
    const roi = { x: 100, y: 800, w: 1700, h: 260 }
    const scale = 1920 / 960
    expect(videoToDisplay(roi, scale)).toEqual({ x: 50, y: 400, w: 850, h: 130 })
    expect(displayToVideo(videoToDisplay(roi, scale), scale)).toEqual(roi)
  })

  it('clamps to the frame', () => {
    expect(clampRoi({ x: -5, y: 1000, w: 3000, h: 200 }, 1920, 1080)).toEqual({
      x: 0,
      y: 1000,
      w: 1920,
      h: 80,
    })
  })
})
```

`frontend/src/lib/pages.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { formatTime, moveItem } from './pages.js'

describe('page helpers', () => {
  it('moves an item without mutating the input', () => {
    const list = [0, 1, 2, 3]
    expect(moveItem(list, 3, 1)).toEqual([0, 3, 1, 2])
    expect(list).toEqual([0, 1, 2, 3])
  })

  it('formats seconds as m:ss.s', () => {
    expect(formatTime(65.25)).toBe('1:05.3')
    expect(formatTime(3)).toBe('0:03.0')
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — `Failed to resolve import "./roi.js"` (and `./pages.js`).

- [ ] **Step 4: Write the helpers**

`frontend/src/lib/roi.js`:

```js
// Convert between on-screen (display) pixels and video pixels for the region editor.

export function normalizeRect(x0, y0, x1, y1) {
  return { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }
}

export function displayToVideo(rect, scale) {
  return {
    x: Math.round(rect.x * scale),
    y: Math.round(rect.y * scale),
    w: Math.round(rect.w * scale),
    h: Math.round(rect.h * scale),
  }
}

export function videoToDisplay(roi, scale) {
  return { x: roi.x / scale, y: roi.y / scale, w: roi.w / scale, h: roi.h / scale }
}

export function clampRoi(roi, width, height) {
  const x = Math.min(Math.max(0, roi.x), width - 1)
  const y = Math.min(Math.max(0, roi.y), height - 1)
  return {
    x,
    y,
    w: Math.max(1, Math.min(roi.w, width - x)),
    h: Math.max(1, Math.min(roi.h, height - y)),
  }
}
```

`frontend/src/lib/pages.js`:

```js
// Pure helpers for the review list (kept out of the component so they are testable).

export function moveItem(list, from, to) {
  const copy = list.slice()
  const [item] = copy.splice(from, 1)
  copy.splice(to, 0, item)
  return copy
}

export function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = (seconds % 60).toFixed(1).padStart(4, '0')
  return `${m}:${s}`
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: 2 files, 5 tests passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/src/lib
git commit -m "feat: scaffold Vue frontend with ROI and page helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Frontend views (input → region → review/export)

**Files:**
- Create: `frontend/index.html`, `frontend/src/main.js`, `frontend/src/style.css`, `frontend/src/api.js`, `frontend/src/App.vue`, `frontend/src/views/InputView.vue`, `frontend/src/views/RegionEditor.vue`, `frontend/src/views/ReviewView.vue`

**Interfaces:**
- Consumes: the REST API (Task 9) and the helpers (Task 10).
- Produces: `api` object — `createFromFile(file)`, `createFromUrl(url)`, `getJob(id)`, `setRegion(id, region)`, `exportPages(id, order, fmt)`, `fileUrl(id, name)`, `frameUrl(id, t)`. Errors throw `Error(detail)`.
- `App.vue` state machine, keyed on `job.status`:
  - no job → `InputView`
  - `downloading` / `analyzing` → progress bar, polling every 800 ms
  - `ready_for_region` → `RegionEditor`
  - `ready_for_review` → `ReviewView`
  - `failed` → error text, plus "调整区域重试" (only when a region exists) and "重新开始"

These are UI components with no unit tests; they are verified by building and by the manual run in Task 12.

- [ ] **Step 1: Write the files**

`frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Video to Tab</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

`frontend/src/main.js`:

```js
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

`frontend/src/style.css`:

```css
:root { font-family: system-ui, sans-serif; color: #222; background: #f6f6f4; }
body { margin: 0; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 22px; margin: 0 0 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 16px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
button { padding: 6px 14px; border-radius: 6px; border: 1px solid #bbb; background: #fff; cursor: pointer; }
button.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
button:disabled { opacity: .5; cursor: default; }
input[type=text], input[type=number] { padding: 6px 8px; border: 1px solid #bbb; border-radius: 6px; }
.error { color: #b91c1c; white-space: pre-wrap; }
.warn { background: #fef3c7; padding: 8px 12px; border-radius: 6px; }
progress { width: 100%; }
```

`frontend/src/api.js`:

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
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`)
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
  getJob: (id) => request('GET', `/api/jobs/${id}`),
  setRegion: (id, region) => request('PUT', `/api/jobs/${id}/region`, region),
  exportPages: (id, order, fmt) => request('POST', `/api/jobs/${id}/export`, { order, fmt }),
  fileUrl: (id, name) => `/api/jobs/${id}/files/${name}`,
  frameUrl: (id, t) => `/api/jobs/${id}/frame?t=${t}`,
}
```

`frontend/src/App.vue`:

```vue
<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { api } from './api.js'
import InputView from './views/InputView.vue'
import RegionEditor from './views/RegionEditor.vue'
import ReviewView from './views/ReviewView.vue'

const job = ref(null)
const STAGES = { download: '下载视频', probe: '检测谱面区域', scan: '扫描换页', compose: '合成页面' }
let timer = null

function track(next) {
  job.value = next
  clearTimeout(timer)
  if (next.status === 'downloading' || next.status === 'analyzing') {
    timer = setTimeout(async () => track(await api.getJob(next.id)), 800)
  }
}

function restart() {
  clearTimeout(timer)
  job.value = null
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <main>
    <h1>Video → Tab</h1>
    <InputView v-if="!job" @created="track" />
    <template v-else>
      <div v-if="job.status === 'downloading' || job.status === 'analyzing'" class="card">
        <p>{{ STAGES[job.stage] || '处理中' }}…</p>
        <progress :value="job.progress" max="1" />
      </div>
      <div v-else-if="job.status === 'failed'" class="card">
        <p class="error">{{ job.error }}</p>
        <div class="row">
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
      />
    </template>
  </main>
</template>
```

`frontend/src/views/InputView.vue`:

```vue
<script setup>
import { ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['created'])
const url = ref('')
const error = ref('')
const busy = ref(false)

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
</template>
```

`frontend/src/views/RegionEditor.vue`:

```vue
<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'
import { clampRoi, displayToVideo, normalizeRect, videoToDisplay } from '../lib/roi.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['started'])

const roi = reactive({ ...props.job.region.roi })
const params = reactive({ fps: 5, diff_threshold: 0.15, min_duration: 0.8 })
const img = ref(null)
const scale = ref(1) // video px per display px
const drag = ref(null)
const error = ref('')
const lowConfidence = computed(() => props.job.region.confidence < 0.5)

const box = computed(() => {
  const r = drag.value ? drag.value.rect : videoToDisplay(roi, scale.value)
  return { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` }
})

function onLoad() {
  scale.value = props.job.width / img.value.clientWidth
}

function point(event) {
  const rect = img.value.getBoundingClientRect()
  return [event.clientX - rect.left, event.clientY - rect.top]
}

function onDown(event) {
  const [x, y] = point(event)
  drag.value = { x0: x, y0: y, rect: { x, y, w: 0, h: 0 } }
}

function onMove(event) {
  if (!drag.value) return
  const [x, y] = point(event)
  drag.value.rect = normalizeRect(drag.value.x0, drag.value.y0, x, y)
}

function onUp() {
  if (!drag.value) return
  const r = drag.value.rect
  drag.value = null
  if (r.w < 5 || r.h < 5) return
  Object.assign(roi, clampRoi(displayToVideo(r, scale.value), props.job.width, props.job.height))
}

async function start() {
  error.value = ''
  try {
    emit('started', await api.setRegion(props.job.id, { ...roi, ...params }))
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="card">
    <h2>2. 确认谱面区域</h2>
    <p v-if="lowConfidence" class="warn">没能可靠地自动找到谱面，请在图上拖拽框选 tab 区域。</p>
    <p v-else>已自动框出谱面区域（蓝框），如不准确可在图上重新拖拽框选。</p>
    <div class="stage" @mousedown.prevent="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp">
      <img ref="img" :src="api.fileUrl(job.id, 'frame.jpg')" draggable="false" @load="onLoad" />
      <div class="roi" :style="box" />
    </div>
    <div class="row">
      <label>x <input v-model.number="roi.x" type="number" /></label>
      <label>y <input v-model.number="roi.y" type="number" /></label>
      <label>宽 <input v-model.number="roi.w" type="number" /></label>
      <label>高 <input v-model.number="roi.h" type="number" /></label>
    </div>
    <details>
      <summary>高级参数</summary>
      <div class="row">
        <label>采样 fps <input v-model.number="params.fps" type="number" step="1" min="1" /></label>
        <label>换页阈值 <input v-model.number="params.diff_threshold" type="number" step="0.01" /></label>
        <label>最短页时长(秒) <input v-model.number="params.min_duration" type="number" step="0.1" /></label>
      </div>
    </details>
    <p><button class="primary" @click="start">开始识别</button></p>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.stage { position: relative; display: inline-block; cursor: crosshair; user-select: none; max-width: 100%; }
.stage img { display: block; max-width: 100%; }
.roi { position: absolute; border: 2px solid #2563eb; background: rgba(37, 99, 235, 0.12); pointer-events: none; }
label input { width: 80px; }
</style>
```

`frontend/src/views/ReviewView.vue`:

```vue
<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import { formatTime, moveItem } from '../lib/pages.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['back', 'restart'])

const pages = ref(props.job.pages.slice())
const dragFrom = ref(null)
const links = ref({})
const error = ref('')

function remove(index) {
  pages.value = pages.value.filter((_, i) => i !== index)
}

function onDrop(index) {
  if (dragFrom.value !== null) pages.value = moveItem(pages.value, dragFrom.value, index)
  dragFrom.value = null
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
    <p>拖动调整顺序，点 × 删除多余页面。标记“重复”的页面与前面某页内容相同（例如副歌重现）。</p>
    <div class="row">
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
    @dragstart="dragFrom = i"
    @dragover.prevent
    @drop="onDrop(i)"
  >
    <div class="row meta">
      <strong>#{{ i + 1 }}</strong>
      <a :href="api.frameUrl(job.id, page.start)" target="_blank">
        {{ formatTime(page.start) }} – {{ formatTime(page.end) }}
      </a>
      <span v-if="page.duplicate_of !== null" class="dup">重复：同第 {{ page.duplicate_of + 1 }} 段</span>
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

- [ ] **Step 2: Build**

Run: `cd frontend && npm run build && npm test`
Expected: `✓ built`, with `dist/index.html` plus one JS bundle (~75 kB) and one CSS bundle; 5 tests still pass.

- [ ] **Step 3: Smoke-check that the backend serves the build**

Run: `cd backend && (uv run uvicorn app.main:app --port 8000 &) && sleep 2 && curl -s http://127.0.0.1:8000/ | head -3; pkill -f 'uvicorn app.main:app'`
Expected: the first lines of `<!doctype html>` with `<html lang="zh-CN">`.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/src
git commit -m "feat: add input, region editor and review views

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: README and end-to-end verification on real videos

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# video-to-tab

把吉他演奏视频下方逐页切换的 tab 谱提取出来，去掉播放光标，拼接成完整的长图 / PDF。

## 安装

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node 20+。

    cd backend && uv sync
    cd ../frontend && npm install && npm run build

不需要系统 ffmpeg：PyAV 自带解码库，yt-dlp 只下载无需合并的视频流。

## 使用

    cd backend && uv run uvicorn app.main:app --port 8000

浏览器打开 http://127.0.0.1:8000 ：上传视频或粘贴 bilibili / YouTube 链接 → 确认谱面区域 → 校对页面 → 导出 PNG / PDF。

- B 站需要登录或受地区限制时：导出浏览器 cookies（Netscape 格式）并设置 `VTT_COOKIES_FILE=/path/cookies.txt` 后启动。
- 数据目录默认 `data/jobs/`，可用 `VTT_DATA_DIR` 修改。
- 高级参数（识别页面里的“高级参数”）：采样 fps、换页阈值（默认 0.15，漏检换页时调低）、最短页时长。

## 开发

    cd backend && uv run pytest            # 单元 + API 测试（-m network 运行联网下载测试）
    cd backend && uv run python -m app.cli video.mp4 --out out/   # 命令行调试
    cd backend && uv run uvicorn app.main:app --reload --port 8000
    cd frontend && npm run dev             # http://localhost:5173，/api 代理到 8000
    cd frontend && npm test
```
- [ ] **Step 2: Run the full automated suite**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests && cd ../frontend && npm test`
Expected: 43 passed, 1 deselected; lint clean; 5 frontend tests passed.

- [ ] **Step 3: CLI on real videos (same ones used in prototyping)**

Run:
```bash
cd backend
uv run python -c "from pathlib import Path; from app.source import download_url; print(download_url('https://www.youtube.com/watch?v=2Ed7UsJd3Es', Path('/tmp/vtt/a')))"
uv run python -m app.cli /tmp/vtt/a/source.mp4 --out /tmp/vtt/a/out
uv run python -c "from pathlib import Path; from app.source import download_url; print(download_url('https://www.youtube.com/watch?v=U2m8IatzpAM', Path('/tmp/vtt/b')))"
uv run python -m app.cli /tmp/vtt/b/source.mp4 --out /tmp/vtt/b/out
```
Expected (from the prototype run):
- **Video a:** `auto ROI {'x': 62, 'y': 802, 'w': 1798, 'h': 256} confidence=0.95` and `wrote 16 pages`. Open `tab.png`: measures 1–18 should run on continuously with no repeated page, no red or blue cursor, and no strip of video above the panel.
- **Video b:** confidence ≈0.95, with the ROI ending before the chord diagram on the right (x+w ≈ 1684). It should write about 23 pages. This video scrolls the tab step by step, so adjacent pages overlap by about one measure. That is expected (see "Follow-ups" below).

Both runs should take about 10 s each on a modern CPU.

- [ ] **Step 4: Manual UI walkthrough**

Run: `cd backend && uv run uvicorn app.main:app --port 8000`, open http://127.0.0.1:8000 and check:
1. **Upload:** upload `/tmp/vtt/a/source.mp4`. The progress bar is followed by the region editor, and the blue box covers the tab panel.
2. **Region editing:** drag a new box. The x/y/宽/高 inputs update; restore the box by editing the numbers.
3. **Analysis:** click "开始识别". The progress bar is followed by the review page with 16 pages.
4. **Review:** drag page 3 above page 1, and delete a page with ×. Click a time link: it opens the original frame at that time.
5. **Export:** "导出 PDF" and then "打开 PDF" shows A4 pages. "导出长图 PNG" and then "打开 PNG" shows the stitched image in the new order.
6. **Bad link:** paste `https://example.com/x`. The error "只支持 bilibili / YouTube 链接或 BV 号" appears.
7. **YouTube link:** paste `https://youtu.be/2Ed7UsJd3Es`. It downloads with a progress bar, then shows the region editor.
8. **Bilibili link:** paste a bilibili link to a guitar video with tabs, e.g. search "指弹 吉他谱 TAB". Either it downloads and processes, or the yt-dlp error appears verbatim with the cookies hint. If it fails with 412 or a login prompt, set `VTT_COOKIES_FILE` and retry.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Follow-ups (out of scope for this plan)

- **Overlap trimming for step-scrolling tabs, as in video b.** Detect horizontal overlap between consecutive pages (for example by aligning bar-line x positions) and crop the repeated measures.
- **Highlight removal.** A static highlight on the current measure (Songsterr-style yellow box) survives the median because it doesn't move within a page.
- Symbol OCR / ASCII / Guitar Pro export, continuous horizontal scrolling, multi-user deployment.
