#!/bin/bash
# Wrapper for file_indexer.py (all commands)
NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$NOTO_HOME"
source .venv/bin/activate
python tools/file_indexer.py "$@"
