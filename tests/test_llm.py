import json

import pytest

from resume_tailor.config import Settings
from resume_tailor.llm import (
    ClaudeCLIEngine,
    LLMError,
    MockEngine,
    OpenAICompatEngine,
    get_engine,
)


def test_get_engine_routes_by_provider(home, monkeypatch):
    s = Settings.load(home)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert isinstance(get_engine(s, override="mock"), MockEngine)
    assert isinstance(get_engine(s, override="openai"), OpenAICompatEngine)
    assert isinstance(get_engine(s, override="ollama"), OpenAICompatEngine)   # no key needed
    # unknown name -> treated as a user-named openai-compat provider (no base_url -> error)
    with pytest.raises(LLMError):
        get_engine(s, override="totally-unknown")


def test_model_override_is_raw_for_api_providers(home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    s = Settings.load(home)
    assert get_engine(s, override="openai", model="gpt-4o-mini").model == "gpt-4o-mini"


def test_model_override_expands_alias_for_claude_cli(home, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _b: "/usr/bin/claude")
    eng = get_engine(Settings.load(home), override="claude-cli", model="haiku")
    assert isinstance(eng, ClaudeCLIEngine) and eng.model == "haiku"


def test_openai_compat_missing_key_raises(home):
    with pytest.raises(LLMError):
        get_engine(Settings.load(home), override="gemini")   # needs GEMINI_API_KEY


def test_openai_compat_post_shapes_request(home, monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    eng = get_engine(Settings.load(home), override="openai", model="gpt-4o")
    assert eng.complete_json("sys", "hi") == {"ok": True}
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"].get("Authorization") == "Bearer sk-live"
    assert captured["body"]["model"] == "gpt-4o"
    assert captured["body"]["messages"][0]["role"] == "system"


def test_mock_engine_extract_and_tailor_json():
    m = MockEngine()
    req = m.complete_json("precise technical recruiter's assistant",
                          'Extract the requirements\n"""\nNeed Python and Kafka, 8+ years\n"""')
    assert "Python" in req["must_have_skills"] and req["min_years"] == 8
    tr = m.complete_json("expert resume writer",
                         '{"experience": [{"id": "job1"}, {"id": "job2"}], "skill": "Go"}')
    assert [e["id"] for e in tr["experience"]] == ["job1", "job2"]
    assert tr["cover_letter"].startswith("Dear Hiring Manager")
