"""What the multi-page steps (Smart Workflow, several pages selected) draw.

Found from a user's screenshot of a Smart Workflow run in webtoon mode with the
interface in Thai: every translation ran past its bubble, the first line being
the whole sentence up to its only space. Three separate faults, each pinned
here with the real window and fake engines:

* Page state stores the target language by its English name, and the
  multi-page Render looked that up in `lang_mapping`, which is keyed by the
  *interface's* label ("ไทย" in a Thai UI). The lookup gave None, so Thai text
  was wrapped as a language with spaces: unbreakable between spaces, it was
  shrunk to the minimum size and still overflowed. An English UI's key is
  "Thai", which is why nothing caught it.
* In webtoon mode every multi-page step first saves the strip, and a page off
  screen had its bubble clipped as if its page-local coordinates were scene
  coordinates — on every page after the first the bubble fell outside its own
  page and was dropped, so text was fitted to the detected box alone.
* Only the page in view was set aside while a step ran. The other pages on
  screen kept their old items, the next step's save took those as the truth,
  and what the step had found for them was wiped.
"""

import json
import re

import numpy as np
import pytest
from PIL import Image

from modules.translation.llm.base import BaseLLMTranslation
from modules.utils.textblock import TextBlock

THAI = "พลังของคำสาปมันทำปฏิกิริยากับปรารถนาอันแรงกล้า มันเลยมองเห็นได้นะ"
TEXT = [590, 400, 720, 480]
BUBBLE = [500, 300, 790, 600]


def _pump_until(qapp, condition, timeout_ms=60000):
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


class FakeLLM(BaseLLMTranslation):
    def get_system_prompt(self, source_lang, target_lang):
        return ""

    def identify_speakers(self, blk_list, image):
        return None

    def _perform_translation(self, user_prompt, system_prompt, image):
        blocks = json.loads(re.search(r"\{[\s\S]*\}", user_prompt.split("Translate this:")[-1]).group(0))
        return json.dumps({k: THAI for k in blocks}, ensure_ascii=False)


class FakeDetector:
    def detect(self, image):
        return [TextBlock(text_bbox=np.array(TEXT), bubble_bbox=np.array(BUBBLE), text_class="text_bubble")]


class FakeOCR:
    def initialize(self, main, lang):
        pass

    def process(self, image, blk_list):
        for blk in blk_list:
            blk.text = "THE CURSE REACTED"


def _bubble_block():
    blk = TextBlock(text_bbox=np.array(TEXT), bubble_bbox=np.array(BUBBLE), text_class="text_bubble")
    blk.text = "THE CURSE REACTED"
    blk.translation = THAI
    return blk


@pytest.fixture
def make_window(qapp, monkeypatch, tmp_path):
    import controller as controller_mod
    from app.controllers import manual_workflow, smart_workflow, text as text_mod
    from app import validation
    from modules.translation import factory

    monkeypatch.setattr(factory.TranslationFactory, "create_engine",
                        classmethod(lambda cls, *a, **k: FakeLLM()))
    for module in (manual_workflow, validation):
        monkeypatch.setattr(module, "validate_translator", lambda *a, **k: True)
        monkeypatch.setattr(module, "validate_ocr", lambda *a, **k: True)
    monkeypatch.setattr(validation, "font_selected", lambda main: True)
    monkeypatch.setattr(text_mod, "font_selected", lambda main: True)
    monkeypatch.setattr(manual_workflow, "OCRProcessor", FakeOCR)
    monkeypatch.setattr(manual_workflow, "segment_page", lambda image, settings: None)
    monkeypatch.setattr(smart_workflow.Messages, "show_smart_workflow_done",
                        staticmethod(lambda *a, **k: None))
    windows = []

    def make(widths, height=1200):
        win = controller_mod.ComicTranslate()
        windows.append(win)
        paths = []
        for index, width in enumerate(widths):
            page = np.full((height, width, 3), 230, np.uint8)
            page[TEXT[1]:TEXT[3], TEXT[0]:TEXT[2]] = 20
            path = str(tmp_path / f"{index:03d}.png")
            Image.fromarray(page).save(path)
            paths.append(path)
        win.image_ctrl.thread_load_images(paths)
        assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == len(widths))
        win.pipeline.block_detection.block_detector_cache = FakeDetector()
        win.pipeline.inpainting.inpaint_image = lambda image, mask, config, blk_list=None: np.where(
            mask[..., None] > 0, 255, image).astype(np.uint8)
        glossary = win.settings_page.ui.glossary_page.manager
        glossary.save = lambda: None
        glossary.enabled = False
        return win, paths

    yield make
    for win in windows:
        win._skip_close_prompt = True
        win.close()


def _interface_in_thai(win):
    """The language combos as a Thai interface labels them: lang_mapping is
    keyed by the label, while page state keeps the English name."""
    label = next(k for k, v in win.lang_mapping.items() if v == "Thai")
    del win.lang_mapping[label]
    win.lang_mapping["ไทย"] = "Thai"
    win.reverse_lang_mapping = {v: k for k, v in win.lang_mapping.items()}
    index = win.t_combo.findText(label)
    win.t_combo.setItemText(index, "ไทย")
    win.t_combo.blockSignals(True)
    win.t_combo.setCurrentIndex(index)
    win.t_combo.blockSignals(False)


def _text_states(win, path):
    return win.image_states.get_page_state(path)["viewer_state"].get("text_items_state", [])


def test_thai_is_wrapped_as_thai_when_the_interface_is_in_thai(make_window, qapp):
    # A bubble too narrow for the sentence's first half on one line at a
    # readable size, as on the reported page; 12 pt is a common minimum.
    win, paths = make_window([800, 800])
    _interface_in_thai(win)
    win.settings_page.ui.min_font_spinbox.setValue(12)
    narrow_text, narrow_bubble = [300, 500, 420, 560], [250, 440, 470, 640]
    for path in paths:
        blk = TextBlock(text_bbox=np.array(narrow_text), bubble_bbox=np.array(narrow_bubble),
                        text_class="text_bubble")
        blk.translation = THAI
        win.image_states.get_page_state(path)["target_lang"] = "Thai"
        win.image_states.get_page_state(path)["blk_list"] = [blk]
    win.blk_list = list(win.image_states.blk_list(paths[win.curr_img_idx]))

    done = []
    win.text_ctrl.render_text(paths=paths, on_done=done.append)
    assert _pump_until(qapp, lambda: done)
    assert done == [True]

    for path in paths:
        (item,) = _text_states(win, path)
        x = item["position"][0]
        # Inside the bubble, broken between Thai words — not one line up to
        # the only space, shrunk to the minimum and still running past it.
        assert narrow_bubble[0] <= x and x + item["width"] <= narrow_bubble[2], (x, item["width"], item["text"])
        assert item["text"].count("\n") >= 2, item["text"]


def _webtoon(win, qapp):
    win.show_main_page()
    win.webtoon_toggle.click()
    manager = win.image_viewer.webtoon_manager
    assert _pump_until(qapp, lambda: win.image_viewer.webtoon_mode and manager.loaded_pages)
    _pump_for(qapp, 300)
    return manager


def test_a_page_off_screen_keeps_its_bubble_when_the_strip_is_saved(make_window, qapp):
    win, paths = make_window([800] * 6)
    for path in paths:
        win.image_states.get_page_state(path)["blk_list"] = [_bubble_block()]
    manager = _webtoon(win, qapp)
    off_screen = [i for i in range(len(paths)) if i not in manager.loaded_pages]
    assert off_screen

    manager.scene_item_manager.save_all_scene_items_to_states()

    for index in off_screen:
        (blk,) = win.image_states.blk_list(paths[index])
        assert blk.bubble_xyxy is not None, index
        assert [round(v) for v in blk.bubble_xyxy] == BUBBLE, index
        assert [round(v) for v in blk.xyxy] == TEXT, index


def test_a_webtoon_smart_workflow_keeps_every_page_it_worked_on(make_window, qapp):
    # The first page is wider, so the strip's other pages sit off centre and
    # their scene x differs from their page x: positions are checked page-local.
    from app.ui.canvas.text_item import TextBlockItem

    win, paths = make_window([1200] + [800] * 5)
    manager = _webtoon(win, qapp)
    on_screen = sorted(manager.loaded_pages)
    assert len(on_screen) >= 2, on_screen
    order = [(step, step != "extract") for step in
             ("detect", "recognize", "extract", "translate", "segment", "clean", "render")]
    assert win.smart_ctrl.start(order)
    assert _pump_until(qapp, lambda: not win.smart_ctrl.running, 120000)
    _pump_for(qapp, 300)

    layout = manager.layout_manager
    for index, path in enumerate(paths):
        blocks = win.image_states.blk_list(path) if index not in manager.loaded_pages else None
        items = _text_states(win, path)
        if index in manager.loaded_pages:
            # On screen: the page's text is on the canvas, inside its bubble.
            top = layout.image_positions[index]
            left = manager.image_loader.image_items[index].pos().x()
            drawn = [it for it in win.image_viewer._scene.items()
                     if isinstance(it, TextBlockItem) and top <= it.pos().y() < top + layout.image_heights[index]]
            assert len(drawn) == 1, (index, on_screen, len(drawn))
            x = drawn[0].pos().x() - left
            assert BUBBLE[0] <= x and x + drawn[0].text_rect().width() <= BUBBLE[2], (index, x)
        else:
            assert len(blocks) == 1, (index, blocks)
            assert blocks[0].bubble_xyxy is not None, index
            assert len(items) == 1, (index, items)
            x = items[0]["position"][0]
            assert BUBBLE[0] <= x and x + items[0]["width"] <= BUBBLE[2], (index, x, items[0]["width"])


def _white_pixels(win, item):
    """Pure-white pixels the scene draws over the item's box: the default
    outline is white, and the page and the text are not."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    rect = item.mapRectToScene(item.boundingRect()).adjusted(-4, -4, 4, 4)
    image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_RGB888)
    image.fill(0)
    painter = QPainter(image)
    win.image_viewer._scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), rect)
    painter.end()
    rows = np.array(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    pixels = rows[:, : image.width() * 3].reshape(image.height(), image.width(), 3)
    return int((pixels.min(axis=2) == 255).sum())


def test_the_outline_shows_without_touching_the_text(make_window, qapp):
    """Reported from the 3.4.3 test build: after Smart Workflow's Render the
    outline was missing until the text was dragged. The multi-page Render saved
    an outline colour but no outline to draw, and only selecting the item —
    which copies the toolbar's ticked Outline box back onto it — built one."""
    from app.ui.canvas.text_item import TextBlockItem

    win, paths = make_window([800, 800])
    win.outline_checkbox.setChecked(True)
    for path in paths:
        win.image_states.get_page_state(path)["target_lang"] = "Thai"
        win.image_states.get_page_state(path)["blk_list"] = [_bubble_block()]
    win.blk_list = list(win.image_states.blk_list(paths[win.curr_img_idx]))

    done = []
    win.text_ctrl.render_text(paths=paths, on_done=done.append)
    assert _pump_until(qapp, lambda: done)
    _pump_for(qapp, 200)

    for path in paths:
        (state,) = _text_states(win, path)
        assert state["outline"] is True
        assert state["selection_outlines"], "an outline to draw, not only its colour"

    (item,) = [i for i in win.image_viewer._scene.items() if isinstance(i, TextBlockItem)]
    drawn = _white_pixels(win, item)
    # What selecting it used to add: the same outline, rebuilt from the toolbar.
    item.set_outline(item.outline_color, item.outline_width)
    assert drawn > 0
    assert drawn == _white_pixels(win, item)


def _state_saved_by_the_3_4_3_test_build(outline_color="#ffffff"):
    """A rendered item as the buggy multi-page Render saved it: an outline
    colour, `outline` False and no outline to draw."""
    from PySide6.QtGui import QColor

    from app.ui.canvas.text.text_item_properties import TextItemProperties
    from core.text_measure import Alignment, LayoutDirection

    state = TextItemProperties(
        text="HELLO THERE", font_family="DejaVu Sans", font_size=40, text_color=QColor("#141418"),
        alignment=Alignment.Center, line_spacing=1.0,
        outline_color=QColor(outline_color) if outline_color else None, outline_width=3.0,
        bold=True, italic=False, underline=False, direction=LayoutDirection.LeftToRight,
        position=(50, 50), rotation=0, scale=1.0, width=400, height=60,
    ).to_dict()
    assert state["outline"] is False and state["selection_outlines"] == []
    return state


def test_pages_rendered_by_that_build_show_their_outline_on_the_canvas(make_window, qapp):
    from PySide6.QtGui import QColor  # noqa: F401
    from app.ui.canvas.text_item import TextBlockItem  # noqa: F401

    win, _paths = make_window([800])
    item = win.image_viewer.add_text_item(_state_saved_by_the_3_4_3_test_build())
    _pump_for(qapp, 100)
    assert any(o.type.name == "Full_Document" for o in item.selection_outlines)
    assert _white_pixels(win, item) > 0


def test_pages_rendered_by_that_build_export_with_their_outline(qapp):
    from app.ui.canvas.save_renderer import render_text_item_rgba

    def white(state):
        top, left, rgba = render_text_item_rgba(state, 600, 200)
        return int(((rgba[..., :3].min(axis=2) >= 250) & (rgba[..., 3] > 200)).sum())

    assert white(_state_saved_by_the_3_4_3_test_build()) > 0
    # An item with no outline colour is left without one.
    assert white(_state_saved_by_the_3_4_3_test_build(outline_color=None)) == 0
