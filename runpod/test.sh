#!/usr/bin/env bash
# รันเทสบน RunPod — ส่ง argument ต่อให้ pytest ได้ เช่น bash runpod/test.sh tests/test_memory.py -x
set -euo pipefail
cd "$(dirname "$0")/.."
source runpod/env.sh
exec venv/bin/python -m pytest -q "$@"
