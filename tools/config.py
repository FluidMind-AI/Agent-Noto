"""
noto Configuration Loader

Resolves paths and settings from:
1. NOTO_HOME environment variable (required, or auto-detected)
2. noto.yaml config file at NOTO_HOME root
3. Sensible defaults matching standard noto directory layout
"""

import os
from typing import Any, Dict, Optional

_config_cache: Optional[Dict[str, Any]] = None


def _resolve_path(relative_or_absolute: str, base: str) -> str:
    """Resolve a path: if absolute, return as-is; if relative, resolve against base."""
    if os.path.isabs(relative_or_absolute):
        return relative_or_absolute
    return os.path.join(base, relative_or_absolute)


def get_home() -> str:
    """Get NOTO_HOME — the PA instance root directory."""
    home = os.environ.get("NOTO_HOME")
    if home:
        return home
    # Auto-detect: assume tools/ is one level below NOTO_HOME
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config() -> Dict[str, Any]:
    """Load noto.yaml config, with caching."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    home = get_home()
    config_path = os.path.join(home, "noto.yaml")
    config: Dict[str, Any] = {}

    if os.path.exists(config_path):
        # Privacy-critical: if the config file exists it MUST load. Silently
        # falling back to defaults would redirect writes to the wrong paths
        # (e.g. un-namespacing instance data into default locations).
        # Fail loud instead.
        try:
            import yaml
        except ImportError as e:
            raise RuntimeError(
                f"config exists at {config_path} but PyYAML is not "
                f"installed, so it cannot be applied and paths would "
                f"silently fall back to defaults. Run: uv pip install pyyaml"
            ) from e
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            raise RuntimeError(
                f"config at {config_path} failed to parse ({e}); "
                f"refusing to fall back to default paths."
            ) from e

    # Inject resolved home
    config["_home"] = home

    # Resolve all paths
    paths = config.get("paths", {})
    config["_resolved"] = {
        "credentials": _resolve_path(paths.get("credentials", "brain/companies-credentials.yaml"), home),
        "emails_dir": _resolve_path(paths.get("emails_dir", "emails"), home),
        "indexes_dir": _resolve_path(paths.get("indexes_dir", "indexes"), home),
        "memory_dir": _resolve_path(paths.get("memory_dir", "memory"), home),
        "brain_dir": _resolve_path(paths.get("brain_dir", "brain"), home),
        "venv": _resolve_path(paths.get("venv", ".venv"), home),
    }

    # Resolve memory paths
    mem = config.get("memory", {})
    config["_resolved"]["long_term_index"] = _resolve_path(
        mem.get("long_term_index", "indexes/memories.mv2"), home)
    config["_resolved"]["short_term_index"] = _resolve_path(
        mem.get("short_term_index", "indexes/short-term.mv2"), home)
    config["_resolved"]["metadata_db"] = _resolve_path(
        mem.get("metadata_db", "indexes/memory_meta.db"), home)

    # Resolve file index path
    files = config.get("files", {})
    config["_resolved"]["files_index"] = _resolve_path(
        files.get("index_path", "indexes/files.mv2"), home)

    # Email index (optional)
    email = config.get("email", {})
    config["_resolved"]["emails_index"] = _resolve_path(
        email.get("index_path", "indexes/emails.mv2"), home)

    # Security
    security = config.get("security", {}) or {}
    config["_resolved"]["integrity_checksums"] = _resolve_path(
        security.get("integrity_checksum_file", "indexes/integrity-checksums.sha256"), home)

    # Learning loop (tools/learn.py) — stdlib-only, works under any harness
    learning = config.get("learning", {}) or {}
    config["_resolved"]["learning_db"] = _resolve_path(learning.get("db", "indexes/learning.db"), home)
    config["_resolved"]["lessons_file"] = _resolve_path(learning.get("lessons_file", "brain/lessons.md"), home)
    config["_resolved"]["learning_log"] = _resolve_path(learning.get("log_file", "brain/learning-log.md"), home)
    config["_resolved"]["skills_dir"] = _resolve_path(learning.get("skills_dir", "skills"), home)

    _config_cache = config
    return config


def reset_cache() -> None:
    """Forget the cached config (tests, or after NOTO_HOME changes in-process)."""
    global _config_cache
    _config_cache = None


def get_path(key: str) -> str:
    """Get a resolved path by key. E.g., get_path('credentials')."""
    cfg = load_config()
    return cfg["_resolved"][key]
