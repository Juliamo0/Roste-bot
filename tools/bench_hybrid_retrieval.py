"""C2 รอบ 4: bge-m3 **sparse + dense hybrid** — ใช้ความสามารถที่โมเดลมีอยู่แล้วแต่ยังไม่ได้ใช้

ที่มา: ผู้ใช้เสนอให้หา "โมเดลเล็กที่เก่งเฉพาะทาง" แทนโมเดลเล็กทั่วไป — bge-m3 เป็นตัวอย่างที่ดี
และมันมี 3 โหมดในตัวเดียว แต่ production ใช้แค่โหมดเดียว:
    dense    (ใช้อยู่)  — ความคล้ายเชิงความหมาย
    sparse   (ยังไม่ใช้) — น้ำหนักรายคำ แบบ BM25 แต่เรียนรู้มา จับชื่อเฉพาะ/คำตรงได้ดี
    colbert  (ยังไม่ใช้) — จับคู่ระดับโทเคน

⚠️ Ollama `/api/embed` คืน **dense อย่างเดียว** (ตรวจแล้ว) — ต้องใช้ FlagEmbedding โดยตรง
   จึงจะดึง sparse ออกมาได้ ไฟล์นี้จึงโหลดโมเดลเองเพื่อ *วัดว่าคุ้มไหม* ก่อนตัดสินใจ
   ว่าจะย้าย production ออกจาก Ollama หรือไม่ (ซึ่งเป็นการเปลี่ยนที่ใหญ่ ต้องมีหลักฐานก่อน)

สมมติฐานที่จะทดสอบ: เคสที่พลาดคือคำถามนามธรรม/สำนวน ("แบก"→ภาระ) ซึ่ง dense จัดอันดับ
คำตอบไว้ที่ 9-19 (เกิน RETRIEVE_K=5) — ถ้า sparse ช่วยดันอันดับขึ้น จะแก้ได้โดย
**ไม่ต้องเพิ่ม K** (ซึ่งวัดแล้วว่าทำให้แย่ลง) และ **ไม่ต้องเรียก LLM เพิ่ม**

วัด: อันดับของคำตอบ (rank) ไม่ใช่แค่ผ่าน/ไม่ผ่าน — เพราะ rank บอกได้ว่า "ดีขึ้นแค่ไหน"
แม้ยังไม่ติด top-5 (metric ที่แยกวิธีออกจากกันได้ ตาม MEMORY_EXPERIMENTS §4)
"""
import argparse
import io
import json
import logging
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import memory  # noqa: E402
from bench_vocab_gap import check_no_overlap  # noqa: E402

logging.disable(logging.CRITICAL)

REAL_UID = 434893254576701450


def sparse_score(q_w: dict, d_w: dict) -> float:
    """คะแนน sparse = ผลรวมน้ำหนักของคำที่ปรากฏร่วมกัน (ตามสูตรของ bge-m3)"""
    return sum(w * d_w.get(t, 0.0) for t, w in q_w.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.5,
                    help="น้ำหนัก dense (1-alpha = น้ำหนัก sparse)")
    ap.add_argument("--top-k", type=int, default=5, help="RETRIEVE_K ที่ใช้ตัดสินผ่าน/ไม่ผ่าน")
    args = ap.parse_args()

    summaries = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))["summaries"]
    docs = [e["text"] for e in summaries]
    cases, _ = check_no_overlap(summaries)

    print("=" * 100)
    print(" C2 รอบ 4 — bge-m3 sparse + dense hybrid (ความจำจริง)")
    print(f" summary {len(docs)} อัน · เคส {len(cases)} · alpha(dense)={args.alpha} · top-k={args.top_k}")
    print("=" * 100)

    print("\n กำลังโหลด bge-m3 ผ่าน FlagEmbedding (ครั้งแรกช้า ต้องโหลดโมเดล)...")
    t0 = time.perf_counter()
    from FlagEmbedding import BGEM3FlagModel
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    print(f" โหลดเสร็จใน {time.perf_counter() - t0:.0f}s")

    print(" กำลัง encode summary ทั้งหมด (dense + sparse)...")
    t0 = time.perf_counter()
    doc_out = model.encode(docs, return_dense=True, return_sparse=True,
                           return_colbert_vecs=False, batch_size=4, max_length=512)
    print(f" encode เสร็จใน {time.perf_counter() - t0:.0f}s")

    import numpy as np
    d_dense = np.array(doc_out["dense_vecs"])
    d_sparse = doc_out["lexical_weights"]

    results = {"dense": [], "sparse": [], "hybrid": []}
    rows = []

    for q, must in cases:
        q_out = model.encode([q], return_dense=True, return_sparse=True,
                             return_colbert_vecs=False, max_length=512)
        qd = np.array(q_out["dense_vecs"][0])
        qs = q_out["lexical_weights"][0]

        dense_s = d_dense @ qd
        sparse_s = np.array([sparse_score(qs, dw) for dw in d_sparse])

        # normalize ทั้งสองฝั่งก่อนผสม (สเกลต่างกันมาก — dense ~0-1, sparse ~0-5)
        def norm(a):
            rng = a.max() - a.min()
            return (a - a.min()) / rng if rng > 1e-9 else a * 0
        hybrid_s = args.alpha * norm(dense_s) + (1 - args.alpha) * norm(sparse_s)

        gold = [i for i, t in enumerate(docs) if any(m in t for m in must)]

        def rank_of(scores):
            order = np.argsort(-scores)
            for pos, i in enumerate(order, 1):
                if i in gold:
                    return pos
            return len(docs) + 1

        r = {"dense": rank_of(dense_s), "sparse": rank_of(sparse_s),
             "hybrid": rank_of(hybrid_s)}
        for k in results:
            results[k].append(r[k])
        rows.append((q, r))

    print("\n" + "=" * 100)
    print(f" {'วิธี':<12} {'ติด top-%d' % args.top_k:>12} {'อันดับเฉลี่ย':>14} {'อันดับกลาง':>12}")
    print("-" * 100)
    import statistics
    for k in ("dense", "sparse", "hybrid"):
        ranks = results[k]
        hits = sum(1 for r in ranks if r <= args.top_k)
        print(f" {k:<12} {hits:>6}/{len(ranks):<5} {statistics.mean(ranks):>14.1f} "
              f"{statistics.median(ranks):>12.0f}")
    print("=" * 100)

    print("\n เคสที่ dense ไม่ติด top-%d — hybrid ช่วยได้ไหม:" % args.top_k)
    improved = worse = 0
    for q, r in rows:
        if r["dense"] <= args.top_k:
            continue
        mark = "✅" if r["hybrid"] <= args.top_k else ("↑" if r["hybrid"] < r["dense"] else " ")
        if r["hybrid"] <= args.top_k:
            improved += 1
        print(f"   {mark} {q[:38]:<40} dense={r['dense']:>3} sparse={r['sparse']:>3} "
              f"hybrid={r['hybrid']:>3}")

    for q, r in rows:
        if r["dense"] <= args.top_k and r["hybrid"] > args.top_k:
            worse += 1
    print(f"\n   hybrid กู้คืนได้ {improved} เคส · ทำเคสที่เดิมดีพัง {worse} เคส")


if __name__ == "__main__":
    main()
