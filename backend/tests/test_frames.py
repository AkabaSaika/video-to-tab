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
    assert ROI_TRUTH.crop(frames[0]).min() > 150  # t=0: blank panel (intro)
    assert ROI_TRUTH.crop(frames[-1]).min() < 100  # near the end: a tab page with ink


def test_frame_at_matches_sequential_decode(synth_video):
    expected = [img for t, img in sample_frames(synth_video.path, fps=25) if abs(t - 5.0) < 1e-3]
    assert np.array_equal(frame_at(synth_video.path, 5.0), expected[0])


def test_decode_error_for_non_video(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(DecodeError):
        probe(bad)
