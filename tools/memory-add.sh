#!/bin/bash
# Wrapper for memory_indexer.py add command
NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$NOTO_HOME"
source .venv/bin/activate
python tools/memory_indexer.py add "$@"
