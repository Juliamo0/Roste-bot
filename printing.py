# ============================================================
#  🖨️  ระบบพิมพ์ PDF — ดาวน์โหลดไฟล์จาก Discord แล้วสั่งพิมพ์
#  (แยกออกมาเป็นไฟล์ของตัวเอง เพื่อให้แก้/ดีบักง่าย)
#  วิธีใช้จาก bot.py:  import printing  แล้วเรียก printing.start_print_request(...)
# ============================================================
import os
import re
import asyncio

# ---------- ⚙️ ตั้งค่าระบบพิมพ์ (แก้ตรงนี้) ----------
# โหมดพิมพ์: False = "จำลอง" (ไม่สั่งเครื่องจริง แค่หน่วงเวลา+แจ้งสถานะ ไว้ทดสอบ)
#            True  = "ของจริง" (สั่ง SumatraPDF พิมพ์จริง)
PRINT_REAL_MODE = True

# ชื่อเครื่องพิมพ์ (ใส่ให้ตรงกับใน Settings > Printers & scanners)
PRINTER_NAME = "Canon E3300 series"

# เกณฑ์ "งานใหญ่" ที่ต้องให้ยืนยันก่อนพิมพ์
MAX_COPIES_NO_CONFIRM = 5      # เกินกี่ชุดต้องยืนยัน
MAX_PAGES_NO_CONFIRM = 20      # ไฟล์เกินกี่หน้าต้องยืนยัน

# โฟลเดอร์เก็บไฟล์ที่ดาวน์โหลดมาจาก Discord เพื่อพิมพ์
PRINT_DIR = "print_jobs"

# คำที่สื่อว่าผู้ใช้อยากให้พิมพ์
PRINT_TRIGGERS = ("พิมพ์", "ปริ้น", "ปริ๊น", "ปลิ้น", "print", "ปรินต์")

# ---------- สถานะภายใน ----------
print_lock = asyncio.Lock()       # ล็อกตอนกำลังพิมพ์ (พิมพ์ได้ทีละงาน)
pending_prints = {}               # user_id -> งานที่รอ "ยืนยัน" (กรณีงานใหญ่)


def find_sumatra():
    """หาที่อยู่ SumatraPDF ในเครื่อง (ใช้สั่งพิมพ์เงียบ ไม่เด้งหน้าต่าง)"""
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local, "SumatraPDF", "SumatraPDF.exe"),
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def get_printer_status(printer):
    """เช็คว่าเครื่องพิมพ์ "พร้อมรับงาน" ไหม ผ่าน win32print
    คืน (พร้อมไหม, ข้อความปัญหา)

    หมายเหตุสำคัญ: เครื่องพิมพ์บ้านหลายรุ่น (รวม Canon E3300) ไม่รายงาน
    'กระดาษหมด/หมึกหมด' ให้ Windows — เลยเช็คได้แค่ระดับ ออฟไลน์/หยุด/error
    ส่วน 'กระดาษหมด' จะจับทางอ้อมตอนงานค้างคิว (timeout) แทน"""
    import win32print
    try:
        h = win32print.OpenPrinter(printer)
    except Exception:
        return False, f"เปิดเครื่องพิมพ์ '{printer}' ไม่ได้ — เครื่องอาจไม่ได้ต่ออยู่ หรือชื่อไม่ตรง"
    try:
        info = win32print.GetPrinter(h, 2)
        attributes = info.get("Attributes", 0)
    except Exception:
        return True, ""   # อ่านไม่ได้ ก็ปล่อยให้ลองพิมพ์
    finally:
        win32print.ClosePrinter(h)

    status = info.get("Status", 0)

    # 1) เช็ค "ออฟไลน์" — ดูทั้ง Status flag และ Attributes (work offline)
    offline_flag = getattr(win32print, "PRINTER_STATUS_OFFLINE", 0)
    attr_offline = getattr(win32print, "PRINTER_ATTRIBUTE_WORK_OFFLINE", 0)
    if (offline_flag and (status & offline_flag)) or (attr_offline and (attributes & attr_offline)):
        return False, "เครื่องพิมพ์ออฟไลน์อยู่ (เครื่องปิด/ไม่ได้เชื่อมต่อ หรือถูกตั้งเป็นใช้งานออฟไลน์)"

    # 2) ปัญหาระดับที่อ่านได้จริง (ถ้าเครื่องรายงานมา)
    checks = [
        ("PRINTER_STATUS_PAUSED", "เครื่องพิมพ์ถูกหยุดชั่วคราว (paused)"),
        ("PRINTER_STATUS_PAPER_JAM", "กระดาษติด"),
        ("PRINTER_STATUS_PAPER_OUT", "กระดาษหมด"),
        ("PRINTER_STATUS_NO_TONER", "หมึกหมด"),
        ("PRINTER_STATUS_DOOR_OPEN", "ฝาเครื่องพิมพ์เปิดอยู่"),
        ("PRINTER_STATUS_USER_INTERVENTION", "เครื่องพิมพ์ต้องการให้ไปจัดการที่เครื่อง"),
        ("PRINTER_STATUS_ERROR", "เครื่องพิมพ์มีข้อผิดพลาด"),
        ("PRINTER_STATUS_NOT_AVAILABLE", "เครื่องพิมพ์ใช้งานไม่ได้ตอนนี้"),
    ]
    for name, desc in checks:
        flag = getattr(win32print, name, 0)
        if flag and (status & flag):
            return False, desc

    return True, ""


def _wait_print_done(printer, timeout=120):
    """รอจนคิวงานพิมพ์ของเครื่องนี้ว่าง (= พิมพ์เสร็จจริง)
    คืน True ถ้าพิมพ์เสร็จ, False ถ้าครบเวลาแล้วงานยังค้างคิว (น่าจะติดขัด)"""
    import win32print
    import time
    start = time.time()
    seen_job = False
    while time.time() - start < timeout:
        try:
            h = win32print.OpenPrinter(printer)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
        except Exception:
            return True   # อ่านคิวไม่ได้ ก็ถือว่าจบ (ไม่ค้าง)
        cjobs = info.get("cJobs", 0)
        if cjobs > 0:
            seen_job = True          # งานเข้าคิวแล้ว
        elif seen_job:
            return True              # เคยมีงาน ตอนนี้คิวว่าง = พิมพ์เสร็จ
        time.sleep(1)
    # ครบเวลาแล้วงานยังค้าง = น่าจะกระดาษหมด/ติดขัด
    return not seen_job  # ถ้าไม่เคยเห็นงานเลย ถือว่าผ่าน (พิมพ์เร็วมาก), ถ้าเห็นแล้วค้าง = False


def print_pdf_windows(path, copies, printer):
    """สั่งพิมพ์จริงด้วย SumatraPDF (เงียบ ไม่เด้งหน้าต่าง ปิดเอง)
    เช็คสถานะก่อน → สั่งพิมพ์ → รอคิวว่างจริง → เช็คสถานะอีกที
    คืน (สำเร็จไหม, ข้อความ error)"""
    import subprocess
    exe = find_sumatra()
    if not exe:
        return False, "หาโปรแกรม SumatraPDF ในเครื่องไม่เจอ (ลองติดตั้งใหม่)"

    # 1) เช็คสถานะเครื่องพิมพ์ก่อนเริ่ม (กระดาษหมด/ออฟไลน์ ฯลฯ)
    ok, problem = get_printer_status(printer)
    if not ok:
        return False, problem

    # 2) สั่งพิมพ์เงียบ — Sumatra ตั้งจำนวนชุดได้ในคำสั่งเดียว (ผ่าน -print-settings)
    #    -print-to <ชื่อเครื่อง>  -silent  -print-settings "<copies>x"  -exit-when-done
    try:
        subprocess.Popen([
            exe,
            "-print-to", printer,
            "-print-settings", f"{copies}x",
            "-silent",
            "-exit-when-done",
            path,
        ])
    except Exception as e:
        return False, f"สั่งพิมพ์ไม่สำเร็จ: {type(e).__name__}"

    # 3) รอจนคิวงานพิมพ์ว่างจริง (= พิมพ์เสร็จ)
    done = _wait_print_done(printer, timeout=180)
    if not done:
        # งานค้างคิวจนหมดเวลา — เครื่องนี้อ่านสถานะกระดาษ/หมึกไม่ได้
        # เลยแจ้งแบบไม่เดาสาเหตุเป๊ะ ให้ไปเช็กที่เครื่อง
        return False, ("งานค้างอยู่ในคิวนานผิดปกติ พิมพ์ไม่ออก "
                       "ลองเช็กที่เครื่องว่ากระดาษหมด หมึกหมด หรือมีไฟกะพริบเตือนไหมนะคะ")

    # 4) เช็คสถานะอีกทีเผื่อมีปัญหาเกิดใหม่ (ออฟไลน์ระหว่างพิมพ์)
    ok, problem = get_printer_status(printer)
    if not ok:
        return False, problem

    return True, ""


async def start_print_request(message, user_id, user_name, attachment, text):
    """รับคำสั่งพิมพ์: ดาวน์โหลดไฟล์ นับหน้า เช็คเงื่อนไขยืนยัน แล้วพิมพ์หรือถามยืนยัน"""
    os.makedirs(PRINT_DIR, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", attachment.filename)
    path = os.path.join(PRINT_DIR, f"{user_id}_{safe}")
    try:
        await attachment.save(path)
    except Exception as e:
        await message.reply(f"ขอโทษค่ะ ดาวน์โหลดไฟล์ไม่สำเร็จ ({type(e).__name__}) ลองส่งใหม่นะคะ")
        return

    # นับจำนวนหน้า
    try:
        from pypdf import PdfReader
        pages = len(PdfReader(path).pages)
    except Exception as e:
        await message.reply(f"ขอโทษค่ะ เปิดไฟล์ PDF นี้ไม่ได้ ({type(e).__name__}) "
                            "ไฟล์อาจเสียหรือมีรหัสผ่าน ลองไฟล์อื่นนะคะ")
        return

    # อ่านจำนวนชุดจากข้อความ (เช่น "2 ชุด") ไม่ระบุ = 1 ชุด
    m = re.search(r"(\d+)\s*ชุด", text)
    copies = int(m.group(1)) if m else 1
    copies = max(1, min(copies, 99))

    job = {
        "path": path, "filename": attachment.filename,
        "copies": copies, "pages": pages, "mention": message.author.mention,
    }

    # งานใหญ่เกินเกณฑ์ → ขอยืนยันก่อน
    if copies > MAX_COPIES_NO_CONFIRM or pages > MAX_PAGES_NO_CONFIRM:
        pending_prints[user_id] = job
        await message.reply(
            f"พอดีเห็นว่างานที่ให้พิมพ์ค่อนข้างเยอะอยู่นะคะ {message.author.mention} "
            f"(ไฟล์ {attachment.filename} — {pages} หน้า × {copies} ชุด) "
            "แน่ใจแล้วใช่ไหมคะว่าจะให้รอสเต้พิมพ์งานนี้? พิมพ์ \"ยืนยัน\" ถ้าให้พิมพ์เลยค่ะ"
        )
        return

    await run_print_job(message, job)


async def run_print_job(message, job):
    """ดำเนินการพิมพ์ + ล็อกบอทระหว่างพิมพ์ + แจ้งสถานะ"""
    async with print_lock:
        await message.channel.send(
            f"🖨️ รอสเต้กำลังเริ่มพิมพ์งานของ {job['mention']} นะคะ "
            f"(ไฟล์ {job['filename']} — {job['pages']} หน้า × {job['copies']} ชุด)\n"
            "ระหว่างนี้ขอพิมพ์ให้เสร็จก่อน ยังรับคำสั่งเพิ่มไม่ได้นะคะ เดี๋ยวเสร็จแล้วจะรีบบอกค่ะ"
        )
        try:
            if PRINT_REAL_MODE:
                ok, err = await asyncio.to_thread(
                    print_pdf_windows, job["path"], job["copies"], PRINTER_NAME)
            else:
                # โหมดจำลอง: หน่วงเวลาเสมือนกำลังพิมพ์ (2 วิ/ชุด)
                print(f"   🖨️ [จำลอง] พิมพ์ {job['filename']} × {job['copies']} ชุด ({job['pages']} หน้า)")
                await asyncio.sleep(min(2 * job["copies"], 10))
                ok, err = True, ""
        except Exception as e:
            ok, err = False, f"{type(e).__name__}"

        if ok:
            await message.channel.send(
                f"{job['mention']} พิมพ์งานเสร็จเรียบร้อยแล้วค่ะ มารับงานที่เครื่องพิมพ์ได้เลย "
                "รอสเต้พร้อมรับคำสั่งต่อแล้วนะคะ"
            )
        else:
            await message.channel.send(
                f"{job['mention']} ขอโทษค่ะ พิมพ์ไม่สำเร็จ — {err} "
                "ลองเช็กเครื่องพิมพ์ดูนะคะ รอสเต้กลับมาพร้อมรับงานแล้วค่ะ"
            )
