import re

import numpy as np
import pytest

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


def test_empty_input_raises_chinese_error(tmp_path):
    for fn in (stitch_vertical, paginate):
        with pytest.raises(ValueError, match="没有可导出的页面"):
            fn([])
    with pytest.raises(ValueError, match="没有可导出的页面"):
        export_pdf([], tmp_path / "t.pdf")


def test_export_png_reports_write_failure(tmp_path):
    with pytest.raises(OSError, match="无法写入文件"):
        export_png([img(10, 50)], tmp_path / "missing_dir" / "t.png")


def test_paginate_handles_sheets_narrower_than_widest_image(tmp_path):
    # re-flowed tab lines differ in width; a sheet without the widest line must still
    # be padded to the common sheet width
    images = [img(100, 100), img(200, 80)]  # the 80-wide image lands on its own sheet
    sheets = paginate(images)
    assert len(sheets) == 2
    assert all(s.shape[1] == 100 for s in sheets)
    assert (sheets[1][:200, 80:] == 255).all()  # right padding
    assert (sheets[1][:200, :80] == 0).all()  # content kept
    export_pdf(images, tmp_path / "mixed.pdf")
