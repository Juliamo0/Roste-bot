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


def _parse_id_list(env_var_name: str) -> list:
    """แปลงค่า env แบบ 'id1, id2, id3' เป็น list[int] — พิมพ์ id ผิด (มีตัวอักษรปน) เดิมจะ
    crash ด้วย ValueError เปล่าๆ ไม่บอกว่าผิดตรงไหน/ตัวไหน ตอนนี้บอกชื่อ env var + ค่าที่ผิดชัดเจน"""
    raw = os.getenv(env_var_name, "")
    result = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            result.append(int(piece))
        except ValueError:
            raise ValueError(
                f"ตั้งค่า {env_var_name} ใน .env ผิดรูปแบบ — {piece!r} ไม่ใช่ตัวเลข "
                f"(ต้องเป็น Discord user/guild ID คั่นด้วย , เช่น 111111111111111111,222222222222222222)"
            ) from None
    return result


PRINT_ALLOWED_USER_IDS = _parse_id_list("PRINT_ALLOWED_USER_IDS")
ALLOWED_GUILD_IDS = _parse_id_list("ALLOWED_GUILD_IDS")
# คนที่ DM บอทได้ — ไม่ตั้งไว้ (list ว่าง) = เปิดรับทุกคน (เดิม ไม่กระทบของเก่า)
# ALLOWED_GUILD_IDS ไม่คุม DM เลย — ถ้าจะเปิดบอทเข้า server สาธารณะ ควรตั้งค่านี้ไว้ด้วย
DM_ALLOWED_USER_IDS = _parse_id_list("DM_ALLOWED_USER_IDS")

# ชื่อเครื่องพิมพ์ (ต้องตรงกับใน Settings > Printers & scanners ของ Windows) — ไม่ตั้งใน .env
# = ใช้ค่า default นี้ (เครื่องพิมพ์ที่ตั้งไว้ตอนแรก) คนอื่น clone ไปใช้เครื่องอื่นตั้งผ่าน .env แทนได้เลย
PRINTER_NAME = os.getenv("PRINTER_NAME", "Canon E3300 series")
