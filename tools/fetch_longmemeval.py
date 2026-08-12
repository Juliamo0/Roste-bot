"""ดาวน์โหลดชุดข้อมูลมาตรฐาน LongMemEval สำหรับวัดระบบความจำ

ไม่เก็บไฟล์ลง git เพราะใหญ่ ~280MB — รันไฟล์นี้ครั้งเดียวก่อนใช้ bench_longmemeval.py

ที่มา: xiaowu0162/longmemeval-cleaned (HuggingFace) — LongMemEval, ICLR 2025
ใช้ไฟล์ _s (มี distractor 40 session/ข้อ) ไม่ใช่ oracle
เพราะ oracle มีแต่ evidence session ทำให้ทุกวิธีได้คะแนนเต็ม = วัดอะไรไม่ได้
"""
import os
import sys
import urllib.request

BASE = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"
FILES = {"longmemeval_s.json": "longmemeval_s_cleaned.json"}


def main():
    os.makedirs("tools/data", exist_ok=True)
    for local, remote in FILES.items():
        out = os.path.join("tools/data", local)
        if os.path.exists(out):
            print(f"มีอยู่แล้ว: {out} ({os.path.getsize(out) // 1024 // 1024} MB)")
            continue
        print(f"กำลังดาวน์โหลด {remote} ...")
        urllib.request.urlretrieve(BASE + remote, out)
        print(f"  เสร็จ: {out} ({os.path.getsize(out) // 1024 // 1024} MB)")


if __name__ == "__main__":
    main()
