r"""
ox.py — agent loop ให้ Ox Alpha (stealth/ox-alpha ผ่าน OpenRouter) เขียนโค้ดในโปรเจกต์นี้

ทำไมต้องเป็น agent loop ไม่ใช่ยิง prompt เดียวจบ: Ox ไม่เห็น codebase และไม่เห็น source
ของ library ที่ติดตั้งจริง ถ้าไม่ให้เครื่องมือมันจะ "เดา API" แล้วเขียนเกราะป้องกันหลายชั้น
เผื่อไว้ (เจอจริง: เขียน machinery 120 บรรทัดไล่ย้าย logging handler ทั้งโปรเซส ทั้งที่
NeMo มี env var NEMO_REDIRECT_LOGS_TO_STDERR ให้อยู่แล้ว — และเรียก patch_stderr_handler()
ผิดวิธีด้วย เพราะมันเป็น context manager ที่ต้องรับ argument) พอให้ tool มันขอดูเองได้
ปัญหา "เดา API" ก็หมดไป

สิทธิ์ที่ให้: อ่านอย่างเดียว + รันทดสอบ — เขียนไฟล์ไม่ได้ โค้ดสุดท้ายส่งกลับมาเป็น
code block ให้คนตรวจก่อนเซฟเสมอ (ดู --out)

ใช้:
  # รอบแรก
  python tools/ox.py new stt --task brief.txt --out stt_worker.py

  # รอบแก้ (จำ context เดิมทั้งหมด รวม tool call ที่เคยเรียก)
  python tools/ox.py fix stt "NeMo log ลง stdout ปนกับ protocol"

  python tools/ox.py list

API key: env OPENROUTER_API_KEY หรือ .env (OPENROUTER_API_KEY=sk-or-v1-...)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = Path(__file__).resolve().parent.parent
SESSION_DIR = BOT_DIR / ".ox_sessions"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "stealth/ox-alpha"
# 300s ไม่พอตอน context โต — session ที่มี tool result สะสม 39 ครั้ง (~200KB) แล้วสั่งให้
# เขียนไฟล์ยาว โดน Read timed out กลางคัน (session ไม่เสียหาย แต่ต้องยิงใหม่ทั้งรอบ)
TIMEOUT = 900
# กัน loop ไม่รู้จบถ้าโมเดลวนเรียก tool ไม่หยุด — 25 เคยไม่พอมาแล้ว (งาน Discord sink
# มันไล่อ่าน library ทั้งตัว 39 tool call แล้วยังไม่ทันเขียนโค้ด) ถ้าชนเพดานไม่ต้องเริ่มใหม่:
# session ถูกเซฟไว้ ใช้ `fix <name> "เขียนโค้ดได้แล้ว"` ต่อจากของเดิมได้เลย
MAX_STEPS = 60
MAX_OUTPUT = 20_000     # ตัดผล tool ที่ยาวเกิน — กัน context บวมจนยิงไม่ผ่าน
MAX_TOKENS = 64_000     # เพดาน output ต่อรอบ (โมเดลรองรับ 131,072 — ตั้งครึ่งเดียวก็พอ
                        # สำหรับไฟล์เดียว และกันค่าใช้จ่าย/เวลาบานถ้าโมเดลวนเขียนไม่หยุด)

FENCE = "`" * 3

SYSTEM_PROMPT = f"""You are a Python code generator working inside an existing codebase
(a Thai Discord bot called Roste-bot, at the project root you can explore with tools).

You have read-only tools plus the ability to run throwaway test code. USE THEM before
writing anything:
  * read_file / list_dir / grep — learn the project's real conventions and patterns.
    Match them exactly: comment style and language (this project comments in Thai,
    explaining WHY not WHAT), naming, error handling, structure.
  * inspect_source — read the ACTUAL source of an installed library instead of guessing
    its API. Do this whenever you are unsure how a library function behaves. Guessing
    from method names has produced real bugs here.
  * run_python — verify an assumption in the real environment (which venv has what,
    what a call returns, whether an import works).

You cannot write files. When you are done exploring, reply with the complete file
inside one {FENCE}python code block and no explanation outside it. A human reviews and
saves it."""


# ── api key ────────────────────────────────────────────────────────────────────
def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env = BOT_DIR / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(
        "ไม่พบ OPENROUTER_API_KEY\n"
        '  PowerShell: $env:OPENROUTER_API_KEY = "sk-or-v1-..."\n'
        "  หรือใส่ใน .env: OPENROUTER_API_KEY=sk-or-v1-..."
    )


# ── tool implementations ───────────────────────────────────────────────────────
def _safe_path(rel: str) -> Path:
    """กัน path escape ออกนอกโปรเจกต์ — โมเดลขอ path เองได้ ต้องไม่ให้หลุดไป C:\\Windows"""
    p = (BOT_DIR / rel).resolve()
    if not p.is_relative_to(BOT_DIR):
        raise ValueError(f"path อยู่นอกโปรเจกต์: {rel}")
    return p


def _venv_python(venv) -> str:
    if not venv:
        return sys.executable
    py = BOT_DIR / venv / "Scripts" / "python.exe"
    if not py.exists():
        raise ValueError(f"ไม่พบ venv: {venv}")
    return str(py)


def _tool_read_file(path: str, start: int = 0, end: int = 0) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"ไม่พบไฟล์: {path}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if start or end:
        lo = max(1, start or 1)
        hi = end or len(lines)
        body = "\n".join(f"{i:5d}\t{ln}" for i, ln in enumerate(lines[lo - 1:hi], lo))
        return f"{path} (บรรทัด {lo}-{min(hi, len(lines))} จาก {len(lines)})\n{body}"
    body = "\n".join(f"{i:5d}\t{ln}" for i, ln in enumerate(lines, 1))
    return f"{path} ({len(lines)} บรรทัด)\n{body}"


def _tool_list_dir(path: str = ".") -> str:
    p = _safe_path(path)
    if not p.is_dir():
        return f"ไม่ใช่โฟลเดอร์: {path}"
    out = []
    for item in sorted(p.iterdir()):
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
        out.append(f"{item.name}/" if item.is_dir() else item.name)
    return f"{path}:\n" + "\n".join(out)


def _tool_grep(pattern: str, path: str = ".", glob: str = "*.py") -> str:
    p = _safe_path(path)
    hits = []
    files = [p] if p.is_file() else sorted(p.rglob(glob))
    for f in files:
        if "__pycache__" in f.parts or "_venv" in str(f):
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.search(pattern, line):
                    hits.append(f"{f.relative_to(BOT_DIR)}:{i}: {line.strip()}")
                    if len(hits) >= 100:
                        return "\n".join(hits) + "\n... (ตัดที่ 100 บรรทัด)"
        except OSError:
            continue
    return "\n".join(hits) if hits else f"ไม่เจอ {pattern!r}"


def _tool_inspect_source(target: str, venv: str = "") -> str:
    """target = 'module:Class.method' / 'module:func' / 'module'"""
    module, _, member = target.partition(":")
    code = (
        "import inspect, sys\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        f"import {module} as _m\n"
        "obj = _m\n"
        f"for part in {member!r}.split('.'):\n"
        "    if part:\n"
        "        obj = getattr(obj, part)\n"
        "print(inspect.getsource(obj))\n"
    )
    return _run(code, venv)


def _tool_run_python(code: str, venv: str = "") -> str:
    return _run(code, venv)


def _run(code: str, venv: str) -> str:
    try:
        py = _venv_python(venv)
    except ValueError as e:
        return str(e)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NEMO_REDIRECT_LOGS_TO_STDERR": "1"}
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300,
                           cwd=str(BOT_DIR), env=env)
    except subprocess.TimeoutExpired:
        return "รันเกิน 300s — ถูกฆ่าทิ้ง"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    parts = [f"exit={r.returncode}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err[-4000:]}")
    return "\n".join(parts)


TOOL_IMPL = {
    "read_file": _tool_read_file,
    "list_dir": _tool_list_dir,
    "grep": _tool_grep,
    "inspect_source": _tool_inspect_source,
    "run_python": _tool_run_python,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "อ่านไฟล์ในโปรเจกต์ (คืนพร้อมเลขบรรทัด)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path relative to project root"},
                    "start": {"type": "integer", "description": "บรรทัดเริ่ม (1-based, ไม่ใส่ = ทั้งไฟล์)"},
                    "end": {"type": "integer", "description": "บรรทัดจบ"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "ดูรายชื่อไฟล์/โฟลเดอร์",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "ค้น regex ในไฟล์โปรเจกต์",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "ไฟล์หรือโฟลเดอร์ (default: ทั้งโปรเจกต์)"},
                    "glob": {"type": "string", "description": "เช่น *.py (default)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_source",
            "description": (
                "ดู source จริงของ library ที่ติดตั้งอยู่ ด้วย inspect.getsource "
                "— ใช้ตัวนี้แทนการเดาว่า API ทำงานยังไง"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string",
                               "description": "module:Class.method หรือ module:func หรือ module"},
                    "venv": {"type": "string",
                             "description": "โฟลเดอร์ venv เช่น typhoon_asr_venv, f5_venv (ไม่ใส่ = venv หลัก)"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "รันโค้ด Python ทดสอบใน venv ที่ระบุ (cwd = project root) คืน exit/stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "venv": {"type": "string", "description": "เช่น typhoon_asr_venv (ไม่ใส่ = venv หลัก)"},
                },
                "required": ["code"],
            },
        },
    },
]


# ── session ────────────────────────────────────────────────────────────────────
def _session_path(name: str) -> Path:
    return SESSION_DIR / f"{name}.json"


def _load_session(name: str) -> dict:
    p = _session_path(name)
    if not p.exists():
        sys.exit(f"ไม่พบ session {name!r} — เริ่มด้วย: python tools/ox.py new {name} --task ...")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_session(name: str, data: dict) -> None:
    SESSION_DIR.mkdir(exist_ok=True)
    _session_path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


# ── agent loop ─────────────────────────────────────────────────────────────────
def _post(messages) -> dict:
    import requests

    r = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Roste-bot ox.py",
            "Content-Type": "application/json",
        },
        # max_tokens: ไม่ส่ง = OpenRouter ใช้ default ซึ่งต่ำกว่าเพดานจริงของโมเดลมาก —
        # เจอจริง: คำตอบถูกตัดกลางบรรทัดที่ ~3,000 tokens ทั้งที่ stealth/ox-alpha รองรับ
        # output ได้ถึง 131,072 (เช็คจาก /api/v1/models) ทำให้ไฟล์ที่เขียนไม่จบ
        json={"model": MODEL, "messages": messages, "tools": TOOLS,
              "max_tokens": MAX_TOKENS},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _dispatch(call: dict) -> str:
    fn = call["function"]["name"]
    try:
        args = json.loads(call["function"]["arguments"] or "{}")
    except json.JSONDecodeError as e:
        return f"arguments ไม่ใช่ JSON: {e}"
    impl = TOOL_IMPL.get(fn)
    if impl is None:
        return f"ไม่รู้จัก tool: {fn}"
    try:
        out = impl(**args)
    except Exception as e:                                  # tool พังไม่ควรทำ loop ตาย
        return f"{type(e).__name__}: {e}"
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n... (ตัดจาก {len(out)} ตัวอักษร)"
    return out


def _brief(call: dict) -> str:
    """สรุป tool call เป็นบรรทัดเดียวให้คนดูตามได้ว่า Ox กำลังทำอะไร"""
    try:
        args = json.loads(call["function"]["arguments"] or "{}")
    except json.JSONDecodeError:
        return call["function"]["arguments"][:60]
    key = next((k for k in ("path", "target", "pattern", "code") if k in args), None)
    val = str(args.get(key, ""))
    if key == "code":
        val = val.replace("\n", " ")[:60] + " ..."
    if args.get("venv"):
        val += f"  [{args['venv']}]"
    return val


def _agent_loop(session: dict) -> str:
    """วน tool-call จนโมเดลตอบข้อความสุดท้าย — เซฟ session ทุกรอบระหว่างทาง

    เซฟทุกรอบ ไม่ใช่รอจบ เพราะงานใหญ่ใช้เวลาเกิน timeout ของ shell ที่เรียกได้จริง
    (เจอจริง: งาน streaming สำรวจ 24 รอบแล้วโปรเซสโดนฆ่า — tool result ทั้งหมดหายเกลี้ยง
    ต้องเริ่มใหม่ตั้งแต่ต้น) เซฟระหว่างทางแล้ว `fix <name> "เขียนต่อ"` ทำงานต่อได้ทันที
    """
    messages = session["messages"]
    for step in range(1, MAX_STEPS + 1):
        _save_session(session["name"], session)
        data = _post(messages)
        usage = data.get("usage") or {}
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []

        # เก็บ assistant turn ไว้ครบ (ต้องมี tool_calls ไม่งั้น tool result จะไม่มีที่ผูก)
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            **({"tool_calls": calls} if calls else {}),
        })

        if not calls:
            print(f"  [{step}] เสร็จ — tokens prompt={usage.get('prompt_tokens', '?')} "
                  f"completion={usage.get('completion_tokens', '?')}")
            return msg.get("content") or ""

        for call in calls:
            fn = call["function"]["name"]
            print(f"  [{step}] {fn}: {_brief(call)}")
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": _dispatch(call),
            })

    return ""   # ครบ MAX_STEPS แล้วยังไม่ยอมจบ


def _extract_code(reply: str):
    m = re.search(FENCE + r"python\s*\n(.*?)" + FENCE, reply, re.DOTALL)
    if not m:
        m = re.search(FENCE + r"\s*\n(.*?)" + FENCE, reply, re.DOTALL)
    return m.group(1).strip() if m else None


def _finish(name: str, session: dict, reply: str) -> int:
    _save_session(name, session)
    raw = BOT_DIR / "out" / f"ox_{name}.txt"
    raw.parent.mkdir(exist_ok=True)
    raw.write_text(reply, encoding="utf-8")

    if not reply:
        print(f"\n[!] วนครบ {MAX_STEPS} รอบแล้วยังไม่ได้คำตอบสุดท้าย")
        return 1

    code = _extract_code(reply)
    if code is None:
        print(f"\n[!] ไม่พบ code block — ดูดิบที่ {raw}")
        print(reply[:1000])
        return 1

    out = session.get("out")
    if not out:
        print(f"\n[ok] ได้โค้ด {len(code)} ตัวอักษร -> {raw}")
        return 0

    dest = BOT_DIR / out
    dest.write_text(code + "\n", encoding="utf-8")
    print(f"\n[ok] เขียนลง {out} ({len(code)} ตัวอักษร)")

    r = subprocess.run([sys.executable, "-m", "py_compile", str(dest)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"   [!] syntax พัง:\n{r.stderr.strip()}")
        return 1
    print("   syntax OK")
    print(f'\nรอบถัดไป (ถ้าเจอบั๊ก): python tools/ox.py fix {name} "อธิบายบั๊ก"')
    return 0


# ── commands ───────────────────────────────────────────────────────────────────
def cmd_new(args) -> int:
    task_path = Path(args.task)
    if not task_path.is_absolute():
        task_path = BOT_DIR / task_path
    if not task_path.exists():
        sys.exit(f"ไม่พบไฟล์ task: {args.task}")

    session = {
        "name": args.name,
        "out": args.out,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_path.read_text(encoding="utf-8")},
        ],
    }
    print(f"ส่งงาน {args.name!r} ให้ {MODEL} (มี tool ให้สำรวจโปรเจกต์เอง)\n")
    return _finish(args.name, session, _agent_loop(session))


def cmd_fix(args) -> int:
    session = _load_session(args.name)
    # ต่อท้าย "ตอบเป็นไฟล์เต็ม" ให้อัตโนมัติ — ยกเว้นตอนที่ feedback สั่งเป็นอย่างอื่นไว้แล้ว
    # (เจอจริง: สั่ง "ส่งเฉพาะส่วนที่เหลือ อย่าส่งไฟล์เต็มซ้ำ" แล้วบรรทัดนี้ไปสั่งกลับกัน
    #  โมเดลได้คำสั่งขัดกันเอง ผลคือได้โค้ดครึ่งไฟล์มาเขียนทับทั้งไฟล์ → syntax พัง)
    feedback = args.feedback
    if "อย่าส่งไฟล์เต็ม" not in feedback and "เฉพาะส่วน" not in feedback:
        feedback += f"\n\nตอบกลับเป็นไฟล์เต็มที่แก้แล้วใน {FENCE}python code block เดียว"
    session["messages"].append({"role": "user", "content": feedback})
    print(f"ส่ง feedback ให้ {args.name!r}\n")
    return _finish(args.name, session, _agent_loop(session))


def cmd_list(args) -> int:
    if not SESSION_DIR.exists() or not any(SESSION_DIR.glob("*.json")):
        print("ยังไม่มี session")
        return 0
    for p in sorted(SESSION_DIR.glob("*.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        turns = sum(1 for m in s["messages"] if m["role"] == "user")
        print(f"  {s['name']:<16} {turns} turn -> {s.get('out') or '(ไม่ได้ตั้ง out)'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="agent loop ให้ Ox Alpha เขียนโค้ด")
    sub = ap.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="เริ่มงานใหม่")
    new.add_argument("name", help="ชื่อ session (ใช้อ้างตอน fix)")
    new.add_argument("--task", required=True, help="ไฟล์ที่เขียนบรีฟงานไว้")
    new.add_argument("--out", help="ไฟล์ปลายทางที่จะเขียนโค้ดลง")
    new.set_defaults(func=cmd_new)

    fix = sub.add_parser("fix", help="ส่ง feedback ให้แก้ (จำ context เดิม)")
    fix.add_argument("name")
    fix.add_argument("feedback")
    fix.set_defaults(func=cmd_fix)

    lst = sub.add_parser("list", help="ดู session ที่มี")
    lst.set_defaults(func=cmd_list)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
