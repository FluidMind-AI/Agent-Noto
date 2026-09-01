#!/bin/bash
# Session-end capture. Wired as a Claude Code SessionEnd hook by setup.sh:
# the hook receives JSON on stdin with a `transcript_path`; we mine it for
# lasting feedback in the background so the session can exit immediately.
# Cheap regex cues run first; the model is only called when a cue fires.
# Other harnesses: feed a transcript by hand with
#   tools/learn.sh extract --transcript PATH   (or --text-file PATH)
NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$NOTO_HOME" || exit 0
input="$(cat 2>/dev/null)"
transcript="$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("transcript_path", ""))
except Exception:
    print("")' 2>/dev/null)"
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
nohup "$PY" tools/learn.py extract --transcript "$transcript" --quiet >/dev/null 2>&1 &
exit 0
