"""
test_tts_stream.py — เทส _generate_tts_stream ใน bot.py (ชั้นเชื่อมระหว่าง voice.py กับ Discord)

ทำไมต้องมีแยก: ชั้นนี้ไม่เคยมีเทสเลย ทั้งที่เป็นทางผ่านของทุกคำตอบที่รอสเต้พูด และเป็นจุดที่
prefetch ใน voice.py จะได้ผลจริงหรือไม่ก็อยู่ที่นี่ — ถ้าชั้นนี้ยังบล็อกรอ consumer อยู่
prefetch ข้างล่างก็เปล่าประโยชน์

ครอบ:
  - producer เดินหน้าเจนล่วงหน้าจริงเมื่อ consumer ยังไม่ขอ (สัญญาหลักของ prefetch)
  - ลำดับ segment ตรงกับลำดับที่ voice.py ผลิต (ห้ามสลับ)
  - consumer หยุดกลางคัน → ไฟล์ที่ค้างถูกลบ ไม่สะสม
  - worker ไม่พร้อม → ไม่ยิงงาน ไม่ throw
  - error ใน producer ไม่ทำให้ consumer ค้าง
mock ล้วน — ไม่ต้องมี GPU/Discord/เน็ต
"""
import asyncio
import os
import threading
import time

import pytest

import bot


# ── fakes ─────────────────────────────────────────────────────────────────────

class FakeWorker:
    """RvcWorker/F5Worker ปลอม — ผ่านด่านเช็ค alive/load_time ใน _generate_tts_stream"""

    def __init__(self, alive=True, load_time=1.0):
        self.alive = alive
        self.load_time = load_time


def _install_workers(monkeypatch, alive=True, load_time=1.0):
    monkeypatch.setattr(bot, "_voice_worker", FakeWorker(alive, load_time))
    monkeypatch.setattr(bot, "_f5_worker", FakeWorker(alive, load_time))


def _fake_segments(paths, *, gen_delay=0.0, on_generate=None, boom_at=None):
    """สร้างตัวแทน voice.text_to_roste_voice_segments ที่ควบคุมจังหวะได้

    สำคัญ: ตัวจริงหลังแก้ prefetch จะ *เจนล่วงหน้า* ไม่รอ consumer — ตัวปลอมนี้จึงต้อง
    ไม่บล็อกที่ yield เช่นกัน ไม่งั้นจะเทสคนละพฤติกรรมกับของจริง
    """
    def _factory(text, *, worker, f5_worker, out_dir, prefetch=2, **kw):
        os.makedirs(out_dir, exist_ok=True)
        import queue as _q
        q: _q.Queue = _q.Queue(maxsize=max(prefetch, 1))
        sentinel = object()

        def _produce():
            try:
                for i, name in enumerate(paths):
                    if boom_at is not None and i == boom_at:
                        q.put(RuntimeError("producer boom"))
                        return
                    if gen_delay:
                        time.sleep(gen_delay)
                    p = os.path.join(out_dir, name)
                    with open(p, "wb") as f:
                        f.write(b"\0" * 16)
                    if on_generate is not None:
                        on_generate(i, p)
                    q.put(p)
            finally:
                q.put(sentinel)

        th = threading.Thread(target=_produce, daemon=True)
        th.start()
        try:
            while True:
                item = q.get()
                if item is sentinel:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            th.join(timeout=5)

    return _factory


async def _drain(stream):
    out = []
    async for wav in stream:
        out.append(wav)
    return out


# ── ทางปกติ ───────────────────────────────────────────────────────────────────

def test_yields_segments_in_order(monkeypatch, tmp_path):
    _install_workers(monkeypatch)
    monkeypatch.setattr(voice_out := bot.voice, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(
        voice_out, "text_to_roste_voice_segments",
        _fake_segments(["a.wav", "b.wav", "c.wav"]))

    got = asyncio.run(_drain(bot._generate_tts_stream("ข้อความ", 1)))

    assert [os.path.basename(p) for p in got] == ["a.wav", "b.wav", "c.wav"]


def test_skips_when_worker_not_ready(monkeypatch, tmp_path):
    """worker ยังโหลดไม่เสร็จ (load_time=0) → ไม่ผลิตอะไรเลย ไม่ throw"""
    monkeypatch.setattr(bot, "_voice_worker", FakeWorker(alive=True, load_time=0.0))
    monkeypatch.setattr(bot, "_f5_worker", FakeWorker())
    called = []
    monkeypatch.setattr(
        bot.voice, "text_to_roste_voice_segments",
        lambda *a, **k: called.append(1) or iter(()))

    got = asyncio.run(_drain(bot._generate_tts_stream("ข้อความ", 1)))

    assert got == []
    assert called == [], "ไม่ควรเรียก TTS เลยตอน worker ยังไม่พร้อม"


def test_skips_when_worker_absent(monkeypatch):
    monkeypatch.setattr(bot, "_voice_worker", None)
    got = asyncio.run(_drain(bot._generate_tts_stream("ข้อความ", 1)))
    assert got == []


# ── prefetch: หัวใจของการแก้ ───────────────────────────────────────────────────

def test_producer_runs_ahead_while_consumer_is_busy(monkeypatch, tmp_path):
    """consumer ช้า (จำลองเล่นเสียง) → producer ต้องเดินหน้าเจนล่วงหน้า ไม่รอ

    ⚠️ สิ่งที่เทสนี้การันตี คือ *ชั้น bot.py* ไม่บล็อก ไม่ใช่ prefetch ใน voice.py —
    _produce รันใน asyncio.to_thread แล้วดัน queue (unbounded) ฝั่ง event loop ตัว
    generator จึงเดินต่อได้ทันทีที่ yield โดยไม่รอ consumer อยู่แล้ว พิสูจน์ได้โดยสลับ
    ตัวปลอมเป็น generator แบบ lock-step ล้วน — เทสนี้ก็ยังผ่าน
    prefetch ใน voice.py มีผลกับ caller ที่วน generator ตรงๆ (ไม่ผ่านชั้นนี้) เป็นหลัก
    ดู regression guard ตัวจริงของ prefetch ที่ test_voice.py::test_prefetch_generates_ahead_of_consumer
    """
    _install_workers(monkeypatch)
    generated: list[float] = []
    monkeypatch.setattr(bot.voice, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(
        bot.voice, "text_to_roste_voice_segments",
        _fake_segments(
            [f"s{i}.wav" for i in range(4)],
            gen_delay=0.05,
            on_generate=lambda i, p: generated.append(time.perf_counter())))

    consumed: list[float] = []

    async def _slow_consume():
        async for wav in bot._generate_tts_stream("ข้อความ", 1):
            consumed.append(time.perf_counter())
            await asyncio.sleep(0.3)   # จำลองเล่นเสียง — ช้ากว่าเจนมาก

    asyncio.run(_slow_consume())

    assert len(consumed) == 4
    # ตอน consumer รับชิ้นที่ 2 (index 1) producer ควรเจนเกิน 2 ชิ้นไปแล้ว
    # ถ้าเป็น lock-step จำนวนที่เจนจะไล่ตาม consumer แบบ 1:1 พอดีเสมอ
    ahead = sum(1 for g in generated if g < consumed[1])
    assert ahead >= 2, (
        f"producer ไม่ได้เดินหน้าล่วงหน้า (เจนไป {ahead} ชิ้นตอน consumer รับชิ้นที่ 2)")


def test_total_time_bounded_by_consumer_not_sum_of_both(monkeypatch, tmp_path):
    """เวลารวมต้องใกล้ 'เวลาเล่น' ไม่ใช่ 'เวลาเล่น + เวลาเจน' รวมกัน

    วัดผลแบบ end-to-end ของชั้นนี้ — ถ้าวันหน้ามีใครแก้ _generate_tts_stream ให้รอ
    producer ก่อน yield แต่ละชิ้น (เช่น เผลอ await producer_task ในลูป) เวลารวมจะพุ่ง
    ไปเท่า lock-step ทันที เทสนี้จับได้
    """
    _install_workers(monkeypatch)
    n, gen_delay, play_delay = 4, 0.15, 0.25
    monkeypatch.setattr(bot.voice, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(
        bot.voice, "text_to_roste_voice_segments",
        _fake_segments([f"s{i}.wav" for i in range(n)], gen_delay=gen_delay))

    async def _consume():
        async for _ in bot._generate_tts_stream("ข้อความ", 1):
            await asyncio.sleep(play_delay)

    t0 = time.perf_counter()
    asyncio.run(_consume())
    elapsed = time.perf_counter() - t0

    lockstep = n * (gen_delay + play_delay)      # ถ้าเจนสลับเล่นทีละชิ้น
    assert elapsed < lockstep * 0.85, (
        f"ใช้เวลา {elapsed:.2f}s ใกล้เคียง lock-step ({lockstep:.2f}s) — prefetch ไม่ทำงาน")


# ── หยุดกลางคัน / error ───────────────────────────────────────────────────────

def test_leftover_files_removed_when_consumer_stops_early(monkeypatch, tmp_path):
    """ผู้ใช้ออกจากห้องกลางคำตอบ → ไฟล์ที่เจนล่วงหน้าไว้ต้องถูกลบ ไม่ค้างสะสมในดิสก์"""
    _install_workers(monkeypatch)
    out_dir = tmp_path / "bot"
    monkeypatch.setattr(bot.voice, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(
        bot.voice, "text_to_roste_voice_segments",
        _fake_segments([f"s{i}.wav" for i in range(5)], gen_delay=0.02))

    async def _stop_after_first():
        stream = bot._generate_tts_stream("ข้อความ", 1)
        first = await anext(stream, None)
        await asyncio.sleep(0.3)      # ให้ producer เจนล่วงหน้าไว้หลายชิ้น
        await stream.aclose()         # ผู้ใช้หลุดห้อง
        return first

    first = asyncio.run(_stop_after_first())

    assert first is not None
    os.remove(first)                  # caller ลบชิ้นที่รับไปแล้วตามสัญญาเดิม
    leftover = list(out_dir.glob("*.wav")) if out_dir.exists() else []
    assert leftover == [], f"ไฟล์ค้างไม่ถูกเก็บกวาด: {leftover}"


def test_producer_error_does_not_hang_consumer(monkeypatch, tmp_path):
    """producer พังกลางคัน → consumer ต้องจบได้ ไม่ค้างรอ sentinel ตลอดไป

    ถ้า sentinel ไม่ถูกส่งตอน error บอทจะค้างถือ voice_lock ไว้ ทำให้พูดไม่ได้อีกเลย
    """
    _install_workers(monkeypatch)
    monkeypatch.setattr(bot.voice, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(
        bot.voice, "text_to_roste_voice_segments",
        _fake_segments([f"s{i}.wav" for i in range(4)], boom_at=2))

    async def _run():
        return await asyncio.wait_for(
            _drain(bot._generate_tts_stream("ข้อความ", 1)), timeout=10)

    got = asyncio.run(_run())   # ไม่ควร timeout และไม่ควร raise ออกมาถึงตรงนี้
    assert len(got) == 2        # ได้ 2 ชิ้นก่อนพัง แล้วจบอย่างสงบ


def test_no_thread_leak_after_stream_closed(monkeypatch, tmp_path):
    """ปิด stream แล้ว thread ของ producer ต้องไม่ค้าง — สะสมทุกคำตอบจะกินทรัพยากรไปเรื่อยๆ"""
    _install_workers(monkeypatch)
    monkeypatch.setattr(bot.voice, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(
        bot.voice, "text_to_roste_voice_segments",
        _fake_segments([f"s{i}.wav" for i in range(5)], gen_delay=0.02))

    before = threading.active_count()

    async def _partial():
        stream = bot._generate_tts_stream("ข้อความ", 1)
        await anext(stream, None)
        await stream.aclose()

    asyncio.run(_partial())

    deadline = time.monotonic() + 5
    while threading.active_count() > before and time.monotonic() < deadline:
        time.sleep(0.05)
    assert threading.active_count() <= before, "thread ค้างหลังปิด stream"
