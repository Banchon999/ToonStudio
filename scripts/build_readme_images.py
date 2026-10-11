"""Build the images in docs/images that README.md shows.

Everything is drawn or produced here, so the README never carries anyone
else's artwork and every screenshot can be regenerated when the UI changes:

  pages      draw two demo pages (shapes only) and a webtoon strip cut into slices
  translate  detect + OCR locally, translate to Thai through OpenRouter, cache JSON
  render     clean + render the translation with the app's own batch path (after image)
  shots      screenshots of the real window, offscreen

  python scripts/build_readme_images.py pages --font Bangers-Regular.ttf
  python scripts/build_readme_images.py translate --model google/gemini-3.1-flash-lite
  python scripts/build_readme_images.py render
  python scripts/build_readme_images.py shots

`translate` needs an OpenRouter key in the environment (OPENROUTER_API_KEY) or
a proxy that supplies it; the others run offline. The source lettering font is
any comic face (Bangers, OFL, was used); it is an input, not committed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
DEMO = OUT / "demo"
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

INK = (24, 24, 30)
PAPER = (250, 250, 247)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _vgradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def _screentone(size, base, dot, step=7, radius=1.6):
    img = Image.new("RGB", size, base)
    d = ImageDraw.Draw(img)
    for y in range(0, size[1], step):
        off = (step // 2) if (y // step) % 2 else 0
        for x in range(off, size[0], step):
            d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=dot)
    return img


def _figure(d: ImageDraw.ImageDraw, x, y, scale, fill, hair=None):
    """A simple silhouette: head, hair, shoulders. (x, y) is the head centre."""
    r = 38 * scale
    d.ellipse((x - 1.6 * r, y + 0.9 * r, x + 1.6 * r, y + 4.2 * r), fill=fill)   # shoulders
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill)                            # head
    if hair:
        d.chord((x - 1.08 * r, y - 1.12 * r, x + 1.08 * r, y + 0.7 * r), 180, 360, fill=hair)


def _lettering(d, box, lines, font, fill=INK, spacing=1.12):
    """Centre `lines` in `box` (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = box
    heights = [font.getbbox(t)[3] - font.getbbox(t)[1] for t in lines]
    line_h = max(heights) * spacing
    total = line_h * len(lines)
    y = (y1 + y2) / 2 - total / 2
    for t in lines:
        w = d.textlength(t, font=font)
        d.text(((x1 + x2) / 2 - w / 2, y), t, font=font, fill=fill)
        y += line_h


def _bubble(page: Image.Image, box, tail=None, cloud=False, width=4):
    """A speech bubble pasted onto `page`: one shape (ellipse or cloud, plus a
    tail to `tail`), filled white with its outline traced around the union,
    so the tail joins the bubble without a line across it."""
    x1, y1, x2, y2 = (int(v) for v in box)
    pad = 6 + width + (int(0.6 * min(x2 - x1, y2 - y1)) if cloud else 0)
    mx1 = min(x1, tail[0] if tail else x1) - pad
    my1 = min(y1, tail[1] if tail else y1) - pad
    mx2 = max(x2, tail[0] if tail else x2) + pad
    my2 = max(y2, tail[1] if tail else y2) + pad
    mask = Image.new("L", (mx2 - mx1, my2 - my1), 0)
    dm = ImageDraw.Draw(mask)
    shift = lambda pts: [(px - mx1, py - my1) for px, py in pts]  # noqa: E731
    if cloud:
        rng = random.Random(7)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rx, ry = (x2 - x1) / 2, (y2 - y1) / 2
        for k in range(14):
            a = 2 * math.pi * k / 14
            px, py = cx + rx * 0.8 * math.cos(a), cy + ry * 0.74 * math.sin(a)
            r = rng.uniform(0.26, 0.32) * min(rx, ry) * 1.7
            dm.ellipse(shift([(px - r, py - r), (px + r, py + r)]), fill=255)
        dm.ellipse(shift([(x1 + 20, y1 + 20), (x2 - 20, y2 - 20)]), fill=255)
    else:
        dm.ellipse(shift([(x1, y1), (x2, y2)]), fill=255)
    if tail:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        base = 0.16 * (x2 - x1)
        dm.polygon(shift([(cx - base, cy), (cx + base * 0.4, cy), tail]), fill=255)
    outer = mask.filter(ImageFilter.MaxFilter(2 * width + 1))
    page.paste(INK, (mx1, my1), outer)
    page.paste((255, 255, 255), (mx1, my1), mask)


def draw_manga_page(font_path: str) -> Image.Image:
    W, H = 1000, 1480
    page = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(page)
    f_big, f_mid, f_cap, f_sfx = (_font(font_path, s) for s in (40, 36, 30, 120))
    m, g = 28, 18

    # Panel 1: dawn sky, hills, a borderless caption.
    p1 = (m, m, W - m, 470)
    sky = _vgradient((p1[2] - p1[0], p1[3] - p1[1]), (255, 196, 150), (120, 160, 230))
    page.paste(sky, p1[:2])
    hills = [(p1[0], p1[3]), (p1[0], 380), (220, 330), (420, 390), (640, 300), (W - m, 360), (W - m, p1[3])]
    d.polygon(hills, fill=(70, 80, 120))
    d.polygon([(p1[0], p1[3]), (p1[0], 420), (300, 400), (560, 440), (W - m, 410), (W - m, p1[3])], fill=(40, 46, 78))
    d.ellipse((700, 120, 790, 210), fill=(255, 236, 200))
    d.rectangle(p1, outline=INK, width=5)
    _lettering(d, (60, 50, 520, 150), ["THE NEXT MORNING,", "AT THE EDGE OF TOWN..."], f_cap, fill=(255, 255, 255))
    _bubble(page, (520, 210, 930, 400), tail=(640, 455))
    _lettering(d, (560, 240, 890, 375), ["WHERE ARE WE", "GOING, JUN?"], f_big)

    # Panel 2: screentone, two figures, two bubbles.
    p2 = (m, 470 + g, 560, 1040)
    panel = _screentone((p2[2] - p2[0], p2[3] - p2[1]), (238, 238, 240), (150, 150, 165))
    dp = ImageDraw.Draw(panel)
    _figure(dp, 170 - p2[0], 860 - p2[1], 1.25, (60, 60, 72), hair=(25, 25, 30))
    _figure(dp, 400 - p2[0], 880 - p2[1], 1.15, (90, 70, 80), hair=(40, 30, 35))
    page.paste(panel, p2[:2])
    d = ImageDraw.Draw(page)
    d.rectangle(p2, outline=INK, width=5)
    _bubble(page, (50, 510, 330, 700), tail=(170, 790))
    _lettering(d, (80, 540, 300, 670), ["TO THE OLD", "LIGHTHOUSE,", "MINA."], f_mid)
    _bubble(page, (300, 640, 540, 800), cloud=True)
    _lettering(d, (320, 665, 520, 775), ["YOU", "PROMISED!"], f_mid)

    # Panel 3: speed lines and an SFX.
    p3 = (560 + g, 470 + g, W - m, 1040)
    pw, ph = p3[2] - p3[0], p3[3] - p3[1]
    panel = Image.new("RGB", (pw, ph), "white")
    dp = ImageDraw.Draw(panel)
    cx, cy = pw / 2, ph / 2 + 60
    rng = random.Random(3)
    for k in range(90):
        a = 2 * math.pi * k / 90 + rng.uniform(-0.02, 0.02)
        r0 = rng.uniform(120, 170)
        dp.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                 (cx + 600 * math.cos(a), cy + 600 * math.sin(a))], fill=(60, 60, 70), width=2)
    _figure(dp, cx, cy - 20, 1.0, (30, 30, 36), hair=(10, 10, 12))
    page.paste(panel, p3[:2])
    d = ImageDraw.Draw(page)
    d.rectangle(p3, outline=INK, width=5)
    sfx = Image.new("RGBA", (420, 170), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sfx)
    ds.text((10, 10), "WHOOSH", font=f_sfx, fill=(230, 60, 90), stroke_width=6, stroke_fill="white")
    page.paste(sfx.rotate(12, expand=True, resample=Image.BICUBIC), (int(p3[0]) - 10, int(p3[1]) + 10),
               sfx.rotate(12, expand=True, resample=Image.BICUBIC))

    # Panel 4: wide, gradient bubble, narration box with an outline.
    p4 = (m, 1040 + g, W - m, H - m)
    sea = _vgradient((p4[2] - p4[0], p4[3] - p4[1]), (40, 70, 120), (12, 24, 52))
    page.paste(sea, p4[:2])
    d = ImageDraw.Draw(page)
    d.rectangle((760, 1110, 820, 1340), fill=(235, 235, 240))
    d.polygon([(745, 1110), (835, 1110), (790, 1070)], fill=(220, 70, 80))
    d.polygon([(790, 1150), (1000 - m, 1080), (1000 - m, 1220)], fill=(255, 240, 180))
    d.rectangle((p4[0], 1340, p4[2], p4[3]), fill=(8, 16, 36))
    d.rectangle(p4, outline=INK, width=5)
    d.rectangle((60, 1090, 470, 1170), fill="white", outline=INK, width=3)
    _lettering(d, (60, 1090, 470, 1170), ["THE LIGHT WAS STILL ON."], f_cap)
    _bubble(page, (110, 1220, 560, 1400), tail=(420, 1445))
    _lettering(d, (150, 1250, 520, 1370), ["SOMEONE IS WAITING", "FOR US UP THERE..."], f_mid)
    return page


def draw_webtoon_strip(font_path: str) -> Image.Image:
    W, H = 800, 3600
    strip = _vgradient((W, H), (252, 244, 236), (232, 238, 252))
    d = ImageDraw.Draw(strip)
    f = _font(font_path, 40)
    # Panels separated by white gutters; one bubble straddles a slice edge.
    panels = [(60, 120, 740, 900), (60, 1100, 740, 1750), (60, 2050, 740, 2900)]
    colours = [((255, 214, 170), (255, 150, 160)), ((170, 200, 255), (120, 140, 220)), ((200, 240, 210), (90, 160, 140))]
    for (x1, y1, x2, y2), (a, b) in zip(panels, colours):
        strip.paste(_vgradient((x2 - x1, y2 - y1), a, b), (x1, y1))
        d.rectangle((x1, y1, x2, y2), outline=INK, width=5)
    _figure(d, 400, 560, 2.0, (70, 50, 70), hair=(30, 20, 30))
    _figure(d, 260, 1450, 1.4, (40, 60, 100), hair=(20, 25, 40))
    _figure(d, 540, 1480, 1.3, (70, 50, 70), hair=(30, 20, 30))
    _bubble(strip, (180, 960, 620, 1150), tail=(300, 1230))   # crosses the cut at 1000
    _lettering(d, (220, 985, 580, 1125), ["I FOUND THE", "LETTER YOU LEFT."], f)
    _bubble(strip, (120, 1780, 560, 1990))                    # crosses the cut at 1900
    _lettering(d, (160, 1810, 520, 1960), ["DID YOU", "READ IT ALL?"], f)
    _bubble(strip, (240, 2930, 700, 3150), cloud=True)
    _lettering(d, (290, 2960, 650, 3120), ["EVERY", "SINGLE WORD."], f)
    return strip


def cmd_pages(args):
    DEMO.mkdir(parents=True, exist_ok=True)
    page = draw_manga_page(args.font)
    page.save(DEMO / "page.png")
    strip = draw_webtoon_strip(args.font)
    # Uploaded slices cut wherever: through two bubbles.
    cuts = [0, 1000, 1900, 2700, strip.height]
    for i, (a, b) in enumerate(zip(cuts, cuts[1:]), 1):
        strip.crop((0, a, strip.width, b)).save(DEMO / f"slice_{i:02d}.png")
    print("pages written to", DEMO)


# ---------------------------------------------------------------------------
# translate
# ---------------------------------------------------------------------------

GLOSSARY = (("Mina", "มินา", "character", "female"), ("Jun", "จุน", "character", "male"))


class _Settings:
    """Just enough of SettingsPage for the engines, outside the window."""

    def __init__(self, model: str):
        import types

        self.ui = types.SimpleNamespace(tr=lambda s: s)
        self.model = model

    def is_gpu_enabled(self):
        return False

    def get_credentials(self, name=""):
        key = os.environ.get("OPENROUTER_API_KEY", "supplied-by-proxy")
        return {"api_key": key, "model": self.model, "ocr_model": self.model}

    def get_llm_settings(self):
        return {"image_input_enabled": True, "extra_context": ""}

    def get_tool_selection(self, tool):
        return "RT-DETR-v2" if tool == "detector" else None

    def __getattr__(self, name):
        return lambda *a, **k: None


def cmd_translate(args):
    import tempfile

    import numpy as np

    from modules.detection.factory import DetectionEngineFactory
    from modules.ocr.factory import OCRFactory
    from modules.translation.llm.openrouter import OpenRouterTranslation
    from modules.utils.glossary import GlossaryEntry, GlossaryManager, collect_source_text
    from modules.utils.translator_utils import join_translation_line_breaks

    settings = _Settings(args.model)
    image = np.asarray(Image.open(DEMO / "page.png").convert("RGB"))
    blocks = DetectionEngineFactory.create_engine(settings, "RT-DETR-v2").detect(image)
    OCRFactory._create_ppocr(settings, "en", "onnx").process_image(image, blocks)
    blocks = [b for b in blocks if (b.text or "").strip()]

    manager = GlossaryManager(base_dir=tempfile.mkdtemp())
    for source, target, kind, gender in GLOSSARY:
        manager.upsert(GlossaryEntry(source, target, kind, gender), save=False)
    engine = OpenRouterTranslation()
    engine.initialize(settings, "English", "Thai")
    engine.translate(blocks, image, manager.build_prompt(collect_source_text(blocks)))
    join_translation_line_breaks(blocks)   # what Translator.translate does in the app

    rows = [{
        "xyxy": [int(v) for v in b.xyxy],
        "bubble": None if b.bubble_xyxy is None else [int(v) for v in b.bubble_xyxy],
        "class": b.text_class, "text": b.text, "translation": b.translation,
        "speaker": getattr(b, "speaker", ""), "gender": getattr(b, "speaker_gender", ""),
    } for b in blocks]
    (DEMO / "page.json").write_text(json.dumps(
        {"model": args.model, "blocks": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['class']:11s} {r['speaker'] or '-':>6} {r['gender'] or '':6s} "
              f"{r['text']!r:50.50} -> {r['translation']}")


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

RENDER_FONT = "IBM Plex Sans Thai"   # bundled with the app, so anyone can reproduce this


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from app.ui.fonts import load_ui_fonts

    load_ui_fonts()
    return app


def _blocks_from_cache():
    import numpy as np

    from modules.utils.textblock import TextBlock

    data = json.loads((DEMO / "page.json").read_text(encoding="utf-8"))
    blocks = []
    for row in data["blocks"]:
        blk = TextBlock(text_bbox=np.array(row["xyxy"]),
                        bubble_bbox=None if row["bubble"] is None else np.array(row["bubble"]),
                        text_class=row["class"], text=row["text"])
        blk.translation = row["translation"]
        blk.speaker, blk.speaker_gender = row.get("speaker", ""), row.get("gender", "")
        blocks.append(blk)
    return blocks


def cmd_render(args):
    import types

    import numpy as np

    _qapp()
    from app.ui.canvas.save_renderer import ImageSaveRenderer
    from core.text_measure import Alignment, LayoutDirection
    from core.text_style import build_text_item_state
    from modules.inpainting.schema import Config
    from modules.rendering.render import pyside_word_wrap
    from modules.utils.image_utils import generate_mask
    from modules.utils.language_utils import is_no_space_lang
    import modules.utils.text_segmentation as text_segmentation
    from pipeline.inpainting import InpaintingHandler

    image = np.asarray(Image.open(DEMO / "page.png").convert("RGB"))
    blocks = _blocks_from_cache()
    settings = _Settings("")
    settings.get_tool_selection = lambda tool: {"detector": "RT-DETR-v2", "inpainter": "AOT"}.get(tool)
    text_segmentation.model_segmentation_enabled = lambda s: True

    # Clean exactly as batch mode does: page mask, then the fast bubble fill and the inpainter.
    seg = text_segmentation.segment_page(image, settings)
    mask = generate_mask(image, blocks, page_text_mask=seg)
    handler = InpaintingHandler(types.SimpleNamespace(settings_page=settings))
    cleaned = handler.inpaint_image(image, mask, Config(hd_strategy="Resize", hd_strategy_resize_limit=960),
                                    blk_list=blocks)
    patches = handler._get_regular_patches(mask, cleaned)

    states = []
    for blk in blocks:
        x1, y1, w, h = (float(v) for v in blk.xywh)
        # Dark ground under the text -> white letters with a dark outline, as the
        # app's smart colour does from the detector's reading of the original.
        crop = image[int(y1):int(y1 + h), int(x1):int(x1 + w)]
        dark = float(np.median(crop.mean(axis=2))) < 110
        text, size, rw, rh = pyside_word_wrap(
            blk.translation, RENDER_FONT, w, h, 1.0, 2.0, False, False, False,
            Alignment.Center, LayoutDirection.LeftToRight, 40, 12, False, is_no_space_lang("th"),
            return_metrics=True)
        states.append(build_text_item_state(
            object_id="", text=text, font_family=RENDER_FONT, font_size=size,
            text_color="#ffffff" if dark else "#141418", alignment=Alignment.Center,
            line_spacing=1.0, outline_color="#141418" if dark else "#ffffff", outline_width=2.0,
            bold=False, italic=False, underline=False, position=(x1, y1), rotation=float(blk.angle),
            scale=1.0, transform_origin=None, width=rw, height=rh,
            direction=LayoutDirection.LeftToRight, vertical=False, outline=True))

    renderer = ImageSaveRenderer(image)
    renderer.apply_patches(patches)
    Image.fromarray(renderer.render_to_image()).save(DEMO / "page_cleaned.png")
    renderer.add_state_to_image({"text_items_state": states})
    after = Image.fromarray(renderer.render_to_image())
    after.save(DEMO / "page_th.png")

    # The README's hero: original | translated, side by side.
    before = Image.open(DEMO / "page.png").convert("RGB")
    gap = 24
    hero = Image.new("RGB", (before.width * 2 + gap, before.height), (255, 255, 255))
    hero.paste(before, (0, 0))
    hero.paste(after.resize(before.size, Image.LANCZOS), (before.width + gap, 0))
    hero = hero.resize((hero.width * 1200 // hero.width, hero.height * 1200 // hero.width), Image.LANCZOS)
    hero.save(OUT / "before-after.jpg", quality=88, optimize=True)
    print("rendered:", DEMO / "page_th.png", "and", OUT / "before-after.jpg")


# ---------------------------------------------------------------------------
# shots
# ---------------------------------------------------------------------------

def _save_shot(widget, name, width=1440):
    image = widget.grab().toImage()
    path = OUT / f"{name}.png"
    image.save(str(path))
    # Kept small enough for a README: PNG, palette-reduced when that is lossless enough.
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, img.height * width // img.width), Image.LANCZOS)
    img.save(path, optimize=True)
    print("  shot:", path.name, f"{path.stat().st_size // 1024} KB")


def cmd_shots(args):
    import shutil
    import tempfile

    home = tempfile.mkdtemp()
    for var in ("HOME", "XDG_CONFIG_HOME"):
        os.environ[var] = home            # never touch the real user's settings
    os.chdir(ROOT)                        # the UI translations load relative to it
    app = _qapp()
    from PySide6 import QtCore

    from comic import load_translation

    load_translation(app, "ไทย")

    def pump(ms=500):
        timer = QtCore.QElapsedTimer()
        timer.start()
        while timer.elapsed() < ms:
            app.processEvents()

    def wait(condition, ms=30000):
        timer = QtCore.QElapsedTimer()
        timer.start()
        while not condition() and timer.elapsed() < ms:
            app.processEvents()
        return condition()

    from controller import ComicTranslate
    from modules.utils.glossary import GlossaryEntry

    win = ComicTranslate()
    win._skip_close_prompt = True
    win.resize(1440, 900)
    win.show()
    pump(800)
    _save_shot(win, "home")

    # Editor: the cleaned demo page, the translation rendered by the Render step.
    page = Path(home) / "page_001.png"
    shutil.copy(DEMO / "page_cleaned.png", page)
    win.image_ctrl.thread_load_images([str(page)])
    assert wait(lambda: win.image_viewer.hasPhoto()), "page did not load"
    win.show_main_page()
    for combo, text in ((win.s_combo, win.tr("English")), (win.t_combo, win.tr("Thai"))):
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)
    font_index = win.font_dropdown.findText(RENDER_FONT)
    if font_index < 0:
        win.font_dropdown.addItem(RENDER_FONT)
        font_index = win.font_dropdown.findText(RENDER_FONT)
    win.font_dropdown.setCurrentIndex(font_index)
    gm = win.settings_page.ui.glossary_page.manager
    gm.save = lambda: None
    gm.entries = [GlossaryEntry(s, t, k, g) for s, t, k, g in GLOSSARY]
    win.blk_list = _blocks_from_cache()
    win.text_ctrl.render_text()
    assert wait(lambda: len(win.image_viewer.text_items) >= len(win.blk_list)), "render did not finish"
    pump(800)
    win.image_viewer.fitInView()
    items = sorted(win.image_viewer.text_items, key=lambda i: (i.pos().y(), i.pos().x()))
    target = items[1] if len(items) > 1 else items[0]
    win.image_viewer.scene().clearSelection()
    target.setSelected(True)
    win.text_ctrl.on_text_item_selected(target)   # what a click on it does
    pump(800)
    win.refresh_step_bar()
    _save_shot(win, "editor")

    win.inspector_tabs.setCurrentWidget(win.layers_panel)
    pump()
    _save_shot(win, "editor-layers")
    win.inspector_tabs.setCurrentIndex(0)

    win.apply_theme(win.settings_page.ui.tr("Light"))
    pump(800)
    _save_shot(win, "editor-light")
    win.apply_theme(win.settings_page.ui.tr("Dark"))
    pump(800)

    # Stitch: the demo strip as uploaded, in slices cut through two bubbles.
    slices = Path(home) / "raw_chapter"
    slices.mkdir()
    for path in sorted(DEMO.glob("slice_*.png")):
        shutil.copy(path, slices / path.name)
    win.show_stitch_page()
    sp = win.stitch_page
    sp.height_spin.setValue(1400)
    sp.add_folder(str(slices))
    sp.output_edit.setText("~/Comics/Chapter 01/stitched")   # not the temp folder it really used
    sp.prefix_edit.setText("ch01_")
    sp.run_preview()
    wait(lambda: sp._plan is not None, 30000)
    pump(800)
    _save_shot(win, "stitch")

    # The glossary editor, opened from the working page as the nav rail does.
    gm.entries = [GlossaryEntry(src, tgt, kind, gender) for src, tgt, kind, gender in GLOSSARY] + [
        GlossaryEntry("Lighthouse", "ประภาคาร", "place"),
        GlossaryEntry("Old Lighthouse", "ประภาคารเก่า", "place"),
    ]
    win.show_main_page()
    win.show_glossary_dialog()
    pump(800)
    dialog = win._glossary_dialog
    dialog.resize(1000, 640)
    pump(500)
    _save_shot(dialog, "glossary", width=1000)
    dialog.close()

    win.close()
    pump(200)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pages")
    p.add_argument("--font", required=True, help="comic lettering font for the source text")
    p.set_defaults(func=cmd_pages)
    p = sub.add_parser("translate")
    p.add_argument("--model", default="google/gemini-3.1-flash-lite", help="OpenRouter model id")
    p.set_defaults(func=cmd_translate)
    sub.add_parser("render").set_defaults(func=cmd_render)
    sub.add_parser("shots").set_defaults(func=cmd_shots)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
