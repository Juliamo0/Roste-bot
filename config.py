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

# Ollama — ไม่บังคับตั้งใน .env เปลี่ยนเครื่อง/เปลี่ยนโมเดลได้โดยไม่ต้องแก้โค้ด
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# โมเดลสำหรับ "สกัดข้อเท็จจริงลงความจำ" (chat.auto_remember) — แยกจากโมเดลหลักโดยตั้งใจ
#
# ทำไมต้องแยก: วัดกับชุดทดสอบ 80 เคส 10 กลุ่มข้อมูลแล้วพบว่างานสกัดกับงานแชตต้องการ
# คนละคุณสมบัติ — โมเดลใหญ่ "อนุรักษ์นิยม" เกินไปสำหรับงานสกัด (qwen3:8b คืน [] 29/80 เคส
# ตัดสินเองว่าไม่มีอะไรน่าจำ ทิ้งข้อมูลอย่าง "ลูกคนเล็ก 3 ขวบ" "อายุ 32" "ยังโสด")
#
#   qwen3:8b    51/80 (64%)  แต่งเรื่อง 0%   0.9s   <- โมเดลหลัก เก่งแชต/tool-calling
#   qwen3:14b   58/80 (73%)  แต่งเรื่อง 0%   1.1s   <- ใหญ่กว่าแต่แย่กว่า 12b
#   qwen3:1.7b  75/80 (94%)  แต่งเรื่อง 41%  0.7s   <- แต่งเรื่องเยอะเกินรับได้
#   gemma3:12b  71/80 (89%)  แต่งเรื่อง 0%   1.9s   <- ดี แต่ 8.1GB
#   qwen3:4b    71/80 (89%)  แต่งเรื่อง 0%   0.8s   <- เท่า 12b แต่เล็กกว่า 2.5 เท่า ✅
#
# ⚠️ qwen3:4b ต้องใช้คู่กับ format:json เท่านั้น (ดู EXTRACT_FORMAT_JSON) ไม่งั้นมันจะ
# "คิดออกเสียง" ก่อนตอบทุกครั้ง (เขียนลง content 1,022 tokens) ทำให้ช้า 13-30s ต่อ call
#
# ไม่แตะ OLLAMA_MODEL เพราะตัวนั้นใช้ร่วมกับ chat/tool-calling/rerank/summarize ซึ่งมี
# ผลวัดรองรับอยู่แล้ว (tool accuracy 100%, persona guard, rerank temperature 0)
OLLAMA_EXTRACT_MODEL = os.getenv("OLLAMA_EXTRACT_MODEL", "qwen3:4b")

# บังคับ constrained decoding ตอนสกัด — ข้ามการ "คิดออกเสียง" ของโมเดลตระกูล reasoning
# ตั้ง OLLAMA_EXTRACT_FORMAT_JSON=0 เพื่อปิด (ถ้าเปลี่ยนไปใช้โมเดลที่ไม่ต้องการ)
EXTRACT_FORMAT_JSON = os.getenv("OLLAMA_EXTRACT_FORMAT_JSON", "1").strip() != "0"

# หน้าเฝ้าดูสถานะบอท (monitor.py) — localhost-only by default, ตั้ง MONITOR_PORT=0 เพื่อปิด
# ทั้งหมด, MONITOR_HOST เปลี่ยนได้ถ้าอยากดูจากมือถือใน LAN (ระวัง: ไม่ auth เลย เปิดวงกว้างเอง)
MONITOR_HOST = os.getenv("MONITOR_HOST") or "127.0.0.1"
# ค่าว่าง (MONITOR_PORT= เปล่าๆ ใน .env ตามที่ .env.example ใส่ไว้ให้) ต้องถือว่า "ไม่ตั้ง" =
# ใช้ default เหมือน os.getenv คืน None ไม่งั้น int("") จะ raise ValueError ทั้งที่ user ไม่ได้
# พิมพ์อะไรผิดเลย แค่ปล่อยว่างไว้ตามตัวอย่าง
_monitor_port_raw = os.getenv("MONITOR_PORT", "").strip()
if not _monitor_port_raw:
    MONITOR_PORT = 8765
else:
    try:
        MONITOR_PORT = int(_monitor_port_raw)
    except ValueError:
        raise ValueError(
            f"ตั้งค่า MONITOR_PORT ใน .env ผิดรูปแบบ — {_monitor_port_raw!r} ไม่ใช่ตัวเลข "
            f"(ต้องเป็นเลขพอร์ต เช่น 8765 หรือ 0 เพื่อปิด monitor ทั้งหมด)"
        ) from None


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
