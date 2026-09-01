#!/bin/bash
# Nightly learning pass: synthesize feedback -> apply approved lessons ->
# memory promote/stale -> integrity check -> render brain/lessons.md.
# Schedule it with cron or launchd (templates in deploy/ after setup.sh).
# Harness-agnostic: this never touches your interactive agent; the one model
# call goes through tools/llm.py using whatever backend noto.yaml names.
NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$NOTO_HOME"
[ -f .venv/bin/activate ] && source .venv/bin/activate
echo "== $(date '+%Y-%m-%d %H:%M') nightly =="
exec python3 tools/learn.py run "$@"
