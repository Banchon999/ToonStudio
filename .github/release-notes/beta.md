**ตัวทดลอง (test build)** — ยังไม่ใช่รุ่นจริง แอปจะไม่เสนอให้อัปเดตเป็นตัวนี้ และใช้การตั้งค่า คลังคำศัพท์ และโมเดลชุดเดียวกับรุ่นที่ใช้อยู่ · A test build, not a release: the app never offers it as an update, and it shares your settings, glossaries and models with the installed version.

## ตัวติดตั้ง Windows / Windows installer

- **`ToonStudio-Setup-x64.exe`** — ติดตั้งได้โดยไม่ต้องใช้สิทธิ์ผู้ดูแลเครื่อง ไฟล์เล็กกว่า zip มาก และ**เลือกได้ตอนติดตั้ง**ว่าจะเอาตัวอ่าน **EasyOCR และ PaddleOCR-VL** ด้วยหรือไม่ ถ้าไม่เลือกก็ไม่ต้องโหลดส่วนที่ใหญ่ (PyTorch) · A Windows installer: no administrator rights needed, much smaller than the zip, and you choose during setup whether to add the EasyOCR and PaddleOCR-VL readers — the large part (PyTorch) is only downloaded if you tick it.
- เปิดตัวติดตั้งซ้ำภายหลังเพื่อเพิ่มหรือเอาสองตัวนี้ออกได้ · Run it again later to add or remove them.
- ตัวอ่านในตัว (PaddleOCR, manga-ocr, Pororo) ยังโหลดโมเดลเองครั้งแรกที่ใช้เหมือนเดิม · The built-in readers still download their models the first time they are used.

## ลบข้อความ / Cleaning

- **Smart Fill แยกงานเป็น 3 แบบ** — ฟองขาวลงสีของฟองก่อน · พื้นเรียบที่ไม่ขาว (ไล่สี กล่องบรรยายมีสี) เติมจากรอบข้างแบบ healing · ส่วนที่มีลวดลายเท่านั้นที่ส่งให้โมเดล · Smart Fill paints white bubbles in their own colour first, heals smooth backgrounds from their surroundings, and sends only textured areas to the model.
- **Healing brush เร็วขึ้นราว 4 เท่า** และพื้นที่กว้างได้ผลถูกต้องขึ้น · The healing brush is about four times faster and settles wide areas properly.

## อ่านข้อความ / OCR

- **กด OCR ซ้ำหลัง Clean ได้แล้ว** — เดิมกดแล้วไม่เกิดอะไร ต้องกดย้อน ตอนนี้กรอบกลับมาเองและอ่านจากภาพต้นฉบับ · การกดซ้ำคืออ่านใหม่จริง ไม่ใช่คืนผลเก่า · อ่านใหม่ทีละกรอบได้ · OCR works again after Clean (it used to do nothing), pressing it again really reads again, and one box can be re-read on its own.

## ตัวอักษร / Text

- **เส้นขอบหนาไม่แตกแล้ว** — เดิมเกิน 10 จะเป็นเงาซ้อนและมีรู โดยเฉพาะกับฟอนต์ที่นำเข้าเอง ตอนนี้เป็นเส้นทึบมุมมนทุกความหนา · Thick text outlines are solid at any width; over about 10 they used to break into ghost copies, above all with imported fonts.
- **ความกว้างตัวอักษร (%)** — บีบตัวอักษรให้ใส่ฟองแคบได้โดยไม่ต้องลดขนาด · Horizontal scale: condense the letters to fit a narrow bubble at full height.

## เลเยอร์ / Layers

- **Alt+คลิกที่รูปตา** แสดงเฉพาะเลเยอร์นั้น คลิกอีกครั้งกลับมาครบ · คลิกขวาที่แถวมีเมนู ซ่อน/ล็อก/เปลี่ยนชื่อ/ลบ · Alt+click an eye to show that layer alone; right-click a row for hide, lock, rename, delete.

## กู้งานเมื่อแอปหลุด / Crash recovery

- **กู้งานแล้วไฟล์กู้คืนยังอยู่** จนกว่าจะบันทึกจริง หลุดซ้ำก็ไม่เสียงาน · งานที่กู้กลับไปเป็นไฟล์โปรเจกต์เดิม · เปิดแอปด้วยการดับเบิลคลิกโปรเจกต์หลังแอปหลุด จะถามเรื่องกู้งานก่อน · A restored project keeps its recovery copy until it is really saved, comes back as its own project file, and opening a project after a crash offers the recovery first.

## แก้ไขจาก 3.3.0 / Fixes since 3.3.0

- **บันทึกโปรเจกต์ได้แล้ว** — 3.3.0 บันทึกหน้าที่แปลแบบ batch ไม่ได้ · Saving a project with batch-translated text failed in 3.3.0; it works again.
- **ออโต้เซฟที่ล้มเหลวไม่ทำให้งานหายเงียบอีก** · A failed auto-save no longer counts as a save, and you are told.
- **แปรงลงสีไม่หน่วงตอนปล่อยเมาส์** · The paint brush no longer stalls on release.

## ดาวน์โหลด / Download

| | |
|---|---|
| **Windows 10/11 (64-bit) — ตัวติดตั้ง / installer** | **`ToonStudio-Setup-x64.exe`** — ไฟล์เล็กกว่า zip มาก ตอนติดตั้งเลือกได้ว่าจะเอา EasyOCR และ PaddleOCR-VL ด้วยหรือไม่ (ถ้าเลือก ตัวติดตั้งจะดาวน์โหลดเพิ่มเอง) / much smaller than the zip; tick EasyOCR and PaddleOCR-VL during setup and it downloads them |
| Windows 10/11 (64-bit), zip | `ToonStudio-Windows-x86_64.zip` — แตกไฟล์แล้วเปิด `ToonStudio.exe` / unzip and run `ToonStudio.exe` |
| Windows 10/11 (64-bit), zip Full | `ToonStudio-Windows-x86_64-full.zip` — ตัวปกติ + EasyOCR + PaddleOCR-VL / the regular app plus EasyOCR and PaddleOCR-VL |
| Linux (x86_64) | `ToonStudio-Linux-x86_64.tar.gz` — แตกไฟล์แล้วรัน `./ToonStudio/ToonStudio` |
| macOS 15+ (Apple Silicon) | `ToonStudio-macOS-arm64.dmg` — เปิดไฟล์แล้วลาก Toon Studio ไปที่ Applications / open it and drag Toon Studio to Applications |

`ToonStudio-ocr-pack-x64.zip` เป็นไฟล์ที่ตัวติดตั้งดาวน์โหลดเอง ไม่ต้องโหลดแยก · `ToonStudio-ocr-pack-x64.zip` is what the installer downloads; you do not need it yourself.

**Windows:** ตัวติดตั้งยังไม่ได้เซ็นรับรอง ครั้งแรก Windows อาจขึ้น "Windows protected your PC" ให้กด **More info → Run anyway** · The installer is not code-signed; if Windows shows "Windows protected your PC", click **More info → Run anyway**.

**macOS:** ครั้งแรกที่เปิดให้ไปที่ System Settings → Privacy & Security แล้วกด **Open Anyway** · The first time, go to System Settings → Privacy & Security and click **Open Anyway** (the app is not notarised by Apple).

เจอปัญหาแจ้งได้ในแชตกับ Claude หรือเปิด issue · Report problems in the chat or open an issue.
