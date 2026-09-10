from resume_tailor.config import Paths, Settings
from resume_tailor.pipeline import run_tailor
from resume_tailor.store import Store
from resume_tailor.webapp import App


def _app(home):
    return App(Paths.resolve(home), Settings.load(home))


def test_core_pages_render(home):
    app = _app(home)
    assert b"New application" in app.page_dashboard()
    assert b"Active provider" in app.page_settings()
    for marker in (b'name="engine"', b'name="model_openai"', b'name="base_url_ollama"',
                   b'value="test:gemini"', b"Match-score weights"):
        assert marker in app.page_settings(), marker


def test_settings_save_persists_and_keeps_key_out_of_settings_yaml(home):
    app = _app(home)
    form = {
        "engine": ["openai"],
        "model_openai": ["gpt-4o-mini"],
        "base_url_openai": ["https://api.openai.com/v1"],
        "key_openai": ["sk-secret-xyz"],
        "make_pdf": ["0"], "page_size": ["a4"], "accent_color": ["#123456"],
        "review_rounds": ["1"],
        "w_coverage": ["0.55"], "w_years": ["0.20"], "w_domain": ["0.10"], "w_archetype": ["0.10"],
        "do": ["save"],
    }
    banner, _ = app.act_settings(form)
    assert banner == ""
    s = Settings.load(home)
    assert s.engine == "openai"
    assert s.provider_config("openai")["model"] == "gpt-4o-mini"
    assert s.page_size == "a4" and s.make_pdf is False and s.review_rounds == 1
    assert "sk-secret-xyz" not in (home / "profile" / "settings.yaml").read_text()
    assert s.provider_key("openai", home) == "sk-secret-xyz"

    # blank key on resave keeps it; the clear checkbox removes it
    app.act_settings({**form, "key_openai": [""]})
    assert Settings.load(home).provider_key("openai", home) == "sk-secret-xyz"
    app.act_settings({**form, "key_openai": [""], "clear_key_openai": ["1"]})
    assert Settings.load(home).provider_key("openai", home) is None


def test_settings_test_button_reports_failure_gracefully(home):
    app = _app(home)
    banner, _ = app.act_settings({
        "engine": ["custom"], "model_custom": ["m"],
        "base_url_custom": ["http://127.0.0.1:59999/v1"],
        "review_rounds": ["2"],
        "w_coverage": ["0.55"], "w_years": ["0.20"], "w_domain": ["0.10"], "w_archetype": ["0.10"],
        "do": ["test:custom"],
    })
    assert banner.startswith("✗ custom")


def test_app_detail_page_shows_defense_sheet(home):
    paths, settings = Paths.resolve(home), Settings.load(home)
    res = run_tailor(paths=paths, settings=settings, profile="default",
                     jd_text="Senior Backend Engineer\nMust have: 8+ years, Go, Kafka, Kubernetes.\n",
                     company="Acme", role="Senior Backend Engineer")
    aid = Store(paths.db).create_application(profile="default", company="Acme",
                                            role="Senior Backend Engineer", out_dir=str(res.out_dir))
    html = App(paths, settings).page_app(aid)
    assert b"Defense sheet" in html
    assert b"Before you submit" in html          # section from defense.md rendered inline
    assert b'href="/file?path=' in html and b"defense.md" in html   # also a download link


def test_settings_test_button_ok_with_mock(home):
    app = _app(home)
    banner, _ = app.act_settings({
        "engine": ["mock"], "review_rounds": ["0"],
        "w_coverage": ["0.55"], "w_years": ["0.20"], "w_domain": ["0.10"], "w_archetype": ["0.10"],
        "do": ["test:mock"],
    })
    assert banner.startswith("✓ mock OK")
