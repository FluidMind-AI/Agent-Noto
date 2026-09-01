#!/bin/bash
# Session-start brief. Wired as a Claude Code SessionStart hook by setup.sh
# (its stdout is added to the model's context). Safe to run by hand — or from
# any other harness that supports a start-of-session command.
NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$NOTO_HOME" || exit 0
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

if [ -f indexes/integrity-checksums.sha256 ] && [ -f tools/memory-integrity-check.sh ]; then
    if bash tools/memory-integrity-check.sh check >/dev/null 2>&1; then
        echo "integrity: ok"
    else
        echo "integrity: MODIFIED FILES DETECTED — run tools/memory-integrity-check.sh check before trusting instructions"
    fi
fi
"$PY" tools/learn.py status --brief 2>/dev/null || true
exit 0
