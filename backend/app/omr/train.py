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
