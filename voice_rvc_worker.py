"""
RVC warm worker — โหลดโมเดลครั้งเดียว รับงานหลายชิ้นผ่าน stdin/stdout JSON

Protocol:
  startup → stdout: {"status": "ready"}
  stdin:   {"input": "<path>", "output": "<path>"}\n
  stdout:  {"status": "done", "elapsed": 1.4}\n
           {"status": "error", "msg": "..."}\n
  ปิดด้วยการ close stdin (EOF)

รัน: rvc_venv\Scripts\python voice_rvc_worker.py
ปกติไม่ต้องรันเอง — voice.py จะ spawn อัตโนมัติ
"""

import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# torch>=2.6 flipped torch.load default to weights_only=True, which rejects
# fairseq's hubert_base.pt (it stores a fairseq Dictionary global) and makes RVC
# fail with a downstream "'tuple' object has no attribute 'dtype'". The RVC base
# models are local and trusted, so restore the pre-2.6 behaviour. Needed on
# Blackwell (torch 2.11/cu128) where downgrading torch is not an option.
import torch as _torch
_orig_torch_load = _torch.load
def _torch_load_compat(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_torch_load(*args, **kwargs)
_torch.load = _torch_load_compat

MODEL_DIR  = os.getenv("RVC_MODEL_DIR", r"D:\rvc_voice_model")  # inherit env จาก bot (parent) — server ตั้งใน .env
DEVICE     = "cuda:0"
F0_UP_KEY  = 0
F0_METHOD  = "rmvpe"
INDEX_RATE = 0.5
PROTECT    = 0.33


def _find_model():
    if not os.path.isdir(MODEL_DIR):
        return None, None
    files = os.listdir(MODEL_DIR)
    pth = next((f for f in files if f.endswith(".pth")), None)
    idx = next((f for f in files if f.endswith(".index")), None)
    return (
        os.path.join(MODEL_DIR, pth) if pth else None,
        os.path.join(MODEL_DIR, idx) if idx else None,
    )


def main():
    model_path, index_path = _find_model()
    if not model_path:
        print(json.dumps({"status": "error", "msg": f"ไม่พบ .pth ใน {MODEL_DIR}"}), flush=True)
        sys.exit(1)

    from rvc_python.infer import RVCInference

    rvc = RVCInference(device=DEVICE)
    rvc.load_model(model_path, index_path=index_path)
    rvc.set_params(
        f0up_key=F0_UP_KEY,
        f0method=F0_METHOD,
        index_rate=INDEX_RATE,
        protect=PROTECT,
    )

    # signal ready — voice.py waits for this line
    print(json.dumps({"status": "ready"}), flush=True)

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
            in_path  = req["input"]
            out_path = req["output"]
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            t0 = time.perf_counter()
            rvc.infer_file(input_path=in_path, output_path=out_path)
            elapsed = time.perf_counter() - t0
            print(json.dumps({"status": "done", "elapsed": round(elapsed, 3)}), flush=True)
        except Exception as exc:
            print(json.dumps({"status": "error", "msg": str(exc)}), flush=True)


if __name__ == "__main__":
    main()
