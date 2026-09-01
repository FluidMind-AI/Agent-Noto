#!/usr/bin/env bash
#
# noto setup.sh — Interactive scaffolding for a new PA (Personal Assistant) instance
#
# Usage: ./setup.sh /path/to/new-pa-instance
#
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Helpers ---
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
header()  { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}\n"; }

ask() {
    local prompt="$1"
    local default="${2:-}"
    local var_name="$3"
    if [[ -n "$default" ]]; then
        echo -en "${BOLD}$prompt${NC} [${default}]: "
    else
        echo -en "${BOLD}$prompt${NC}: "
    fi
    read -r input
    if [[ -z "$input" && -n "$default" ]]; then
        eval "$var_name='$default'"
    elif [[ -z "$input" ]]; then
        error "This field is required."
        ask "$prompt" "$default" "$var_name"
    else
        eval "$var_name='$input'"
    fi
}

# --- Resolve script directory (where the template lives) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/AGENTS.TEMPLATE.md"

if [[ ! -f "$TEMPLATE_FILE" ]]; then
    error "AGENTS.TEMPLATE.md not found at $SCRIPT_DIR"
    error "Run this script from the noto repo directory."
    exit 1
fi

# --- Parse target directory ---
if [[ $# -lt 1 ]]; then
    echo -e "${BOLD}Usage:${NC} $0 /path/to/new-pa-instance"
    echo ""
    echo "Creates a new Personal Assistant instance with the noto framework."
    echo ""
    echo "Example:"
    echo "  $0 ~/my-assistant"
    echo "  $0 /home/user/jarvis"
    exit 1
fi

# Portable absolute-path resolution (GNU `realpath -m` is absent on macOS/BSD)
TARGET_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$1")"
INSTANCE_NAME="$(basename "$TARGET_DIR")"

# --- Check if target exists ---
if [[ -d "$TARGET_DIR" ]]; then
    if [[ -f "$TARGET_DIR/AGENTS.md" || -f "$TARGET_DIR/CLAUDE.md" ]]; then
        error "Directory $TARGET_DIR already contains an AGENTS.md / CLAUDE.md file."
        error "This looks like an existing PA instance. Aborting to avoid overwriting."
        exit 1
    fi
    warn "Directory $TARGET_DIR already exists. Files will be created inside it."
    echo -en "Continue? [y/N]: "
    read -r confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        info "Aborted."
        exit 0
    fi
fi

# --- Header ---
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║        noto — PA Framework Setup         ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""
info "Setting up new PA instance at: ${BOLD}$TARGET_DIR${NC}"
echo ""

# --- Interactive questions ---
header "Agent Configuration"

ask "Agent name (e.g., Noto, Jarvis, Friday)" "" AGENT_NAME
ask "Agent role (e.g., Chief of Staff, Personal Assistant)" "Personal Assistant" AGENT_ROLE

header "User Configuration"

ask "User's full name" "" USER_NAME
# Derive first name lowercase for profile file
USER_FIRST_NAME="${USER_NAME%% *}"
USER_FIRST_NAME_LOWER="$(echo "$USER_FIRST_NAME" | tr '[:upper:]' '[:lower:]')"
USER_PROFILE_FILE="${USER_FIRST_NAME_LOWER}-profile.md"

ask "Preferred language" "English" USER_PREFERRED_LANGUAGE
ask "Native language (or same as preferred)" "$USER_PREFERRED_LANGUAGE" USER_NATIVE_LANGUAGE

header "System Configuration"

ask "System hostname (e.g., mini-noto, homelab, macbook)" "$(hostname)" SYSTEM_NAME
ask "Operating system" "$(uname -s)" SYSTEM_OS
ask "RAM (e.g., 4 GB, 16 GB)" "" SYSTEM_RAM
ask "Storage (e.g., 256 GB, 1 TB)" "" SYSTEM_STORAGE
ask "System hardware (e.g., Mac Mini, Raspberry Pi, Desktop)" "" SYSTEM_HARDWARE
ask "Timezone (e.g., America/Denver, UTC)" "$(cat /etc/timezone 2>/dev/null || echo 'UTC')" SYSTEM_TIMEZONE

header "Email Configuration (optional — press Enter to skip)"

echo -en "${BOLD}User's email account${NC} (e.g., user@example.com) [skip]: "
read -r EMAIL_ACCOUNT_1
EMAIL_ACCOUNT_1="${EMAIL_ACCOUNT_1:-user@example.com}"

echo -en "${BOLD}Agent's email account${NC} (e.g., agent@example.com) [skip]: "
read -r EMAIL_ACCOUNT_2
EMAIL_ACCOUNT_2="${EMAIL_ACCOUNT_2:-agent@example.com}"

# --- Derived values ---
HOME_DIR="$(dirname "$TARGET_DIR")"
INSTANCE_DIR="$TARGET_DIR"
AGENT_ID="pa-$(echo "$AGENT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
CURRENT_YEAR="$(date +%Y)"

# --- Confirm ---
header "Review Configuration"

echo -e "  Agent:     ${GREEN}$AGENT_NAME${NC} ($AGENT_ROLE)"
echo -e "  User:      ${GREEN}$USER_NAME${NC} ($USER_PREFERRED_LANGUAGE / $USER_NATIVE_LANGUAGE)"
echo -e "  System:    ${GREEN}$SYSTEM_NAME${NC} ($SYSTEM_OS, $SYSTEM_RAM RAM, $SYSTEM_STORAGE)"
echo -e "  Hardware:  ${GREEN}$SYSTEM_HARDWARE${NC}"
echo -e "  Timezone:  ${GREEN}$SYSTEM_TIMEZONE${NC}"
echo -e "  Email 1:   ${GREEN}$EMAIL_ACCOUNT_1${NC}"
echo -e "  Email 2:   ${GREEN}$EMAIL_ACCOUNT_2${NC}"
echo -e "  Target:    ${GREEN}$TARGET_DIR${NC}"
echo -e "  Agent ID:  ${GREEN}$AGENT_ID${NC}"
echo ""
echo -en "${BOLD}Proceed with setup? [Y/n]:${NC} "
read -r proceed
if [[ "$proceed" == "n" || "$proceed" == "N" ]]; then
    info "Aborted."
    exit 0
fi

# --- Create directory structure ---
header "Creating Directory Structure"

dirs=(
    "$TARGET_DIR/brain"
    "$TARGET_DIR/memory"
    "$TARGET_DIR/indexes"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_1/inbox"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_1/sent"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_1/drafts"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_1/attachments"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_2/inbox"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_2/sent"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_2/drafts"
    "$TARGET_DIR/emails/$EMAIL_ACCOUNT_2/attachments"
    "$TARGET_DIR/articles/drafts"
    "$TARGET_DIR/articles/published"
    "$TARGET_DIR/prompts"
    "$TARGET_DIR/tools"
    "$TARGET_DIR/scripts"
    "$TARGET_DIR/skills"
    "$TARGET_DIR/tests"
    "$TARGET_DIR/docs"
    "$TARGET_DIR/deploy"
    "$TARGET_DIR/.claude"
)

for dir in "${dirs[@]}"; do
    mkdir -p "$dir"
done
success "Directory structure created (${#dirs[@]} directories)"

# --- Copy tools from noto repo ---
header "Copying Tools & Templates"

# Copy tools if they exist in the repo
if [[ -d "$SCRIPT_DIR/tools" ]]; then
    cp -n "$SCRIPT_DIR/tools/"* "$TARGET_DIR/tools/" 2>/dev/null || true
    success "Copied tools from noto repo"
fi

# Copy skills if they exist
if [[ -d "$SCRIPT_DIR/skills" ]]; then
    cp -rn "$SCRIPT_DIR/skills/"* "$TARGET_DIR/skills/" 2>/dev/null || true
    success "Copied skills from noto repo"
fi

# Copy brain templates
cp -n "$SCRIPT_DIR/templates/eisenhower.md" "$TARGET_DIR/brain/eisenhower.md" 2>/dev/null || true
cp -n "$SCRIPT_DIR/brain/agents.md" "$TARGET_DIR/brain/agents.md" 2>/dev/null || true
cp -n "$SCRIPT_DIR/brain/README.md" "$TARGET_DIR/brain/README.md" 2>/dev/null || true
success "Copied brain templates"

# Copy memory README
cp -n "$SCRIPT_DIR/memory/README.md" "$TARGET_DIR/memory/README.md" 2>/dev/null || true
success "Copied memory README"

# Dependency manifest (installed into .venv below)
cp -n "$SCRIPT_DIR/requirements.txt" "$TARGET_DIR/requirements.txt" 2>/dev/null || true

# --- Harness adapters ---
# The framework is harness-neutral: AGENTS.md + skills/ + tools/ work under
# Claude Code, Codex CLI, Gemini CLI, OpenCode, ... Anything harness-specific
# lives in a small adapter so nothing else has to know which one you run.

# Claude Code: permissions + session hooks, and skills discoverable as slash commands.
sed -e "s|{{INSTANCE_DIR}}|$INSTANCE_DIR|g" \
    "$SCRIPT_DIR/templates/claude/settings.json" > "$TARGET_DIR/.claude/settings.json"
if [[ ! -e "$TARGET_DIR/.claude/skills" ]]; then
    ln -s ../skills "$TARGET_DIR/.claude/skills" 2>/dev/null || true
fi
success "Claude Code adapter: .claude/settings.json (allow tools, ask before sending email, session hooks) + .claude/skills -> skills/"

# Scheduling templates for the nightly learning pass (launchd for macOS, cron elsewhere).
sed -e "s|{{INSTANCE_DIR}}|$INSTANCE_DIR|g" \
    -e "s|{{INSTANCE_NAME}}|$INSTANCE_NAME|g" \
    -e "s|{{HOME_DIR}}|$HOME|g" \
    "$SCRIPT_DIR/templates/launchd/com.noto.nightly.plist" > "$TARGET_DIR/deploy/com.noto.$INSTANCE_NAME.nightly.plist"
sed -e "s|{{INSTANCE_DIR}}|$INSTANCE_DIR|g" \
    "$SCRIPT_DIR/templates/crontab.example" > "$TARGET_DIR/deploy/crontab.example"
success "Scheduling templates in deploy/ (nightly learning pass)"

# --- Generate noto.yaml ---
header "Generating Configuration"

cat > "$TARGET_DIR/noto.yaml" <<YAML
# noto.yaml — PA instance configuration
# Generated by noto setup.sh on $(date -Iseconds)

agent:
  name: "$AGENT_NAME"
  role: "$AGENT_ROLE"
  id: "$AGENT_ID"

user:
  name: "$USER_NAME"
  preferred_language: "$USER_PREFERRED_LANGUAGE"
  native_language: "$USER_NATIVE_LANGUAGE"
  profile_file: "$USER_PROFILE_FILE"

system:
  name: "$SYSTEM_NAME"
  hardware: "$SYSTEM_HARDWARE"
  os: "$SYSTEM_OS"
  ram: "$SYSTEM_RAM"
  storage: "$SYSTEM_STORAGE"
  timezone: "$SYSTEM_TIMEZONE"

email:
  account_1: "$EMAIL_ACCOUNT_1"
  account_2: "$EMAIL_ACCOUNT_2"

paths:
  home_dir: "$HOME_DIR"
  instance_dir: "$INSTANCE_DIR"
  instance_name: "$INSTANCE_NAME"

# LLM backend for BACKGROUND jobs only (nightly learning pass, transcript
# feedback extraction). Your interactive agent is whatever harness you run.
# auto = first available of: claude-cli, codex-cli, gemini-cli, anthropic
# (ANTHROPIC_API_KEY), openai (OPENAI_API_KEY). See noto.yaml.example for
# Ollama / LM Studio / OpenRouter settings.
llm:
  backend: "auto"
  model: ""
  base_url: ""
  api_key_env: ""
  timeout_seconds: 180

# Learning loop (tools/learn.py)
learning:
  db: "indexes/learning.db"
  lessons_file: "brain/lessons.md"
  log_file: "brain/learning-log.md"
  skills_dir: "skills"
YAML
success "Generated noto.yaml"

# --- Generate AGENTS.md from template ---
info "Generating AGENTS.md from template..."

sed \
    -e "s|{{AGENT_NAME}}|$AGENT_NAME|g" \
    -e "s|{{AGENT_ROLE}}|$AGENT_ROLE|g" \
    -e "s|{{AGENT_ID}}|$AGENT_ID|g" \
    -e "s|{{USER_NAME}}|$USER_NAME|g" \
    -e "s|{{USER_PREFERRED_LANGUAGE}}|$USER_PREFERRED_LANGUAGE|g" \
    -e "s|{{USER_NATIVE_LANGUAGE}}|$USER_NATIVE_LANGUAGE|g" \
    -e "s|{{USER_FIRST_NAME_LOWER}}|$USER_FIRST_NAME_LOWER|g" \
    -e "s|{{USER_PROFILE_FILE}}|$USER_PROFILE_FILE|g" \
    -e "s|{{SYSTEM_NAME}}|$SYSTEM_NAME|g" \
    -e "s|{{SYSTEM_HARDWARE}}|$SYSTEM_HARDWARE|g" \
    -e "s|{{SYSTEM_OS}}|$SYSTEM_OS|g" \
    -e "s|{{SYSTEM_RAM}}|$SYSTEM_RAM|g" \
    -e "s|{{SYSTEM_STORAGE}}|$SYSTEM_STORAGE|g" \
    -e "s|{{SYSTEM_TIMEZONE}}|$SYSTEM_TIMEZONE|g" \
    -e "s|{{HOME_DIR}}|$HOME_DIR|g" \
    -e "s|{{INSTANCE_DIR}}|$INSTANCE_DIR|g" \
    -e "s|{{INSTANCE_NAME}}|$INSTANCE_NAME|g" \
    -e "s|{{EMAIL_ACCOUNT_1}}|$EMAIL_ACCOUNT_1|g" \
    -e "s|{{EMAIL_ACCOUNT_2}}|$EMAIL_ACCOUNT_2|g" \
    -e "s|{{YEAR}}|$CURRENT_YEAR|g" \
    "$TEMPLATE_FILE" > "$TARGET_DIR/AGENTS.md"

# Harness aliases: Codex/OpenCode/Cursor read AGENTS.md natively; Claude Code
# reads CLAUDE.md; Gemini CLI reads GEMINI.md. Symlinks keep one source of truth.
for alias in CLAUDE.md GEMINI.md; do
    if [[ ! -e "$TARGET_DIR/$alias" ]]; then
        ln -s AGENTS.md "$TARGET_DIR/$alias" 2>/dev/null || cp "$TARGET_DIR/AGENTS.md" "$TARGET_DIR/$alias"
    fi
done
success "Generated AGENTS.md (+ CLAUDE.md, GEMINI.md aliases)"

# --- Also replace placeholders in brain templates ---
for brain_file in "$TARGET_DIR/brain/eisenhower.md" "$TARGET_DIR/brain/agents.md"; do
    if [[ -f "$brain_file" ]]; then
        # In-place sed portable across GNU and BSD/macOS: write to a temp
        # file and move it back (BSD `sed -i` requires a suffix argument).
        sed \
            -e "s|{{AGENT_NAME}}|$AGENT_NAME|g" \
            -e "s|{{USER_NAME}}|$USER_NAME|g" \
            "$brain_file" > "$brain_file.tmp" && mv "$brain_file.tmp" "$brain_file"
    fi
done
success "Updated brain templates with agent/user names"

# --- Create starter memory files ---
if [[ ! -f "$TARGET_DIR/memory/$USER_PROFILE_FILE" ]]; then
    cat > "$TARGET_DIR/memory/$USER_PROFILE_FILE" <<EOF
# $USER_NAME - Profile

## Basic Info
- **Name:** $USER_NAME
- **Preferred language:** $USER_PREFERRED_LANGUAGE
- **Native language:** $USER_NATIVE_LANGUAGE

## Family

<!-- Add family members here -->

## Background

<!-- Add background information here -->

## Health

<!-- Add health information here -->

## Preferences

<!-- Add preferences here -->
EOF
    success "Created memory/$USER_PROFILE_FILE"
fi

if [[ ! -f "$TARGET_DIR/memory/goals.md" ]]; then
    cat > "$TARGET_DIR/memory/goals.md" <<EOF
# Goals

$USER_NAME's current goals and priorities.

**Last updated:** $(date +%Y-%m-%d)

---

## Active Goals

<!-- Add goals here -->

---

## Completed Goals

(None yet)
EOF
    success "Created memory/goals.md"
fi

if [[ ! -f "$TARGET_DIR/memory/journal-$CURRENT_YEAR.md" ]]; then
    cat > "$TARGET_DIR/memory/journal-$CURRENT_YEAR.md" <<EOF
# Journal $CURRENT_YEAR

Life events and milestones for $USER_NAME.

---

## $(date +%B) $CURRENT_YEAR

- **$(date +%Y-%m-%d):** PA instance set up with noto framework
EOF
    success "Created memory/journal-$CURRENT_YEAR.md"
fi

# --- Create .gitignore ---
header "Creating .gitignore"

cat > "$TARGET_DIR/.gitignore" <<'GITIGNORE'
# Credentials & secrets
brain/credentials.yaml
brain/*-credentials.yaml
brain/*-credentials.yml
*.env
.env
.env.*

# Python
.venv/
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/

# Indexes (large binary files - rebuild from tools)
indexes/*.mv2
indexes/*.db
indexes/*.log

# Email cache (can be re-synced)
emails/*/inbox/
emails/*/sent/
emails/*/drafts/
emails/*/attachments/

# OS
.DS_Store
Thumbs.db
*.swp
*.swo
*~

# IDE / harness-local overrides
.idea/
.vscode/
*.code-workspace
.claude/settings.local.json

# Logs
*.log
/tmp/

# Node
node_modules/
GITIGNORE

success "Created .gitignore"

# --- Set up Python venv ---
header "Setting Up Python Environment"

if command -v uv &>/dev/null; then
    info "Using uv for Python environment..."
    (cd "$TARGET_DIR" && uv venv .venv 2>&1) && success "Created .venv with uv" || warn "Failed to create venv with uv"
    if [[ -f "$TARGET_DIR/.venv/bin/activate" ]]; then
        info "Installing dependencies from requirements.txt..."
        (cd "$TARGET_DIR" && source .venv/bin/activate && uv pip install -r requirements.txt 2>&1) && success "Installed requirements.txt" || warn "Dependency install failed (later: uv pip install -r requirements.txt)"
    fi
elif command -v python3 &>/dev/null; then
    info "uv not found, using python3 venv..."
    python3 -m venv "$TARGET_DIR/.venv" 2>&1 && success "Created .venv with python3" || warn "Failed to create venv"
    if [[ -f "$TARGET_DIR/.venv/bin/activate" ]]; then
        info "Installing dependencies from requirements.txt..."
        (cd "$TARGET_DIR" && source .venv/bin/activate && pip install -r requirements.txt 2>&1) && success "Installed requirements.txt" || warn "Dependency install failed (later: pip install -r requirements.txt)"
    fi
else
    warn "Neither uv nor python3 found. Skipping venv setup."
    warn "Install Python and run: cd $TARGET_DIR && uv venv .venv && source .venv/bin/activate && uv pip install -r requirements.txt"
fi

# --- Initialize git repo if not already ---
header "Git Repository"

if [[ -d "$TARGET_DIR/.git" ]]; then
    info "Git repo already exists"
else
    if command -v git &>/dev/null; then
        (cd "$TARGET_DIR" && git init 2>&1) && success "Initialized git repository" || warn "Failed to init git repo"
    else
        warn "git not found. Initialize manually: cd $TARGET_DIR && git init"
    fi
fi

# --- Print summary ---
header "Setup Complete!"

echo -e "${GREEN}${BOLD}Your new PA instance is ready at:${NC}"
echo -e "  ${BOLD}$TARGET_DIR${NC}"
echo ""
echo -e "${BOLD}Directory structure:${NC}"
echo "  $INSTANCE_NAME/"
echo "  ├── AGENTS.md              # Agent instructions (generated) — CLAUDE.md, GEMINI.md are aliases"
echo "  ├── noto.yaml              # Instance configuration (llm backend, paths, learning loop)"
echo "  ├── requirements.txt"
echo "  ├── .gitignore"
echo "  ├── .claude/               # Claude Code adapter: settings.json (permissions + hooks), skills -> ../skills"
echo "  ├── brain/"
echo "  │   ├── eisenhower.md      # Task management"
echo "  │   ├── agents.md          # Agent registry"
echo "  │   ├── lessons.md         # Approved lessons (written by tools/learn.py after first run)"
echo "  │   └── README.md"
echo "  ├── memory/"
echo "  │   ├── $USER_PROFILE_FILE"
echo "  │   ├── goals.md"
echo "  │   ├── journal-$CURRENT_YEAR.md"
echo "  │   └── README.md"
echo "  ├── indexes/               # Memvid indexes + learning.db (gitignored)"
echo "  ├── emails/                # Email cache (gitignored)"
echo "  ├── deploy/                # launchd plist + crontab example for the nightly learning pass"
echo "  ├── articles/"
echo "  ├── tools/                 # email, memory, files, llm.py (model chokepoint), learn.py (learning loop)"
echo "  ├── skills/                # SKILL.md skills (Agent Skills format)"
echo "  ├── scripts/  tests/  docs/  prompts/"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo -e "  1. ${CYAN}cd $TARGET_DIR${NC}"
echo -e "  2. Review ${CYAN}AGENTS.md${NC} (uncomment the sections you need)"
echo -e "  3. Add credentials to ${CYAN}brain/credentials.yaml${NC} (gitignored); email accounts in ${CYAN}noto.yaml${NC}"
echo -e "  4. Check the background model backend: ${CYAN}python tools/llm.py backends${NC} then ${CYAN}python tools/llm.py selftest${NC}"
echo -e "     (auto = claude/codex/gemini CLI, or set llm: in noto.yaml for Ollama / OpenAI-compatible / Anthropic API)"
echo -e "  5. Seal your instructions: ${CYAN}tools/memory-integrity-check.sh init${NC}"
echo -e "  6. Schedule the nightly learning pass:"
echo -e "       macOS:  ${CYAN}cp deploy/com.noto.$INSTANCE_NAME.nightly.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.noto.$INSTANCE_NAME.nightly.plist${NC}"
echo -e "       Linux:  ${CYAN}crontab -e${NC} and paste ${CYAN}deploy/crontab.example${NC}"
echo -e "  7. ${CYAN}git add -A && git commit -m 'Initial agent setup'${NC}"
echo ""
echo -e "${BOLD}Launch with the harness you use${NC} (all read the same AGENTS.md):"
echo -e "  ${CYAN}cd $TARGET_DIR && claude${NC}        # Claude Code (hooks + slash-command skills wired)"
echo -e "  ${CYAN}cd $TARGET_DIR && codex${NC}         # Codex CLI"
echo -e "  ${CYAN}cd $TARGET_DIR && gemini${NC}        # Gemini CLI"
echo ""
echo -e "${GREEN}${BOLD}Happy automating!${NC}"
