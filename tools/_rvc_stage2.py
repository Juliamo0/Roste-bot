"""Stage 2: f5_raw.wav → RVC Laibaht  (รันด้วย rvc_venv)"""
import sys, time, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

args      = json.loads(sys.argv[1])
in_path   = args["in_path"]
out_path  = args["out_path"]
f0_key    = args.get("f0_key", 0)

MODEL_DIR  = r"D:\LaibahtMaLaew"
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
