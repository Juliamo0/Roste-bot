"""เทียบ 2 วิธีส่งความทรงจำให้โมเดล — ยัดเข้า context ล่วงหน้า vs ให้โมเดลค้นเอง

⚠️ ไม่แตะ production — prototype อยู่ใน memory_tool_proto.py

  P1 ยัดเข้า context (ปัจจุบัน) — recall_summaries เดาว่าอันไหนเกี่ยว แล้วยัด 5 อันเข้า
     system prompt ทุกครั้งที่เจอคำใบ้อดีต โมเดลไม่มีสิทธิ์เลือก
  P2 ให้โมเดลค้นเอง         — ไม่ยัดอะไร แต่ยื่น tool search_memory(query, whose) ให้
     โมเดลเรียกเองเมื่อรู้ว่าต้องการ

ทำไมต้องเทียบ: วิธี F (แยกเจ้าของด้วย tag) บันทึกได้ถูก 87% แต่ตอน recall กลายเป็น
*ข้อความดิบ* ใน system prompt — โมเดลต้องตีความ "user_pref:" เอง ซึ่งเป็นสิ่งที่วัดแล้วว่า
ทำได้ไม่ดี P2 ทำให้ "ของใคร" เป็น parameter จริงที่ระบบกรองให้ก่อนส่ง

วัด 3 ฝั่งพร้อมกัน (บทเรียนจาก bench_attention: แก้ทางหนึ่งมักพังอีกทาง):
  1. ความจำ    — ตอบเรื่องที่เคยคุยได้ไหม + แยกเจ้าของถูกไหม
  2. ข้อมูลสด  — ยังเรียก tool ข้อมูลจริงถูกไหม (P2 เพิ่ม tool = เสี่ยงชนเกณฑ์ 3,700c
                 ที่วัดได้ว่าทำให้โมเดลลืม summary — ปัญหาที่เพิ่งแก้เมื่อวาน)
  3. ต้นทุน    — ขนาด context + จำนวนรอบที่ยิงโมเดล (P2 ต้อง 2 รอบ: เรียก tool แล้วตอบ)
"""
import argparse
import asyncio
import copy
import json
import math
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging  # noqa: E402

import llm_tools  # noqa: E402
import ollama_client  # noqa: E402
import persona  # noqa: E402
from memory_tool_proto import (  # noqa: E402
    SEARCH_MEMORY_TOOL, build_memory_block, guess_owner, search_memory, tool_size,
)

logging.disable(logging.CRITICAL)

# ความทรงจำจำลองรูปแบบ F (แยกเจ้าของ) — คุมเนื้อหาได้ จึงรู้คำตอบที่ถูกล่วงหน้า
SUMMARIES = [
    "31 ก.ค.: คุยเรื่องแนวนิยายที่ชอบ | user_pref:ชอบนิยายสืบสวน me_pref:ชอบแนวแฟนตาซี",
    "30 ก.ค.: คุยเรื่องอาหาร | user_fact:กินเผ็ดไม่ได้ me_pref:ไม่ชอบของหวาน",
    "29 ก.ค.: คุยงานอดิเรก | user_pref:ชอบเล่นเกม me_pref:ชอบซ่อมหุ่นยนต์",
    "28 ก.ค.: คุยเรื่องราคาน้ำมันและอากาศ",
    "27 ก.ค.: คุยเรื่องร้านก๋วยเตี๋ยวแถวชุมพร | user_fact:อยู่ชุมพร",
]

# (คำถาม, ชนิด, คำที่ต้องมี, คำที่ห้ามมี)
#   mem_user = ถามเรื่องของผู้ใช้   mem_me = ถามเรื่องของรอสเต้เอง
#   live     = ข้อมูลสด (ต้องเรียก tool จริง ไม่ใช่ search_memory)
CASES = [
    ("ผมชอบอ่านนิยายแนวไหนนะ จำได้ไหม", "mem_user", ["สืบสวน"], ["แฟนตาซี"]),
    ("รอสเต้ชอบอ่านแนวไหนเหรอ จำได้ไหม", "mem_me", ["แฟนตาซี"], ["สืบสวน"]),
    ("จำได้ไหมว่าผมกินเผ็ดได้ไหม", "mem_user", ["เผ็ด"], []),
    ("รอสเต้ไม่ชอบกินอะไรนะ จำได้ไหม", "mem_me", ["หวาน"], ["เผ็ด"]),
    ("เคยคุยเรื่องงานอดิเรกกันไหม ผมชอบอะไร", "mem_user", ["เกม"], []),
    ("พรุ่งนี้ฝนตกไหม", "live", [], []),
    ("ราคาน้ำมันวันนี้เท่าไหร่", "live", [], []),
]

WANT_TOOL = {"พรุ่งนี้ฝนตกไหม": "get_weather",
             "ราคาน้ำมันวันนี้เท่าไหร่": "get_oil_price"}

DENIAL = ["ไม่เคย", "ไม่ได้คุย", "จำไม่ได้", "ไม่มีข้อมูล", "ไม่แน่ใจ"]


def _base_messages(question: str, memory_block: str = "") -> list:
    sp = persona.SYSTEM_PROMPT
    if memory_block:
        sp += (
            "\n\nเรื่องที่เคยคุยกันก่อนหน้า (รอสเต้จำได้จริง — นี่คือความทรงจำของคุณเอง):\n"
            + memory_block
            + "\nถ้าผู้ใช้ถามว่าเคยคุยเรื่องนี้กันไหม/จำได้ไหม แล้วอยู่ในรายการข้างบน "
              "= เคยคุยกันจริง ให้ยืนยันแล้วเล่าเท่าที่จำได้ ห้ามตอบว่าไม่เคยคุย"
        )
    return ([{"role": "system", "content": sp}]
            + copy.deepcopy(persona.FEWSHOT_EXAMPLES)
            + [{"role": "system", "content": persona.build_author_note()},
               {"role": "user", "content": question}])


def _first_tool(msg):
    calls = msg.get("tool_calls") or []
    if not calls:
        return None, {}
    fn = calls[0].get("function") if isinstance(calls[0], dict) else None
    if not isinstance(fn, dict):
        return None, {}
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    return fn.get("name"), args


async def run_p1(question: str, kind: str):
    """ยัด summary เข้า context ล่วงหน้า (พฤติกรรมปัจจุบัน)"""
    block = ""
    ctx_extra = 0
    if kind.startswith("mem"):
        # จำลอง recall_summaries: คืนทุกอันที่มีคำตรง (ไม่รู้ว่าถามฝั่งไหน)
        block = "\n".join(f"- {s}" for s in SUMMARIES[:5])
        ctx_extra = len(block)
    tools = llm_tools.select_tools(question)
    msgs = _base_messages(question, block)
    t0 = time.perf_counter()
    msg = await ollama_client._chat_once(msgs, temperature=0.8, tools=tools)
    name, _ = _first_tool(msg)
    content = ollama_client._strip_think(msg.get("content", "") or "")
    return dict(reply=content, tool=name, rounds=1,
                ctx=ctx_extra + sum(tool_size(t) for t in tools),
                secs=time.perf_counter() - t0)


async def run_p2(question: str, kind: str):
    """ให้โมเดลเรียก search_memory เอง — ไม่ยัดอะไรล่วงหน้า"""
    tools = llm_tools.select_tools(question) + [SEARCH_MEMORY_TOOL]
    msgs = _base_messages(question)
    t0 = time.perf_counter()
    msg = await ollama_client._chat_once(msgs, temperature=0.8, tools=tools)
    name, args = _first_tool(msg)
    rounds = 1
    content = ollama_client._strip_think(msg.get("content", "") or "")

    if name == "search_memory":
        result = search_memory(SUMMARIES, args.get("query", question),
                               args.get("whose", "any"))
        msgs.append({"role": "assistant", "content": "", "tool_calls": msg["tool_calls"]})
        msgs.append({"role": "tool", "tool_name": "search_memory", "content": result})
        msg2 = await ollama_client._chat_once(msgs, temperature=0.8, tools=[])
        content = ollama_client._strip_think(msg2.get("content", "") or "")
        rounds = 2

    return dict(reply=content, tool=name, rounds=rounds,
                ctx=sum(tool_size(t) for t in tools),
                secs=time.perf_counter() - t0,
                whose=args.get("whose") if name == "search_memory" else None)


async def run_p3(question: str, kind: str):
    """ยัดเข้า context เหมือน P1 แต่ *กรองฝั่งเจ้าของก่อนยัด* ด้วย rule

    ได้ความเชื่อถือได้ของ P1 (ไม่ต้องพึ่งโมเดลตัดสินใจเรียก tool ซึ่งวัดแล้วว่าทำได้ 36%)
    บวกการกรองฝั่งของ P2 (ที่ P1 ทำไม่ได้เลย จึงสลับเจ้าของ 10/25)
    """
    block, whose = "", None
    ctx_extra = 0
    if kind.startswith("mem"):
        block, whose = build_memory_block(SUMMARIES, question)
        ctx_extra = len(block)
    tools = llm_tools.select_tools(question)
    msgs = _base_messages(question, block)
    t0 = time.perf_counter()
    msg = await ollama_client._chat_once(msgs, temperature=0.8, tools=tools)
    name, _ = _first_tool(msg)
    content = ollama_client._strip_think(msg.get("content", "") or "")
    return dict(reply=content, tool=name, rounds=1,
                ctx=ctx_extra + sum(tool_size(t) for t in tools),
                secs=time.perf_counter() - t0, whose=whose)


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    """ช่วงความเชื่อมั่น 95% แบบ Wilson — ที่ n น้อยสูตรปกติให้ช่วงแคบเกินจริง

    เหตุผลที่ต้องมี: รอบก่อนวัดที่ n=25 แล้ว P1 ได้ 56% กับ 64% ในสองรอบติดกัน ซึ่งต่างกัน
    8% — ถ้าไม่มีช่วงความเชื่อมั่นจะแยกไม่ออกว่าเป็นความต่างจริงหรือ noise (บทเรียนเดียวกับ
    ตอน pass^8 ที่อันดับสลับกันจนเกือบเลือกผิด)
    """
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def judge(res: dict, question: str, kind: str, must: list, forbid: list) -> tuple:
    bad = []
    reply = res["reply"]
    if kind == "live":
        want = WANT_TOOL.get(question)
        if res["tool"] != want:
            bad.append(f"tool={res['tool']} (ควร {want})")
    else:
        if any(d in reply for d in DENIAL):
            bad.append("ปฏิเสธว่าจำไม่ได้")
        if must and not any(w in reply for w in must):
            bad.append(f"ขาด {must}")
        if forbid and any(w in reply for w in forbid):
            bad.append(f"สลับเจ้าของ (มี {forbid})")
    return (not bad), bad


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()

    print("=" * 100)
    print(f" P1 (ยัดเข้า context) vs P2 (โมเดลค้นเอง) — {len(CASES)} เคส × {args.reps} รอบ")
    print(f" search_memory tool = {tool_size(SEARCH_MEMORY_TOOL)}c   เกณฑ์ที่วัดได้: >3,700c โมเดลเริ่มลืม")
    print("=" * 100)

    rows = []
    for pname, runner in (("P1 ยัดเข้า context", run_p1),
                          ("P2 โมเดลค้นเอง", run_p2),
                          ("P3 กรองฝั่งก่อนยัด", run_p3)):
        stat = {"mem_ok": 0, "mem_n": 0, "live_ok": 0, "live_n": 0,
                "swap": 0, "ctx": [], "secs": [], "rounds": [], "searched": 0,
                "whose_ok": 0}
        fails = []
        print(f"\n{'=' * 100}\n  {pname}\n{'=' * 100}")
        for q, kind, must, forbid in CASES:
            for _ in range(args.reps):
                try:
                    res = await runner(q, kind)
                except Exception as exc:
                    fails.append((q, f"ERROR {exc}"))
                    continue
                ok, bad = judge(res, q, kind, must, forbid)
                stat["ctx"].append(res["ctx"])
                stat["secs"].append(res["secs"])
                stat["rounds"].append(res["rounds"])
                if res.get("tool") == "search_memory":
                    stat["searched"] += 1
                    exp = "user" if kind == "mem_user" else ("me" if kind == "mem_me" else None)
                    if exp and res.get("whose") == exp:
                        stat["whose_ok"] += 1
                if kind == "live":
                    stat["live_n"] += 1
                    stat["live_ok"] += ok
                else:
                    stat["mem_n"] += 1
                    stat["mem_ok"] += ok
                    if any("สลับ" in b for b in bad):
                        stat["swap"] += 1
                if not ok and len(fails) < 6:
                    fails.append((q, ", ".join(bad) + " | " + res["reply"][:70]))

        mn, ln = max(stat["mem_n"], 1), max(stat["live_n"], 1)
        lo, hi = wilson(stat["mem_ok"], stat["mem_n"])
        print(f"   ความจำ   {stat['mem_ok']}/{stat['mem_n']} ({stat['mem_ok']/mn*100:.0f}%)  "
              f"ช่วง 95% [{lo*100:.0f}-{hi*100:.0f}%]   สลับเจ้าของ {stat['swap']}"
              f" ({stat['swap']/mn*100:.0f}%)")
        print(f"   ข้อมูลสด {stat['live_ok']}/{stat['live_n']} ({stat['live_ok']/ln*100:.0f}%)")
        print(f"   context เฉลี่ย {sum(stat['ctx'])/max(len(stat['ctx']),1):.0f}c   "
              f"เวลา {sum(stat['secs'])/max(len(stat['secs']),1):.1f}s   "
              f"รอบเฉลี่ย {sum(stat['rounds'])/max(len(stat['rounds']),1):.2f}")
        if stat["searched"]:
            print(f"   เรียก search_memory {stat['searched']} ครั้ง "
                  f"(ระบุ whose ถูก {stat['whose_ok']})")
        for q, why in fails[:5]:
            print(f"     ❌ {q[:34]} → {why}")
        rows.append(dict(name=pname, ok=stat["mem_ok"], n=stat["mem_n"],
                         lo=lo, hi=hi, swap=stat["swap"],
                         live_ok=stat["live_ok"], live_n=stat["live_n"],
                         ctx=sum(stat["ctx"]) / max(len(stat["ctx"]), 1)))

    print("\n" + "=" * 100)
    print(f" {'วิธี':<24} {'ความจำ':>10} {'ช่วง 95%':>14} {'สลับเจ้าของ':>13} "
          f"{'ข้อมูลสด':>10} {'context':>9}")
    print("-" * 100)
    for r in rows:
        print(f" {r['name']:<24} {r['ok']:>3}/{r['n']:<5} "
              f"[{r['lo']*100:>3.0f}-{r['hi']*100:>3.0f}%]  {r['swap']:>10} "
              f"{r['live_ok']:>6}/{r['live_n']:<3} {r['ctx']:>8.0f}c")
    print("=" * 100)

    print("\n เทียบรายคู่ (ช่วงไม่ซ้อนทับ = ต่างจริง ไม่ใช่ noise):")
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            sep = ("ต่างจริง" if a["lo"] > b["hi"] or b["lo"] > a["hi"]
                   else "แยกไม่ออก")
            better = a["name"] if a["ok"] / max(a["n"], 1) > b["ok"] / max(b["n"], 1) else b["name"]
            note = f" ({better} สูงกว่า)" if sep == "ต่างจริง" else ""
            print(f"   {a['name']:<24} vs {b['name']:<24} {sep}{note}")

    print("\n สิ่งที่ต้องดู: P2 ต้องไม่ทำให้ข้อมูลสดพัง (tool เพิ่ม = เสี่ยงชนเกณฑ์)")
    print(" และต้องแยกเจ้าของได้ดีกว่า P1 จริง ไม่งั้นความซับซ้อนที่เพิ่มมาไม่คุ้ม")


if __name__ == "__main__":
    asyncio.run(main())
