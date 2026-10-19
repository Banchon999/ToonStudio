"""Smart Workflow: every step across all pages, in the user's order, skipping done work.

Each step runs through the same multi-page code the manual buttons use when
several pages are selected (`ManualWorkflowController.block_detect(paths=...)`
and friends), so the results land in exactly the page state the editor reads.
What runs where is decided by `core.smart_workflow` from what each page
already shows — a page whose translation was fixed by hand is not translated
again, which is the difference from batch mode.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings

from core.smart_workflow import (
    DEFAULT_ORDER,
    EXTRACTED_KEY,
    normalise_order,
    page_evidence,
    pages_for,
    validate,
)
from app.ui.messages import Messages
from core.i18n import translate

if TYPE_CHECKING:
    from controller import ComicTranslate

logger = logging.getLogger(__name__)

SETTINGS_KEY = "smart_workflow/steps"


def step_label(step: str) -> str:
    return {
        "detect": translate("SmartWorkflow", "Detect"),
        "recognize": translate("SmartWorkflow", "Recognize text"),
        "extract": translate("SmartWorkflow", "Extract glossary terms"),
        "translate": translate("SmartWorkflow", "Translate"),
        "segment": translate("SmartWorkflow", "Segment"),
        "clean": translate("SmartWorkflow", "Clean"),
        "render": translate("SmartWorkflow", "Render"),
    }.get(step, step)


def load_order() -> list[tuple[str, bool]]:
    raw = QSettings("ComicLabs", "ComicTranslate").value(SETTINGS_KEY, "")
    try:
        saved = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        saved = None
    return normalise_order(saved or [(s, True) for s in DEFAULT_ORDER])


def save_order(order: list[tuple[str, bool]]) -> None:
    QSettings("ComicLabs", "ComicTranslate").setValue(
        SETTINGS_KEY, json.dumps([[s, bool(e)] for s, e in order]))


class SmartWorkflowController:
    def __init__(self, main: ComicTranslate) -> None:
        self.main = main
        self.running = False
        self.cancel_requested = False
        self._steps: list[str] = []
        self._pages: list[str] = []
        self._index = 0
        self._done: list[tuple[str, int]] = []   # (step, pages it ran on)
        self._failed = False

    # --- state -----------------------------------------------------------

    def _sync_current_page(self) -> None:
        """Put what is on the canvas into the page state, which is what is read."""
        main = self.main
        if main.webtoon_mode:
            manager = getattr(main.image_viewer, "webtoon_manager", None)
            scene_mgr = getattr(manager, "scene_item_manager", None) if manager else None
            if scene_mgr is not None:
                scene_mgr.save_all_scene_items_to_states()
        elif main.image_viewer.hasPhoto():
            main.image_ctrl.save_current_image_state()

    def _evidence(self) -> dict[str, dict[str, bool]]:
        states, patches = self.main.image_states, self.main.image_patches
        return {p: page_evidence(states.get_page_state(p, {}), patches.get(p)) for p in self._pages}

    def _skipped(self) -> set[str]:
        return {p for p in self._pages if self.main.image_states.is_skipped(p)}

    # --- run -------------------------------------------------------------

    def start(self, order: list[tuple[str, bool]] | None = None) -> bool:
        if self.running or not self.main.image_files:
            return False
        order = order if order is not None else load_order()
        steps = [s for s, enabled in order if enabled]
        blocking = [p for p in validate(steps) if p.blocking]
        if blocking or not steps:
            Messages.show_smart_workflow_invalid(self.main, "; ".join(p.message for p in blocking))
            return False
        if not self._preflight(steps):
            return False
        selected = self.main.get_selected_page_paths()
        self._pages = list(selected) if len(selected) > 1 else list(self.main.image_files)
        self._steps, self._index, self._done = steps, 0, []
        self.running, self.cancel_requested, self._failed = True, False, False
        self._set_busy(True)
        self._next()
        return True

    def _preflight(self, steps: list[str]) -> bool:
        """Settings each step will need, checked before the first one runs.

        A missing font used to surface at Render, after every paid step had
        already run; each check shows its own message, as the buttons do.
        """
        from app.validation import font_selected, validate_ocr, validate_translator

        if "recognize" in steps and not validate_ocr(self.main):
            return False
        if "translate" in steps or "extract" in steps:
            targets = {self.main.image_states.languages(p)[1] or self.main.t_combo.currentText()
                       for p in self.main.image_files}
            if not all(validate_translator(self.main, t) for t in targets):
                return False
        if "render" in steps and not font_selected(self.main):
            return False
        return True

    def cancel(self) -> None:
        if self.running:
            self.cancel_requested = True
            self._status(translate("SmartWorkflow", "Smart Workflow: stopping after this page…"))

    def _next(self) -> None:
        if self.cancel_requested or self._failed:
            return self._finish()
        while self._index < len(self._steps):
            step = self._steps[self._index]
            self._index += 1
            self._sync_current_page()
            pages = pages_for(step, self._pages, self._evidence(), self._skipped())
            if not pages:
                logger.info("Smart Workflow: %s — nothing to do", step)
                continue
            self._status(translate("SmartWorkflow", "Smart Workflow: step {0}/{1} · {2} · {3} page(s)").format(
                self._index, len(self._steps), step_label(step), len(pages)))
            logger.info("Smart Workflow: %s on %d page(s)", step, len(pages))
            self._done.append((step, len(pages)))
            self._run(step, pages)
            return None
        return self._finish()

    def _step_done(self, ok: bool) -> None:
        if not ok:
            self._failed = True
        # The step's own finished callback re-enabled the buttons; keep them
        # off until the whole run is over.
        self._set_busy(True)
        self._next()

    def _run(self, step: str, pages: list[str]) -> None:
        wf = self.main.manual_workflow_ctrl
        runners = {
            "detect": lambda: wf.block_detect(paths=pages, on_done=self._step_done),
            "recognize": lambda: wf.ocr(paths=pages, on_done=self._step_done),
            "extract": lambda: self._extract(pages),
            "translate": lambda: wf.translate_image(paths=pages, on_done=self._step_done),
            "segment": lambda: wf.load_segmentation_points(paths=pages, on_done=self._step_done),
            "clean": lambda: wf.inpaint_and_set(paths=pages, on_done=self._step_done),
            "render": lambda: self.main.text_ctrl.render_text(paths=pages, on_done=self._step_done),
        }
        runners[step]()

    def _extract(self, pages: list[str]) -> None:
        """Glossary terms from the recognised text of `pages`, in one LLM run."""
        manager = getattr(getattr(self.main.settings_page.ui, "glossary_page", None), "manager", None)
        if manager is None or not manager.enabled:
            logger.info("Smart Workflow: glossary is off, extract step skipped")
            return self._step_done(True)
        texts = []
        for page in pages:
            texts.extend(b.text for b in self.main.image_states.blk_list(page) if (b.text or "").strip())
        if not texts:
            return self._step_done(True)
        from modules.utils.glossary_extractor import extract_glossary_terms
        existing = manager.extraction_skip_sources()

        def merge(entries):
            added, filled = manager.merge_extracted(entries or [])
            logger.info("Smart Workflow: glossary +%d terms, %d genders filled", added, filled)
            page_ui = self.main.settings_page.ui.glossary_page
            if added or filled:
                page_ui.refresh_table()
            for page in pages:
                state = self.main.image_states.get_page_state(page)
                if state is not None:
                    state[EXTRACTED_KEY] = True
            self.main.mark_project_dirty()

        error_cb, finished_cb = self.main.manual_workflow_ctrl._step_callbacks(self._step_done, None)
        self.main.run_threaded(
            lambda: extract_glossary_terms(self.main, "\n".join(texts), existing),
            merge, error_cb, finished_cb,
        )

    def _finish(self) -> None:
        cancelled, failed = self.cancel_requested, self._failed
        self.running = False
        self.cancel_requested = False
        self._set_busy(False)
        self._status("")
        refresh = getattr(self.main, "refresh_step_bar", None)
        if callable(refresh):
            refresh()
        summary = " · ".join(
            translate("SmartWorkflow", "{0}: {1} page(s)").format(step_label(s), n) for s, n in self._done
        ) or translate("SmartWorkflow", "every page already had every step")
        Messages.show_smart_workflow_done(self.main, summary, stopped=failed or cancelled)

    # --- UI ----------------------------------------------------------------

    def _status(self, text: str) -> None:
        bar = getattr(self.main, "editor_status_bar", None)
        if bar is not None and hasattr(bar, "set_workflow_status"):
            bar.set_workflow_status(text, running=self.running)

    def _set_busy(self, busy: bool) -> None:
        main = self.main
        main.loading.setVisible(busy)
        if busy:
            main.disable_hbutton_group()
        main.translate_button.setEnabled(not busy)
        main.webtoon_toggle.setEnabled(not busy)
        if hasattr(main, "smart_settings_button"):
            main.smart_settings_button.setEnabled(not busy)
