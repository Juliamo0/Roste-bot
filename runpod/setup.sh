#!/usr/bin/env bash
# ============================================================
#  ติดตั้งรอสเต้บน RunPod (Linux) แบบครบ — เทียบเท่า setup.bat + venv เสียง
#  ใช้: bash runpod/setup.sh
#
#  ทุกอย่างลง network volume (/workspace) — ครั้งแรก ~25 นาที ครั้งต่อไปข้ามของที่มี
#  แล้วเกือบหมด เหลือแค่ apt (container disk ถูกล้างทุกรอบ)
#  ไม่ลง: typhoon_asr_venv (STT_ENABLED=False ใน bot.py), voxcpm_venv (VOXCPM_ENABLED=False)
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source runpod/env.sh
mkdir -p "$VOL/bin" "$VOL/ollama" "$OLLAMA_MODELS"

echo "== [1/6] apt: ffmpeg (เล่นเพลง/ปรับเสียง) + zstd (แตกไฟล์ Ollama) =="
# อยู่บน container disk — หายทุกรอบ แต่ลงแค่ ~20 วิ ไม่คุ้มย้ายไป volume
if ! command -v ffmpeg >/dev/null || ! command -v zstd >/dev/null; then
    apt-get update -qq
    apt-get install -y -qq ffmpeg zstd curl >/dev/null
fi

echo "== [2/6] Ollama (ลงใน volume ไม่ใช่ /usr/local) =="
if ! command -v ollama >/dev/null; then
    # แตก tarball ตรงเข้า volume แทน install.sh — install.sh ลง /usr/local ซึ่งหายทุกครั้งที่
    # stop pod ทำให้ต้องโหลด ~1.5GB (รวม CUDA libs) ใหม่ทุกรอบ
    if ! curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst \
            | zstd -d | tar -x -C "$VOL/ollama"; then
        echo "   โหลด tarball ไม่ได้ — ใช้ install.sh แทน (จะหายเมื่อ stop pod)"
        curl -fsSL https://ollama.com/install.sh | sh
    fi
fi
start_ollama
# โมเดลเดียวกับ default ใน config.py (OLLAMA_MODEL / OLLAMA_EXTRACT_MODEL) + vectormemory.EMBED_MODEL
for m in "${OLLAMA_MODEL:-qwen3:8b}" "${OLLAMA_EXTRACT_MODEL:-qwen3:4b}" bge-m3; do
    ollama pull "$m"
done

echo "== [3/6] uv + Python 3.10 =="
# image ของ RunPod มี Python 3.11 — f5/rvc ทดสอบไว้แค่ 3.10 (README) ใช้ uv โหลด 3.10 มาเก็บใน volume
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$VOL/bin" UV_NO_MODIFY_PATH=1 sh
fi
uv python install 3.10

# venv ที่ก๊อปมาจาก Windows ใช้ไม่ได้ (มีแต่ Scripts/python.exe) — สร้างใหม่ทับ
# --seed ให้มี pip ใน venv: voice.py เรียก <venv>/bin/python ตรงๆ ไม่ได้ผ่าน uv
make_venv() {
    [[ -x "$1/bin/python" ]] || { rm -rf "$1"; uv venv --seed --python 3.10 "$1"; }
}

echo "== [4/6] venv หลัก (bot.py + pytest) =="
make_venv venv
venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt

echo "== [5/6] f5_venv + rvc_venv (ดู README หัวข้อ f5_venv / rvc_venv) =="
for v in f5_venv rvc_venv; do
    make_venv $v
    $v/bin/pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cu128
done
f5_venv/bin/pip install -q f5-tts-th
rvc_venv/bin/pip install -q rvc-python==0.1.5

echo "== [6/6] เช็คไฟล์ที่ไม่อยู่ใน git =="
missing=0
for f in ref_audio/lai_seg4_160s.wav; do
    [[ -f $f ]] || { echo "   ขาด: $f"; missing=1; }
done
ls "$RVC_MODEL_DIR"/*.pth >/dev/null 2>&1 || { echo "   ขาด: $RVC_MODEL_DIR/*.pth (โมเดล RVC — ที่บ้านอยู่ D:\\rvc_voice_model)"; missing=1; }
if [[ $missing == 1 ]]; then
    echo "   ต้องอัปขึ้น volume เอง (runpodctl send / scp) — ถ้าไม่มี voice.py จะ fallback"
    echo "   ไป edge-tts ให้เอง บอทไม่ล่ม แต่จะไม่ใช่เสียงรอสเต้"
fi

echo
echo "เสร็จแล้ว — เทส: bash runpod/test.sh | รันบอท: bash runpod/start.sh"
