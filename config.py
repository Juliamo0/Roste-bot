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
