#!/bin/bash
# Quick email send
#
# Usage:
#   email-send.sh --to "user@example.com" --subject "Hello" --body "Message"
#   email-send.sh --from assistant@example.com --to "user@example.com" --subject "Hello" --body "Message"

LOLABOT_HOME="${LOLABOT_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Sending account must be explicit (--from) — no hardcoded default.
ACCOUNT=""

# Parse --from if provided
ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --from)
            ACCOUNT="$2"
            shift 2
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$ACCOUNT" ]]; then
    echo "ERROR: no sending account. Pass --from <address> (must match an account in your config)." >&2
    exit 1
fi

"$SCRIPT_DIR/email.sh" send "$ACCOUNT" "${ARGS[@]}"
