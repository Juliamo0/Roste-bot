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
    f5, rvc = FakeF5(), FakeRvc()
    got = []
    gen = voice.text_to_roste_voice_segments(
        "อะไรก็ได้", worker=rvc, f5_worker=f5, out_dir=str(tmp_path))
    got.append(next(gen))     # seg0 เส้น F5 ปกติ
    f5.alive = False          # worker ตายกลางคัน
    got.extend(gen)           # seg1, seg2 ต้องไปเส้น edge-tts ต่อ ไม่เงียบ

    assert len(got) == 3
    assert f5.calls == [three_segments[0]]           # F5 ไม่ถูกเรียกอีกหลังตาย
    assert edge_ok == three_segments[1:]             # ที่เหลือ edge-tts ครบ


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
