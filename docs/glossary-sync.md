# คลังคำศัพท์ของทีม / Team glossary

แชร์คลังคำศัพท์ของแต่ละเรื่องกับทีมผ่าน Google Sheet แผ่นเดียว ทุกคนกด **ซิงก์กับทีม** ในหน้า ตั้งค่า > คลังคำศัพท์ แล้วคำศัพท์จะรวมกัน

Share each series' glossary with your team through one Google Sheet. Everyone presses **Sync with Team** on Settings > Glossary and the terms merge.

## ตั้งค่าครั้งเดียว (คนเดียวทำ) / One-time setup (one person)

1. สร้าง Google Sheet ใหม่ แล้วแชร์ให้ทีมถ้าอยากให้ทีมเปิดดูหรือแก้ในชีตได้ด้วย (ไม่จำเป็นสำหรับการซิงก์)
2. เปิด **ส่วนขยาย > Apps Script** ลบโค้ดเดิม แล้ววางสคริปต์ในแอป (ตั้งค่า > คลังคำศัพท์ > ตั้งค่า… > **คัดลอกสคริปต์**) หรือจากไฟล์ [`resources/glossary_sync/Code.gs`](../resources/glossary_sync/Code.gs)
3. เปลี่ยน `const TOKEN = 'CHANGE-ME';` เป็นรหัสยาว ๆ ที่เดายาก แล้วบันทึก
4. **การทำให้ใช้งานได้ > การทำให้ใช้งานได้รายการใหม่ > เว็บแอป**
   - เรียกใช้ในฐานะ: **ฉัน**
   - ผู้มีสิทธิ์เข้าถึง: **ทุกคน**
   - กด ทำให้ใช้งานได้ แล้วอนุญาตสิทธิ์ (Google จะเตือนว่าแอปยังไม่ผ่านการยืนยัน ให้กด ขั้นสูง > ไปที่โปรเจกต์ เพราะเป็นสคริปต์ของคุณเอง)
5. ส่ง **URL ของเว็บแอป** (ลงท้ายด้วย `/exec`) และ **โทเค็น** ให้ทุกคนในทีม

แต่ละคนเปิด ตั้งค่า > คลังคำศัพท์ > **ตั้งค่า…** ใส่ URL, โทเค็น และชื่อตัวเอง (ชื่อจะแสดงในคอลัมน์ `updated_by` ข้างคำที่แก้)

1. Create a Google Sheet. Sharing it with the team is optional; it lets them read or edit the rows by hand.
2. Open **Extensions > Apps Script**, replace the code with the script (Settings > Glossary > Set Up… > **Copy Script**, or [`resources/glossary_sync/Code.gs`](../resources/glossary_sync/Code.gs)).
3. Change `const TOKEN = 'CHANGE-ME';` to a long random value and save.
4. **Deploy > New deployment > Web app**, Execute as **Me**, Who has access **Anyone**. Authorise it (Google warns the app is unverified: Advanced > Go to project, since it is your own script).
5. Send everyone the **web app URL** (ending in `/exec`) and the **token**. Each member enters them, and their name, in Settings > Glossary > **Set Up…**.

> **Google Workspace (องค์กร/โรงเรียน):** ผู้ดูแลระบบอาจปิดตัวเลือก "ทุกคน" ไว้ ถ้าเลือกไม่ได้ ให้ใช้บัญชี Gmail ส่วนตัวสร้างชีตแทน · An organisation's admin may not allow "Anyone"; create the sheet with a personal Gmail account instead.

ถ้าแก้สคริปต์ภายหลัง ต้อง Deploy ใหม่: การทำให้ใช้งานได้ > จัดการ > แก้ไข > เวอร์ชัน: ใหม่ (URL เดิม) · After editing the script, deploy again (Manage deployments > edit > Version: New version); the URL stays the same.

## ซิงก์ทำงานอย่างไร / How syncing works

- แต่ละเรื่อง (profile) คือหนึ่งแท็บในชีต ชื่อตามชื่อเรื่อง · Each series is one tab, named after the series.
- เทียบทีละคำ ระหว่าง เครื่องเรา, ชีตของทีม และสถานะตอนซิงก์ครั้งก่อน · Each term is compared three ways: this machine, the team's sheet, and the state at the last sync.
  - แก้ฝั่งเดียว → ใช้ฝั่งที่แก้ · Changed on one side only → that side wins.
  - ลบฝั่งเดียว และอีกฝั่งไม่ได้แก้ → ลบทั้งสองฝั่ง; ถ้าอีกฝั่งแก้ → เก็บไว้ (งานที่แก้ไม่หายเพราะซิงก์) · Deleted on one side and untouched on the other → deleted; edited on the other → kept.
  - แก้ทั้งสองฝั่ง **คำแปลตรงกัน** → รวมกัน (ชื่อเรียกอื่นรวมกัน, เพศ/หมายเหตุที่ว่างเติมจากอีกฝั่ง) · Both changed, **same translation** → combined.
  - แก้ทั้งสองฝั่ง **คำแปลต่างกัน** → ส่งให้ AI ตัวแปลที่เลือกไว้ตัดสิน (AI เห็นแค่ A กับ B ไม่รู้ว่าเป็นของใคร) แล้วผลส่งถึงทุกคน · Both changed, **different translations** → the selected AI translator decides, seeing them only as A and B.
  - **เพศไม่ตรงกัน** (ชาย/หญิง) → ให้คนเลือก เพราะเพศคุม ครับ/ค่ะ และ AI ไม่มีหลักฐานจากแค่แถวในคลัง · **Genders disagree** → a person chooses; gender decides ครับ/ค่ะ and two rows give a model no evidence.
  - ถ้า AI ใช้ไม่ได้ (ไม่ได้เลือกตัวแปล AI, ไม่มีคีย์) คำที่ขัดกันจะรอให้คนเลือก ส่วนคำอื่นซิงก์ตามปกติ · If the AI is unavailable, conflicts wait for a person and the rest syncs.
- แก้ในชีตด้วยมือได้ การซิงก์ครั้งถัดไปจะรับการแก้นั้นมา แต่คอลัมน์ที่เพิ่มเองจะไม่ถูกเก็บ · Hand edits in the sheet are picked up; extra columns are not kept.
- ถ้ามีคนซิงก์พร้อมกัน สคริปต์จะล็อกและให้แอปรวมใหม่กับข้อมูลล่าสุดเอง · Simultaneous syncs are serialised by the script; the app re-merges on the newest rows.
- ใครมี URL และโทเค็นก็อ่านและแก้คลังได้ ส่งให้เฉพาะทีม · Anyone with the URL and the token can read and change the glossary.

## ข้อจำกัด / Limits

Apps Script ฟรีรันพร้อมกันได้ 30 ครั้งต่อผู้ใช้ และครั้งละไม่เกิน 6 นาที ซึ่งเกินพอสำหรับคลังคำศัพท์หลักพันคำ · Apps Script allows 30 simultaneous executions per user and 6 minutes per run — far more than a glossary of a few thousand terms needs. ([quotas](https://developers.google.com/apps-script/guides/services/quotas))
