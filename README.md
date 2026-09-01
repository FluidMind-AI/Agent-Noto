# noto

**A base personal-agent framework for coding-agent harnesses.** Email, semantic memory, file indexing, task management, content security, and an operator-gated learning loop — the foundation FluidMind builds specialized agents on. Works with Claude Code, Codex CLI, Gemini CLI, OpenCode and any other harness that reads `AGENTS.md`; background jobs run on whichever model you point them at.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS%20%7C%20Linux](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)]()

---

## What This Is

noto is a batteries-included scaffold for a personal AI assistant. Clone the repo, run `setup.sh`, and launch your coding agent in the generated instance — the agent's name, role, user, and model backend all live in `noto.yaml`, so the same framework can back any number of differently-branded agents.

It is deliberately **not** an agent runtime. Every harness already ships an agent loop, tool calling, and model access. noto adds the things they don't: durable memory, a security layer for untrusted content, a task system, and a way to get better from corrections — each reachable from a shell.

This is the **base layer**: free of any domain-specific (e.g. recruiting) or platform-specific (e.g. Lark) code. Specializations live in their own repos and layer on top.

## What You Get

- **Any harness, any LLM** — `AGENTS.md` is the instruction file (`CLAUDE.md` / `GEMINI.md` are aliases). Background jobs call one chokepoint, `tools/llm.py`, backed by the claude/codex/gemini CLIs, the Anthropic API, or any OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter, vLLM). See [docs/any-llm.md](docs/any-llm.md).
- **Learning loop** — corrections are recorded as feedback, a nightly pass synthesizes them into lessons with reasoning, the operator approves, approved lessons become standing instructions (global in `brain/lessons.md`, skill-scoped appended to that skill's `SKILL.md`). Nothing changes behaviour until a human says yes. See [docs/learning-loop.md](docs/learning-loop.md).
- **Email Client** — IMAP/SMTP with multi-account support, SPF/DKIM/DMARC verification
- **Semantic Memory** — Hybrid Memvid + SQLite for fast search over facts, events, learnings, decisions, with reinforcement counters and short-term → long-term promotion
- **File Index** — Track files across local, remote, and cloud locations (OneDrive, Google Drive, S3, iCloud)
- **Task Management** — Eisenhower Matrix prioritization system
- **Content Security** — 34-pattern prompt injection defense, email sanitizer, attachment risk assessment, file integrity checksums
- **Skills** — File processing, mail handling, memory delegation (Agent Skills `SKILL.md` format)
- **HEIC/Image Processing** — Convert Apple image formats for AI consumption
- **Claude Code adapter** — generated `.claude/settings.json` with sane permissions (tools allowed, email send asks first) and session hooks; skills exposed as slash commands. Delete the folder if you don't use Claude Code; nothing else depends on it.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/FluidMind-AI/Agent-Noto.git noto

# Scaffold a new agent instance (interactive; creates .venv and installs requirements.txt)
./noto/setup.sh ~/my-assistant
cd ~/my-assistant
export NOTO_HOME=~/my-assistant     # put this in your shell profile

# Pick the model for background jobs (auto = first of claude/codex/gemini CLI, then API keys)
python tools/llm.py backends
python tools/llm.py selftest

# Seal your instructions, schedule the nightly learning pass (see deploy/)
tools/memory-integrity-check.sh init

# Launch with the harness you use — they all read the same AGENTS.md
claude        # or: codex, gemini, opencode ...
```

## How It Works

1. **Clone & scaffold** — `setup.sh` creates your agent instance with config, tools, skills, the Claude Code adapter, and scheduling templates
2. **Configure** — `noto.yaml` holds the agent's name, email accounts, paths, and the `llm:` backend for background jobs
3. **Launch** — run your harness in the instance directory; it reads `AGENTS.md` and has everything it needs
4. **Learn** — the agent records corrections as it works; `tools/nightly.sh` turns them into proposed lessons; you approve with `tools/learn.sh approve L3`

The framework is instance-agnostic: the repo holds engine code and templates only; every name, credential, and preference is config, and instances are separate (private) directories that are never pushed here.

## Project Structure

```
your-assistant/              # Your agent instance (private, never pushed)
├── AGENTS.md                # Generated from AGENTS.TEMPLATE.md (CLAUDE.md, GEMINI.md -> symlinks)
├── noto.yaml                # Your config (git-ignored)
├── requirements.txt
├── .claude/                 # Claude Code adapter (settings.json, skills -> ../skills)
├── tools/                   # From this repo (copied at scaffold time)
├── skills/                  # From this repo; grows "Learned" sections as lessons are approved
├── brain/                   # Tasks (eisenhower.md), agent registry, lessons.md, learning-log.md
├── memory/                  # Journals, profiles, goals
├── emails/                  # Cached emails
├── indexes/                 # Memvid indexes, learning.db, checksums
└── deploy/                  # launchd plist + crontab example for the nightly pass
```

## Tools

| Tool | Purpose |
|------|---------|
| `tools/llm.py` | The one place background jobs call a model; backend from `noto.yaml` |
| `tools/learn.py` (`learn.sh`) | Learning loop: feedback → lessons → approval → standing instructions |
| `tools/nightly.sh` | Scheduled pass: synthesize, apply, memory promote/stale, integrity check |
| `tools/email_client.py` (`email.sh`) | Read, send, reply, forward, search emails |
| `tools/email_sanitizer.py` | Content security for inbound email |
| `tools/memory_indexer.py` (`memory.sh`) | Semantic memory with Memvid + SQLite |
| `tools/file_indexer.py` (`files.sh`) | Multi-location file discovery and search |
| `tools/heic-convert.sh` | Apple HEIC to JPEG conversion |
| `tools/memory-integrity-check.sh` | Detect unauthorized modification of instructions, brain files, skills |
| `tools/session-start.sh`, `tools/session-end.sh` | Session hooks (wired for Claude Code; runnable from any harness) |

## Skills

| Skill | Purpose |
|-------|---------|
| `file-processing` | Document classification, organization, indexing |
| `mail-handler` | Safe email interaction rules and trust model |
| `pa-memory-delegation` | User memory management (facts, events, learnings) |

Skills live in `skills/<name>/SKILL.md`. Claude Code discovers them through the `.claude/skills` symlink; other harnesses read them by path from `AGENTS.md`.

## Configuration

All configuration lives in `noto.yaml`. See `noto.yaml.example` for all options, including the `llm:` and `learning:` sections.

The single required environment variable is `NOTO_HOME`, pointing to your agent instance directory. `NOTO_LLM_BACKEND` (and friends) override the model backend for a one-off run.

## Security

noto includes defense-in-depth for AI assistants:

- **Prompt injection scanning** — 34 patterns detected in inbound email
- **Trust model** — Operator (verified sender) vs. external content separation
- **Email authentication** — SPF/DKIM/DMARC verification
- **Content wrapping** — External content tagged as data-only, never executed
- **Attachment risk assessment** — Dangerous file types blocked
- **File integrity monitoring** — SHA256 checksums on instructions, brain files, and skills
- **Operator-gated learning** — the agent never edits its own instructions; lessons take effect only after approval
- **Sandboxed background calls** — CLI-backed model calls run in an empty scratch directory with tools disabled

## Requirements

- A coding-agent harness: [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Codex CLI](https://github.com/openai/codex), [Gemini CLI](https://github.com/google-gemini/gemini-cli), or any that reads `AGENTS.md`
- Python 3.10+ and `uv` (recommended) or `pip`
- `requirements.txt`: `memvid-sdk`, `pyyaml`, `pillow-heif` (installed by `setup.sh`). `tools/llm.py`, `tools/learn.py`, and the sanitizer are stdlib-only.

## Development

```bash
uv run --no-project --with pytest --with pyyaml pytest -q tests/
```

## Provenance & License

MIT — see [LICENSE](LICENSE).

noto began as a fork of [23blocks-OS/lolabot](https://github.com/23blocks-OS/lolabot) (MIT, © 2026 23blocks Inc.) and has since been rebranded and hardened for FluidMind's agent fleet. Thanks to the lolabot authors for the original scaffold. The learning loop's operator-gated synthesis comes from FluidMind's noto-platform chassis; the "corrections are first-class learning signals, patch the skill that was in play" ideas are borrowed from [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s session-review prompts.
