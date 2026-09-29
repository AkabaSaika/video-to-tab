"""homr (AGPL-3.0) wrapped for the app: one grand-staff system image in, MusicXML out.

The three ONNX models (~160 MB) live in a model directory, not inside the homr package:
VTT_HOMR_MODELS if set, else `homr_models` next to the frozen app (bundled by
packaging/build.py), else data/models/homr in the repository. Missing models are downloaded
once from homr's release page (`python -m app.piano.engine --download`).

homr's title OCR (rapidocr) is not installed; its module is replaced by a stub that finds no
title. Models are loaded on first use and reused; recognition is serialized by a lock because
homr keeps its models in module globals.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import threading
import types
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

import cv2
import numpy as np

SEGNET = "segnet_308-3296ccd40960f90ca6ab9c035cca945675d30a0f.onnx"
ENCODER = "encoder_pytorch_model_396-f6feedb42ff90087d898b0941a55d040fa6b2903.onnx"
DECODER = "decoder_pytorch_model_396-f6feedb42ff90087d898b0941a55d040fa6b2903.onnx"
MODEL_FILES = [SEGNET, ENCODER, DECODER]
DOWNLOAD_BASE = "https://github.com/liebharc/homr/releases/download/onnx_checkpoints/"


class EngineError(ValueError):
    """Recognition failed; the message is shown to the user."""


def model_dir() -> Path:
    env = os.environ.get("VTT_HOMR_MODELS")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "homr_models"
    return Path(__file__).resolve().parents[3] / "data" / "models" / "homr"


def models_available(directory: Path | None = None) -> bool:
    directory = directory or model_dir()
    return all((directory / name).is_file() for name in MODEL_FILES)


def download_model(name: str, dest: Path) -> None:
    """Fetch one model the way homr does (<release>/<name without .onnx>.zip) into dest."""
    from homr import download_utils

    stem = name.removesuffix(".onnx")
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        archive = os.path.join(tmp, stem + ".zip")
        download_utils.download_file(DOWNLOAD_BASE + stem + ".zip", archive)
        download_utils.unzip_file(archive, tmp)
        found = next(Path(tmp).rglob(name), None)
        if found is None:
            raise OSError(f"{stem}.zip does not contain {name}")
        shutil.move(str(found), dest / name)


def ensure_models(
    directory: Path | None = None, fetch: Callable[[str, Path], None] = download_model
) -> Path:
    """Make sure every model file is in `directory`, downloading the missing ones."""
    directory = directory or model_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        if (directory / name).is_file():
            continue
        try:
            fetch(name, directory)
        except Exception as exc:  # noqa: BLE001 - any network/unzip error
            raise EngineError(f"钢琴谱识别模型下载失败（{name}）：{exc}") from exc
    return directory


def _stub_title_detection() -> None:
    """homr.main imports homr.title_detection, which needs rapidocr; we never read titles."""
    stub = types.ModuleType("homr.title_detection")

    def detect_title(debug, top_staff) -> Future:  # noqa: ANN001 - homr's signature
        done: Future = Future()
        done.set_result("")
        return done

    stub.detect_title = detect_title  # type: ignore[attr-defined]
    stub.download_ocr_weights = lambda: None  # type: ignore[attr-defined]
    sys.modules["homr.title_detection"] = stub


class _Homr:
    """homr's pipeline (homr.main.process_image without title OCR and file output)."""

    def __init__(self, directory: Path) -> None:
        _stub_title_detection()
        from homr import main as homr_main
        from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
        from homr.segmentation import inference_segnet
        from homr.staff_parsing import parse_staffs
        from homr.transformer.configs import Config

        inference_segnet.segnet_path_onnx = str(directory / SEGNET)
        segnet = inference_segnet.Segnet(False)  # load once; homr builds one per image
        inference_segnet.Segnet = lambda use_gpu_inference: segnet
        self.main = homr_main
        self.parse_staffs = parse_staffs
        self.generate_xml = generate_xml
        self.xml_args = XmlGeneratorArguments(False, None, None)
        self.config = Config()
        self.config.filepaths.encoder_path = str(directory / ENCODER)
        self.config.filepaths.decoder_path = str(directory / DECODER)
        self.config.use_gpu_inference = False
        self.processing = homr_main.ProcessingConfig(
            enable_debug=False,
            enable_cache=False,
            write_staff_positions=False,
            read_staff_positions=False,
            selected_staff=-1,
            transformer_use_gpu=False,
            segnet_use_gpu=False,
            coreml_encoder=False,
        )

    def run(self, image: np.ndarray) -> str:
        with tempfile.TemporaryDirectory(prefix="vtt-piano-") as tmp:
            path = os.path.join(tmp, "system.png")
            if not cv2.imwrite(path, image):
                raise EngineError("谱表图像无法写入临时文件")
            try:
                staffs, preprocessed, debug, _title = self.main.detect_staffs_in_image(
                    path, self.processing
                )
                result = self.parse_staffs(
                    debug, staffs, preprocessed, selected_staff=-1, config=self.config
                )
            except Exception as exc:  # noqa: BLE001 - homr raises bare Exception
                raise EngineError(f"没有识别出乐谱：{exc}") from exc
            if not result or not any(result):
                raise EngineError("没有识别出乐谱")
            out = os.path.join(tmp, "system.musicxml")
            self.generate_xml(self.xml_args, result, "").write(out)
            return Path(out).read_text(encoding="utf-8")


_lock = threading.Lock()
_homr: _Homr | None = None


def recognize(image: np.ndarray) -> str:
    """MusicXML (one piano part, two staves) of one grand-staff system image (BGR)."""
    global _homr
    with _lock:
        if _homr is None:
            _homr = _Homr(ensure_models())
        return _homr.run(image)


def main() -> None:
    parser = argparse.ArgumentParser(description="homr piano recognition models")
    parser.add_argument("--download", action="store_true", help="fetch missing models")
    parser.add_argument("--dir", type=Path, default=None, help="model directory")
    parser.add_argument("image", nargs="?", type=Path, help="recognize this image")
    args = parser.parse_args()
    if args.dir:
        os.environ["VTT_HOMR_MODELS"] = str(args.dir)
    if args.download:
        print(ensure_models())
    if args.image:
        img = cv2.imread(str(args.image))
        if img is None:
            sys.exit(f"cannot read {args.image}")
        print(recognize(img))


if __name__ == "__main__":
    main()
