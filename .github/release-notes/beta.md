**ตัวทดลอง (test build)** — ยังไม่ใช่รุ่นจริง แอปจะไม่เสนอให้อัปเดตเป็นตัวนี้ และใช้การตั้งค่า คลังคำศัพท์ และโมเดลชุดเดียวกับรุ่นที่ใช้อยู่ · A test build, not a release: the app never offers it as an update, and it shares your settings, glossaries and models with the installed version.

## คลังคำศัพท์ของทีม / Team glossary

- **แชร์คลังคำศัพท์กับทีมผ่าน Google Sheet** — ตั้งค่า > คลังคำศัพท์ > ทีม: **ตั้งค่า…** แล้วกด **ซิงก์กับทีม** วิธีตั้ง Google Sheet อยู่ใน [docs/glossary-sync.md](https://github.com/Banchon999/ToonStudio/blob/claude/text-canvas-architecture-794fyh/docs/glossary-sync.md) · Share a series glossary with your team through a Google Sheet: Settings > Glossary > Team: **Set Up…**, then **Sync with Team**.
- คำที่แก้ฝั่งเดียวใช้ตามนั้น · คำแปลตรงกันรวมให้เอง · คำแปลต่างกันให้ AI ตัวแปลตัดสิน · เพศไม่ตรงกันให้คนเลือก · A term changed on one side is taken; the same translation on both sides is combined; different translations are settled by the AI translator; different genders are for a person to choose.

## หน่วยความจำ / Memory

- **เว็บตูนยาวไม่กินแรมสะสมอีก** — เลื่อนดู 40 หน้า (800×5000) เคยค้างทุกหน้าในหน่วยความจำ (+537 MB) ตอนนี้เก็บแค่ไม่กี่หน้า (+190 MB) · Scrolling a long webtoon no longer keeps every page in memory.
- **Smart Workflow ทั้งเรื่องไม่ค้างทุกหน้าในแรม** — 60 หน้า จาก 641 MB เหลือ 334 MB · Smart Workflow over a whole chapter no longer holds every page.
- นำเข้า PSD หลายไฟล์เก็บในแรมแค่หน้าที่เปิดอยู่ · Importing many PSDs keeps only the page on screen in memory.

## ดาวน์โหลด / Download

| | |
|---|---|
| Windows 10/11 (64-bit) | `ToonStudio-Windows-x86_64.zip` — แตกไฟล์แล้วเปิด `ToonStudio.exe` / unzip and run `ToonStudio.exe` |
| Linux (x86_64) | `ToonStudio-Linux-x86_64.tar.gz` — แตกไฟล์แล้วรัน `./ToonStudio/ToonStudio` |
| macOS 15+ (Apple Silicon) | `ToonStudio-macOS-arm64.dmg` — เปิดไฟล์แล้วลาก Toon Studio ไปที่ Applications / open it and drag Toon Studio to Applications |

**macOS:** ครั้งแรกที่เปิดให้ไปที่ System Settings → Privacy & Security แล้วกด **Open Anyway** · The first time, go to System Settings → Privacy & Security and click **Open Anyway** (the app is not notarised by Apple).

เจอปัญหาแจ้งได้ที่ PR [#74](https://github.com/Banchon999/ToonStudio/pull/74) · Problems with this build: PR #74.
