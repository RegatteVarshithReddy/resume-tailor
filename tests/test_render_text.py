from resume_tailor.models import TailoredResume
from resume_tailor.render_text import resume_to_markdown, resume_to_text

TR = TailoredResume.from_dict({
    "contact": {"name": "Ada Lovelace", "title": "Senior Engineer",
                "email": "ada@example.com", "location": "Brooklyn, NY"},
    "target_role": "Staff Backend Engineer",
    "summary": "Backend engineer with deep distributed-systems experience.",
    "skill_groups": [{"category": "Languages", "skills": ["Go", "Python", "SQL"]}],
    "experience": [{
        "id": "job1", "client": "Northwind", "employer": "Vendor Co",
        "role": "Lead Engineer", "location": "Remote", "start": "2021-03", "end": "present",
        "summary": "Owned the payments platform.",
        "bullets": [{"text": "Built an event-driven service on Kafka.", "source": "bullet:0"}],
    }],
})


def test_plain_text_shape():
    txt = resume_to_text(TR)
    assert txt.startswith("Ada Lovelace")
    assert "Staff Backend Engineer" in txt          # target role wins over contact title
    assert "PROFESSIONAL SUMMARY" in txt            # uppercase heading
    assert "Languages: Go, Python, SQL" in txt
    assert "- Built an event-driven service on Kafka." in txt
    assert "Northwind - Vendor Co" in txt
    assert txt.endswith("\n")


def test_markdown_shape():
    md = resume_to_markdown(TR)
    assert md.startswith("# Ada Lovelace")
    assert "## Professional Summary" in md
    assert "### Northwind — Vendor Co" in md
    assert "- **Languages:** Go, Python, SQL" in md
    assert "- Built an event-driven service on Kafka." in md


def test_empty_sections_are_skipped():
    tr = TailoredResume.from_dict({"contact": {"name": "X"}})
    txt, md = resume_to_text(tr), resume_to_markdown(tr)
    assert "EDUCATION" not in txt and "## Education" not in md
