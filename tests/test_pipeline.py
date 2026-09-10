"""End-to-end run through the mock engine + the invariant lock."""
import yaml

from resume_tailor.config import Paths, Settings
from resume_tailor.pipeline import run_tailor

JOB = """Senior Backend Engineer (Contract)
Must have: 8+ years, Python, Go, Apache Kafka, Kubernetes, PostgreSQL, AWS, CI/CD.
Nice to have: Terraform.
"""


def test_run_tailor_produces_full_output_set(home):
    paths, settings = Paths.resolve(home), Settings.load(home)
    res = run_tailor(paths=paths, settings=settings, profile="default",
                     jd_text=JOB, company="Acme", role="Senior Backend Engineer")
    for name in ("resume.docx", "resume.txt", "resume.md", "cover_letter.docx", "defense.md",
                 "match.md", "coverage.md", "gap_report.md", "tailored_profile.yaml",
                 "requirements.json"):
        assert (res.out_dir / name).exists(), name
    assert (res.out_dir / "resume.txt").read_text().strip()      # non-empty
    assert "# Defense sheet" in (res.out_dir / "defense.md").read_text()
    assert res.match is not None and 0 <= res.match.score <= 100
    assert res.coverage is not None


def test_invariants_locked_against_master(home):
    master = yaml.safe_load(
        (home / "profile" / "profiles" / "default" / "master_profile.yaml").read_text()
    )
    locked = {(e["client"], e["start"], e["end"]) for e in master["experience"]}

    res = run_tailor(paths=Paths.resolve(home), settings=Settings.load(home),
                     profile="default", jd_text=JOB)
    tr = yaml.safe_load((res.out_dir / "tailored_profile.yaml").read_text())
    got = {(e["client"], e["start"], e["end"]) for e in tr["experience"]}
    assert got == locked                      # clients + dates unchanged
    assert len(tr["experience"]) == len(master["experience"])


def test_mock_engine_needs_no_key_or_network(home, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("network used")))
    run_tailor(paths=Paths.resolve(home), settings=Settings.load(home),
               profile="default", jd_text=JOB)
