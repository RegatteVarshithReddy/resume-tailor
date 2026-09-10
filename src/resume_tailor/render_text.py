"""Plain-text and Markdown renderers for the tailored resume.

Deterministic, no dependencies. `resume.txt` is ATS-paste / email-body friendly;
`resume.md` is for a quick readable diff or a static site. Both walk the same
`tr.layout` section order as the DOCX/PDF renderers.
"""
from __future__ import annotations

import textwrap

from .models import ResumeLayout, SectionSpec, TailoredResume
from .render_docx import fmt_period


def _cap(items, spec: SectionSpec):
    n = spec.max_items
    return items[:n] if n and n > 0 else items


def _contact_line(tr: TailoredResume, sep: str = "  |  ") -> str:
    c = tr.contact
    return sep.join(x for x in (c.email, c.phone, c.location, c.linkedin, c.website) if x)


# --------------------------------------------------------------------------- #
# plain text
# --------------------------------------------------------------------------- #
def resume_to_text(tr: TailoredResume, width: int = 78) -> str:
    c = tr.contact
    wrap = lambda s: textwrap.fill(s, width=width) if s else ""  # noqa: E731
    out: list[str] = []

    out.append(c.name or "")
    title = tr.target_role or c.title
    if title:
        out.append(title)
    if _contact_line(tr):
        out.append(_contact_line(tr))
    if c.work_authorization:
        out.append(f"Work Authorization: {c.work_authorization}")

    def heading(text: str) -> None:
        out.append("")
        out.append(text.upper())
        out.append("-" * min(width, len(text)))

    def sec_summary(spec: SectionSpec) -> None:
        if not tr.summary:
            return
        heading(spec.heading())
        out.append(wrap(tr.summary))

    def sec_skills(spec: SectionSpec) -> None:
        groups = [g for g in tr.skill_groups if g.skills]
        if not groups:
            return
        heading(spec.heading())
        for g in groups:
            out.append(wrap(f"{g.category}: " + ", ".join(_cap(g.skills, spec))))

    def sec_experience(spec: SectionSpec) -> None:
        if not tr.experience:
            return
        heading(spec.heading())
        dfmt = spec.effective_date_format()
        for e in tr.experience:
            out.append("")
            head = e.client + (f" - {e.employer}" if e.employer else "")
            out.append(head)
            sub = " | ".join(x for x in (e.role, e.location, fmt_period(e.start, e.end, dfmt)) if x)
            if sub:
                out.append(sub)
            if e.summary:
                out.append(wrap(e.summary))
            for b in _cap(e.bullets, spec):
                out.append(textwrap.fill(b, width=width, initial_indent="- ",
                                         subsequent_indent="  "))

    def sec_education(spec: SectionSpec) -> None:
        if not tr.education:
            return
        heading(spec.heading())
        for ed in _cap(tr.education, spec):
            out.append(", ".join(x for x in (
                " ".join(x for x in (ed.degree, ed.field_of_study) if x),
                ed.institution, ed.location, ed.year) if x))

    def sec_certifications(spec: SectionSpec) -> None:
        if not tr.certifications:
            return
        heading(spec.heading())
        for ct in _cap(tr.certifications, spec):
            out.append("- " + " - ".join(x for x in (ct.name, ct.issuer, ct.year) if x))

    def sec_custom(spec: SectionSpec) -> None:
        lines = _cap(spec.content, spec)
        if not lines:
            return
        heading(spec.heading())
        for ln in lines:
            out.append(wrap(ln) if spec.effective_style() == "paragraph"
                       else textwrap.fill(ln, width=width, initial_indent="- ",
                                          subsequent_indent="  "))

    core = {"summary": sec_summary, "skills": sec_skills, "experience": sec_experience,
            "education": sec_education, "certifications": sec_certifications}
    for spec in (tr.layout or ResumeLayout()).visible():
        (sec_custom if spec.is_custom else core.get(spec.key, lambda _s: None))(spec)

    return "\n".join(out).strip() + "\n"


# --------------------------------------------------------------------------- #
# markdown
# --------------------------------------------------------------------------- #
def resume_to_markdown(tr: TailoredResume) -> str:
    c = tr.contact
    out: list[str] = [f"# {c.name}".rstrip()]
    title = tr.target_role or c.title
    if title:
        out.append(f"**{title}**")
    if _contact_line(tr, " · "):
        out.append(_contact_line(tr, " · "))
    if c.work_authorization:
        out.append(f"_Work Authorization: {c.work_authorization}_")

    def sec_summary(spec: SectionSpec) -> None:
        if not tr.summary:
            return
        out.extend(["", f"## {spec.heading()}", "", tr.summary])

    def sec_skills(spec: SectionSpec) -> None:
        groups = [g for g in tr.skill_groups if g.skills]
        if not groups:
            return
        out.extend(["", f"## {spec.heading()}", ""])
        for g in groups:
            out.append(f"- **{g.category}:** " + ", ".join(_cap(g.skills, spec)))

    def sec_experience(spec: SectionSpec) -> None:
        if not tr.experience:
            return
        out.extend(["", f"## {spec.heading()}"])
        dfmt = spec.effective_date_format()
        for e in tr.experience:
            head = e.client + (f" — {e.employer}" if e.employer else "")
            sub = " | ".join(x for x in (e.role, e.location, fmt_period(e.start, e.end, dfmt)) if x)
            out.extend(["", f"### {head}", f"*{sub}*" if sub else ""])
            if e.summary:
                out.append(e.summary)
            out.append("")
            for b in _cap(e.bullets, spec):
                out.append(f"- {b}")

    def sec_education(spec: SectionSpec) -> None:
        if not tr.education:
            return
        out.extend(["", f"## {spec.heading()}", ""])
        for ed in _cap(tr.education, spec):
            out.append("- " + ", ".join(x for x in (
                " ".join(x for x in (ed.degree, ed.field_of_study) if x),
                ed.institution, ed.location, ed.year) if x))

    def sec_certifications(spec: SectionSpec) -> None:
        if not tr.certifications:
            return
        out.extend(["", f"## {spec.heading()}", ""])
        for ct in _cap(tr.certifications, spec):
            out.append("- " + " — ".join(x for x in (ct.name, ct.issuer, ct.year) if x))

    def sec_custom(spec: SectionSpec) -> None:
        lines = _cap(spec.content, spec)
        if not lines:
            return
        out.extend(["", f"## {spec.heading()}", ""])
        for ln in lines:
            out.append(ln if spec.effective_style() == "paragraph" else f"- {ln}")

    core = {"summary": sec_summary, "skills": sec_skills, "experience": sec_experience,
            "education": sec_education, "certifications": sec_certifications}
    for spec in (tr.layout or ResumeLayout()).visible():
        (sec_custom if spec.is_custom else core.get(spec.key, lambda _s: None))(spec)

    return "\n".join(line for line in out).strip() + "\n"
