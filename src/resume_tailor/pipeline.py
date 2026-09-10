"""End-to-end tailoring pipeline shared by the CLI and the web UI.

Per run:  extract requirements (1 AI call) -> deterministic gap analysis ->
draft resume+cover letter (1 AI call) -> self-review revise x`review_rounds`
(review_rounds AI calls) -> deterministic coverage map + match score -> render.
`variants` runs the draft+review+score sequence once per angle and writes a
comparison.md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .config import DEFAULT_PROFILE, Paths, Settings
from .llm import Engine, get_engine
from .matcher import (
    build_gap_report,
    check_coverage,
    heuristic_parse_jd,
    score_match,
    select_profile,
)
from .models import (
    CoverageReport,
    GapReport,
    JobRequirement,
    MasterProfile,
    MatchScore,
    TailoredResume,
)
from .profile_io import dump_tailored, load_master
from .prompts import (
    CRITIQUE_SYSTEM,
    EXTRACT_SYSTEM,
    TAILOR_SYSTEM,
    critique_prompt,
    extract_prompt,
    tailor_prompt,
)
from .defense import build_defense
from .render_docx import build_cover_letter_doc, build_resume_doc, save_doc
from .render_pdf import cover_letter_to_pdf, docx_to_pdf, resume_to_pdf
from .render_text import resume_to_markdown, resume_to_text
from .validate import lock_invariants

# angle name -> (aggressive?, archetype override or None)
VARIANT_ANGLES = {
    "aggressive": (True, None),
    "conservative": (False, None),
    "ic": (True, "ic"),
    "lead": (True, "tech-lead"),
}


@dataclass
class VariantResult:
    angle: str
    out_dir: Path
    match: MatchScore
    coverage: CoverageReport


@dataclass
class TailorResult:
    out_dir: Path
    req: JobRequirement
    gap: GapReport
    tailored: TailoredResume
    warnings: list[str] = field(default_factory=list)
    files: dict[str, Path] = field(default_factory=dict)
    pdf_engine: str = "none"
    profile: str = DEFAULT_PROFILE
    mode: str = "aggressive"
    route_reason: str = ""
    coverage: CoverageReport | None = None
    match: MatchScore | None = None
    variants: list[VariantResult] = field(default_factory=list)


def _slug(s: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (s or "").strip()).strip("-").lower()
    return s or fallback


def read_jd(jd_file: str | None, jd_text: str | None) -> str:
    if jd_text and jd_text.strip():
        return jd_text.strip()
    if jd_file:
        p = Path(jd_file).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"JD file not found: {p}")
        return p.read_text().strip()
    raise ValueError("No job description provided (use --jd FILE or --jd-text).")


def extract_requirement(engine: Engine, raw_jd: str, use_llm: bool = True) -> JobRequirement:
    if not use_llm:
        return heuristic_parse_jd(raw_jd)
    data = engine.complete_json(EXTRACT_SYSTEM, extract_prompt(raw_jd))
    req = JobRequirement.from_dict(data)
    req.raw_text = raw_jd
    if not req.must_have_skills and not req.nice_to_have_skills:
        h = heuristic_parse_jd(raw_jd)
        req.must_have_skills = h.must_have_skills
        req.must_have_ranked = h.must_have_ranked
        req.hard_gates = req.hard_gates or h.hard_gates
        req.min_years = req.min_years or h.min_years
    return req


# --------------------------------------------------------------------------- #
# One tailored resume: draft -> self-review -> lock
# --------------------------------------------------------------------------- #
def _draft_payload(tr: TailoredResume) -> dict:
    """The editable slice fed back into the critique call (matches tailor output shape)."""
    return {
        "target_company": tr.target_company,
        "target_role": tr.target_role,
        "summary": tr.summary,
        "skill_groups": [{"category": g.category, "skills": list(g.skills)} for g in tr.skill_groups],
        "experience": [
            {
                "id": e.id,
                "role": e.role,
                "summary": e.summary,
                "bullets": [
                    {"text": t, "source": (e.bullet_sources[i] if i < len(e.bullet_sources) else "")}
                    for i, t in enumerate(e.bullets)
                ],
            }
            for e in tr.experience
        ],
        "cover_letter": tr.cover_letter,
    }


def _finish(tr: TailoredResume, master: MasterProfile, req: JobRequirement) -> list[str]:
    tr.target_company = tr.target_company or req.company or req.vendor
    tr.target_role = tr.target_role or req.role
    warnings = lock_invariants(master, tr)
    tr.layout = master.layout
    tr.declared_years = master.meta.years_experience
    return warnings


def generate_tailored(
    engine: Engine,
    master: MasterProfile,
    req: JobRequirement,
    gap: GapReport,
    *,
    aggressive: bool,
    max_bullets: int,
) -> tuple[TailoredResume, list[str]]:
    data = engine.complete_json(
        TAILOR_SYSTEM,
        tailor_prompt(master, req, gap, aggressive=aggressive, max_bullets=max_bullets),
    )
    tr = TailoredResume.from_dict(data)
    warnings = _finish(tr, master, req)
    return tr, warnings


def review_tailored(
    engine: Engine,
    tr: TailoredResume,
    master: MasterProfile,
    req: JobRequirement,
    gap: GapReport,
    *,
    rounds: int,
    aggressive: bool,
    max_bullets: int,
    say=lambda _m: None,
) -> tuple[TailoredResume, list[str]]:
    best, best_cov = tr, check_coverage(tr, req)
    best_key = (best_cov.coverage_fraction(), -len(best_cov.stretch_bullets))
    all_warnings: list[str] = []
    for n in range(1, rounds + 1):
        cov = check_coverage(best, req)
        unmet = [g for g in cov.gates if g["verdict"] == "unmet"]
        if not cov.gaps() and not unmet and not cov.stretch_bullets:
            say(f"self-review round {n}/{rounds}: converged, nothing to fix")
            break
        say(f"self-review round {n}/{rounds} (AI call)")
        data = engine.complete_json(
            CRITIQUE_SYSTEM,
            critique_prompt(_draft_payload(best), req, gap, cov,
                            max_bullets=max_bullets, aggressive=aggressive),
        )
        cand = TailoredResume.from_dict(data)
        w = _finish(cand, master, req)
        cand_cov = check_coverage(cand, req)
        cand_key = (cand_cov.coverage_fraction(), -len(cand_cov.stretch_bullets))
        if cand_key >= best_key:
            best, best_cov, best_key = cand, cand_cov, cand_key
            all_warnings = w
    return best, all_warnings


# --------------------------------------------------------------------------- #
# Write one full output set into a directory
# --------------------------------------------------------------------------- #
def _write_set(
    od: Path,
    *,
    raw_jd: str,
    req: JobRequirement,
    gap: GapReport,
    tailored: TailoredResume,
    coverage: CoverageReport,
    match: MatchScore,
    warnings: list[str],
    settings: Settings,
    make_pdf: bool | None,
    master: MasterProfile | None = None,
) -> tuple[dict[str, Path], str]:
    od.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    (od / "job.txt").write_text(raw_jd)
    files["job"] = od / "job.txt"
    (od / "requirements.json").write_text(json.dumps(vars(req), indent=2, default=str))
    files["requirements"] = od / "requirements.json"
    (od / "gap_report.md").write_text(gap.to_markdown(req))
    files["gap_report"] = od / "gap_report.md"
    (od / "coverage.md").write_text(coverage.to_markdown(req))
    files["coverage"] = od / "coverage.md"
    (od / "match.md").write_text(match.to_markdown(req))
    files["match"] = od / "match.md"
    (od / "match.json").write_text(json.dumps({
        "score": match.score, "breakdown": match.breakdown, "weak_points": match.weak_points,
    }, indent=2))
    (od / "coverage.json").write_text(json.dumps({
        "fraction": round(coverage.coverage_fraction(), 4),
        "full": sum(1 for i in coverage.items if i.status == "full"),
        "total": len(coverage.items),
        "stretch": len(coverage.stretch_bullets),
        "gaps": [{"skill": i.skill, "weight": i.weight, "status": i.status} for i in coverage.gaps()],
        "gates": coverage.gates,
    }, indent=2))
    dump_tailored(tailored, od / "tailored_profile.yaml")
    files["tailored_profile"] = od / "tailored_profile.yaml"
    if warnings:
        (od / "warnings.txt").write_text("\n".join(warnings))
        files["warnings"] = od / "warnings.txt"
    if master is not None:
        (od / "defense.md").write_text(build_defense(tailored, gap, coverage, req, master))
        files["defense"] = od / "defense.md"

    (od / "resume.txt").write_text(resume_to_text(tailored))
    files["resume_txt"] = od / "resume.txt"
    (od / "resume.md").write_text(resume_to_markdown(tailored))
    files["resume_md"] = od / "resume.md"

    accent = settings.accent_color
    resume_docx = save_doc(build_resume_doc(tailored, accent), od / "resume.docx")
    files["resume_docx"] = resume_docx
    cl_body = tailored.cover_letter or ""
    cover_docx = save_doc(build_cover_letter_doc(tailored, cl_body, accent), od / "cover_letter.docx")
    files["cover_letter_docx"] = cover_docx
    (od / "cover_letter.txt").write_text(cl_body)
    files["cover_letter_txt"] = od / "cover_letter.txt"

    pdf_engine = "none"
    want_pdf = settings.make_pdf if make_pdf is None else make_pdf
    if want_pdf:
        r_pdf = docx_to_pdf(resume_docx, od)
        c_pdf = docx_to_pdf(cover_docx, od)
        if r_pdf and c_pdf:
            pdf_engine = "libreoffice"
            files["resume_pdf"], files["cover_letter_pdf"] = r_pdf, c_pdf
        else:
            pdf_engine = "fpdf2"
            files["resume_pdf"] = resume_to_pdf(tailored, od / "resume.pdf", settings.page_size)
            files["cover_letter_pdf"] = cover_letter_to_pdf(
                tailored, cl_body, od / "cover_letter.pdf", settings.page_size
            )
    return files, pdf_engine


def _one_angle(
    engine: Engine,
    master: MasterProfile,
    base_req: JobRequirement,
    gap: GapReport,
    *,
    angle: str,
    aggressive: bool,
    max_bullets: int,
    review_rounds: int,
    od: Path,
    settings: Settings,
    make_pdf: bool | None,
    say,
) -> tuple[TailoredResume, CoverageReport, MatchScore, dict[str, Path], list[str], str]:
    agg, arch_override = VARIANT_ANGLES.get(angle, (aggressive, None))
    req = base_req
    if arch_override:
        req = JobRequirement.from_dict({**vars(base_req)})
        req.archetype = arch_override
        req.raw_text = base_req.raw_text

    say(f"[{angle}] drafting (AI call)")
    tr, warnings = generate_tailored(engine, master, req, gap,
                                     aggressive=agg, max_bullets=max_bullets)
    if review_rounds > 0:
        tr, rw = review_tailored(engine, tr, master, req, gap, rounds=review_rounds,
                                 aggressive=agg, max_bullets=max_bullets, say=say)
        warnings = rw or warnings

    coverage = check_coverage(tr, req)
    match = score_match(gap, coverage, req, master, settings.match_weights)
    say(f"[{angle}] coverage {round(coverage.coverage_fraction() * 100)}% · match {match.score}/100")
    files, pdf_engine = _write_set(
        od, raw_jd=base_req.raw_text, req=req, gap=gap, tailored=tr,
        coverage=coverage, match=match, warnings=warnings, settings=settings, make_pdf=make_pdf,
        master=master,
    )
    return tr, coverage, match, files, warnings, pdf_engine


def _comparison_md(variants: list[VariantResult], req: JobRequirement) -> str:
    lines = ["# Variant comparison", ""]
    lines += [f"**Target:** {req.role or '?'} @ {req.company or req.vendor or '?'}", ""]
    lines += ["| Angle | Match | Must-have coverage | Stretch bullets |",
              "|---|---|---|---|"]
    for v in variants:
        lines.append(f"| {v.angle} | {v.match.score}/100 | "
                     f"{round(v.coverage.coverage_fraction() * 100)}% | "
                     f"{len(v.coverage.stretch_bullets)} |")
    lines.append("")
    best = sorted(variants, key=lambda v: (-v.match.score, len(v.coverage.stretch_bullets)))[0]
    lines += ["## Recommendation", "",
              f"**{best.angle}** — highest match ({best.match.score}/100) with "
              f"{len(best.coverage.stretch_bullets)} stretch bullet(s). "
              f"Files in `{best.out_dir.name}/`.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run_tailor(
    *,
    paths: Paths,
    settings: Settings,
    profile: str = DEFAULT_PROFILE,
    jd_file: str | None = None,
    jd_text: str | None = None,
    company: str | None = None,
    role: str | None = None,
    engine_name: str | None = None,
    model: str | None = None,
    aggressive: bool = True,
    max_bullets: int = 6,
    make_pdf: bool | None = None,
    out_dir: str | None = None,
    review_rounds: int | None = None,
    variants: list[str] | None = None,
    progress=None,
) -> TailorResult:
    def _say(msg: str) -> None:
        if progress:
            progress(msg)

    rounds = settings.review_rounds if review_rounds is None else max(0, int(review_rounds))
    angles = [a for a in (variants or []) if a in VARIANT_ANGLES]

    raw_jd = read_jd(jd_file, jd_text)
    engine = get_engine(settings, engine_name, model=model)
    _say(f"engine: {engine.name} · model: {getattr(engine, 'model', None) or 'engine default'}")

    _say("extracting requirements from JD (AI call)")
    req = extract_requirement(engine, raw_jd, use_llm=True)
    if company:
        req.company = company
    if role:
        req.role = role

    chosen, reason = select_profile(paths, req, profile)
    if (profile or "").lower() in ("", "auto"):
        _say(f"auto-selected profile '{chosen}' — {reason}")
    else:
        _say(f"loading profile '{chosen}'")
    master = load_master(paths, chosen)

    _say("running gap analysis")
    gap = build_gap_report(master, req)

    comp = _slug(company or req.company or req.vendor, "vendor")
    rl = _slug(role or req.role, "role")
    folder = out_dir or f"{comp}_{rl}_{date.today().isoformat()}"
    od = paths.outputs / folder
    if od.exists() and not out_dir:
        folder = f"{comp}_{rl}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        od = paths.outputs / folder
    od.mkdir(parents=True, exist_ok=True)

    if not angles:
        tr, coverage, match, files, warnings, pdf_engine = _one_angle(
            engine, master, req, gap,
            angle=("aggressive" if aggressive else "conservative"),
            aggressive=aggressive, max_bullets=max_bullets, review_rounds=rounds,
            od=od, settings=settings, make_pdf=make_pdf, say=_say,
        )
        _say("done")
        return TailorResult(
            out_dir=od, req=req, gap=gap, tailored=tr, warnings=warnings, files=files,
            pdf_engine=pdf_engine, profile=chosen,
            mode="aggressive" if aggressive else "conservative", route_reason=reason,
            coverage=coverage, match=match,
        )

    variant_results: list[VariantResult] = []
    by_angle: dict[str, tuple] = {}
    for angle in angles:
        vod = od / angle
        got = _one_angle(
            engine, master, req, gap, angle=angle,
            aggressive=aggressive, max_bullets=max_bullets, review_rounds=rounds,
            od=vod, settings=settings, make_pdf=make_pdf, say=_say,
        )
        by_angle[angle] = got
        variant_results.append(VariantResult(angle=angle, out_dir=vod, match=got[2], coverage=got[1]))

    (od / "comparison.md").write_text(_comparison_md(variant_results, req))
    ranked = sorted(variant_results,
                    key=lambda v: (-v.match.score, len(v.coverage.stretch_bullets)))
    best = ranked[0]
    variant_results = [next(v for v in variant_results if v.angle == best.angle)] + \
                      [v for v in variant_results if v.angle != best.angle]
    tr, coverage, match, files, warnings, pdf_engine = by_angle[best.angle]
    # surface the recommended variant at the run root (user can Promote another later)
    import shutil
    for f in best.out_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, od / f.name)
    files = {**files, "comparison": od / "comparison.md"}
    _say(f"done · recommended variant: {best.angle}")
    return TailorResult(
        out_dir=od, req=req, gap=gap, tailored=tr, warnings=warnings, files=files,
        pdf_engine=pdf_engine, profile=chosen, mode="variants", route_reason=reason,
        coverage=coverage, match=match, variants=variant_results,
    )


def rerender(
    *, paths: Paths, settings: Settings, tailored_yaml: str, make_pdf: bool | None = None
) -> TailorResult:
    from .profile_io import load_tailored

    tr = load_tailored(Path(tailored_yaml).expanduser())
    od = Path(tailored_yaml).expanduser().parent
    accent = settings.accent_color
    files: dict[str, Path] = {}
    resume_docx = save_doc(build_resume_doc(tr, accent), od / "resume.docx")
    cover_docx = save_doc(build_cover_letter_doc(tr, tr.cover_letter, accent), od / "cover_letter.docx")
    files["resume_docx"] = resume_docx
    files["cover_letter_docx"] = cover_docx
    (od / "resume.txt").write_text(resume_to_text(tr))
    (od / "resume.md").write_text(resume_to_markdown(tr))
    files["resume_txt"], files["resume_md"] = od / "resume.txt", od / "resume.md"
    pdf_engine = "none"
    want_pdf = settings.make_pdf if make_pdf is None else make_pdf
    if want_pdf:
        r_pdf = docx_to_pdf(resume_docx, od)
        c_pdf = docx_to_pdf(cover_docx, od)
        if r_pdf and c_pdf:
            pdf_engine = "libreoffice"
            files["resume_pdf"], files["cover_letter_pdf"] = r_pdf, c_pdf
        else:
            pdf_engine = "fpdf2"
            files["resume_pdf"] = resume_to_pdf(tr, od / "resume.pdf", settings.page_size)
            files["cover_letter_pdf"] = cover_letter_to_pdf(
                tr, tr.cover_letter, od / "cover_letter.pdf", settings.page_size
            )
    return TailorResult(
        out_dir=od, req=JobRequirement(), gap=GapReport(), tailored=tr,
        warnings=[], files=files, pdf_engine=pdf_engine,
    )
