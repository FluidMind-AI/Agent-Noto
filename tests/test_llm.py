#!/usr/bin/env python3
"""Tests for tools/llm.py — backend resolution, config overrides, JSON extraction.

No network, no CLIs: the fake backend and monkeypatched detection only.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

import config  # noqa: E402
import llm  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point NOTO_HOME at an empty dir so no developer noto.yaml leaks in."""
    monkeypatch.setenv("NOTO_HOME", str(tmp_path))
    for var in ("NOTO_LLM_BACKEND", "NOTO_LLM_MODEL", "NOTO_LLM_BASE_URL", "NOTO_LLM_API_KEY_ENV",
                "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "NOTO_LLM_FAKE_RESPONSE", "NOTO_LLM_FAKE_RESPONSE_FILE"):
        monkeypatch.delenv(var, raising=False)
    config.reset_cache()
    yield
    config.reset_cache()


class TestConfig:
    def test_defaults(self):
        cfg = llm.llm_config()
        assert cfg["backend"] == "auto"
        assert cfg["model"] == ""
        assert cfg["timeout_seconds"] == llm.DEFAULT_TIMEOUT_SECONDS

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        (tmp_path / "noto.yaml").write_text("llm:\n  backend: openai\n  model: yaml-model\n")
        config.reset_cache()
        assert llm.llm_config()["backend"] == "openai"
        assert llm.llm_config()["model"] == "yaml-model"
        monkeypatch.setenv("NOTO_LLM_BACKEND", "fake")
        monkeypatch.setenv("NOTO_LLM_MODEL", "env-model")
        assert llm.llm_config()["backend"] == "fake"
        assert llm.llm_config()["model"] == "env-model"


class TestResolve:
    def test_explicit_backend(self):
        assert llm.resolve_backend("codex-cli") == "codex-cli"

    def test_unknown_backend(self):
        with pytest.raises(llm.LLMError, match="unknown llm.backend"):
            llm.resolve_backend("bogus")

    def test_auto_prefers_claude_cli(self, monkeypatch):
        monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/" + name if name in ("claude", "codex") else None)
        assert llm.resolve_backend("auto") == "claude-cli"

    def test_auto_falls_through_to_keys(self, monkeypatch):
        monkeypatch.setattr(llm.shutil, "which", lambda name: None)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert llm.resolve_backend("auto") == "openai"

    def test_auto_nothing_available(self, monkeypatch):
        monkeypatch.setattr(llm.shutil, "which", lambda name: None)
        with pytest.raises(llm.LLMError, match="no LLM backend available"):
            llm.resolve_backend("auto")


class TestFakeBackend:
    def test_returns_env_response(self, monkeypatch):
        monkeypatch.setenv("NOTO_LLM_BACKEND", "fake")
        monkeypatch.setenv("NOTO_LLM_FAKE_RESPONSE", "hello there")
        assert llm.complete("anything") == "hello there"

    def test_logs_prompt_and_system(self, monkeypatch, tmp_path):
        log = tmp_path / "fake.log"
        monkeypatch.setenv("NOTO_LLM_BACKEND", "fake")
        monkeypatch.setenv("NOTO_LLM_FAKE_LOG", str(log))
        llm.complete("the prompt", system="the system")
        assert '"system": "the system"' in log.read_text()
        assert '"prompt": "the prompt"' in log.read_text()

    def test_response_file_wins(self, monkeypatch, tmp_path):
        f = tmp_path / "reply.txt"
        f.write_text("from file")
        monkeypatch.setenv("NOTO_LLM_BACKEND", "fake")
        monkeypatch.setenv("NOTO_LLM_FAKE_RESPONSE", "from env")
        monkeypatch.setenv("NOTO_LLM_FAKE_RESPONSE_FILE", str(f))
        assert llm.complete("x") == "from file"


class TestHttpBackendsPreflight:
    def test_openai_requires_model(self):
        with pytest.raises(llm.LLMError, match="llm.model"):
            llm.complete("x", backend="openai")

    def test_anthropic_requires_key(self):
        with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
            llm.complete("x", backend="anthropic")

    def test_custom_key_env_name(self, monkeypatch):
        monkeypatch.setenv("NOTO_LLM_API_KEY_ENV", "MY_KEY")
        with pytest.raises(llm.LLMError, match="MY_KEY"):
            llm.complete("x", backend="anthropic")


class TestExtractJson:
    def test_plain(self):
        assert llm.extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert llm.extract_json('Sure:\n```json\n{"a": [1, 2]}\n```\nDone.') == {"a": [1, 2]}

    def test_embedded_in_prose(self):
        assert llm.extract_json('Here you go {"lessons": []} hope it helps') == {"lessons": []}

    def test_array(self):
        assert llm.extract_json('[1, 2, 3]') == [1, 2, 3]

    def test_failure(self):
        with pytest.raises(llm.LLMError, match="parseable JSON"):
            llm.extract_json("no json here")


class TestHelpers:
    def test_fold_system(self):
        assert llm._fold_system("p", None) == "p"
        folded = llm._fold_system("p", "s")
        assert folded.startswith("<system>\ns\n</system>")
        assert folded.endswith("p")

    def test_scrubbed_env_drops_nested_markers(self, monkeypatch):
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("KEEP_ME", "yes")
        env = llm._scrubbed_env()
        assert "CLAUDECODE" not in env
        assert env["KEEP_ME"] == "yes"
