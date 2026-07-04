"""
🤖 Ollama HTTP client — บาง ทั่วไป ไม่รู้จัก TOOLS/business logic ใดๆ ของบอทเลย

ตั้งใจให้ไม่พึ่งอะไรใน llm_tools.py/chat.py เด็ดขาด (ต่อให้ _chat_once ใช้เรื่องเครื่องมือ
ก็ตาม) เพื่อกัน circular import: llm_tools.py ต้องใช้ _get_json_post/_strip_think/MODEL
จากไฟล์นี้ ถ้าไฟล์นี้ import TOOLS จาก llm_tools.py กลับไปจะเกิด import วนตอน startup —
ผู้เรียก _chat_once ต้องส่ง tools มาเองเสมอถ้าต้องการให้โมเดลเรียกเครื่องมือได้
"""
import aiohttp

OLLAMA_URL = "http://localhost:11434/api/chat"

# โมเดลที่จะใช้ — เปลี่ยนได้ตามเครื่อง
#   qwen3:1.7b = เร็วสุด แต่โง่   |   qwen3:8b = สมดุล   |   qwen3:14b = ฉลาดขึ้นแต่ช้า (บนการ์ด 4GB ~1-2 นาที)
MODEL = "qwen3:8b"


async def _get_json_post(payload, timeout=120):
    async with aiohttp.ClientSession() as s:
        async with s.post(OLLAMA_URL, json=payload, timeout=timeout) as r:
            return await r.json()


def _strip_think(text: str) -> str:
    """ตัด <think>...</think> ที่โมเดลเผลอโชว์ทิ้ง เหลือแค่คำตอบจริงหลัง </think>"""
    if "</think>" in text:
        return text.rsplit("</think>", 1)[-1]
    return text


async def _chat_once(messages, temperature: float = 0.8, tools=None):
    """ยิงคำขอไปที่ Ollama หนึ่งครั้ง แล้วคืน message dict
    temperature ต่ำ (~0.5) = แม่นยำ เดาน้อย (ใช้ตอนตอบข้อมูลจริง)
    temperature สูง (~0.8) = มีชีวิตชีวา (ใช้ตอนคุยเล่น)
    tools: รายชื่อเครื่องมือที่ยื่นให้โมเดลรอบนี้ — ผู้เรียกต้องส่งมาเอง (ไม่มี default เป็น
           TOOLS ของบอทเพราะไฟล์นี้ไม่รู้จัก TOOLS) ไม่ส่งมา = ไม่ยื่นเครื่องมือให้เลย"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "tools": tools if tools is not None else [],
        "options": {
            "temperature": temperature,
            "repeat_penalty": 1.12,  # ลดการพูดซ้ำคำ/ประโยคแพทเทิร์นเดิม (กันฟังดูหุ่นยนต์)
        },
    }
    data = await _get_json_post(payload, timeout=300)
    return data["message"]
