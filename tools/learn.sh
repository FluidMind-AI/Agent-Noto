#!/bin/bash
# Wrapper for learn.py (all commands). stdlib-only, so the venv is optional.
NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$NOTO_HOME"
[ -f .venv/bin/activate ] && source .venv/bin/activate
python3 tools/learn.py "$@"
