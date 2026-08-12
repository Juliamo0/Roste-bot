"""Phase 0 ข้อ 2: ยืนยันด้วย *ตัวเลข* ว่าสองสโตร์ความจำ drift ออกจากกันจริงไหม

สมมติฐานที่ได้จากการอ่านโค้ด (ยังไม่ใช่ข้อสรุป):
  1. JSON ตัด summary ที่เก่าเกิน MAX_SUMMARIES ทิ้ง — chat.py:475 `summaries[-MAX_SUMMARIES:]`
  2. Chroma ไม่มี delete ใน convmem path เลย — ของที่ JSON ตัดทิ้งยังค้างอยู่ตลอดกาล
  3. id ที่ใช้เขียนคือ `int(time.time()*1000)` (vectormemory.py:253) ซึ่งไม่มีวันซ้ำ
     → `upsert` ทำงานเป็น `insert` เสมอ อัปเดต summary เดิมไม่ได้เลย

⚠️ ทำไมต้องรันจริงแทนที่จะสรุปจากการอ่านโค้ด: MEMORY_EXPERIMENTS §4 บันทึกไว้ว่าเคย
   รายงานว่า find_ungrounded พลาด แล้วตรวจข้อมูลดิบพบว่าเครื่องมือทำงานถูก คนอ่านผิดเอง
   — "ตรวจข้อมูลดิบก่อนสรุปว่าเครื่องมือพัง"

ไม่แตะข้อมูลผู้ใช้: ใช้ user id ทดสอบ แล้วลบ collection ทิ้งท้ายรอบเสมอ
ไม่เรียก LLM rerank (ปิดด้วยการเรียก collection ตรงๆ) → เร็ว ผลไม่แกว่ง
"""
import asyncio
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
import vectormemory  # noqa: E402

logging.disable(logging.CRITICAL)

# id ทดสอบ — ตั้งให้ชนกับของจริงไม่ได้ (discord id เป็นเลข 17-19 หลัก ไม่ขึ้นต้นด้วย 9999)
TEST_UID = 999900000000000001


async def probe_id_collision() -> dict:
    """ข้อ 3: เขียน summary *ข้อความเดียวกัน* สองครั้ง — ควรได้ 1 แถวถ้า upsert ทำงาน"""
    coll = vectormemory._convmem_collection(TEST_UID)
    text = "1 ส.ค.: คุยเรื่องแนวนิยาย | user_pref:ชอบไซไฟ"

    before = coll.count()
    await vectormemory.add_conversation_memory(TEST_UID, text)
    mid = coll.count()
    await vectormemory.add_conversation_memory(TEST_UID, text)  # ข้อความเดิมเป๊ะ
    after = coll.count()

    return {"before": before, "after_first": mid, "after_duplicate": after,
            "duplicated": after > mid}


async def probe_json_vector_drift() -> dict:
    """ข้อ 1+2: เขียนเกิน MAX_SUMMARIES แล้วดูว่า JSON กับ Chroma เหลือเท่ากันไหม

    จำลอง write path ของ chat.py:471-481 ตรงๆ (สรุปเสร็จ → append JSON + ตัด → เขียน vector)
    """
    # ⚠️ ฟังก์ชันนี้จำลอง write path **แบบเดิม** (append + ตัด แต่ไม่ลบฝั่ง vector)
    # ไว้ยืนยันว่าบั๊กเคยมีจริง — หลังแก้แล้ว chat.summarize_and_verify เรียก
    # vectormemory.delete_conversation_memory ให้ด้วย จึงไม่ drift อีก
    # (ทดสอบเส้นจริงได้ที่ tests/test_vectormemory.py + tools/repair_vector_sync.py)
    n_write = memory.MAX_SUMMARIES + 5   # เขียนให้ล้นเพดาน 5 อัน

    # ⚠️ ล้าง collection ก่อนเสมอ — ไม่งั้นของที่ probe [1] เขียนไว้จะค้างมานับรวมด้วย
    #    (รอบแรกที่รันเจอจริง: Chroma รายงาน 107 แทนที่จะเป็น 105 เพราะ 2 แถวจาก probe [1])
    #    ข้อสรุปไม่เปลี่ยน เพราะดูค่า *เปรียบเทียบ* แต่เลขที่พิมพ์ออกมาต้องตรงกับที่เขียนจริง
    try:
        vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    coll = vectormemory._convmem_collection(TEST_UID)

    mem = {"name": "", "preferred_name": "", "facts": [], "history": [], "summaries": []}
    memory.save_memory(TEST_UID, mem)

    for i in range(n_write):
        entry = {"date": "2026-01-01", "text": f"บทที่ {i}: คุยเรื่องหัวข้อที่ {i}"}
        # ── ฝั่ง JSON: เหมือน chat.py:473-476 ──
        mem = memory.load_memory(TEST_UID)
        summaries = mem.get("summaries", [])
        summaries.append(entry)
        mem["summaries"] = summaries[-memory.MAX_SUMMARIES:]
        memory.save_memory(TEST_UID, mem)
        # ── ฝั่ง vector: เหมือน chat.py:481 ──
        await vectormemory.add_conversation_memory(TEST_UID, entry["text"])

    mem = memory.load_memory(TEST_UID)
    json_n = len(mem["summaries"])
    vec_n = coll.count()

    # summary ที่ JSON ตัดทิ้งไปแล้ว — ยังค้นเจอใน Chroma ไหม
    dropped = [f"บทที่ {i}: คุยเรื่องหัวข้อที่ {i}" for i in range(n_write - memory.MAX_SUMMARIES)]
    still_in_vector = []
    for text in dropped:
        got = coll.get(where_document={"$contains": text})
        if got and got.get("ids"):
            still_in_vector.append(text)

    return {"written": n_write, "json_kept": json_n, "vector_kept": vec_n,
            "dropped_from_json": len(dropped),
            "dropped_but_still_in_vector": len(still_in_vector)}


async def probe_no_delete_api() -> dict:
    """ข้อ 2 เสริม: มีทางลบ summary ออกจาก convmem ใน production ไหม"""
    src = (ROOT / "vectormemory.py").read_text(encoding="utf-8")
    # หา .delete( ที่อยู่ในฟังก์ชัน convmem — เทียบกับ pdf ที่มี evict อยู่แล้ว
    has_any_delete = ".delete(" in src
    convmem_section = src[src.find("async def add_conversation_memory"):]
    has_convmem_delete = ".delete(" in convmem_section
    return {"vectormemory_has_any_delete": has_any_delete,
            "convmem_path_has_delete": has_convmem_delete}


def cleanup():
    try:
        vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    try:
        import tools.memory_conflict_fixture as f
        f.uninstall(TEST_UID)
    except Exception:
        p = memory._memory_path(TEST_UID)
        if os.path.exists(p):
            os.remove(p)


async def main():
    print("=" * 92)
    print(" Phase 0 ข้อ 2 — ยืนยันบั๊ก vector drift ด้วยตัวเลข (ไม่เรียก LLM)")
    print(f" MAX_SUMMARIES = {memory.MAX_SUMMARIES}   user id ทดสอบ = {TEST_UID}")
    print("=" * 92)

    cleanup()  # เริ่มจากสภาพสะอาดเสมอ
    try:
        print("\n[1] id ซ้ำได้ไหม — เขียน summary ข้อความเดียวกัน 2 ครั้ง")
        r1 = await probe_id_collision()
        print(f"    ก่อนเขียน={r1['before']}  เขียนครั้งแรก={r1['after_first']}  "
              f"เขียนซ้ำข้อความเดิม={r1['after_duplicate']}")
        if r1["duplicated"]:
            print("    ❌ ยืนยันบั๊ก: ข้อความเดิมกลายเป็นแถวใหม่ → upsert ไม่เคยอัปเดตของเดิมเลย")
        else:
            print("    ✅ ไม่ซ้ำ — สมมติฐานข้อ 3 ผิด ต้องทบทวนแผน")

        print(f"\n[2] JSON vs Chroma — เขียน {memory.MAX_SUMMARIES + 5} อัน (ล้นเพดาน 5)")
        r2 = await probe_json_vector_drift()
        print(f"    เขียนทั้งหมด={r2['written']}  JSON เหลือ={r2['json_kept']}  "
              f"Chroma เหลือ={r2['vector_kept']}")
        print(f"    JSON ตัดทิ้ง={r2['dropped_from_json']} อัน  "
              f"→ ยังค้างใน Chroma={r2['dropped_but_still_in_vector']} อัน")
        if r2["dropped_but_still_in_vector"]:
            print("    ❌ ยืนยันบั๊ก: summary ที่ JSON ลืมไปแล้ว RAG ยังดึงกลับมาได้")
        else:
            print("    ✅ สองสโตร์ตรงกัน — สมมติฐานข้อ 1+2 ผิด ต้องทบทวนแผน")

        print("\n[3] มี API ลบ convmem ไหม")
        r3 = await probe_no_delete_api()
        print(f"    vectormemory.py มี .delete() ที่ไหนสักแห่ง={r3['vectormemory_has_any_delete']}  "
              f"ใน convmem path={r3['convmem_path_has_delete']}")

        print("\n" + "=" * 92)
        drift = r2["dropped_but_still_in_vector"] > 0
        dup = r1["duplicated"]
        print(f" สรุป: id ซ้ำไม่ได้/เขียนทับไม่ได้ = {dup}   สองสโตร์ drift = {drift}")
        if dup and drift:
            print(" → ยืนยันครบ: conflict resolution ที่แก้แค่ฝั่ง JSON จะไม่มีผลกับ RAG")
            print("   ต้องแก้ id ให้เสถียร + เพิ่ม delete ใน Phase 2 ตามแผน")
        print("=" * 92)
    finally:
        cleanup()
        print("\n(ลบข้อมูลทดสอบเรียบร้อย)")


if __name__ == "__main__":
    asyncio.run(main())
