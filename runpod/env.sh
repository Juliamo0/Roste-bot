# ค่ากลางที่ทุกสคริปต์ใน runpod/ source เข้าไป — ไม่ได้รันเดี่ยว
#
# network volume ต่อเข้า pod ที่ /workspace และอยู่รอดแม้ terminate pod ทิ้ง
# ส่วน container disk (/usr, /root, /tmp) หายทุกครั้งที่ stop — ของที่โหลดนาน
# จึงต้องชี้มาที่ volume ทั้งหมด ไม่งั้นเปิด pod ใหม่ต้องโหลด ~30GB ใหม่ทุกรอบ

VOL="${ROSTE_VOLUME:-/workspace}"

# ตัวโปรแกรม (ollama, uv) — เดิม install.sh ของ Ollama ลงที่ /usr/local ซึ่งหายทุกรอบ
export PATH="$VOL/bin:$VOL/ollama/bin:$PATH"
export OLLAMA_MODELS="$VOL/ollama-models"
# bind localhost เท่านั้น: Ollama ไม่มี auth ถ้า expose port ออกไป ใครก็ใช้ GPU เราได้
export OLLAMA_HOST="127.0.0.1:11434"

# cache ที่ worker เสียงโหลดเองตอน start ครั้งแรก (F5/NeMo ดึงจาก Hugging Face)
# ถ้าไม่ย้าย จะโหลด checkpoint ใหม่ทุกครั้งที่เปิด pod แม้ venv จะอยู่ครบ
export HF_HOME="$VOL/.cache/huggingface"
export TORCH_HOME="$VOL/.cache/torch"
export PIP_CACHE_DIR="$VOL/.cache/pip"
export UV_CACHE_DIR="$VOL/.cache/uv"
# โมเดล RVC อยู่นอก repo (default ใน voice.py = D:\rvc_voice_model ของเครื่องบ้าน)
# voice_rvc_worker อ่านค่านี้จาก env ที่ bot ส่งต่อให้ (voice.MODEL_DIR)
export RVC_MODEL_DIR="${RVC_MODEL_DIR:-$VOL/rvc_voice_model}"
# Python ที่ uv โหลดมา (3.10 ให้ตรงกับเครื่อง dev — README ระบุ f5/rvc ต้อง 3.10)
export UV_PYTHON_INSTALL_DIR="$VOL/.python"

ollama_up() {
    curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null
}

start_ollama() {
    ollama_up && return 0
    nohup ollama serve >"$VOL/ollama.log" 2>&1 &
    for _ in $(seq 1 30); do
        ollama_up && return 0
        sleep 1
    done
    echo "[X] Ollama ไม่ขึ้นใน 30 วิ — ดู $VOL/ollama.log"
    return 1
}
