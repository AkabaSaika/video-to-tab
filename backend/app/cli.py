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
