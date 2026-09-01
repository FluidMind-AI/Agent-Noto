#!/usr/bin/env python3
"""Tests for tools/learn.py — capture, cue detection, transcript parsing,
synthesis (fake LLM), review, apply, render, nightly run.
"""

import json
import os
import sys
from argparse import Namespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

import config  # noqa: E402
import learn  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / "noto.yaml").write_text('agent:\n  name: "Testbot"\nllm:\n  backend: fake\n')
    skill = tmp_path / "skills" / "mail-handler"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: mail-handler\n---\n\n# Mail Handler\n\nBe safe.\n")
    (tmp_path / "skills" / "file-processing").mkdir()
    (tmp_path / "skills" / "file-processing" / "SKILL.md").write_text("---\nname: file-processing\n---\n")
    monkeypatch.setenv("NOTO_HOME", str(tmp_path))
    for var in ("NOTO_LLM_BACKEND", "NOTO_LLM_FAKE_RESPONSE", "NOTO_LLM_FAKE_RESPONSE_FILE"):
        monkeypatch.delenv(var, raising=False)
    config.reset_cache()
    yield tmp_path
    config.reset_cache()


def fake(monkeypatch, payload):
    monkeypatch.setenv("NOTO_LLM_FAKE_RESPONSE", json.dumps(payload))


class TestFeedback:
    def test_add_and_dedupe(self, home):
        fid, created = learn.add_feedback("Stop adding summaries at the end", skill="mail-handler")
        assert created and fid == 1
        again, created2 = learn.add_feedback("stop adding   summaries at the end")
        assert not created2 and again == 1
        conn = learn.db()
        row = conn.execute("SELECT * FROM feedback").fetchone()
        assert row["skill"] == "mail-handler" and row["status"] == "new" and row["source"] == "agent"

    def test_skills_listed(self, home):
        assert learn.list_skills() == ["file-processing", "mail-handler"]


class TestCues:
    @pytest.mark.parametrize("text", [
        "please don't add a summary at the end",
        "From now on reply in Spanish",
        "that's not what I asked",
        "you keep formatting things as tables",
        "too verbose, just give me the answer",
        "remember this: I never work on Fridays",
        "feedback: stop using emojis",
        "Always include the ticket number in the subject",
    ])
    def test_positive(self, text):
        assert learn.looks_like_feedback(text)

    @pytest.mark.parametrize("text", [
        "summarize this file for me",
        "I never went to Paris",
        "what's on my calendar tomorrow?",
        "reply to Bob and attach the invoice",
    ])
    def test_negative(self, text):
        assert not learn.looks_like_feedback(text)


class TestTranscript:
    def test_claude_jsonl(self, tmp_path):
        lines = [
            {"type": "user", "message": {"role": "user", "content": "first message"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "reply"}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "ignored"}, {"type": "text", "text": "second message"}]}},
            {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
            {"type": "summary", "summary": "x"},
        ]
        p = tmp_path / "s.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines))
        assert learn.parse_transcript(str(p)) == ["first message", "second message"]

    def test_generic_role_content_jsonl(self, tmp_path):
        p = tmp_path / "g.jsonl"
        p.write_text('{"role":"user","content":"hi"}\n{"role":"assistant","content":"yo"}\n')
        assert learn.parse_transcript(str(p)) == ["hi"]

    def test_plain_text(self, tmp_path):
        p = tmp_path / "t.txt"
        p.write_text("one paragraph\nstill one\n\ntwo\n\n\nthree")
        assert learn.parse_transcript(str(p)) == ["one paragraph\nstill one", "two", "three"]


class TestExtract:
    def test_no_cues_no_llm(self, home, tmp_path, monkeypatch, capsys):
        p = tmp_path / "t.txt"
        p.write_text("summarize this\n\nthanks")
        monkeypatch.setenv("NOTO_LLM_FAKE_RESPONSE", "SHOULD NOT BE CALLED")
        learn.cmd_extract(Namespace(transcript=None, text_file=str(p), dry_run=False, quiet=False))
        assert "no feedback cues" in capsys.readouterr().out
        assert learn.db().execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0

    def test_dry_run(self, home, tmp_path, capsys):
        p = tmp_path / "t.txt"
        p.write_text("from now on, no emojis\n\nsummarize this")
        learn.cmd_extract(Namespace(transcript=None, text_file=str(p), dry_run=True, quiet=False))
        out = capsys.readouterr().out
        assert "1 of 2" in out and "no emojis" in out

    def test_extract_records_feedback(self, home, tmp_path, monkeypatch):
        p = tmp_path / "t.txt"
        p.write_text("stop putting greetings in emails, it's too formal")
        fake(monkeypatch, {"feedback": [
            {"text": "Do not open emails with a greeting line", "skill": "mail-handler", "context": "drafting a reply"},
            {"text": "", "skill": None},
            {"text": "Unknown skill gets nulled", "skill": "nope", "context": ""},
        ]})
        learn.cmd_extract(Namespace(transcript=None, text_file=str(p), dry_run=False, quiet=True))
        rows = learn.db().execute("SELECT text, skill, source FROM feedback ORDER BY id").fetchall()
        assert [(r["text"], r["skill"], r["source"]) for r in rows] == [
            ("Do not open emails with a greeting line", "mail-handler", "transcript"),
            ("Unknown skill gets nulled", None, "transcript"),
        ]


class TestSynthesize:
    def test_nothing_new(self, home, monkeypatch):
        monkeypatch.setenv("NOTO_LLM_FAKE_RESPONSE", "SHOULD NOT BE CALLED")
        assert learn.synthesize(learn.db()) == {"feedback": 0, "lessons": 0, "pending": 0}

    def test_lessons_created_and_nothing_dropped(self, home, monkeypatch):
        learn.add_feedback("No emojis in replies")
        learn.add_feedback("Stop using emojis", skill="mail-handler")
        learn.add_feedback("Rename the Q3 deck to final")          # one-off
        learn.add_feedback("Something the model forgets to place")  # uncovered -> insufficient_evidence
        fake(monkeypatch, {"lessons": [
            {"lesson_text": "Never use emojis in email replies.", "scope": "skill:mail-handler",
             "reasoning": "Two independent corrections.", "supporting_feedback_ids": [1, 2]},
            {"lesson_text": "Renamed one deck.", "scope": "one_off", "reasoning": "Task-specific.",
             "supporting_feedback_ids": [3, 999]},
        ]})
        conn = learn.db()
        stats = learn.synthesize(conn)
        assert stats == {"feedback": 4, "lessons": 3, "pending": 1}
        lessons = conn.execute("SELECT scope, status, supporting_ids FROM lessons ORDER BY id").fetchall()
        assert [(l["scope"], l["status"], json.loads(l["supporting_ids"])) for l in lessons] == [
            ("skill:mail-handler", "pending", [1, 2]),
            ("one_off", "deferred", [3]),
            ("insufficient_evidence", "deferred", [4]),
        ]
        fb = conn.execute("SELECT status, lesson_id FROM feedback ORDER BY id").fetchall()
        assert [(r["status"], r["lesson_id"]) for r in fb] == [
            ("synthesized", 1), ("synthesized", 1), ("synthesized", 2), ("synthesized", 3)]

    def test_bad_scope_and_unknown_skill_normalised(self, home):
        skills = learn.list_skills()
        assert learn._normalize_scope("skill:mail-handler", skills) == "skill:mail-handler"
        assert learn._normalize_scope("skill:doesnotexist", skills) == "global"
        assert learn._normalize_scope("weird", skills) == "insufficient_evidence"
        assert learn._normalize_scope("global", skills) == "global"

    def test_prompt_carries_active_lessons_and_skills(self, home, monkeypatch, tmp_path):
        log = tmp_path / "llm.log"
        monkeypatch.setenv("NOTO_LLM_FAKE_LOG", str(log))
        learn.cmd_lesson_add(Namespace(text="Existing rule", scope="global"))
        learn.add_feedback("new thing")
        fake(monkeypatch, {"lessons": [{"lesson_text": "x", "scope": "already_covered",
                                        "reasoning": "L1", "supporting_feedback_ids": [1]}]})
        learn.synthesize(learn.db())
        entry = json.loads(log.read_text().splitlines()[-1])
        assert "L1 [global] Existing rule" in entry["prompt"]
        assert '"mail-handler"' in entry["system"] and "Testbot" in entry["system"]


class TestReviewAndApply:
    def test_approve_applies_skill_lesson(self, home, monkeypatch, capsys):
        learn.add_feedback("no emojis", skill="mail-handler")
        fake(monkeypatch, {"lessons": [{"lesson_text": "Never use emojis in replies.", "scope": "skill:mail-handler",
                                        "reasoning": "r", "supporting_feedback_ids": [1]}]})
        learn.synthesize(learn.db())
        learn.cmd_approve(Namespace(ids=["l1"], note=None))
        out = capsys.readouterr().out
        assert "L1: approved" in out and "applied 1" in out
        skill_md = (home / "skills" / "mail-handler" / "SKILL.md").read_text()
        assert learn.LEARNED_HEADER in skill_md
        assert "(L1, " in skill_md and "Never use emojis in replies." in skill_md
        assert learn.db().execute("SELECT status FROM lessons WHERE id=1").fetchone()[0] == "applied"
        # second approval of another skill lesson appends under the same header, once
        learn.cmd_lesson_add(Namespace(text="Sign with first name only.", scope="skill:mail-handler"))
        skill_md = (home / "skills" / "mail-handler" / "SKILL.md").read_text()
        assert skill_md.count(learn.LEARNED_HEADER) == 1
        assert skill_md.rstrip().endswith("Sign with first name only.")

    def test_reject(self, home, capsys):
        learn.cmd_lesson_add(Namespace(text="tmp", scope="global"))
        learn.cmd_reject(Namespace(ids=["L1"], reason="not a rule"))
        assert "rejected" in capsys.readouterr().out
        row = learn.db().execute("SELECT status, review_note FROM lessons WHERE id=1").fetchone()
        assert (row["status"], row["review_note"]) == ("rejected", "not a rule")

    def test_lesson_add_rejects_bad_scope(self, home):
        with pytest.raises(SystemExit):
            learn.cmd_lesson_add(Namespace(text="x", scope="one_off"))

    def test_missing_skill_file_leaves_approved(self, home, capsys):
        conn = learn.db()
        conn.execute("INSERT INTO lessons (created_at, updated_at, lesson_text, scope, reasoning, status, source, supporting_ids) "
                     "VALUES ('t','t','x','skill:ghost','r','approved','manual','[]')")
        conn.commit()
        assert learn.apply_lessons(conn) == 0
        assert "not found" in capsys.readouterr().out


class TestRender:
    def test_sections(self, home, monkeypatch):
        learn.cmd_lesson_add(Namespace(text="Always be brief.", scope="global"))
        learn.add_feedback("one-off thing")
        fake(monkeypatch, {"lessons": [
            {"lesson_text": "Pending one", "scope": "global", "reasoning": "why", "supporting_feedback_ids": [1]}]})
        learn.cmd_synthesize(Namespace())
        text = (home / "brain" / "lessons.md").read_text()
        assert "# Lessons — Testbot" in text
        assert "## Active lessons" in text and "**L1** [global] Always be brief." in text
        assert "## Pending review" in text and "**L2** [global] Pending one" in text and "why: why" in text
        assert "evidence: F1" in text
        assert "do not edit by hand" in text


class TestRunAndStatus:
    def test_run_no_llm_without_memvid(self, home, capsys):
        learn.cmd_run(Namespace(no_llm=True))
        out = capsys.readouterr().out
        assert "synthesize: skipped (--no-llm)" in out
        assert "apply: 0" in out
        assert "integrity: skipped" in out
        log = (home / "brain" / "learning-log.md").read_text()
        assert log.startswith("# Learning log — Testbot") and "synthesize: skipped" in log
        assert (home / "brain" / "lessons.md").exists()

    def test_run_with_fake_llm(self, home, monkeypatch, capsys):
        learn.add_feedback("from now on be brief")
        fake(monkeypatch, {"lessons": [{"lesson_text": "Be brief.", "scope": "global", "reasoning": "explicit",
                                        "supporting_feedback_ids": [1]}]})
        learn.cmd_run(Namespace(no_llm=False))
        assert "synthesize: 1 feedback -> 1 lessons (1 pending)" in capsys.readouterr().out

    def test_status_brief(self, home, capsys):
        learn.cmd_lesson_add(Namespace(text="a", scope="global"))
        learn.add_feedback("b")
        learn.cmd_status(Namespace(brief=True))
        out = capsys.readouterr().out
        assert "1 active lesson(s)" in out and "1 feedback waiting" in out
