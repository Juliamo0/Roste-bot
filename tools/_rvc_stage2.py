"""Stage 2: f5_raw.wav → RVC  (รันด้วย rvc_venv)"""
import sys, time, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

args      = json.loads(sys.argv[1])
in_path   = args["in_path"]
out_path  = args["out_path"]
f0_key    = args.get("f0_key", 0)

# torch>=2.6 flipped torch.load default to weights_only=True, which rejects
# fairseq's hubert_base.pt (it stores a fairseq Dictionary global) and makes RVC
# fail with a downstream "'tuple' object has no attribute 'dtype'". The RVC base
# models are local and trusted, so restore the pre-2.6 behaviour. Needed on
# Blackwell (torch 2.11/cu128) where downgrading torch is not an option.
# (patch เดียวกับ voice_rvc_worker.py — สคริปต์นี้ตกหล่นตอนย้ายเครื่อง)
import torch as _torch
_orig_torch_load = _torch.load
def _torch_load_compat(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_torch_load(*args, **kwargs)
_torch.load = _torch_load_compat

# path โมเดลเสียง RVC — แต่ละเครื่องวางคนละที่ (แล็ปท็อป D:\ , PC Server ไม่มี
# ไดรฟ์ D: → C:\Users\User\...) จึงอ่านจาก env ก่อน
#
# สคริปต์นี้ถูกเรียกตรงๆ จาก rvc_venv ได้ (ไม่ผ่าน voice.py) จึงไม่มีใคร load_dotenv
# ให้ และ rvc_venv ก็อาจไม่มี python-dotenv ติดตั้ง — อ่าน .env เองแบบง่ายๆ
# ไม่งั้นจะตกไปใช้ค่า default D:\ แล้วพังบน PC Server (บั๊กที่เพิ่งเจอมา)
def _model_dir() -> str:
    env = os.getenv("RVC_MODEL_DIR")
    if env:
        return env
    dotenv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(dotenv):
        try:
            with open(dotenv, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("RVC_MODEL_DIR="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return r"D:\rvc_voice_model"

MODEL_DIR  = _model_dir()
DEVICE     = "cuda:0"
INDEX_RATE = 0.5
PROTECT    = 0.33

files = os.listdir(MODEL_DIR)
pth   = next((f for f in files if f.endswith(".pth")), None)
idx   = next((f for f in files if f.endswith(".index")), None)
model_path = os.path.join(MODEL_DIR, pth)
index_path = os.path.join(MODEL_DIR, idx) if idx else None

t0 = time.perf_counter()
from rvc_python.infer import RVCInference
rvc = RVCInference(device=DEVICE)
rvc.load_model(model_path, index_path=index_path)
rvc.set_params(f0up_key=f0_key, f0method="rmvpe",
               index_rate=INDEX_RATE, protect=PROTECT)
load_time = time.perf_counter() - t0
print(f"RVC_LOAD_TIME={load_time:.1f}")

os.makedirs(os.path.dirname(out_path), exist_ok=True)
t1 = time.perf_counter()
rvc.infer_file(input_path=in_path, output_path=out_path)
conv_time = time.perf_counter() - t1
print(f"RVC_CONV_TIME={conv_time:.1f}")
print(f"RVC_OUT={out_path}")
