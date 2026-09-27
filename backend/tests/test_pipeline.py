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
