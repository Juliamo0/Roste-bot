"""ทดสอบ pass^k เฉพาะเคสที่เจอบั๊กจริงบน Discord: แนะนำตัว / บอกลา
ต้องไม่ตอบด้วย AI_DEFLECT ("เอ๋? ก็ฉันเป็นฉันนี่แหละค่ะ...") เพราะไม่ได้ถูกถามว่าเป็น AI
รัน: venv/Scripts/python.exe tools/_test_intro_bye.py [N_REPEAT]
"""
import asyncio
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import chat     # noqa: E402
import memory   # noqa: E402
import persona  # noqa: E402

TEST_USER_ID = 987_654_321_000_111

CASES = [
    "รอสเต้แนะนำตัวหน่อย",
    "อยากให้แนะนำตัวให้คนที่ไม่รู้จักนะ",
    "ช่วยบอกลาหน่อย",
]

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5


async def main():
    total = 0
    bad = 0
    for run in range(1, N + 1):
        mpath = memory._memory_path(TEST_USER_ID)
        if os.path.exists(mpath):
            os.remove(mpath)
        print(f"\n{'='*70}\n รอบ {run}/{N}\n{'='*70}")
        for msg in CASES:
            total += 1
            reply = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", msg)
            is_deflect = persona.AI_DEFLECT.strip() in reply.strip() or "ก็ฉันเป็นฉันนี่แหละ" in reply
            status = "FAIL (deflect หลุดผิดที่)" if is_deflect else "OK"
            if is_deflect:
                bad += 1
            print(f"  [{status}] ผู้ใช้: {msg!r}")
            print(f"       บอท: {reply!r}")

    print(f"\n{'='*70}")
    print(f" สรุป: {total - bad}/{total} ผ่าน ({bad} ครั้งที่หลุด deflect ผิดที่)")
    print(f"{'='*70}")

    mpath = memory._memory_path(TEST_USER_ID)
    if os.path.exists(mpath):
        os.remove(mpath)
        print("🗑️  ลบ memory ทดสอบแล้ว")


if __name__ == "__main__":
    asyncio.run(main())
