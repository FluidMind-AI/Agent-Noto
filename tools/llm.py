#!/usr/bin/env python3
"""
LLM chokepoint — the ONE place noto's background jobs call a model.

The interactive agent is whatever harness the operator runs (Claude Code,
Codex CLI, Gemini CLI, OpenCode, ...). noto never owns that loop. But the
scheduled jobs — the nightly learning pass, transcript feedback extraction —
need a model call outside any session. Every such call goes through
complete() so pointing noto at a different engine is a config change, never
a code change.

Backends (noto.yaml -> llm.backend, or NOTO_LLM_BACKEND env):
  auto        pick the first available: claude-cli, codex-cli, gemini-cli,
              anthropic (ANTHROPIC_API_KEY set), openai (OPENAI_API_KEY set)
  claude-cli  `claude -p`  — uses the operator's Claude subscription, no key
  codex-cli   `codex exec` — uses the operator's OpenAI/ChatGPT login, no key
  gemini-cli  `gemini -p`  — uses the operator's Google login, no key
  anthropic   Anthropic Messages API over HTTP (api_key_env, default
              ANTHROPIC_API_KEY)
  openai      any OpenAI-compatible /chat/completions endpoint: OpenAI,
              OpenRouter, Groq, Ollama, LM Studio, vLLM, llama.cpp ...
              (base_url + model; api_key_env optional for local servers)
  fake        tests only — returns NOTO_LLM_FAKE_RESPONSE verbatim

CLI-backed engines run in an empty scratch directory with tools disabled so
the call is a pure completion: no instance files are read, nothing is
executed, nothing is written.

stdlib only — no SDKs, no third-party packages.

CLI:
  python tools/llm.py backends          # what is configured / detected
  python tools/llm.py selftest          # one round-trip through the chokepoint
  python tools/llm.py complete "prompt" [--system "..."] [--backend X]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config  # noqa: E402

BACKENDS = ("auto", "claude-cli", "codex-cli", "gemini-cli", "anthropic", "openai", "fake")

# Tools a CLI engine must never touch during a chokepoint call. The list is
# deliberately broad: a background completion has no business editing files,
# running shell, spawning agents, or fetching URLs.
_CLAUDE_DISALLOWED_TOOLS = (
    "Bash,Edit,Write,MultiEdit,NotebookEdit,Agent,Task,WebFetch,WebSearch,"
    "Read,Glob,Grep,LS,TodoWrite,KillShell,BashOutput"
)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"
DEFAULT_OPENAI_BASE_URL = "http://localhost:11434/v1"  # Ollama's default
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_TOKENS = 8192


class LLMError(RuntimeError):
    """Raised when the configured backend cannot produce a completion."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def llm_config() -> Dict[str, Any]:
    """Merged llm settings: noto.yaml `llm:` block, overridden by NOTO_LLM_* env."""
    cfg = load_config().get("llm") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    env = os.environ
    return {
        "backend": env.get("NOTO_LLM_BACKEND") or cfg.get("backend") or "auto",
        "model": env.get("NOTO_LLM_MODEL") or cfg.get("model") or "",
        "base_url": env.get("NOTO_LLM_BASE_URL") or cfg.get("base_url") or "",
        "api_key_env": env.get("NOTO_LLM_API_KEY_ENV") or cfg.get("api_key_env") or "",
        "timeout_seconds": int(env.get("NOTO_LLM_TIMEOUT") or cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
    }


def detect_backends() -> List[str]:
    """Backends usable on this machine right now, in auto-selection order."""
    found = []
    if shutil.which("claude"):
        found.append("claude-cli")
    if shutil.which("codex"):
        found.append("codex-cli")
    if shutil.which("gemini"):
        found.append("gemini-cli")
    if os.environ.get("ANTHROPIC_API_KEY"):
        found.append("anthropic")
    if os.environ.get("OPENAI_API_KEY"):
        found.append("openai")
    return found


def resolve_backend(name: Optional[str] = None) -> str:
    """Turn a configured backend name (or 'auto') into a concrete backend."""
    name = name or llm_config()["backend"]
    if name not in BACKENDS:
        raise LLMError(f"unknown llm.backend {name!r}; choose one of {', '.join(BACKENDS)}")
    if name != "auto":
        return name
    found = detect_backends()
    if found:
        return found[0]
    raise LLMError(
        "no LLM backend available. Install one of the `claude`, `codex`, or "
        "`gemini` CLIs, or set ANTHROPIC_API_KEY / OPENAI_API_KEY, or configure "
        "`llm:` in noto.yaml (e.g. backend: openai, base_url: http://localhost:11434/v1, "
        "model: <ollama model>)."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def complete(prompt: str, *, system: Optional[str] = None, max_tokens: int = DEFAULT_MAX_TOKENS,
             backend: Optional[str] = None, model: Optional[str] = None) -> str:
    """Return the model's text reply for `prompt` (plus optional system prompt)."""
    cfg = llm_config()
    chosen = resolve_backend(backend)
    model = model or cfg["model"] or None
    timeout = cfg["timeout_seconds"]

    if chosen == "fake":
        return _fake(prompt, system)
    if chosen == "claude-cli":
        return _claude_cli(prompt, system, model, timeout)
    if chosen == "codex-cli":
        return _codex_cli(prompt, system, model, timeout)
    if chosen == "gemini-cli":
        return _gemini_cli(prompt, system, model, timeout)
    if chosen == "anthropic":
        return _anthropic(prompt, system, model, max_tokens, cfg, timeout)
    if chosen == "openai":
        return _openai(prompt, system, model, max_tokens, cfg, timeout)
    raise LLMError(f"backend {chosen!r} has no implementation")


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a model reply that may wrap it in prose or fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # Last resort: the outermost {...} or [...] span.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    raise LLMError("model reply did not contain parseable JSON:\n" + text[:500])


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _fold_system(prompt: str, system: Optional[str]) -> str:
    """CLI engines without a system-prompt flag get it folded into the prompt."""
    if not system:
        return prompt
    return f"<system>\n{system}\n</system>\n\n{prompt}"


def _scrubbed_env() -> Dict[str, str]:
    """Env for child CLIs: drop nested-session markers so a hook-triggered call works."""
    env = dict(os.environ)
    for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR"):
        env.pop(key, None)
    return env


def _run(cmd: List[str], stdin_text: Optional[str], timeout: int, label: str) -> str:
    with tempfile.TemporaryDirectory(prefix="noto-llm-") as scratch:
        try:
            proc = subprocess.run(
                cmd, input=stdin_text, capture_output=True, text=True,
                timeout=timeout, cwd=scratch, env=_scrubbed_env(),
            )
        except FileNotFoundError as e:
            raise LLMError(f"{label}: executable not found ({cmd[0]})") from e
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"{label}: timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise LLMError(f"{label}: exit {proc.returncode}\n{proc.stderr.strip()[:1000]}")
    out = proc.stdout.strip()
    if not out:
        raise LLMError(f"{label}: empty reply\n{proc.stderr.strip()[:500]}")
    return out


def _claude_cli(prompt: str, system: Optional[str], model: Optional[str], timeout: int) -> str:
    cmd = ["claude", "-p", "--output-format", "text", "--no-session-persistence",
           "--disallowedTools", _CLAUDE_DISALLOWED_TOOLS]
    if system:
        cmd += ["--system-prompt", system]
    if model:
        cmd += ["--model", model]
    return _run(cmd, prompt, timeout, "claude-cli")


def _codex_cli(prompt: str, system: Optional[str], model: Optional[str], timeout: int) -> str:
    with tempfile.NamedTemporaryFile(prefix="noto-codex-", suffix=".txt", delete=False) as last:
        last_path = last.name
    try:
        cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
               "--color", "never", "--output-last-message", last_path]
        if model:
            cmd += ["--model", model]
        cmd.append("-")  # prompt from stdin
        _run(cmd, _fold_system(prompt, system), timeout, "codex-cli")
        with open(last_path, encoding="utf-8") as f:
            out = f.read().strip()
        if not out:
            raise LLMError("codex-cli: empty final message")
        return out
    finally:
        try:
            os.unlink(last_path)
        except OSError:
            pass


def _gemini_cli(prompt: str, system: Optional[str], model: Optional[str], timeout: int) -> str:
    cmd = ["gemini", "-p", _fold_system(prompt, system)]
    if model:
        cmd += ["-m", model]
    return _run(cmd, None, timeout, "gemini-cli")


def _http_json(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: int, label: str) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:1000]
        raise LLMError(f"{label}: HTTP {e.code} from {url}\n{detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"{label}: cannot reach {url} ({e.reason})") from e


def _api_key(cfg: Dict[str, Any], default_env: str, required: bool, label: str) -> Optional[str]:
    env_name = cfg["api_key_env"] or default_env
    key = os.environ.get(env_name)
    if required and not key:
        raise LLMError(f"{label}: set ${env_name} (or llm.api_key_env in noto.yaml)")
    return key


def _anthropic(prompt: str, system: Optional[str], model: Optional[str], max_tokens: int,
               cfg: Dict[str, Any], timeout: int) -> str:
    key = _api_key(cfg, "ANTHROPIC_API_KEY", True, "anthropic")
    base = (cfg["base_url"] or "https://api.anthropic.com").rstrip("/")
    body: Dict[str, Any] = {
        "model": model or DEFAULT_ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    reply = _http_json(f"{base}/v1/messages",
                       {"x-api-key": key, "anthropic-version": "2023-06-01"},
                       body, timeout, "anthropic")
    if reply.get("stop_reason") == "refusal":
        details = reply.get("stop_details") or {}
        raise LLMError(f"anthropic: request refused ({details.get('category')}): {details.get('explanation')}")
    text = "".join(block.get("text", "") for block in reply.get("content", []) if block.get("type") == "text")
    if not text.strip():
        raise LLMError("anthropic: reply had no text content")
    return text.strip()


def _openai(prompt: str, system: Optional[str], model: Optional[str], max_tokens: int,
            cfg: Dict[str, Any], timeout: int) -> str:
    base = (cfg["base_url"] or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    if not model:
        raise LLMError("openai: set llm.model in noto.yaml (e.g. gpt-5, llama3.1, qwen2.5) — "
                       "OpenAI-compatible servers have no universal default")
    key = _api_key(cfg, "OPENAI_API_KEY", False, "openai")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    reply = _http_json(f"{base}/chat/completions", headers, body, timeout, "openai")
    try:
        text = reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"openai: unexpected response shape: {json.dumps(reply)[:500]}") from e
    if not text or not text.strip():
        raise LLMError("openai: empty reply")
    return text.strip()


def _fake(prompt: str, system: Optional[str]) -> str:
    log = os.environ.get("NOTO_LLM_FAKE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"system": system, "prompt": prompt}) + "\n")
    path = os.environ.get("NOTO_LLM_FAKE_RESPONSE_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    return os.environ.get("NOTO_LLM_FAKE_RESPONSE", "OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="noto LLM chokepoint")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("backends", help="Show configured backend and what is detected on this machine")
    st = sub.add_parser("selftest", help="One round-trip through the configured backend")
    st.add_argument("--backend", choices=BACKENDS)
    cp = sub.add_parser("complete", help="Send a prompt and print the reply")
    cp.add_argument("prompt")
    cp.add_argument("--system")
    cp.add_argument("--backend", choices=BACKENDS)
    cp.add_argument("--model")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if args.command == "backends":
        cfg = llm_config()
        print(f"configured: {cfg['backend']}  model: {cfg['model'] or '(backend default)'}")
        print(f"detected:   {', '.join(detect_backends()) or 'none'}")
        try:
            print(f"resolved:   {resolve_backend()}")
        except LLMError as e:
            print(f"resolved:   ERROR — {e}")
        return

    try:
        if args.command == "selftest":
            chosen = resolve_backend(args.backend)
            reply = complete("Reply with exactly the single word: OK", backend=chosen)
            status = "ok" if reply.strip().strip(".").upper() == "OK" else "reply differs"
            print(f"[{chosen}] {status}: {reply[:200]}")
            return
        if args.command == "complete":
            print(complete(args.prompt, system=args.system, backend=args.backend, model=args.model))
    except LLMError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
