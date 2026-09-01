#!/bin/bash
# Memory Integrity Checker
# Detects unauthorized modifications to critical agent files.
# Usage:
#   ./memory-integrity-check.sh init     # Generate initial checksums
#   ./memory-integrity-check.sh check    # Verify against stored checksums
#   ./memory-integrity-check.sh update   # Update checksums (after authorized changes)
#
# Cron example (check every hour):
#   0 * * * * /path/to/tools/memory-integrity-check.sh check >> /tmp/integrity-check.log 2>&1

set -euo pipefail

NOTO_HOME="${NOTO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CHECKSUM_FILE="$NOTO_HOME/indexes/integrity-checksums.sha256"
ALERT_LOG="/tmp/integrity-alerts.log"

# Portable hashing. macOS 13+ ships a BSD /sbin/sha256sum whose `-c` does NOT
# verify like GNU's (it silently reports OK), so we never rely on `-c`: hashes
# are computed per file and compared here. Perl `shasum` exists on macOS and
# nearly every Linux; GNU sha256sum is the fallback.
hash_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

# Files to monitor: the agent's instructions (AGENTS.md; CLAUDE.md/GEMINI.md are
# normally symlinks to it — watched only when they are real files).
WATCHED_FILES=()
for f in "$NOTO_HOME/AGENTS.md" "$NOTO_HOME/CLAUDE.md" "$NOTO_HOME/GEMINI.md"; do
    [ -f "$f" ] && [ ! -L "$f" ] && WATCHED_FILES+=("$f")
done

# brain/*.md — except the files the learning loop rewrites on every run
# (brain/lessons.md, brain/learning-log.md); those are generated, not instructions.
for f in "$NOTO_HOME"/brain/*.md; do
    case "$(basename "$f")" in
        lessons.md|learning-log.md) continue ;;
    esac
    [ -f "$f" ] && WATCHED_FILES+=("$f")
done

# Instance skills (their "Learned" sections change only via tools/learn.py after
# operator approval, which then runs `update`).
for f in "$NOTO_HOME"/skills/*/SKILL.md; do
    [ -f "$f" ] && WATCHED_FILES+=("$f")
done
for f in "$HOME"/.claude/projects/*/memory/*.md; do
    [ -f "$f" ] && WATCHED_FILES+=("$f")
done

# Skills SKILL.md files
for f in "$HOME"/.claude/skills/*/SKILL.md; do
    [ -f "$f" ] && WATCHED_FILES+=("$f")
done

generate_checksums() {
    echo "# Memory Integrity Checksums"
    echo "# Generated: $(date -Iseconds)"
    echo "# Files: ${#WATCHED_FILES[@]}"
    echo ""
    for f in "${WATCHED_FILES[@]}"; do
        if [ -f "$f" ]; then
            echo "$(hash_file "$f")  $f"
        fi
    done
}

verify_checksums() {
    # Prints one line per problem: "<path>: FAILED" or "<path>: MISSING".
    # Returns 0 when everything matches.
    local problems=0 expected path actual
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        expected="${line%%  *}"
        path="${line#*  }"
        if [ ! -f "$path" ]; then
            echo "$path: MISSING"; problems=$((problems+1)); continue
        fi
        actual="$(hash_file "$path")"
        if [ "$actual" != "$expected" ]; then
            echo "$path: FAILED"; problems=$((problems+1))
        fi
    done < "$CHECKSUM_FILE"
    [ "$problems" -eq 0 ]
}

cmd="${1:-check}"

case "$cmd" in
    init)
        generate_checksums > "$CHECKSUM_FILE"
        echo "Checksums initialized for ${#WATCHED_FILES[@]} files."
        echo "Stored at: $CHECKSUM_FILE"
        ;;

    update)
        generate_checksums > "$CHECKSUM_FILE"
        echo "Checksums updated for ${#WATCHED_FILES[@]} files."
        ;;

    check)
        if [ ! -f "$CHECKSUM_FILE" ]; then
            echo "ERROR: No checksum file found. Run '$0 init' first."
            exit 1
        fi

        RESULT=$(verify_checksums) || true
        FAILURES=$(printf '%s\n' "$RESULT" | grep -c ": FAILED$" || true)
        MISSING=$(printf '%s\n' "$RESULT" | grep -c ": MISSING$" || true)

        if [ "$FAILURES" -gt 0 ] || [ "$MISSING" -gt 0 ]; then
            TIMESTAMP=$(date -Iseconds)
            echo "[$TIMESTAMP] INTEGRITY ALERT: $FAILURES file(s) modified, $MISSING file(s) missing" | tee -a "$ALERT_LOG"
            printf '%s\n' "$RESULT" | grep -E ": (FAILED|MISSING)$" | tee -a "$ALERT_LOG"
            echo ""
            echo "If these changes were authorized, run: $0 update"
            exit 2
        else
            echo "All ${#WATCHED_FILES[@]} files OK — no unauthorized modifications detected."
        fi
        ;;

    list)
        echo "Monitored files (${#WATCHED_FILES[@]}):"
        for f in "${WATCHED_FILES[@]}"; do
            if [ -f "$f" ]; then
                echo "  [OK] $f"
            else
                echo "  [MISSING] $f"
            fi
        done
        ;;

    *)
        echo "Usage: $0 {init|check|update|list}"
        exit 1
        ;;
esac
