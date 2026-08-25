"""Interactive CLI chat with Ox Alpha (stealth model) via OpenRouter.

Usage:
    setx OPENROUTER_API_KEY "sk-or-v1-..."   (or set in current shell)
    python tools/chat_ox_alpha.py
"""
import os
import sys
import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "stealth/ox-alpha"


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Missing OPENROUTER_API_KEY environment variable.")
        print('PowerShell:  $env:OPENROUTER_API_KEY = "sk-or-v1-..."')
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Roste-bot Ox Alpha CLI",
        "Content-Type": "application/json",
    }

    messages = []
    print(f"Chatting with {MODEL} (ctrl+c to quit)\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nbye")
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            resp = requests.post(
                API_URL,
                headers=headers,
                json={"model": MODEL, "messages": messages},
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[error] request failed: {e}")
            messages.pop()
            continue

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        reply = choice.get("message", {}).get("content", "")
        if not reply:
            print(f"[error] unexpected response: {data}")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})
        print(f"ox-alpha> {reply}\n")


if __name__ == "__main__":
    main()
