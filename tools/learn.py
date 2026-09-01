#!/usr/bin/env python3
"""
Learning loop — how noto gets better without anyone hand-editing prompts.

Raw feedback is EVIDENCE, not a rule. The loop is:

  1. CAPTURE     feedback rows land in indexes/learning.db
                 - the agent records a correction the moment the user makes one
                   (`learn.py feedback add "..."`) — works under ANY harness
                 - transcripts can be mined afterwards (`learn.py extract`),
                   cheap regex cues first, the LLM only when cues fire
  2. SYNTHESIZE  the model reads the not-yet-synthesized feedback and derives
                 LESSONS, each with a scope, a reasoning trail and the feedback
                 ids that support it. Every feedback item lands in some lesson
                 row — including "one-off, no rule derivable" — so nothing is
                 silently dropped. (`learn.py synthesize`, or nightly `run`)
  3. REVIEW      global / skill lessons wait as `pending` until the operator
                 approves or rejects them. One-offs are auto-parked as
                 `deferred`. Nothing shapes behaviour until approved.
  4. APPLY       approved global lessons are rendered into brain/lessons.md,
                 which the agent reads at session start. Approved skill-scoped
                 lessons are appended to that skill's SKILL.md under a
                 "Learned" section — the skill that was in play is the one
                 that grows.

Design lineage: the operator-gated synthesis comes from FluidMind's
production noto-platform chassis; the "patch the loaded skill first" and
"corrections are first-class learning signals" ideas come from Hermes
Agent's session-review prompts. Everything runs through tools/llm.py, so it
works with whichever model backend the instance is configured for.

CLI (or via tools/learn.sh):
  feedback add "text" [--skill NAME] [--context "..."] [--source agent|operator]
  feedback list [--all]
  extract --transcript PATH | --text-file PATH [--dry-run]
  synthesize
  lessons [--pending|--active|--all]
  approve L3 [L4 ...]     reject L5 [--reason "..."]
  lesson add "text" [--scope global|skill:NAME]     (operator shortcut, pre-approved)
  apply                   render
  run [--no-llm]          nightly: synthesize -> apply -> memory promote/stale -> integrity -> render
  status [--brief]
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, get_path, get_home  # noqa: E402
import llm  # noqa: E402

SCOPE_PENDING = ("global",)          # plus any "skill:<name>"
SCOPE_DEFERRED = ("one_off", "insufficient_evidence", "already_covered")

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'agent',
    skill TEXT,
    context TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    lesson_id INTEGER,
    content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lesson_text TEXT NOT NULL,
    scope TEXT NOT NULL,
    reasoning TEXT,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    supporting_ids TEXT,
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT
);
"""

# Cheap cues that a user message carries a LASTING correction or preference,
# not a one-off task instruction. Deliberately conservative — a miss costs
# nothing (the agent can still record feedback explicitly); a false positive
# costs one LLM call.
FEEDBACK_CUES = [
    r"\b(stop|quit) (doing|adding|using|saying|putting|writing|including|explaining|asking)\b",
    r"\bdon'?t (ever |always |keep )?(do|add|use|say|put|write|include|send|format|explain|ask|start|end|call|make)\b",
    r"\b(never|always) (do|add|use|say|put|write|include|send|format|explain|ask|start|end|reply|respond|call|make|keep)\b",
    r"\bfrom now on\b",
    r"\bin (the )?future\b",
    r"\bnext time\b",
    r"\bgoing forward\b",
    r"\bremember (this|that|to)\b",
    r"\bkeep in mind\b",
    r"\btoo (verbose|long|short|wordy|formal|casual|detailed|brief|chatty|slow)\b",
    r"\b(not|isn'?t|wasn'?t|that'?s not) what i (meant|asked|wanted|said)\b",
    r"\bi (prefer|'d prefer|would prefer|like it when|don'?t like|hate) \b",
    r"\bi'?d rather\b",
    r"\byou (keep|always|never|tend to|constantly|still)\b",
    r"\bwhy (do|are|did) you (keep|always|still)\b",
    r"\bjust (give|tell|show|send) me\b",
    r"\bno need to\b",
    r"\bplease (don'?t|stop|always|never)\b",
    r"\bthat'?s (wrong|incorrect|not right|not how)\b",
    r"^\s*feedback\s*:",
]
_CUE_RES = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in FEEDBACK_CUES]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:16]


def _fid(n: int) -> str:
    return f"F{n}"


def _lid(n: int) -> str:
    return f"L{n}"


def _parse_id(raw: str, prefix: str) -> int:
    s = raw.strip().upper()
    if s.startswith(prefix):
        s = s[len(prefix):]
    if not s.isdigit():
        raise SystemExit(f"bad id {raw!r}; expected e.g. {prefix}3")
    return int(s)


def db() -> sqlite3.Connection:
    path = get_path("learning_db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def agent_name() -> str:
    return (load_config().get("agent") or {}).get("name") or "noto"


def skills_dir() -> str:
    return get_path("skills_dir")


def list_skills() -> List[str]:
    root = skills_dir()
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "SKILL.md")))


def looks_like_feedback(text: str) -> List[str]:
    """Return the cue patterns that fire on `text` (empty list = no signal)."""
    return [rx.pattern for rx in _CUE_RES if rx.search(text)]


def _user_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p)
    return ""


def parse_transcript(path: str) -> List[str]:
    """User messages from a transcript.

    Understands Claude Code session JSONL (and any JSONL whose rows carry a
    role/content pair, top-level or under `message`). Anything else is
    treated as plain text split on blank lines.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    messages: List[str] = []
    jsonl = True
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            jsonl = False
            break
        if not isinstance(obj, dict):
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = msg.get("role") or obj.get("type")
        if role != "user":
            continue
        text = _user_text_from_content(msg.get("content")).strip()
        # Skip harness-injected blocks (command output, system reminders, tool results).
        if not text or text.startswith("<"):
            continue
        messages.append(text)
    if jsonl:
        return messages
    return [chunk.strip() for chunk in re.split(r"\n\s*\n", raw) if chunk.strip()]


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def add_feedback(text: str, *, source: str = "agent", skill: Optional[str] = None,
                 context: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> Tuple[int, bool]:
    """Insert a feedback row. Returns (id, created). Duplicates return the existing id."""
    own = conn is None
    conn = conn or db()
    text = text.strip()
    if not text:
        raise SystemExit("feedback text is empty")
    h = _hash(text)
    row = conn.execute("SELECT id FROM feedback WHERE content_hash = ?", (h,)).fetchone()
    if row:
        if own:
            conn.close()
        return int(row["id"]), False
    cur = conn.execute(
        "INSERT INTO feedback (created_at, text, source, skill, context, status, content_hash) "
        "VALUES (?, ?, ?, ?, ?, 'new', ?)",
        (_now(), text, source, skill or None, context or None, h),
    )
    conn.commit()
    fid = int(cur.lastrowid)
    if own:
        conn.close()
    return fid, True


def cmd_feedback(args: argparse.Namespace) -> None:
    if args.feedback_command == "add":
        fid, created = add_feedback(args.text, source=args.source, skill=args.skill, context=args.context)
        if created:
            print(f"recorded {_fid(fid)} — it will be synthesized into a lesson on the next `learn.py run`")
        else:
            print(f"already recorded as {_fid(fid)}")
        return
    conn = db()
    where = "" if args.all else "WHERE status = 'new'"
    rows = conn.execute(f"SELECT * FROM feedback {where} ORDER BY id").fetchall()
    if not rows:
        print("no feedback" + ("" if args.all else " waiting for synthesis"))
        return
    for r in rows:
        tag = f" [skill:{r['skill']}]" if r["skill"] else ""
        lesson = f" -> {_lid(r['lesson_id'])}" if r["lesson_id"] else ""
        print(f"{_fid(r['id'])} {r['created_at'][:10]} ({r['source']}{tag}) {r['status']}{lesson}: {r['text']}")
        if r["context"]:
            print(f"    context: {r['context']}")
    conn.close()


# ---------------------------------------------------------------------------
# Extraction from transcripts
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = """You are the learning module of a personal AI assistant named {agent}.
You read the USER's messages from one session and pull out LASTING feedback:
corrections about style, tone, format, verbosity, workflow, sequence of steps,
tool usage, or explicit "remember this" preferences — anything a future session
should already know.

Ignore one-off task instructions ("summarize this file", "reply to Bob") and
anything that only makes sense for today's task. Do not invent feedback that is
not clearly in the text. Quote the user's intent faithfully; one item per
distinct point.

Reply with JSON only:
{{"feedback": [{{"text": "<the correction, as an instruction to the assistant>",
                "skill": <one of {skills} or null>,
                "context": "<5-15 words on the situation>"}}]}}
If there is nothing lasting, reply {{"feedback": []}}."""


def cmd_extract(args: argparse.Namespace) -> None:
    if args.transcript:
        messages = parse_transcript(args.transcript)
        origin = os.path.basename(args.transcript)
    else:
        messages = parse_transcript(args.text_file)
        origin = os.path.basename(args.text_file)
    candidates = [(i, m) for i, m in enumerate(messages) if looks_like_feedback(m)]
    if not candidates:
        if not args.quiet:
            print(f"{origin}: {len(messages)} user messages, no feedback cues")
        return
    if args.dry_run:
        print(f"{origin}: {len(candidates)} of {len(messages)} user messages carry feedback cues:")
        for _, m in candidates:
            print(f"  - {m[:200]}")
        return

    skills = list_skills()
    numbered = "\n\n".join(f"[{n}] {m[:2000]}" for n, (_, m) in enumerate(candidates, 1))
    reply = llm.complete(
        f"USER MESSAGES FROM ONE SESSION (only the ones that look like feedback):\n\n{numbered}",
        system=EXTRACT_SYSTEM.format(agent=agent_name(), skills=json.dumps(skills)),
    )
    data = llm.extract_json(reply)
    items = data.get("feedback") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SystemExit("extraction reply was not {\"feedback\": [...]}")

    conn = db()
    created = 0
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        skill = item.get("skill")
        if skill not in skills:
            skill = None
        _, is_new = add_feedback(str(item["text"]), source="transcript", skill=skill,
                                 context=f"{origin}: {item.get('context', '')}".strip(": "), conn=conn)
        created += int(is_new)
    conn.close()
    if not args.quiet:
        print(f"{origin}: {len(candidates)} candidate messages -> {created} new feedback rows")


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

SYNTH_SYSTEM = """You are the learning module of a personal AI assistant named {agent}.

Raw feedback is EVIDENCE, not a rule. Some of it is a one-off comment about
one specific task; some of it is "that's how things should always be done".
Your job is to read the accumulated feedback and derive LESSONS the operator
can approve. Nothing you output takes effect until a human approves it.

For each lesson give:
  lesson_text  — the proposed rule, imperative, one or two sentences, written
                 so it can be injected verbatim into the assistant's standing
                 instructions. No names of specific documents or dates.
  scope        — exactly one of:
                 "global"                 applies to all work
                 "skill:<name>"           applies to one skill (name from the list below)
                 "one_off"                specific to a single task, no rule derivable
                 "insufficient_evidence"  might be a pattern, needs more repeats
                 "already_covered"        an ACTIVE lesson below already says this
  reasoning    — WHY you concluded this, one or two sentences (audit trail)
  supporting_feedback_ids — the numeric ids of the feedback items that fed it

Rules:
  - Every feedback id below must appear in exactly one lesson. Group items
    that express the same point; never drop one.
  - Prefer patching the skill that was in play: if feedback is tagged with a
    skill or clearly concerns one, scope it "skill:<name>".
  - Two independent items saying the same thing is strong evidence for a
    global or skill lesson; a single item can still become one if it is an
    explicit instruction ("from now on", "always", "never", "remember").
  - Do not restate an active lesson; mark it "already_covered" and name the
    lesson id in reasoning.

Available skills: {skills}

Reply with JSON only:
{{"lessons": [{{"lesson_text": "...", "scope": "...", "reasoning": "...",
               "supporting_feedback_ids": [1, 2]}}]}}"""


def _lesson_status_for(scope: str) -> str:
    if scope == "global" or scope.startswith("skill:"):
        return "pending"
    return "deferred"


def _normalize_scope(scope: Any, skills: List[str]) -> str:
    s = str(scope or "").strip()
    if s in SCOPE_PENDING or s in SCOPE_DEFERRED:
        return s
    if s.startswith("skill:"):
        name = s[len("skill:"):].strip()
        return f"skill:{name}" if name in skills else "global"
    return "insufficient_evidence"


def synthesize(conn: sqlite3.Connection) -> Dict[str, int]:
    new_rows = conn.execute("SELECT * FROM feedback WHERE status = 'new' ORDER BY id").fetchall()
    if not new_rows:
        return {"feedback": 0, "lessons": 0, "pending": 0}

    skills = list_skills()
    active = conn.execute(
        "SELECT id, scope, lesson_text FROM lessons WHERE status IN ('approved','applied','pending') ORDER BY id"
    ).fetchall()
    active_block = "\n".join(f"  {_lid(r['id'])} [{r['scope']}] {r['lesson_text']}" for r in active) or "  (none yet)"
    feedback_block = "\n".join(
        f"  id={r['id']} ({r['source']}{', skill:' + r['skill'] if r['skill'] else ''}"
        f"{', ' + r['context'] if r['context'] else ''}) {r['text']}"
        for r in new_rows
    )
    prompt = f"ACTIVE LESSONS (already in force or awaiting review):\n{active_block}\n\nNEW FEEDBACK:\n{feedback_block}"
    reply = llm.complete(prompt, system=SYNTH_SYSTEM.format(agent=agent_name(), skills=json.dumps(skills)))
    data = llm.extract_json(reply)
    proposed = data.get("lessons") if isinstance(data, dict) else None
    if not isinstance(proposed, list):
        raise SystemExit("synthesis reply was not {\"lessons\": [...]}")

    valid_ids = {int(r["id"]) for r in new_rows}
    covered: set = set()
    created = 0
    pending = 0
    now = _now()

    def insert(text: str, scope: str, reasoning: str, ids: List[int]) -> int:
        nonlocal created, pending
        status = _lesson_status_for(scope)
        cur = conn.execute(
            "INSERT INTO lessons (created_at, updated_at, lesson_text, scope, reasoning, status, source, supporting_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, 'synthesis', ?)",
            (now, now, text, scope, reasoning, status, json.dumps(sorted(ids))),
        )
        lid = int(cur.lastrowid)
        for fid in ids:
            conn.execute("UPDATE feedback SET status = 'synthesized', lesson_id = ? WHERE id = ?", (lid, fid))
        created += 1
        pending += int(status == "pending")
        return lid

    for item in proposed:
        if not isinstance(item, dict):
            continue
        text = str(item.get("lesson_text", "")).strip()
        ids = [int(i) for i in item.get("supporting_feedback_ids", []) if str(i).isdigit() and int(i) in valid_ids]
        ids = [i for i in ids if i not in covered]
        if not text or not ids:
            continue
        scope = _normalize_scope(item.get("scope"), skills)
        insert(text, scope, str(item.get("reasoning", "")).strip(), ids)
        covered.update(ids)

    # Nothing is silently dropped: feedback the model did not place gets its own row.
    for fid in sorted(valid_ids - covered):
        row = conn.execute("SELECT text FROM feedback WHERE id = ?", (fid,)).fetchone()
        insert(row["text"], "insufficient_evidence",
               "Not placed by synthesis; kept so the operator can see it.", [fid])

    conn.execute("INSERT INTO runs (ran_at, kind, summary) VALUES (?, 'synthesize', ?)",
                 (now, f"{len(new_rows)} feedback -> {created} lessons ({pending} pending)"))
    conn.commit()
    return {"feedback": len(new_rows), "lessons": created, "pending": pending}


def cmd_synthesize(args: argparse.Namespace) -> None:
    conn = db()
    stats = synthesize(conn)
    render(conn)
    conn.close()
    if stats["feedback"] == 0:
        print("nothing new to synthesize")
    else:
        print(f"{stats['feedback']} feedback -> {stats['lessons']} lessons, {stats['pending']} pending review "
              f"(tools/learn.sh lessons --pending)")


# ---------------------------------------------------------------------------
# Lessons: list / approve / reject / manual add / apply
# ---------------------------------------------------------------------------

def _print_lesson(r: sqlite3.Row, verbose: bool = True) -> None:
    ids = ", ".join(_fid(i) for i in json.loads(r["supporting_ids"] or "[]"))
    print(f"{_lid(r['id'])} [{r['scope']}] {r['status']} — {r['lesson_text']}")
    if verbose:
        if r["reasoning"]:
            print(f"    why: {r['reasoning']}")
        if ids:
            print(f"    evidence: {ids}")
        if r["review_note"]:
            print(f"    note: {r['review_note']}")


def cmd_lessons(args: argparse.Namespace) -> None:
    conn = db()
    if args.all:
        where = ""
    elif args.active:
        where = "WHERE status IN ('approved','applied')"
    else:
        where = "WHERE status = 'pending'"
    rows = conn.execute(f"SELECT * FROM lessons {where} ORDER BY id").fetchall()
    if not rows:
        print("no lessons" + (" pending review" if not (args.all or args.active) else ""))
    for r in rows:
        _print_lesson(r)
    conn.close()


def cmd_approve(args: argparse.Namespace) -> None:
    conn = db()
    for raw in args.ids:
        lid = _parse_id(raw, "L")
        row = conn.execute("SELECT status FROM lessons WHERE id = ?", (lid,)).fetchone()
        if not row:
            print(f"{_lid(lid)}: not found")
            continue
        conn.execute("UPDATE lessons SET status = 'approved', updated_at = ?, review_note = ? WHERE id = ?",
                     (_now(), args.note, lid))
        print(f"{_lid(lid)}: approved")
    conn.commit()
    applied = apply_lessons(conn)
    render(conn)
    conn.close()
    if applied:
        print(f"applied {applied} skill-scoped lesson(s) to SKILL.md")


def cmd_reject(args: argparse.Namespace) -> None:
    conn = db()
    for raw in args.ids:
        lid = _parse_id(raw, "L")
        if not conn.execute("SELECT 1 FROM lessons WHERE id = ?", (lid,)).fetchone():
            print(f"{_lid(lid)}: not found")
            continue
        conn.execute("UPDATE lessons SET status = 'rejected', updated_at = ?, review_note = ? WHERE id = ?",
                     (_now(), args.reason, lid))
        print(f"{_lid(lid)}: rejected")
    conn.commit()
    render(conn)
    conn.close()


def cmd_lesson_add(args: argparse.Namespace) -> None:
    """Operator shortcut: a lesson written by the human is approved on arrival."""
    skills = list_skills()
    scope = _normalize_scope(args.scope, skills)
    if scope not in SCOPE_PENDING and not scope.startswith("skill:"):
        raise SystemExit(f"scope must be global or skill:<name> (skills: {', '.join(skills) or 'none'})")
    conn = db()
    now = _now()
    cur = conn.execute(
        "INSERT INTO lessons (created_at, updated_at, lesson_text, scope, reasoning, status, source, supporting_ids) "
        "VALUES (?, ?, ?, ?, 'Written directly by the operator.', 'approved', 'manual', '[]')",
        (now, now, args.text.strip(), scope),
    )
    conn.commit()
    lid = int(cur.lastrowid)
    apply_lessons(conn)
    render(conn)
    conn.close()
    print(f"{_lid(lid)} [{scope}] approved")


LEARNED_HEADER = "## Learned (operator-approved)"


def apply_lessons(conn: sqlite3.Connection) -> int:
    """Append approved skill-scoped lessons to their SKILL.md. Returns count applied."""
    rows = conn.execute(
        "SELECT * FROM lessons WHERE status = 'approved' AND scope LIKE 'skill:%' ORDER BY id"
    ).fetchall()
    applied = 0
    for r in rows:
        name = r["scope"][len("skill:"):]
        path = os.path.join(skills_dir(), name, "SKILL.md")
        if not os.path.isfile(path):
            print(f"{_lid(r['id'])}: skills/{name}/SKILL.md not found; left as approved")
            continue
        with open(path, encoding="utf-8") as f:
            body = f.read()
        line = f"- ({_lid(r['id'])}, {_today()}) {r['lesson_text']}"
        if LEARNED_HEADER not in body:
            body = body.rstrip("\n") + f"\n\n{LEARNED_HEADER}\n\nRules added by the learning loop after operator approval. Managed by tools/learn.py.\n\n{line}\n"
        else:
            body = body.rstrip("\n") + f"\n{line}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        conn.execute("UPDATE lessons SET status = 'applied', updated_at = ? WHERE id = ?", (_now(), r["id"]))
        applied += 1
    conn.commit()
    return applied


def cmd_apply(args: argparse.Namespace) -> None:
    conn = db()
    n = apply_lessons(conn)
    render(conn)
    conn.close()
    print(f"applied {n} lesson(s)")


# ---------------------------------------------------------------------------
# Rendering brain/lessons.md
# ---------------------------------------------------------------------------

def render(conn: sqlite3.Connection) -> str:
    path = get_path("lessons_file")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = conn.execute("SELECT * FROM lessons ORDER BY id").fetchall()
    active = [r for r in rows if r["status"] in ("approved", "applied")]
    pending = [r for r in rows if r["status"] == "pending"]
    deferred = [r for r in rows if r["status"] == "deferred"]
    rejected = [r for r in rows if r["status"] == "rejected"]

    def ids_of(r: sqlite3.Row) -> str:
        return ", ".join(_fid(i) for i in json.loads(r["supporting_ids"] or "[]")) or "operator"

    out = [
        f"# Lessons — {agent_name()}",
        "",
        "Generated by `tools/learn.py`; do not edit by hand.",
        "Active lessons are standing instructions: follow them in every session.",
        "Review pending ones with `tools/learn.sh lessons --pending`, then",
        "`tools/learn.sh approve L3` or `tools/learn.sh reject L3 --reason \"...\"`.",
        "",
        f"_Rendered {_now()} — {len(active)} active, {len(pending)} pending, {len(deferred)} deferred._",
        "",
        "## Active lessons",
        "",
    ]
    if active:
        for r in active:
            where = f"{r['scope']} → written into skills/{r['scope'][6:]}/SKILL.md" if r["status"] == "applied" else r["scope"]
            out.append(f"- **{_lid(r['id'])}** [{where}] {r['lesson_text']}")
    else:
        out.append("_None yet. Record feedback with `tools/learn.sh feedback add \"...\"` and let the nightly run propose lessons._")
    out += ["", "## Pending review", ""]
    if pending:
        for r in pending:
            out.append(f"- **{_lid(r['id'])}** [{r['scope']}] {r['lesson_text']}")
            if r["reasoning"]:
                out.append(f"  - why: {r['reasoning']}")
            out.append(f"  - evidence: {ids_of(r)}")
    else:
        out.append("_Nothing waiting._")
    out += ["", "## Deferred (one-off or not enough evidence)", ""]
    if deferred:
        for r in deferred[-20:]:
            out.append(f"- {_lid(r['id'])} [{r['scope']}] {r['lesson_text']} — {r['reasoning'] or ''}".rstrip(" —"))
    else:
        out.append("_None._")
    if rejected:
        out += ["", "## Rejected", ""]
        for r in rejected[-20:]:
            note = f" — {r['review_note']}" if r["review_note"] else ""
            out.append(f"- {_lid(r['id'])} {r['lesson_text']}{note}")
    text = "\n".join(out) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def cmd_render(args: argparse.Namespace) -> None:
    conn = db()
    print(f"wrote {render(conn)}")
    conn.close()


# ---------------------------------------------------------------------------
# Nightly run
# ---------------------------------------------------------------------------

def _python() -> str:
    venv = os.path.join(get_path("venv"), "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


def _memory_available() -> bool:
    try:
        r = subprocess.run([_python(), "-c", "import memvid_sdk"], capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _run_tool(cmd: List[str], timeout: int = 900) -> Tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=get_home(),
                           env={**os.environ, "NOTO_HOME": get_home()})
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def cmd_run(args: argparse.Namespace) -> None:
    home = get_home()
    conn = db()
    steps: List[str] = []

    # 1. synthesize
    if args.no_llm:
        steps.append("synthesize: skipped (--no-llm)")
    else:
        try:
            s = synthesize(conn)
            steps.append(f"synthesize: {s['feedback']} feedback -> {s['lessons']} lessons ({s['pending']} pending)")
        except (llm.LLMError, SystemExit) as e:
            steps.append(f"synthesize: FAILED ({e})")

    # 2. apply already-approved lessons
    steps.append(f"apply: {apply_lessons(conn)} skill lesson(s)")

    # 3-4. memory maintenance
    if _memory_available():
        code, out = _run_tool([_python(), os.path.join(home, "tools", "memory_indexer.py"), "promote"])
        steps.append("memory promote: " + ("ok" if code == 0 else "FAILED") + (f" — {out.splitlines()[-1]}" if out else ""))
        code, out = _run_tool([_python(), os.path.join(home, "tools", "memory_indexer.py"), "stale"])
        stale_n = len([ln for ln in out.splitlines() if ln.strip().startswith(("-", "•", "📌", "📅", "💡", "⚖", "📝", "👤", "🎯", "⭐", "🔄", "🧠"))])
        steps.append("memory stale: " + ("ok" if code == 0 else "FAILED") + (f" — {stale_n} due for review" if code == 0 else ""))
    else:
        steps.append("memory promote/stale: skipped (memvid-sdk not installed)")

    # 5. integrity
    checksums = get_path("integrity_checksums")
    script = os.path.join(home, "tools", "memory-integrity-check.sh")
    if os.path.exists(checksums) and os.path.exists(script):
        code, out = _run_tool(["bash", script, "check"])
        steps.append("integrity: " + ("ok" if code == 0 else "MODIFIED FILES — see tools/memory-integrity-check.sh check"))
    else:
        steps.append("integrity: skipped (run tools/memory-integrity-check.sh init once)")

    # 6. render + log
    render(conn)
    summary = " · ".join(steps)
    conn.execute("INSERT INTO runs (ran_at, kind, summary) VALUES (?, 'run', ?)", (_now(), summary))
    conn.commit()
    conn.close()
    log = get_path("learning_log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    new_file = not os.path.exists(log)
    with open(log, "a", encoding="utf-8") as f:
        if new_file:
            f.write(f"# Learning log — {agent_name()}\n\nOne line per nightly run (tools/learn.py run).\n\n")
        f.write(f"- {_now()} — {summary}\n")
    print("\n".join(steps))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    conn = db()
    counts = {k: 0 for k in ("new_feedback", "pending", "active", "deferred")}
    counts["new_feedback"] = conn.execute("SELECT COUNT(*) FROM feedback WHERE status = 'new'").fetchone()[0]
    counts["pending"] = conn.execute("SELECT COUNT(*) FROM lessons WHERE status = 'pending'").fetchone()[0]
    counts["active"] = conn.execute("SELECT COUNT(*) FROM lessons WHERE status IN ('approved','applied')").fetchone()[0]
    counts["deferred"] = conn.execute("SELECT COUNT(*) FROM lessons WHERE status = 'deferred'").fetchone()[0]
    last = conn.execute("SELECT ran_at, summary FROM runs WHERE kind = 'run' ORDER BY id DESC LIMIT 1").fetchone()
    if args.brief:
        line = (f"{agent_name()} learning: {counts['active']} active lesson(s) in brain/lessons.md, "
                f"{counts['pending']} pending review, {counts['new_feedback']} feedback waiting for synthesis")
        if counts["pending"]:
            line += " — review with `tools/learn.sh lessons --pending`"
        print(line)
    else:
        for k, v in counts.items():
            print(f"{k:14} {v}")
        print(f"{'last run':14} {last['ran_at'] + ' — ' + last['summary'] if last else 'never'}")
        print(f"{'lessons file':14} {get_path('lessons_file')}")
        print(f"{'llm backend':14} {llm.llm_config()['backend']}")
    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="noto learning loop")
    sub = parser.add_subparsers(dest="command")

    fb = sub.add_parser("feedback", help="Record or list feedback (evidence)")
    fbsub = fb.add_subparsers(dest="feedback_command")
    fa = fbsub.add_parser("add", help="Record one piece of feedback")
    fa.add_argument("text")
    fa.add_argument("--skill", help="Skill the feedback is about (directory name under skills/)")
    fa.add_argument("--context", help="Short note on the situation")
    fa.add_argument("--source", default="agent", choices=("agent", "operator", "transcript"))
    fl = fbsub.add_parser("list", help="List feedback")
    fl.add_argument("--all", action="store_true", help="Include already-synthesized rows")
    fb.set_defaults(func=cmd_feedback)

    ex = sub.add_parser("extract", help="Mine a transcript for lasting feedback")
    g = ex.add_mutually_exclusive_group(required=True)
    g.add_argument("--transcript", help="Claude Code session .jsonl (or any role/content JSONL)")
    g.add_argument("--text-file", help="Plain-text transcript, user messages separated by blank lines")
    ex.add_argument("--dry-run", action="store_true", help="Show cue hits, do not call the model")
    ex.add_argument("--quiet", action="store_true")
    ex.set_defaults(func=cmd_extract)

    sy = sub.add_parser("synthesize", help="Turn new feedback into lessons (calls the LLM)")
    sy.set_defaults(func=cmd_synthesize)

    ls = sub.add_parser("lessons", help="List lessons (default: pending review)")
    ls.add_argument("--pending", action="store_true")
    ls.add_argument("--active", action="store_true")
    ls.add_argument("--all", action="store_true")
    ls.set_defaults(func=cmd_lessons)

    ap = sub.add_parser("approve", help="Approve lessons (operator)")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--note")
    ap.set_defaults(func=cmd_approve)

    rj = sub.add_parser("reject", help="Reject lessons (operator)")
    rj.add_argument("ids", nargs="+")
    rj.add_argument("--reason")
    rj.set_defaults(func=cmd_reject)

    la = sub.add_parser("lesson", help="Operator shortcuts")
    lasub = la.add_subparsers(dest="lesson_command")
    laa = lasub.add_parser("add", help="Add a pre-approved lesson directly")
    laa.add_argument("text")
    laa.add_argument("--scope", default="global", help="global or skill:<name>")
    laa.set_defaults(func=cmd_lesson_add)

    sub.add_parser("apply", help="Write approved skill lessons into SKILL.md files").set_defaults(func=cmd_apply)
    sub.add_parser("render", help="Rewrite brain/lessons.md from the database").set_defaults(func=cmd_render)

    rn = sub.add_parser("run", help="Nightly pass: synthesize, apply, memory maintenance, integrity, render")
    rn.add_argument("--no-llm", action="store_true", help="Skip synthesis (no model call)")
    rn.set_defaults(func=cmd_run)

    st = sub.add_parser("status", help="Counts and last run")
    st.add_argument("--brief", action="store_true", help="One line, for session-start hooks")
    st.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if not args.command or (args.command == "feedback" and not args.feedback_command) \
            or (args.command == "lesson" and not args.lesson_command):
        parser.print_help()
        return
    try:
        args.func(args)
    except llm.LLMError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
