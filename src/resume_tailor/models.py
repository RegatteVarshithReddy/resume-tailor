"""Plain-dataclass data models (no pydantic, so it runs on brand-new Python builds).

Locked fields — never changed by tailoring:
    Experience.client, Experience.employer, Experience.location,
    Experience.start, Experience.end
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def _lines(v: Any) -> list[str]:
    """Like _list but splits strings on newlines, not commas (for prose bullets)."""
    if v is None:
        return []
    if isinstance(v, str):
        return [ln.strip() for ln in v.splitlines() if ln.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def _float_or_none(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _int_or_none(v: Any) -> int | None:
    try:
        return int(float(v)) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Master profile
# --------------------------------------------------------------------------- #
@dataclass
class Contact:
    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    website: str = ""
    work_authorization: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Contact":
        d = d or {}
        return cls(
            name=_s(d.get("name")),
            title=_s(d.get("title")),
            email=_s(d.get("email")),
            phone=_s(d.get("phone")),
            location=_s(d.get("location")),
            linkedin=_s(d.get("linkedin")),
            website=_s(d.get("website")),
            work_authorization=_s(d.get("work_authorization")),
        )


@dataclass
class SkillGroup:
    category: str = ""
    skills: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "SkillGroup":
        return cls(category=_s(d.get("category")), skills=_list(d.get("skills")))


@dataclass
class Education:
    degree: str = ""
    field_of_study: str = ""
    institution: str = ""
    location: str = ""
    year: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Education":
        return cls(
            degree=_s(d.get("degree")),
            field_of_study=_s(d.get("field") or d.get("field_of_study")),
            institution=_s(d.get("institution")),
            location=_s(d.get("location")),
            year=_s(d.get("year")),
        )


@dataclass
class Certification:
    name: str = ""
    issuer: str = ""
    year: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Certification":
        return cls(name=_s(d.get("name")), issuer=_s(d.get("issuer")), year=_s(d.get("year")))


# --------------------------------------------------------------------------- #
# Per-profile metadata + resume section layout
# --------------------------------------------------------------------------- #
CORE_SECTIONS = ("summary", "skills", "experience", "education", "certifications")

_DEFAULT_TITLES = {
    "summary": "Professional Summary",
    "skills": "Technical Skills",
    "experience": "Professional Experience",
    "education": "Education",
    "certifications": "Certifications",
}
_DEFAULT_STYLES = {
    "summary": "paragraph",
    "skills": "grouped",
    "experience": "bullets",
    "education": "list",
    "certifications": "bullets",
}


@dataclass
class ProfileMeta:
    """Per-profile metadata: picker label, role family (for JD auto-routing),
    declared years of experience, seniority hint."""

    label: str = ""
    role_family: list[str] = field(default_factory=list)
    years_experience: float | None = None
    seniority: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict | None) -> "ProfileMeta":
        d = d or {}
        return cls(
            label=_s(d.get("label")),
            role_family=_list(d.get("role_family")),
            years_experience=_float_or_none(d.get("years_experience")),
            seniority=_s(d.get("seniority")),
            notes=_s(d.get("notes")),
        )

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "role_family": list(self.role_family),
            "years_experience": self.years_experience,
            "seniority": self.seniority,
            "notes": self.notes,
        }

    def is_empty(self) -> bool:
        return not (
            self.label or self.role_family or self.seniority or self.notes
            or self.years_experience is not None
        )


@dataclass
class SectionSpec:
    """One resume section: a core key (summary|skills|experience|education|
    certifications) or 'custom:<slug>'. Order in ResumeLayout.sections is render order."""

    key: str = ""
    title: str = ""                   # heading override; "" -> default for core keys
    show: bool = True
    style: str = ""                   # paragraph|grouped|bullets|list (per section type)
    max_items: int | None = None      # cap bullets / skills / entries
    date_format: str = ""             # experience only, strftime; "" -> "%b %Y"
    content: list[str] = field(default_factory=list)   # custom sections only

    @property
    def is_custom(self) -> bool:
        return self.key.startswith("custom:")

    def heading(self) -> str:
        if self.title:
            return self.title
        if self.is_custom:
            return self.key.split(":", 1)[1].replace("-", " ").replace("_", " ").title()
        return _DEFAULT_TITLES.get(self.key, self.key.title())

    def effective_style(self) -> str:
        return self.style or _DEFAULT_STYLES.get(self.key, "bullets")

    def effective_date_format(self) -> str:
        return self.date_format or "%b %Y"

    @classmethod
    def from_dict(cls, d: dict) -> "SectionSpec":
        d = d or {}
        show = d.get("show", True)
        if isinstance(show, str):
            show = show.strip().lower() not in ("false", "0", "no", "off", "")
        return cls(
            key=_s(d.get("key")),
            title=_s(d.get("title")),
            show=bool(show),
            style=_s(d.get("style")),
            max_items=_int_or_none(d.get("max_items")),
            date_format=_s(d.get("date_format")),
            content=_lines(d.get("content")),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"key": self.key, "show": self.show}
        if self.title:
            out["title"] = self.title
        if self.style:
            out["style"] = self.style
        if self.max_items is not None:
            out["max_items"] = self.max_items
        if self.date_format:
            out["date_format"] = self.date_format
        if self.is_custom:
            out["content"] = list(self.content)
        return out


def _default_sections() -> list[SectionSpec]:
    # bare keys — effective_style()/effective_date_format() supply the per-key
    # defaults at render time, so a pristine layout round-trips to no `layout:` block
    return [SectionSpec(key=k) for k in CORE_SECTIONS]


@dataclass
class ResumeLayout:
    sections: list[SectionSpec] = field(default_factory=_default_sections)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ResumeLayout":
        if not d or not d.get("sections"):
            return cls()
        secs = [SectionSpec.from_dict(x) for x in d["sections"] if _s((x or {}).get("key"))]
        return cls(sections=secs or _default_sections())

    def to_dict(self) -> dict:
        return {"sections": [s.to_dict() for s in self.sections]}

    def visible(self) -> list["SectionSpec"]:
        return [s for s in self.sections if s.show]

    def is_default(self) -> bool:
        return self.to_dict() == ResumeLayout().to_dict()


@dataclass
class Experience:
    id: str = ""
    client: str = ""              # LOCKED
    employer: str = ""            # LOCKED (implementation partner / staffing vendor)
    role: str = ""
    location: str = ""            # LOCKED
    start: str = ""               # LOCKED  "YYYY-MM"
    end: str = ""                 # LOCKED  "YYYY-MM" or "Present"
    environment: list[str] = field(default_factory=list)
    summary: str = ""
    bullets: list[str] = field(default_factory=list)
    bullet_library: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, idx: int = 0) -> "Experience":
        return cls(
            id=_s(d.get("id")) or f"exp{idx + 1}",
            client=_s(d.get("client")),
            employer=_s(d.get("employer") or d.get("vendor")),
            role=_s(d.get("role") or d.get("title")),
            location=_s(d.get("location")),
            start=_s(d.get("start")),
            end=_s(d.get("end")) or "Present",
            environment=_list(d.get("environment")),
            summary=_s(d.get("summary")),
            bullets=_list(d.get("bullets")),
            bullet_library=_list(d.get("bullet_library")),
        )


@dataclass
class MasterProfile:
    contact: Contact = field(default_factory=Contact)
    summary: str = ""
    skill_groups: list[SkillGroup] = field(default_factory=list)
    experience: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    certifications: list[Certification] = field(default_factory=list)
    extra_bullets: list[str] = field(default_factory=list)
    meta: ProfileMeta = field(default_factory=ProfileMeta)
    layout: ResumeLayout = field(default_factory=ResumeLayout)

    @classmethod
    def from_dict(cls, d: dict) -> "MasterProfile":
        d = d or {}
        return cls(
            contact=Contact.from_dict(d.get("contact", {})),
            summary=_s(d.get("summary")),
            skill_groups=[SkillGroup.from_dict(x) for x in (d.get("skill_groups") or [])],
            experience=[Experience.from_dict(x, i) for i, x in enumerate(d.get("experience") or [])],
            education=[Education.from_dict(x) for x in (d.get("education") or [])],
            certifications=[Certification.from_dict(x) for x in (d.get("certifications") or [])],
            extra_bullets=_list(d.get("extra_bullets")),
            meta=ProfileMeta.from_dict(d.get("meta")),
            layout=ResumeLayout.from_dict(d.get("layout")),
        )

    def to_yaml_dict(self) -> dict:
        """Clean YAML mapping matching the input schema. Inverse of from_dict.
        Omits `meta` when empty and `layout` when it equals the default."""
        out: dict[str, Any] = {}
        if not self.meta.is_empty():
            out["meta"] = self.meta.to_dict()
        c = self.contact
        out["contact"] = {
            "name": c.name, "title": c.title, "email": c.email, "phone": c.phone,
            "location": c.location, "linkedin": c.linkedin, "website": c.website,
            "work_authorization": c.work_authorization,
        }
        out["summary"] = self.summary
        out["skill_groups"] = [
            {"category": g.category, "skills": list(g.skills)} for g in self.skill_groups
        ]
        out["experience"] = [
            {
                "id": e.id, "client": e.client, "employer": e.employer, "role": e.role,
                "location": e.location, "start": e.start, "end": e.end,
                "environment": list(e.environment), "summary": e.summary,
                "bullets": list(e.bullets), "bullet_library": list(e.bullet_library),
            }
            for e in self.experience
        ]
        out["education"] = [
            {"degree": ed.degree, "field": ed.field_of_study, "institution": ed.institution,
             "location": ed.location, "year": ed.year}
            for ed in self.education
        ]
        out["certifications"] = [
            {"name": ct.name, "issuer": ct.issuer, "year": ct.year} for ct in self.certifications
        ]
        out["extra_bullets"] = list(self.extra_bullets)
        if not self.layout.is_default():
            out["layout"] = self.layout.to_dict()
        return out

    def all_skills(self) -> list[str]:
        out: list[str] = []
        for g in self.skill_groups:
            out.extend(g.skills)
        for e in self.experience:
            out.extend(e.environment)
        return out

    def years_experience(self) -> float:
        starts, ends = [], []
        for e in self.experience:
            sd = _parse_ym(e.start)
            ed = date.today() if e.end.lower() in ("present", "current", "") else _parse_ym(e.end)
            if sd:
                starts.append(sd)
            if ed:
                ends.append(ed)
        if not starts or not ends:
            return 0.0
        span = (max(ends) - min(starts)).days / 365.25
        return round(span, 1)


def _parse_ym(v: str):
    v = _s(v)
    if not v:
        return None
    for fmt in ("%Y-%m", "%Y/%m", "%m/%Y", "%b %Y", "%B %Y", "%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Job requirement (LLM- or heuristic-extracted)
# --------------------------------------------------------------------------- #
_ARCHETYPES = ("ic", "tech-lead", "architect", "hands-on-manager")


def _ranked(v: Any) -> list[dict]:
    """Normalize must_have_ranked into [{skill, weight:int 1-3}], deduped by skill."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in v or []:
        if isinstance(item, dict):
            sk = _s(item.get("skill") or item.get("name"))
            w = item.get("weight", 2)
        else:
            sk, w = _s(item), 2
        if not sk or sk.lower() in seen:
            continue
        seen.add(sk.lower())
        try:
            wi = max(1, min(3, int(float(w))))
        except (TypeError, ValueError):
            wi = 2
        out.append({"skill": sk, "weight": wi})
    return out


@dataclass
class JobRequirement:
    company: str = ""
    vendor: str = ""
    role: str = ""
    location: str = ""
    employment_type: str = ""
    min_years: float | None = None
    must_have_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    must_have_ranked: list[dict] = field(default_factory=list)   # [{skill, weight 1-3}]
    ats_keywords: list[str] = field(default_factory=list)        # verbatim phrases
    hard_gates: list[str] = field(default_factory=list)          # absolute bars
    archetype: str = ""                                          # ic|tech-lead|architect|hands-on-manager
    raw_text: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "JobRequirement":
        d = d or {}
        my = d.get("min_years")
        try:
            my = float(my) if my not in (None, "") else None
        except (TypeError, ValueError):
            my = None
        ranked = _ranked(d.get("must_have_ranked"))
        flat = _list(d.get("must_have_skills"))
        if ranked and not flat:
            flat = [r["skill"] for r in sorted(ranked, key=lambda r: -r["weight"])]
        arch = _s(d.get("archetype")).lower().replace(" ", "-")
        if arch not in _ARCHETYPES:
            arch = ""
        return cls(
            company=_s(d.get("company")),
            vendor=_s(d.get("vendor")),
            role=_s(d.get("role") or d.get("title")),
            location=_s(d.get("location")),
            employment_type=_s(d.get("employment_type")),
            min_years=my,
            must_have_skills=flat,
            nice_to_have_skills=_list(d.get("nice_to_have_skills")),
            domains=_list(d.get("domains")),
            responsibilities=_list(d.get("responsibilities")),
            must_have_ranked=ranked,
            ats_keywords=_list(d.get("ats_keywords")),
            hard_gates=_list(d.get("hard_gates")),
            archetype=arch,
            raw_text=_s(d.get("raw_text")),
        )

    def ranked_or_flat(self) -> list[dict]:
        """Always a [{skill, weight}] list — falls back to weight-2 for every flat skill."""
        if self.must_have_ranked:
            return self.must_have_ranked
        return [{"skill": s, "weight": 2} for s in self.must_have_skills]


# --------------------------------------------------------------------------- #
# Gap report
# --------------------------------------------------------------------------- #
@dataclass
class GapItem:
    skill: str
    status: str            # matched | partial | missing
    evidence: str = ""


@dataclass
class GapReport:
    matched: list[GapItem] = field(default_factory=list)
    partial: list[GapItem] = field(default_factory=list)
    missing: list[GapItem] = field(default_factory=list)
    years_required: float | None = None
    years_available: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_markdown(self, req: "JobRequirement | None" = None) -> str:
        lines = ["# Gap Report", ""]
        if req:
            lines += [f"**Target:** {req.role or '?'} @ {req.company or req.vendor or '?'}", ""]
        yr = self.years_required
        ya = self.years_available
        if yr is not None or ya is not None:
            flag = ""
            if yr is not None and ya is not None and ya + 0.5 < yr:
                flag = "  ⚠️ shortfall"
            lines += [f"**Experience:** required ~{yr if yr is not None else '?'} yrs / "
                      f"available ~{ya if ya is not None else '?'} yrs{flag}", ""]

        def block(title: str, items: list[GapItem]) -> list[str]:
            out = [f"## {title} ({len(items)})", ""]
            if not items:
                out.append("_none_")
                out.append("")
                return out
            for it in items:
                ev = f" — {it.evidence}" if it.evidence else ""
                out.append(f"- **{it.skill}**{ev}")
            out.append("")
            return out

        lines += block("Matched", self.matched)
        lines += block("Partial", self.partial)
        lines += block("Missing", self.missing)
        if self.notes:
            lines += ["## Notes", ""] + [f"- {n}" for n in self.notes] + [""]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Coverage map — does the *tailored resume* actually carry each must-have?
# --------------------------------------------------------------------------- #
@dataclass
class CoverageItem:
    skill: str
    weight: int = 2
    in_summary: bool = False
    in_skills: bool = False
    in_bullets: list[str] = field(default_factory=list)   # experience ids

    @property
    def status(self) -> str:
        if self.in_summary and self.in_skills and self.in_bullets:
            return "full"
        if self.in_summary or self.in_skills or self.in_bullets:
            return "partial"
        return "absent"


@dataclass
class CoverageReport:
    items: list[CoverageItem] = field(default_factory=list)
    gates: list[dict] = field(default_factory=list)              # [{gate, verdict: met|unmet|verify}]
    stretch_bullets: list[dict] = field(default_factory=list)    # [{exp_id, text}]

    def gaps(self) -> list[CoverageItem]:
        return [i for i in self.items if i.status != "full"]

    def coverage_fraction(self) -> float:
        tot = sum(i.weight for i in self.items) or 1
        got = sum(i.weight for i in self.items if i.status == "full")
        got += 0.5 * sum(i.weight for i in self.items if i.status == "partial")
        return got / tot

    def to_markdown(self, req: "JobRequirement | None" = None) -> str:
        lines = ["# Coverage map", ""]
        if req:
            lines += [f"**Target:** {req.role or '?'} @ {req.company or req.vendor or '?'}", ""]
        lines += [f"**Must-have coverage:** {round(self.coverage_fraction() * 100)}%  "
                  f"({sum(1 for i in self.items if i.status == 'full')}/{len(self.items)} full)", ""]
        lines += ["| Must-have | Wt | Summary | Skills | Bullets | Status |",
                  "|---|---|---|---|---|---|"]
        mark = {True: "✓", False: "·"}
        for i in sorted(self.items, key=lambda x: (-x.weight, x.skill.lower())):
            b = ", ".join(i.in_bullets) if i.in_bullets else "·"
            lines.append(f"| {i.skill} | {i.weight} | {mark[i.in_summary]} | "
                         f"{mark[i.in_skills]} | {b} | **{i.status}** |")
        lines.append("")
        if self.gates:
            lines += ["## Hard gates", ""]
            for g in self.gates:
                lines.append(f"- **{g['gate']}** — {g['verdict']}")
            lines.append("")
        lines += [f"## Stretch bullets ({len(self.stretch_bullets)})", ""]
        if self.stretch_bullets:
            lines.append("_Not backed by your master profile — be ready to defend each in a "
                         "screen, or cut it._\n")
            for s in self.stretch_bullets:
                lines.append(f"- [{s['exp_id']}] {s['text']}")
        else:
            lines.append("_None — every bullet traces to real master material._")
        lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Match score — deterministic 0-100 fit + concrete weak points
# --------------------------------------------------------------------------- #
@dataclass
class MatchScore:
    score: int = 0
    breakdown: dict = field(default_factory=dict)     # name -> 0..1 (pre-weight); 'penalty' subtractive
    weak_points: list[str] = field(default_factory=list)

    def to_markdown(self, req: "JobRequirement | None" = None) -> str:
        lines = ["# Match score", ""]
        if req:
            lines += [f"**Target:** {req.role or '?'} @ {req.company or req.vendor or '?'}", ""]
        lines += [f"## {self.score} / 100", "", "| Component | Score |", "|---|---|"]
        for k, v in self.breakdown.items():
            lines.append(f"| {k} | {round(v * 100)}% |")
        lines.append("")
        lines += ["## What's weak", ""]
        lines += ([f"- {w}" for w in self.weak_points] or ["- _nothing flagged_"])
        lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Tailored output
# --------------------------------------------------------------------------- #
def _split_bullets(v: Any) -> tuple[list[str], list[str]]:
    """Accept bullets as ['text', ...] or [{'text':..., 'source':...}, ...].
    Returns (texts, sources) — sources parallel to texts, '' where unknown."""
    texts: list[str] = []
    sources: list[str] = []
    for item in v or []:
        if isinstance(item, dict):
            t = _s(item.get("text") or item.get("bullet"))
            s = _s(item.get("source"))
        else:
            t, s = _s(item), ""
        if t:
            texts.append(t)
            sources.append(s)
    return texts, sources


@dataclass
class TailoredExperience:
    id: str = ""
    client: str = ""
    employer: str = ""
    role: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    summary: str = ""
    bullets: list[str] = field(default_factory=list)
    bullet_sources: list[str] = field(default_factory=list)   # parallel to bullets: lib:n|bullet:n|env:x|stretch

    @classmethod
    def from_dict(cls, d: dict) -> "TailoredExperience":
        texts, sources = _split_bullets(d.get("bullets"))
        if not sources or all(not s for s in sources):
            sources = _list(d.get("bullet_sources"))
        return cls(
            id=_s(d.get("id")),
            client=_s(d.get("client")),
            employer=_s(d.get("employer")),
            role=_s(d.get("role")),
            location=_s(d.get("location")),
            start=_s(d.get("start")),
            end=_s(d.get("end")),
            summary=_s(d.get("summary")),
            bullets=texts,
            bullet_sources=sources,
        )


@dataclass
class TailoredResume:
    contact: Contact = field(default_factory=Contact)
    target_company: str = ""
    target_role: str = ""
    summary: str = ""
    skill_groups: list[SkillGroup] = field(default_factory=list)
    experience: list[TailoredExperience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    certifications: list[Certification] = field(default_factory=list)
    cover_letter: str = ""
    layout: ResumeLayout = field(default_factory=ResumeLayout)
    declared_years: float | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "TailoredResume":
        d = d or {}
        return cls(
            contact=Contact.from_dict(d.get("contact", {})),
            target_company=_s(d.get("target_company")),
            target_role=_s(d.get("target_role")),
            summary=_s(d.get("summary")),
            skill_groups=[SkillGroup.from_dict(x) for x in (d.get("skill_groups") or [])],
            experience=[TailoredExperience.from_dict(x) for x in (d.get("experience") or [])],
            education=[Education.from_dict(x) for x in (d.get("education") or [])],
            certifications=[Certification.from_dict(x) for x in (d.get("certifications") or [])],
            cover_letter=_s(d.get("cover_letter")),
            layout=ResumeLayout.from_dict(d.get("layout")),
            declared_years=_float_or_none(d.get("declared_years")),
        )

    def to_yaml_dict(self) -> dict:
        d = asdict(self)
        d["layout"] = self.layout.to_dict()
        if self.declared_years is None:
            d.pop("declared_years", None)
        return d
