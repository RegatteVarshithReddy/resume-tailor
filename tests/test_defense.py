from resume_tailor.defense import build_defense
from resume_tailor.models import (
    CoverageItem,
    CoverageReport,
    GapItem,
    GapReport,
    JobRequirement,
    MasterProfile,
    TailoredResume,
)

MASTER = MasterProfile.from_dict({
    "contact": {"name": "Ada"},
    "experience": [{
        "id": "job1", "client": "Northwind Health", "employer": "Vendor Co",
        "start": "2021-01", "end": "present",
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
                     must_have_ranked=[{"skill": "Kubernetes", "weight": 3},
                                       {"skill": "Go", "weight": 2}],
                     min_years=8.0)
GAP = GapReport(missing=[GapItem(skill="Kubernetes", status="missing"),
                         GapItem(skill="Go", status="missing")],
                years_required=8.0, years_available=4.0)
COV = CoverageReport(
    items=[CoverageItem(skill="Kubernetes", weight=3, in_skills=True),
           CoverageItem(skill="Go", weight=2)],
    gates=[{"gate": "active TS/SCI clearance", "verdict": "unmet"},
           {"gate": "8+ years", "verdict": "verify"}],
    stretch_bullets=[{"exp_id": "job1", "text": "Operated Kubernetes clusters at scale."}],
)


def test_defense_flags_stretch_with_real_pivot_material():
    md = build_defense(TR, GAP, COV, REQ, MASTER)
    assert "## 1. Stretch bullets (1)" in md
    assert "Operated Kubernetes clusters at scale." in md
    assert "### Northwind Health" in md
    assert "Ran the claims ingestion pipeline in Python." in md    # pivot material from master
    assert "Real environment:" in md and "Airflow" in md


def test_defense_lists_gates_gaps_and_years():
    md = build_defense(TR, GAP, COV, REQ, MASTER)
    assert "active TS/SCI clearance** — unmet" in md
    assert "8+ years** — verify" in md
    assert "Must-haves not in your master profile" in md and "**Kubernetes**" in md
    assert "Experience shortfall" in md and "4-yr gap" in md
    assert "Thin coverage" in md and "**Kubernetes** (weight 3) — only in skills" in md


def test_defense_clean_when_nothing_risky():
    md = build_defense(TR, GapReport(), CoverageReport(), REQ, MASTER)
    assert "_None — every bullet traces to real master material._" in md
    assert "_None flagged._" in md
