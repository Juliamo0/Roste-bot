# ============================================================
#  🔑  โหลดค่าลับจาก .env — ไฟล์นี้เองไม่มีค่าลับ ปลอดภัยที่จะ commit
# ------------------------------------------------------------
#  วิธีใช้: คัดลอก .env.example → .env แล้วใส่ค่าจริงในนั้น
#  (.env ถูกกันไม่ให้ขึ้น GitHub ผ่าน .gitignore — ไฟล์นี้ config.py ไม่ต้องกันแล้ว)
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
TMD_TOKEN = os.getenv("TMD_TOKEN", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

_print_ids_raw = os.getenv("PRINT_ALLOWED_USER_IDS", "")
PRINT_ALLOWED_USER_IDS = [
    int(uid.strip()) for uid in _print_ids_raw.split(",") if uid.strip()
]

_guild_ids_raw = os.getenv("ALLOWED_GUILD_IDS", "")
ALLOWED_GUILD_IDS = [
    int(gid.strip()) for gid in _guild_ids_raw.split(",") if gid.strip()
]

# คนที่ DM บอทได้ — ไม่ตั้งไว้ (list ว่าง) = เปิดรับทุกคน (เดิม ไม่กระทบของเก่า)
# ALLOWED_GUILD_IDS ไม่คุม DM เลย — ถ้าจะเปิดบอทเข้า server สาธารณะ ควรตั้งค่านี้ไว้ด้วย
_dm_ids_raw = os.getenv("DM_ALLOWED_USER_IDS", "")
DM_ALLOWED_USER_IDS = [
    int(uid.strip()) for uid in _dm_ids_raw.split(",") if uid.strip()
]

# ชื่อเครื่องพิมพ์ (ต้องตรงกับใน Settings > Printers & scanners ของ Windows) — ไม่ตั้งใน .env
# = ใช้ค่า default นี้ (เครื่องพิมพ์ที่ตั้งไว้ตอนแรก) คนอื่น clone ไปใช้เครื่องอื่นตั้งผ่าน .env แทนได้เลย
PRINTER_NAME = os.getenv("PRINTER_NAME", "Canon E3300 series")
