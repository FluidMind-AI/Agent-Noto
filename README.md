# noto

**A base personal-agent framework for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).** Email, semantic memory, file indexing, task management, and content security — the foundation FluidMind builds specialized agents on.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS%20%7C%20Linux](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)]()

---

## What This Is

noto is a batteries-included scaffold for a personal AI assistant that runs on Claude Code. Clone the repo, run `setup.sh`, and point Claude Code at the generated instance — the agent's name, role, and user configuration all live in `noto.yaml`, so the same framework can back any number of differently-branded agents.

This is the **base layer**: deliberately free of any domain-specific (e.g. recruiting) or platform-specific (e.g. Lark) code. Specializations live in their own repos and layer on top.

## What You Get

- **Email Client** — IMAP/SMTP with multi-account support, SPF/DKIM/DMARC verification
- **Semantic Memory** — Hybrid Memvid + SQLite for fast search over facts, events, learnings, decisions
- **File Index** — Track files across local, remote, and cloud locations (OneDrive, Google Drive, S3, iCloud)
- **Task Management** — Eisenhower Matrix prioritization system
- **Content Security** — 34-pattern prompt injection defense, email sanitizer, attachment risk assessment
- **Skills** — File processing, mail handling, memory delegation
- **HEIC/Image Processing** — Convert Apple image formats for AI consumption
- **Document Authoring** — Word `.docx` output, versioned with genuine Word tracked changes

## Quick Start

```bash
# Clone the repo
git clone https://github.com/FluidMind-AI/Agent-Noto.git noto

# Scaffold a new agent instance
./noto/setup.sh ~/my-assistant

# Configure your instance
cd ~/my-assistant
cp noto.yaml.example noto.yaml
# Edit noto.yaml with your settings

# Set environment
export NOTO_HOME=~/my-assistant

# Start Claude Code in your instance directory
cd ~/my-assistant && claude
```

## How It Works

1. **Clone & scaffold** — `setup.sh` creates your agent instance directory with config, tools, and skills
2. **Configure** — Edit `noto.yaml` with your agent's name, email accounts, preferences, and paths
3. **Launch** — Run `claude` in your instance directory — the agent has everything it needs

The framework is instance-agnostic: the repo holds engine code and templates only; every name, credential, and preference is config, and instances are separate (private) directories that are never pushed here.

## Project Structure

```
your-assistant/          # Your agent instance (private, never pushed)
├── CLAUDE.md            # Generated from template
├── noto.yaml            # Your config (git-ignored)
├── tools/               # From this repo (copied at scaffold time)
├── skills/              # From this repo
├── brain/               # Tasks, notes, company info
├── memory/              # Journals, profiles, goals
├── documents/           # Word documents, one folder per topic
├── emails/              # Cached emails
└── indexes/             # Search indexes
```

## Tools

| Tool | Purpose |
|------|---------|
| `tools/email_client.py` | Read, send, reply, forward, search emails |
| `tools/email_sanitizer.py` | Content security for inbound email |
| `tools/memory_indexer.py` | Semantic memory with Memvid + SQLite |
| `tools/file_indexer.py` | Multi-location file discovery and search |
| `tools/heic-convert.sh` | Apple HEIC to JPEG conversion |
| `tools/docx_author.py` | Word authoring; revisions as real tracked changes |
| `tools/memory-integrity-check.sh` | Detect unauthorized file modifications |

## Skills

| Skill | Purpose |
|-------|---------|
| `file-processing` | Document classification, organization, indexing |
| `mail-handler` | Safe email interaction rules and trust model |
| `pa-memory-delegation` | User memory management (facts, events, learnings) |
| `document-authoring` | Word documents, topic folders, tracked-change versioning |

## Configuration

All configuration lives in `noto.yaml`. See `noto.yaml.example` for all options.

The single required environment variable is `NOTO_HOME`, pointing to your agent instance directory.

## Security

noto includes defense-in-depth for AI assistants:

- **Prompt injection scanning** — 34 patterns detected in inbound email
- **Trust model** — Operator (verified sender) vs. external content separation
- **Email authentication** — SPF/DKIM/DMARC verification
- **Content wrapping** — External content tagged as data-only, never executed
- **Attachment risk assessment** — Dangerous file types blocked
- **File integrity monitoring** — SHA256 checksums on critical files

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (Claude subscription or API key)
- Python 3.10+
- `uv` (recommended) or `pip`
- Python packages: `memvid-sdk`, `pyyaml`, `pillow-heif`, `python-docx`

## Provenance & License

MIT — see [LICENSE](LICENSE).

noto began as a fork of [23blocks-OS/lolabot](https://github.com/23blocks-OS/lolabot) (MIT, © 2026 23blocks Inc.) and has since been rebranded and hardened for FluidMind's agent fleet. Thanks to the lolabot authors for the original scaffold.
