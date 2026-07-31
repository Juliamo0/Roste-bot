"""เทียบวิธีแก้ recall หลายแบบบนเคสจริงที่บอทตอบผิด

เคสทดสอบมาจากบทสนทนาจริงบน Discord (00:13 น. 31 ก.ค.) ที่รอสเต้ตอบว่า "ไม่เคยคุย"
ทั้งที่เคยคุยเรื่องนิยาย/หนังสือจริง

วิธีที่เทียบ (ทั้งหมดวัดบน summaries ชุดเดียวกัน 25 อัน):
  A) baseline      — split() ตามช่องว่าง (โค้ดปัจจุบัน)
  B) tokenize      — ตัดคำไทยด้วย newmm ก่อน match  (แก้ต้นตอเดียวกับบั๊ก TTS)
  C) expand        — B + ขยายคำพ้องความหมาย (อ่าน↔หนังสือ↔นิยาย)
  D) bm25-ish      — B + ถ่วงน้ำหนักคำหายาก (คำที่โผล่ทุก summary ไม่ควรมีน้ำหนัก)
  E) hybrid RRF    — รวมอันดับจาก D กับ vector ด้วย Reciprocal Rank Fusion
  F) vector only   — ระบบ vector ปัจจุบัน (embedding + LLM rerank)

วัด: recall@k (เจอ summary ที่ควรเจอไหม) + precision (ดึงขยะมาด้วยกี่อัน)
"""
import asyncio
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pythainlp.tokenize import word_tokenize  # noqa: E402

from _bench_target import resolve_memory_file, resolve_uid  # noqa: E402

MEM_FILE = resolve_memory_file()
UID = resolve_uid()
TOP_K = 5

# เคสจริง: (คำถาม, คำที่ต้องปรากฏใน summary ที่ถูกต้อง)
CASES = [
    ("ว่าแต่รอสเต้เราเคยคุยเรื่องการอ่านอะไรพวกนั้นด้วยไหมก่อนหน้านี้", ["นิยาย", "หนังสือ"]),
    ("เรื่องเกี่ยวกับการอ่านหนังสือนะพอจำได้ไหมตอนนั้นคุยอะไรกัน", ["นิยาย", "หนังสือ"]),
    ("เราเคยคุยเรื่องของหวานกันไหม", ["ของหวาน"]),
    ("จำได้ไหมว่าเคยคุยเรื่องน้ำมันอะไรบ้าง", ["น้ำมัน"]),
    ("เคยคุยเรื่องอากาศกันหรือเปล่า", ["อากาศ"]),
]

# คำพ้อง/คำใกล้เคียงสำหรับวิธี C — เขียนมือเฉพาะโดเมนที่บอทคุยบ่อย
SYNONYMS = {
    "อ่าน": ["หนังสือ", "นิยาย", "อ่าน"],
    "หนังสือ": ["หนังสือ", "นิยาย", "อ่าน"],
    "นิยาย": ["นิยาย", "หนังสือ", "อ่าน"],
    "ของหวาน": ["ของหวาน", "ขนม", "ไอศกรีม", "เจลาโต้"],
    "ขนม": ["ของหวาน", "ขนม", "ไอศกรีม"],
    "อากาศ": ["อากาศ", "ฝน", "ร้อน", "หนาว", "อุณหภูมิ"],
    "น้ำมัน": ["น้ำมัน", "ดีเซล", "เบนซิน", "ราคา"],
    "กิน": ["อาหาร", "ร้าน", "เมนู", "กิน"],
    "เที่ยว": ["เที่ยว", "สถานที่", "ทะเล"],
}

_STOP = {"ว่าแต่", "เรา", "เคย", "คุย", "เรื่อง", "การ", "อะไร", "พวก", "นั้น",
         "ด้วย", "ไหม", "ก่อนหน้านี้", "ตอนนั้น", "กัน", "หรือเปล่า", "จำได้",
         "นะ", "พอ", "บ้าง", "รอ", "สเต้", "ที่", "ของ", "ให้", "และ", "มี"}


def _tok(text):
    return [t for t in word_tokenize(text, engine="newmm")
            if t.strip() and len(t) >= 2]


def _content_words(text):
    return [t for t in _tok(text) if t not in _STOP]


def load_summaries():
    d = json.load(open(MEM_FILE, encoding="utf-8"))
    return [s["text"] if isinstance(s, dict) else s for s in d.get("summaries", [])]


# ── A) baseline: split ตามช่องว่าง (โค้ดปัจจุบัน) ──
def method_baseline(q, summaries):
    words = [w for w in q.split() if len(w) >= 2]
    scored = [(sum(1 for w in words if w in s), s) for s in summaries]
    return [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc > 0][:TOP_K]


# ── B) tokenize ก่อน match ──
def method_tokenize(q, summaries):
    words = _content_words(q)
    scored = [(sum(1 for w in words if w in s), s) for s in summaries]
    return [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc > 0][:TOP_K]


# ── C) tokenize + ขยายคำพ้อง ──
def method_expand(q, summaries):
    words = set()
    for w in _content_words(q):
        words.update(SYNONYMS.get(w, [w]))
    scored = [(sum(1 for w in words if w in s), s) for s in summaries]
    return [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc > 0][:TOP_K]


# ── D) ถ่วงน้ำหนักคำหายาก (idf แบบง่าย) ──
def method_bm25ish(q, summaries):
    import math
    N = len(summaries)
    words = set()
    for w in _content_words(q):
        words.update(SYNONYMS.get(w, [w]))
    scored = []
    for s in summaries:
        sc = 0.0
        for w in words:
            df = sum(1 for x in summaries if w in x)
            if df and w in s:
                sc += math.log(1 + N / df)      # คำยิ่งหายาก ยิ่งมีน้ำหนัก
        scored.append((sc, s))
    return [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc > 0][:TOP_K]


# ── F) vector ปัจจุบัน ──
async def method_vector(q, _summaries):
    import vectormemory as V
    return await V.query_conversation_memory(UID, q, top_k=TOP_K)


# ── E) hybrid: RRF รวมอันดับ D + vector ──
async def method_hybrid(q, summaries):
    sparse = method_bm25ish(q, summaries)
    dense = await method_vector(q, summaries)
    K = 60          # ค่ามาตรฐานของ RRF
    scores = {}
    for rank, doc in enumerate(sparse):
        scores[doc] = scores.get(doc, 0) + 1 / (K + rank + 1)
    for rank, doc in enumerate(dense):
        scores[doc] = scores.get(doc, 0) + 1 / (K + rank + 1)
    return [d for d, _ in sorted(scores.items(), key=lambda x: -x[1])][:TOP_K]


def hit(results, must_have):
    return any(any(m in r for m in must_have) for r in results)


async def main():
    summaries = load_summaries()
    print("=" * 84)
    print(f" เทียบวิธี recall — summaries {len(summaries)} อัน, {len(CASES)} เคสจริง")
    print("=" * 84)

    methods = [
        ("A baseline (ปัจจุบัน)", method_baseline, False),
        ("B tokenize",            method_tokenize, False),
        ("C +คำพ้อง",             method_expand,   False),
        ("D +ถ่วงคำหายาก",        method_bm25ish,  False),
        ("F vector (ปัจจุบัน)",   method_vector,   True),
        ("E hybrid RRF",          method_hybrid,   True),
    ]

    table = {}
    for name, fn, is_async in methods:
        hits, noise = 0, 0
        detail = []
        for q, must in CASES:
            res = await fn(q, summaries) if is_async else fn(q, summaries)
            ok = hit(res, must)
            hits += ok
            noise += sum(1 for r in res if not any(m in r for m in must))
            detail.append((ok, len(res), q[:34]))
        table[name] = (hits, noise, detail)
        print(f"\n【{name}】  เจอ {hits}/{len(CASES)}  (ดึงที่ไม่เกี่ยวมาด้วย {noise} อัน)")
        for ok, n, q in detail:
            print(f"    {'✅' if ok else '❌'}  คืน {n} อัน   {q}")

    print("\n" + "=" * 84)
    print(f" {'วิธี':<26} {'เจอ':>8} {'ขยะ':>8}   หมายเหตุ")
    print("-" * 84)
    for name, (h, n, _) in table.items():
        note = ""
        if h == len(CASES) and n == min(x[1] for x in table.values() if x[0] == len(CASES)):
            note = "← ดีสุด"
        print(f" {name:<26} {h:>4}/{len(CASES):<3} {n:>8}   {note}")
    print("=" * 84)


if __name__ == "__main__":
    asyncio.run(main())
