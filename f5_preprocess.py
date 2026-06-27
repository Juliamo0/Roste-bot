"""
f5_preprocess.py — แก้ข้อความก่อนส่ง F5-TTS
import: from f5_preprocess import preprocess_for_f5
"""
import re

_D = ['ศูนย์','หนึ่ง','สอง','สาม','สี่','ห้า','หก','เจ็ด','แปด','เก้า']

def _int_to_thai(n: int) -> str:
    if n == 0: return 'ศูนย์'
    if n < 0:  return 'ลบ' + _int_to_thai(-n)
    if n <= 9:  return _D[n]
    if n <= 19:
        u = n % 10
        return 'สิบ' + ('' if u == 0 else 'เอ็ด' if u == 1 else _D[u])
    if n <= 99:
        t, u = divmod(n, 10)
        tens = 'ยี่สิบ' if t == 2 else _D[t] + 'สิบ'
        unit = '' if u == 0 else 'เอ็ด' if u == 1 else _D[u]
        return tens + unit
    if n <= 999:
        h, r = divmod(n, 100)
        return (_D[h]) + 'ร้อย' + (_int_to_thai(r) if r else '')
    if n <= 9_999:
        th, r = divmod(n, 1_000)
        return _D[th] + 'พัน' + (_int_to_thai(r) if r else '')
    if n <= 99_999:
        tm, r = divmod(n, 10_000)
        return _int_to_thai(tm) + 'หมื่น' + (_int_to_thai(r) if r else '')
    if n <= 999_999:
        hth, r = divmod(n, 100_000)
        return _int_to_thai(hth) + 'แสน' + (_int_to_thai(r) if r else '')
    if n <= 9_999_999:
        m, r = divmod(n, 1_000_000)
        return _int_to_thai(m) + 'ล้าน' + (_int_to_thai(r) if r else '')
    return ''.join(_D[int(d)] for d in str(n))

def _num_match(m: re.Match) -> str:
    s = m.group(0)
    if '.' in s:
        int_part, dec_part = s.split('.', 1)
        int_val = int(int_part) if int_part else 0
        return _int_to_thai(int_val) + 'จุด' + ''.join(_D[int(d)] for d in dec_part)
    return _int_to_thai(int(s))

def numbers_to_thai(text: str) -> str:
    """แปลงตัวเลขทั้งหมดในประโยคเป็นคำอ่านภาษาไทย"""
    text = re.sub(r'(\d),(\d{3})', r'\1\2', text)  # 1,500 → 1500
    return re.sub(r'\d+(?:\.\d+)?', _num_match, text)

_MAI_YAMOK_RE = re.compile(r'([เ-ไ]?[ก-ฮ][ะ-ฺ็-๎อ]*[ก-ฮ]?)ๆ')

def expand_mai_yamok(text: str) -> str:
    """ขยาย ๆ → ซ้ำคำสุดท้ายหน้า ๆ (Thai syllable regex — ไม่ซ้ำทั้ง phrase)
    เร็วๆ → เร็วเร็ว  |  น่าสนใจมากๆ → น่าสนใจมากมาก  |  ค่อยๆ → ค่อยค่อย
    ถ้าจับ syllable ไม่ได้ → ลบ ๆ ทิ้ง (F5 loop ถ้าส่ง ๆ ตรงๆ)
    """
    result = _MAI_YAMOK_RE.sub(r'\1\1', text)
    # ๆ ที่เหลือ (จับ syllable ไม่ได้) → ลบออก
    return re.sub(r'\s*ๆ', '', result)

def reduce_naka(text: str) -> str:
    """ลด 'นะคะ' ซ้ำ — เก็บแค่ตัวสุดท้าย"""
    if text.count('นะคะ') <= 1:
        return text
    parts = text.split('นะคะ')
    # ทุก part ยกเว้นสุดท้าย → ลบ whitespace ต่อท้าย แล้วรวม
    clean = ' '.join(p.strip() for p in parts[:-1]).strip()
    return clean + 'นะคะ' + parts[-1]

def preprocess_for_f5(text: str) -> tuple:
    """
    แปลงข้อความก่อนส่ง F5-TTS
    Returns: (processed_text, warnings: list[str])
    """
    warnings = []
    t = numbers_to_thai(text)
    t = expand_mai_yamok(t)
    t = reduce_naka(t)
    t = re.sub(r' +', ' ', t).strip()

    # warn อ+สระยาว กลางประโยค (ยัง fix อัตโนมัติไม่ได้)
    mid_or = re.findall(r'(?<= )(อา\w+|อี\w+|อู\w+|เอ\w+|โอ\w+|อย\w+|อว\w+)', t)
    if mid_or:
        warnings.append(f"⚠️  อ+สระยาว กลางประโยค: {mid_or}")

    return t, warnings


# ── unit tests ─────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=== Unit test: _int_to_thai ===")
    cases = [0,1,10,11,20,21,95,100,101,200,999,1000,1500,10000,100000]
    for n in cases:
        print(f"  {n:>7} → {_int_to_thai(n)}")

    print("\n=== Unit test: numbers_to_thai ===")
    num_cases = [
        ("47.38 บาท",         "สี่สิบเจ็ดจุดสามแปด บาท"),
        ("29.94 บาท",         "ยี่สิบเก้าจุดเก้าสี่ บาท"),
        ("38.85 บาท",         "สามสิบแปดจุดแปดห้า บาท"),
        ("33 องศา",           "สามสิบสาม องศา"),
        ("แก๊สโซฮอล์ 95",    "แก๊สโซฮอล์ เก้าสิบห้า"),
        ("ดีเซล 29.94 บาทต่อลิตร", "ดีเซล ยี่สิบเก้าจุดเก้าสี่ บาทต่อลิตร"),
        ("1,500 บาท",         "N/A (comma ไม่ถูก match)"),
    ]
    for text, expected in num_cases:
        got = numbers_to_thai(text)
        ok = "✅" if got == expected else "❓"
        print(f"  {ok} '{text}'")
        print(f"      → '{got}'")

    print("\n=== Unit test: remove_mai_yamok ===")
    mk_cases = [
        "มันน่าสนใจมากๆ เลยนะคะ",
        "ดีๆ และง่ายๆ",
        "ไม่มี mai yamok",
    ]
    for t in mk_cases:
        print(f"  '{t}' → '{remove_mai_yamok(t)}'")

    print("\n=== Unit test: reduce_naka ===")
    nk_cases = [
        "ลองดูนะคะ มันน่าสนใจนะคะ ง่ายด้วยนะคะ",
        "สวัสดีค่ะ มีอะไรให้ช่วยนะคะ",
        "แนะนำให้ลองนะคะ และก็ดูแลตัวเองด้วยนะคะ",
    ]
    for t in nk_cases:
        print(f"  '{t}'")
        print(f"  → '{reduce_naka(t)}'")

    print("\n=== preprocess_for_f5 full pipeline ===")
    full_cases = [
        "ราคาน้ำมันวันนี้ เบนซิน 95 อยู่ที่ 47.38 บาทต่อลิตรค่ะ ดีเซลอยู่ที่ 29.94 บาทต่อลิตรนะคะ",
        "อุณหภูมิวันนี้อยู่ที่ 34 องศาเซลเซียสค่ะ อากาศร้อนมากเลยนะคะ ระวังด้วยนะคะ",
        "ดีมากเลยค่ะ รอสเต้แนะนำให้ลองดูนะคะ มันน่าสนใจมากๆ เลยนะคะ และก็ง่ายๆ ด้วยนะคะ",
        "แก๊สโซฮอล์ 95 ราคา 38.85 บาท",
    ]
    for t in full_cases:
        out, warns = preprocess_for_f5(t)
        print(f"\n  IN : {t}")
        print(f"  OUT: {out}")
        for w in warns:
            print(f"       {w}")
