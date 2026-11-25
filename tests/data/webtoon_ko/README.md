# Korean webtoon test pages

Three pages of a Korean webtoon opening ("the Tower"). The project owner made them with an
AI image generator for testing, so no one else's artwork is in the repository and they can
be used in tests, measurements and screenshots freely.

| File | Size | What is on it |
|---|---|---|
| `page_01.png` | 852×1846 | narration boxes, spiky/glowing/dark thought bubbles, an invitation with text, sound effects over art |
| `page_02.png` | 854×1842 | round self-talk bubbles, a blue game-style system window, sound effects |
| `page_03.png` | 810×1941 | round bubbles, a paper invitation with three lines of text and a signature, sound effects |

They are the hard cases a real chapter has: glowing and dark lettering over a busy
purple background (cleaning), sound effects drawn as artwork (detection: lettering or
not?), text inside the art (the invitation, the system window), and bubbles of four
shapes.

## Ground truth: `pages.json`

Every piece of lettering on each page, top to bottom, with its `kind`:
`narration`, `speech`, `thought` (self-talk, inner voice, a line said to no one),
`sfx`, `sign` (text drawn on an object in the scene) or `system`.

- **`text`** is what the page says. Where the generator drew a letter wrong, **`as_drawn`**
  holds what is actually on the page (`돌아오자` for 돌아오지, `이번앤` for 이번엔, `:::` and
  `∴` for an ellipsis). An OCR engine that reads `as_drawn` has read correctly.
- **`uncertain: true`** marks a stylised sound effect whose letters cannot be told
  for sure.
- Every line of dialogue is the male protagonist talking to himself (`speaker`,
  `speakers`), so a Thai translation should use no polite particle (ครับ) on them and
  ฉัน/เรา rather than ผม — the speaker map's `thought` mode is exactly this case.

There are no boxes in the ground truth: they would have been measured by eye. Match
detected blocks to it by reading order or by text.

`tests/test_webtoon_test_pages.py` keeps the images and the ground truth consistent.
