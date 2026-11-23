**ตัวทดลอง (test build)** — ยังไม่ใช่รุ่นจริง แอปจะไม่เสนอให้อัปเดตเป็นตัวนี้ และใช้การตั้งค่า คลังคำศัพท์ และโมเดลชุดเดียวกับรุ่นที่ใช้อยู่ · A test build, not a release: the app never offers it as an update, and it shares your settings, glossaries and models with the installed version.

## ใหม่ตั้งแต่ beta.28 / Since beta.28

- **OCR เกาหลีตัวใหม่: Hayai (Korean)** — ตั้งค่า › เครื่องมือ › OCR › Hayai (Korean) อ่านทั้งกล่องในครั้งเดียว บนหน้าทดสอบเกาหลีอ่านผิด 0% (ตัวเดิม 10.7%) ตรงทั้งกล่อง 31 จาก 32 (ตัวเดิม 6) แม่นพอ ๆ กับ Gemini แต่ฟรีและไม่ต้องต่อเน็ต ใช้ครั้งแรกดาวน์โหลดประมาณ 265 MB ใช้กับหน้าเกาหลีเท่านั้น หน้าภาษาอื่นใช้ตัวอ่านเดิม · Hayai OCR for Korean pages: 0% Hangul error against 10.7% on the test pages, free and offline.
- **ตัวแยกพิกเซลตัวอักษรแบบใหม่: comic-text-mask** — ตั้งค่า › เครื่องมือ › โมเดลแยกพิกเซลตัวอักษร อ่านทีละกล่องข้อความ ใช้แรมน้อยกว่า (~150 MB เทียบ ~420 MB) และเร็วกว่า บนหน้าทดสอบลบข้อความบนลายภาพได้หมด (ตัวเดิมเหลือ 3 ตัวอักษร) ค่าเริ่มต้นยังเป็นตัวเดิม · comic-text-mask as a lighter text segmentation choice; it removed the text the default left on the test pages.
- **ใช้แรมน้อยลง** — คืนแรมของโมเดล AI อัตโนมัติเมื่อไม่ได้ใช้งาน 3 นาที (ตั้งค่า › เครื่องมือ ปิดได้) และ LaMa ไม่กินแรมสะสมจนเครื่องค้างแล้ว เหมาะกับเครื่อง 8 GB ที่เปิดเพลงหรือเบราว์เซอร์ไปด้วย · Uses less memory: models are freed after 3 idle minutes, and LaMa no longer piles up memory.

## แก้จาก beta.27 (อยู่ใน beta.28 แล้ว) / Since beta.27

- **ไล่สีเฉพาะคำที่เลือก** — เลือกคำในช่องคำแปล (หรือบนภาพ) แล้วคลิกไล่สีในแผงไล่สี หรือเปิดสวิตช์ไล่สีในสไตล์เลเยอร์ จะไล่สีเฉพาะคำนั้น ไม่เลือกคำ = ไล่ทั้งข้อความเหมือนเดิม · A gradient on just the picked words, from the Gradients panel or the Layer Style switch.
- **เลือกคำครั้งเดียวปรับได้หลายอย่าง** — เดิมเปลี่ยนได้ครั้งเดียวแล้วคำที่เลือกหาย · Picked words stay picked for several changes.
- **หน้าต่างแผงที่ลากออกมาแสดงเฉพาะหน้า editor** — ไม่ค้างทับหน้าตั้งค่าหรือหน้าแรกแล้ว และเปิดแอปใหม่จะกลับมาที่เดิมเมื่อเข้าหน้า editor · Floating panels show on the editor page only, and come back where they were after a restart.
- **ส่งออกเป็นโฟลเดอร์: ชื่อโฟลเดอร์ = ชื่อตอน** (ชื่อโฟลเดอร์ต้นทางของรูป) แล้วรูปอยู่ข้างใน — เดิมได้ชื่อโปรเจกต์หรือ "001" · Export › Images (Folder) names each chapter folder after the folder its images came from.

## แผงแบบ Photoshop / Photoshop-style panels

- **ทุกแผงเป็นหน้าต่างลากออกได้** — ข้อความ, คลังคำศัพท์, ตัวอักษร, ย่อหน้า, สไตล์เลเยอร์, สี, ไล่สี และเลเยอร์ ลากหัวแผงออกมาเป็นหน้าต่างลอย ปรับขนาดได้ หรือวางทับแผงอื่นให้เป็นแท็บรวมกัน ปุ่มแผงบนแถบด้านบนใช้เปิด/ปิดแต่ละแผง และ **จัดแผงกลับค่าเริ่มต้น** ตำแหน่งจำไว้ให้ครั้งหน้า · Every panel can float as its own resizable window or be tabbed with another; the panels button shows, hides and resets them, and the layout is remembered.
- **เมนูฟอนต์แบบ PhotoCraft** — ตัวอย่างข้อความที่เลือกด้วยฟอนต์ที่ชี้อยู่ แยกหมวด (Serif, Sans Serif, ลายมือ…) ฟอนต์โปรด (★) และค้นหา เลือกแล้วเปลี่ยนเฉพาะเลเยอร์ที่เลือก (เลือกหลายเลเยอร์ในแผงเลเยอร์ได้) · A font menu with a live preview, classes, favourites and search; it changes the selected layers only.
- **ตัวอักษร:** ตัวพิมพ์ใหญ่ทั้งหมด, ตัวพิมพ์ใหญ่ขนาดเล็ก, ตัวยก, ตัวห้อย, ขีดฆ่า · **ย่อหน้า:** จัดชิดสองข้าง, เยื้องซ้าย/ขวา, เยื้องบรรทัดแรก, เว้นก่อน/หลังย่อหน้า · Character: all caps, small caps, superscript, subscript, strikethrough. Paragraph: justify, indents and spacing.
- **แผงสี** — เลือกสีจากช่องสีและแถบเฉดสี หรือพิมพ์ hex/RGB ตั้งได้ทั้งสีตัวอักษรและสีเส้นขอบ เห็นผลสด ๆ บนเลเยอร์ที่เลือกขณะลาก ปล่อยเมาส์ = ย้อนกลับได้ในครั้งเดียว มีสีที่ใช้ล่าสุดเก็บไว้ · A Color panel for fill and stroke, live on the selected layers, one undo step per drag.
- **แผงไล่สี** — ไล่สีสำเร็จรูปแยกโฟลเดอร์ตามโทน คลิกเดียวใส่ให้เลเยอร์ที่เลือก กลับด้านได้ และ "+" บันทึกไล่สีของตัวเองไว้ใน "ไล่สีของฉัน" · A Gradients panel: preset folders, one click, reverse, and your own saved gradients.
- **แผงเลเยอร์** มีภาพย่อของแต่ละเลเยอร์ · The Layers panel shows a thumbnail of each layer.

## ข้อความ / Text

- **เลือกคำในช่องคำแปลด้านขวา** แล้วเปลี่ยนฟอนต์ ขนาด สี ตัวหนา/เอียง/ขีดเส้นใต้ หรือเส้นขอบ เฉพาะคำนั้นได้ · Select words in the translation box to format just those words.
- **ชุดเส้นขอบสำเร็จรูป** (outline preset) — สี ความหนา และเส้นขอบหลายชั้นในคลิกเดียว บันทึกของตัวเองได้ · Outline presets: colour, width and extra strokes in one pick.
- **เรืองแสงรอบตัวอักษร** (Outer Glow) — สี ขนาด และความเข้ม ไปถึงตอนส่งออกและใน PSD ด้วย · Outer glow, also in exports and PSDs.
- **วงหมุนเลือกทิศทาง** สำหรับเงาและไล่สี — ลากเข็มไปทางที่ต้องการ กด Shift เพื่อหมุนทีละ 15° · Direction dials for the shadow and the gradient.

## เครื่องมือและการส่งออก / Tools and export

- **คีย์ลัดเครื่องมือแบบ Photoshop** — V กล่อง, H มือ, T ข้อความ, B แปรง, E ยางลบ, J ซ่อมจุด, S โคลน, G ถังสี, I ดูดสี, M เลือกสี่เหลี่ยม, L บ่วงบาศ, W ไม้กายสิทธิ์ (Shift + คีย์ = สลับเครื่องมือในกลุ่ม), `[` `]` ปรับขนาดแปรง, กด Space ค้างเพื่อเลื่อนภาพ แก้ได้ในตั้งค่า › คีย์ลัด · Photoshop's tool keys, editable in Settings › Shortcuts.
- **ส่งออกเป็นโฟลเดอร์รูป** แยกตามชื่อตอน · Export › Images (Folder), one folder per chapter.
- **หน้าเครดิตหัว/ท้าย** — ตั้งค่า › ส่งออก ใส่รูปหน้าแรกและหน้าสุดท้ายให้ทุกตอนอัตโนมัติ ปรับให้กว้างเท่าหน้าในตอน · Opening and closing credit pages on every exported chapter.
- **โฟลเดอร์ฟอนต์** — ตั้งค่า › การแสดงข้อความ › โฟลเดอร์ฟอนต์ โหลดฟอนต์ทั้งโฟลเดอร์จากเครื่องทุกครั้งที่เปิดแอป ไม่ต้องนำเข้าทีละไฟล์ และฟอนต์ที่นำเข้าไว้จะไม่หายหลังปิดแอปอีกแล้ว · Font folders loaded at every start; imported fonts no longer vanish after a restart.
- **รวมภาพ (Stitch) ทั้งเรื่องในครั้งเดียว** — เลือกโฟลเดอร์เรื่องที่มีโฟลเดอร์ย่อยเป็นแต่ละตอน ระบบจะต่อแต่ละตอนแยกกันลงโฟลเดอร์ตามชื่อตอน · Stitch a whole series folder: each chapter is stitched into its own folder.

## อยากให้ช่วยลอง / Please try

- เลือก **Hayai (Korean)** แล้ว OCR ตอนเกาหลีจริงสักตอน เทียบกับตัวเดิม · Hayai on a real Korean chapter.
- เลือก **comic-text-mask** แล้วลบข้อความหน้าที่ตัวหนังสืออยู่บนลายภาพหรือมีแสงเรือง ว่าดีกว่าหรือแย่กว่าตัวเดิม · comic-text-mask on text over artwork or glowing text.

- ลากแผงออกมาเป็นหน้าต่างลอย จัดใหม่ แล้วปิด-เปิดแอปว่าจำตำแหน่งได้ · Float and rearrange panels, then restart.
- เมนูฟอนต์กับฟอนต์ไทยที่ใช้งานจริง (ฟอนต์ไทยส่วนใหญ่ไม่บอกหมวด จะอยู่ใน "ทุกหมวด") · The font menu with your Thai fonts (most declare no class and show under All Classes).
- คีย์ลัดเครื่องมือขณะใช้แป้นพิมพ์ภาษาไทยบน Windows (ยังไม่ได้ทดสอบ อาจต้องสลับเป็นภาษาอังกฤษ) · Tool keys with a Thai keyboard layout on Windows (not yet tested).
