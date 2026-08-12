"""วัดว่า schema ใหม่ (user_ask / me_suggest) แก้ attribution error ได้จริงไหม

⚠️ ทำไมต้องมี bench แยกจาก bench_provenance.py:
   bench_provenance วัดกับความจำ **เดิม** ที่เขียนด้วย schema เก่า -> tag ใหม่ไม่มีทางโผล่
   ไฟล์นี้ **เขียนความจำใหม่ด้วย 4B จริง** แล้ววัดว่า 8B ตอบถูกเจ้าของไหม
   = วัดทั้ง write path (4B) และ read path (8B) ต่อกันจริงตามสถาปัตยกรรมของเรา

ที่มา (ผู้ใช้ชี้): "เราใช้ qwen3:4B จด แล้ว RAG ดึงให้ 8B ตอบ ถ้า 9/18 มาจาก write path
จริงจากหลักฐานก็ลองแก้ดู" -> หาหลักฐานแล้วพบว่ามาจาก write path จริง:
    tag ในความจำจริงติดผิดชนิด 28/144 = 19%
    me_pref (54) > me_fact (42) ทั้งที่รอสเต้แทบไม่เคยแสดงความชอบเอง
    ทำซ้ำได้ที่ temperature 0: "รอสเต้แนะนำ Pomodoro" -> me_pref:วิธี Pomodoro

เทียบ 2 schema บนบทสนทนาชุดเดียวกัน:
    old = pref/fact เท่านั้น (ของเดิม)
    new = + user_ask / me_suggest
"""
import argparse
import asyncio
import json
import logging
import os
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

import memory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from config import OLLAMA_EXTRACT_MODEL, OLLAMA_MODEL, OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)

# บทสนทนาที่ "ผู้ใช้ขอ / รอสเต้เสนอ" — รูปแบบที่ทำให้เกิด attribution error
# แต่ละอันมีคำถามล่อที่ถามราวกับผู้ใช้ทำสิ่งนั้นอยู่แล้ว
CASES = [
    ([{"role": "user", "content": "งานหนักมาก ขอวิธีจัดการเวลาหน่อย"},
      {"role": "assistant", "content": "ลองเทคนิค Pomodoro ดูไหมคะ ทำ 25 นาที พัก 5 นาที"},
      {"role": "user", "content": "โอเค"}],
     "ผมใช้เทคนิค Pomodoro อยู่ใช่ไหม"),
    ([{"role": "user", "content": "ขอคำกล่าวขอบคุณแบบเป็นทางการหน่อย"},
      {"role": "assistant", "content": "ลองใช้ 'ขอขอบพระคุณเป็นอย่างสูง' ค่ะ"}],
     "ผมเคยใช้คำกล่าวขอบคุณแบบไหน"),
    ([{"role": "user", "content": "เบื่อจัง อ่านหนังสือไม่ลงเลย"},
      {"role": "assistant", "content": "ลองเปลี่ยนบรรยากาศไปอ่านที่ร้านกาแฟดูไหมคะ"}],
     "ผมเปลี่ยนบรรยากาศยังไงตอนเบื่อ"),
    ([{"role": "user", "content": "งานเยอะมาก ไม่รู้จะเริ่มตรงไหน"},
      {"role": "assistant", "content": "ลองจัดลำดับความสำคัญก่อนค่ะ เอางานด่วนขึ้นก่อน"}],
     "ผมจัดลำดับความสำคัญยังไง"),
    ([{"role": "user", "content": "อยากได้คำพูดเป็นทางการไว้ใช้ในที่ประชุม"},
      {"role": "assistant", "content": "เช่น 'ขออนุญาตนำเสนอ' หรือ 'ขอเรียนให้ทราบ' ค่ะ"}],
     "ผมชอบพูดเป็นทางการใช่ไหม"),
]

_CORRECT = ("เคยแนะนำ", "เคยเสนอ", "รอสเต้แนะนำ", "ที่แนะนำไป", "ได้แนะนำ", "แนะนำให้",
            "คุณเคยขอ", "คุณขอ", "คุณเคยถาม", "คุณต้องการ", "ที่คุณขอ", "เสนอให้")
_CONFUSE = ("คุณใช้", "คุณจัดการ", "คุณชอบ", "คุณเคยใช้", "คุณทำ", "ใช่ค่ะ", "ใช่แล้ว",
            "ถูกต้อง", "คุณเป็นคน")


def classify(ans: str) -> str:
    a = re.sub(r"\s+", "", ans)
    c = any(re.sub(r"\s+", "", k) in a for k in _CORRECT)
    x = any(re.sub(r"\s+", "", k) in a for k in _CONFUSE)
    if c and not x:
        return "correct"
    if x and not c:
        return "confuse"
    return "correct" if c else "unclear"


async def post(model: str, prompt: str, as_json: bool) -> str:
    pl = {"model": model, "messages": [{"role": "user", "content": prompt}],
          "stream": False, "think": False, "options": {"temperature": 0}}
    if as_json:
        pl["format"] = "json"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=pl, timeout=180) as r:
                d = await r.json()
        raw = d.get("message", {}).get("content", "") or ""
        return raw.rsplit("</think>", 1)[-1] if "</think>" in raw else raw
    except Exception as e:
        return f"(error {type(e).__name__})"


def strip_new_tags(prompt: str) -> str:
    """จำลอง schema เก่า — เอาบรรทัด user_ask/me_suggest และกฎ 2 ข้อใหม่ออก"""
    keep = [ln for ln in prompt.split("\n")
            if "user_ask:" not in ln and "me_suggest:" not in ln
            and "= user_ask" not in ln and "= me_suggest" not in ln]
    return "\n".join(keep).replace(" *จริงๆ*", "")


async def run(schema: str, rounds: int) -> dict:
    tally = {"correct": 0, "confuse": 0, "unclear": 0}
    mistag = 0
    for pairs, probe in CASES:
        p = memory.build_summary_prompt(pairs)
        if schema == "old":
            p = strip_new_tags(p)
        line = memory.parse_summary_json(await post(OLLAMA_EXTRACT_MODEL, p, True))
        if not line:
            continue
        parts = memory.split_owner_tags(line)
        # ติดผิดชนิด = คำขอ/ข้อเสนอ ไปโผล่ใน pref
        for v in parts["user_pref"]:
            if v.startswith(("ต้องการ", "ขอ", "อยาก", "สนใจ")):
                mistag += 1
        for v in parts["me_pref"]:
            if v.startswith(("แนะนำ", "ลอง", "วิธี", "เทคนิค")):
                mistag += 1
        whose = memory.guess_owner(probe)
        ctx = "\n".join(f"- {x}" for x in memory.filter_by_owner([line], whose))
        ask = ("คุณคือรอสเต้ ผู้ช่วยหญิงพูดไทย ลงท้าย ค่ะ/นะคะ\n\n"
               "เรื่องที่เคยคุยกันก่อนหน้า:\n" + ctx +
               "\n\nตอบคำถามสั้นๆ ตามความทรงจำข้างบนเท่านั้น\n"
               f"ผู้ใช้: {probe}\nรอสเต้:")
        for _ in range(rounds):
            tally[classify(await post(OLLAMA_MODEL, ask, False))] += 1
    return {"tally": tally, "mistag": mistag}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    print("=" * 92)
    print(" schema ใหม่ (user_ask/me_suggest) แก้ attribution error ได้ไหม")
    print(f" {len(CASES)} บทสนทนา × {args.rounds} รอบ · เขียนด้วย {OLLAMA_EXTRACT_MODEL}"
          f" ตอบด้วย {OLLAMA_MODEL}")
    print("=" * 92)

    res = {}
    for schema in ("old", "new"):
        res[schema] = await run(schema, args.rounds)
        t = res[schema]["tally"]
        n = sum(t.values())
        print(f"   {schema:<5} ถูก {t['correct']:>2} · สับสน {t['confuse']:>2} · "
              f"ไม่ชัด {t['unclear']:>2}  · tag ติดผิดชนิด {res[schema]['mistag']}")

    print("\n" + "=" * 92)
    print(f" {'schema':<10}{'ระบุถูก':>12}{'สับสน':>12}{'error rate':>16}{'ช่วง 95%':>16}")
    print("-" * 92)
    for schema in ("old", "new"):
        t = res[schema]["tally"]
        n = sum(t.values()) or 1
        lo, hi = wilson(t["confuse"], n)
        print(f" {schema:<10}{t['correct']:>8}/{n:<4}{t['confuse']:>8}/{n:<4}"
              f"{t['confuse']/n*100:>12.0f}%{lo*100:>10.0f}-{hi*100:<6.0f}%")
    print("=" * 92)

    a, b = res["old"]["tally"], res["new"]["tally"]
    na, nb = sum(a.values()) or 1, sum(b.values()) or 1
    la, ha = wilson(a["confuse"], na)
    lb, hb = wilson(b["confuse"], nb)
    ov = not (lb > ha or la > hb)
    print(f"\n {'ซ้อนทับ = แยกไม่ออก' if ov else 'ต่างจริง ✅'}"
          f"  ({b['confuse']}/{nb} vs {a['confuse']}/{na})")
    print(f" tag ติดผิดชนิด: {res['old']['mistag']} -> {res['new']['mistag']}")


if __name__ == "__main__":
    asyncio.run(main())
