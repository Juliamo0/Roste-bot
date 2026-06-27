"""Stage 1: F5-TTS → f5_raw.wav  (รันด้วย f5_venv)"""
import sys, time, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

args = json.loads(sys.argv[1])
ref_audio = args["ref_audio"]
ref_text  = args["ref_text"]
gen_text  = args["gen_text"]
out_path  = args["out_path"]
speed     = args.get("speed", 0.9)

os.makedirs(os.path.dirname(out_path), exist_ok=True)

import torch
t0 = time.perf_counter()
from f5_tts_th.tts import TTS
tts = TTS(model="v2")
load_time = time.perf_counter() - t0
vram_after_load = torch.cuda.memory_allocated() / 1024**2 if torch.cuda.is_available() else 0
print(f"F5_LOAD_TIME={load_time:.1f}")
print(f"F5_VRAM_LOAD={vram_after_load:.0f}")

import soundfile as sf
t1 = time.perf_counter()
wav = tts.infer(
    ref_audio=ref_audio,
    ref_text=ref_text,
    gen_text=gen_text,
    step=32,
    cfg=2.0,
    speed=speed,
)
gen_time = time.perf_counter() - t1
duration = len(wav) / 24000
vram_peak = torch.cuda.memory_reserved() / 1024**2 if torch.cuda.is_available() else 0

sf.write(out_path, wav, 24000)
print(f"F5_GEN_TIME={gen_time:.1f}")
print(f"F5_DURATION={duration:.1f}")
print(f"F5_VRAM_PEAK={vram_peak:.0f}")
print(f"F5_OUT={out_path}")
