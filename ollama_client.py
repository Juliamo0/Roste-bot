"""
🤖 Ollama HTTP client — บาง ทั่วไป ไม่รู้จัก TOOLS/business logic ใดๆ ของบอทเลย

ตั้งใจให้ไม่พึ่งอะไรใน llm_tools.py/chat.py เด็ดขาด (ต่อให้ _chat_once/_chat_stream ใช้เรื่อง
เครื่องมือก็ตาม) เพื่อกัน circular import: llm_tools.py ต้องใช้ _get_json_post/_strip_think/MODEL
จากไฟล์นี้ ถ้าไฟล์นี้ import TOOLS จาก llm_tools.py กลับไปจะเกิด import วนตอน startup —
ผู้เรียกต้องส่ง tools มาเองเสมอถ้าต้องการให้โมเดลเรียกเครื่องมือได้ (เส้น streaming ก็กฎเดียวกัน)
"""
import json
import time
from urllib.parse import urlsplit

import aiohttp

# OLLAMA_URL/MODEL อ่านจาก config.py (ตั้งใน .env ได้ผ่าน OLLAMA_URL/OLLAMA_MODEL) — ไม่บังคับ
# เปลี่ยนเครื่อง/เปลี่ยนโมเดลได้โดยไม่ต้องแก้โค้ด fallback เป็นค่าเดิมถ้า import config ไม่ได้
# (เช่น ตอนรันไฟล์นี้แยกหรือในบางเทส) เหมือน pattern SERPAPI_KEY ใน websearch.py
try:
    from config import OLLAMA_URL, OLLAMA_MODEL as MODEL
except ImportError:
    OLLAMA_URL = "http://localhost:11434/api/chat"
    # qwen3:1.7b = เร็วสุด แต่โง่   |   qwen3:8b = สมดุล   |   qwen3:14b = ฉลาดขึ้นแต่ช้า (การ์ด 4GB ~1-2 นาที)
    MODEL = "qwen3:8b"

# tag เปิด/ปิดบล็อก "คิด" ของโมเดลตระกูล reasoning — ประกอบจาก string ย่อย ไม่เขียนติดกัน
# เพื่อไม่ให้ tag จริงๆ โผล่เป็น literal ใน log/diff แล้ว parser ของ tool ภายนอกกลืนหาย
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"


class OllamaUnavailable(Exception):
    """Ollama ไม่พร้อม (ล่ม/ช้าเกิน/breaker เปิด) — ผู้เรียกควรตอบ fallback ทันที ไม่ต้องรอ"""


# circuit breaker กันทุกข้อความค้างรอ timeout เต็มเวลาเวลา Ollama ล่ม/กำลังรีสตาร์ท —
# ล้มติดกันเกิน threshold แล้วเปิด breaker พัก cooldown วิ ก่อนยอมลองยิง HTTP จริงอีกครั้ง
# คุมทั้ง _chat_once และ _chat_stream (ทั้งคู่ยิง POST ไป OLLAMA_URL เหมือนกัน) ผ่าน
# _check_breaker/_record_success/_record_failure ร่วมกัน กันเขียน logic ซ้ำสองที่
_consecutive_failures = 0
_breaker_open_until = 0.0        # time.monotonic() ที่ breaker จะกลับมาลองใหม่
_FAILURE_THRESHOLD = 3           # ล้มติดกันกี่ครั้งถึงเปิด breaker
_BREAKER_COOLDOWN_SEC = 30       # เปิดแล้วพัก 30 วิ ก่อนยอมลองใหม่


def _check_breaker() -> None:
    if time.monotonic() < _breaker_open_until:
        raise OllamaUnavailable("Ollama breaker เปิดอยู่ (ล้มติดกันเกินเกณฑ์)")


def _record_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


def _record_failure() -> None:
    global _consecutive_failures, _breaker_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= _FAILURE_THRESHOLD:
        _breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_SEC


async def _get_json_post(payload, timeout=90):
    # เดิม timeout=300 — การ์ด 4GB คำตอบปกติ <30 วิ, 90 คือเผื่อตอนโหลดโมเดลใหม่ เกินกว่า
    # นั้นถือว่าผิดปกติ ให้ fail เร็วดีกว่าค้าง (ผู้ใช้เจอจริง: Ollama รีสตาร์ทแล้วทุก
    # ข้อความค้างรอเต็ม 300 วิก่อนตอบ error)
    _check_breaker()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=payload, timeout=timeout) as r:
                data = await r.json()
    except (aiohttp.ClientError, TimeoutError, OSError) as e:
        _record_failure()
        raise OllamaUnavailable(f"Ollama ไม่ตอบสนอง: {type(e).__name__}: {e}") from e
    _record_success()
    return data


# ไว้แปลง OLLAMA_URL (ที่ลงท้าย /api/chat) เป็น /api/tags — เดิม probe_health hardcode
# localhost ตรงๆ ทำให้เช็คผิดเครื่องเมื่อผู้ใช้ตั้ง OLLAMA_URL ชี้เครื่องอื่นผ่าน .env
# (ค่านี้ override ได้จริงตาม config.py/.env.example) ต้องอิงจาก OLLAMA_URL เดียวกับ
# ที่ _get_json_post/_stream_chat_chunks ใช้จริง ไม่ใช่ผูกกับ localhost ตายตัว
_ollama_parts = urlsplit(OLLAMA_URL)
_OLLAMA_HEALTH_URL = f"{_ollama_parts.scheme}://{_ollama_parts.netloc}/api/tags"


async def probe_health(timeout: float = 3) -> bool:
    """เช็คว่า Ollama ยังมีชีวิตอยู่ไหมแบบเร็วๆ (ping /api/tags) — ไม่ผ่าน breaker เพราะ
    ตัวนี้มีไว้ *เช็คสถานะ* ไม่ใช่คุยจริง ผู้เรียกภายนอก (เช่น bot startup) ใช้ตัดสินใจ
    ไม่ต้อง raise เด็ดขาด คืน False เสมอเมื่อเช็คไม่ผ่านไม่ว่าเหตุผลอะไร"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(_OLLAMA_HEALTH_URL, timeout=timeout) as r:
                return r.status == 200
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False


def _strip_think(text: str) -> str:
    """ตัดบล็อก "คิด" ที่โมเดลเผลอโชว์ทิ้ง เหลือแค่คำตอบจริงหลัง tag ปิด"""
    if _THINK_CLOSE in text:
        return text.rsplit(_THINK_CLOSE, 1)[-1]
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
    data = await _get_json_post(payload, timeout=90)
    return data["message"]


# ── เส้น streaming (สำหรับ pipeline เสียง) ────────────────────────────────────
#
# ทำไมต้องมีแยกจาก _chat_once: เส้นเสียงเดิมรอคำตอบ "เต็ม" ก่อนถึงจะเริ่ม TTS = ผู้ฟังเงียบ
# ~8s ทั้งที่ token แรกมาถึงในไม่ถึงวินาที (วัดจริง qwen3:8b บนเครื่องนี้: knowledge question
# first token 55ms แต่ full answer ~12s — casual chat first sentence done 708ms vs full 1974ms)
# ขอแค่ delta ทยอยมา ก็ตัดประโยคแรกส่งเข้า TTS ได้ทันที ไม่ต้องรอโมเดลพิมพ์จบ
# _chat_once ไม่แตะแม้แต่บรรทัดเดียว เพราะ typed-chat + tool loop ใน chat.py พึ่งพฤติกรรม
# เดิมแบบเป๊ะ (msg.get("tool_calls"), msg.get("content")) — เสี่ยง regression ไม่คุ้ม


def _may_start_tag(buf: str) -> bool:
    """True ถ้าท้าย buf อาจเป็นเพียง *ต้น* tag think ที่ถูกตัดคร่อม chunk — ยังตัดสินใจ
    ไม่ได้ต้องรอ chunk ถัดไป (Ollama แบ่ง delta ตาม token โดยไม่รู้จัก tag แบ่งกลาง
    "<th|ink>" ได้เสมอ ไม่มีการรับประกันว่า tag จะมาครบใน chunk เดียว)"""
    return any(t.startswith(buf[i:]) for t in (_THINK_OPEN, _THINK_CLOSE)
               for i in range(len(buf)))


async def _stream_chat_chunks(payload, timeout=90):
    """transport ล้วน: POST แล้ว yield dict ทีละบรรทัด NDJSON — ไม่รู้จัก business logic

    /api/chat เมื่อ stream:true ตอบเป็น JSON บรรทัดละ object: chunk delta ตาม token
    แล้วปิดท้ายด้วยตัว done:true (message.content ว่าง) — ต้อง iterate r.content
    เท่านั้น (aiohttp 3.x ClientResponse ไม่ใช่ async iterator, async for บน response
    ตรงๆ จะ TypeError — เจอจริงตอนพัฒนา)
    timeout เป็น int เหมือน _get_json_post — aiohttp แปลงเป็น ClientTimeout(total=...) เอง
    เดิม 300 — ลดพร้อมกับ _get_json_post (เหตุผลเดียวกัน: ค้างเกินนี้ผิดปกติ ให้ breaker
    จับแทนที่จะรอเต็มเวลา)

    ผ่าน breaker เดียวกับ _get_json_post ก่อน yield chunk แรก และเมื่อ connection พังกลาง
    ทาง (Ollama ล่มระหว่างสตรีมเสียง ต้องล้มเร็วเหมือนเส้นพิมพ์ ไม่ใช่ปล่อยให้ผู้ใช้เงียบ
    รอจน timeout)
    """
    _check_breaker()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=payload, timeout=timeout) as r:
                async for raw in r.content:
                    line = raw.strip()
                    if line:  # บรรทัดว่างคั่นกลางเกิดได้ — ข้าม ไม่ใช่ error
                        yield json.loads(line.decode("utf-8"))
    except (aiohttp.ClientError, TimeoutError, OSError) as e:
        _record_failure()
        raise OllamaUnavailable(f"Ollama ไม่ตอบสนอง: {type(e).__name__}: {e}") from e
    else:
        _record_success()


async def _chat_stream(messages, temperature: float = 0.8, tools=None, final=None):
    """เหมือน _chat_once แต่ทยอย yield delta ระหว่างที่โมเดลยังพิมพ์ (สำหรับเส้นเสียง)

    payload/options/repeat_penalty/timeout/error behaviour เหมือน _chat_once ทุกอย่าง
    ผู้เรียกจึงไม่ต้องเขียน error handling เพิ่ม — ต่างกันแค่รูปแบบการคืนค่า:

    สัญญา (contract) กับผู้เรียก:
      - เทิร์นปกติ: yield str delta เรียงต่อกันจนครบคำตอบ — ตัด tag think ให้แล้ว
        (delta แรกอาจมีช่องว่าง/tag นำหน้าตามโมเดล ผู้เรียก .strip() ก่อนใช้เอง)
      - ข้อความดิบฉบับเต็ม (รวม tag think — เทียบเท่า data["message"] ของ _chat_once):
          ส่ง dict เปล่ามาทาง final= พอลูปจบได้ final = {"role","content"[,"tool_calls"]}
          ใช้บันทึก history ต่อได้เลย (ทำ out-param เพราะ async generator คืนค่าผ่าน
          StopAsyncIteration.value ซึ่ง caller ต้อง anext เอง อ่านยากกว่าแบบนี้)
      - ⚠️ เทิร์นที่โมเดลขอเรียก tool: streaming ข้อความไร้ความหมายสำหรับเทิร์นนี้ (ต้อง
        เรียก tool แล้วถามใหม่) จึง *ไม่ yield อะไรเลย* แล้วฝาก list ไว้ที่ final["tool_calls"]
        โครงสร้างเหมือนที่ _chat_once คืน (arguments decode เป็น dict แล้ว — วัดจริงกับ
        qwen3:8b แล้ว Ollama ส่ง tool_calls มาครบใน chunk เดียว มักเป็น chunk แรกก่อน
        text ใดๆ) ผู้เรียกต้อง *ทิ้ง delta ที่สะสมไว้* เมื่อเห็น final["tool_calls"] —
        มันคือเศษ reasoning ไม่ใช่คำตอบ — แล้ววน tool loop ต่อด้วยรอบใหม่ของ
        _chat_stream เอง (หรือยิง _chat_once ก็ได้ ผลเท่ากัน)
    """
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "think": False,
        "tools": tools if tools is not None else [],
        "options": {
            "temperature": temperature,
            "repeat_penalty": 1.12,  # ค่าเดียวกับ _chat_once — สองเส้นต้องให้ character เดียวกัน
        },
    }
    sink = final if final is not None else {}
    sink.clear()
    parts = []       # delta ดิบทุกก้อน (รวม tag think) — เอาไปประกอบ final["content"]
    pending = ""     # หัวคำตอบที่ยังไม่กล้า yield เพราะอาจมี/กำลังโตเป็น tag think
    decided = False  # เลย tag ปิดไปแล้ว → delta ถัดไปปล่อยตรงๆ ไม่ต้องเช็คอีก (fast path)
    tool_calls = None
    got_chunk = False
    async for chunk in _stream_chat_chunks(payload):
        got_chunk = True
        if "error" in chunk:
            # Ollama ส่ง error กลาง stream เป็น object เดียว {"error": "..."} ไม่มี done:true
            # (วัดจริง: model ไม่มีบนเครื่อง = HTTP 404 + body รูปแบบเดียวกัน) — raise ให้
            # caller เจอ exception แบบเดียวกับที่ _chat_once พัง ไม่ต้องเขียน handling ใหม่
            raise RuntimeError(f"Ollama: {chunk['error']}")
        msg = chunk.get("message") or {}
        tc = msg.get("tool_calls")
        if tc:
            tool_calls = tc
        delta = msg.get("content") or ""
        if not delta:
            continue  # chunk ที่มีแต่ tool_calls/done:true — ไม่มีอะไรปล่อย
        parts.append(delta)
        if tool_calls:
            continue  # เทิร์น tool — text ที่ปนมาไม่ใช่คำตอบ ห้ามปล่อย (ดู contract ข้างบน)
        if decided:
            yield delta
            continue
        # ช่วงหัวคำตอบ: _strip_think ทำงานกับ "ทั้งก้อน" (rsplit หา tag ปิดแล้วตัดทุกอย่าง
        # ก่อนหน้าทิ้ง) จึงรันต่อ chunk ไม่ได้ — tag โดนแบ่งคร่อม chunk ("<th" + "ink>")
        # กินได้ ต้องถือ buffer เองจนแน่ใจ แล้วปล่อยทีเดียว (ค้างเฉพาะช่วงหัว ไม่กระทบ
        # ลำดับ/ความล่าช้าของประโยคหลังจากนั้น)
        pending += delta
        if _THINK_CLOSE in pending:
            clean = pending.rsplit(_THINK_CLOSE, 1)[-1]  # logic เดียวกับ _strip_think
            if clean:
                yield clean
            pending, decided = "", True
        elif _THINK_OPEN in pending:
            pass  # ยังอยู่ "ใน" บล็อกคิด — ค้างไว้จนกว่าจะเจอ tag ปิด
        elif _may_start_tag(pending):
            pass  # อาจเป็นต้น tag คร่อม chunk — รอ chunk ถัดไปก่อนตัดสินใจ
        elif pending.strip():
            # ไม่มีร่องรอย tag เลย → ปล่อยทั้ง buffer ครั้งเดียว (หน่วงแค่ chunk แรก)
            yield pending
            pending, decided = "", True
        # pending ล้วนช่องว่าง: ถือไว้อีกที — เผื่อขึ้นบรรทัดใหม่นำหน้า tag เปิดใน chunk ถัดไป
    if not got_chunk:
        raise RuntimeError("Ollama ไม่ส่ง chunk กลับมาเลย (เซิร์ฟเวอร์ตาย/OLLAMA_URL ผิด)")
    if pending:
        # tail สุดท้ายเป็นข้อความ "ครบ" แล้ว จึงใช้ helper ตัวจริงได้ (tag คร่อม chunk ไม่ได้อีก)
        clean = _strip_think(pending)
        if clean:
            yield clean
    sink["role"] = "assistant"
    sink["content"] = "".join(parts)
    if tool_calls is not None:
        sink["tool_calls"] = tool_calls
