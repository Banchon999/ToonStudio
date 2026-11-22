"""Export as a folder of images, and credit pages before/after each chapter.

A credit page is a page of its own (the owner's choice), as wide as the
chapter's pages, in every image/CBZ/PDF/ZIP export — never watermarked.
"""

import os
import zipfile

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QElapsedTimer

from core.watermark import WatermarkSettings, credit_image, export_names


def test_pages_keep_their_names_without_credit_pages():
    assert export_names(["a.jpg", "b.png"], False, False) == ["a.jpg", "b.png"]


def test_credit_pages_number_everything_so_they_sort_first_and_last():
    assert export_names(["x.jpg", "y.jpg"], True, True) == ["001.png", "002.jpg", "003.jpg", "004.png"]
    assert export_names(["x.jpg"], False, True) == ["001.jpg", "002.png"]
    many = export_names([f"{i}.png" for i in range(1000)], True, False)
    assert many[0] == "0001.png" and many[-1] == "1001.png"


def test_a_credit_image_is_sized_to_the_page_and_its_transparency_is_white(tmp_path):
    rgba = np.zeros((50, 100, 4), np.uint8)
    rgba[:, :50] = (255, 0, 0, 255)  # left half red, right half transparent
    path = tmp_path / "credit.png"
    Image.fromarray(rgba).save(path)
    out = credit_image(str(path), 200)
    assert out.shape == (100, 200, 3)
    assert tuple(out[50, 20]) == (255, 0, 0)
    assert tuple(out[50, 180]) == (255, 255, 255)
    assert credit_image(str(tmp_path / "missing.png"), 100) is None


def test_credit_pages_only_count_when_the_file_is_there(tmp_path):
    path = tmp_path / "c.png"
    Image.fromarray(np.zeros((4, 4, 3), np.uint8)).save(path)
    settings = WatermarkSettings.from_dict({"credit_first": str(path), "credit_last": str(tmp_path / "gone.png")})
    assert settings.credit_pages() == (str(path), "")
    assert not settings.is_active()  # credit pages do not need the watermark on


def _pump_until(qapp, condition, timeout_ms=20000):
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


@pytest.fixture
def window(qapp, tmp_path):
    import controller as controller_mod

    paths = []
    for chapter, shade in (("ch1", 40), ("ch2", 90)):
        folder = tmp_path / "src" / chapter
        folder.mkdir(parents=True)
        for name in ("001.jpg", "002.jpg"):
            path = str(folder / name)
            Image.fromarray(np.full((300, 200, 3), shade, np.uint8)).save(path)
            paths.append(path)
    win = controller_mod.ComicTranslate()
    win.image_ctrl.thread_load_images(paths)
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == 4)
    yield win
    win.settings_page.ui.export_page.watermark_section.set_settings(WatermarkSettings())
    win._skip_close_prompt = True
    win.close()


def _chapters(win):
    return {p: os.path.basename(os.path.dirname(p)) for p in win.image_files}


def test_a_folder_export_writes_each_chapter_into_its_own_folder(window, tmp_path):
    ctrl = window.project_ctrl
    out = tmp_path / "out"
    plan = ctrl.folder_export_plan(str(out), _chapters(window))
    assert all(group["folder"] for group in plan)
    ctrl.save_and_make_worker(plan, ctrl._build_all_pages_current_state(), None, ctrl.credit_pages())
    assert sorted(os.listdir(out)) == ["ch1", "ch2"]
    assert sorted(os.listdir(out / "ch1")) == ["001.jpg", "002.jpg"]
    assert np.asarray(Image.open(out / "ch2" / "001.jpg")).mean() > 80


def test_credit_pages_open_and_close_every_chapter(window, tmp_path):
    first, last = tmp_path / "hello.png", tmp_path / "bye.png"
    Image.fromarray(np.full((50, 100, 3), (255, 0, 0), np.uint8)).save(first)
    Image.fromarray(np.full((40, 100, 3), (0, 0, 255), np.uint8)).save(last)
    section = window.settings_page.ui.export_page.watermark_section
    section.set_credit_page("credit_first", str(first))
    section.set_credit_page("credit_last", str(last))
    stored = window.project_ctrl.credit_pages()
    assert all(stored) and all(os.path.dirname(p) != str(tmp_path) for p in stored), "kept as copies"

    ctrl = window.project_ctrl
    out = tmp_path / "out"
    ctrl.save_and_make_worker(ctrl.folder_export_plan(str(out), _chapters(window)),
                              ctrl._build_all_pages_current_state(), None, ctrl.credit_pages())
    for chapter in ("ch1", "ch2"):
        names = sorted(os.listdir(out / chapter))
        assert names == ["001.png", "002.jpg", "003.jpg", "004.png"]
        opening = np.asarray(Image.open(out / chapter / "001.png"))
        closing = np.asarray(Image.open(out / chapter / "004.png"))
        assert opening.shape == (100, 200, 3) and tuple(opening[50, 100]) == (255, 0, 0), "page width"
        assert closing.shape == (80, 200, 3) and tuple(closing[40, 100]) == (0, 0, 255)

    # An archive carries them in the same order.
    cbz = tmp_path / "ch1.cbz"
    plan = [{"group_name": "ch1", "page_indices": [0, 1], "output_path": str(cbz)}]
    ctrl.save_and_make_worker(plan, ctrl._build_all_pages_current_state(), None, ctrl.credit_pages())
    with zipfile.ZipFile(cbz) as archive:
        assert sorted(archive.namelist()) == ["001.png", "002.jpg", "003.jpg", "004.png"]


def test_the_export_menu_offers_a_folder(window):
    labels = [action.text() for action in window.export_menu.actions()]
    assert "Images (Folder)" in labels
