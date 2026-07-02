"""
simulate_vectormemory.py — ทดสอบ vectormemory.py (RAG PDF + semantic recall) แบบ end-to-end

ขั้นตอน:
  Phase 1: สร้าง PDF ทดสอบ (มีข้อความ+ facts ฝังอยู่หลายจุด) → ingest_pdf → ยิงคำถามเจาะจง
           ตรวจว่า query_pdf ดึง chunk ที่ถูกต้องมา (และกรองคำถามไม่เกี่ยวข้องทิ้ง)
  Phase 2: seed vector memory ด้วยบทสนทนา 3 หัวข้อ → ยิงคำถามหลายแบบ
           ตรวจว่า query_conversation_memory ดึงเฉพาะเรื่องที่เกี่ยวข้องจริง

ทั้งสอง phase ปริ้น "ระยะห่าง embedding ดิบ" (ด่าน 1) ควบคู่กับผลลัพธ์หลัง rerank (ด่าน 2)
เพื่อโชว์เคสก้ำกึ่งที่เคยแยกไม่ออกด้วย distance threshold เดียว — โดยเฉพาะคู่
"ย้าย server ไป Nakhon" (ควรดึง, distance 0.4642) กับ "แผนเที่ยวเชียงใหม่ vs ถามอากาศ"
(ไม่ควรดึง, distance 0.4692) ที่ต่างกันแค่ 0.005 (ตัวเลขนี้มาจากการคาลิเบรตจริงตอนพัฒนา
ระบบนี้ — ดู MAX_DISTANCE เดิมที่ถูกถอดออกไปแล้วใน vectormemory.py)

รัน: python simulate_vectormemory.py
(ต้อง Ollama กำลังทำงานที่ localhost:11434, pull โมเดล bge-m3 ไว้แล้ว: `ollama pull bge-m3`
 — ไม่ต้อง pull โมเดล rerank แยก เพราะ rerank ใช้ qwen3:8b ตัวเดียวกับที่บอทตอบแชตอยู่แล้ว)
"""
import asyncio
import os
import pathlib
import sys
import textwrap

# กัน UnicodeEncodeError บน Windows console (cp874/cp1252) ตอนปริ้นข้อความไทย/สัญลักษณ์
# (bot.py ทำแบบนี้อยู่แล้วที่บรรทัดแรกๆ ของไฟล์ — ที่นี่ทำเองเพราะสคริปต์นี้ไม่ได้ import bot)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)  # ให้ chroma_db/ ชี้ที่เดียวกับตอนบอทรันจริง
sys.path.insert(0, str(PROJECT_ROOT))  # ให้ import vectormemory เจอ (root ไม่ได้อยู่ใน sys.path เดิม)

import vectormemory  # noqa: E402 — หลัง chdir/sys.path เพื่อให้ path ของ ChromaDB ถูกต้อง

TEST_USER_ID = 444_444_444_444_444_444   # ไม่ชนกับ test user ของสคริปต์อื่น (111/222/333)


def hr(char="─", w=66):
    print(char * w)


async def show_raw_topk(coll, question: str, label: str = "") -> None:
    """ปริ้น top-k ดิบจาก embedding พร้อม cosine distance (ก่อน rerank)
    ให้เห็นว่าด่าน 1 (embedding) แยกเคสก้ำกึ่งไม่ออก — ต้องพึ่งด่าน 2 (rerank) มาตัดสิน"""
    if coll.count() == 0:
        return
    emb = await vectormemory.get_embedding(question)
    if emb is None:
        return
    result = coll.query(query_embeddings=[emb], n_results=min(vectormemory.RETRIEVE_K, coll.count()))
    docs = (result.get("documents") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    tag = f" ({label})" if label else ""
    print(f"    🔬 ด่าน 1 (embedding) — top-{len(docs)} ดิบ ก่อน rerank{tag}:")
    for d, dist in zip(docs, dists):
        short = d[:60] + ("…" if len(d) > 60 else "")
        print(f"       distance={dist:.4f}  {short}")


# ============================================================
#  🔧 helper: สร้าง PDF ขั้นต่ำแบบ hand-rolled (ไม่ต้องพึ่ง reportlab/fpdf)
#      แค่พอให้ pypdf.PdfReader().extract_text() อ่านข้อความคืนมาได้จริง
# ============================================================
def _build_minimal_pdf(paragraph: str) -> bytes:
    lines = textwrap.wrap(paragraph, width=90)

    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content_lines = ["BT", "/F1 11 Tf", "40 780 Td", "14 TL"]
    for line in lines:
        content_lines.append(f"({esc(line)}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    content_stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>"
        b"/MediaBox[0 0 612 792]/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length " + str(len(content_stream)).encode() + b">>\nstream\n"
        + content_stream + b"\nendstream",
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]  # object 0 (free) — placeholder ตาม spec
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_start = len(buf)
    n = len(objects) + 1
    buf += f"xref\n0 {n}\n".encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += f"trailer\n<</Size {n}/Root 1 0 R>>\nstartxref\n{xref_start}\n%%EOF".encode()
    return bytes(buf)


# ============================================================
#  📄 Phase 1 — RAG PDF
# ============================================================
FILLER = (
    "This section describes routine operations of the Roste home assistant project. "
    "It covers logging conventions, backup schedules, and general maintenance notes "
    "that are not particularly important for this test but exist to pad the document "
    "length so it splits into multiple retrieval chunks. "
)

PDF_PARAGRAPH = (
    FILLER * 2
    + "The secret unlock code for the garden gate is ORCHID-7. Only the head gardener "
    "knows this code and it should not be shared with anyone else. "
    + FILLER * 2
    + "The new Roste bot server rack will be relocated to Nakhon Si Thammarat in "
    "August 2026 for better cooling and lower electricity cost. "
    + FILLER * 2
    + "Fuel price data for the bot is scraped from the Kapook gas price page, and "
    "the scrape job runs every morning at 7 AM Thailand time. "
    + FILLER * 2
)

PDF_CASES = [
    {"q": "What is the unlock code for the garden gate?", "expect_kw": "ORCHID", "should_find": True},
    {"q": "Where will the server rack be relocated to?", "expect_kw": "Nakhon", "should_find": True},
    {"q": "Where does the bot scrape fuel price data from?", "expect_kw": "Kapook", "should_find": True},
    {"q": "What is the capital city of France?", "expect_kw": None, "should_find": False},
]


async def phase1_pdf():
    hr("═")
    print("  Phase 1: RAG PDF — ingest + query")
    hr("═")

    pdf_bytes = _build_minimal_pdf(PDF_PARAGRAPH)
    print(f"  📄 สร้าง PDF ทดสอบ {len(pdf_bytes)} bytes (ข้อความ {len(PDF_PARAGRAPH)} ตัวอักษร)")

    n_chunks = await vectormemory.ingest_pdf(TEST_USER_ID, "test_facts.pdf", pdf_bytes)
    print(f"  ✅ ingest_pdf เก็บได้ {n_chunks} chunk(s)")
    if n_chunks == 0:
        print("  ⚠️  ingest ได้ 0 chunk — PDF อาจสร้างผิดพลาด หรือ extract_text() อ่านไม่ออก ข้าม phase นี้")
        return 0, 0

    coll = vectormemory._pdf_collection(TEST_USER_ID)

    passed = failed = 0
    for case in PDF_CASES:
        hr()
        print(f"  คำถาม: {case['q']!r}")
        await show_raw_topk(coll, case["q"])

        hits = await vectormemory.query_pdf(TEST_USER_ID, case["q"], top_k=3)
        found = any(case["expect_kw"] and case["expect_kw"] in h for h in hits) if case["expect_kw"] else False
        got = found if case["should_find"] else (not found)
        status = "✅ PASS" if got else "❌ FAIL"
        passed += got
        failed += not got

        print(f"  {status}")
        print(f"  คาดหวัง: {'เจอคำว่า ' + case['expect_kw'] if case['should_find'] else 'ไม่ควรเจอ keyword ที่ไม่เกี่ยวข้อง'}")
        print(f"    🎯 ด่าน 2 (rerank) — ผลลัพธ์สุดท้าย:")
        if hits:
            for h in hits:
                short = h[:100] + ("…" if len(h) > 100 else "")
                print(f"    📎 {short}")
        else:
            print("    (query_pdf คืน [] — ไม่มี chunk ไหนใกล้พอ)")
        print()

    hr("═")
    print(f"  Phase 1 สรุป: {passed}/{len(PDF_CASES)} passed")
    hr("═")
    print()
    return passed, failed


# ============================================================
#  🔎 Phase 2 — semantic conversation memory
# ============================================================
SEED_MEMORIES = [
    "คุยเรื่องการเลี้ยงแมวเปอร์เซีย ชื่อเหมียว ชอบกินปลาทู",
    "คุยเรื่องสูตรทำต้มยำกุ้งแบบใต้ ใส่กะทิเยอะๆ",
    "คุยเรื่องแผนไปเที่ยวเชียงใหม่เดือนหน้ากับเพื่อน",
    "คุยเรื่องซ่อมจักรยานที่ล้อแบนไปร้านแถวบ้าน",
    "คุยเรื่องหนังสือ sci-fi เล่มใหม่ที่เพิ่งซื้อมาอ่าน",
]  # 5 เรื่อง = เท่ากับ RETRIEVE_K พอดี ทำให้ query "ไม่เคยคุย" ด้านล่างต้องคัดทิ้งทั้ง 5 อันจริงๆ

RECALL_CASES = [
    {"label": "1. ถามเรื่องแมว", "msg": "แมวที่บ้านชอบกินอะไรนะ", "should_recall": True},
    {"label": "2. ถามเรื่องอากาศ (ไม่เกี่ยวข้อง)", "msg": "พยากรณ์อากาศพรุ่งนี้เป็นยังไงบ้าง", "should_recall": False},
    {"label": "3. ถามเรื่องต้มยำกุ้ง", "msg": "อยากทำต้มยำกุ้งกินที่บ้านเย็นนี้", "should_recall": True},
    {"label": "4. ถามเรื่องเชียงใหม่", "msg": "แผนเที่ยวเชียงใหม่คราวก่อนเป็นไงบ้าง", "should_recall": True},
    {"label": "5. ถามเรื่องน้ำมัน (ไม่เกี่ยวข้อง)", "msg": "ราคาน้ำมันวันนี้เท่าไหร่แล้วนะ", "should_recall": False},
    {
        "label": "6. ถามเรื่องที่ไม่เคยคุยมาก่อนเลย (เทส RETRIEVE_K=5 เต็มจำนวน)",
        "msg": "ช่วยแนะนำวิธีลงทุนกองทุนรวมสำหรับมือใหม่หน่อย",
        "should_recall": False,
    },
]


async def phase2_convmem():
    hr("═")
    print("  Phase 2: semantic conversation memory — seed + query")
    hr("═")

    for text in SEED_MEMORIES:
        await vectormemory.add_conversation_memory(TEST_USER_ID, text)
    print(f"  🌱 seed แล้ว {len(SEED_MEMORIES)} ความทรงจำ")
    print()

    coll = vectormemory._convmem_collection(TEST_USER_ID)

    passed = failed = 0
    for case in RECALL_CASES:
        hr()
        print(f"  {case['label']}")
        print(f"  ข้อความ: {case['msg']!r}")
        await show_raw_topk(coll, case["msg"])

        hits = await vectormemory.query_conversation_memory(TEST_USER_ID, case["msg"])
        got = len(hits) > 0
        ok = got == case["should_recall"]
        status = "✅ PASS" if ok else "❌ FAIL"
        passed += ok
        failed += not ok

        print(f"  {status}")
        print(f"  คาดหวัง: {'ควรดึงความทรงจำมา' if case['should_recall'] else 'ไม่ควรดึงอะไรมา (ไม่เกี่ยวข้อง)'}")
        print(f"    🎯 ด่าน 2 (rerank) — ผลลัพธ์สุดท้าย:")
        if hits:
            for h in hits:
                print(f"    📝 {h}")
        else:
            print("    (query_conversation_memory คืน [] )")
        print()

    hr("═")
    print(f"  Phase 2 สรุป: {passed}/{len(RECALL_CASES)} passed")
    hr("═")
    print()
    return passed, failed


# ============================================================
#  main
# ============================================================
async def main():
    hr("═")
    print("  จำลองทดสอบ vectormemory.py (RAG PDF + semantic recall)")
    print(f"  TEST_USER_ID = {TEST_USER_ID}")
    hr("═")
    print()

    p1_pass, p1_fail = await phase1_pdf()
    p2_pass, p2_fail = await phase2_convmem()

    total_pass = p1_pass + p2_pass
    total_fail = p1_fail + p2_fail
    hr("═")
    print(f"  🏁 รวมทั้งหมด: {total_pass}/{total_pass + total_fail} passed"
          f"{'  ✅ ทั้งหมดผ่าน' if total_fail == 0 else f'  ❌ {total_fail} ไม่ผ่าน'}")
    hr("═")

    # ──── เก็บกวาด collection ทดสอบ ─────────────────────────────────────────
    print()
    print(f"ลบ collection ทดสอบ (pdf_{TEST_USER_ID}, convmem_{TEST_USER_ID}) ออกไหม? (y/n) ",
          end="", flush=True)
    try:
        ans = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "y"
    if ans != "n":
        for name in (f"pdf_{TEST_USER_ID}", f"convmem_{TEST_USER_ID}"):
            try:
                vectormemory._client.delete_collection(name)
            except Exception:
                pass
        print("   ลบแล้ว")
    else:
        print("   เก็บไว้")


if __name__ == "__main__":
    asyncio.run(main())
