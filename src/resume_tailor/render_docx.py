"""Render a TailoredResume and a cover letter to .docx.

Section order, visibility, headings and per-section formatting come from
`tr.layout` (a ResumeLayout). A profile with the default layout renders the
classic five-section resume. The same layout (and the same `ResumeStyle`
templates below) drives render_pdf's fpdf2 fallback, and LibreOffice converts
this DOCX directly to the primary PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.enum.section import WD_SECTION  # noqa: F401  (kept for compat)
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches

from .models import ResumeLayout, SectionSpec, TailoredResume

BODY_FONT = "Calibri"
BASE_SIZE = 10.5  # kept for anything still importing it; RESUME_TEMPLATES is the source of truth


# --------------------------------------------------------------------------- #
# Resume templates — named presets that trade density for page count. Every
# renderer (this file + render_pdf.py) takes a `template` key and looks up a
# ResumeStyle here; a profile's own layout (section order/visibility/max_items)
# is unaffected — templates only change type size, spacing and per-role caps.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ResumeStyle:
    label: str
    base_size: float = 10.5
    margin_in: float = 0.7
    section_gap_before: float = 8
    heading_gap_after: float = 2
    bullet_gap_after: float = 1.5
    max_bullets: int | None = None   # extra cap on bullets/role, on top of the section's own max_items
    max_skills: int | None = None    # extra cap on skills/group


RESUME_TEMPLATES: dict[str, ResumeStyle] = {
    "standard": ResumeStyle(
        label="Standard — balanced, usually ~2 pages",
    ),
    "compact": ResumeStyle(
        label="Compact — tight spacing + fewer bullets, aims for 1 page",
        base_size=9.5, margin_in=0.5, section_gap_before=5,
        heading_gap_after=1, bullet_gap_after=0.75, max_bullets=4, max_skills=10,
    ),
    "detailed": ResumeStyle(
        label="Detailed — roomier spacing, full bullet history",
        base_size=11, margin_in=0.8, section_gap_before=10,
        heading_gap_after=3, bullet_gap_after=2.5,
    ),
}
DEFAULT_TEMPLATE = "standard"
TEMPLATE_LABELS: dict[str, str] = {k: v.label for k, v in RESUME_TEMPLATES.items()}


def resolve_template(name: str | None) -> ResumeStyle:
    return RESUME_TEMPLATES.get((name or "").strip().lower()) or RESUME_TEMPLATES[DEFAULT_TEMPLATE]


def _hex_to_rgb(h: str) -> RGBColor:
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def fmt_period(start: str, end: str, date_format: str = "%b %Y") -> str:
    def one(v: str) -> str:
        v = (v or "").strip()
        if v.lower() in ("present", "current", ""):
            return "Present" if v else ""
        for f in ("%Y-%m", "%Y/%m", "%m/%Y", "%b %Y", "%B %Y", "%Y"):
            try:
                return datetime.strptime(v, f).strftime(date_format or "%b %Y")
            except ValueError:
                continue
        return v

    a, b = one(start), one(end) or "Present"
    return f"{a} – {b}" if a else b


def _base_style(doc: Document, style: ResumeStyle) -> None:
    st = doc.styles["Normal"]
    st.font.name = BODY_FONT
    st.font.size = Pt(style.base_size)
    rpr = st.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), BODY_FONT)
    rfonts.set(qn("w:hAnsi"), BODY_FONT)
    for section in doc.sections:
        section.top_margin = Inches(style.margin_in)
        section.bottom_margin = Inches(style.margin_in)
        section.left_margin = Inches(style.margin_in)
        section.right_margin = Inches(style.margin_in)


def _content_width(doc: Document):
    s = doc.sections[0]
    return s.page_width - s.left_margin - s.right_margin


def _p(doc, text="", *, size=BASE_SIZE, bold=False, italic=False, color=None,
       align=None, space_before=0, space_after=2, all_caps=False):
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(space_before)
    para.paragraph_format.space_after = Pt(space_after)
    if align is not None:
        para.alignment = align
    if text:
        run = para.add_run(text)
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color
        if all_caps:
            run.font.all_caps = True
    return para


def _section_heading(doc, title, accent, style: ResumeStyle):
    """`accent` is an (r, g, b) tuple."""
    para = _p(doc, title, size=style.base_size + 1.5, bold=True, color=RGBColor(*accent),
              space_before=style.section_gap_before, space_after=style.heading_gap_after, all_caps=True)
    pbdr = para.paragraph_format.element.get_or_add_pPr()
    bdr = pbdr.makeelement(qn("w:pBdr"), {})
    bottom = bdr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single", qn("w:sz"): "6", qn("w:space"): "1",
        qn("w:color"): "%02X%02X%02X" % (accent[0], accent[1], accent[2]),
    })
    bdr.append(bottom)
    pbdr.append(bdr)
    return para


def _bullet(doc, text, style: ResumeStyle):
    para = doc.add_paragraph(style=None)
    para.paragraph_format.left_indent = Inches(0.18)
    para.paragraph_format.space_after = Pt(style.bullet_gap_after)
    para.add_run("•  ").bold = False
    run = para.add_run(text)
    run.font.size = Pt(style.base_size)
    return para


def _cap(items, spec: SectionSpec, style: ResumeStyle, kind: str = ""):
    caps = [n for n in (spec.max_items, getattr(style, f"max_{kind}", None)) if n and n > 0]
    return items[:min(caps)] if caps else items


# --------------------------------------------------------------------------- #
# Section renderers — one per core key, plus custom
# --------------------------------------------------------------------------- #
def _sec_summary(doc, tr: TailoredResume, spec: SectionSpec, accent_t, style: ResumeStyle) -> None:
    if not tr.summary:
        return
    _section_heading(doc, spec.heading(), accent_t, style)
    _p(doc, tr.summary, size=style.base_size, space_after=4)


def _sec_skills(doc, tr: TailoredResume, spec: SectionSpec, accent_t, style: ResumeStyle) -> None:
    groups = [g for g in tr.skill_groups if g.skills]
    if not groups:
        return
    _section_heading(doc, spec.heading(), accent_t, style)
    for g in groups:
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(1.5)
        r1 = para.add_run(f"{g.category}: ")
        r1.bold = True
        r1.font.size = Pt(style.base_size)
        r2 = para.add_run(", ".join(_cap(g.skills, spec, style, kind="skills")))
        r2.font.size = Pt(style.base_size)


def _sec_experience(doc, tr: TailoredResume, spec: SectionSpec, accent_t, style: ResumeStyle) -> None:
    if not tr.experience:
        return
    _section_heading(doc, spec.heading(), accent_t, style)
    tab_x = _content_width(doc) - Pt(2)
    dfmt = spec.effective_date_format()
    for e in tr.experience:
        header = doc.add_paragraph()
        header.paragraph_format.space_before = Pt(6)
        header.paragraph_format.space_after = Pt(0)
        tabs = header.paragraph_format.tab_stops
        tabs.add_tab_stop(tab_x, alignment=WD_TAB_ALIGNMENT.RIGHT)
        left = e.client + (f"  —  {e.employer}" if e.employer else "")
        rr = header.add_run(left)
        rr.bold = True
        rr.font.size = Pt(style.base_size + 0.5)
        header.add_run("\t" + fmt_period(e.start, e.end, dfmt)).font.size = Pt(style.base_size - 0.5)

        sub = doc.add_paragraph()
        sub.paragraph_format.space_after = Pt(2)
        s2 = sub.add_run(e.role + (f"   |   {e.location}" if e.location else ""))
        s2.italic = True
        s2.font.size = Pt(style.base_size)

        if e.summary:
            _p(doc, e.summary, size=style.base_size - 0.5, italic=True, space_after=2)
        for b in _cap(e.bullets, spec, style, kind="bullets"):
            _bullet(doc, b, style)


def _sec_education(doc, tr: TailoredResume, spec: SectionSpec, accent_t, style: ResumeStyle) -> None:
    if not tr.education:
        return
    _section_heading(doc, spec.heading(), accent_t, style)
    for ed in _cap(tr.education, spec, style):
        line = ", ".join(x for x in [
            " ".join(x for x in [ed.degree, ed.field_of_study] if x),
            ed.institution, ed.location, ed.year,
        ] if x)
        _p(doc, line, size=style.base_size, space_after=1.5)


def _sec_certifications(doc, tr: TailoredResume, spec: SectionSpec, accent_t, style: ResumeStyle) -> None:
    if not tr.certifications:
        return
    _section_heading(doc, spec.heading(), accent_t, style)
    for ct in _cap(tr.certifications, spec, style):
        _bullet(doc, " — ".join(x for x in [ct.name, ct.issuer, ct.year] if x), style)


def _sec_custom(doc, spec: SectionSpec, accent_t, style: ResumeStyle) -> None:
    lines = _cap(spec.content, spec, style)
    if not lines:
        return
    _section_heading(doc, spec.heading(), accent_t, style)
    if spec.effective_style() == "paragraph":
        for ln in lines:
            _p(doc, ln, size=style.base_size, space_after=4)
    else:
        for ln in lines:
            _bullet(doc, ln, style)


_CORE_RENDERERS = {
    "summary": _sec_summary,
    "skills": _sec_skills,
    "experience": _sec_experience,
    "education": _sec_education,
    "certifications": _sec_certifications,
}


def build_resume_doc(tr: TailoredResume, accent_hex: str = "#1F4E79",
                     template: str = DEFAULT_TEMPLATE) -> Document:
    style = resolve_template(template)
    accent = _hex_to_rgb(accent_hex)
    accent_t = (accent[0], accent[1], accent[2])
    doc = Document()
    _base_style(doc, style)

    c = tr.contact
    _p(doc, c.name, size=style.base_size + 9.5, bold=True, color=accent,
       align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
    title = tr.target_role or c.title
    if title:
        _p(doc, title, size=style.base_size + 1, color=accent,
           align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    contact_bits = [x for x in [c.email, c.phone, c.location, c.linkedin, c.website] if x]
    if contact_bits:
        _p(doc, "  |  ".join(contact_bits), size=style.base_size - 1,
           align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
    if c.work_authorization:
        _p(doc, f"Work Authorization: {c.work_authorization}", size=style.base_size - 1,
           align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)

    layout = tr.layout or ResumeLayout()
    for spec in layout.visible():
        if spec.is_custom:
            _sec_custom(doc, spec, accent_t, style)
        else:
            fn = _CORE_RENDERERS.get(spec.key)
            if fn:
                fn(doc, tr, spec, accent_t, style)

    return doc


def build_cover_letter_doc(tr: TailoredResume, body: str, accent_hex: str = "#1F4E79",
                           template: str = DEFAULT_TEMPLATE) -> Document:
    style = resolve_template(template)
    accent = _hex_to_rgb(accent_hex)
    doc = Document()
    _base_style(doc, style)
    c = tr.contact
    _p(doc, c.name, size=style.base_size + 5.5, bold=True, color=accent, space_after=0)
    bits = [x for x in [c.email, c.phone, c.location, c.linkedin] if x]
    if bits:
        _p(doc, "  |  ".join(bits), size=style.base_size - 1, space_after=6)
    _p(doc, datetime.now().strftime("%B %d, %Y"), size=style.base_size, space_after=6)
    tgt = " / ".join(x for x in [tr.target_role, tr.target_company] if x)
    if tgt:
        _p(doc, f"Re: {tgt}", size=style.base_size, bold=True, space_after=6)
    for para in [p for p in body.split("\n\n") if p.strip()]:
        _p(doc, para.strip(), size=style.base_size, space_after=6)
    return doc


def save_doc(doc: Document, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path
