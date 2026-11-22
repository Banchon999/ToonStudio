# Performance notes (measured, not yet acted on)

The owner asked where the app is slow and whether Rust would help, and asked
for the answer to be kept for later rather than acted on now. Measured
2026-11-22 on a 4-core CPU container (no GPU), with the real pipeline on the
README demo page (1000×1480, 6 blocks) and the four demo slices stacked to an
800×3600 webtoon page. The harness was a script that times and profiles
(`cProfile`, sorted by own time) each stage: detection, OCR, text
segmentation, mask, inpainting, patches, Thai wrap, text render and stitch
plan.

## The answer on Rust

Not worth it now. Nearly all heavy work already runs in native code (OpenVINO,
ONNX Runtime, numpy/pocketfft, mahotas, Skia, Qt), so a Rust rewrite would not
make it faster. Rust would also add a native build to every release (Windows,
macOS, Linux wheels, PyInstaller, CI). The time goes into **repeated work and
waiting one item at a time**, which Python fixes. The only place Rust might
earn its keep is the spot-heal search (item 4), and only if the algorithmic
fix below is not enough.

## Bottlenecks, largest effect first

| # | Where | Measured | Cause | Fix | Expected |
|---|---|---|---|---|---|
| 1 | LLM OCR (`gpt_ocr.process_image`, OpenRouter/Gemini) | ~1.5 s per block (CLAUDE.md) → ~22 s for a 15-block page | one request per block, in sequence | send 4–6 blocks' requests at once (thread pool; mind rate limits) | ~4–5 s per page |
| 2 | Model checksum on every load (`download.is_downloaded` → `calculate_sha256_checksum`) | LaMa 7 s (hashed **twice** per load), text segmentation 2.5 s, detection/OCR ~1 s each | reads the whole file in 4 KB Python reads on every app start | verify once, store (size, mtime, sha) beside the model, re-hash only when they change; 1 MB reads | 5–10 s off every first use per start |
| 3 | OpenVINO compile on every start (`openvino_cpu.make_cpu_session`, `text_seg_onnx._make_runner`) | LaMa cold 16 s vs warm 2.9 s; text segmentation ~3 s of compile | no compiled-model cache | OpenVINO `CACHE_DIR` under the models folder (keep `CPU_CONFIG` f32) | several seconds per start; to be measured |
| 4 | Spot healing brush / Smart Fill "heal" (`core/spot_heal.py`) | 3.9 s for one 400×40 stroke (136 tiles, 3 808 FFTs, 72% in pocketfft) | the search area's FFT is recomputed for every tile although every tile of a part searches the same area | FFT the search area once per part and reuse it per tile | 3–5× (estimate) |
| 5 | Text segmentation on tall pages (`text_seg_onnx.tile_rows`) | ~0.8 s per window; 3600 px page = 5 calls = 4.5 s | one inference call per window | batch the windows into one call, or fewer/larger windows where quality allows (see CLAUDE.md on judging by the cleaned page) | some; to be measured |
| 6 | First Thai wrap (pythainlp dictionary trie) | 0.6–1.2 s once, then ~0.1 ms | dictionary loaded on first use | warm it on a background thread at start | invisible to the user |
| 7 | Automatic mode runs pages strictly in sequence | network-bound | the CPU idles while a page waits for translation | detect/OCR page N+1 while page N is translated (pipelining) | largest change; do last |

## Already fast enough (same run)

Detection 0.4 s, local OCR 0.2 s, mask 0.3 s, AOT 1.0 s (warm), Smart Fill on
white bubbles 0.3 s, patches + denoise 0.01 s, stitch plan 0.04 s, text render
0.2 s, opening the app ~2.7 s (1.1 s of it Skia's first font collection).

## How to re-measure

Time each stage with `time.perf_counter()` and profile it with `cProfile`
(`sort_stats("tottime")`), on the demo page from
`scripts/build_readme_images.py` (`_blocks_from_cache`, the same `_Settings`
stand-in) and on a stacked webtoon page. Run every stage twice: the first run
includes loading, checksums and compiling, the second shows the steady state.
