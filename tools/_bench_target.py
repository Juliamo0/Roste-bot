"""ตัวเลือกไฟล์ความจำที่ bench ใช้เป็นข้อมูลตั้งต้น — แชร์กันทุกสคริปต์ใน tools/

ทำไมต้องมีไฟล์นี้: bench พวกนี้ต้องอ่านความจำของผู้ใช้จริงเพื่อวัด recall/ความจำ ซึ่ง
เดิมฝัง Discord user ID ไว้ในโค้ดตรงๆ ทั้ง 5 สคริปต์ — repo นี้เป็น public ID จึงติดไปด้วย
และคนอื่นที่ clone ไปก็ใช้ไม่ได้เพราะไม่มีไฟล์นั้นในเครื่อง

ใช้ยังไง — ตั้ง env var ชี้ไปที่ไฟล์ความจำของตัวเอง:
    set BENCH_MEMORY_UID=123456789012345678        (Windows)
    export BENCH_MEMORY_UID=123456789012345678     (bash)

ถ้าไม่ตั้ง จะหยิบไฟล์ที่ใหญ่ที่สุดใน memory/ มาใช้แทน (= คนที่คุยเยอะสุด ซึ่งเป็นข้อมูล
ที่เหมาะกับการวัด recall ที่สุดอยู่แล้ว) — ไม่มีไฟล์เลยถึงจะ error พร้อมบอกวิธีแก้
"""
import os
import pathlib

MEMORY_DIR = pathlib.Path("memory")


def resolve_memory_file() -> str:
    """คืน path ไฟล์ความจำที่จะใช้เป็นข้อมูลตั้งต้นของ bench"""
    uid = os.environ.get("BENCH_MEMORY_UID", "").strip()
    if uid:
        p = MEMORY_DIR / f"{uid}.json"
        if not p.exists():
            raise SystemExit(f"ไม่พบ {p} — ตรวจค่า BENCH_MEMORY_UID อีกที")
        return str(p)

    files = [f for f in MEMORY_DIR.glob("*.json") if f.is_file()]
    if not files:
        raise SystemExit(
            "ไม่มีไฟล์ความจำใน memory/ — คุยกับบอทสักพักให้มีข้อมูลก่อน "
            "หรือตั้ง BENCH_MEMORY_UID ชี้ไฟล์ที่ต้องการ"
        )
    return str(max(files, key=lambda f: f.stat().st_size))


def resolve_uid() -> int:
    """คืน user id (int) ของไฟล์ที่ resolve_memory_file() เลือก"""
    return int(pathlib.Path(resolve_memory_file()).stem)
