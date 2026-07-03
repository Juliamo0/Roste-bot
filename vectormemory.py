# ============================================================
#  🔎 vectormemory.py — ความจำ/ค้นหาเชิงความหมาย (semantic) ผ่าน ChromaDB
#      ใช้ Ollama (bge-m3) ทำ embedding — รันในเครื่องทั้งหมด ไม่ต้องพึ่ง cloud
#      เก็บ vector ลงดิสก์ที่ chroma_db/ (persist ข้ามการรันบอท)
#
#      แยกจาก memory.py โดยเจตนา — memory.py จำแบบ keyword/fact ตรงตัว
#      ไฟล์นี้ค้นแบบ "ความหมายใกล้เคียง" 2 เรื่อง:
#        1) RAG PDF — ผู้ใช้แนบ PDF มาแล้วถามถึงเนื้อหาทีหลังได้
#        2) semantic recall — เสริม recall_summaries (keyword) ด้วยการค้นความหมาย
#
#      สถาปัตยกรรม: retrieve top-k (embedding, ด่านคัดหยาบ) → rerank (LLM, ด่านตัดสินละเอียด)
#      เดิมเคยใช้ cosine-distance threshold ตัดสินตรงๆ ชั้นเดียว แต่ tools/simulate_vectormemory.py
#      เจอว่าระยะของเคส "ควรดึง" กับ "ไม่ควรดึง" ซ้อนทับกันได้ (ต่างกันแค่ ~0.005) เพราะ distance
#      สัมบูรณ์ไม่ใช่สัญญาณที่แยกขาดได้เสมอ — เปลี่ยนมาให้ embedding แค่คัด candidate มาก่อน (relative,
#      ไม่ตัดสินขาด) แล้วให้ LLM (qwen3 ตัวเดียวกับที่ตอบแชต) อ่าน query+candidate คู่กันจริงแล้วให้คะแนน
#      ความเกี่ยวข้อง — threshold ที่แท้จริงย้ายไปอยู่บนคะแนนของ LLM แทน ซึ่งไม่แกว่งตามความยาว/หัวข้อ
#      เหมือน distance เดิม
# ============================================================
import io
import json
import re
import time

import aiohttp
import chromadb
from pypdf import PdfReader

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "bge-m3"   # ต้อง `ollama pull bge-m3` ก่อนใช้ (~1.2GB, รองรับไทยดี)

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
RERANK_MODEL = "qwen3:8b"   # ต้องตรงกับ MODEL ใน bot.py — ใช้โมเดลเดิมที่โหลดอยู่แล้ว ไม่กิน VRAM เพิ่ม

RETRIEVE_K = 5          # ด่าน 1 (embedding): ดึงผู้เข้ารอบมาก่อนแบบ relative ไม่สนระยะสัมบูรณ์
RERANK_SCORE_MIN = 5    # ด่าน 2 (LLM): คะแนน 0-10 ขั้นต่ำที่ถือว่า "เกี่ยวข้องพอจะ inject" (เกณฑ์หลวมๆ)

PDF_CHUNK_SIZE = 800
PDF_CHUNK_OVERLAP = 100
MAX_CHUNKS_PER_PDF = 300   # กันไฟล์ใหญ่มากทำให้บอทค้างนานเกิน (embed ทีละ chunk แบบ sequential)
MAX_PDF_PAGES = 200        # กัน PDF ที่มีจำนวนหน้าเยอะผิดปกติ (เช่นไฟล์ประสงค์ร้าย) ทำ extract_text ช้า/ค้าง

_client = chromadb.PersistentClient(path="chroma_db")


async def get_embedding(text: str, _retried: bool = False) -> list | None:
    """ยิงขอ embedding จาก Ollama (bge-m3) คืน None ถ้าพลาด (Ollama ปิด/ยังไม่ pull โมเดล)
    ลอง retry 1 ครั้งถ้าพลาด (เจอ timeout เป็นระยะตอน Ollama เพิ่ง cold-load โมเดล)"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                OLLAMA_EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=60,
            ) as r:
                data = await r.json()
        return data.get("embedding")
    except Exception as e:
        if not _retried:
            return await get_embedding(text, _retried=True)
        err = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        print(f"   ⚠️ vectormemory: ทำ embedding ไม่สำเร็จ ({err})")
        return None


def _build_rerank_prompt(query: str, candidates: list) -> str:
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(candidates))
    return (
        "ให้คะแนนความเกี่ยวข้องของข้อความแต่ละข้อกับคำถามนี้ คะแนน 0-10 "
        "(10 = เกี่ยวข้องตรงๆ ช่วยตอบคำถามได้, 0 = ไม่เกี่ยวข้องเลย)\n\n"
        f"คำถาม: {query}\n\n"
        f"ข้อความ:\n{numbered}\n\n"
        f"ตอบเป็น JSON array ตัวเลข {len(candidates)} ตัวเรียงตามลำดับข้อ เช่น [8, 2, 0] "
        "ห้ามมีคำอธิบายอื่น ตอบแค่ JSON array เท่านั้น"
    )


async def rerank_with_llm(query: str, candidates: list, top_n: int = 3) -> list:
    """ด่าน 2 — ให้ LLM (โมเดลเดียวกับที่บอทใช้ตอบแชต) อ่าน query+candidate คู่กันจริง
    แล้วให้คะแนนความเกี่ยวข้อง คืนเฉพาะอันที่คะแนน >= RERANK_SCORE_MIN เรียงมากไปน้อย สูงสุด top_n อัน

    fail-safe: ถ้า LLM ตอบพัง/parse ไม่ได้/ไม่ครบ คืน [] (ไม่ inject อะไรเลย) — เพราะจุดประสงค์ของ
    rerank คือกันเนื้อหาไม่เกี่ยวข้องหลุดเข้ามา ถ้า rerank ทำงานไม่ได้ การ inject แบบไม่กรองเลย
    เสี่ยงกว่าการไม่ inject อะไรเลยในรอบนั้น"""
    if not candidates:
        return []
    if len(candidates) == 1:
        return candidates  # อันเดียวไม่มีอะไรต้องเทียบ

    payload = {
        "model": RERANK_MODEL,
        "messages": [{"role": "user", "content": _build_rerank_prompt(query, candidates)}],
        "stream": False, "think": False,
        # temperature 0 (ไม่ใช่ 0.1 เหมือนจุดอื่นในโปรเจกต์) — rerank ต้องการผลนิ่งที่สุดเท่าที่จะทำได้
        # เพราะเคสก้ำกึ่ง (เช่น distance ต่างกันแค่ 0.005) ต้องได้คะแนนเดิมทุกครั้งที่ query ซ้ำ
        # ไม่งั้นผลอาจสลับข้ามไปมาระหว่างรัน ต่างจาก distance เดิมที่นิ่งเสมอ
        "options": {"temperature": 0},
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_CHAT_URL, json=payload, timeout=60) as r:
                data = await r.json()
        raw = data.get("message", {}).get("content", "") or ""
        if "</think>" in raw:
            raw = raw.rsplit("</think>", 1)[-1]
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not m:
            return []
        scores = json.loads(m.group(0))
        if not isinstance(scores, list) or len(scores) != len(candidates):
            return []
        ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [c for c, s in ranked if isinstance(s, (int, float)) and s >= RERANK_SCORE_MIN][:top_n]
    except Exception as e:
        print(f"   ⚠️ vectormemory: rerank ไม่สำเร็จ ({type(e).__name__}: {e}) — ไม่ inject รอบนี้")
        return []


def _pdf_collection(user_id: int):
    return _client.get_or_create_collection(
        f"pdf_{user_id}", metadata={"hnsw:space": "cosine"})


def _convmem_collection(user_id: int):
    return _client.get_or_create_collection(
        f"convmem_{user_id}", metadata={"hnsw:space": "cosine"})


def _chunk_text(text: str, size: int = PDF_CHUNK_SIZE, overlap: int = PDF_CHUNK_OVERLAP) -> list:
    """ตัดข้อความยาวเป็นชิ้นๆ ทับกันบางส่วน (overlap) กันบริบทขาดตรงรอยตัด"""
    text = " ".join(text.split())  # ยุบ whitespace/ขึ้นบรรทัดรัวๆ จาก PDF ให้เป็นช่องว่างเดียว
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c.strip()]


async def ingest_pdf(user_id: int, filename: str, pdf_bytes: bytes) -> int:
    """แตกไฟล์ PDF เป็น chunk + ทำ embedding แล้วเก็บลง ChromaDB ต่อ user (persist ถาวร)
    คืนจำนวน chunk ที่เก็บสำเร็จ (0 = อ่านไม่ได้/ไม่มีข้อความ/embedding พัง)"""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = reader.pages
        if len(pages) > MAX_PDF_PAGES:
            print(f"   ⚠️ vectormemory: PDF {filename!r} มี {len(pages)} หน้า — อ่านแค่ {MAX_PDF_PAGES} หน้าแรก")
            pages = pages[:MAX_PDF_PAGES]
        full_text = "\n".join(page.extract_text() or "" for page in pages)
    except Exception as e:
        print(f"   ⚠️ vectormemory: อ่าน PDF ไม่สำเร็จ ({e})")
        return 0

    chunks = _chunk_text(full_text)
    if not chunks:
        return 0
    if len(chunks) > MAX_CHUNKS_PER_PDF:
        print(f"   ⚠️ vectormemory: PDF {filename!r} ยาวเกิน — เก็บแค่ {MAX_CHUNKS_PER_PDF} chunk แรก")
        chunks = chunks[:MAX_CHUNKS_PER_PDF]

    coll = _pdf_collection(user_id)
    ids, embeddings, documents, metadatas = [], [], [], []
    for i, chunk in enumerate(chunks):
        emb = await get_embedding(chunk)
        if emb is None:
            continue
        ids.append(f"{filename}::{i}")
        embeddings.append(emb)
        documents.append(chunk)
        metadatas.append({"filename": filename, "chunk": i})

    if not ids:
        return 0
    coll.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    return len(ids)


async def query_pdf(user_id: int, question: str, top_k: int = 3) -> list:
    """ค้นเนื้อหาจาก PDF ที่ user เคยส่งมา ซึ่งเกี่ยวข้องกับคำถามนี้
    ด่าน 1: ดึง RETRIEVE_K ผู้เข้ารอบที่ใกล้ที่สุด (embedding, relative ไม่สนระยะสัมบูรณ์)
    ด่าน 2: ให้ LLM ให้คะแนนความเกี่ยวข้องจริง แล้วกรอง/เรียงใหม่ (rerank_with_llm)
    คืน [] ถ้าไม่เคยส่ง PDF มาเลย หรือ rerank เห็นว่าไม่มีอันไหนเกี่ยวข้องจริง"""
    coll = _pdf_collection(user_id)
    if coll.count() == 0:
        return []
    emb = await get_embedding(question)
    if emb is None:
        return []
    result = coll.query(query_embeddings=[emb], n_results=min(RETRIEVE_K, coll.count()))
    candidates = (result.get("documents") or [[]])[0]
    if not candidates:
        return []
    return await rerank_with_llm(question, candidates, top_n=top_k)


async def add_conversation_memory(user_id: int, text: str) -> None:
    """เก็บสรุปบทสนทนา (จาก summarize_and_verify หลังตรวจ hallucinate แล้ว) ลง vector memory
    เพื่อให้ค้นแบบความหมายได้ทีหลัง — เสริม recall_summaries แบบ keyword ใน memory.py"""
    if not text.strip():
        return
    emb = await get_embedding(text)
    if emb is None:
        return
    coll = _convmem_collection(user_id)
    coll.upsert(ids=[f"{int(time.time() * 1000)}"], embeddings=[emb], documents=[text])


async def query_conversation_memory(user_id: int, question: str, top_k: int = 3) -> list:
    """ค้นความทรงจำเก่าที่เกี่ยวข้องกับข้อความนี้แบบ semantic
    ด่าน 1: ดึง RETRIEVE_K ผู้เข้ารอบที่ใกล้ที่สุด (embedding, relative ไม่สนระยะสัมบูรณ์)
    ด่าน 2: ให้ LLM ให้คะแนนความเกี่ยวข้องจริง แล้วกรอง/เรียงใหม่ (rerank_with_llm)
    คืน [] ถ้ายังไม่เคยมีบทสนทนาสรุปเก็บไว้ หรือ rerank เห็นว่าไม่มีอันไหนเกี่ยวข้องจริง"""
    coll = _convmem_collection(user_id)
    if coll.count() == 0:
        return []
    emb = await get_embedding(question)
    if emb is None:
        return []
    result = coll.query(query_embeddings=[emb], n_results=min(RETRIEVE_K, coll.count()))
    candidates = (result.get("documents") or [[]])[0]
    if not candidates:
        return []
    return await rerank_with_llm(question, candidates, top_n=top_k)
