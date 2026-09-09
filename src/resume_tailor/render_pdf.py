"""PDF rendering.

Preferred: convert the generated .docx with LibreOffice headless (pixel-faithful
to the DOCX). Fallback: draw the same layout directly with fpdf2 so a PDF is
always produced even on a box without LibreOffice.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .models import ResumeLayout, SectionSpec, TailoredResume
from .render_docx import fmt_period


def _cap(items, spec: SectionSpec):
    n = spec.max_items
    return items[:n] if n and n > 0 else items


def _soffice() -> str | None:
    for name in ("libreoffice", "soffice"):
        p = shutil.which(name)
        if p:
            return p
    return None


def docx_to_pdf(docx_path: Path, out_dir: Path, timeout: int = 120) -> Path | None:
    exe = _soffice()
    if not exe:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [exe, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    pdf = out_dir / (docx_path.stem + ".pdf")
    return pdf if pdf.exists() else None


# --------------------------------------------------------------------------- #
# fpdf2 fallback
# --------------------------------------------------------------------------- #
_ACCENT = (31, 78, 121)


def _pdf(page_size: str):
    from fpdf import FPDF

    fmt = "A4" if page_size.lower() == "a4" else "Letter"
    pdf = FPDF(orientation="P", unit="mm", format=fmt)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(16, 15, 16)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    return pdf


def _clean(s: str) -> str:
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def _heading(pdf, text: str) -> None:
    pdf.ln(2.5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 6, _clean(text.upper()), new_x="LMARGIN", new_y="NEXT")
    y = pdf.get_y()
    pdf.set_draw_color(*_ACCENT)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(1.5)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=10)


def _para(pdf, text: str, size=10, style="", gap=1.5) -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.multi_cell(0, 4.6, _clean(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(gap)


def _bullet(pdf, text: str) -> None:
    pdf.set_font("Helvetica", size=10)
    x0 = pdf.get_x()
    pdf.multi_cell(4, 4.4, "-", new_x="RIGHT", new_y="TOP")
    pdf.set_x(x0 + 4)
    pdf.multi_cell(pdf.w - pdf.r_margin - (x0 + 4), 4.4, _clean(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.6)


def resume_to_pdf(tr: TailoredResume, out_path: Path, page_size: str = "letter") -> Path:
    pdf = _pdf(page_size)
    c = tr.contact

    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 8, _clean(c.name), align="C", new_x="LMARGIN", new_y="NEXT")
    title = tr.target_role or c.title
    if title:
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 5, _clean(title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    bits = [x for x in [c.email, c.phone, c.location, c.linkedin, c.website] if x]
    if bits:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(0, 4.5, _clean("  |  ".join(bits)), align="C", new_x="LMARGIN", new_y="NEXT")
    if c.work_authorization:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(0, 4.5, _clean(f"Work Authorization: {c.work_authorization}"),
                 align="C", new_x="LMARGIN", new_y="NEXT")

    def sec_summary(spec: SectionSpec) -> None:
        if not tr.summary:
            return
        _heading(pdf, spec.heading())
        _para(pdf, tr.summary, gap=2)

    def sec_skills(spec: SectionSpec) -> None:
        groups = [g for g in tr.skill_groups if g.skills]
        if not groups:
            return
        _heading(pdf, spec.heading())
        for g in groups:
            pdf.set_font("Helvetica", "B", 10)
            pdf.write(4.6, _clean(f"{g.category}: "))
            pdf.set_font("Helvetica", "", 10)
            pdf.write(4.6, _clean(", ".join(_cap(g.skills, spec))))
            pdf.ln(5.2)

    def sec_experience(spec: SectionSpec) -> None:
        if not tr.experience:
            return
        _heading(pdf, spec.heading())
        dfmt = spec.effective_date_format()
        for e in tr.experience:
            pdf.ln(1.5)
            left = e.client + (f"  -  {e.employer}" if e.employer else "")
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.cell(0, 5, _clean(left), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "I", 9.5)
            sub = e.role + (f"   |   {e.location}" if e.location else "")
            pdf.cell(0, 4.6, _clean(sub), new_x="RIGHT", new_y="TOP")
            pdf.cell(0, 4.6, _clean(fmt_period(e.start, e.end, dfmt)), align="R",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(0.8)
            if e.summary:
                _para(pdf, e.summary, size=9, style="I", gap=1)
            for b in _cap(e.bullets, spec):
                _bullet(pdf, b)

    def sec_education(spec: SectionSpec) -> None:
        if not tr.education:
            return
        _heading(pdf, spec.heading())
        for ed in _cap(tr.education, spec):
            line = ", ".join(x for x in [
                " ".join(x for x in [ed.degree, ed.field_of_study] if x),
                ed.institution, ed.location, ed.year,
            ] if x)
            _para(pdf, line, gap=1)

    def sec_certifications(spec: SectionSpec) -> None:
        if not tr.certifications:
            return
        _heading(pdf, spec.heading())
        for ct in _cap(tr.certifications, spec):
            _bullet(pdf, " - ".join(x for x in [ct.name, ct.issuer, ct.year] if x))

    def sec_custom(spec: SectionSpec) -> None:
        lines = _cap(spec.content, spec)
        if not lines:
            return
        _heading(pdf, spec.heading())
        if spec.effective_style() == "paragraph":
            for ln in lines:
                _para(pdf, ln, gap=2)
        else:
            for ln in lines:
                _bullet(pdf, ln)

    core = {
        "summary": sec_summary, "skills": sec_skills, "experience": sec_experience,
        "education": sec_education, "certifications": sec_certifications,
    }
    for spec in (tr.layout or ResumeLayout()).visible():
        (sec_custom if spec.is_custom else core.get(spec.key, lambda _s: None))(spec)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


def cover_letter_to_pdf(tr: TailoredResume, body: str, out_path: Path,
                        page_size: str = "letter") -> Path:
    from datetime import datetime

    pdf = _pdf(page_size)
    c = tr.contact
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 7, _clean(c.name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    bits = [x for x in [c.email, c.phone, c.location, c.linkedin] if x]
    if bits:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(0, 4.5, _clean("  |  ".join(bits)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, datetime.now().strftime("%B %d, %Y"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    tgt = " / ".join(x for x in [tr.target_role, tr.target_company] if x)
    if tgt:
        _para(pdf, f"Re: {tgt}", style="B", gap=2)
    for para in [p for p in body.split("\n\n") if p.strip()]:
        _para(pdf, para.strip(), gap=2.5)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
