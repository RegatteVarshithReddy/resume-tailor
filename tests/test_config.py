from resume_tailor.config import (
    PROVIDERS,
    Paths,
    Settings,
    clear_secret,
    load_secrets,
    save_secret,
    save_settings,
)


def test_legacy_flat_fields_migrate_into_providers(home):
    (home / "profile" / "settings.yaml").write_text(
        "engine: api\nmodel: sonnet\napi_model: claude-sonnet-5\n"
        "ollama_model: llama3.1\nollama_url: http://localhost:11434\n"
    )
    s = Settings.load(home)
    assert s.engine == "anthropic"                       # "api" alias normalised
    assert s.providers["anthropic"]["model"] == "claude-sonnet-5"
    assert s.providers["ollama"]["base_url"] == "http://localhost:11434/v1"


def test_provider_config_merges_preset_and_saved(home):
    save_settings(Paths.resolve(home), {
        "engine": "openai",
        "providers": {"openai": {"model": "gpt-4o-mini"}},
    })
    cfg = Settings.load(home).provider_config("openai")
    assert cfg["model"] == "gpt-4o-mini"                 # saved wins
    assert cfg["base_url"] == "https://api.openai.com/v1"  # preset fills the gap
    assert cfg["kind"] == "openai-compat"


def test_anthropic_alias_maps_to_full_id(home):
    save_settings(Paths.resolve(home), {"engine": "anthropic",
                                        "providers": {"anthropic": {"model": "haiku"}}})
    assert Settings.load(home).provider_config("anthropic")["model"] == "claude-haiku-4-5-20251001"


def test_provider_key_precedence(home, monkeypatch):
    s = Settings.load(home)
    assert s.provider_key("openai", home) is None
    save_secret("openai", "sk-from-file", home)
    assert s.provider_key("openai", home) == "sk-from-file"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert s.provider_key("openai", home) == "sk-from-env"   # env wins over file
    clear_secret("openai", home)
    assert load_secrets(home) == {}


def test_secrets_file_is_chmod_600(home):
    save_secret("gemini", "AIza-xyz", home)
    p = home / "profile" / "secrets.yaml"
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert "AIza-xyz" not in (home / "profile" / "settings.yaml").read_text()


def test_env_model_override_routes_to_active_provider(home, monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_ENGINE", "openai")
    monkeypatch.setenv("RESUME_TAILOR_MODEL", "o3")
    assert Settings.load(home).provider_config("openai")["model"] == "o3"


def test_every_provider_has_a_kind():
    for name, p in PROVIDERS.items():
        assert p["kind"] in {"claude-cli", "anthropic", "openai-compat", "mock"}, name
