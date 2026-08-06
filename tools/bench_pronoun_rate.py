"""วัดว่า "สรรพนามทางการหลุด" เกิดบ่อยแค่ไหนจริงๆ — แยกความผิดของโมเดลออกจาก guard

ที่มา: ROADMAP known issue "สรรพนาม 'ข้าพเจ้า' หลุด" บันทึกจากที่เจอบน Discord *ครั้งเดียว*
ซึ่งพิสูจน์ได้แค่ว่า "เกิดขึ้นได้" ไม่ได้บอกว่า "บ่อยแค่ไหน" — โมเดลมีการสุ่ม การเจอครั้งเดียว
อาจเป็น 1% หรือ 30% ก็ได้ ซึ่งคนละเรื่องกันตอนตัดสินใจว่าจะแก้ไหม

แยกวัด 2 ชั้น (ชั้นล่างไม่ต้องเรียกโมเดล = ไม่แกว่ง วัดครั้งเดียวก็จบ):
  ชั้น guard — ถ้าโมเดลพูดคำนี้ออกมา guard จับได้ไหม  (deterministic, ดู tests/test_persona_pronoun.py)
  ชั้นโมเดล — โมเดลพูดคำนี้ออกมาบ่อยแค่ไหน            (สุ่ม ต้องยิงหลายรอบ = สคริปต์นี้)

วิธีวัด: ยิงคำถามที่ "ล่อ" ให้ตอบเป็นทางการ (ถามความเห็น/ให้แนะนำตัว/ถามเรื่องที่ไม่รู้)
ผ่าน chat.ask_ollama เส้นจริง N รอบต่อคำถาม แล้วนับว่ากี่รอบมีสรรพนามผิด

รายงานเป็นช่วงความเชื่อมั่น Wilson ไม่ใช่ค่าเดียว — บทเรียนจาก bench_model_upgrade:
n น้อยแล้วอ่านค่าเดียวทำให้ตัดสินใจผิดมาแล้ว ("2/20 = 10%" จริงๆ กว้าง 3-30%)

ใช้:
    python tools/bench_pronoun_rate.py            # 15 รอบ/คำถาม
    BENCH_N=30 python tools/bench_pronoun_rate.py # เพิ่ม n ให้ช่วงแคบลง
"""
import asyncio
import math
import os
import pathlib
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pythainlp.tokenize import word_tokenize  # noqa: E402

import chat  # noqa: E402
import persona  # noqa: E402
from _bench_target import resolve_uid  # noqa: E402

N = int(os.environ.get("BENCH_N", "15"))
UID = resolve_uid()
USER_NAME = "เทสเตอร์"

# สรรพนามที่ผิดคาแร็กเตอร์ (รอสเต้ = เด็กสาว พูดกันเอง ต้องใช้ "ฉัน")
# "ผม" ต้องเช็คด้วย regex ของ persona เอง เพราะ "ผม" เป็นคำนาม (เส้นผม) ได้ด้วย
#
# ⚠️ ห้ามเช็คด้วย `p in text` เด็ดขาด — คำพวกนี้เป็น substring ของคำปกติเต็มไปหมด
# (เจอจริงตอน smoke test n=2: "ข้า" แมตช์ใน "เข้าใจ"/"ข้างนอก"/"ข้าว" → รายงาน 40% ทั้งที่
# ของจริงคือ 0%) ต้องตัดคำด้วย newmm แล้วเทียบ *ทั้งโทเคน* — บทเรียนเดียวกับบั๊ก keyword
# recall ที่ str.split() ใช้กับภาษาไทยไม่ได้
FORMAL_PRONOUNS = {"ข้าพเจ้า", "กระผม", "ดิฉัน", "หนู", "ตัวข้า", "ข้า", "อาตมา", "ข้าน้อย", "ผม"}

# คำ/วลีทางการที่ไม่ใช่สรรพนาม — วัดด้วยเพราะ "บุคลิกทางการ" ไม่ได้มีแค่สรรพนาม
# (เจอจริง: "ขอกราบขอบพระคุณ...ด้วยความเคารพอย่างสูง" = ทิ้งคาแร็กเตอร์ทั้งดุ้นทั้งที่สรรพนามถูก)
FORMAL_PHRASES = [
    "ขอกราบขอบพระคุณ", "กราบขอบพระคุณ", "ด้วยความเคารพอย่างสูง", "ขอแสดงความนับถือ",
    "ในโอกาสนี้", "ขอเรียนให้ทราบ", "โปรดทราบ", "ข้าพเจ้าขอ", "ใคร่ขอ",
]

# คำถามที่ล่อให้ตอบเป็นทางการ — เลือกจากบริบทที่เจอปัญหาจริง
# (ถามความเห็น/ขอคำแนะนำ/ถามเรื่องที่ตอบไม่ได้ = โมเดลมักสวิตช์ไปโหมด "ผู้ช่วย" ที่เป็นทางการ)
PROMPTS = [
    "ช่วยแนะนำตัวอย่างเป็นทางการหน่อยได้ไหม",
    "คิดยังไงกับเรื่องการอ่านหนังสือ ตอบแบบสุภาพหน่อยนะ",
    "ขอความเห็นเรื่องการทำงานหนักหน่อย",
    "เธอช่วยอธิบายเรื่องที่เธอไม่รู้ให้ฟังหน่อย",
    "เขียนคำกล่าวขอบคุณอย่างเป็นทางการให้หน่อย",
]


def wilson(k: int, n: int, z: float = 1.96):
    """ช่วงความเชื่อมั่น Wilson 95% — เหมาะกับ n น้อย/สัดส่วนใกล้ 0 กว่า normal approx"""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def find_bad_pronouns(text: str) -> list:
    """คืนลิสต์สรรพนามผิดที่เจอในข้อความ — ตัดคำก่อนเทียบ ไม่ใช้ substring match

    หมายเหตุ: ไม่พึ่ง internal ของ persona (เคยเรียก _MOM_PRONOUN_RE ตรงๆ แล้วพังตอน refactor)
    — bench ควรวัด "ผลลัพธ์ที่ผู้ใช้เห็น" ไม่ใช่ผูกกับวิธี implement ของ guard"""
    tokens = word_tokenize(strip_quoted(text), engine="newmm")
    return sorted({t for t in tokens if t in FORMAL_PRONOUNS})


# ส่วนที่เป็น "ตัวอย่างที่รอสเต้ยกให้" ไม่ใช่ "น้ำเสียงของรอสเต้เอง" — ต้องตัดออกก่อนวัด
#   "..." / “...”  = ข้อความที่ยกมา
#   > ...          = blockquote (markdown)
#   **...**        = ตัวหนา ที่โมเดลใช้ครอบตัวอย่าง
# เจอจริงหลังแก้รอบแรก: วัดได้ 9.3% แต่พออ่านคำตอบเต็มพบว่ารอสเต้พูดกันเองปกติทุกรอบ
# ("แน่นอนค่ะ ดูตัวอย่างนี้เลย") วลีทางการอยู่ใน *ตัวอย่างที่ผู้ใช้ขอให้เขียน* ทั้งหมด
# = ทำงานถูกแล้ว ไม่ใช่หลุดคาแร็กเตอร์ ถ้าไม่ตัดออกจะไล่แก้ผิดจุด
_QUOTED_RE = re.compile(
    r"\"[^\"]*\"|“[^”]*”|^\s*>.*$|\*\*[^*]*\*\*",
    re.MULTILINE,
)


def strip_quoted(text: str) -> str:
    """ตัดส่วนที่เป็นตัวอย่าง/ข้อความที่ยกมา เหลือเฉพาะน้ำเสียงที่รอสเต้พูดเอง"""
    return _QUOTED_RE.sub(" ", text)


def find_formal_phrases(text: str) -> list:
    """คืนวลีทางการที่ *รอสเต้พูดเอง* (ไม่นับที่อยู่ในตัวอย่างที่ยกให้)"""
    body = strip_quoted(text)
    return [p for p in FORMAL_PHRASES if p in body]


async def main():
    print("=" * 74)
    print(f"วัดอัตราสรรพนามหลุด — {N} รอบ/คำถาม × {len(PROMPTS)} คำถาม = {N * len(PROMPTS)} รอบ")
    print(f"โมเดล: {os.getenv('OLLAMA_MODEL', 'qwen3:8b')}   uid ที่ใช้ความจำ: {UID}")
    print("=" * 74)

    total_pron = 0       # รอบที่มีสรรพนามผิด (หลังผ่าน guard แล้ว = ที่ผู้ใช้เห็นจริง)
    total_phrase = 0     # รอบที่มีวลีทางการ (guard ไม่ได้แก้ให้ ต้องอาศัย prompt/few-shot)
    total_any = 0        # รอบที่ผิดอย่างน้อยหนึ่งแกน
    total_runs = 0
    pron_counter = Counter()
    phrase_counter = Counter()
    examples = []

    for prompt in PROMPTS:
        pron_hits = phrase_hits = any_hits = 0
        for i in range(N):
            try:
                reply = await chat.ask_ollama(UID, USER_NAME, prompt)
            except Exception as e:
                print(f"  [error] {type(e).__name__}: {e}")
                continue
            total_runs += 1

            # ask_ollama ใส่ guard ให้แล้ว — วัดจากผลลัพธ์จริงที่ผู้ใช้เห็น (ชั้นที่สำคัญที่สุด)
            bad = find_bad_pronouns(reply)
            phrases = find_formal_phrases(reply)
            if bad:
                pron_hits += 1
                for b in bad:
                    pron_counter[b] += 1
            if phrases:
                phrase_hits += 1
                for p in phrases:
                    phrase_counter[p] += 1
            if bad or phrases:
                any_hits += 1
                if len(examples) < 8:
                    snippet = re.sub(r"\s+", " ", reply)[:110]
                    examples.append(f"[{','.join(bad + phrases)}] {snippet}")

        total_pron += pron_hits
        total_phrase += phrase_hits
        total_any += any_hits
        lo, hi = wilson(any_hits, N)
        print(f"\n  {prompt}")
        print(f"    ทางการ {any_hits}/{N}  ({any_hits/N*100:.0f}%, ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%)"
              f"   [สรรพนาม {pron_hits} / วลี {phrase_hits}]")

    lo, hi = wilson(total_any, total_runs) if total_runs else (0, 0)
    print()
    print("=" * 74)
    print(f"รวม: หลุดเป็นทางการ {total_any}/{total_runs} = {total_any/max(total_runs,1)*100:.1f}%")
    print(f"     ช่วงความเชื่อมั่น 95% (Wilson): {lo*100:.1f}% - {hi*100:.1f}%")
    print(f"     แยกแกน: สรรพนาม {total_pron}/{total_runs}, วลีทางการ {total_phrase}/{total_runs}")
    if pron_counter:
        print(f"     สรรพนามที่เจอ: {dict(pron_counter)}")
    if phrase_counter:
        print(f"     วลีที่เจอ: {dict(phrase_counter)}")
    print("=" * 74)
    if examples:
        print("\nตัวอย่างที่หลุด (ข้อความที่ผู้ใช้เห็นจริง หลังผ่าน guard แล้ว):")
        for e in examples:
            print(f"  - {e}")


if __name__ == "__main__":
    asyncio.run(main())
