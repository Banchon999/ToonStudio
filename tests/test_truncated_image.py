"""A page file cut off at the end is read anyway (reported from beta.29).

Detect stopped with "OSError: image file is truncated (44 bytes not processed)"
from imkit.read_image, while the same file showed on the canvas: Qt and
browsers draw what is there, Pillow refused. It is now read with the missing
part left grey, and a warning is logged.
"""
import io

import numpy as np
import pytest
from PIL import Image, ImageFile

import imkit as imk


@pytest.fixture(autouse=True)
def strict_pillow(monkeypatch):
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)


def _cut_file(tmp_path, fmt, cut):
    rng = np.random.default_rng(0)
    page = rng.integers(0, 255, (120, 80, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(page).save(buf, format=fmt)
    path = tmp_path / f"page.{fmt.lower()}"
    path.write_bytes(buf.getvalue()[:-cut])
    return path


@pytest.mark.parametrize("fmt, cut", [("JPEG", 44), ("PNG", 44)])
def test_a_file_cut_off_at_the_end_is_still_read(tmp_path, fmt, cut, caplog):
    path = _cut_file(tmp_path, fmt, cut)
    with pytest.raises(OSError):
        np.array(Image.open(path))  # what Pillow does on its own
    with caplog.at_level("WARNING"):
        page = imk.read_image(str(path))
    assert page.shape == (120, 80, 3) and page.dtype == np.uint8
    assert "cut off" in caplog.text


def test_a_file_that_is_not_an_image_still_fails(tmp_path):
    path = tmp_path / "page.png"
    path.write_bytes(b"not an image at all")
    with pytest.raises(OSError):
        imk.read_image(str(path))


def test_the_webtoon_batch_reads_a_cut_off_page_too(tmp_path):
    from types import SimpleNamespace

    from pipeline.webtoon_batch.flow import FlowMixin

    path = _cut_file(tmp_path, "JPEG", 44)
    failures = []
    owner = SimpleNamespace(_report_image_load_failure=lambda p, e: failures.append(e))
    vpage = SimpleNamespace(physical_page_path=str(path), crop_top=10, crop_bottom=90, physical_width=80)
    arr = FlowMixin._read_virtual_image(owner, vpage)
    assert failures == [] and arr.shape == (80, 80, 3)
