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
