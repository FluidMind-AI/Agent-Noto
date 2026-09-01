# Any LLM, any harness

noto is markdown instructions + Python CLIs + `SKILL.md` skills. None of
that is tied to one model or one coding agent. Two things make that true in
practice.

## 1. AGENTS.md is the instruction file

`setup.sh` generates **`AGENTS.md`** and creates `CLAUDE.md` and
`GEMINI.md` as symlinks to it. One source of truth, read natively by:

| Harness | Reads | Skills | Session hooks |
|---------|-------|--------|---------------|
| Claude Code | `CLAUDE.md` → AGENTS.md | `.claude/skills` → `skills/` (slash commands) | `.claude/settings.json` (SessionStart brief, SessionEnd transcript mining) |
| Codex CLI | `AGENTS.md` | by path (`skills/<name>/SKILL.md`, referenced from AGENTS.md) | none — use the nightly job |
| Gemini CLI | `GEMINI.md` → AGENTS.md | by path | none — use the nightly job |
| OpenCode, Cursor, Aider, … | `AGENTS.md` | by path | none — use the nightly job |
| Hermes Agent | its own config; point it at the instance dir and paste AGENTS.md as the system prompt | its own `skills/` (same SKILL.md format) | its own |

The only harness-specific artefact is the small Claude Code adapter in
`.claude/`. Delete it and nothing else changes.

## 2. One chokepoint for background model calls

The interactive loop belongs to the harness. But two jobs run *outside* any
session and need a model: the nightly learning pass and transcript feedback
extraction. Both call `tools/llm.py::complete()` — the only place noto
talks to a model. Backend is config, not code:

```yaml
llm:
  backend: "auto"     # auto | claude-cli | codex-cli | gemini-cli | anthropic | openai
  model: ""
  base_url: ""
  api_key_env: ""
  timeout_seconds: 180
```

| Backend | Uses | Needs |
|---------|------|-------|
| `claude-cli` | `claude -p` | Claude Code installed and logged in (subscription; no API key) |
| `codex-cli` | `codex exec` | Codex CLI installed and logged in |
| `gemini-cli` | `gemini -p` | Gemini CLI installed and logged in |
| `anthropic` | Messages API over HTTPS | `ANTHROPIC_API_KEY` (or `api_key_env`); default model `claude-opus-5` |
| `openai` | any `/chat/completions` endpoint | `base_url` + `model`; key optional for local servers |

`auto` picks the first that is available in that order. CLI backends run in
an empty scratch directory with tools disabled, so a background call can
never read instance files or execute anything.

Examples:

```yaml
# Local, free, private — Ollama
llm: { backend: openai, base_url: "http://localhost:11434/v1", model: "qwen2.5:7b" }

# LM Studio
llm: { backend: openai, base_url: "http://localhost:1234/v1", model: "local-model" }

# OpenRouter
llm: { backend: openai, base_url: "https://openrouter.ai/api/v1", model: "anthropic/claude-sonnet-4.6", api_key_env: "OPENROUTER_API_KEY" }

# OpenAI
llm: { backend: openai, base_url: "https://api.openai.com/v1", model: "gpt-5" }

# Anthropic API directly
llm: { backend: anthropic, model: "claude-opus-5" }
```

Check and test:

```bash
python tools/llm.py backends     # configured vs detected
python tools/llm.py selftest     # one round-trip
NOTO_LLM_BACKEND=codex-cli python tools/llm.py selftest   # env overrides for a one-off
```

Environment overrides: `NOTO_LLM_BACKEND`, `NOTO_LLM_MODEL`,
`NOTO_LLM_BASE_URL`, `NOTO_LLM_API_KEY_ENV`, `NOTO_LLM_TIMEOUT`.

## What stays out on purpose

No agent loop, no multi-provider SDK, no gateway/messaging layer, no tool
registry. Every harness already ships those. noto adds only what harnesses
do not: the memory, the security layer, the task system, and the learning
loop — and keeps each one reachable from a shell.
