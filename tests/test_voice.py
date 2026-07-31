# ============================================================
#  test_voice.py — unit tests สำหรับ voice.py streaming generator
#  (mock ล้วน — ไม่ต้องมี GPU / venv / เน็ต)
#
#  ครอบคลุม:
#    - ลำดับ segment ออกตามลำดับ input (สัญญาหลักของ streaming)
#    - fail-safe chain ต่อ segment: F5 retry → edge-tts fallback → skip
#    - text_to_roste_voice (API เดิม) ยังคืนไฟล์เดียวหลัง refactor
# ============================================================
import os
import threading
import time

import numpy as np
import pytest
import soundfile as sf

import voice


SR = 40000


def _write_dummy_wav(path):
    sf.write(path, np.zeros(SR // 10), SR)  # 0.1s silence


# ---------- fakes ----------

class FakeF5:
    """F5Worker ปลอม — สั่งให้พังเป็นรายครั้งได้ผ่าน fail_calls (นับจาก 1)"""

    def __init__(self, fail_calls=()):
        self.fail_calls = set(fail_calls)
        self.calls = []          # gen_text ของทุกครั้งที่ถูกเรียก
        self.alive = True

    def generate(self, *, ref_audio, ref_text, gen_text, out_path, speed, steps):
        self.calls.append(gen_text)
        if len(self.calls) in self.fail_calls:
            raise RuntimeError("F5 boom")
        _write_dummy_wav(out_path)
        return 0.1


class FakeRvc:
    def __init__(self):
        self.calls = []

    @property
    def alive(self):
        return True

    def convert(self, input_path, output_path):
        self.calls.append(input_path)
        _write_dummy_wav(output_path)
        return 0.1


@pytest.fixture
def three_segments(monkeypatch):
    """บังคับ split เป็น 3 segment คงที่ + ปิด preprocess (identity)"""
    segs = ["ประโยคหนึ่งค่ะ", "ประโยคสองนะคะ", "ประโยคสามค่ะ"]
    monkeypatch.setattr(voice, "_split_thai_text", lambda text, max_chars=300: segs)
    import f5_preprocess
    monkeypatch.setattr(f5_preprocess, "preprocess_for_f5", lambda t: (t, []))
    return segs


@pytest.fixture
def edge_ok(monkeypatch):
    """edge-tts + adjust ปลอมที่สำเร็จเสมอ — บันทึกข้อความที่ถูกเรียก"""
    called = []

    def fake_edge(text, out_wav, retries=3):
        called.append(text)
        _write_dummy_wav(out_wav)

    monkeypatch.setattr(voice, "_edge_tts", fake_edge)
    monkeypatch.setattr(voice, "_adjust", lambda i, o: _write_dummy_wav(o))
    return called


@pytest.fixture
def edge_broken(monkeypatch):
    called = []

    def fake_edge(text, out_wav, retries=3):
        called.append(text)
        raise RuntimeError("edge boom")

    monkeypatch.setattr(voice, "_edge_tts", fake_edge)
    monkeypatch.setattr(voice, "_adjust", lambda i, o: _write_dummy_wav(o))
    return called


def _collect(text, f5, rvc, tmp_path, **kw):
    return list(voice.text_to_roste_voice_segments(
        text, worker=rvc, f5_worker=f5, out_dir=str(tmp_path), **kw))


# ---------- streaming: ลำดับ + ทางปกติ ----------

def test_segments_yield_in_order(three_segments, edge_ok, tmp_path):
    f5, rvc = FakeF5(), FakeRvc()
    got = _collect("อะไรก็ได้", f5, rvc, tmp_path, filename="t")

    assert len(got) == 3
    # ลำดับไฟล์ตรงกับลำดับ segment (index ฝังในชื่อไฟล์)
    assert [os.path.basename(p) for p in got] == [
        "t_0_rvc.wav", "t_1_rvc.wav", "t_2_rvc.wav"]
    # F5 ถูกเรียกตามลำดับ segment ไม่สลับ
    assert f5.calls == three_segments
    # ทุกไฟล์ที่ yield มีอยู่จริง (persistent ใน out_dir ไม่ใช่ tmp ที่ถูกลบ)
    assert all(os.path.exists(p) for p in got)
    # ทางปกติไม่แตะ edge-tts
    assert edge_ok == []


def test_f5_retry_once_then_success(three_segments, edge_ok, tmp_path):
    # call 1 = seg0 ครั้งแรกพัง → retry (call 2) สำเร็จ
    f5, rvc = FakeF5(fail_calls={1}), FakeRvc()
    got = _collect("อะไรก็ได้", f5, rvc, tmp_path)

    assert len(got) == 3
    assert f5.calls == [three_segments[0]] + three_segments  # seg0 สองครั้ง
    assert edge_ok == []  # retry สำเร็จ ไม่ต้อง fallback


def test_f5_double_fail_falls_back_to_edge_for_that_segment(
        three_segments, edge_ok, tmp_path):
    # seg1 พังทั้งสองครั้ง (call 2, 3) → เฉพาะ seg1 ไปเส้น edge-tts
    f5, rvc = FakeF5(fail_calls={2, 3}), FakeRvc()
    got = _collect("อะไรก็ได้", f5, rvc, tmp_path)

    assert len(got) == 3          # เนื้อหาครบทุก segment
    assert edge_ok == [three_segments[1]]   # edge โดนเรียกแค่ seg ที่พัง
    # seg2 กลับมาเส้น F5 ปกติ (call 4)
    assert f5.calls[-1] == three_segments[2]


def test_edge_also_fails_skips_only_that_segment(
        three_segments, edge_broken, tmp_path):
    f5, rvc = FakeF5(fail_calls={2, 3}), FakeRvc()
    got = _collect("อะไรก็ได้", f5, rvc, tmp_path, filename="t")

    # seg1 ถูกข้าม — เหลือ seg0, seg2 และลำดับยังถูก
    assert [os.path.basename(p) for p in got] == ["t_0_rvc.wav", "t_2_rvc.wav"]
    assert edge_broken == [three_segments[1]]


def test_all_segments_fail_yields_nothing_without_raise(
        three_segments, edge_broken, tmp_path):
    f5 = FakeF5(fail_calls=set(range(1, 10)))
    got = _collect("อะไรก็ได้", f5, FakeRvc(), tmp_path)
    assert got == []


def test_dead_f5_worker_goes_straight_to_edge_per_segment(
        three_segments, edge_ok, tmp_path):
    # worker ตายหลังเริ่ม (alive=False ตอนเข้า _gen_one_segment) → ไม่ retry F5 เลย
    #
    # ใช้ prefetch=0 เพราะเทสนี้ต้องคุม "จังหวะ" ที่ worker ตาย ให้ตกระหว่าง segment 0 กับ 1
    # พอดี — ซึ่งทำได้ต่อเมื่อ generate เกิดตอน caller ขอเท่านั้น ส่วนโหมด prefetch (default)
    # producer เดินหน้าเจนล่วงหน้าไปแล้วโดยตั้งใจ จังหวะจึงคุมจากฝั่ง caller ไม่ได้
    # (พฤติกรรมที่เทสนี้สนใจจริงๆ — ตายแล้วต้องไป edge-tts ไม่เงียบ — เทสแยกไว้ด้านล่าง
    #  แบบไม่ผูกกับจังหวะ)
    f5, rvc = FakeF5(), FakeRvc()
    got = []
    gen = voice.text_to_roste_voice_segments(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path), prefetch=0)
    got.append(next(gen))     # seg0 เส้น F5 ปกติ
    f5.alive = False          # worker ตายกลางคัน
    got.extend(gen)           # seg1, seg2 ต้องไปเส้น edge-tts ต่อ ไม่เงียบ

    assert len(got) == 3
    assert f5.calls == [three_segments[0]]           # F5 ไม่ถูกเรียกอีกหลังตาย
    assert edge_ok == three_segments[1:]             # ที่เหลือ edge-tts ครบ


def test_f5_failing_every_call_falls_back_per_segment_under_prefetch(
        three_segments, edge_ok, tmp_path):
    """F5 พังทุกครั้ง (worker ยัง alive) → ทุก segment ต้องตกไป edge-tts ครบ ไม่มีอันหาย

    เทียบกับเทสข้างบน: อันนั้นคุมจังหวะที่ worker ตายกลางคัน (ต้อง prefetch=0) อันนี้เช็ค
    "ผลลัพธ์" ที่ต้องจริงทุกโหมด จึงรันบน default (prefetch เปิด) — ยืนยันว่า fail-safe
    chain ต่อ segment ยังทำงานเหมือนเดิมหลังย้าย generate ไปอยู่ใน producer thread
    """
    f5, rvc = FakeF5(fail_calls=set(range(1, 20))), FakeRvc()
    got = _collect("อะไรก็ได้", f5, rvc, tmp_path)

    assert len(got) == 3
    assert edge_ok == three_segments      # ครบทั้ง 3 ตามลำดับ


def test_prefetch_generates_ahead_of_consumer(three_segments, edge_ok, tmp_path):
    """หัวใจของ prefetch: producer ต้องเดินหน้าเจน segment ถัดไปโดยไม่รอ caller ขอ

    เทสนี้คือ regression guard ของบั๊กที่แก้: เดิม generate ค้างที่ yield จนกว่า caller
    จะขอชิ้นถัดไป ทำให้ระหว่างที่เสียงเล่นอยู่ GPU ว่างเปล่า แล้วผู้ฟังต้องรอเจนใหม่ทุกช่วง
    (วัดจริงบนคำตอบ 6 segment: เงียบรวม 20.7s → 0.0s หลังแก้)
    """
    f5, rvc = FakeF5(), FakeRvc()
    gen = voice.text_to_roste_voice_segments(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path), prefetch=2)
    first = next(gen)         # ขอแค่ชิ้นแรกชิ้นเดียว แล้วไม่ขอต่อ

    # ให้ producer มีโอกาสเดินหน้า — รอจนเจนเกิน 1 ชิ้น (timeout กัน hang ถ้าพัง)
    deadline = time.monotonic() + 5
    while len(f5.calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert first is not None
    # ถ้ายังเป็น lock-step แบบเดิม f5.calls จะมีแค่ 1 ตลอด (ค้างที่ yield)
    assert len(f5.calls) >= 2, "producer ไม่ได้เจนล่วงหน้า — prefetch ไม่ทำงาน"
    gen.close()


def test_prefetch_respects_queue_bound(three_segments, edge_ok, tmp_path, monkeypatch):
    """คิวเต็มแล้ว producer ต้องหยุดรอ ไม่เจนรวดทั้งคำตอบทิ้งไว้

    สำคัญเพราะถ้าไม่มี bound งาน generate ที่ผู้ใช้ไม่มีวันได้ยิน (หยุดกลางคัน) จะกิน
    GPU + ดิสก์ฟรีๆ ทั้งก้อน — 6 segment ที่เตรียมไว้ให้ split ในเทสนี้ใช้ 5 ชิ้น
    """
    monkeypatch.setattr(voice, "_split_thai_text", lambda t, max_chars=300: [f"s{i}" for i in range(5)])
    f5, rvc = FakeF5(), FakeRvc()
    gen = voice.text_to_roste_voice_segments(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path), prefetch=1)
    first = next(gen)

    time.sleep(0.5)   # ให้เวลา producer เดินหน้าจนสุดที่คิวยอมให้
    # prefetch=1 → คิวถือได้ 1 + ชิ้นที่ producer กำลังถืออยู่ระหว่าง put
    # ถ้าไม่มี bound เลยจะเจนครบ 5 ชิ้นทันที
    assert first is not None
    assert len(f5.calls) < 5, f"producer เจนเกินขอบเขตคิว ({len(f5.calls)}/5)"
    gen.close()


def test_close_midway_cleans_up_prefetched_files(three_segments, edge_ok, tmp_path):
    """caller เลิกฟังกลางคัน → ไฟล์ที่เจนล่วงหน้าไว้ต้องถูกลบ ไม่ค้างสะสมใน out_dir

    (เฉพาะไฟล์ที่ยังไม่ได้ yield ออกไป — ที่ yield แล้วเป็นความรับผิดชอบของ caller
     ตามสัญญาเดิมของฟังก์ชัน)
    """
    f5, rvc = FakeF5(), FakeRvc()
    gen = voice.text_to_roste_voice_segments(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path), prefetch=2)
    first = next(gen)
    time.sleep(0.3)        # ให้ producer เจนล่วงหน้าไว้บ้าง
    gen.close()            # ผู้ใช้ออกจากห้อง / สั่งหยุด

    os.remove(first)       # caller ลบชิ้นที่ตัวเองรับไปแล้ว (ตามสัญญาเดิม)
    leftover = [f for f in os.listdir(tmp_path) if f.endswith(".wav")]
    assert leftover == [], f"ไฟล์ prefetch ค้างไม่ถูกลบ: {leftover}"


def test_producer_thread_does_not_leak_after_close(three_segments, edge_ok, tmp_path):
    """ปิด generator แล้ว producer thread ต้องจบ ไม่ค้างถือ worker ไว้

    เดิมถ้า producer ค้างอยู่ที่ q.put() ตอนคิวเต็มแล้วไม่มีใครดึง มันจะไม่มีวันจบเลย
    """
    f5, rvc = FakeF5(), FakeRvc()
    before = set(threading.enumerate())
    gen = voice.text_to_roste_voice_segments(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path), prefetch=1)
    next(gen)
    time.sleep(0.3)
    gen.close()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        extra = [t for t in threading.enumerate()
                 if t not in before and t.name.startswith("tts-produce-")]
        if not extra:
            break
        time.sleep(0.05)
    assert not extra, f"producer thread ค้างหลังปิด generator: {extra}"


def test_no_f5_worker_single_edge_segment(edge_ok, tmp_path):
    got = _collect("สวัสดีค่ะ", None, FakeRvc(), tmp_path, filename="t")
    assert [os.path.basename(p) for p in got] == ["t_rvc.wav"]
    assert edge_ok == ["สวัสดีค่ะ"]


def test_empty_text_raises(tmp_path):
    with pytest.raises(ValueError):
        list(voice.text_to_roste_voice_segments("🎶✨", out_dir=str(tmp_path)))


# ---------- API เดิม (regression หลัง refactor) ----------

def test_text_to_roste_voice_returns_single_concat_file(
        three_segments, edge_ok, tmp_path):
    f5, rvc = FakeF5(), FakeRvc()
    out = voice.text_to_roste_voice(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path), filename="one")

    assert os.path.basename(out) == "one_rvc.wav"
    assert os.path.exists(out)
    # ไฟล์ segment ระหว่างทางถูกลบหมด เหลือไฟล์เดียว
    assert os.listdir(tmp_path) == ["one_rvc.wav"]
    # ยาวกว่า segment เดียว (concat 3 ชิ้น + silence 150ms×2)
    dur = sf.info(out).frames / sf.info(out).samplerate
    assert dur > 0.3


def test_text_to_roste_voice_single_segment_no_concat(edge_ok, tmp_path, monkeypatch):
    # ไม่มี f5_worker → เส้น edge ไฟล์เดียว → os.replace ไม่ผ่าน _concat_wavs
    out = voice.text_to_roste_voice(
        "สั้นๆ", worker=FakeRvc(), out_dir=str(tmp_path), filename="one")
    assert os.path.basename(out) == "one_rvc.wav"
    assert os.listdir(tmp_path) == ["one_rvc.wav"]


def test_text_to_roste_voice_all_fail_raises(three_segments, edge_broken, tmp_path):
    f5 = FakeF5(fail_calls=set(range(1, 10)))
    with pytest.raises(RuntimeError):
        voice.text_to_roste_voice(
            "อะไรก็ได้", worker=FakeRvc(), f5_worker=f5, out_dir=str(tmp_path))


# ── years_to_thai — อ่านปี พ.ศ./ค.ศ. ทีละหลัก ─────────────────────────────────

class TestYearsToThai:
    def test_year_after_full_month(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("อัปเดตวันที่ 30 มิถุนายน 2569")
        assert "สองห้าหกเก้า" in out
        assert "สองพันห้าร้อยหกสิบเก้า" not in out

    def test_year_after_por_sor(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("พ.ศ. 2569 เป็นปีนี้")
        assert "พอศอ สองห้าหกเก้า" in out

    def test_year_after_kor_sor(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("ค.ศ. 2026")
        assert "คอศอ สองศูนย์สองหก" in out

    def test_year_after_pee(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("ปี 2569 ฝนเยอะ")
        assert "ปี สองห้าหกเก้า" in out

    def test_year_after_abbrev_month(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("2 ก.ค. 2569")
        assert "สองห้าหกเก้า" in out

    def test_plain_amount_not_digit_read(self):
        from f5_preprocess import preprocess_for_f5
        # เลข 4 หลักที่ไม่ใช่บริบทปี ต้องอ่านแบบจำนวนเหมือนเดิม
        out, _ = preprocess_for_f5("ราคา 2500 บาท")
        assert "สองพันห้าร้อย บาท" in out
        assert "สองห้าศูนย์ศูนย์" not in out

    def test_month_abbrev_not_confused_with_era(self):
        from f5_preprocess import preprocess_for_f5
        # พ.ค. (พฤษภาคม) ต้องไม่โดนกฎ พ.ศ. — ปียังอ่านทีละหลักผ่านกฎเดือนย่อ
        out, _ = preprocess_for_f5("15 พ.ค. 2569")
        assert "สองห้าหกเก้า" in out
        assert "พอศอ" not in out


# ── หน่วยจากข้อมูล TMD ที่ F5 อ่านผิด (สะกดตัวอักษรแทนคำเต็ม) ──────────────────

class TestUnitAbbreviations:
    def test_mm_expands_to_full_word(self):
        from f5_preprocess import preprocess_for_f5
        # บั๊กที่เจอจริง: "0.2 มม." ถูก F5 อ่านสะกดตัวอักษร "มอมอ"
        out, _ = preprocess_for_f5("ปริมาณฝนรวม 0.2 มม.")
        assert "มิลลิเมตร" in out
        assert "มม." not in out

    def test_percent_expands_to_full_word(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("ความชื้น 79%")
        assert "เปอร์เซ็นต์" in out
        assert "%" not in out


# ── ๆ (ไม้ยมก) — ต้องขยายเป็นคำซ้ำก่อนส่ง F5 (F5 อ่าน ๆ ไม่ได้เลยถ้าส่งดิบๆ) ────────
# regression: expand_mai_yamok() ถูกเขียนใหม่ตอน integrate F5 v2 (9f5bc24) แต่หลุดจาก
# preprocess_for_f5 pipeline ไปเงียบๆ ทั้งที่เคย wire ไว้แล้วใน d67431e

class TestMaiYamokInPipeline:
    def test_mai_yamok_expanded_through_full_pipeline(self):
        from f5_preprocess import preprocess_for_f5
        out, _ = preprocess_for_f5("จริงๆ นะคะ")
        assert "ๆ" not in out
        assert "จริงจริง" in out


# ── worker hang timeout — บั๊กจริงที่เจอ: worker subprocess ค้าง (GPU stall) ทำ
#    music.voice_lock/_tts_lock ค้างตลอดไปเพราะ readline() เดิมไม่มี timeout ──────

import queue
import threading
import time as _time


class _HangingStdout:
    """จำลอง subprocess.stdout ที่ readline() ค้างตลอดไป (ไม่มีวันคืนค่า) จนกว่าจะถูก kill"""

    def __init__(self):
        self._killed = threading.Event()

    def readline(self):
        self._killed.wait()   # ค้างจน kill() ถูกเรียก (จำลอง process หยุดตอบสนอง)
        return ""


class _FakeProc:
    """จำลอง subprocess.Popen แบบเพียงพอสำหรับเทส timeout — poll()/stdin เป็น no-op, stdout ค้างได้"""

    def __init__(self):
        self.stdout = _HangingStdout()
        self.stdin = type("_Stdin", (), {"write": lambda self, s: None,
                                          "flush": lambda self: None})()
        self.killed = False

    def poll(self):
        return None if not self.killed else 1

    def kill(self):
        self.killed = True
        self.stdout._killed.set()   # จำลองว่า process ตายแล้ว readline() คืนค่าว่างได้ (unblock thread ทิ้ง)


class TestReadlineWithTimeout:
    def test_returns_line_when_available_immediately(self):
        proc = _FakeProc()
        proc.stdout.readline = lambda: "hello\n"
        assert voice._readline_with_timeout(proc, timeout=1.0) == "hello\n"

    def test_returns_none_when_hung_past_timeout(self):
        proc = _FakeProc()
        t0 = _time.monotonic()
        result = voice._readline_with_timeout(proc, timeout=0.2)
        elapsed = _time.monotonic() - t0
        assert result is None
        assert elapsed < 1.0   # ไม่ควรรอเกิน timeout ไปมาก


class TestRvcWorkerTimeout:
    def test_convert_kills_process_and_raises_on_hang(self):
        w = voice.RvcWorker()
        w._proc = _FakeProc()
        with pytest.raises(RuntimeError, match="ไม่ตอบสนอง"):
            w.convert("in.wav", "out.wav", timeout=0.2)
        assert w._proc is None   # _kill() เซ็ต _proc=None ให้ .alive เป็น False ต่อไป
        assert w.alive is False

    def test_worker_dead_after_timeout_kill(self):
        w = voice.RvcWorker()
        w._proc = _FakeProc()
        try:
            w.convert("in.wav", "out.wav", timeout=0.2)
        except RuntimeError:
            pass
        assert w.alive is False


class TestF5WorkerTimeout:
    def test_generate_kills_process_and_raises_on_hang(self):
        w = voice.F5Worker()
        w._proc = _FakeProc()
        with pytest.raises(RuntimeError, match="ไม่ตอบสนอง"):
            w.generate(ref_audio="ref.wav", ref_text="x", gen_text="y",
                       out_path="out.wav", timeout=0.2)
        assert w._proc is None
        assert w.alive is False


# ── stderr drain — บั๊กจริงที่อาจเกิด: worker เขียน stderr เยอะตอนโหลดโมเดล (torch/cuda
#    warnings) ถ้าไม่มีใคร drain แล้ว pipe buffer เต็ม (~64KB บน Windows) subprocess จะ block
#    ตอนเขียน stderr เพิ่ม ทำให้ start() ค้างตลอดไป (ไม่มี timeout ในตัว) ──────────────────────

import sys as _sys
from pathlib import Path as _Path

_STDERR_SPAM_RVC_SCRIPT = (
    "import sys\n"
    "sys.stderr.write('x' * 100_000)\n"
    "sys.stderr.flush()\n"
    "print('{\"status\": \"ready\"}')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.readline()\n"
)

_STDERR_SPAM_F5_SCRIPT = (
    "import sys\n"
    "sys.stderr.write('x' * 100_000)\n"
    "sys.stderr.flush()\n"
    "print('F5_WORKER_READY')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.readline()\n"
)


def _run_start_with_timeout(worker, timeout=5.0):
    """รัน worker.start() ใน thread แยกพร้อม wall-clock timeout — start() เดิมไม่มี timeout
    ในตัวเลย (ต่างจาก convert()/generate()) ถ้า drain ไม่ทำงาน test นี้จะค้างจริง ต้องกันด้วย
    thread + timeout ไม่ให้ pytest ทั้ง session แขวนตามไปด้วย"""
    done = threading.Event()
    result = {}

    def _run():
        try:
            worker.start()
            result["ok"] = True
        except Exception as e:
            result["error"] = e
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    finished = done.wait(timeout=timeout)
    return finished, result


class TestStderrDrain:
    def test_rvc_worker_start_does_not_hang_on_stderr_spam(self, tmp_path, monkeypatch):
        script = tmp_path / "fake_rvc_worker.py"
        script.write_text(_STDERR_SPAM_RVC_SCRIPT, encoding="utf-8")
        monkeypatch.setattr(voice, "_RVC_VENV_PY", _Path(_sys.executable))
        monkeypatch.setattr(voice, "_WORKER_PY", script)

        w = voice.RvcWorker()
        try:
            finished, result = _run_start_with_timeout(w, timeout=5.0)
            assert finished, "start() ค้าง — stderr ไม่ถูก drain ทำให้ pipe เต็มแล้ว subprocess block"
            assert result.get("ok") is True, result.get("error")
            assert w.alive is True
        finally:
            w.stop()

    def test_f5_worker_start_does_not_hang_on_stderr_spam(self, tmp_path, monkeypatch):
        script = tmp_path / "fake_f5_worker.py"
        script.write_text(_STDERR_SPAM_F5_SCRIPT, encoding="utf-8")
        monkeypatch.setattr(voice, "_F5_VENV_PY", _Path(_sys.executable))
        monkeypatch.setattr(voice, "_F5_WORKER_PY", script)

        w = voice.F5Worker()
        try:
            finished, result = _run_start_with_timeout(w, timeout=5.0)
            assert finished, "start() ค้าง — stderr ไม่ถูก drain ทำให้ pipe เต็มแล้ว subprocess block"
            assert result.get("ok") is True, result.get("error")
            assert w.alive is True
        finally:
            w.stop()

    def test_stderr_lines_available_in_ring_buffer_on_death_before_ready(self, tmp_path, monkeypatch):
        """worker ตายก่อน ready ต้องยังรายงาน stderr ได้ (จาก ring buffer แทน .stderr.read()
        ตรงๆ เพราะ drain thread อ่าน stderr ไปแล้ว — .read() ตรงจะได้ผลลัพธ์ว่างเปล่า)"""
        script = tmp_path / "fake_dying_worker.py"
        script.write_text(
            "import sys\n"
            "sys.stderr.write('boom: something went wrong\n')\n"
            "sys.stderr.flush()\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(voice, "_RVC_VENV_PY", _Path(_sys.executable))
        monkeypatch.setattr(voice, "_WORKER_PY", script)

        w = voice.RvcWorker()
        finished, result = _run_start_with_timeout(w, timeout=5.0)
        assert finished
        assert "error" in result
        assert "boom: something went wrong" in str(result["error"])


# ============================================================
#  _split_thai_text — การซอยข้อความไทยสำหรับ F5
#
#  ทำไมต้องมีเทสชุดนี้: เดิมฟังก์ชันนี้ถูก mock ทิ้งในทุกเทส ไม่เคยมีใครเช็คพฤติกรรมจริง
#  ทั้งที่มันตัดสินว่าเสียงจะเพี้ยนหรือไม่ — ภาษาไทยไม่เขียนเว้นวรรคระหว่างคำ ตัดผิดตำแหน่ง
#  = F5 อ่านผิดคำทันที (เจอจริง: ตัดที่ตัวที่ 100 ได้ 'ทุกวั' | 'นที่ผ่าน')
# ============================================================

def _word_boundary_set(text):
    """ตำแหน่งทั้งหมดที่เป็นขอบเขตคำจริงของ text (ใช้ตรวจว่าจุดตัดปลอดภัย)"""
    from pythainlp.tokenize import word_tokenize
    bounds, off = {0}, 0
    for tok in word_tokenize(text, engine="newmm", keep_whitespace=True):
        off += len(tok)
        bounds.add(off)
    return bounds


class TestSplitThaiText:

    LONG_NO_SPACE = (
        "การเรียนรู้สิ่งใหม่ทุกวันทำให้ชีวิตมีความหมายและเราจะเติบโตขึ้น"
        "เรื่อยๆอย่างไม่มีที่สิ้นสุดในทุกทุกวันที่ผ่านไปนะคะ"
    ) * 2
    WEATHER = (
        "วันนี้อากาศที่ชุมพรมีเมฆบางส่วนนะคะ อุณหภูมิประมาณสามสิบสององศา "
        "ช่วงบ่ายอาจมีฝนตกเล็กน้อยประมาณสามสิบเปอร์เซ็นต์ค่ะ "
        "ถ้าจะออกไปข้างนอกพกร่มติดตัวไว้หน่อยก็ดีนะคะ "
        "ส่วนพรุ่งนี้อากาศจะดีขึ้น ฝนน้อยลงเหลือแค่สิบเปอร์เซ็นต์"
    )

    @pytest.mark.parametrize("text", [
        LONG_NO_SPACE,
        WEATHER,
        "รอสเต้อยากบอกว่าการดูแลสุขภาพเป็นเรื่องสำคัญมากนะคะ " * 6,
        "ดีเซล 32.94 บาท เบนซิน 41.500 บาท แก๊สโซฮอล์ 95 อยู่ที่ 37.35 บาท",
        "สวัสดีค่ะ",
    ])
    def test_content_preserved_exactly(self, text):
        """เนื้อหาต้องครบทุกตัวอักษรหลังซอย — ตัวอักษรหายแม้ตัวเดียว = ผู้ใช้ไม่ได้ยินคำนั้น"""
        segs = voice._split_thai_text(text)
        assert "".join(segs).replace(" ", "") == text.replace(" ", "")

    @pytest.mark.parametrize("text", [LONG_NO_SPACE, WEATHER])
    def test_never_cuts_mid_word(self, text):
        """จุดตัดทุกจุดต้องตรงกับขอบเขตคำจริง — หัวใจของการซอยภาษาไทย

        เดิม fallback เป็น remaining[:max_chars] ดิบๆ ตัดกลางคำได้ ('ทุกวั'|'นที่ผ่าน')
        """
        segs = voice._split_thai_text(text)
        if len(segs) < 2:
            pytest.skip("ข้อความนี้ไม่ถูกซอย ไม่มีจุดตัดให้ตรวจ")
        bounds = _word_boundary_set(text)
        pos = 0
        for seg in segs[:-1]:
            idx = text.find(seg.strip(), pos)
            assert idx >= 0, "หา segment ในข้อความเดิมไม่เจอ"
            end = idx + len(seg.strip())
            assert end in bounds, (
                f"ตัดกลางคำที่ตำแหน่ง {end}: "
                f"{text[max(0, end-10):end]!r} | {text[end:end+10]!r}")
            pos = end

    def test_no_empty_segments(self):
        for text in [self.LONG_NO_SPACE, self.WEATHER, "สวัสดีค่ะ", "  ", ""]:
            assert all(s.strip() for s in voice._split_thai_text(text))

    def test_short_text_not_split(self):
        assert voice._split_thai_text("สวัสดีค่ะ") == ["สวัสดีค่ะ"]

    def test_segments_stay_near_target_length(self):
        """ความยาวต้องสม่ำเสมอราว target — ตัวที่ยาวผิดปกติทำให้ตัวถัดไปเจนไม่ทัน

        เดิมได้ 31c/120c/144c (ต่างกัน 4 เท่า) segment แรกเล่นจบก่อนอันถัดไปเจนเสร็จ
        ผู้ฟังเลยได้ยินเงียบคั่นทั้งที่ระบบตามทันอยู่
        """
        segs = voice._split_thai_text(self.WEATHER, target=90)
        assert len(segs) > 1
        limit = int(90 * 1.25)
        assert all(len(s) <= limit for s in segs), [len(s) for s in segs]

    def test_merge_does_not_create_oversized_segment(self):
        """การยุบ segment สั้นต้องไม่ไปสร้างตัวยาวเกินแทน

        เจอจริงตอนพัฒนา: 36c + 125c ถูกยุบเป็น 160c ทั้งที่ target แค่ 90 —
        แก้ปัญหาหนึ่งแล้วสร้างอีกปัญหาที่กำลังพยายามแก้อยู่พอดี
        """
        segs = voice._split_thai_text(self.WEATHER, target=90)
        assert max(len(s) for s in segs) <= int(90 * 1.25)

    def test_falls_back_to_whole_text_when_no_safe_cut(self, monkeypatch):
        """หาขอบเขตคำไม่ได้ → ไม่ตัดเลย ดีกว่าตัดมั่วจนเสียงเพี้ยน"""
        monkeypatch.setattr(voice, "_thai_word_bounds", lambda t: [])
        text = "ก" * 400
        segs = voice._split_thai_text(text)
        assert segs == [text]

    def test_tokenizer_failure_is_not_fatal(self, monkeypatch):
        """pythainlp พังต้องไม่ทำให้ทั้ง pipeline ล้ม — เสียงยังต้องออก"""
        import pythainlp.tokenize as tk
        monkeypatch.setattr(
            tk, "word_tokenize",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        segs = voice._split_thai_text(self.LONG_NO_SPACE)
        assert "".join(segs).replace(" ", "") == self.LONG_NO_SPACE.replace(" ", "")

    def test_word_bounds_rejects_lossy_tokenizer(self, monkeypatch):
        """tokenizer ที่คืนเนื้อหาไม่ครบต้องถูกปฏิเสธ ไม่เอามาใช้หาจุดตัด"""
        import pythainlp.tokenize as tk
        monkeypatch.setattr(tk, "word_tokenize", lambda *a, **k: ["ตัดทิ้ง"])
        assert voice._thai_word_bounds("ข้อความจริงที่ยาวกว่านั้นมาก") == []


# ============================================================
#  split_lines_for_tts — รักษาขอบเขตบรรทัดไว้เป็นจุดตัด
#
#  preprocess_for_f5 ยุบ \n เป็นช่องว่าง (จำเป็นสำหรับ F5) แต่นั่นทำให้ขอบเขตประโยคที่
#  ชัดที่สุดหายไปด้วย เจอจริงกับคำตอบ markdown list (31 ก.ค.): "1." กลายเป็น "หนึ่ง."
#  แล้วถูกตัดไปค้างท้าย segment ก่อนหน้า แทนที่จะนำหน้าข้อของตัวเอง — ฟังแล้วสะดุด
# ============================================================

class TestSplitLinesForTTS:

    MARKDOWN_REPLY = (
        "การทักทายในภาษาญี่ปุ่นมีหลายแบบ ขึ้นอยู่กับบริบท เช่น:\n"
        "1. **คำว่าอาริงาโตะ** - เป็นคำขอบคุณทั่วไป\n"
        " - ใช้เมื่อต้องการขอบคุณคนอื่น\n"
        "2. **คำว่าโดโมอาริงาโตะ** - เป็นรูปแบบที่สุภาพมากขึ้น\n"
    )

    def test_no_newline_returns_single_piece(self):
        from f5_preprocess import split_lines_for_tts
        assert split_lines_for_tts("สวัสดีค่ะ") == ["สวัสดีค่ะ"]

    def test_blank_lines_dropped(self):
        from f5_preprocess import split_lines_for_tts
        assert split_lines_for_tts("บรรทัดหนึ่ง\n\n\nบรรทัดสอง") == ["บรรทัดหนึ่ง", "บรรทัดสอง"]

    def test_empty_text_returns_empty(self):
        from f5_preprocess import split_lines_for_tts
        assert split_lines_for_tts("") == []
        assert split_lines_for_tts("   \n  \n") == []

    def test_content_preserved_across_lines(self):
        from f5_preprocess import split_lines_for_tts
        parts = split_lines_for_tts(self.MARKDOWN_REPLY)
        joined = "".join(parts).replace(" ", "")
        original = self.MARKDOWN_REPLY.replace("\n", "").replace(" ", "")
        assert joined == original

    def test_list_number_leads_its_own_item(self):
        """หัวใจของบั๊ก: เลขข้อต้องนำหน้าข้อของตัวเอง ไม่ค้างท้าย segment ก่อนหน้า"""
        from f5_preprocess import preprocess_for_f5, split_lines_for_tts
        segs = []
        for line in split_lines_for_tts(self.MARKDOWN_REPLY):
            pre, _ = preprocess_for_f5(line)
            if pre.strip():
                segs.extend(voice._split_thai_text(pre))

        # ไม่มี segment ไหนลงท้ายด้วยเลขข้อลอยๆ ("...เช่น: หนึ่ง.")
        for s in segs:
            assert not s.rstrip().endswith(("หนึ่ง.", "สอง.", "สาม.")), \
                f"เลขข้อค้างท้าย segment: {s!r}"
        # และต้องมี segment ที่ขึ้นต้นด้วยเลขข้อจริง
        assert any(s.lstrip().startswith(("หนึ่ง.", "สอง.")) for s in segs), segs

    def test_single_line_behaves_same_as_before(self):
        """ข้อความบรรทัดเดียว (กรณีส่วนใหญ่) ต้องได้ผลเหมือนเดิมทุกประการ"""
        from f5_preprocess import preprocess_for_f5, split_lines_for_tts
        text = "วันนี้อากาศดีนะคะ อุณหภูมิสามสิบองศา ลมพัดเย็นสบายเลย"
        pre_whole, _ = preprocess_for_f5(text)
        via_lines = []
        for line in split_lines_for_tts(text):
            p, _ = preprocess_for_f5(line)
            via_lines.extend(voice._split_thai_text(p))
        assert via_lines == voice._split_thai_text(pre_whole)

    def test_generator_respects_line_boundaries_end_to_end(self, edge_ok, tmp_path, monkeypatch):
        """เส้นทางจริงใน text_to_roste_voice_segments ต้องแยกบรรทัดก่อน preprocess

        เทสข้างบนเรียก helper ตรงๆ จึงไม่จับว่า voice.py ต่อสายถูกไหม — ตัวนี้ยิงผ่าน
        generator จริงเพื่อกันกรณีมีคนแก้ให้กลับไป preprocess ทั้งก้อนก่อนซอย
        """
        import f5_preprocess
        monkeypatch.undo()   # ใช้ preprocess ตัวจริง ไม่ใช่ identity ของ fixture อื่น
        f5, rvc = FakeF5(), FakeRvc()
        list(voice.text_to_roste_voice_segments(
            self.MARKDOWN_REPLY, worker=rvc, f5_worker=f5,
            out_dir=str(tmp_path), prefetch=0))

        assert f5.calls, "ไม่มี segment ถูกสร้างเลย"
        for seg in f5.calls:
            assert not seg.rstrip().endswith(("หนึ่ง.", "สอง.", "สาม.")), \
                f"เลขข้อค้างท้าย segment ที่ส่งเข้า F5 จริง: {seg!r}"
