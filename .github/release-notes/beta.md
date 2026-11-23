**ตัวทดลอง (test build)** — ยังไม่ใช่รุ่นจริง แอปจะไม่เสนอให้อัปเดตเป็นตัวนี้ และใช้การตั้งค่า คลังคำศัพท์ และโมเดลชุดเดียวกับรุ่นที่ใช้อยู่ · A test build, not a release: the app never offers it as an update, and it shares your settings, glossaries and models with the installed version.

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

- ลากแผงออกมาเป็นหน้าต่างลอย จัดใหม่ แล้วปิด-เปิดแอปว่าจำตำแหน่งได้ · Float and rearrange panels, then restart.
- เมนูฟอนต์กับฟอนต์ไทยที่ใช้งานจริง (ฟอนต์ไทยส่วนใหญ่ไม่บอกหมวด จะอยู่ใน "ทุกหมวด") · The font menu with your Thai fonts (most declare no class and show under All Classes).
- คีย์ลัดเครื่องมือขณะใช้แป้นพิมพ์ภาษาไทยบน Windows (ยังไม่ได้ทดสอบ อาจต้องสลับเป็นภาษาอังกฤษ) · Tool keys with a Thai keyboard layout on Windows (not yet tested).
