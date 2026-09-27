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
