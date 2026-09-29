from resume_tailor.models import TailoredResume
from resume_tailor.render_docx import RESUME_TEMPLATES, build_resume_doc, resolve_template

TR = TailoredResume.from_dict({
    "contact": {"name": "Ada Lovelace", "title": "Senior Engineer",
                "email": "ada@example.com", "location": "Brooklyn, NY"},
    "target_role": "Staff Backend Engineer",
    "summary": "Backend engineer with deep distributed-systems experience.",
    "skill_groups": [{"category": "Languages", "skills": ["Go", "Python", "SQL", "Rust", "C++"]}],
    "experience": [{
        "id": "job1", "client": "Northwind", "employer": "Vendor Co",
        "role": "Lead Engineer", "location": "Remote", "start": "2021-03", "end": "present",
        "summary": "Owned the payments platform.",
        "bullets": [{"text": f"Bullet number {n}.", "source": "bullet:0"} for n in range(8)],
    }],
})


def _doc_text(doc) -> str:
    return "\n".join(p.text for p in doc.paragraphs)


def test_every_named_template_resolves_and_renders():
    for key in RESUME_TEMPLATES:
        doc = build_resume_doc(TR, template=key)
        assert "Ada Lovelace" in _doc_text(doc)


def test_unknown_template_falls_back_to_standard():
    assert resolve_template("nope") is resolve_template("standard")
    assert resolve_template(None) is resolve_template("standard")


def test_compact_caps_bullets_and_uses_smaller_type():
    standard = build_resume_doc(TR, template="standard")
    compact = build_resume_doc(TR, template="compact")
    std_bullets = sum(1 for p in standard.paragraphs if p.text.startswith("•"))
    compact_bullets = sum(1 for p in compact.paragraphs if p.text.startswith("•"))
    assert std_bullets == 8
    assert compact_bullets == RESUME_TEMPLATES["compact"].max_bullets
    assert compact.styles["Normal"].font.size < standard.styles["Normal"].font.size


def test_detailed_uses_larger_type_and_no_bullet_cap():
    detailed = build_resume_doc(TR, template="detailed")
    detailed_bullets = sum(1 for p in detailed.paragraphs if p.text.startswith("•"))
    assert detailed_bullets == 8
    assert detailed.styles["Normal"].font.size > build_resume_doc(TR).styles["Normal"].font.size
