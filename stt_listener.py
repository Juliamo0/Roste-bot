"""
stt_listener.py — ฟังเสียงใน voice channel → ตัดเป็นประโยค → ถอดเสียงด้วย SttWorker

AudioSink ของ discord.ext.voice_recv ที่รับ PCM จาก Discord มาเก็บแยกตามผู้พูด (keyed ด้วย
user id) แล้วตัดเป็น "ประโยค" (utterance) ด้วยการจับเวลาเงียบบนเนื้อเสียงจริง:

  • ผู้พูดคนหนึ่งไม่มีเสียงดัง (chunk ที่ RMS ต่ำกว่า _SILENCE_RMS) ติดต่อกันเกิน SILENCE_MS
    → ถือว่าจบประโยค ส่ง buffer เข้าคิวถอดเสียง
  • สั้นกว่า MIN_UTTERANCE_MS → ทิ้ง (เสียงไอ/คลิกไมค์/เก้าอี้ ไม่ใช่คำพูด)
  • ยาวถึง MAX_UTTERANCE_MS กลางประโยค → ตัดส่งถอดเสียงทันที (ไม่รอเงียบ) เพราะ
    typhoon-asr-realtime ถูกเทรนด้วย clip ยาวสุด 30s (max_duration ใน NeMo config) และ
    เป็นการจำกัด buffer ต่อคนไม่ให้โตไม่อั้นถ้ามีใครพูดไม่หยุด — ตัดดีกว่าทิ้งทั้งก้อน
    เพราะทิ้งทั้งก้อน = คนพูดยาวไม่ได้ถอดเสียงอะไรเลย + หน่วยความจำยังโตต่อจนกว่าจะเงียบ

การตัดประโยคมี 2 กลยุทธ์ เลือกด้วย TURN_STRATEGY (แก้ค่าเดียว ไม่ต้องแตะโค้ดส่วนอื่น):
  • "semantic" (default) — เงียบครบ SILENCE_MS ยังไม่ยอมเรียก callback แต่ถอดเสียงก่อน
    แล้วถามว่า "ข้อความจบหรือยัง" ด้วย _is_utterance_finished(): TURN_LLM=True (default)
    ให้โมเดลเล็ก (OLLAMA_EXTRACT_MODEL = qwen3:4b) ตัดสิน โดยบังคับ format JSON-schema
    (ทำไมใช้โมเดลนี้/ทำไมต้องบังคับ format — ตัวเลขวัดจริงอยู่ใน comment เหนือ _TURN_FEWSHOT)
    ถ้าถาม LLM ล้มเหลวกรณีใดก็ตาม (Ollama ล่ม/timeout/JSON เพี้ยน) fallback ไป
    looks_unfinished() heuristic คำท้ายประโยคเดิม (พอร์ตจาก tools/bench_turn_taking.py —
    ชนะ bench 13/14 กับ 7/14 ของกฎเงียบล้วน) ถ้าข้อความดูยังไม่จบ (ลงท้ายคำเชื่อม/กำลังไล่
    list) จะ "ถือ" ไว้ ถ้าคนพูดพูดต่อภายใน SEMANTIC_IDLE_GIVEUP_MS ก้อนถัดมาจะถูกถอดเสียง
    แล้วแปะต่อท้ายและเช็คซ้ำ จนกว่าข้อความจะจบ หรือเงียบเกิน deadline จึงยอมปล่อยก้อนที่ถือ
    อยู่ — กลไกถือ/แปะ/ตัดสินใจจบอยู่ฝั่ง transcriber thread เท่านั้น เพราะต้องมี "ข้อความ"
    ซึ่งมีหลังถอดเสียง และการถอดเสียงห้ามไปอยู่บนเส้นทางอื่น (ดู Threading ด้านล่าง)
  • "silence" — กฎเดิม เงียบครบ SILENCE_MS ตัด ถอดเสียง แล้วเรียก callback ทันที

ก่อนข้อความใดๆ ถึง callback จะผ่าน _fix_bot_name() — ASR เขียนชื่อบอท "รอสเต้" เพี้ยนเป็น
"ลอตเต้"/"รอสเตย์" ฯลฯ (เจอจริงทั้งใน voice channel และใน tools/turn_bench_result.json)
ชื่อเป็น closed set และเป็นวิธีที่บอทรู้ว่ากำลังถูกพูดถึง จึงแก้ด้วย post-processing แทน
การเทรนโมเดลใหม่ (ขอบเขตที่ตั้งใจไม่แตะ — ดูที่ _NAME_FIXES)

ทำไมไม่ใช้ event voice_member_speaking_start/stop ที่ voice_recv มีให้ — stop ถูกยิงโดย
SpeakingTimer หลังไม่ได้รับ packet แค่ 200ms (ค่า fix ใน reader.py) ซึ่งสั้นกว่าช่วงเ้นวรรค
ธรรมดาของคนพูด ใช้ตัดประโยคแล้วจะหักกลางคำ แถม event นี้ไม่ยิงเลยถ้าหา member จาก ssrc
ไม่เจอใน cache จึงวัดความเงียบจาก PCM เองแทน (แม่นกว่า และไม่พึ่ง guild member cache)

PCM ที่ได้ต้องแปลงก่อนเข้าโมเดล — Discord เป็น 48kHz stereo 16-bit (Decoder.SAMPLING_RATE/
CHANNELS/SAMPLE_SIZE ของ discord.opus) แต่ typhoon-asr-realtime ต้องการ 16kHz mono
(m._cfg.sample_rate = 16000 ตรวจจาก config จริงของโมเดล) จึงใช้ stdlib audioop แปลงเป็น
wav 16kHz mono s16 ลง temp file ก่อนส่งให้ SttWorker (แพ็กเกจ typhoon_asr จะ resample
ให้เองถ้าไฟล์ไม่ตรง แต่แปลงเองตั้งแต่ต้นได้ไฟล์เล็กกว่าและ deterministic กว่า)

Threading (เหตุผลสำคัญ — write() ถูกเรียกจาก packet-router thread ของ voice_recv ไม่ใช่
event loop ของบอท):
  • write()         → แค่ append buffer + วัด RMS ด้วย audioop (C-speed) ไม่มี IO หนัก
  • silence-checker → thread แยก ตรวจทุก ~100ms ว่าใครเงียบเกิน SILENCE_MS บ้าง
                      (semantic mode: แค่เปลี่ยน buffer เป็น "ถือรอ" + บังคับปล่อยเมื่อ
                       หมดเวลา — ไม่ตัดสินจากเนื้อหา เพราะตอนนี้ยังไม่มีข้อความ)
  • transcriber     → thread แยก ดึงจากคิวมาเขียน wav + เรียก SttWorker.transcribe()
                      (ขั้นตอนนี้กินเวลาหลักสิบ ms ขึ้นไป ห้ามอยู่บนเส้นทางรับ packet เพราะ
                       Discord ส่ง packet มาเรื่อยๆ ไม่รอใคร — ค้างแล้ว jitter buffer ล้น)
                      semantic mode ยังเป็นคนถือ/แปะ/ตัดสินใจจบประโยคด้วย เพราะเป็น
                      thread เดียวที่มีข้อความให้ดู (ดู self._held) — การถาม LLM ว่า
                      "จบหรือยัง" จึงเป็น HTTP แบบ *sync* (requests) บน thread นี้ตั้งใจ:
                      เป็น dedicated worker ที่งานเดียวคืองานช้า ไม่มีอะไรอื่นรอมัน และ
                      ห้าม schedule ขึ้น event loop แน่ๆ เพราะจะไป block loop ของบอท
                      ความเสี่ยงเดียวคือ "ค้างนาน" จึงผูก timeout ไว้เสมอ (TURN_LLM_TIMEOUT_SEC)
  • callback        → async callback schedule ด้วย asyncio.run_coroutine_threadsafe /
                      sync callback ด้วย loop.call_soon_threadsafe — เลือกให้ callback
                      รันบน event loop ของบอทเสมอทั้งสองแบบ เพราะ callback มักต้องแตะ
                      discord.py (ส่ง message, เรียก LLM ฯลฯ) ซึ่งไม่ thread-safe ถ้ารัน
                      บน thread ของ sink ตรงๆ

⚠️ voice client ต้องเป็น VoiceRecvClient — bot.py ปัจจุบันเรียก channel.connect() ธรรมดาซึ่ง
   ได้ VoiceClient ที่ *ไม่มี* listen(sink) ต้องเปลี่ยนเป็น
       vc = await channel.connect(cls=discord.ext.voice_recv.VoiceRecvClient)
   ก่อน ไม่งั้น start_listening() จะ raise TypeError ทันที

การใช้:
    import discord.ext.voice_recv as voice_recv
    from stt_client import SttWorker
    from stt_listener import start_listening

    stt = SttWorker(); stt.start()

    async def on_utterance(user, text):
        await channel.send(f"{user.display_name}: {text}")

    vc = await channel.connect(cls=voice_recv.VoiceRecvClient)     # ← cls ต้องระบุ
    listener = await start_listening(vc, stt, on_utterance)
    ...
    listener.cleanup()      # เรียกก่อน vc.disconnect()
"""

import asyncio
import audioop
import concurrent.futures
import inspect
import json
import logging
import os
import queue
import re
import tempfile
import threading
import time
import wave

import requests

from discord.ext import voice_recv
from discord.ext.voice_recv import VoiceRecvClient

# ค่า Ollama — ตาม pattern ของ chat.py/ollama_client.py: อ่านจาก config แล้วมี fallback
# ตอน import config ไม่ได้ (tests/conftest.py inject config ปลอมที่ไม่มีค่าเหล่านี้)
try:
    from config import (OLLAMA_URL,
                        OLLAMA_EXTRACT_MODEL as _TURN_LLM_MODEL,
                        EXTRACT_FORMAT_JSON as _TURN_FORMAT_JSON)
except ImportError:
    OLLAMA_URL = "http://localhost:11434/api/chat"
    _TURN_LLM_MODEL = "qwen3:4b"
    _TURN_FORMAT_JSON = True

# ไม่ต้อง config handler เอง — bot.py ตั้ง root logger ไว้แล้ว (rotating file + console)
logger = logging.getLogger("roste.stt_listener")

# ── constants ──────────────────────────────────────────────────────────────────
# ชื่อค่ามาจากโจทย์ แต่ตัวเลขเลือกจากพฤติกรรมคนพูดจริง:
#   SILENce_MS 800 — ช่วงเ้นวรรคปกติของคนพูด ~200-500ms คิดเผื่อ network jitter +
#                  ความละเอียดของ checker thread (100ms) แล้ว 800 ไม่หักกลางคำแต่ก็ไม่
#                  หลงใหลให้รอนานเกิน ถ้าอยากตอบเร็วขึ้นลดได้แต่ <500 เริ่มหักประโยคบ่อย
SILENCE_MS       = 800
MIN_UTTERANCE_MS = 400    # ต่ำกว่านี้คือเสียงไอ/คลิก/กระแทกไมค์ — ASR กลืนเปล่าเป็นขยะ
MAX_UTTERANCE_SEC = 30    # typhoon-asr-realtime เทรนด้วย clip ≤ 30s + bound หน่วยความจำ
MAX_UTTERANCE_MS = MAX_UTTERANCE_SEC * 1000

# กลยุทธ์ตัดประโยค — "semantic" (default): ตัดที่ SILENCE_MS แล้วยังไม่ปล่อย ให้ดูเนื้อหา
# ข้อความต่อ (ถือ/แปะ/ปล่อย ตาม _is_utterance_finished) "silence" = กฎเดิม (ตัดที่
# SILENCE_MS ทันที) — สลับกลับได้โดยแก้ค่าเดียว ไม่ต้องแตะโค้ด
TURN_STRATEGY = "semantic"

# ── สวิตช์ตัดสิน "จบประโยคหรือยัง" ด้วย LLM ────────────────────────────────────
# True (default) = ถามโมเดลเล็กก่อนเสมอ, False = ใช้ลิสต์คำ looks_unfinished() ล้วน
# (พฤติกรรมเท่าเดิมทุกอย่าง) — ปิดได้โดยไม่ต้องแกะโค้ด ในจิตวิญญาณเดียวกับ TURN_STRATEGY
#
# ทำไมใช้ OLLAMA_EXTRACT_MODEL (qwen3:4b) ไม่ใช่โมเดลหลัก (qwen3:8b) — วัดแล้ว ไม่ใช่เดา:
#   • คุณภาพ (bench 30 เคส): qwen3:4b 77% / F1(not-done) 0.811 · qwen3:1.7b 60% /
#     scb10x/typhoon2-1b 50% และ F1 0.000 (ตอบ "จบ" ทุกเคส — 1B instruct ธรรมดาทำงานนี้
#     ไม่ได้เลย paper Thai-EOT arXiv 2510.04016 ได้ F1 0.881 ต่อเมื่อ fine-tune ซึ่งไม่มี weights)
#   • latency ใต้ contention: qwen3:8b p95 119ms ปกติ แต่ "ตอนบอทกำลัง generate reply"
#     พุ่งเป็น 5375ms (45 เท่า) เพราะ EOT call ต้องคิวหลังงานแชตที่ใช้โมเดลเดียวกัน —
#     แถมเกิดตอนที่คนมีโอกาสพูดต่อมากที่สุด qwen3:4b เป็นโมเดลละกัน Ollama serve
#     concurrent กันได้ p95 คงที่ที่ 410ms — นี่ไม่ใช่ tradeoff คุณภาพ/ขนาด แต่เป็น
#     การแชร์ resource ใน server เดียว อย่า "simplify" กลับไปใช้โมเดลหลัก
TURN_LLM = True

# timeout ของ EOT call — จุดขายคือ bounded latency: Ollama ค้างต้องไม่ลาก listener ไปค้างด้วย
#
# ⚠️ 2.0s (ค่าแรกที่ตั้งจาก p95 410ms ใต้ contention) พังจริงตอนทดสอบ — คืน None ทุกครั้ง
# เพราะตัวเลข p95 นั้นวัดตอนโมเดล *อยู่ใน VRAM แล้ว* แต่ EOT call มักเป็นคนปลุกโมเดลเอง:
# บอทเงียบไปพักหนึ่ง Ollama unload โมเดลออก (keep_alive default 5 นาที) พอมีคนพูดขึ้นมา
# call แรกต้องรอโหลดกลับ ~3-5s (วัดได้ 5020ms ตอน bench 30 เคส) ทุกครั้งจึง timeout →
# fallback ลิสต์คำถาวรโดยไม่มีใครรู้ (มันคืน None เงียบๆ ตามสัญญา)
#
# 6.0s ครอบ cold start ที่วัดได้จริง โดย worst case ยังถูกจำกัดจากอีกทาง: ประโยคที่ถือรอมี
# SEMANTIC_IDLE_GIVEUP_MS=1500ms คอยปล่อยอยู่แล้ว ผู้ใช้จึงไม่เคยรอเกินนั้นไม่ว่า Ollama
# จะช้าแค่ไหน — timeout ตัวนี้กันแค่ thread ค้างถาวร ไม่ใช่ตัวกำหนด latency ที่คนรู้สึก
TURN_LLM_TIMEOUT_SEC = 6.0

# รอข้อความต่อได้นานสุด "หลังจากเงียบ" เท่านี้ แล้วค่อยยอมปล่อยก้อนที่ถือไว้ — ค่าเดียวกับ
# bench (ตั้งระหว่าง 800 กับ threshold ของกลยุทธ์ B เพื่อให้มี margin จับช่วงพูดต่อ แต่
# ไม่แพงกว่า B เรื่อง latency)
SEMANTIC_IDLE_GIVEUP_MS = 1500

_CHECK_INTERVAL_SEC = 0.1   # ความละเอียดของ silence-checker (latency เพิ่มไม่เกินค่านี้)
_QUEUE_SIZE         = 64    # คิวงานถอดเสียง — เกินนี้แปลว่า ASR ตามไม่ทัน ทิ้งก้อนใหม่ดีกว่าค้าง

# เกณฑ์ "มีเสียง" จาก RMS (0-32767) — ตั้งต่ำไว้จงใจ เพราะหน้าที่มีแค่กรอง buffer ที่เงียบ
# สนิท (comfort noise ของ Discord) ไม่ใช่ gate เสียงดัง คนพูดเบาๆ ต้องผ่าน
# (false positive = เสียยิง ASR เปล่าครั้งนึง ได้ text ว่างก็จบ แพ้น้อยกว่า false negative)
_SILENCE_RMS = 150

# ── ฟอร์แมตเสียง (ตรวจจาก discord.opus.Decoder จริง ไม่ใช่สันนิษฐาน) ────────────
_DISCORD_RATE     = 48000   # Decoder.SAMPLING_RATE
_DISCORD_CHANNELS = 2       # Decoder.CHANNELS
_SAMPLE_WIDTH     = 2       # s16le → Decoder.SAMPLE_SIZE // CHANNELS
_TARGET_RATE      = 16000   # m._cfg.sample_rate ของ scb10x/typhoon-asr-realtime
_BYTES_PER_MS     = _DISCORD_RATE * _DISCORD_CHANNELS * _SAMPLE_WIDTH // 1000   # = 192


# ── heuristic "ข้อความจบหรือยัง" — fallback ของ TURN_LLM + ตัวหลักเมื่อ TURN_LLM=False ──
# พอร์ตมาจาก tools/bench_turn_taking.py (ชุดที่ชนะ bench) แล้วปรับจากการวัดกับ transcript
# ASR จริง 34 ก้อนใน tools/turn_bench_result.json:
#   เจอ marker ฝั่งรอ (_NOT_DONE, ท้าย) : 3   → ถือต่อ
#   เจอ marker ฝั่งปล่อย (ท้าย)         : 24  → ปล่อย
#   ไม่เจออะไรเลย ตก default            : 7   → ถือเ้อจนครบ SEMANTIC_IDLE_GIVEUP_MS
# ใน 7 ก้อนที่ตก default มี 2 ก้อนที่ "จบประโยคชัดเจน" แต่ถูกมองว่ายังไม่จบ:
#   'รอสเต้คิดว่าอันไหนดีกว่ากัน' / 'ตอนนี้กี่โมงแล้วรอสเต้'
# สาเหตุ: คำถาม ('อันไหน', 'กี่โมง') อยู่ *กลาง* ประโยค หน้าตัด 15 ตัวอักษรท้ายมองไม่เห็น
# จึงแยกลิสต์คำถาม (_QUESTION — สแกน *ทั้งประโยค*) ออกจากคำลงท้าย (_DONE — ท้ายเท่านั้น):
#   • คำถามสแกนทั้งประโยคได้ เพราะธรรมชาติของมันคือ "บอกชนิดประโยค" — ประโยคที่มีคำถาม
#     กลางๆ ก็ยังเป็นคำถามและผู้พูดกำลังรอคำตอบ ('รอสเต้คิดว่าอันไหนดีกว่ากัน')
#   • คำเชื่อม/คำลงท้ายห้ามสแกนทั้งประโยค เพราะกลางประโยคไม่ได้แปลว่าอะไร: 'คือ'
#     โผล่กลางประโยคได้ตลอด ('คือเมื่อวานผมไป...') 'นะ' ก็ฝังกลางคำได้
#     ('ช่วยสองอย่างนะอย่างแรกคือ...') — ดูทั้งประโยคจะจับผิดเพียบ จึงคงเช็คเฉพาะท้าย
# ⚠️ นี่คือตัวแทน semantic-VAD ด้วยลิสต์คำล้วนๆ คุณภาพ = คุณภาพลิสต์ (ดู docstring ของ bench)
# แก้ลิสต์ = เปลี่ยนพฤติกรรมที่วัดผลไว้แล้ว — ต้องรัน tools/bench_turn_taking.py ซ้ำ
_NOT_DONE = (
    # คำเชื่อม/บอกว่ากำลังจะอธิบายต่อ — ค้างไว้รอ
    "แล้วก็", "ก็คือ", "คือว่า", "คือ",
    "ประมาณว่า", "ประมาณ",
    "อย่างแรก", "อย่างที่สอง", "อย่างที่สาม",        # กำลังไล่ list — ยังไม่ครบ
    "รวมถึง", "รวมทั้ง", "แถม", "บวกกับ",
    "และ", "หรือ", "กับ", "แต่", "เพราะ", "เพราะว่า",
    "เนื่องจาก", "ถ้า", "ถ้าหาก", "เมื่อ", "ตอนที่",
    "ที่", "ซึ่ง", "ดังนั้น", "ฉะนั้น", "ส่วน", "สำหรับ",
    "เช่น", "ได้แก่", "เหมือน", "เพื่อ", "ก่อนที่", "หลังจาก",
)
_QUESTION = (
    # คำถาม — สแกนทั้งประโยค (เหตุผลใน comment เหนือลิสต์): มีคำถาม = ผู้พูดรอคำตอบ =
    # ประโยคจบแล้ว ไม่ว่าคำถามจะอยู่ต้น/กลาง/ท้าย
    "ไหม", "มั้ย", "มั้ง", "หรอ", "ปะ", "หรือเปล่า", "เปล่า", "ใช่ไหม", "ใช่มั้ย",
    "ยังไง", "อย่างไง", "เท่าไหร่", "เท่าไหน", "กี่โมง", "กี่", "อะไร", "ใคร",
    "ตรงไหน", "ที่ไหน", "เมื่อไหร่", "เมื่อไร",
    "อันไหน", "ทำไม",   # เพิ่มจากการวัดจริง — 'อันไหนดีกว่ากัน' ตก default เพราะมองแค่ท้าย
)
_DONE = (
    # คำลงท้ายของคนไทยที่ปิดประโยค — ขอ/เล่า/เห็นด้วยจบวง (เช็คเฉพาะท้าย เพราะ
    # กลางประโยคไม่มีความหมายว่าจบ — ดู comment เหนือลิสต์)
    "หน่อย", "ด้วย", "สิ", "ซิ", "จ้ะ", "จ๊ะ", "ครับ", "ค่ะ", "นะ",
    "เลย", "จัง", "มาก", "ล่ะ", "ละ", "แน่ะ",
)
# "แล้ว" เดี่ยวๆ ไม่อยู่ในลิสต์ไหนตั้งใจ — กำกวมทั้งสองทาง ("ทำเสร็จแล้ว" = จบ vs
# "...แล้วก็" = ค้าง) ปล่อยให้ตกไปที่ default ด้านล่าง ดีกว่าเดาผิดเป็นระบบ
_MARKER_WINDOW_CHARS = 15   # ครอบคลุม marker ยาวสุด ("อย่างที่สองคือ" ฯลฯ) + vocative "รอสเต้" ท้ายประโยค
_DEFAULT_UNFINISHED = True  # ไม่เจอ marker ทั้งสองฝั่ง → เชื่อว่า "ยังไม่จบ" (bench เกิดจากปัญหาตัดเร็วเกิน
                            # จึง bias ฝั่งรอ — พลิกเป็น False แล้วรัน bench ซ้ำเป็น experiment ได้)


def _norm(text: str) -> str:
    """ตัดช่องว่าง/วรรคตอน/ตัวพิมพ์ก่อนดู marker — ASR ใส่ไม่เหมือนกันไม่ควรเปลี่ยนคำตัดสิน"""
    text = text.lower().strip()
    text = re.sub(r"[.,!?;:\"'()\[\]{}…ๆฯ]", "", text)
    return re.sub(r"\s+", "", text)


def looks_unfinished(text: str) -> bool:
    """ข้อความที่ถอดได้ดูเหมือน "ยังพูดไม่จบ" หรือเปล่า — heuristic คำ (fallback ของ
    _is_utterance_finished — ตัวแทน semantic-VAD ด้วยลิสต์คำ ดู comment เหนือลิสต์)

    ลำดับความสำคัญ (ตั้งใจ):
      1. _NOT_DONE ที่ *ท้าย*        → ยังไม่จบ  (คำเชื่อมท้ายชนะทุกอย่าง —
                                        'อันไหนดีกว่ากันแล้วก็' ยังไม่จบจริงๆ แม้มีคำถามกลางประโยค)
      2. _QUESTION ที่ *ทั้งประโยค*  → จบ (ถามแล้วต้องได้คำตอบ)
      3. _DONE ที่ *ท้าย*            → จบ (คำลงท้ายปิดประโยค)
      4. ไม่เจออะไรเลย               → default (bias ฝั่งรอ)
    """
    t = _norm(text)
    if not t:
        return False          # ก้อนว่าง = ไม่มีอะไรให้รอ ปล่อยไปเลย
    if t.endswith("?"):
        return False
    tail = t[-_MARKER_WINDOW_CHARS:]
    if any(m in tail for m in _NOT_DONE):
        return True
    if any(q in t for q in _QUESTION):    # ทั้งประโยค — คำถามกลางประโยคก็ยังบอกว่าเป็นคำถาม
        return False
    if any(m in tail for m in _DONE):
        return False
    return _DEFAULT_UNFINISHED


# ⚠️ failure mode ที่เจอจริงใน voice channel (ไม่ใช่แค่ใน bench): คนพูดถามว่า "ได้ยินไหม"
# แต่ ASR เขียน "ได้ยินไว้" — "ไหม" อยู่ใน _QUESTION, "ไว้" ไม่อยู่ ประโยคจึงโดนมองว่า
# "ยังไม่จบ" และค้างรอจนหมด SEMANTIC_IDLE_GIVEUP_MS แทนที่จะปล่อยทันที ASR พลาด
# particle ท้ายประโยคแบบนี้ได้เงียบๆ เสมอ (ไม่มี exception ให้จับ) — ใครจะปรับลิสต์คำ
# ต้องอ่าน transcript จริงประกอบ อย่าเชื่อว่าเสียงที่ได้ยิน = ตัวอักษรที่โมเดลเขียน
# (ยังไม่แก้ที่นี่ — map "ไว้→ไหม" ทั่วไปอันตรายเกิน เพราะ "ไว้" เป็นคำไทยจริง)


# ── ตัดสิน "จบประโยคหรือยัง" ด้วย LLM (TURN_LLM=True) ──────────────────────────
#
# ทำไมต้องมี LLM แทนที่ลิสต์คำ: ไทยไม่มีช่องว่างคั่นคำและไม่มีเครื่องหมายจบประโยค
# tail-matching จึงมองไม่เห็นโครงสร้างประโยค วัดกับเคสรูปแบบจริงแล้วลิสต์คำพลาด
# กลับด้านพอดีในเคสที่สำคัญ:
#   "รอสเต้คิดว่าอันไหนดีกว่ากัน ระหว่างสีเขียว"        → บอก "จบ" (ผิด — กำลังไล่ตัวเลือก)
#   "รอสเต้คิดว่าอันไหนดีกว่ากัน ระหว่างสีเขียว กับสีฟ้า" → บอก "ยังไม่จบ" (ผิด — พูดครบแล้ว)
# ("สีเขียว" ไม่ match อะไรจึงตก default, "กับสีฟ้า" ลงท้าย "กับ" ซึ่งอยู่ใน _NOT_DONE)
#
# prompt นี้คือตัวที่วัดได้ qwen3:4b 77% / F1(not-done) 0.811 (bench 30 เคส) — ตัวเลขใน
# comment เหนือ TURN_LLM อ้างอิง prompt ตัวนี้ แก้ example = เปลี่ยนพฤติกรรมที่วัดไว้
#
# ⚠️ ทิศทาง error ที่ปลอดภัย: qwen3:4b ผิด 7/30 เคส *ทั้งหมด* ฝั่ง "บอกยังไม่จบ" กับ
# ประโยคที่จบจริง (precision 0.68 / recall 1.00 บน not-done) — ต้นทุนที่ user เห็นคือ
# "รอเพิ่ม ~1.5s บ้าง" ไม่ใช่ "โดนตัดกลางคำคิด" ตัวหลังแย่กว่ามาก ถ้าจะเติม example
# เพิ่ม (ข้างล่างเติม 3 เคสที่ผิด) อย่าเติมจนเริ่มตัดประโยคค้างจริง — recall 1.00
# ของฝั่ง not-done คือสมบัติที่ต้องรักษา
_TURN_FEWSHOT = (
    "จำแนกว่าข้อความภาษาไทยต่อไปนี้ ผู้พูดพูด \"จบ\" แล้วหรือ \"ยังไม่จบ\" "
    "(ยังไม่จบ = กำลังจะพูดต่อ เช่น ค้างกลางประโยค กำลังไล่รายการ หรือรอข้อมูลเพิ่ม)\n"
    "ตอบเป็น JSON รูปแบบ {\"done\": true} หรือ {\"done\": false} เท่านั้น\n\n"
    'ข้อความ: ช่วยเปิดเพลงให้หน่อยสิ\n{"done": true}\n\n'
    'ข้อความ: พรุ่งนี้ฝนจะตกไหม\n{"done": true}\n\n'
    'ข้อความ: เมื่อวานผมไปเที่ยวมาแล้วก็\n{"done": false}\n\n'
    'ข้อความ: ก็คือเมื่อวานผมไปดูโน้ตบุ๊กมาสองรุ่น\n{"done": false}\n\n'
    'ข้อความ: รอสเต้คิดว่าอันไหนดีกว่ากัน ระหว่างสีดำ\n{"done": false}\n\n'
    'ข้อความ: รอสเต้คิดว่าอันไหนดีกว่ากัน ระหว่างสีดำ กับสีแดง\n{"done": true}\n\n'
    'ข้อความ: ช่วยสองอย่างนะ อย่างแรกคือเปิดแอร์ห้องนอน\n{"done": false}\n\n'
    'ข้อความ: ตอนนี้กี่โมงแล้วรอสเต้\n{"done": true}\n\n'
    'ข้อความ: ประมาณว่า ระหว่างรุ่นเล็กกับรุ่นใหญ่ รอสเต้ว่าอันไหนคุ้มกว่า\n{"done": true}\n\n'
    # ── เคสเสริม 3 อันจาก 7 เคสที่ qwen3:4b ยังผิด (ทั้งหมดเป็นประโยคจบที่มันบอกไม่จบ) —
    # อย่าเติมต่อจน recall ฝั่ง not-done ต่ำกว่า 1.00 (ดู comment ⚠️ ด้านบน)
    'ข้อความ: พรุ่งนี้อากาศเป็นไง\n{"done": true}\n\n'
    'ข้อความ: พอดีจะไปเที่ยวทะเล รอสเต้แนะนำที่ไหนดี\n{"done": true}\n\n'
    'ข้อความ: รอสเต้ว่าอันไหนดี ระหว่างรุ่นเล็ก กับรุ่นใหญ่\n{"done": true}\n\n'
    "ข้อความ: "
)

# schema บังคับ {"done": boolean} — เทคนิคเดียวกับ chat.auto_remember/memory.EXTRACT_JSON_SCHEMA
# 🚨 ห้ามปล่อย format ว่างกับ qwen3:4b: มันไม่เคารพ think:False แล้วเขียน reasoning
# ลง content ~1,000 tokens = 13-30s/call (วัดจริง ดู config.EXTRACT_FORMAT_JSON) —
# บังคับ format แล้วเหลือระดับ ~200ms ซึ่งคือค่าที่ timeout ด้านบนตั้งรอไว้
_TURN_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {"done": {"type": "boolean"}},
    "required": ["done"],
}


# Session เดียวใช้ตลอดอายุโปรเซส — keep-alive ให้ TCP connection ค้างไว้ (ดูเหตุผล/ตัวเลข
# ที่จุดเรียกใน _ask_llm_finished) thread-safe พอสำหรับที่นี่เพราะมีแต่ transcriber thread
# เรียก และ requests.Session ปลอดภัยกับการใช้ข้าม thread แบบ request/response ธรรมดาอยู่แล้ว
_TURN_SESSION = requests.Session()


def _ask_llm_finished(text: str) -> bool | None:
    """ถามโมเดลเล็กว่า "ข้อความนี้พูดจบหรือยัง" — คืน True(จบ)/False(ยังไม่จบ)
    หรือ None ถ้าพลาดกรณีใดก็ตาม (Ollama ล่ม/timeout/JSON ผิดรูป) — caller ต้อง
    fallback ไปลิสต์คำทุกครั้งที่ได้ None ฟังก์ชันนี้ block ได้สูงสุด TURN_LLM_TIMEOUT_SEC
    (sync HTTP บน transcriber thread — เหตุผลที่ปลอดภัยดู docstring Threading)"""
    payload = {
        "model": _TURN_LLM_MODEL,
        "messages": [{"role": "user", "content": _TURN_FEWSHOT + text.strip()}],
        "stream": False, "think": False,
        "options": {"temperature": 0.0},   # งาน classification ต้อง deterministic ไม่ใช่งานแชต
    }
    if _TURN_FORMAT_JSON:
        payload["format"] = _TURN_FORMAT_SCHEMA
    try:
        # requests (pin ใน requirements.txt, websearch.py ใช้แบบเดียวกัน) ไม่ aiohttp —
        # เพราะจุดนี้อยู่บน plain thread ไม่ใช่ event loop ห้ามลาก async เข้ามา
        #
        # ⚠️ ต้องใช้ Session ไม่ใช่ requests.post() ตรงๆ — วัดจริงบนเครื่องนี้ (โมเดลอยู่ใน
        # VRAM แล้ว GPU ว่าง): requests.post() 2126ms · Session.post() 114ms · aiohttp 111ms
        # ช้ากว่า 19 เท่าเพราะเปิด TCP connection ใหม่ทุกครั้ง (overhead ของ Winsock ต่อ
        # localhost สูงผิดคาด) — bench เดิมวัดได้ 207ms เพราะใช้ aiohttp ที่ reuse ให้อยู่แล้ว
        # จึงมองไม่เห็นปัญหานี้ ห้ามเปลี่ยนกลับเป็น requests.post() เพื่อ "ความเรียบง่าย"
        r = _TURN_SESSION.post(OLLAMA_URL, json=payload, timeout=TURN_LLM_TIMEOUT_SEC)
        done = json.loads(r.json()["message"]["content"])["done"]
        return bool(done)
    except Exception as e:
        logger.debug(f"   [stt] ถาม LLM end-of-turn ล้มเหลว: {e}")
        return None


# ── แก้ชื่อบอทที่ ASR เขียนผิด (post-processing) ───────────────────────────────
_BOT_NAME = "รอสเต้"
_NAME_FIXES = {
    "ลอตเต้": _BOT_NAME,
    "ล็อตเต้": _BOT_NAME,
    "รอสเตย์": _BOT_NAME,   # เจอจริงใน tools/turn_bench_result.json
    "ลอสเต้": _BOT_NAME,
    "ล็อสเต้": _BOT_NAME,
    "รอสเต": _BOT_NAME,     # หล่นวรรณยุกต์ — ASR ไทยหล่นไม้ตรี/ไม้โทบนคำแปลกๆ บ่อย
    "ลอสเต": _BOT_NAME,
}
# ต้องมีตัวสะกดที่ "ถูกต้อง" อยู่ใน pattern ด้วย — ไม่งั้น variant สั้น "รอสเต" (จับหัว
# ของ "รอสเต้" ได้) จะกินคำที่สะกดถูกแล้วทิ้งวรรณยุกต์หลุดค้าง ("รอสเต"+"้") และต้องเรียง
# ยาว→สั้น เพื่อให้ alternation ที่ยาวกว่าจับก่อน
#
# ⚠️ ตารางตายตัวไม่พอ — transcript จริงจากห้อง voice (24 ส.ค.) ให้พยางค์แรกเพี้ยนไม่ซ้ำเลย:
#   "ก็เต้ทําอะไรอยู่" · "ออเต้วันนี้ฝนจะตกไหม" · "ตอเต้ร้องเพลง..." · "ได้ยินไหมรสเอ"
# ทุกตัวลงท้าย "เต้" เหมือนกันหมด (พยัญชนะ+สระท้ายเป็นส่วนที่ ASR จับติดเสมอ ส่วนหัวคำ
# ที่เสียงเบากว่าเพี้ยนได้สารพัด) จึงเพิ่ม pattern จับ "พยางค์สั้นๆ + เต้" ทั้งหมด แล้ว
# ตัดคำไทยจริงที่ลงท้าย "เต้" ออกด้วย _NAME_FALSE_POSITIVES กันแก้คำที่ไม่ได้หมายถึงบอท
#
# ยอมรับ false positive ได้มากกว่า false negative ตรงนี้: แก้ผิด = บอทตอบคำที่ไม่ได้เรียก
# (รำคาญ) แต่แก้ไม่ทัน = ผู้ใช้พูดแล้วบอทเงียบโดยไม่รู้สาเหตุ (ใช้งานไม่ได้เลย — เจอจริง
# ว่าต้องพูดซ้ำ 2 รอบทุกครั้ง)
_NAME_FALSE_POSITIVES = ("เต้นเต้", "เต้าเต้")   # คำซ้ำที่ไม่ใช่ชื่อบอท (เผื่อไว้)
_NAME_LOOSE_RE = re.compile(
    r"(?:^|(?<=[\sๆฯ]))"          # ต้นข้อความหรือหลังช่องว่าง — ไม่จับกลางคำ
    r"[ก-ฮ][่้๊๋]?[อ็ัาิีึืุูเแโใไ]{0,2}"   # พยางค์แรกอะไรก็ได้ (ที่ ASR เพี้ยน)
    r"[ก-ฮ]?[์]?"                  # ตัวสะกด + การันต์ ("ปาร์-", "รอส-", "ลอต-") — หลุดได้
    r"[เ]?[ตท][ี้์]?[้]?"            # แกนพยางค์ท้าย — "เต้"/"ตี้"/"เท้" (สระเพี้ยนได้ แต่ ต/ท คงอยู่)
    r"(?![ิึืุูัาน])"                 # กัน "เต้น/เต้า/ตีน" ที่เป็นคำไทยจริง ไม่ใช่ชื่อบอท
)
_NAME_FIX_RE = re.compile("|".join(re.escape(w) for w in sorted({*_NAME_FIXES, _BOT_NAME},
                                                                key=len, reverse=True)))


def _fix_bot_name(text: str) -> str:
    """แก้ตัวสะกดชื่อบอทให้ตรง — เรียกจากจุดเดียวคือ _emit_final() ก่อนถึง callback เสมอ

    สองชั้น: ตารางตายตัวก่อน (แม่นสุด) แล้วค่อย pattern หลวมจับ variant ที่ไม่เคยเจอ
    — พยางค์แรกของ "รอสเต้" เพี้ยนได้ไม่จำกัดรูปแบบ (ดู comment เหนือ _NAME_LOOSE_RE)
    """
    if not text:
        return text
    fixed = _NAME_FIX_RE.sub(_BOT_NAME, text)
    if _BOT_NAME in fixed:
        return fixed              # ตารางจัดการได้แล้ว ไม่ต้องเสี่ยงกับ pattern หลวม
    return _NAME_LOOSE_RE.sub(_BOT_NAME, fixed)


class _SpeakerBuf:
    """buffer เสียงของผู้พูด 1 คน (ระหว่างยังไม่จบประโยค)"""

    __slots__ = ("user", "pcm", "ms", "last_sound", "has_sound")

    def __init__(self, user):
        self.user = user                    # เก็บ object เดิมไว้ส่งให้ callback ตอนจบประโยค
        self.pcm = bytearray()
        self.ms = 0                         # ความยาวสะสม (ms) — นับจากจำนวน byte ที่ได้รับ
        self.last_sound = time.monotonic()  # เวลาของ chunk ล่าสุดที่ "ดัง" (ไม่นับ chunk เงียบ)
        self.has_sound = False              # เคยมี chunk ที่ดังเกินเกณฑ์ไหม (กรอง buffer เงียบสนิท)


# ── STT listener sink ──────────────────────────────────────────────────────────

class SttListener(voice_recv.AudioSink):
    """
    AudioSink ตัดประโยคจากเสียงใน voice channel แล้วถอดด้วย SttWorker

    ต้องแนกเข้ากับ voice client ผ่าน start_listening() เท่านั้น (ตรวจ isinstance
    VoiceRecvClient ให้) — สร้างเองแล้วเรียก vc.listen() ตรงๆ ได้ แต่จะเสียการตรวจ
    cls ของ client และการ ignore เสียงบอทเอง

    ตัวอย่าง callback:
        async def on_utterance(user, text): ...     # user = discord.Member/User
        def on_utterance(user, text): ...           # sync ก็ได้ (รันบน event loop เช่นกัน)
    """

    def __init__(self, stt_worker, on_utterance, loop, *, bot_user_id: int | None = None,
                 on_speech_start=None):
        super().__init__()
        self._stt = stt_worker
        self._on_utterance = on_utterance
        self._loop = loop
        self._bot_user_id = bot_user_id   # id ของบอท — ตัดเสียงตัวเอง (TTS) ทิ้งตั้งแต่ปากทาง
        # callback ตอน "เริ่มได้ยินเสียงคน" (sync, รันบน event loop) — ใช้ทำ barge-in
        # แยกจาก on_utterance เพราะต้องยิงทันที ไม่ใช่หลังถอดเสียงเสร็จ
        self._on_speech_start = on_speech_start

        # แจ้ง fallback ครั้งแรกครั้งเดียวต่อ listener (แตะเฉพาะ transcriber thread
        # จึงไม่ต้อง lock — ดู docstring Threading)
        self._llm_warned = False

        self._lock = threading.Lock()                 # ป้องกัน _buffers/_held (write อยู่ thread คนละตัวกับ checker/transcriber)
        self._buffers: dict[int, _SpeakerBuf] = {}    # {user_id: buffer ประโยคที่ยังไม่จบ}
        # ประโยคที่ checker ตัดแล้วแต่ "ข้อความยังดูไม่จบ" (เฉพาะ TURN_STRATEGY="semantic")
        # ทำไมเก็บ state นี้ไว้กับฝั่ง transcriber ไม่ใช่ใน _silence_checker_loop: การรู้ว่า
        # จบหรือยังต้องมี "ข้อความ" ซึ่งเกิดหลังถอดเสียง และการถอดเสียงต้องอยู่บน transcriber
        # thread เท่านั้น (ห้ามลากไปบนเส้นทางรับ packet/checker — ดู docstring Threading)
        # checker จึงทำแค่ส่งงาน + บังคับปล่อยเมื่อหมดเวลารอ ส่วนการถือ/แปะ/ตัดสินใจจบเกิด
        # ใน _transcribe_loop เท่านั้น (งานในคิวเรียงตามลำดับที่พูด — FIFO — การแปะท้าย
        # จึงได้ลำดับประโยคถูกเสมอ)
        self._held: dict[int, dict] = {}              # {user_id: {"user", "text", "deadline"}}
        self._jobs: "queue.Queue[tuple]" = queue.Queue(maxsize=_QUEUE_SIZE)
        self._stopping = threading.Event()

        self._checker = threading.Thread(
            target=self._silence_checker_loop, name=f"stt-silence-{id(self):x}", daemon=True)
        self._transcriber = threading.Thread(
            target=self._transcribe_loop, name=f"stt-asr-{id(self):x}", daemon=True)
        self._checker.start()
        self._transcriber.start()

        # ตั้งท้ายสุด — cleanup() อาจถูกเรียกจาก __del__ ของ base class แม้ __init__ พังครึ่งทาง
        # จะให้ cleanup รู้ว่า thread ถูก start จริงหรือยัง (ดู _started guard ใน cleanup)
        self._started = True

    # -- ส่วนที่ AudioSink บังคับ ------------------------------------------------

    def wants_opus(self) -> bool:
        # ต้องการ PCM ที่ถอดแล้ว (False = voice_recv จะสร้าง Opus decoder ให้และส่ง
        # data.pcm เข้ามาเป็น 48kHz stereo s16le) — รับ opus มาเองไม่มีประโยชน์
        return False

    def write(self, user, data: voice_recv.VoiceData) -> None:
        # อยู่บนเส้นทางรับ packet ของ voice_recv — ห้ามให้ exception หลุดไปฆ่า session
        # (PacketRouter.run จับแล้วสั่ง stop_listening ทั้งหมด) จึงกันไว้ที่นี่แทน
        try:
            self._write_inner(user, data)
        except Exception:
            logger.warning("   ⚠️ รับ packet เสียงไม่สำเร็จ — ข้าม packet นี้", exc_info=True)

    def _write_inner(self, user, data: voice_recv.VoiceData) -> None:
        if user is None or data is None:
            return   # packet จาก ssrc ที่ map หา user ไม่เจอ — ถอดแล้วจะไม่รู้ใครพูด ทิ้ง
        if self._bot_user_id is not None and user.id == self._bot_user_id:
            return   # เสียงบอทเอง (TTS ที่บอทกำลังเล่น) — ไม่งั้นบอทถอดเสียงตัวเองวนลูป

        pcm = data.pcm
        if not pcm:
            return

        loud = audioop.rms(pcm, _SAMPLE_WIDTH) > _SILENCE_RMS
        ms = round(len(pcm) / _BYTES_PER_MS)

        finished: _SpeakerBuf | None = None
        started_speaking = False
        with self._lock:
            buf = self._buffers.get(user.id)
            if buf is None:
                buf = self._buffers[user.id] = _SpeakerBuf(user)
            buf.pcm += pcm
            buf.ms += ms
            if loud:
                # อัปเดต last_sound เฉพาะ chunk ที่ดัง — ถ้านับ chunk เงียบ (comfort noise
                # ที่ Discord ส่งมาเรื่อยๆ ตอนคนเงียบ) เวลาเงียบจะไม่มีวันนับและประโยคไม่จบ
                buf.last_sound = time.monotonic()
                started_speaking = not buf.has_sound   # ขอบขาขึ้น: เงียบ → เริ่มมีเสียง
                buf.has_sound = True
                if buf.ms >= MAX_UTTERANCE_MS:
                    # พูดยาวถึงฝา — ตัดส่งถอดเสียงทันที ไม่รอเงียบ (เหตุผลที่ตัด ไม่ทิ้ง:
                    # ดู module docstring) packet ถัดไปของคนนี้จะเริ่ม buffer ใหม่เอง
                    finished = self._buffers.pop(user.id)

        if started_speaking and self._on_speech_start is not None:
            # ยิงทันทีที่ได้ยินเสียงแรก ไม่รอถอดเสียง — barge-in ต้องหยุดบอทภายในเสี้ยววินาที
            # ถ้ารอจนถอดเสียงเสร็จ (เงียบ 800ms + ASR + LLM ≈ 1s) บอทพูดทับไปแล้วค่อยหยุด
            # ซึ่งสายเกินจนไม่รู้สึกว่า "ขัดได้"
            self._loop.call_soon_threadsafe(self._run_speech_start, user)

        if finished is not None:
            self._enqueue_finished(finished)

    # -- การตัดประโยคและคิวงาน ---------------------------------------------------

    def _silence_checker_loop(self) -> None:
        """ตรวจระยะเ้นวรรคของทุกคนเป็นระยะ — แยก thread เพราะ write() ไม่ควรโดน sleep"""
        while not self._stopping.wait(_CHECK_INTERVAL_SEC):
            now = time.monotonic()
            finished: list[_SpeakerBuf] = []
            give_up: list[tuple] = []
            with self._lock:
                if TURN_STRATEGY == "semantic":
                    # เงียบครบ SILENCE_MS → ส่งเสียงไปถอดเหมือนโหมด silence ทุกประการ
                    # ต่างกันแค่ "ตอนได้ข้อความแล้วจะปล่อยเลยหรือถือรอ" ซึ่งเป็นงานของ
                    # transcriber (thread เดียวที่มีข้อความให้ดู — ดู _fold_semantic_text)
                    #
                    # ⚠️ เคยพังตรงนี้: เวอร์ชันแรก pop buffer ทิ้งแล้วสร้าง _held ที่ text=""
                    # ไปเลยโดยไม่ส่งเข้าคิว ASR — เสียงหายทั้งหมด ประโยคไม่เคยถูกถอด และ
                    # text ว่างตลอดไป (วินิจฉัยจริงเจอ packets=278 แต่ ตัด=0 asr=0)
                    # deadline ตั้งที่ transcriber ตอนแปะข้อความก้อนแรก ไม่ใช่ที่นี่ —
                    # ตั้งที่นี่จะได้ held ผีที่ไม่มีทางมีข้อความถ้า ASR คืนค่าว่าง
                    for uid, buf in list(self._buffers.items()):
                        if (now - buf.last_sound) * 1000 >= SILENCE_MS:
                            finished.append(self._buffers.pop(uid))
                    for uid, h in list(self._held.items()):
                        if now >= h["deadline"]:
                            self._held.pop(uid)
                            if h["text"].strip():
                                give_up.append((h["user"], h["text"]))
                else:
                    for uid, buf in list(self._buffers.items()):
                        if (now - buf.last_sound) * 1000 >= SILENCE_MS:
                            finished.append(self._buffers.pop(uid))
            for buf in finished:
                self._enqueue_finished(buf)
            for user, text in give_up:
                # หมดเวลารอโดยข้อความยังดูไม่จบ — ปล่อยเพราะ "เลิกรอ" ไม่ใช่เพราะ "ข้อความจบ"
                # (dispatch จาก checker thread ปลอดภัย เพราะ _dispatch_callback schedule
                # ขึ้น event loop ของบอทเสมอ ไม่แตะ discord.py จาก thread ตรงๆ)
                logger.debug(f"   [stt] ปล่อยประโยคค้างของ {self._user_label(user)} — "
                             f"เงียบเกิน SEMANTIC_IDLE_GIVEUP_MS ({SEMANTIC_IDLE_GIVEUP_MS}ms)")
                self._emit_final(user, text)

    def _enqueue_finished(self, buf: _SpeakerBuf) -> None:
        # กรองก่อนลงคิว — ประหยัดงานฝั่ง transcriber (ไอ/คลิกไมค์/เงียบสนิท ไม่ควรถึง ASR)
        name = self._user_label(buf.user)
        if not buf.has_sound:
            logger.debug(f"   [stt] ข้ามประโยคของ {name} ({buf.ms}ms) — เงียบสนิททั้งก้อน")
            return
        if buf.ms < MIN_UTTERANCE_MS:
            logger.debug(f"   [stt] ข้ามประโยคของ {name} ({buf.ms}ms < {MIN_UTTERANCE_MS}ms)")
            return
        job = (buf.user, bytes(buf.pcm), buf.ms)
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            # ASR ตามไม่ทัน (คนพูดพร้อมกันหลายคน/GPU ติด) — ทิ้งก้อนใหม่ ไม่ block write()
            # และไม่ block checker เพราะการรอคิวเต็ม = ดีเลย์ที่จะไปสะสมเป็น latency สะสม
            logger.warning(f"   ⚠️ คิวถอดเสียงเต็ม — ทิ้งประโยคของ {name} ({buf.ms}ms)")

    def _transcribe_loop(self) -> None:
        """ดึงงานจากคิวมาเขียน wav + ถอดเสียง — ทำบน thread แยก ไม่ใช่เส้นทางรับ packet"""
        while True:
            if self._stopping.is_set():
                # ตอนปิด ระบายคิวทิ้งเร็วๆ ไม่ถอดต่อ — ปิด session ให้เร็ว ไม่งั้น
                # callback ยิงหลังบอทออกจากห้องไปแล้ว (คำพูดครึ่งๆ กลางคันทิ้งได้)
                try:
                    while True:
                        self._jobs.get_nowait()
                except queue.Empty:
                    pass
                return
            try:
                user, pcm48, ms = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process_job(user, pcm48, ms)
            except Exception:
                # fail-safe ต่อ job — เสียประโยคนึงได้ แต่ thread ต้องรอดไปถอดก้อนถัดไป
                logger.warning(f"   ⚠️ ถอดเสียงล้มเหลว — ข้ามประโยคของ {self._user_label(user)}",
                               exc_info=True)

    def _process_job(self, user, pcm48: bytes, ms: int) -> None:
        if not self._stt.alive:
            # worker ตาย/timeout ถูก kill ไปแล้ว — แจ้งเตือนแล้วทิ้งก้อนนี้ (caller ของ
            # SttWorker มีหน้าที่ restart เอง ตาม contract ของ stt_client.transcribe)
            logger.warning(f"   ⚠️ SttWorker ไม่ทำงาน — ทิ้งประโยคของ {self._user_label(user)} ({ms}ms)")
            return

        wav_path = self._pcm_to_temp_wav(pcm48)
        try:
            text = self._stt.transcribe(wav_path)
        finally:
            try:
                os.remove(wav_path)   # ลบไม่ได้ก็ปล่อย — เป็นแค่ไฟล์ขยะใน temp dir
            except OSError:
                pass

        text = (text or "").strip()
        if not text:
            return   # ASR คืนว่าง (เสียงไม่ชัดพอ) — ไม่เรียก callback กันข้อความเปล่า

        if TURN_STRATEGY == "semantic":
            # ก้อนนี้ checker ตัดมาแล้ว แต่ยังไม่จบ — จบ/ถือ/แปะ ตัดสินใจจากเนื้อหา
            # อยู่ใน _fold_semantic_text (รันที่นี่เท่านั้น เพราะเป็น transcriber thread)
            self._fold_semantic_text(user, text)
        else:
            self._emit_final(user, text)

    def _fold_semantic_text(self, user, text: str) -> None:
        """(transcriber thread เท่านั้น) พับข้อความก้อนล่าสุดเข้ากับประโยคที่ถือรอของคนนี้ —
        จบ → ปล่อยทันที, ยังไม่จบ → ถือต่อและ re-arm deadline"""
        # ⚠️ ลำดับที่นี่สำคัญกับการมี LLM call (นานได้ถึง TURN_LLM_TIMEOUT_SEC และต้องรัน
        # *นอก* lock — ถือ lock คร่อม HTTP = บล็อก write()/checker ทั้งห้อง): เดิมการตัดสิน
        # เร็วจนวิ่งจบใต้ lock เดียวกับ checker จึงแทรกกันไม่ได้ แต่ตอนนี้ถ้าอ่าน h แล้วปล่อย
        # lock ไปถาม LLM โดยไม่แตะ state ก่อน checker จะแวะ give-up กลางทางได้ — pop ประโยค
        # เดิม (ยังไม่รวมก้อนใหม่) ไป emit แล้วเราตัดสินทีหลัง → ประโยคหาย/emit ซ้ำ
        # จึง "แปะก้อนใหม่ + re-arm deadline ใต้ lock ก่อน" แล้วค่อยถาม: ถ้า give-up ยิง
        # ระหว่างถาม มันปล่อยข้อความที่ *ครบรวมก้อนใหม่แล้ว* พอดี และเราเช็ค identity ของ h
        # ตอนผลกลับมาเพื่อไม่ emit ซ้ำ (exactly-once เสมอ)
        with self._lock:
            h = self._held.get(user.id)
            if h is None:
                # ไม่มีประโยครอ (เช่น give-up ปล่อยของเก่าไปแล้ว) → ถือเป็นประโยคใหม่
                # ที่มี deadline ของตัวเอง — ไม่มี state ไหนค้างถาวร
                h = self._held[user.id] = {"user": user, "text": ""}
            acc = " ".join(filter(None, (h["text"], text)))   # แปะท้ายแบบเดียวกับ bench
            if not acc.strip():
                self._held.pop(user.id, None)
                return                     # ยังไม่มีเนื้อความจริง — ไม่มีอะไรจะ dispatch
            h["text"] = acc                # แปะ optimistic — ถ้าคำตอบคือ "ยังไม่จบ" state ก็ถูกอยู่แล้ว
            h["deadline"] = time.monotonic() + SEMANTIC_IDLE_GIVEUP_MS / 1000

        if not self._is_utterance_finished(acc):
            return                         # ยังถือต่อ — รอก้อนถัดไป หรือหมดเวลาแล้ว checker ปล่อยเอง

        with self._lock:
            cur = self._held.get(user.id)
            if cur is not h:
                # give-up ปล่อยไปแล้ว (พร้อมก้อนนี้ เพราะเราแปะก่อนถาม) หรือโดนเริ่มถือใหม่
                # — ห้าม emit ซ้ำ ทิ้งคำตอบ stale นี้ไป
                return
            self._held.pop(user.id, None)  # จบแล้ว — pop ก่อน ให้ dispatch อยู่นอก lock
        self._emit_final(user, acc)

    def _is_utterance_finished(self, text: str) -> bool:
        """(transcriber thread) "ข้อความนี้พูดจบหรือยัง" — LLM ก่อน (TURN_LLM=True),
        ล้มเหลวกรณีใดก็ตาม → fallback heuristic ลิสต์คำเดิม คืน False = ยังไม่จบ (ถือรอ)"""
        if TURN_LLM:
            verdict = _ask_llm_finished(text)
            if verdict is not None:
                return verdict
            if not self._llm_warned:
                self._llm_warned = True    # warn ครั้งเดียว/listener — กัน spam ทุกประโยคตอน Ollama ล่ม
                logger.warning(
                    "   ⚠️ ถาม LLM end-of-turn ไม่สำเร็จ (Ollama ล่ม/timeout/JSON เพี้ยน)"
                    " — ใช้ heuristic ลิสต์คำแทน (รายละเอียดต่อประโยคอยู่ใน DEBUG)")
        return looks_unfinished(text)

    def _emit_final(self, user, text: str) -> None:
        """จุดเดียวที่ข้อความถึง callback — แก้ชื่อบอทที่นี่ที่เดียว (เหตุผลที่ _NAME_FIXES)
        เรียกได้จากทั้ง transcriber และ checker thread เพราะ dispatch schedule ขึ้น
        event loop ของบอทเสมอ"""
        fixed = _fix_bot_name(text)
        logger.info(f"   🎙️ {self._user_label(user)}: {fixed}")
        self._dispatch_callback(user, fixed)

    @staticmethod
    def _pcm_to_temp_wav(pcm48: bytes) -> str:
        """แปลง PCM 48kHz stereo → wav 16kHz mono s16 (ฟอร์แมตที่โมเดลต้องการ) แล้วเขียน temp file"""
        # ตัดให้ลงตัว frame กัน audioop โยน error ถ้า packet สุดท้ายไม่เต็ม (ปกติ decoder
        # คืนทีละ 3840B พอดี แต่กัน edge case ของ jitter buffer flush)
        pcm48 = pcm48[:len(pcm48) // (_SAMPLE_WIDTH * _DISCORD_CHANNELS) * (_SAMPLE_WIDTH * _DISCORD_CHANNELS)]
        mono = audioop.tomono(pcm48, _SAMPLE_WIDTH, 1.0, 1.0)
        pcm16, _ = audioop.ratecv(mono, _SAMPLE_WIDTH, 1, _DISCORD_RATE, _TARGET_RATE, None)

        fd, path = tempfile.mkstemp(prefix="roste_stt_", suffix=".wav")
        try:
            os.close(fd)
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(_SAMPLE_WIDTH)
                w.setframerate(_TARGET_RATE)
                w.writeframes(pcm16)
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return path

    # -- callback dispatch --------------------------------------------------------

    def _dispatch_callback(self, user, text: str) -> None:
        cb = self._on_utterance
        try:
            if inspect.iscoroutinefunction(cb):
                # async callback → schedule บน event loop ของบอทจาก thread นอก loop
                # (transcriber thread) — run_coroutine_threadsafe คือทางที่ถูกต้อง
                fut = asyncio.run_coroutine_threadsafe(cb(user, text), self._loop)
                fut.add_done_callback(self._log_async_cb_error)
            else:
                # sync callback → ผ่าน call_soon_threadsafe ให้รันบน event loop เหมือนกัน
                # (แทนที่จะรันบน transcriber thread ตรงๆ) เพราะ callback มักแตะ discord.py
                # ซึ่งไม่ thread-safe — ต่างกันแค่รูปแบบ callback เท่านั้น
                self._loop.call_soon_threadsafe(self._run_sync_cb, cb, user, text)
        except RuntimeError:
            # loop ปิดไปแล้ว (บอทกำลัง shutdown) — ประโยคนี้หายไปตามธรรมชาติ ไม่ใช่ error
            logger.warning("   ⚠️ event loop ปิดอยู่ — ไม่ได้เรียก on_utterance")

    def _run_speech_start(self, user) -> None:
        """(event loop) แจ้งว่ามีคนเริ่มพูด — callback พังต้องไม่ทำ listener ล้ม
        เหมือน on_utterance ทุกประการ ต่างแค่ยิงเร็วกว่าและไม่มีข้อความให้ดู"""
        try:
            self._on_speech_start(user)
        except Exception:
            logger.warning("   ⚠️ on_speech_start callback โยน exception", exc_info=True)

    @staticmethod
    def _run_sync_cb(cb, user, text: str) -> None:
        try:
            cb(user, text)
        except Exception:
            # callback ของผู้ใช้พัง ≠ พังทั้ง listener — log แล้วปล่อยให้ประโยคถัดไปทำงานต่อ
            logger.warning("   ⚠️ on_utterance callback โยน exception", exc_info=True)

    @staticmethod
    def _log_async_cb_error(fut: "concurrent.futures.Future") -> None:
        try:
            exc = fut.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning("   ⚠️ on_utterance callback โยน exception", exc_info=exc)

    @staticmethod
    def _user_label(user) -> str:
        uid = getattr(user, "id", "?")
        return getattr(user, "display_name", None) or getattr(user, "name", str(uid))

    # -- ปิดเครื่อง ----------------------------------------------------------------

    def cleanup(self) -> None:
        """หยุด thread ทั้งหมด + ทิ้ง buffer ค้าง — idempotent และไม่ raise เด็ดขาด
        (base class เรียกจาก __del__ และ AudioReader.stop() ก็เรียกซ้ำ อาจถูกเรียก
        สองรอบ/จาก thread ไหนก็ได้ รวมถึงตอน interpreter กำลัง teardown)"""
        if not getattr(self, "_started", False):
            return
        self._started = False

        self._stopping.set()   # checker (Event.wait) และ transcriber (queue.get timeout) เห็นแล้วจบเอง

        # ทิ้ง buffer ค้าง ไม่ flush เข้า ASR — ตอนออกจากห้องคำพูดครึ่งๆ กลางคันไม่มีค่า
        # พอจะแลกกับการรอ transcribe (หลักสิบ ms+/ก้อน) ตอนปิด session ประโยคที่ "ถือรอ"
        # ของ semantic mode ก็ทิ้งเช่นกัน (ครึ่งๆ กลางคันเหมือนกัน)
        with self._lock:
            dropped = len(self._buffers)
            holds = len(self._held)
            self._buffers.clear()
            self._held.clear()
        if dropped or holds:
            logger.debug(f"   [stt] cleanup: ทิ้ง buffer ค้าง {dropped} คน, "
                         f"ประโยคที่ถือรอ {holds} คน")

        try:
            self._checker.join(timeout=1.0)
        except RuntimeError:
            pass   # cleanup ถูกเรียกจาก thread ตัวเอง (edge ของ __del__) — join ตัวเองไม่ได้
        except Exception:
            logger.debug("   [stt] cleanup: join checker มีปัญหา", exc_info=True)
        # ไม่ join transcriber — มัน daemon และจะเห็น _stopping ภายใน 0.5s (timeout ของ
        # queue.get) การ join รอมันแปลว่ารอ transcribe/EOT-call ก้อนสุดท้ายจบ ซึ่งขัดกับ
        # เป้าปิดเร็ว (EOT call เองก็โดน TURN_LLM_TIMEOUT_SEC จำกัดไว้แล้ว)


# ── helper สำหรับ bot.py ───────────────────────────────────────────────────────

async def start_listening(voice_client, stt_worker, on_utterance,
                          loop: asyncio.AbstractEventLoop | None = None,
                          *, on_speech_start=None) -> SttListener:
    """
    แนก SttListener เข้ากับ voice client ที่ต่ออยู่ แล้วคืน listener (เอาไว้เรียก cleanup())

    ⚠️ voice_client ต้องมาจาก channel.connect(cls=discord.ext.voice_recv.VoiceRecvClient)
    เท่านั้น — VoiceClient ธรรมดา (ที่ bot.py ใช้อยู่ตอนนี้) ไม่มี .listen(sink) จึงฟังเสียง
    คนอื่นไม่ได้ ฟังก์ชันนี้จะ raise TypeError แทนการปล่อยให้พังเงียบๆ ตอนกลางคัน

    loop ไม่ใส่ได้ ถ้าเรียกจากใน coroutine ของบอทอยู่แล้ว (ดึง running loop ให้เอง)
    """
    if not isinstance(voice_client, VoiceRecvClient):
        raise TypeError(
            "start_listening() ต้องใช้ VoiceRecvClient — "
            "เรียก channel.connect(cls=discord.ext.voice_recv.VoiceRecvClient) แทน "
            f"channel.connect() ธรรมดา (ตอนนี้ได้ {type(voice_client).__name__})"
        )
    if loop is None:
        loop = asyncio.get_running_loop()

    client_user = getattr(getattr(voice_client, "client", None), "user", None)
    listener = SttListener(
        stt_worker, on_utterance, loop,
        bot_user_id=getattr(client_user, "id", None),
        on_speech_start=on_speech_start,
    )
    # listen() raise ClientException ถ้ายังไม่ต่อ/ฟังอยู่แล้ว — ปล่อยให้หลุดขึ้นไป เพราะ
    # เป็น misuse ที่ caller ควรเห็นตั้งแต่ตอน attach ไม่ใช่เงียบๆ แล้วไม่มีเสียงให้ถอดเลย
    voice_client.listen(listener)
    return listener
