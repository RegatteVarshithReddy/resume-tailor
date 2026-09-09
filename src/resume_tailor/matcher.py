"""Deterministic skill matching (profile vs JD), JD-based profile auto-routing,
and a no-LLM heuristic JD parser."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .config import DEFAULT_PROFILE, DEFAULT_MATCH_WEIGHTS, Paths
from .models import (
    CoverageItem,
    CoverageReport,
    GapItem,
    GapReport,
    JobRequirement,
    MasterProfile,
    MatchScore,
    TailoredResume,
)

_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "react.js": "react",
    "reactjs": "react",
    "node": "node.js",
    "nodejs": "node.js",
    "k8s": "kubernetes",
    "gcp": "google cloud",
    "aws cloud": "aws",
    "postgres": "postgresql",
    "ms sql": "sql server",
    "mssql": "sql server",
    "dotnet": ".net",
    ".net core": ".net",
    "c sharp": "c#",
    "py": "python",
    "golang": "go",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "rest": "rest api",
    "restful": "rest api",
    "restful api": "rest api",
    "spring boot": "springboot",
    "gha": "github actions",
}

_TECH_LEXICON = {
    "python", "java", "javascript", "typescript", "c#", "c++", "go", "ruby", "php", "scala",
    "kotlin", "swift", "rust", "sql", "bash", "powershell", ".net", "springboot", "spring",
    "django", "flask", "fastapi", "node.js", "express", "react", "angular", "vue", "next.js",
    "redux", "graphql", "rest api", "grpc", "kafka", "rabbitmq", "redis", "elasticsearch",
    "postgresql", "mysql", "sql server", "oracle", "mongodb", "dynamodb", "cassandra",
    "snowflake", "databricks", "spark", "hadoop", "airflow", "dbt", "aws", "azure",
    "google cloud", "kubernetes", "docker", "terraform", "ansible", "jenkins",
    "github actions", "gitlab ci", "cicd", "linux", "git", "microservices", "kafka streams",
    "selenium", "cypress", "playwright", "junit", "pytest", "pandas", "numpy", "pytorch",
    "tensorflow", "scikit-learn", "power bi", "tableau", "servicenow", "salesforce", "sap",
}


def _norm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,:;()[]/")
    return _ALIASES.get(s, s)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _pool(*phrases: str) -> tuple[set[str], set[str]]:
    """(normalized-phrase set, token set) from a bag of skill/text strings."""
    pool = {_norm(x) for x in phrases if x and x.strip()}
    toks: set[str] = set()
    for x in pool:
        toks.update(t for t in x.split() if len(t) > 1)
    return pool, toks


def match_skill(skill: str, pool: set[str], pool_tokens: set[str]) -> tuple[str, str]:
    """Classify a JD skill against a profile/resume pool. -> (status, evidence).
    status: matched | partial | missing."""
    n = _norm(skill)
    if not n:
        return "missing", ""
    if n in pool:
        return "matched", "listed"
    n_toks = set(n.split())
    for p in pool:
        p_toks = set(p.split())
        if n in p_toks or p in n_toks:
            return "matched", f"~ '{p}'"
    if len(n) >= 4:
        for p in pool:
            if n in p or p in n:
                return "matched", f"~ '{p}'"
    best, best_p = 0.0, ""
    for p in pool:
        r = _similar(n, p)
        if r > best:
            best, best_p = r, p
    if best >= 0.86:
        return "matched", f"~ '{best_p}'"
    if n_toks & pool_tokens:
        return "partial", "related terms present"
    if best >= 0.7:
        return "partial", f"loosely ~ '{best_p}'"
    return "missing", ""


def _text_has(skill: str, text_norm: str, text_tokens: set[str]) -> bool:
    """Is `skill` present in a free-text blob (summary / bullets)?"""
    n = _norm(skill)
    if not n:
        return False
    if n in text_norm:
        return True
    parts = [t for t in n.split() if len(t) > 2]
    return bool(parts) and all(t in text_tokens for t in parts)


def build_gap_report(master: MasterProfile, req: JobRequirement) -> GapReport:
    pool, pool_tokens = _pool(*master.all_skills())

    report = GapReport(
        years_required=req.min_years,
        years_available=master.years_experience() or None,
    )

    _GAP_STATUS = {"matched": "matched", "partial": "partial", "missing": "missing"}
    seen: set[str] = set()
    for skill in list(req.must_have_skills) + list(req.nice_to_have_skills):
        key = _norm(skill)
        if key in seen:
            continue
        seen.add(key)
        status, ev = match_skill(skill, pool, pool_tokens)
        getattr(report, _GAP_STATUS[status]).append(GapItem(skill=skill, status=status, evidence=ev))

    declared = master.meta.years_experience
    computed = master.years_experience() or None
    if declared is not None:
        report.years_available = declared
        if computed is not None and abs(declared - computed) >= 1.0:
            report.notes.append(
                f"Profile declares ~{declared} yrs; dated entries span ~{computed} yrs."
            )
    if req.min_years and report.years_available and report.years_available + 0.5 < req.min_years:
        report.notes.append(
            f"JD asks for ~{req.min_years} yrs; profile offers ~{report.years_available} yrs."
        )
    if report.missing:
        report.notes.append(
            f"{len(report.missing)} required/preferred skill(s) not in your master profile."
        )
    return report


# --------------------------------------------------------------------------- #
# Coverage map — does the tailored resume actually carry each must-have?
# --------------------------------------------------------------------------- #
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)", re.I)
_CERT_HINT = re.compile(r"\b(cert|certified|certification|pmp|cissp|csm|ccna|ccnp|aws|azure|"
                        r"gcp|itil|safe|togaf|cka|ckad|terraform associate)\b", re.I)
_VERIFY_HINT = re.compile(r"\b(clearance|ts/sci|public trust|secret|onsite|on-site|"
                          r"relocat|citizen|gc only|green card|no c2c|w2 only|no opt|no cpt)\b", re.I)


def _eval_gate(gate: str, tr: TailoredResume) -> str:
    m = _YEARS_RE.search(gate)
    if m and tr.declared_years is not None:
        return "met" if tr.declared_years + 1e-6 >= float(m.group(1)) else "unmet"
    if _CERT_HINT.search(gate):
        cert_pool, cert_tok = _pool(*[c.name for c in tr.certifications])
        if not cert_pool:
            return "unmet"
        gtok = {t for t in _norm(gate).split() if len(t) > 2}
        return "met" if gtok & cert_tok else "unmet"
    if _VERIFY_HINT.search(gate):
        return "verify"
    return "verify"


def check_coverage(tr: TailoredResume, req: JobRequirement) -> CoverageReport:
    sum_norm = _norm(tr.summary)
    _, sum_tok = _pool(tr.summary)
    sk_pool, sk_tok = _pool(*[s for g in tr.skill_groups for s in g.skills])
    exp_blobs: list[tuple[str, str, set[str]]] = []
    for e in tr.experience:
        blob = " . ".join(e.bullets + [e.summary])
        _, btok = _pool(blob)
        exp_blobs.append((e.id, _norm(blob), btok))

    items: list[CoverageItem] = []
    for r in req.ranked_or_flat():
        skill = r["skill"]
        wt = int(r.get("weight", 2))
        in_sum = _text_has(skill, sum_norm, sum_tok)
        in_sk = match_skill(skill, sk_pool, sk_tok)[0] in ("matched", "partial")
        in_b = [eid for eid, bn, bt in exp_blobs if _text_has(skill, bn, bt)]
        items.append(CoverageItem(skill=skill, weight=wt, in_summary=in_sum,
                                  in_skills=in_sk, in_bullets=in_b))

    stretch = [
        {"exp_id": e.id, "text": e.bullets[i]}
        for e in tr.experience
        for i, src in enumerate(e.bullet_sources[: len(e.bullets)])
        if src == "stretch"
    ]
    gates = [{"gate": g, "verdict": _eval_gate(g, tr)} for g in req.hard_gates]
    return CoverageReport(items=items, gates=gates, stretch_bullets=stretch)


# --------------------------------------------------------------------------- #
# Match score — deterministic 0-100 fit + concrete weak points
# --------------------------------------------------------------------------- #
_ARCH_KEYS = {
    "ic": ("engineer", "developer", "programmer", "sde"),
    "tech-lead": ("lead", "senior", "principal"),
    "architect": ("architect", "principal", "staff"),
    "hands-on-manager": ("manager", "lead", "head"),
}


def _archetype_fit(req: JobRequirement, master: MasterProfile) -> float:
    if not req.archetype:
        return 1.0
    hay = f"{master.contact.title} {master.meta.seniority} {master.meta.label}".lower()
    for m in master.experience:
        hay += " " + (m.role or "").lower()
    keys = _ARCH_KEYS.get(req.archetype, ())
    return 1.0 if any(k in hay for k in keys) else 0.5


def score_match(
    gap: GapReport,
    coverage: CoverageReport,
    req: JobRequirement,
    master: MasterProfile,
    weights: dict | None = None,
) -> MatchScore:
    w = {**DEFAULT_MATCH_WEIGHTS, **(weights or {})}

    cov = coverage.coverage_fraction() if coverage.items else 1.0
    if req.min_years and gap.years_available:
        yrs = min(1.0, gap.years_available / req.min_years)
    else:
        yrs = 1.0
    dom = 1.0
    if req.domains:
        _, jd_tok = _pool(*req.domains)
        prof_tok = _pool(
            master.contact.title, master.meta.label, master.meta.seniority,
            *[m.summary for m in master.experience],
            *[g.category for g in master.skill_groups],
        )[1]
        inter = len(jd_tok & prof_tok)
        dom = inter / len(jd_tok) if jd_tok else 1.0
    arch = _archetype_fit(req, master)

    absent_w3 = sum(1 for i in coverage.items if i.weight == 3 and i.status == "absent")
    penalty = min(0.10, 0.02 * len(coverage.stretch_bullets) + 0.03 * absent_w3)

    breakdown = {"coverage": cov, "years": yrs, "domain": dom, "archetype": arch, "penalty": penalty}
    raw = (w["coverage"] * cov + w["years"] * yrs + w["domain"] * dom
           + w["archetype"] * arch - penalty)
    score = max(0, min(100, round(raw * 100)))

    weak: list[str] = []
    for i in sorted(coverage.gaps(), key=lambda x: -x.weight):
        where = "absent" if i.status == "absent" else (
            "only in " + ", ".join(
                p for p, ok in (("summary", i.in_summary), ("skills", i.in_skills),
                                ("bullets", bool(i.in_bullets))) if ok))
        weak.append(f"'{i.skill}' (weight {i.weight}) — {where}; add a real bullet or accept partial.")
    if req.min_years and gap.years_available and gap.years_available + 0.5 < req.min_years:
        weak.append(f"Years {gap.years_available:g}/{req.min_years:g} — "
                    f"{req.min_years - gap.years_available:g}-yr shortfall.")
    if coverage.stretch_bullets:
        weak.append(f"{len(coverage.stretch_bullets)} bullet(s) are 'stretch' — "
                    "be ready to defend each in a screen, or cut it.")
    for g in coverage.gates:
        if g["verdict"] == "unmet":
            weak.append(f"Hard gate '{g['gate']}' looks unmet.")
        elif g["verdict"] == "verify":
            weak.append(f"Hard gate '{g['gate']}' — verify you can meet this before submitting.")
    if req.domains and dom < 0.5:
        weak.append(f"Domain fit is thin ({round(dom * 100)}%) for: {', '.join(req.domains)}.")

    return MatchScore(score=score, breakdown=breakdown, weak_points=weak[:12])


def estimate_match(master: MasterProfile, req: JobRequirement, gap: GapReport,
                   weights: dict | None = None) -> MatchScore:
    """Pre-run match estimate: score the *profile* against the JD (no tailoring yet),
    treating gap 'matched' as fully covered and 'missing' as absent."""
    status_by = {}
    for it in gap.matched:
        status_by[_norm(it.skill)] = "full"
    for it in gap.partial:
        status_by.setdefault(_norm(it.skill), "partial")
    items: list[CoverageItem] = []
    for r in req.ranked_or_flat():
        st = status_by.get(_norm(r["skill"]), "absent")
        items.append(CoverageItem(
            skill=r["skill"], weight=int(r.get("weight", 2)),
            in_summary=(st == "full"), in_skills=(st in ("full", "partial")),
            in_bullets=(["profile"] if st == "full" else []),
        ))
    fake_tr = TailoredResume(declared_years=master.meta.years_experience,
                             certifications=list(master.certifications))
    cov = CoverageReport(items=items,
                         gates=[{"gate": g, "verdict": _eval_gate(g, fake_tr)}
                                for g in req.hard_gates])
    return score_match(gap, cov, req, master, weights)


# --------------------------------------------------------------------------- #
# JD-based profile auto-routing
# --------------------------------------------------------------------------- #
def _tokens(*parts: str) -> set[str]:
    out: set[str] = set()
    for p in parts:
        for t in re.split(r"[^a-z0-9+#.]+", (p or "").lower()):
            if len(t) > 1:
                out.add(t)
    return out


def select_profile(paths: Paths, req: JobRequirement, requested: str | None) -> tuple[str, str]:
    """Return (profile_name, reason). If `requested` is a real profile name it is
    used verbatim; only "auto"/"" trigger routing by the JD's role + min_years."""
    names = paths.list_profiles()
    if requested and requested.lower() != "auto":
        return requested, "explicitly selected"
    if not names:
        return DEFAULT_PROFILE, "no profiles defined"

    from .profile_io import load_master_meta

    jd_tokens = _tokens(req.role, " ".join(req.domains), " ".join(req.responsibilities[:6]))
    need = req.min_years or 0.0

    scored: list[dict] = []
    any_meta = False
    for n in names:
        meta = load_master_meta(paths.master_profile(n))
        if meta:
            any_meta = True
        fam = [str(x).lower() for x in (meta.get("role_family") or [])]
        fam_tokens = _tokens(" ".join(fam), meta.get("label", ""), meta.get("seniority", ""))
        role_score = len(jd_tokens & fam_tokens)
        yrs = meta.get("years_experience")
        try:
            yrs = float(yrs) if yrs not in (None, "") else None
        except (TypeError, ValueError):
            yrs = None
        scored.append({"name": n, "role_score": role_score, "years": yrs})

    if not any_meta:
        pick = DEFAULT_PROFILE if DEFAULT_PROFILE in names else names[0]
        return pick, "no profile metadata set — using default (add role_family + years to enable routing)"

    qualifies = [s for s in scored if (s["years"] or 0.0) + 0.01 >= need]
    pool = qualifies or scored
    shortfall = not qualifies and need > 0

    # best role-family match; tie-break: closest years above the need, else most years
    def key(s: dict):
        yrs = s["years"] or 0.0
        fit = (yrs - need) if yrs >= need else 1e6 - yrs  # prefer smallest non-negative gap
        return (-s["role_score"], fit)

    best = sorted(pool, key=key)[0]
    yrs_txt = f"{best['years']:g}" if best["years"] is not None else "unset"
    bits = []
    if need:
        bits.append(f"JD wants ~{need:g} yrs")
    bits.append(f"'{best['name']}' offers {yrs_txt}")
    if best["role_score"]:
        bits.append(f"role match +{best['role_score']}")
    if shortfall:
        bits.append("no profile meets the year bar — picked the highest")
    return best["name"], "; ".join(bits)


# --------------------------------------------------------------------------- #
# Heuristic (no-LLM) JD parser for `resume-tailor gap --no-llm`
# --------------------------------------------------------------------------- #
def heuristic_parse_jd(raw: str) -> JobRequirement:
    text = raw.strip()
    low = text.lower()

    m = re.search(r"(\d+)\s*\+?\s*(?:years|yrs)\b", low)
    min_years = float(m.group(1)) if m else None

    found = []
    for term in sorted(_TECH_LEXICON, key=len, reverse=True):
        pat = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
        if re.search(pat, low):
            found.append(term)

    role = ""
    for line in text.splitlines():
        s = line.strip()
        if s and len(s) < 90 and not s.endswith(":"):
            role = s
            break

    # weight by first appearance: earlier in the JD = more prominent
    first_at = {t: low.find(t) for t in found}
    third = max(1, len(text) // 3)
    ranked = [
        {"skill": t, "weight": 3 if first_at[t] < len(role) + 5 else (2 if first_at[t] < third else 1)}
        for t in found
    ]

    gates: list[str] = []
    if m:
        gates.append(f"{m.group(1)}+ years")
    for pat, label in ((r"clearance|ts/sci|public trust", "security clearance"),
                       (r"\b(pmp|cissp|csm|ccna|ccnp)\b", None),
                       (r"us citizen|citizenship required|gc only|green card only", "US citizen / GC only"),
                       (r"onsite\s+(?:only|from day one)|no remote", "strictly onsite")):
        mm = re.search(pat, low)
        if mm:
            gates.append(label or mm.group(0).upper())

    return JobRequirement(
        role=role,
        min_years=min_years,
        must_have_skills=found,
        must_have_ranked=ranked,
        hard_gates=gates,
        raw_text=text,
    )
