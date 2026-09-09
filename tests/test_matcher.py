"""Deterministic matcher — no AI, no network."""
from resume_tailor.matcher import build_gap_report, heuristic_parse_jd, match_skill
from resume_tailor.models import JobRequirement, MasterProfile

JD = """Senior Data Engineer
Must have: 6+ years, Python, Apache Airflow, Snowflake, dbt, AWS.
Nice to have: Kafka, Terraform.
US citizen required.
"""


def test_heuristic_parse_pulls_years_skills_gates():
    req = heuristic_parse_jd(JD)
    assert req.min_years == 6.0
    lowered = {s.lower() for s in req.must_have_skills}
    assert {"python", "airflow", "snowflake", "aws"} <= lowered
    assert any("year" in g.lower() for g in req.hard_gates)


def test_match_skill_aliases_and_fuzz():
    pool = {"postgresql", "kubernetes", "ci/cd"}
    toks = {t for p in pool for t in p.split()}
    assert match_skill("Postgres", pool, toks)[0] == "matched"   # alias
    assert match_skill("k8s", pool, toks)[0] == "matched"        # alias
    assert match_skill("Rust", pool, toks)[0] == "missing"


def test_build_gap_report_partitions_skills():
    master = MasterProfile.from_dict({
        "contact": {"name": "T"},
        "skill_groups": [{"category": "x", "skills": ["Python", "AWS", "Airflow"]}],
        "experience": [],
    })
    req = JobRequirement(must_have_skills=["Python", "AWS", "Airflow", "Snowflake", "dbt"])
    gap = build_gap_report(master, req)
    got = {g.skill for g in gap.matched}
    assert {"Python", "AWS", "Airflow"} <= got
    assert {g.skill for g in gap.missing} >= {"Snowflake", "dbt"}
