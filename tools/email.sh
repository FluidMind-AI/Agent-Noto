#!/bin/bash
# Noto Email Client - Main wrapper
#
# Usage:
#   email.sh check operator@example.com
#   email.sh read operator@example.com 12345
#   email.sh send assistant@example.com --to "user@example.com" --subject "Hello" --body "Message"
#   email.sh reply operator@example.com 12345 --body "My reply"
#   email.sh search "invoice" --account operator@example.com
#   email.sh sync operator@example.com --days 7
#   email.sh accounts

NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$NOTO_HOME/.venv"

# Activate venv if exists
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi

python3 "$SCRIPT_DIR/email_client.py" "$@"
