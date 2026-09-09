from importlib.resources import files

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway RESUME_TAILOR_HOME with the example profile and the mock engine."""
    root = tmp_path / "rt"
    (root / "profile" / "profiles" / "default").mkdir(parents=True)
    data = files("resume_tailor") / "data"
    (root / "profile" / "profiles" / "default" / "master_profile.yaml").write_text(
        (data / "master_profile.example.yaml").read_text()
    )
    (root / "profile" / "settings.yaml").write_text(
        "engine: mock\nmodel: mock\nmake_pdf: false\nreview_rounds: 0\n"
    )
    monkeypatch.setenv("RESUME_TAILOR_HOME", str(root))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return root
