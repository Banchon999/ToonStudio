"""Smart Workflow through the real window, with the models faked.

The point of it, against batch mode: a page that already has a step's result
— here a translation the user fixed by hand — is left alone, while the other
pages go through every step, one step across all pages at a time.
"""

import json
import re

import numpy as np
import pytest
from PIL import Image

from modules.translation.llm.base import BaseLLMTranslation
from modules.utils.glossary import GlossaryEntry
from modules.utils.textblock import TextBlock


def _pump_until(qapp, condition, timeout_ms=30000):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


class FakeLLM(BaseLLMTranslation):
    asked: list[str] = []

    def get_system_prompt(self, source_lang, target_lang):
        return ""

    def identify_speakers(self, blk_list, image):
        return None

    def _perform_translation(self, user_prompt, system_prompt, image):
        blocks = json.loads(re.search(r"\{[\s\S]*\}", user_prompt.split("Translate this:")[-1]).group(0))
        FakeLLM.asked.extend(blocks.values())
        return json.dumps({k: f"แปล:{v}" for k, v in blocks.items()}, ensure_ascii=False)


class FakeDetector:
    def detect(self, image):
        return [TextBlock(text_bbox=np.array([20, 20, 140, 60]), text_class="text_free")]


class FakeOCR:
    def initialize(self, main, lang):
        pass

    def process(self, image, blk_list):
        for blk in blk_list:
            blk.text = f"글자{int(image[0, 0, 0])}"


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    import controller as controller_mod
    from app.controllers import manual_workflow, text as text_mod, smart_workflow
    from modules.translation import factory
    from modules.utils import glossary_extractor

    FakeLLM.asked = []
    monkeypatch.setattr(factory.TranslationFactory, "create_engine",
                        classmethod(lambda cls, *a, **k: FakeLLM()))
    monkeypatch.setattr(manual_workflow, "validate_translator", lambda *a, **k: True)
    monkeypatch.setattr(manual_workflow, "validate_ocr", lambda *a, **k: True)
    monkeypatch.setattr(manual_workflow, "OCRProcessor", FakeOCR)
    monkeypatch.setattr(manual_workflow, "segment_page", lambda image, settings: None)
    monkeypatch.setattr(text_mod, "font_selected", lambda main: True)
    from app import validation
    monkeypatch.setattr(validation, "validate_translator", lambda *a, **k: True)
    monkeypatch.setattr(validation, "validate_ocr", lambda *a, **k: True)
    monkeypatch.setattr(validation, "font_selected", lambda main: True)
    extracted = []
    monkeypatch.setattr(glossary_extractor, "extract_glossary_terms",
                        lambda main, text, existing, progress=None: extracted.append(text) or
                        [GlossaryEntry("글자1", "คำหนึ่ง", "term")])
    done = []
    monkeypatch.setattr(smart_workflow.Messages, "show_smart_workflow_done",
                        staticmethod(lambda parent, summary, stopped=False: done.append((summary, stopped))))

    win = controller_mod.ComicTranslate()
    paths = []
    for index in range(3):
        page = np.full((200, 300, 3), 230, np.uint8)
        page[0, 0] = index + 1                      # tells FakeOCR which page it reads
        page[30:50, 30:130] = 20                    # "lettering" for Segment to find
        path = str(tmp_path / f"{index:03d}.png")
        Image.fromarray(page).save(path)
        paths.append(path)
    win.image_ctrl.thread_load_images(paths)
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == 3)
    win.pipeline.block_detection.block_detector_cache = FakeDetector()
    # No inpainting model in a test: paint the mask white.
    win.pipeline.inpainting.inpaint_image = lambda image, mask, config, blk_list=None: np.where(
        mask[..., None] > 0, 255, image).astype(np.uint8)
    manager = win.settings_page.ui.glossary_page.manager
    manager.save = lambda: None
    manager.enabled = True
    manager.entries = []

    # Page 2 was detected, recognised and translated by hand earlier.
    hand = TextBlock(text_bbox=np.array([20, 20, 140, 60]), text_class="text_free", text="글자2")
    hand.translation = "แก้เองแล้ว"
    win.image_states.get_page_state(paths[1])["blk_list"] = [hand]

    yield win, paths, extracted, done
    win._skip_close_prompt = True
    win.close()


def _run(win, qapp, order=None):
    steps = []
    real = win.smart_ctrl._run
    win.smart_ctrl._run = lambda step, pages: (steps.append((step, list(pages))), real(step, pages))
    assert win.smart_ctrl.start(order)
    assert _pump_until(qapp, lambda: not win.smart_ctrl.running)
    return steps


def test_every_step_runs_across_the_pages_and_hand_work_is_kept(window, qapp):
    win, paths, extracted, done = window
    steps = _run(win, qapp)
    assert [s for s, _ in steps] == ["detect", "recognize", "extract", "translate", "segment", "clean", "render"]
    by_step = dict(steps)
    assert by_step["detect"] == [paths[0], paths[2]]          # page 2 already had blocks
    assert by_step["translate"] == [paths[0], paths[2]]       # and its own translation
    assert "글자2" not in FakeLLM.asked
    states = win.image_states
    assert states.blk_list(paths[1])[0].translation == "แก้เองแล้ว"
    assert states.blk_list(paths[0])[0].translation == "แปล:글자1"
    assert states.blk_list(paths[2])[0].translation == "แปล:글자3"
    assert extracted and "글자1" in extracted[0]
    assert any(e.source == "글자1" for e in win.settings_page.ui.glossary_page.manager.entries)
    for path in paths:
        assert win.image_patches.get(path), path                   # cleaned
        assert states.get_page_state(path)["viewer_state"].get("text_items_state"), path   # rendered
    assert done and not done[-1][1]


def test_a_second_run_finds_nothing_to_do(window, qapp):
    win, paths, _, done = window
    _run(win, qapp)
    FakeLLM.asked = []
    steps = _run(win, qapp)
    assert steps == [] and FakeLLM.asked == []
    assert done[-1][1] is False


def test_the_order_is_the_users(window, qapp):
    win, paths, _, _ = window
    order = [("detect", True), ("recognize", True), ("translate", True), ("extract", False),
             ("segment", False), ("clean", False), ("render", False)]
    steps = _run(win, qapp, order)
    assert [s for s, _ in steps] == ["detect", "recognize", "translate"]
    assert not any(win.image_patches.get(p) for p in paths)


def test_stop_ends_the_run_after_the_step_in_progress(window, qapp):
    win, paths, _, done = window
    real = win.smart_ctrl._run

    def run_then_stop(step, pages):
        real(step, pages)
        win.smart_ctrl.cancel()

    win.smart_ctrl._run = run_then_stop
    assert win.smart_ctrl.start()
    assert _pump_until(qapp, lambda: not win.smart_ctrl.running)
    assert not any(win.image_states.blk_list(p)[0].text for p in (paths[0], paths[2])
                   if win.image_states.blk_list(p))
    assert done[-1][1] is True


def test_an_order_that_cannot_run_is_refused(window, qapp, monkeypatch):
    from app.controllers import smart_workflow

    win, *_ = window
    shown = []
    monkeypatch.setattr(smart_workflow.Messages, "show_smart_workflow_invalid",
                        staticmethod(lambda parent, problems: shown.append(problems)))
    assert not win.smart_ctrl.start([("translate", True), ("recognize", True)])
    assert shown and "after" in shown[0]
    assert not win.smart_ctrl.running


def test_the_dialog_saves_the_order(window, qapp):
    from PySide6 import QtCore
    from app.controllers.smart_workflow import load_order
    from app.ui.smart_workflow_dialog import SmartWorkflowDialog

    win, *_ = window
    dialog = SmartWorkflowDialog(win)
    item = dialog.steps.takeItem(dialog.steps.count() - 1)       # render
    dialog.steps.insertItem(0, item)
    dialog._check()
    assert not dialog.save_button.isEnabled()                    # render before translate
    dialog.steps.insertItem(dialog.steps.count() - 1, dialog.steps.takeItem(0))
    dialog.steps.item(2).setCheckState(QtCore.Qt.CheckState.Unchecked)   # extract off
    assert dialog.save_button.isEnabled()
    dialog._save()
    order = load_order()
    assert ("extract", False) in order and order[0] == ("detect", True)
    dialog.deleteLater()


def test_the_run_button_starts_smart_workflow_in_smart_mode(window, qapp):
    win, *_ = window
    started = []
    win.smart_ctrl.start = lambda order=None: started.append(True) or True
    win.smart_radio.click()
    assert win.translate_button.text() == "Run Workflow"
    win.translate_button.click()
    assert started == [True]
    win.automatic_radio.click()
    assert win.translate_button.text() == "Translate All"


def test_webtoon_mode_runs_on_the_pages_of_the_strip(window, qapp):
    win, paths, _, done = window
    win.show_main_page()
    win.webtoon_toggle.click()
    assert _pump_until(qapp, lambda: win.image_viewer.webtoon_mode
                       and len(win.image_viewer.webtoon_manager.loaded_pages) >= 2)
    order = [("detect", True), ("recognize", True), ("translate", True), ("extract", False),
             ("segment", False), ("clean", False), ("render", False)]
    steps = _run(win, qapp, order)
    assert [s for s, _ in steps] == ["detect", "recognize", "translate"]
    states = win.image_states
    assert states.blk_list(paths[0])[0].translation == "แปล:글자1"
    assert states.blk_list(paths[1])[0].translation == "แก้เองแล้ว"
    assert done and not done[-1][1]


def test_a_missing_font_is_caught_before_anything_runs(window, qapp, monkeypatch):
    # Found on a real run: Render refused for want of a font after every paid
    # step had already run.
    from app import validation

    win, paths, _, done = window
    monkeypatch.setattr(validation, "font_selected", lambda main: False)
    steps = []
    real = win.smart_ctrl._run
    win.smart_ctrl._run = lambda step, pages: (steps.append(step), real(step, pages))
    assert not win.smart_ctrl.start()
    assert steps == [] and not win.smart_ctrl.running
    # Without Render in the run, the font is not needed.
    order = [(s, s in ("detect",)) for s in ("detect", "recognize", "extract", "translate",
                                             "segment", "clean", "render")]
    assert win.smart_ctrl.start(order)
    assert _pump_until(qapp, lambda: not win.smart_ctrl.running)
    assert steps == ["detect"]


def test_rendered_text_is_centred_where_the_lettering_was(window, qapp):
    # The multi-page Render pinned each text box to the top-left corner of
    # the detected box, so a translation shorter than its source sat high
    # and to the left on every page Smart Workflow rendered.
    win, paths, _, _ = window
    _run(win, qapp)
    x1, y1, x2, y2 = 20, 20, 140, 60          # FakeDetector's box
    for path in (paths[0], paths[2]):
        item = win.image_states.get_page_state(path)["viewer_state"]["text_items_state"][0]
        x, y = (float(v) for v in item["position"])
        assert x + item["width"] / 2 == pytest.approx((x1 + x2) / 2, abs=1)
        assert y + item["height"] / 2 == pytest.approx((y1 + y2) / 2, abs=1)


def test_the_single_page_render_centres_text_in_its_bubble(window, qapp):
    # The Render button (one page) goes through on_blk_rendered, which placed
    # the item at the detected box's corner.
    win, paths, _, _ = window
    blk = TextBlock(text_bbox=np.array([120, 90, 180, 110]), bubble_bbox=np.array([60, 40, 260, 180]),
                    text_class="text_bubble")
    blk.translation = "สวัสดี"
    win.blk_list = [blk]
    win.text_ctrl.on_blk_rendered("สวัสดี", 20, blk, win.image_files[win.curr_img_idx])
    item = win.image_viewer.text_items[-1]
    rect = item.text_rect()
    assert item.pos().x() + rect.width() / 2 == pytest.approx(160, abs=1)
    assert item.pos().y() + rect.height() / 2 == pytest.approx(110, abs=1)


def test_rendering_a_page_again_does_not_draw_its_text_twice(window, qapp):
    # Render skips blocks that already have text by matching an item to its
    # block. It matched by position, which centring moved off the block's
    # corner — so it now matches by the block's object_id.
    win, paths, _, _ = window
    _run(win, qapp)
    state = win.image_states.get_page_state(paths[2])["viewer_state"]
    assert len(state["text_items_state"]) == 1
    done = []
    win.text_ctrl.render_text(paths=[paths[2]], on_done=done.append)
    assert _pump_until(qapp, lambda: done)
    assert len(state["text_items_state"]) == 1

    win.image_ctrl.display_image(0) if win.curr_img_idx != 0 else None
    assert _pump_until(qapp, lambda: win.curr_img_idx == 0 and win.blk_list)
    before = len(win.image_viewer.text_items)
    assert before == 1
    win.text_ctrl.render_text()
    _pump_until(qapp, lambda: False, timeout_ms=1500)
    assert len(win.image_viewer.text_items) == before
