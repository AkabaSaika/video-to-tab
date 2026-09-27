from __future__ import annotations

import math
from pathlib import Path

import cv2
import img2pdf
import numpy as np

GAP = 24
A4_RATIO = math.sqrt(2)  # height / width


def _max_width(images: list[np.ndarray]) -> int:
    if not images:
        raise ValueError("没有可导出的页面")
    return max(i.shape[1] for i in images)


def _pad_width(img: np.ndarray, width: int) -> np.ndarray:
    if img.shape[1] == width:
        return img
    pad = np.full((img.shape[0], width - img.shape[1], 3), 255, np.uint8)
    return np.hstack([img, pad])


def stitch_vertical(images: list[np.ndarray], gap: int = GAP) -> np.ndarray:
    width = _max_width(images)
    parts: list[np.ndarray] = []
    for i, img in enumerate(images):
        if i:
            parts.append(np.full((gap, width, 3), 255, np.uint8))
        parts.append(_pad_width(img, width))
    return np.vstack(parts)


def export_png(images: list[np.ndarray], out: Path) -> Path:
    if not cv2.imwrite(str(out), stitch_vertical(images)):
        raise OSError(f"无法写入文件：{out}")
    return out


def paginate(images: list[np.ndarray], gap: int = GAP) -> list[np.ndarray]:
    """Pack images top-to-bottom into A4-proportioned sheets without splitting an image."""
    width = _max_width(images)
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
        if not ok:
            raise ValueError("页面图像编码失败")
        blobs.append(buf.tobytes())
    layout = img2pdf.get_layout_fun((img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)))
    out.write_bytes(img2pdf.convert(blobs, layout_fun=layout))
    return out
