"""
📈 monitor.py — เว็บเซิร์ฟเวอร์เฝ้าดูสถานะบอท (localhost-only by default)

เปิดที่ 127.0.0.1:<MONITOR_PORT> (ตั้งค่าผ่าน .env: MONITOR_HOST/MONITOR_PORT — ไม่ตั้ง =
default 127.0.0.1:8765, ตั้ง MONITOR_PORT=0 = ปิดเซิร์ฟเวอร์นี้ทั้งหมด) รวมข้อมูลจาก stats.py
(latency ต่อข้อความ ตัวบอทเอง) + psutil (CPU/RAM/disk) + nvidia-smi (GPU) + Ollama /api/ps
(โมเดลที่โหลดอยู่ตอนนี้ — ตัวชี้วัด model swap ตรงๆ)

วินัยสำคัญ: endpoint นี้ห้ามส่งเนื้อหาข้อความ/ชื่อ user ออกไปเด็ดขาด — stats.py เก็บแค่ตัวเลข
อยู่แล้ว (ดู docstring stats.py) ส่วน bot-status callback ก็ต้องคืนแค่ตัวเลข/สถานะเช่นกัน

ทุกแหล่งข้อมูลภายนอก (nvidia-smi/Ollama) ต้อง degrade เป็น None เสมอถ้าไม่มี/ไม่ตอบ ไม่ crash
เพราะเครื่อง dev ปกติมี GPU+Ollama ครบ แต่ CI runner ไม่มีทั้งคู่ — ใส่ timeout สั้นทุกจุดกัน
dashboard ค้างถ้า Ollama/nvidia-smi ค้าง"""
import asyncio
import logging
import os
import time

import psutil
from aiohttp import ClientSession, ClientTimeout, web

import stats

logger = logging.getLogger("roste.monitor")

_NVIDIA_SMI_TIMEOUT_SEC = 2
_OLLAMA_PS_TIMEOUT_SEC = 2


async def get_gpu_stats() -> dict | None:
    """คืน dict GPU utilization/VRAM/อุณหภูมิจาก nvidia-smi หรือ None ถ้าไม่มี GPU/nvidia-smi
    (ใช้ asyncio.create_subprocess_exec ไม่ใช่ subprocess.run — กัน block event loop)"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_NVIDIA_SMI_TIMEOUT_SEC)
    except (FileNotFoundError, OSError, asyncio.TimeoutError):
        return None
    if proc.returncode != 0 or not stdout:
        return None
    try:
        line = stdout.decode().strip().splitlines()[0]
        util, mem_used, mem_total, temp = (p.strip() for p in line.split(","))
        return {
            "utilization_pct": float(util),
            "vram_used_mb": float(mem_used),
            "vram_total_mb": float(mem_total),
            "temperature_c": float(temp),
        }
    except (ValueError, IndexError):
        return None


async def get_ollama_models() -> list | None:
    """คืนรายชื่อโมเดลที่โหลดอยู่ใน VRAM ตอนนี้จาก Ollama /api/ps (ตัวชี้วัด model swap
    ตรงๆ) หรือ None ถ้า Ollama ไม่ได้เปิดอยู่/ไม่ตอบภายใน timeout สั้นๆ"""
    from ollama_client import OLLAMA_URL
    ps_url = OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/ps"
    try:
        timeout = ClientTimeout(total=_OLLAMA_PS_TIMEOUT_SEC)
        async with ClientSession(timeout=timeout) as s:
            async with s.get(ps_url) as r:
                if r.status != 200:
                    return None
                data = await r.json()
    except Exception:
        return None
    models = data.get("models") or []
    return [
        {"name": m.get("name"), "size_vram_mb": (m.get("size_vram") or 0) / 1024 / 1024}
        for m in models
    ]


def get_system_stats() -> dict:
    """CPU/RAM/disk ผ่าน psutil — cpu_percent(interval=None) คืนค่าตั้งแต่ call ก่อนหน้าทันที
    (ไม่ใช่ interval=1 ที่จะ block event loop 1 วิเต็มๆ — กับดักที่คนพลาดบ่อย)"""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.getcwd())
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_mb": vm.used / 1024 / 1024,
        "ram_total_mb": vm.total / 1024 / 1024,
        "disk_used_gb": disk.used / 1024 / 1024 / 1024,
        "disk_total_gb": disk.total / 1024 / 1024 / 1024,
    }


async def build_stats_payload(get_bot_status, start_time: float) -> dict:
    gpu, ollama_models = await asyncio.gather(get_gpu_stats(), get_ollama_models())
    return {
        "uptime_sec": time.monotonic() - start_time,
        "bot": get_bot_status(),
        "system": get_system_stats(),
        "gpu": gpu,
        "ollama_models": ollama_models,
        "latency_recent": stats.get_recent(50),
        "latency_summary": stats.get_summary(),
    }


class MonitorServer:
    """เริ่ม/หยุดเว็บเซิร์ฟเวอร์เฝ้าดูสถานะ — เรียก start() ใน on_ready (หลัง idempotency guard),
    stop() ใน RosteClient.close() ก่อน super().close()

    get_bot_status: callback ไม่รับ argument คืน dict สถานะภายในบอท (worker alive ไหม, bg queue
    ค้างกี่งาน, กำลังพูด/พิมพ์อยู่ไหม ฯลฯ) — ต้องคืนแค่ตัวเลข/สถานะ ห้ามมีเนื้อหาข้อความ/user id"""

    def __init__(self, get_bot_status, host: str = "127.0.0.1", port: int = 8765):
        self._get_bot_status = get_bot_status
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self._start_time = time.monotonic()

    async def _handle_stats_json(self, request: web.Request) -> web.Response:
        payload = await build_stats_payload(self._get_bot_status, self._start_time)
        return web.json_response(payload)

    async def start(self) -> None:
        if self._port == 0:
            logger.info("📈 monitor ปิดอยู่ (MONITOR_PORT=0)")
            return
        app = web.Application()
        app.router.add_get("/stats.json", self._handle_stats_json)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(f"📈 monitor เปิดที่ http://{self._host}:{self._port}/stats.json")

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
