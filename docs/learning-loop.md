# Learning loop

How a noto instance gets better without anyone hand-editing prompts, and
without the agent quietly rewriting its own instructions.

## The idea in one paragraph

Raw feedback is **evidence, not a rule**. The agent records corrections the
moment they happen. A scheduled pass reads the accumulated feedback and
proposes *lessons*, each with a scope and a reasoning trail. The operator
approves or rejects. Approved lessons become standing instructions: global
ones in `brain/lessons.md` (read at session start), skill ones appended to
that skill's `SKILL.md`. Nothing shapes behaviour until a human said yes.

This is the operator-gated design proven in FluidMind's production
noto-platform chassis, combined with two ideas from Hermes Agent's
session-review prompts: corrections about style/format/workflow are
first-class learning signals, and the skill that was in play is the one
that should grow.

## Four stages

| Stage | What happens | Who / when |
|-------|--------------|------------|
| **Capture** | `tools/learn.sh feedback add "..."` writes a row to `indexes/learning.db`. `learn.py extract --transcript` mines a session transcript: regex cues first, the model only when a cue fires. | The agent, immediately on correction (any harness). Claude Code users also get automatic transcript mining via the SessionEnd hook. |
| **Synthesize** | The model reads new feedback plus the active lessons and returns lessons as JSON: `lesson_text`, `scope`, `reasoning`, `supporting_feedback_ids`. Every feedback id lands in exactly one lesson; anything the model did not place gets an `insufficient_evidence` row so nothing is silently dropped. | `tools/nightly.sh` (cron / launchd), or `tools/learn.sh synthesize` by hand. |
| **Review** | `global` and `skill:<name>` lessons wait as **pending**. `one_off`, `insufficient_evidence`, `already_covered` are parked as **deferred** (visible, no action needed). | The operator: `learn.sh lessons --pending`, `approve L3`, `reject L3 --reason "..."`. |
| **Apply** | Approved global lessons render into `brain/lessons.md`. Approved skill lessons are appended under `## Learned (operator-approved)` in `skills/<name>/SKILL.md` and marked **applied**. | `learn.py` on approve, and on every nightly run. |

Scopes:

- `global` — applies to all work
- `skill:<name>` — applies to one skill; `<name>` is a directory under `skills/`
- `one_off` — specific to a single task, no rule derivable
- `insufficient_evidence` — might be a pattern, needs more repeats
- `already_covered` — an active lesson already says this

## What the nightly run does

`tools/nightly.sh` → `tools/learn.py run`:

1. synthesize new feedback (one model call, skipped when there is nothing new)
2. apply already-approved skill lessons
3. `memory_indexer.py promote` — mature short-term memories move to long-term
4. `memory_indexer.py stale` — count memories due for review
5. `memory-integrity-check.sh check` — if checksums were initialised
6. render `brain/lessons.md`, append one line to `brain/learning-log.md`

Steps 3–4 are skipped cleanly when `memvid-sdk` is not installed.

## Commands

```bash
tools/learn.sh feedback add "Don't open replies with 'I hope this finds you well'" --skill mail-handler
tools/learn.sh feedback list
tools/learn.sh extract --transcript ~/.claude/projects/<proj>/<session>.jsonl --dry-run
tools/learn.sh synthesize
tools/learn.sh lessons --pending        # or --active, --all
tools/learn.sh approve L3 L4
tools/learn.sh reject L5 --reason "one-off"
tools/learn.sh lesson add "Reply in the language the sender used" --scope skill:mail-handler   # operator shortcut, pre-approved
tools/learn.sh status
tools/nightly.sh                        # what the scheduler runs
```

## Files

| Path | Role |
|------|------|
| `indexes/learning.db` | SQLite: `feedback`, `lessons`, `runs` (the source of truth; git-ignored) |
| `brain/lessons.md` | Rendered view: active / pending / deferred / rejected. Read by the agent at session start. Never hand-edited. |
| `brain/learning-log.md` | One line per nightly run |
| `skills/<name>/SKILL.md` | Gains a `## Learned (operator-approved)` section as skill lessons are applied |

The integrity checker deliberately ignores `lessons.md` and
`learning-log.md` (they change every night) but does watch `SKILL.md`
files — after approving a skill lesson, run `tools/memory-integrity-check.sh update`.

## Model calls

Both model calls (extraction, synthesis) go through `tools/llm.py`, so the
loop works with whichever backend `noto.yaml` names — see
[any-llm.md](any-llm.md). Prompts ask for JSON only; `llm.extract_json`
tolerates fences and surrounding prose.
