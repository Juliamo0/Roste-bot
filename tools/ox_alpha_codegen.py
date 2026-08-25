"""Ask Ox Alpha (via OpenRouter) to write a Python script, run it, and let it
self-correct on errors before handing the result back for review.

Usage:
    $env:OPENROUTER_API_KEY = "sk-or-v1-..."
    python tools/ox_alpha_codegen.py "write a function that reverses a linked list, with a self-test"

Flow:
    1. Send the task to Ox Alpha, asking for a single Python file in a ```python fenced block.
    2. Extract the code, save it to out/ox_alpha_gen.py.
    3. Run it with `python`, capture stdout/stderr/exit code.
    4. If it fails, send the traceback back to Ox Alpha and ask for a fix. Repeat up to MAX_ROUNDS.
    5. Print a final summary (code + run result) for human/Claude review.
"""
import os
import re
import sys
import subprocess
import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "stealth/ox-alpha"
MAX_ROUNDS = 3
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
OUT_FILE = os.path.join(OUT_DIR, "ox_alpha_gen.py")

SYSTEM_PROMPT = (
    "You are a Python code generator. Given a task, respond with a single "
    "self-contained Python script inside one ```python code block. "
    "Include a small self-test (e.g. asserts or a __main__ block) so the "
    "script proves itself when run directly. No explanation needed outside "
    "the code block unless asked."
)


def call_ox_alpha(api_key, messages):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Roste-bot Ox Alpha Codegen",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        API_URL,
        headers=headers,
        json={"model": MODEL, "messages": messages},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def extract_code(text):
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else None


def run_script(path):
    result = subprocess.run(
        [sys.executable, path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def main():
    if len(sys.argv) < 2:
        print('Usage: python tools/ox_alpha_codegen.py "task description"')
        sys.exit(1)
    task = " ".join(sys.argv[1:])

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Missing OPENROUTER_API_KEY environment variable.")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for round_num in range(1, MAX_ROUNDS + 1):
        print(f"\n=== Round {round_num}: asking Ox Alpha ===")
        reply = call_ox_alpha(api_key, messages)
        messages.append({"role": "assistant", "content": reply})

        code = extract_code(reply)
        if not code:
            print("[error] no code block found in reply:")
            print(reply)
            sys.exit(1)

        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"[saved] {OUT_FILE}")

        print("=== Running ===")
        try:
            returncode, stdout, stderr = run_script(OUT_FILE)
        except subprocess.TimeoutExpired:
            print("[error] script timed out after 30s")
            sys.exit(1)

        print(f"exit code: {returncode}")
        if stdout:
            print("--- stdout ---")
            print(stdout)
        if stderr:
            print("--- stderr ---")
            print(stderr)

        if returncode == 0:
            print("\n=== SUCCESS ===")
            print(f"Final script: {OUT_FILE}")
            print("Review the code above / in the file before trusting or using it further.")
            return

        if round_num == MAX_ROUNDS:
            print(f"\n=== FAILED after {MAX_ROUNDS} rounds ===")
            print(f"Last script left at: {OUT_FILE}")
            return

        messages.append({
            "role": "user",
            "content": (
                f"The script failed with exit code {returncode}.\n"
                f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n"
                "Please fix the script and reply with the corrected full script "
                "in one ```python code block."
            ),
        })


if __name__ == "__main__":
    main()
