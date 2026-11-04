"""Page pixels stay within the window's in-memory cap, whatever the user does.

`max_images_in_memory` only ever bounded the pages someone opened one by one.
Measured with the real window: a Smart Workflow run over 60 pages of 1200x1800
held all 60 in image_data (641 MB RSS, against 334 MB once fixed), and
scrolling 40 webtoon pages of 800x5000 held all 40 (458 MB of pixels) while the
strip loader itself kept 5. Every page is on disk — its file or its latest
history file — so a page out of image_data is just read back when needed.
"""

import numpy as np
import pytest
from PIL import Image

from modules.utils.textblock import TextBlock


def _pump_until(qapp, condition, timeout_ms=30000):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


def _pump_for(qapp, ms):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        qapp.processEvents()


def held(win):
    return [p for p, img in win.image_data.items() if img is not None]


class FakeDetector:
    def detect(self, image):
        return [TextBlock(text_bbox=np.array([20, 20, 140, 60]), text_class="text_free")]


PAGES = 8


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    import controller as controller_mod
    from app.controllers import smart_workflow

    monkeypatch.setattr(smart_workflow.Messages, "show_smart_workflow_done",
                        staticmethod(lambda *a, **k: None))
    win = controller_mod.ComicTranslate()
    win.max_images_in_memory = 3
    paths = []
    for index in range(PAGES):
        page = np.full((1500, 300, 3), 200 + index, np.uint8)  # taller than the view, so a strip unloads
        path = str(tmp_path / f"{index:03d}.png")
        Image.fromarray(page).save(path)
        paths.append(path)
    win.image_ctrl.thread_load_images(paths)
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == PAGES)
    win.pipeline.block_detection.block_detector_cache = FakeDetector()
    yield win, paths
    win._skip_close_prompt = True
    win.close()


def test_a_step_over_every_page_does_not_keep_every_page(window, qapp):
    win, paths = window
    assert win.smart_ctrl.start([("detect", True)])
    assert _pump_until(qapp, lambda: not win.smart_ctrl.running, 60000)
    assert all(win.image_states.blk_list(p) for p in paths)  # every page was read
    assert len(held(win)) <= win.max_images_in_memory


def test_paging_through_keeps_the_newest_pages_and_the_one_on_screen(window, qapp):
    win, paths = window
    for index in [0, 1, 2, 3, 4, 1]:
        win.page_list.setCurrentRow(index)
        assert _pump_until(qapp, lambda: win.curr_img_idx == index and win.image_data.get(paths[index]) is not None)
    assert set(held(win)) == {paths[3], paths[4], paths[1]}
    # A page dropped from memory still opens, from disk.
    win.page_list.setCurrentRow(0)
    assert _pump_until(qapp, lambda: win.curr_img_idx == 0 and win.image_viewer.hasPhoto())
    assert int(win.image_ctrl.load_image(paths[0])[0, 0, 0]) == 200


def test_scrolling_a_webtoon_strip_lets_pages_go(window, qapp):
    win, paths = window
    win.show_main_page()
    win.webtoon_toggle.click()
    assert _pump_until(qapp, lambda: win.image_viewer.webtoon_mode
                       and win.image_viewer.webtoon_manager.loaded_pages)
    loader = win.image_viewer.webtoon_manager.image_loader
    loader.max_loaded_pages = 2
    for index in range(PAGES):
        win.image_viewer.scroll_to_page(index)
        _pump_for(qapp, 150)
    unloaded = [paths[i] for i in range(PAGES) if i not in loader.loaded_pages]
    assert len(unloaded) >= PAGES // 2  # the strip did let pages go
    stray = [p for p in unloaded if win.image_data.get(p) is not None and p not in win.loaded_images]
    assert stray == []

    # Back to the regular view: the strip's pages join the capped cache.
    win.webtoon_toggle.click()
    assert _pump_until(qapp, lambda: not win.image_viewer.webtoon_mode)
    assert len(held(win)) <= win.max_images_in_memory


def test_importing_a_psd_book_keeps_only_the_page_shown(qapp, monkeypatch, tmp_path):
    import controller as controller_mod
    from app.controllers.psd_importer import ImportedPsdPage

    win = controller_mod.ComicTranslate()
    try:
        pages = []
        for index in range(4):
            image = np.full((200, 150, 3), 100 + index, np.uint8)
            path = str(tmp_path / f"psd_{index}.png")
            Image.fromarray(image).save(path)  # the importer writes every page
            pages.append(ImportedPsdPage(
                source_path=str(tmp_path / f"{index}.psd"), image_path=path, rgb_image=image,
                viewer_state={"rectangles": [], "text_items_state": []},
            ))
        win.image_ctrl.on_psd_imported(pages)
        assert held(win) == [pages[0].image_path]
        assert sum(len(h) for h in win.in_memory_history.values()) == 1
        assert int(win.image_ctrl.load_image(pages[3].image_path)[0, 0, 0]) == 103
    finally:
        win._skip_close_prompt = True
        win.close()
