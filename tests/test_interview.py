import json
from pathlib import Path

import pytest

from resume_tailor.config import Paths, Settings
from resume_tailor.interview import build_prep_fallback, prep_payload, render_prep
from resume_tailor.models import (
    CoverageItem,
    CoverageReport,
    GapItem,
    GapReport,
    JobRequirement,
    MasterProfile,
    TailoredResume,
)
from resume_tailor.pipeline import run_prep, run_tailor

MASTER = MasterProfile.from_dict({
    "contact": {"name": "Ada", "work_authorization": "US Citizen"},
    "meta": {"years_experience": 6},
    "experience": [{
        "id": "job1", "client": "Northwind Health", "employer": "Vendor Co",
        "role": "Data Engineer", "start": "2021-01", "end": "present",
        "bullets": ["Ran the claims ingestion pipeline in Python."],
        "bullet_library": ["Cut nightly batch time 40%."],
        "environment": ["Python", "Airflow", "PostgreSQL"],
    }],
})
TR = TailoredResume.from_dict({
    "contact": {"name": "Ada"},
    "experience": [{
        "id": "job1", "client": "Northwind Health", "start": "2021-01", "end": "present",
        "bullets": [
            {"text": "Operated Kubernetes clusters at scale.", "source": "stretch"},
            {"text": "Built ingestion in Python.", "source": "bullet:0"},
        ],
    }],
})
REQ = JobRequirement(role="Platform Engineer", company="Northwind Health",
                     employment_type="W2 contract", location="Remote",
                     archetype="tech-lead",
                     domains=["healthcare"], responsibilities=["own the ingestion platform"],
                     must_have_ranked=[{"skill": "Kubernetes", "weight": 3},
                                       {"skill": "Python", "weight": 2}],
                     min_years=8.0)
GAP = GapReport(matched=[GapItem(skill="Python", status="matched")],
                missing=[GapItem(skill="Kubernetes", status="missing")],
                years_required=8.0, years_available=4.0)
COV = CoverageReport(
    items=[CoverageItem(skill="Kubernetes", weight=3, in_skills=True),
           CoverageItem(skill="Python", weight=2, in_summary=True, in_skills=True,
                        in_bullets=["job1"])],
    gates=[{"gate": "8+ years", "verdict": "verify"}],
    stretch_bullets=[{"exp_id": "job1", "text": "Operated Kubernetes clusters at scale."}],
)


def _payload():
    return prep_payload(TR, MASTER, REQ, COV, GAP)


# -- payload ---------------------------------------------------------------
def test_payload_classifies_risk_and_carries_pivot_material():
    p = _payload()
    by_skill = {m["skill"]: m for m in p["must_haves"]}
    assert by_skill["Kubernetes"]["risk"] == "stretch"     # in gap.missing
    assert by_skill["Python"]["risk"] == "solid"           # full coverage
    assert by_skill["Kubernetes"]["weight"] == 3
    assert p["must_haves"][0]["skill"] == "Kubernetes"     # weight-3 first

    assert len(p["stretch"]) == 1
    s = p["stretch"][0]
    assert s["client"] == "Northwind Health"
    assert "Ran the claims ingestion pipeline in Python." in s["real_material"]
    assert "Airflow" in s["real_environment"]
    assert p["work_authorization"] == "US Citizen"
    assert p["years"] == {"required": 8.0, "available": 4.0, "declared": 6}


def test_payload_marks_partial_coverage_thin():
    cov = CoverageReport(items=[CoverageItem(skill="Go", weight=2, in_skills=True)])
    p = prep_payload(TR, MASTER, REQ, cov, GapReport())
    assert {m["skill"]: m["risk"] for m in p["must_haves"]}["Kubernetes"] == "thin"


# -- deterministic fallback ------------------------------------------------
def test_fallback_builds_every_section():
    d = build_prep_fallback(_payload())
    assert [c["skill"] for c in d["technical"]] == ["Kubernetes", "Python"]
    assert len(d["technical"][0]["questions"]) >= 3          # weight 3 + stretch
    assert d["stories"] and d["stories"][0]["exp_id"] == "job1"
    assert "Cut nightly batch time 40%." == d["stories"][0]["result"]   # the one with a number
    assert d["landmines"][0]["claim"] == "Operated Kubernetes clusters at scale."
    assert "Ran the claims ingestion pipeline" in d["landmines"][0]["pivot_to"]
    # archetype-specific behavioural questions, not just the generic pair
    assert any("bottleneck" in b["question"] for b in d["behavioral"])
    assert any("healthcare" in q for q in d["ask_them"])


# -- markdown --------------------------------------------------------------
def test_render_marks_risk_gates_and_years():
    p = _payload()
    md = render_prep(build_prep_fallback(p), p)
    assert "# Interview prep" in md
    assert "Platform Engineer @ Northwind Health" in md
    for heading in ("## 1. Likely technical questions", "## 2. STAR stories",
                    "## 3. Behavioural", "## 4. Screening logistics",
                    "## 5. Questions to ask them", "## 6. Landmines"):
        assert heading in md
    assert "stretch** — your profile does not back this" in md
    assert "✓ solid" in md
    assert "they want ~8, your dated timeline is ~4" in md
    assert "Gate — 8+ years** (verify)" in md
    assert "US Citizen" in md
    assert "W2 contract" in md
    assert "Operated Kubernetes clusters at scale." in md      # landmine claim
    assert "reads as **tech-lead**" in md


def test_render_clean_when_nothing_stretchy():
    cov = CoverageReport(items=[CoverageItem(skill="Python", weight=2, in_summary=True,
                                             in_skills=True, in_bullets=["job1"])])
    p = prep_payload(TR, MASTER, REQ, cov, GapReport())
    md = render_prep(build_prep_fallback(p), p)
    assert "_None — every bullet on this resume traces to real master material._" in md


# -- end to end, offline via the mock engine -------------------------------
@pytest.fixture
def tailored_run(home):
    paths, settings = Paths.resolve(), Settings.load()
    res = run_tailor(paths=paths, settings=settings, profile="default",
                     jd_text="Senior Python Engineer\n7+ years with Python, Kubernetes and AWS.",
                     make_pdf=False, review_rounds=0)
    return paths, settings, res.out_dir


def test_run_prep_end_to_end_uses_the_engine(tailored_run):
    paths, settings, od = tailored_run
    assert not (od / "interview_prep.md").exists()      # tailor must not write it

    result = run_prep(paths=paths, settings=settings, out_dir=od, profile="default")
    assert result.used_llm is True                      # mock engine answered
    assert result.areas > 0
    md = (od / "interview_prep.md").read_text()
    assert "# Interview prep" in md and "## 6. Landmines" in md
    saved = json.loads((od / "interview_prep.json").read_text())
    assert saved["used_llm"] is True and saved["data"]["technical"]


def test_run_prep_no_llm_is_deterministic(tailored_run):
    paths, settings, od = tailored_run
    result = run_prep(paths=paths, settings=settings, out_dir=od, profile="default",
                      use_llm=False)
    assert result.used_llm is False
    assert json.loads((od / "interview_prep.json").read_text())["used_llm"] is False


def test_run_prep_rejects_an_incomplete_run_dir(home, tmp_path):
    paths, settings = Paths.resolve(), Settings.load()
    empty = tmp_path / "not-a-run"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="tailored_profile.yaml"):
        run_prep(paths=paths, settings=settings, out_dir=empty, profile="default")


def test_run_prep_falls_back_when_the_model_misbehaves(tailored_run, monkeypatch):
    paths, settings, od = tailored_run

    class Broken:
        name, model = "broken", "x"

        def complete_json(self, system, prompt):
            raise RuntimeError("nope")

    monkeypatch.setattr("resume_tailor.pipeline.get_engine", lambda *a, **k: Broken())
    result = run_prep(paths=paths, settings=settings, out_dir=od, profile="default")
    assert result.used_llm is False
    assert (od / "interview_prep.md").exists()          # still written


# -- web -------------------------------------------------------------------
def test_app_page_offers_prep_then_shows_it(tailored_run):
    from resume_tailor.store import Store
    from resume_tailor.webapp import App

    paths, settings, od = tailored_run
    store = Store(paths.db)
    aid = store.create_application(profile="default", company="Northwind", role="Platform Engineer",
                                   mode="aggressive", out_dir=str(od))
    app = App(paths, settings)

    html = app.page_app(aid).decode()
    assert "Generate interview prep" in html

    run_prep(paths=paths, settings=settings, out_dir=od, profile="default")
    html = app.page_app(aid).decode()
    assert "# Interview prep" in html and "Regenerate" in html
    assert "interview_prep.md" in html                  # download link

    store.update_application(aid, status="screening")
    assert Path(app.store.get_application(aid)["out_dir"]) == od
