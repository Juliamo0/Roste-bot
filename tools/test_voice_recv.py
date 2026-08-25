r"""
test_voice_recv.py — ทดสอบว่าบอทรับเสียงจาก Discord voice channel ได้จริงไหม

ทำไมต้องเทสแยกก่อนต่อเข้า bot.py: discord-ext-voice-recv ที่ติดตั้งไว้เป็น branch
dave-decrypt-receive ของ PR #62 (ยังไม่ merge เข้า main) ซึ่งแพตช์การถอดรหัส DAVE
(E2EE ที่ Discord บังคับตั้งแต่ มี.ค. 2026) — ยังไม่มีใครยืนยันว่าใช้ได้จริง และ
issue #53 ของ repo ต้นทางรายงานว่าใช้กับ discord.py 2.7.1 แล้วได้เสียงเพี้ยนเป็น
gibberish สคริปต์นี้จึงตอบคำถามเดียว: PCM ที่ได้เป็นเสียงคนจริง หรือขยะ

รันด้วย: venv\Scripts\python.exe tools\test_voice_recv.py [ชื่อห้อง]
  ไม่ใส่ชื่อห้อง = เข้าห้องแรกที่เจอคนอยู่
  บอทจะเข้าห้อง ฟัง LISTEN_SEC วินาที แล้วรายงาน + เซฟ wav ให้ฟังเอง

อ่านผลยังไง:
  * ไม่มี packet เลย    → DAVE ถอดไม่ได้/ไม่ได้ subscribe (ดู stderr)
  * มี packet แต่ RMS ~0 → ถอดรหัสได้แต่เป็นความเงียบ (อาจไม่มีใครพูด — ลองพูดดู)
  * RMS สูงแต่ฟังเป็นซ่า → gibberish ตาม issue #53 = DAVE patch ใช้ไม่ได้
  * ฟัง wav แล้วได้ยินเสียงตัวเอง → ผ่าน ไปต่อได้
"""
import asyncio
import audioop
import os
import sys
import time
import wave
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)          # ให้ load_dotenv เจอ .env

import discord
from discord.ext import voice_recv
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "")

LISTEN_SEC = 25
OUT_DIR = BOT_DIR / "f5_out" / "voice_recv_test"

# ฟอร์แมตที่ voice_recv ส่งมา (48kHz stereo s16) — ค่าเดียวกับ stt_listener
RATE, CHANNELS, WIDTH = 48000, 2, 2


class ProbeSink(voice_recv.AudioSink):
    """เก็บ PCM ต่อคน + สถิติ RMS — ไม่ทำอย่างอื่น เพื่อให้เห็นชัดว่าได้ข้อมูลอะไรมา"""

    def __init__(self):
        super().__init__()
        self.pcm = defaultdict(bytearray)
        self.packets = defaultdict(int)
        self.rms_max = defaultdict(int)
        self.first_packet_at = None

    def wants_opus(self) -> bool:
        return False        # ขอ PCM ที่ถอดแล้ว — ถ้า DAVE พัง จะพังตรงนี้

    def write(self, user, data: voice_recv.VoiceData) -> None:
        try:
            if user is None or not data.pcm:
                return
            if self.first_packet_at is None:
                self.first_packet_at = time.monotonic()
            name = getattr(user, "display_name", str(user))
            self.pcm[name] += data.pcm
            self.packets[name] += 1
            self.rms_max[name] = max(self.rms_max[name], audioop.rms(data.pcm, WIDTH))
        except Exception as e:
            print(f"  [!] write error: {type(e).__name__}: {e}")

    def cleanup(self) -> None:
        pass


class Probe(discord.Client):
    def __init__(self, target: str | None):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.target = target
        self.sink = ProbeSink()

    async def on_ready(self):
        print(f"ล็อกอิน: {self.user}")
        channel = self._pick_channel()
        if channel is None:
            print("[!] ไม่เจอห้องที่มีคนอยู่ — เข้าห้อง voice ก่อนแล้วรันใหม่")
            await self.close()
            return

        print(f"เข้าห้อง {channel.name!r} (guild {channel.guild.name!r})")
        try:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
        except Exception as e:
            print(f"[!] connect ล้มเหลว: {type(e).__name__}: {e}")
            await self.close()
            return

        print(f"ต่อแล้ว — client type = {type(vc).__name__}")
        vc.listen(self.sink)
        print(f"\n>>> พูดใส่ไมค์ได้เลย ฟัง {LISTEN_SEC} วินาที <<<\n")

        for i in range(LISTEN_SEC, 0, -5):
            await asyncio.sleep(5)
            total = sum(self.sink.packets.values())
            print(f"  เหลือ {i - 5}s — packet สะสม {total}")

        vc.stop_listening()
        await vc.disconnect()
        self._report()
        await self.close()

    def _pick_channel(self):
        for guild in self.guilds:
            for ch in guild.voice_channels:
                humans = [m for m in ch.members if not m.bot]
                if not humans:
                    continue
                if self.target is None or self.target.lower() in ch.name.lower():
                    return ch
        return None

    def _report(self):
        print("\n" + "=" * 60)
        print("  ผลการทดสอบ")
        print("=" * 60)
        if not self.sink.packets:
            print("  ❌ ไม่ได้รับ packet เลย")
            print("     → DAVE ถอดรหัสไม่ได้ หรือไม่มีใครพูดตอนที่ฟัง")
            print("     → ดู stderr ข้างบนว่ามี error เรื่อง decrypt ไหม")
            return

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for name, pcm in self.sink.pcm.items():
            dur = len(pcm) / (RATE * CHANNELS * WIDTH)
            rms = audioop.rms(bytes(pcm), WIDTH) if pcm else 0
            path = OUT_DIR / f"{name}.wav".replace("/", "_")
            with wave.open(str(path), "wb") as w:
                w.setnchannels(CHANNELS)
                w.setsampwidth(WIDTH)
                w.setframerate(RATE)
                w.writeframes(bytes(pcm))
            print(f"  {name}: {self.sink.packets[name]} packets, {dur:.1f}s, "
                  f"RMS เฉลี่ย {rms} (สูงสุด {self.sink.rms_max[name]})")
            print(f"    → {path}")

        print("\n  ขั้นต่อไป: เปิดไฟล์ wav ข้างบนฟัง")
        print("    ได้ยินเสียงตัวเองชัด = DAVE patch ใช้ได้ ✅")
        print("    เป็นเสียงซ่า/ขยะ      = gibberish ตาม issue #53 ❌")


def main() -> int:
    if not TOKEN:
        print("[!] ไม่พบ DISCORD_TOKEN ใน .env")
        return 1
    target = sys.argv[1] if len(sys.argv) > 1 else None
    Probe(target).run(TOKEN, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
