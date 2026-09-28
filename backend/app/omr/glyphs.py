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
