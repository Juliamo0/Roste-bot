"""ซ่อม vector store ให้ตรงกับ JSON — แก้ drift ที่สะสมมาก่อนหน้า

JSON เป็น **source of truth** · vector เป็น **derived index** ที่สร้างใหม่ได้เสมอ
(รูปแบบมาตรฐานของการ sync vector store กับแหล่งข้อมูลหลัก — ทำให้ reconcile ทางเดียว)

ทำ 2 อย่าง:
    1. summary ที่อยู่ใน JSON แต่ไม่มีใน vector  -> เขียนเพิ่ม (embed ใหม่)
    2. summary ที่อยู่ใน vector แต่ไม่มีใน JSON  -> ลบทิ้ง (ของที่ถูกตัดตามเพดานแล้ว)

⚠️ ค่าเริ่มต้นเป็น dry-run — ต้องใส่ --apply ถึงจะเขียนจริง (แตะข้อมูลผู้ใช้)
⚠️ id เดิมเป็น timestamp จึงเทียบกับ id ใหม่ (hash เนื้อหา) ไม่ได้ → เทียบด้วย *ข้อความ*
   แล้วเขียนใหม่ด้วย id ใหม่ ของเก่าที่ id ไม่ตรงจะถูกลบทิ้งในขั้นที่ 2
"""
import argparse
import asyncio
import glob
import io
import json
import logging
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402
import vectormemory  # noqa: E402

logging.disable(logging.CRITICAL)


async def repair_user(uid: str, apply: bool) -> dict:
    path = f"memory/{uid}.json"
    if not os.path.exists(path):
        return {}
    js = [e["text"] if isinstance(e, dict) else e
          for e in json.load(open(path, encoding="utf-8")).get("summaries", [])]
    js_set = set(js)

    coll = vectormemory._convmem_collection(int(uid))
    got = coll.get()
    vec_docs = got.get("documents") or []
    vec_ids = got.get("ids") or []
    vec_set = set(vec_docs)

    missing = [t for t in js if t not in vec_set]           # มีใน JSON ไม่มีใน vector
    extra_idx = [i for i, d in enumerate(vec_docs) if d not in js_set]
    extra_ids = [vec_ids[i] for i in extra_idx]             # มีใน vector ไม่มีใน JSON

    # id ที่ยังเป็นรูปแบบเก่า (timestamp) — เขียนใหม่ให้เป็น hash เพื่อให้ upsert idempotent
    stale_id = [vec_ids[i] for i, d in enumerate(vec_docs)
                if d in js_set and vec_ids[i] != vectormemory._summary_id(d)]

    if apply:
        for t in missing:
            await vectormemory.add_conversation_memory(int(uid), t)
        if extra_ids:
            coll.delete(ids=extra_ids)
        # เขียนทับด้วย id ใหม่ แล้วลบ id เก่าทิ้ง
        for i, d in enumerate(vec_docs):
            if d in js_set and vec_ids[i] != vectormemory._summary_id(d):
                await vectormemory.add_conversation_memory(int(uid), d)
        if stale_id:
            coll.delete(ids=stale_id)

    return {"json": len(js), "vector": len(vec_docs), "missing": len(missing),
            "extra": len(extra_ids), "stale_id": len(stale_id)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="เขียนจริง (ค่าเริ่มต้น = dry-run)")
    args = ap.parse_args()

    print("=" * 92)
    print(" ซ่อม vector store ให้ตรงกับ JSON (JSON = source of truth)")
    print(f" โหมด: {'APPLY (เขียนจริง)' if args.apply else 'DRY-RUN (ไม่เขียน)'}")
    print("=" * 92)
    print(f" {'ผู้ใช้':<22} {'json':>5} {'vector':>7} {'ขาด':>5} {'เกิน':>5} {'id เก่า':>8}")
    print("-" * 92)

    total = {"missing": 0, "extra": 0, "stale_id": 0}
    for f in sorted(glob.glob("memory/*.json")):
        uid = os.path.basename(f)[:-5]
        if not uid.isdigit():
            continue
        r = await repair_user(uid, args.apply)
        if not r or (r["json"] == 0 and r["vector"] == 0):
            continue
        for k in total:
            total[k] += r[k]
        flag = "" if (r["missing"] == r["extra"] == r["stale_id"] == 0) else "  <-- ต้องซ่อม"
        print(f" {uid[:20]:<22} {r['json']:>5} {r['vector']:>7} {r['missing']:>5}"
              f" {r['extra']:>5} {r['stale_id']:>8}{flag}")

    print("-" * 92)
    print(f" รวม: ขาด {total['missing']} · เกิน {total['extra']} · id รูปแบบเก่า {total['stale_id']}")
    if not args.apply and any(total.values()):
        print("\n รันด้วย --apply เพื่อซ่อมจริง")
    print("=" * 92)


if __name__ == "__main__":
    asyncio.run(main())
