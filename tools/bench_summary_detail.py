"""วัดว่า summary ปัจจุบันเก็บ "เนื้อหา" ได้แค่ไหน — และ prototype แบบใหม่ดีขึ้นจริงไหม

⚠️ สคริปต์นี้ไม่แตะ production เลย — prototype อยู่ในไฟล์นี้ทั้งหมด (build_summary_prompt_v2)
เรียก memory.build_summary_prompt ตัวจริงเป็น baseline เทียบเท่านั้น ยังไม่แก้ memory.py

ปัญหาที่วัด: summary ปัจจุบันบอกแค่ *หัวข้อ* ไม่บอก *เนื้อหา*
    "23 ก.ค.: คุยเรื่องความแตกต่างระหว่างเจลาโต้และไอศกรีม"
พอผู้ใช้ถาม "เคยคุยเรื่องของหวานว่าไง" รอสเต้ตอบได้แค่ว่า "เคยคุยเรื่องเจลาโต้" แต่บอกไม่ได้
ว่าคุยว่าอะไร ทั้งที่ตอนนั้นคุยรายละเอียดกันจริง

ต้นเหตุอยู่ที่ build_summary_prompt เอง ซึ่งสั่งไว้ว่า:
    "- ห้ามเติมชื่อหนังสือ/สถานที่/ตัวเลข/รายละเอียดที่ผู้ใช้ไม่ได้พูดถึง"
    "- สั้นที่สุดเท่าที่จะบอกหัวข้อได้"
บวก verify pass ที่ตามลบรายละเอียดที่หลุดมาอีกชั้น — กฎนี้เขียนไว้กัน hallucinate ซึ่งถูกต้อง
แต่เหวี่ยงเกิน: ห้ามทั้งของที่แต่งขึ้น *และ* ของที่ผู้ใช้พูดจริง

แนวคิดของ v2: เปลี่ยนจาก "ห้ามใส่รายละเอียด" → "ใส่ได้ ถ้ายกมาจากบทสนทนาจริง"
แล้วตรวจความจริงด้วย rule (grounding) แทนการเชื่อโมเดล — หลักการเดียวกับ
llm_tools._strip_ungrounded_optional_args ที่ใช้แก้ปัญหาโมเดลเดา province เอง

วัด 4 อย่าง (ต้องดูพร้อมกัน ไม่งั้นแก้ทางหนึ่งพังอีกทาง — บทเรียนจาก bench_attention):
  1. detail    — summary มีคำที่เป็น "เนื้อหาจริง" จากบทไหม (ไม่ใช่แค่ชื่อหัวข้อ)
  2. grounded  — คำในสรุปมีอยู่ในบทสนทนาจริงไหม (= ไม่ hallucinate)
  3. ขนาด      — ยาวขึ้นเท่าไหร่ ⚠️ สำคัญเพราะเพิ่งวัดได้ว่าขนาดใน context ทำให้โมเดลลืม
  4. ความจำ    — ถามจริงผ่านโมเดลแล้วตอบรายละเอียดได้ไหม
"""
import argparse
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

import logging  # noqa: E402

import memory  # noqa: E402
import ollama_client  # noqa: E402
from _bench_target import resolve_memory_file  # noqa: E402

logging.disable(logging.CRITICAL)

MEM_FILE = resolve_memory_file()

# บทสนทนาตัวอย่าง — เขียนขึ้นให้ *มีรายละเอียดชัดเจน* ที่ summary ควรเก็บไว้
# (ใช้บทที่แต่งเองแทนบทจริง เพราะต้องรู้ "คำตอบที่ถูก" ล่วงหน้าถึงจะวัดได้ว่าเก็บครบไหม)
#
# must_keep = คำที่เป็นเนื้อหาจริง ถ้า summary ไม่มีเลย = ข้อมูลหาย
# forbidden = คำที่ *ไม่มี* ในบท ถ้าโผล่มา = hallucinate
CASES = [
    {
        "name": "ของหวาน",
        "pairs": [
            {"role": "user", "content": "รอสเต้ว่าเจลาโต้กับไอศกรีมต่างกันยังไง"},
            {"role": "assistant", "content": "เจลาโต้ใช้นมมากกว่าครีม เลยมีไขมันน้อยกว่าไอศกรีมค่ะ "
                                              "แล้วก็ปั่นช้ากว่า อากาศเข้าไปน้อย เนื้อเลยแน่นกว่า"},
            {"role": "user", "content": "งั้นผมชอบเจลาโต้มากกว่า เพราะเนื้อแน่นดี"},
            {"role": "assistant", "content": "เข้าใจเลยค่ะ เนื้อแน่นๆ รสชาติมันเข้มกว่าด้วยนะคะ"},
        ],
        "must_keep": ["เจลาโต้", "แน่น"],
        "forbidden": ["ช็อกโกแลต", "วานิลลา", "สตรอเบอร์รี่"],
        "question": "เคยคุยเรื่องของหวานกันไหม ผมชอบอะไร",
        "answer_keys": ["เจลาโต้"],
    },
    {
        "name": "การอ่าน",
        "pairs": [
            {"role": "user", "content": "ช่วงนี้ผมอ่านนิยายสืบสวนอยู่ ชอบแนวที่หักมุมตอนจบ"},
            {"role": "assistant", "content": "แนวสืบสวนสนุกตรงที่ได้เดาไปด้วยเนอะคะ หักมุมตอนจบนี่ชอบเลย"},
            {"role": "user", "content": "ใช่ แต่ไม่ชอบแนวสยองขวัญนะ อ่านแล้วนอนไม่หลับ"},
            {"role": "assistant", "content": "555 เข้าใจค่ะ สยองขวัญนี่อ่านกลางวันยังหลอนเลย"},
        ],
        "must_keep": ["สืบสวน", "หักมุม"],
        "forbidden": ["ฮิกาชิโนะ", "อกาธา", "เชอร์ล็อก"],
        "question": "จำได้ไหมว่าผมชอบอ่านนิยายแนวไหน",
        "answer_keys": ["สืบสวน", "หักมุม"],
    },
    {
        "name": "อาหาร",
        "pairs": [
            {"role": "user", "content": "เมื่อวานไปกินข้าวหน้าเนื้อที่ร้านแถวบ้าน อร่อยมาก"},
            {"role": "assistant", "content": "ข้าวหน้าเนื้อนี่ดีเลยค่ะ เนื้อนุ่มๆ ราดซอสหวานๆ"},
            {"role": "user", "content": "แต่ผมกินเผ็ดไม่ได้เลยนะ พริกนิดเดียวก็แสบแล้ว"},
            {"role": "assistant", "content": "งั้นต้องสั่งแบบไม่เผ็ดตลอดเลยสิคะ จำไว้แล้วค่ะ"},
        ],
        "must_keep": ["ข้าวหน้าเนื้อ", "เผ็ด"],
        "forbidden": ["ต้มยำ", "ส้มตำ", "ผัดกะเพรา"],
        "question": "เคยคุยเรื่องกินกันไหม ผมกินเผ็ดได้ไหม",
        "answer_keys": ["เผ็ด", "ไม่ได้", "ข้าวหน้าเนื้อ"],
    },
]


# ── prototype: prompt แบบใหม่ (ยังไม่แตะ memory.py) ────────────────────────────

def build_summary_prompt_v2(pairs: list) -> str:
    """ขอ 2 ส่วน: หัวข้อ + รายละเอียดที่ผู้ใช้พูดจริง

    ต่างจากตัวเดิมตรงที่ *ไม่ห้าม* รายละเอียด แต่บังคับว่าต้องยกมาจากบท — ความจริงของ
    รายละเอียดไปตรวจด้วย grounding check (rule-based) ทีหลัง ไม่ต้องพึ่งโมเดลตรวจตัวเอง
    """
    convo = "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'รอสเต้'}: {m.get('content', '')}"
        for m in pairs
    )
    return (
        "สรุปบทสนทนาต่อไปนี้เป็นภาษาไทย 1 บรรทัด โดยเก็บ *สิ่งที่ผู้ใช้บอกเกี่ยวกับตัวเอง* ไว้ด้วย\n"
        "กฎ:\n"
        "- เขียนทั้งหัวข้อที่คุย และสิ่งที่ผู้ใช้ชอบ/ไม่ชอบ/ทำ/ตัดสินใจ ถ้ามีในบท\n"
        "- ใช้คำเดียวกับที่ปรากฏในบทสนทนา ห้ามเปลี่ยนเป็นคำอื่นที่ความหมายใกล้เคียง\n"
        "- ห้ามเติมชื่อเฉพาะ/ตัวเลข/รายละเอียดที่ไม่ได้อยู่ในบทข้างล่าง\n"
        "- ไม่เกิน 2 ประโยค เขียนติดกันเป็นบรรทัดเดียว\n"
        "ตอบมาแค่ประโยคสรุปเท่านั้น ห้ามมีคำนำ:\n\n"
        + convo
    )


def _conversation_text(pairs: list) -> str:
    return " ".join((m.get("content") or "") for m in pairs)


def find_ungrounded(summary: str, pairs: list) -> list:
    """คืนรายการ "ข้อเท็จจริงเฉพาะเจาะจงที่ไม่ปรากฏในบทสนทนา" = สัญญาณว่าโมเดลแต่งขึ้น

    ⚠️ ตรวจอย่างเดียว ไม่แก้สตริง เจอแล้วให้ขอสรุปใหม่ (fail-conservative แบบเดียวกับ
    DISCARD เดิม) — เดิมเขียนให้ "ตัดคำที่ไม่มีในบททิ้ง" แล้วทดสอบพบว่าพัง 2 แบบ:
      1. ตัดกลางประโยคได้เศษคำอ่านไม่รู้เรื่อง
         "เจลาโต้รสช็อกโกแลตที่ร้านสเวนเซ่นส์" → "เจลาโต้รสส"
      2. สรุปที่ถูกต้องถูกลบจนเหลือสตริงว่าง — "คุยเรื่องของหวาน" → ""

    ⚠️ และตรวจ *เฉพาะคำนามเฉพาะ/ตัวเลข* เท่านั้น ไม่ใช่ทุกคำที่ไม่อยู่ในบท เพราะการสรุป
    คือการ "สรุปความ" โดยธรรมชาติ — บทที่คุยเรื่องเจลาโต้กับไอศกรีม สรุปว่า "ของหวาน"
    หรือ "ความแตกต่าง" ได้ถูกต้อง ทั้งที่สองคำนั้นไม่ได้อยู่ในบทตรงๆ (ทดสอบแล้วเจอว่า
    การเช็คทุกคำ flag สองอันนี้เป็น hallucinate ทั้งที่ถูก = false positive)

    สิ่งที่อันตรายจริงคือรายละเอียดที่ *ตรวจสอบได้* และผู้ใช้ไม่เคยพูด — ชื่อร้าน ชื่อหนังสือ
    ยี่ห้อ ตัวเลข ซึ่งเป็นเคสเดียวกับที่ build_verify_prompt เดิมพยายามจับ ต่างกันแค่
    ตัวนี้ตรวจด้วย rule (เชื่อถือได้) แทนการถามโมเดลว่าตัวเองแต่งไหม
    """
    import re
    convo = _conversation_text(pairs)
    out = []

    # ตัวเลขที่ไม่มีในบท — โมเดลชอบเติมราคา/จำนวน/ปีเอง
    for num in re.findall(r"\d+(?:[.,]\d+)?", summary):
        if num not in convo:
            out.append(num)

    # คำในเครื่องหมายคำพูด/วงเล็บ = โมเดลกำลังอ้างชื่อเฉพาะ
    for quoted in re.findall(r"[\"'“”‘’]([^\"'“”‘’]{2,40})[\"'“”‘’]", summary):
        if quoted.strip() and quoted.strip() not in convo:
            out.append(quoted.strip())

    # คำภาษาอังกฤษ (ชื่อยี่ห้อ/ชื่อเฉพาะมักเขียนด้วยอักษรละติน)
    for eng in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", summary):
        if eng.lower() not in convo.lower():
            out.append(eng)

    return out


# ── การให้คะแนน ───────────────────────────────────────────────────────────────

def score_summary(summary: str, case: dict) -> dict:
    keeps = [k for k in case["must_keep"] if k in summary]
    bad = [f for f in case["forbidden"] if f in summary]
    return {
        "detail": len(keeps) / len(case["must_keep"]),
        "kept": keeps,
        "missing": [k for k in case["must_keep"] if k not in summary],
        "hallucinated": bad,
        "ungrounded": find_ungrounded(summary, case["pairs"]),
        "size": len(summary),
    }


async def _gen(prompt: str) -> str:
    msg = await ollama_client._chat_once(
        [{"role": "user", "content": prompt}], temperature=0.1)
    raw = ollama_client._strip_think(msg.get("content", "") or "")
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    return lines[0] if lines else ""


async def run_variant(label: str, prompt_fn, reps: int, do_ground: bool):
    """do_ground=True → เจอคำแต่งขึ้น ขอสรุปใหม่ 1 ครั้ง (ไม่ใช่ตัดคำทิ้ง — ดู find_ungrounded)"""
    print(f"\n{'=' * 92}\n  {label}\n{'=' * 92}")
    agg = {"detail": 0.0, "hall": 0, "unground": 0, "size": 0, "n": 0, "retry": 0}
    for case in CASES:
        d_sum = h_sum = u_sum = s_sum = 0
        samples = []
        for _ in range(reps):
            summary = await _gen(prompt_fn(case["pairs"]))
            if not summary:
                continue
            if do_ground and find_ungrounded(summary, case["pairs"]):
                # สรุปนี้มีคำที่ไม่มีในบท = แต่งขึ้น → ขอใหม่อีกรอบ
                agg["retry"] += 1
                retry = await _gen(prompt_fn(case["pairs"]))
                if retry and not find_ungrounded(retry, case["pairs"]):
                    summary = retry
            sc = score_summary(summary, case)
            d_sum += sc["detail"]
            h_sum += len(sc["hallucinated"])
            u_sum += len(sc["ungrounded"])
            s_sum += sc["size"]
            if len(samples) < 2:
                samples.append((sc, summary))
            agg["n"] += 1
            agg["detail"] += sc["detail"]
            agg["hall"] += len(sc["hallucinated"])
            agg["unground"] += len(sc["ungrounded"])
            agg["size"] += sc["size"]
        print(f"\n  【{case['name']}】 เก็บเนื้อหา {d_sum/reps*100:.0f}%  "
              f"แต่งเพิ่ม {h_sum}  คำไม่มีในบท {u_sum}  ยาวเฉลี่ย {s_sum/reps:.0f}c")
        for sc, s in samples:
            mark = "✅" if sc["detail"] == 1.0 and not sc["hallucinated"] else "⚠️"
            print(f"     {mark} {s[:110]}")
            if sc["missing"]:
                print(f"        ขาด: {sc['missing']}")
            if sc["ungrounded"]:
                print(f"        ไม่มีในบท: {sc['ungrounded'][:6]}")
    n = max(agg["n"], 1)
    print(f"\n  ── รวม: เก็บเนื้อหา {agg['detail']/n*100:.0f}%  "
          f"แต่งเพิ่ม {agg['hall']}  คำไม่มีในบท {agg['unground']}  "
          f"ยาวเฉลี่ย {agg['size']/n:.0f}c" + (f"  (ขอใหม่ {agg['retry']} ครั้ง)" if do_ground else ""))
    return dict(label=label, detail=agg["detail"] / n, hall=agg["hall"],
                unground=agg["unground"], size=agg["size"] / n, retry=agg["retry"])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()

    cur = [x["text"] if isinstance(x, dict) else x
           for x in json.load(open(MEM_FILE, encoding="utf-8")).get("summaries", [])]
    print("=" * 92)
    print(f" วัด summary: เก็บเนื้อหาได้แค่ไหน (ซ้ำ {args.reps} รอบ/เคส)")
    print(f" summary จริงในเครื่องตอนนี้: {len(cur)} อัน เฉลี่ย "
          f"{sum(len(x) for x in cur)/max(len(cur),1):.0f}c รวม {sum(len(x) for x in cur)}c")
    print("=" * 92)

    rows = [
        await run_variant("A. ปัจจุบัน (build_summary_prompt)",
                          memory.build_summary_prompt, args.reps, False),
        await run_variant("B. v2 ขอรายละเอียด (ยังไม่ ground)",
                          build_summary_prompt_v2, args.reps, False),
        await run_variant("C. v2 + grounding check (ตัดคำที่ไม่มีในบท)",
                          build_summary_prompt_v2, args.reps, True),
    ]

    print("\n" + "=" * 92)
    print(f" {'แบบ':<42} {'เก็บเนื้อหา':>12} {'แต่งเพิ่ม':>10} {'ไม่มีในบท':>11} {'ขนาด':>8}")
    print("-" * 92)
    for r in rows:
        print(f" {r['label']:<42} {r['detail']*100:>10.0f}%  {r['hall']:>9} "
              f"{r['unground']:>10} {r['size']:>6.0f}c")
    print("=" * 92)
    base = rows[0]
    print("\n สิ่งที่ต้องดู:")
    print("   - เก็บเนื้อหาต้องสูงขึ้นชัดเจน ไม่งั้นแก้ไปก็ไม่ได้อะไร")
    print("   - แต่งเพิ่ม/ไม่มีในบท ต้องไม่สูงกว่าเดิม (ไม่งั้นแลก hallucinate กับรายละเอียด)")
    print(f"   - ขนาดโตจาก {base['size']:.0f}c ไปเท่าไหร่ — ยิ่งโตยิ่งเสี่ยงชนเพดาน context")
    print("     (วัดแล้วว่า tool schema >3,700c ทำให้โมเดลลืม summary — ขนาดมีราคาจริง)")


if __name__ == "__main__":
    asyncio.run(main())
