"""Project paths, settings, and multi-profile resolution."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PROFILE = "default"


def project_root() -> Path:
    env = os.environ.get("RESUME_TAILOR_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def slugify(s: str, fallback: str = "item") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (s or "").strip()).strip("-").lower()
    return s or fallback


DEFAULT_MATCH_WEIGHTS = {"coverage": 0.55, "years": 0.20, "domain": 0.10, "archetype": 0.10}

# Curated model picker. Key -> per-engine identifier + a one-line label.
# `claude-cli` takes the short aliases; the Anthropic API needs the full id.
# Any value not listed here is passed straight through (a full model id, an
# Ollama tag, a `sonnet[1m]`-style alias, …), so power users are never boxed in.
MODEL_CHOICES: dict[str, dict[str, str]] = {
    "opus": {
        "cli": "opus", "api": "claude-opus-5",
        "label": "Opus 5 — highest quality, slowest, heaviest on usage",
    },
    "sonnet": {
        "cli": "sonnet", "api": "claude-sonnet-5",
        "label": "Sonnet 5 — balanced quality vs. speed (default)",
    },
    "haiku": {
        "cli": "haiku", "api": "claude-haiku-4-5-20251001",
        "label": "Haiku 4.5 — fastest and cheapest, lighter quality",
    },
}
DEFAULT_MODEL = "sonnet"
DEFAULT_ENGINE = "claude-cli"

# Provider presets for the Settings tab + engine routing. `kind` picks the engine
# class: "claude-cli" (local `claude`, no API bill), "anthropic" (native SDK), or
# "openai-compat" (any endpoint speaking OpenAI's POST /chat/completions — OpenAI,
# Gemini via its compat URL, OpenRouter, Groq, Ollama, LM Studio, vLLM, llama.cpp).
# Per-provider `model` + `base_url` are saved in settings.yaml under `providers:`;
# API keys are NOT — they live in env vars or the git-ignored profile/secrets.yaml.
PROVIDERS: dict[str, dict] = {
    "claude-cli": {
        "label": "Claude — via Claude Code subscription (no API bill)",
        "kind": "claude-cli", "needs_key": False,
        "models": list(MODEL_CHOICES), "default_model": DEFAULT_MODEL,
        "help": "Uses the local `claude` CLI. No key needed if you're signed in to Claude Code.",
    },
    "anthropic": {
        "label": "Anthropic API — Claude",
        "kind": "anthropic", "needs_key": True, "key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
        "default_model": "claude-sonnet-5",
        "signup": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI — ChatGPT API",
        "kind": "openai-compat", "needs_key": True, "key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini"],
        "default_model": "gpt-4o",
        "signup": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "label": "Google — Gemini API",
        "kind": "openai-compat", "needs_key": True, "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        "default_model": "gemini-2.5-flash",
        "signup": "https://aistudio.google.com/apikey",
    },
    "openrouter": {
        "label": "OpenRouter — one key, many models",
        "kind": "openai-compat", "needs_key": True, "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["anthropic/claude-3.7-sonnet", "openai/gpt-4o",
                   "google/gemini-2.0-flash-001", "meta-llama/llama-3.3-70b-instruct"],
        "default_model": "anthropic/claude-3.7-sonnet",
        "signup": "https://openrouter.ai/keys",
    },
    "ollama": {
        "label": "Ollama — local models",
        "kind": "openai-compat", "needs_key": False,
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.1", "qwen2.5", "mistral", "gemma2", "phi3"],
        "default_model": "llama3.1",
        "signup": "https://ollama.com",
        "help": "Run `ollama serve` and `ollama pull <model>` first. \"Refresh\" lists pulled models.",
    },
    "custom": {
        "label": "Custom — any OpenAI-compatible endpoint",
        "kind": "openai-compat", "needs_key": False,
        "base_url": "http://localhost:1234/v1",
        "models": [], "default_model": "",
        "help": "LM Studio, vLLM, llama.cpp, text-generation-webui, a gateway… set base URL + model.",
    },
    "mock": {
        "label": "Mock — offline, deterministic, no key (testing / demo)",
        "kind": "mock", "needs_key": False,
        "models": ["mock"], "default_model": "mock",
        "help": "Canned output — try the whole flow with zero setup, or run CI.",
    },
}


@dataclass
class Settings:
    engine: str = DEFAULT_ENGINE        # a key of PROVIDERS
    claude_binary: str = "claude"
    model: str = DEFAULT_MODEL           # opus | sonnet | haiku  (or a full model id)
    api_model: str = "claude-sonnet-5"   # legacy — migrated into providers["anthropic"]
    ollama_model: str = "llama3.1"       # legacy — migrated into providers["ollama"]
    ollama_url: str = "http://localhost:11434"  # legacy
    providers: dict = field(default_factory=dict)  # name -> {"model": str, "base_url": str}
    llm_timeout: int = 240
    make_pdf: bool = True
    page_size: str = "letter"           # letter | a4
    accent_color: str = "#1F4E79"
    review_rounds: int = 2              # draft -> critique/revise this many times (0 disables)
    match_weights: dict = field(default_factory=lambda: dict(DEFAULT_MATCH_WEIGHTS))

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        root = root or project_root()
        p = root / "profile" / "settings.yaml"
        data = {}
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
        s = cls()
        for k, v in data.items():
            if hasattr(s, k) and v is not None:
                setattr(s, k, v)
        if isinstance(s.match_weights, dict):
            s.match_weights = {**DEFAULT_MATCH_WEIGHTS, **s.match_weights}
        else:
            s.match_weights = dict(DEFAULT_MATCH_WEIGHTS)
        try:
            s.review_rounds = max(0, min(3, int(s.review_rounds)))
        except (TypeError, ValueError):
            s.review_rounds = 2

        # --- providers map (new) + migration from the old flat fields ---
        s.providers = dict(s.providers) if isinstance(s.providers, dict) else {}
        _legacy = {
            "claude-cli": {"model": s.model},
            "anthropic": {"model": s.api_model},
            "ollama": {
                "model": s.ollama_model,
                "base_url": (s.ollama_url.rstrip("/") + "/v1") if s.ollama_url else "",
            },
        }
        for _name, _cfg in _legacy.items():
            _cur = dict(s.providers.get(_name) or {})
            for _k, _v in _cfg.items():
                if _v and not _cur.get(_k):
                    _cur[_k] = _v
            if _cur:
                s.providers[_name] = _cur
        if s.engine in ("api", "anthropic-api"):
            s.engine = "anthropic"

        if os.environ.get("RESUME_TAILOR_ENGINE"):
            s.engine = os.environ["RESUME_TAILOR_ENGINE"]
        if os.environ.get("RESUME_TAILOR_MODEL"):
            s.model = os.environ["RESUME_TAILOR_MODEL"]
            s.providers.setdefault(s.engine, {})["model"] = s.model
        return s

    # -- provider resolution ------------------------------------------------
    def provider_config(self, name: str | None = None) -> dict:
        """Merged view of one provider: presets <- settings.yaml `providers:`.
        `model`/`base_url` only — never the key (see `provider_key`)."""
        name = name or self.engine or DEFAULT_ENGINE
        preset = PROVIDERS.get(name, PROVIDERS["custom"])
        saved = (self.providers or {}).get(name, {}) or {}
        model = (saved.get("model") or "").strip() or preset.get("default_model", "")
        if name == "anthropic":
            mc = MODEL_CHOICES.get(model.lower())
            if mc:
                model = mc["api"]          # 'sonnet' -> 'claude-sonnet-5' for the native SDK
        return {
            "name": name,
            "kind": preset.get("kind", "openai-compat"),
            "label": preset.get("label", name),
            "needs_key": bool(preset.get("needs_key")),
            "key_env": preset.get("key_env"),
            "base_url": (saved.get("base_url") or preset.get("base_url", "")).rstrip("/"),
            "model": model,
            "models": list(preset.get("models", [])),
            "signup": preset.get("signup"),
            "help": preset.get("help"),
        }

    def provider_key(self, name: str | None = None, root: Path | None = None) -> str | None:
        """API key for a provider: provider env var, then RESUME_TAILOR_<NAME>_KEY,
        then the git-ignored profile/secrets.yaml. Never read from settings.yaml."""
        name = name or self.engine or DEFAULT_ENGINE
        env = (PROVIDERS.get(name) or {}).get("key_env")
        if env and os.environ.get(env, "").strip():
            return os.environ[env].strip()
        gen = os.environ.get("RESUME_TAILOR_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()) + "_KEY", "")
        if gen.strip():
            return gen.strip()
        return load_secrets(root).get(name) or None

    def resolve_model(self, engine_name: str | None = None) -> str:
        """Map the picker key in `self.model` to the id the active engine wants.

        `opus` -> `claude-opus-5` for the API engine, `opus` for the CLI. An
        unknown value passes straight through; an empty value lets the CLI use
        its own default and falls back to `api_model` for the API engine.
        """
        raw = (self.model or "").strip()
        eng = (engine_name or self.engine or "claude-cli").lower()
        choice = MODEL_CHOICES.get(raw.lower())
        if choice:
            return choice["api"] if eng in ("api", "anthropic") else choice["cli"]
        if eng in ("api", "anthropic"):
            return raw or self.api_model
        return raw


# --------------------------------------------------------------------------- #
# tiny per-install UI state (last-used dashboard choices) — data/ui_state.json
# --------------------------------------------------------------------------- #
def _ui_state_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "ui_state.json"


def load_ui_state(root: Path | None = None) -> dict:
    import json

    p = _ui_state_path(root)
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ui_state(state: dict, root: Path | None = None) -> None:
    import json

    p = _ui_state_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# API keys — profile/secrets.yaml  (git-ignored, chmod 600, never committed)
# --------------------------------------------------------------------------- #
def _secrets_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "profile" / "secrets.yaml"


def load_secrets(root: Path | None = None) -> dict:
    try:
        d = yaml.safe_load(_secrets_path(root).read_text()) or {}
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in d.items() if v} if isinstance(d, dict) else {}


def save_secret(name: str, key: str, root: Path | None = None) -> None:
    """Set (key truthy) or remove (key falsy) one provider's API key."""
    p = _secrets_path(root)
    d = load_secrets(root)
    if key:
        d[name] = key
    else:
        d.pop(name, None)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# resume-tailor API keys — DO NOT COMMIT. Managed by the Settings page.\n"
        + yaml.safe_dump(d, default_flow_style=False, sort_keys=True)
    )
    try:
        p.chmod(0o600)
    except OSError:
        pass


def clear_secret(name: str, root: Path | None = None) -> None:
    save_secret(name, "", root)


def save_settings(paths: "Paths", data: dict) -> None:
    """Write profile/settings.yaml from the Settings page. Keys are never written
    here — they go to profile/secrets.yaml via save_secret()."""
    paths.settings.parent.mkdir(parents=True, exist_ok=True)
    paths.settings.write_text(
        "# resume-tailor settings — managed by the Settings page (safe to hand-edit).\n"
        "# Every option is documented in settings.example.yaml. API keys: secrets.yaml.\n\n"
        + yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    )


@dataclass
class Paths:
    root: Path
    profile_dir: Path = field(init=False)
    profiles_dir: Path = field(init=False)
    legacy_master: Path = field(init=False)
    settings: Path = field(init=False)
    data_dir: Path = field(init=False)
    db: Path = field(init=False)
    outputs: Path = field(init=False)

    def __post_init__(self) -> None:
        self.profile_dir = self.root / "profile"
        self.profiles_dir = self.profile_dir / "profiles"
        self.legacy_master = self.profile_dir / "master_profile.yaml"
        self.settings = self.profile_dir / "settings.yaml"
        self.data_dir = self.root / "data"
        self.db = self.data_dir / "applications.db"
        self.outputs = self.root / "outputs"

    @classmethod
    def resolve(cls, root: Path | None = None) -> "Paths":
        return cls(root=(root or project_root()))

    # -- profiles ---------------------------------------------------------
    def master_profile(self, name: str = DEFAULT_PROFILE) -> Path:
        """Resolve a profile name to its master_profile.yaml path.

        Falls back to the legacy single-file layout for the default profile.
        """
        cand = self.profiles_dir / name / "master_profile.yaml"
        if cand.exists():
            return cand
        if name == DEFAULT_PROFILE and self.legacy_master.exists():
            return self.legacy_master
        return cand  # non-existent; caller raises a helpful error

    def list_profiles(self) -> list[str]:
        names: list[str] = []
        if self.profiles_dir.exists():
            names = sorted(
                d.name for d in self.profiles_dir.iterdir()
                if d.is_dir() and (d / "master_profile.yaml").exists()
            )
        if not names and self.legacy_master.exists():
            names = [DEFAULT_PROFILE]
        return names
