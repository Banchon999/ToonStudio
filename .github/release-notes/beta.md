**ตัวทดลอง (test build)** — ยังไม่ใช่รุ่นจริง แอปจะไม่เสนอให้อัปเดตเป็นตัวนี้ และใช้การตั้งค่า คลังคำศัพท์ และโมเดลชุดเดียวกับรุ่นที่ใช้อยู่ · A test build, not a release: the app never offers it as an update, and it shares your settings, glossaries and models with the installed version.

## ลบคำเร็วขึ้นบน CPU / Faster cleaning on the CPU

- **AOT และ LaMa ใช้ OpenVINO** — AOT เร็วขึ้นประมาณ 1.4 เท่า (LaMa แทบเท่าเดิม) ผลลัพธ์ต่างจากเดิมไม่เกิน 1 ระดับสี ถ้า OpenVINO มีปัญหาจะกลับไปใช้ ONNX Runtime เอง · AOT and LaMa run on OpenVINO: AOT about 1.4× faster, the same pixels within one grey level.
- **ล็อกความแม่นยำเต็ม (f32)** — ซีพียูบางรุ่นเคยแอบลดความแม่นยำจนภาพเพี้ยน · Full precision everywhere: some CPUs used to drop to bf16 on their own and change the result.
- ทาสีบับเบิลขาวและ Smart Fill เร็วขึ้น ผลเหมือนเดิมทุกพิกเซล · The white-bubble fill and Smart Fill are faster, pixel for pixel the same.

## Smart Fill ไม่ใช้ AI ก็ได้ / Smart Fill without the model

- ตั้งค่า > เครื่องมือ > (เลือก Smart Fill) > **ตัวอักษรบนสกรีนโทนหรือลายภาพ**: ส่งให้ AI (LaMa) · **ซ่อมจุด** (คัดลอกลายจากใกล้ ๆ ไม่ใช้โมเดล) · ปล่อยไว้ให้แก้เอง · Settings > Tools, with Smart Fill selected: send text over texture to LaMa, spot-heal it with no model, or leave it.
- หน้า 180 ตัวอักษรบนสกรีนโทน: AI ~16 วิ, ซ่อมจุด ~2 วิ · On a page of 180 letters over screentone: ~16 s with LaMa, ~2 s with spot heal.

## แปรงซ่อมจุด / Spot healing brush (ใหม่ / new)

- ปุ่มใหม่ในแถบเครื่องมือ ถัดจากแปรงซ่อมภาพ — ระบายทับจุดที่จะลบ แล้วจะเติมด้วยลายที่เข้ากันที่สุดจากบริเวณใกล้ ๆ ในสีของรอบ ๆ ไม่ต้อง Alt+คลิก ไม่ใช้โมเดล · A new tool beside the healing brush: paint over a mark and it is filled with the best-matching texture nearby, in the colour around it. No Alt+click, no model.
- สกรีนโทนและเส้นแรเงากลับมาเหมือนเดิม · Screentone and hatching come back as they were.
- **ข้อจำกัด:** ถ้าจุดที่ลบพาดผ่านขอบของรูปทรง ขอบอาจออกมาเป็นฟันเลื่อย กรณีนี้ใช้แปรง AI ดีกว่า · **Limit:** across the edge of a shape the edge may come back jagged; use the AI brush for that.

## ลายน้ำ / Watermark (ใหม่ / new)

- ตั้งค่า › ส่งออก › **ลายน้ำ**: ใส่ข้อความ รูปโลโก้ หรือทั้งสองอย่าง เลือกตำแหน่งได้ 9 จุด ปรับขนาด ความทึบ เส้นขอบ และระยะจากขอบ มีตัวอย่างให้ดูทันที · Settings › Export › **Watermark**: text, a logo or both, in one of nine positions, with size, opacity, outline and margin, and a live preview.
- ใส่ทุกหน้าตอนส่งออกเท่านั้น (ภาพ, CBZ, PDF, ZIP, คิวหลายตอน, บันทึกหน้าปัจจุบัน) ตัวโปรเจกต์ไม่ถูกแก้ ส่วน PSD จะได้ลายน้ำเป็นเลเยอร์แยกชื่อ "Watermark" ซ่อนหรือย้ายได้ · Stamped on every page at export only; a PSD gets it as its own "Watermark" layer.
- ขนาดคิดเป็นสัดส่วนของความกว้างหน้า ใช้ค่าเดียวได้ทั้งมังงะและเว็บตูนหน้ายาว · Sizes follow the page width, so one setting suits manga and long webtoon pages.

## แก้ไข / Fixed

- **เส้นขอบตัวอักษรหายหลัง Smart Workflow แปะคำ** จนกว่าจะไปขยับตัวอักษร — ตอนนี้แสดงทันที และหน้าที่แปะไว้ด้วยตัวทดลองก่อน (beta.19) จะได้เส้นขอบกลับมาเองเมื่อเปิดหรือส่งออก · Text rendered by Smart Workflow had no outline until it was moved; it now shows at once, and pages rendered with the previous test build get theirs back when opened or exported.

- **แปลแล้วขึ้น error `JSONDecodeError: Expecting ',' delimiter`** — เกิดเมื่อ AI ตอบกลับมาในรูปแบบที่ผิดเล็กน้อย (เช่นมีเครื่องหมายคำพูดในคำแปล) ตอนนี้แอปซ่อมและอ่านได้เอง ถ้าอ่านไม่ได้จริง ๆ จะถาม AI ใหม่อีก 1 ครั้ง และถ้ายังไม่ได้จะบอกเป็นข้อความว่าต้องทำอะไร แทนหน้าต่าง error · A translation reply that is not quite valid JSON is now repaired and read; if it cannot be, the model is asked once more, and a second failure is a plain message instead of a traceback.

- **ลบคำหน้ายาวมากแล้วขึ้น `MemoryError: Unable to allocate 600. MiB`** — การลบคำหนึ่งหน้าขนาด 32767×800 เคยใช้หน่วยความจำถึง ~1.9 GB ตอนนี้ใช้ ~250 MB ผลลัพธ์เหมือนเดิมทุกพิกเซล และเร็วขึ้นเล็กน้อย · Cleaning a very tall page ran out of memory: one 32767×800 page peaked at ~1.9 GB, now ~250 MB, with the same pixels.

## อยากให้ช่วยลอง / Please try

- แปรงซ่อมจุดบนหน้ามังงะ/เว็บตูนจริง โดยเฉพาะตัวอักษรบนสกรีนโทน · The spot healing brush on real pages, especially text over screentone.
- Smart Fill โหมด "ซ่อมจุด" ทั้งหน้า เทียบกับ AOT · Smart Fill's spot-heal mode on a whole page, against AOT.
- ขั้นลบคำ (Clean) บนเครื่องที่ไม่มีการ์ดจอ ว่าเร็วขึ้นแค่ไหน · How much faster Clean is on a machine without a GPU.
