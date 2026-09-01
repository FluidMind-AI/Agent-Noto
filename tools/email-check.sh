#!/bin/bash
# Quick inbox check
#
# Usage:
#   email-check.sh                    # Check the default inbox
#   email-check.sh operator@example.com # Check specific account
#   email-check.sh assistant@example.com    # Check Lola's inbox

LOLABOT_HOME="${LOLABOT_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACCOUNT="${1:-operator@example.com}"
shift 2>/dev/null

"$SCRIPT_DIR/email.sh" check "$ACCOUNT" "$@"
