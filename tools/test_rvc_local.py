"""
ทดสอบ RVC GPU — วัดเวลาแปลง 3 รอบ (โหลดโมเดลครั้งเดียว) + VRAM ที่ใช้จริง

วิธีใช้:
  rvc_venv\\Scripts\\python tools/test_rvc_local.py
"""

import os
import sys
import time
import glob
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── ตั้งค่าตรงนี้ ──────────────────────────────────────────────────────────────
MODEL_DIR   = r"D:\LaibahtMaLaew"
DEVICE      = "cuda:0"   # "cuda:0" = GPU, "cpu" = CPU
F0_METHOD   = "rmvpe"    # rmvpe (แม่น), pm, harvest, crepe
F0_UP_KEY   = 0          # semitones — ตั้ง 0 เพราะปรับมาแล้วใน adjust_raw.py
INDEX_RATE  = 0.5        # 0.0–1.0 ยิ่งสูงยิ่งคล้ายเสียงต้นแบบ
PROTECT     = 0.33
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "..")
INPUT_DIR   = os.path.join(PROJECT_DIR, "tts_adjusted")
OUTPUT_DIR  = os.path.join(PROJECT_DIR, "rvc_out")


def _find_model_files():
    if not os.path.isdir(MODEL_DIR):
        return None, None
    pth   = [f for f in os.listdir(MODEL_DIR) if f.endswith(".pth")]
    index = [f for f in os.listdir(MODEL_DIR) if f.endswith(".index")]
    return (
        os.path.join(MODEL_DIR, pth[0])   if pth   else None,
        os.path.join(MODEL_DIR, index[0]) if index else None,
    )


def _vram_mb() -> tuple[int, int]:
    """(allocated_MB, reserved_MB) จาก torch CUDA"""
    import torch
    alloc = torch.cuda.memory_allocated(0) // (1024 * 1024)
    rsrv  = torch.cuda.memory_reserved(0)  // (1024 * 1024)
    return alloc, rsrv


def _nvidia_smi_vram() -> str:
    """VRAM จาก nvidia-smi (ครอบคลุมทุก process รวม Ollama)"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            text=True, timeout=5
        ).strip()
        used, total = out.split(",")
        return f"{used.strip()} / {total.strip()} MiB"
    except Exception:
        return "N/A"


def main():
    import torch

    # ── header ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"Python : {sys.version.split()[0]}  |  torch {torch.__version__}")
    cuda_ok = torch.cuda.is_available()
    if cuda_ok:
        props = torch.cuda.get_device_properties(0)
        total_vram = props.total_memory // (1024 * 1024)
        print(f"GPU    : {props.name}  ({total_vram} MiB VRAM)")
    else:
        print("GPU    : ไม่พบ (จะใช้ CPU)")
    print(f"Device : {DEVICE}")
    print("=" * 60)

    # ── หาไฟล์ input ─────────────────────────────────────────────────────────
    all_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.wav")))
    if not all_files:
        print(f"\n❌ ไม่พบไฟล์ใน {INPUT_DIR}  รัน tools/adjust_raw.py ก่อน")
        sys.exit(1)
    files = all_files[:3]   # แปลง 3 ไฟล์แรก
    print(f"\nไฟล์ input ({len(files)} จาก {len(all_files)}):")
    for f in files:
        print(f"   {os.path.basename(f)}")

    # ── หาโมเดล ──────────────────────────────────────────────────────────────
    model_path, index_path = _find_model_files()
    if not model_path:
        print(f"\n❌ ไม่พบ .pth ใน {MODEL_DIR}")
        sys.exit(1)
    print(f"\nโมเดล : {os.path.basename(model_path)}")
    print(f"Index : {os.path.basename(index_path) if index_path else 'ไม่มี'}")

    # ── โหลดโมเดลครั้งเดียว ───────────────────────────────────────────────────
    from rvc_python.infer import RVCInference

    print(f"\n[โหลดโมเดล]  VRAM ก่อน: {_nvidia_smi_vram()}", flush=True)
    t_load_start = time.perf_counter()

    if cuda_ok:
        torch.cuda.reset_peak_memory_stats(0)

    rvc = RVCInference(device=DEVICE)
    rvc.load_model(model_path, index_path=index_path)
    rvc.set_params(f0up_key=F0_UP_KEY, f0method=F0_METHOD,
                   index_rate=INDEX_RATE, protect=PROTECT)

    t_load = time.perf_counter() - t_load_start
    alloc_after_load, rsrv_after_load = _vram_mb() if cuda_ok else (0, 0)
    print(f"  เสร็จใน {t_load:.1f}s")
    print(f"  VRAM หลังโหลด (torch): allocated={alloc_after_load} MiB  reserved={rsrv_after_load} MiB")
    print(f"  VRAM หลังโหลด (smi)  : {_nvidia_smi_vram()}")

    # ── แปลง 3 รอบ ───────────────────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"\n{'─'*60}")
    print(f"{'รอบ':<6} {'ไฟล์':<30} {'เวลา':>7}  {'VRAM peak (torch)':>18}")
    print(f"{'─'*60}")

    timings = []
    peak_vrams = []

    for i, f in enumerate(files, 1):
        base   = os.path.splitext(os.path.basename(f))[0]
        out    = os.path.join(OUTPUT_DIR, f"{base}_rvc.wav")

        if cuda_ok:
            torch.cuda.reset_peak_memory_stats(0)

        t0 = time.perf_counter()
        rvc.infer_file(input_path=f, output_path=out)
        elapsed = time.perf_counter() - t0

        if cuda_ok:
            peak_mb = torch.cuda.max_memory_allocated(0) // (1024 * 1024)
        else:
            peak_mb = 0

        timings.append(elapsed)
        peak_vrams.append(peak_mb)
        label = os.path.basename(f)[:28]
        print(f"  {i:<4} {label:<30} {elapsed:>6.1f}s  {peak_mb:>15} MiB")

    # ── สรุป ──────────────────────────────────────────────────────────────────
    print(f"{'─'*60}")
    print(f"\n[สรุป]")
    print(f"  โหลดโมเดล     : {t_load:.1f}s")
    print(f"  รอบ 1 (cold)  : {timings[0]:.1f}s  ← รวม Hubert+rmvpe โหลดครั้งแรก")
    if len(timings) > 1:
        warm = timings[1:]
        print(f"  รอบ 2-{len(timings)} (warm) : {', '.join(f'{t:.1f}s' for t in warm)}  ← เวลาจริงเมื่อโมเดลค้างใน VRAM")
        print(f"  เฉลี่ย warm   : {sum(warm)/len(warm):.1f}s")
    if cuda_ok and peak_vrams:
        max_peak = max(peak_vrams)
        remaining = total_vram - rsrv_after_load
        print(f"\n  VRAM peak ระหว่างแปลง : {max_peak} MiB")
        print(f"  VRAM reserved รวม    : {rsrv_after_load} MiB")
        print(f"  VRAM ว่างหลัง RVC    : {total_vram - rsrv_after_load} MiB")
        print(f"  VRAM smi ปัจจุบัน    : {_nvidia_smi_vram()}")
        print()
        qwen_need = 3500
        if remaining >= qwen_need:
            print(f"  ✅ VRAM เหลือพอให้ qwen3:8b (~{qwen_need} MiB) ค้างพร้อมกันได้")
        else:
            print(f"  ⚠️  VRAM เหลือ {remaining} MiB — qwen3:8b (~{qwen_need} MiB) อาจไม่พอ")
            print(f"     ต้อง unload qwen ก่อนรัน RVC หรือใช้ qwen3:1.7b")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
