"""Prompt builders for the LLM calls (extract, tailor, self-review)."""

from __future__ import annotations

import json

from .models import CoverageReport, GapReport, JobRequirement, MasterProfile

# --------------------------------------------------------------------------- #
# Call 1 — extract structured requirements from the raw JD
# --------------------------------------------------------------------------- #
EXTRACT_SYSTEM = (
    "You are a precise technical recruiter's assistant. You read a raw job "
    "description for a contract/consulting IT role and return STRICT JSON only. "
    "No commentary, no markdown fences."
)


def extract_prompt(raw_jd: str) -> str:
    schema = {
        "company": "end client name if stated else ''",
        "vendor": "staffing vendor / prime name if stated else ''",
        "role": "job title",
        "location": "location / remote",
        "employment_type": "e.g. W2 contract, C2C, 6-month contract",
        "min_years": "number of total years of experience required, or null",
        "must_have_ranked": [
            {"skill": "canonical skill name",
             "weight": "3 = in the title or first responsibility, 2 = repeated or clearly core, "
                       "1 = merely listed among required items"}
        ],
        "must_have_skills": ["same skills as must_have_ranked, most important first (flat list)"],
        "nice_to_have_skills": ["preferred / plus skills"],
        "ats_keywords": ["exact phrases as they appear in the JD, verbatim casing "
                         "(e.g. 'Azure Data Factory', 'CI/CD', 'Spring Boot')"],
        "hard_gates": ["absolute bars phrased as non-negotiable: exact years ('10+ years'), "
                       "clearance ('active TS/SCI'), a specific certification ('PMP required'), "
                       "work authorization ('USC/GC only'), strict onsite ('onsite Dallas, no remote')"],
        "archetype": "one of: ic | tech-lead | architect | hands-on-manager  (from the tone of "
                     "the responsibilities; '' if unclear)",
        "domains": ["business/industry domains e.g. healthcare, payments, telecom"],
        "responsibilities": ["short phrases summarizing day-to-day responsibilities"],
    }
    return (
        "Extract the requirements from this job description.\n\n"
        "Return JSON with exactly these keys:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Rules:\n"
        "- Use canonical tech names (JavaScript not JS, Kubernetes not k8s, "
        "CI/CD, REST API, PostgreSQL, etc.).\n"
        "- must_have_ranked / must_have_skills: only things the JD marks as required/must/"
        "mandatory or lists as core. Everything merely 'preferred/plus/nice' goes to "
        "nice_to_have_skills.\n"
        "- Weight by PROMINENCE: title or first responsibility -> 3; repeated / called out as "
        "core -> 2; just listed -> 1.\n"
        "- ats_keywords: copy the phrases EXACTLY as written in the JD (do not canonicalize).\n"
        "- hard_gates: only true non-negotiables. If the JD says 'preferred' it is NOT a gate.\n"
        "- min_years: integer or decimal number only, or null.\n"
        "- Keep each list item short. Deduplicate.\n\n"
        "JOB DESCRIPTION:\n"
        '"""\n'
        f"{raw_jd.strip()}\n"
        '"""'
    )


# --------------------------------------------------------------------------- #
# Call 2 — produce the tailored resume + cover letter
# --------------------------------------------------------------------------- #
TAILOR_SYSTEM = (
    "You are an expert resume writer for IT contract consultants. You rewrite a "
    "candidate's resume end-to-end so it maps tightly onto a specific job "
    "requirement, then write a matching cover letter. You return STRICT JSON only "
    "(no markdown fences, no prose outside the JSON). Escape every newline inside a "
    "string as \\n — never put a literal line break inside a JSON string value. Use "
    "\\n\\n between cover-letter paragraphs."
)


def tailor_prompt(
    master: MasterProfile,
    req: JobRequirement,
    gap: GapReport,
    *,
    aggressive: bool,
    max_bullets: int,
) -> str:
    master_json = json.dumps(_master_payload(master), indent=2)
    req_json = json.dumps(_req_payload(req), indent=2)
    gap_json = json.dumps(
        {
            "matched": [g.skill for g in gap.matched],
            "partial": [g.skill for g in gap.partial],
            "missing": [g.skill for g in gap.missing],
            "years_required": gap.years_required,
            "years_available": gap.years_available,
        },
        indent=2,
    )

    if aggressive:
        rewrite_rule = (
            "- REWRITE each experience's project context and bullets freely so that the "
            "technologies, architecture and responsibilities the job asks for are the "
            "centre of gravity of the resume. You may replace what the project was about. "
            "Spread the required tech sensibly across the timeline (newest roles carry the "
            "most advanced / most recent stack; older roles carry foundational work).\n"
            "- Fold in the 'missing' skills as real, worked experience where it is "
            "chronologically plausible."
        )
    else:
        rewrite_rule = (
            "- Rephrase, reorder and re-emphasise the candidate's REAL experience to "
            "surface matches with the job. Do NOT invent technologies the candidate has "
            "never listed; leave 'missing' skills out and let the gap report stand."
        )

    out_schema = {
        "target_company": "string",
        "target_role": "string",
        "summary": "3-5 sentence professional summary, tailored, first-person-implied, no 'I'",
        "skill_groups": [
            {"category": "e.g. Languages", "skills": ["ordered so JD must-haves come first"]}
        ],
        "experience": [
            {
                "id": "MUST equal the master entry id",
                "role": "title (may be adjusted to match JD seniority/wording)",
                "summary": "1-2 sentence context line for this engagement (optional, can be '')",
                "bullets": [
                    {
                        "text": f"achievement bullet ({max_bullets} or fewer per experience), metric-led where possible",
                        "source": "where this bullet comes from in the master entry: "
                                  "'bullet:<i>' (rewrote master bullets[i]) | 'lib:<i>' (used "
                                  "bullet_library[i]) | 'env:<skill>' (built around a listed "
                                  "environment/skill) | 'stretch' (added for the JD, NOT backed "
                                  "by this master entry)",
                    }
                ],
            }
        ],
        "cover_letter": "180-320 word cover letter, addressed 'Dear Hiring Manager,', "
        "plain paragraphs separated by blank lines, signed with the candidate name",
    }

    return (
        "Tailor this resume to the job requirement below.\n\n"
        "=== CANDIDATE MASTER PROFILE (source of truth) ===\n"
        f"{master_json}\n\n"
        "=== JOB REQUIREMENT ===\n"
        f"{req_json}\n\n"
        "=== GAP ANALYSIS (skills the JD wants vs. the profile) ===\n"
        f"{gap_json}\n\n"
        "=== HARD RULES (must not be broken) ===\n"
        "- Do NOT output contact info, client names, employer/vendor names, locations, "
        "start dates or end dates — those are locked and re-applied by the tool. Only "
        "return the fields in the schema.\n"
        "- Keep EXACTLY one output experience per master experience, same ids, same order.\n"
        f"- Max {max_bullets} bullets per experience. Each bullet text <= 32 words, starts with "
        "a strong past-tense verb (vary the verbs — do not start two bullets the same way), no "
        "first-person pronouns, no period-separated run-ons.\n"
        "- Every skill in must_have_ranked appears in the summary, the skill_groups, AND in the "
        "bullets of at least one experience. Weight-3 skills first.\n"
        "- Use the ats_keywords EXACT wording where it fits naturally.\n"
        "- Write bullets in the voice of the archetype (ic = builds/ships; tech-lead = leads/"
        "guides while hands-on; architect = designs/defines; hands-on-manager = owns delivery + "
        "people).\n"
        "- Do not claim any hard_gate the master cannot support (a certification/clearance not "
        "in the profile, years beyond meta.years_experience).\n"
        "- Set 'source' honestly on every bullet. Mark 'stretch' for anything not grounded in "
        "that master entry's bullets / bullet_library / environment.\n"
        "- No two experiences may claim the same accomplishment. Seniority must read plausibly "
        "from oldest to newest.\n"
        "- Do not claim certifications or degrees that are not in the master profile.\n"
        "- If meta.years_experience is given, the summary's opening clause states that "
        "experience level (e.g. 'Data Engineer with 7+ years…') and nothing may contradict it.\n"
        f"{rewrite_rule}\n\n"
        "=== RETURN JSON WITH EXACTLY THIS SHAPE ===\n"
        f"{json.dumps(out_schema, indent=2)}"
    )


# --------------------------------------------------------------------------- #
# Call 3 — self-review: critique the draft against the requirement and rewrite
# --------------------------------------------------------------------------- #
CRITIQUE_SYSTEM = (
    "You are a senior resume reviewer for IT contract consultants. You are given a DRAFT "
    "tailored resume as JSON and a list of concrete defects. You return an improved resume as "
    "STRICT JSON of the SAME shape — no commentary, no markdown fences. Escape every newline "
    "inside a string as \\n; never put a literal line break inside a JSON string value."
)


def critique_prompt(
    draft: dict,
    req: JobRequirement,
    gap: GapReport,
    coverage: CoverageReport,
    *,
    max_bullets: int,
    aggressive: bool,
) -> str:
    gaps = [
        f"- '{i.skill}' (weight {i.weight}) is {i.status}: "
        f"{'in summary' if i.in_summary else 'NOT in summary'}, "
        f"{'in skills' if i.in_skills else 'NOT in skills'}, "
        f"{'in bullets ' + ','.join(i.in_bullets) if i.in_bullets else 'NOT in any bullet'}"
        for i in coverage.gaps()
    ]
    gate_issues = [f"- hard gate '{g['gate']}' is {g['verdict']}" for g in coverage.gates
                   if g["verdict"] != "met"]
    stretch = [f"- [{s['exp_id']}] {s['text']}" for s in coverage.stretch_bullets]

    fab_rule = (
        "You MAY add missing skills as worked experience where chronologically plausible, "
        "marking those bullets source='stretch'."
        if aggressive else
        "Do NOT invent skills the candidate never listed; if a must-have cannot be covered from "
        "real material, leave it and let the gap stand."
    )

    return (
        "Improve this DRAFT tailored resume. Fix every defect below, keep everything that is "
        "already good, and return the SAME JSON shape (experience bullets stay objects with "
        "'text' and 'source').\n\n"
        "=== DRAFT (JSON) ===\n"
        f"{json.dumps(draft, indent=2)}\n\n"
        "=== JOB REQUIREMENT ===\n"
        f"{json.dumps(_req_payload(req), indent=2)}\n\n"
        "=== COVERAGE DEFECTS (must be fixed) ===\n"
        + ("\n".join(gaps) or "- (skill coverage is complete)") + "\n"
        + ("\n".join(gate_issues) + "\n" if gate_issues else "")
        + "\n=== RUBRIC (apply all) ===\n"
        "- Every must-have from the requirement appears in the summary AND skill_groups AND the "
        "bullets of >=1 experience. Weight-3 skills lead.\n"
        "- Use ats_keywords' exact wording where natural.\n"
        f"- <= {max_bullets} bullets per experience; each <= 32 words; distinct strong past-tense "
        "lead verb; metric-led where a real number exists; no run-ons; no first person.\n"
        "- No accomplishment repeated across two experiences. Seniority arc plausible oldest->newest.\n"
        "- Keep 'source' accurate. Reduce 'stretch' bullets where a real one from bullet_library/"
        "environment would serve. Current stretch bullets:\n"
        + ("\n".join(stretch) or "- (none)") + "\n"
        "- Do NOT output contact / client / employer / location / dates. Same experience ids, "
        "same order. No unlisted certs or degrees.\n"
        f"- {fab_rule}\n\n"
        "Return the improved resume JSON now."
    )


def _master_payload(m: MasterProfile) -> dict:
    return {
        "contact": {"name": m.contact.name, "title": m.contact.title},
        "meta": {
            "years_experience": m.meta.years_experience,
            "seniority": m.meta.seniority,
        },
        "summary": m.summary,
        "skill_groups": [{"category": g.category, "skills": g.skills} for g in m.skill_groups],
        "experience": [
            {
                "id": e.id,
                "client": e.client,
                "employer": e.employer,
                "role": e.role,
                "start": e.start,
                "end": e.end,
                "environment": e.environment,
                "summary": e.summary,
                "bullets": e.bullets,
                "bullet_library": e.bullet_library,
            }
            for e in m.experience
        ],
        "education": [
            {"degree": e.degree, "field": e.field_of_study, "institution": e.institution}
            for e in m.education
        ],
        "certifications": [{"name": c.name, "issuer": c.issuer} for c in m.certifications],
        "extra_bullets": m.extra_bullets,
    }


def _req_payload(r: JobRequirement) -> dict:
    return {
        "company": r.company,
        "vendor": r.vendor,
        "role": r.role,
        "location": r.location,
        "employment_type": r.employment_type,
        "min_years": r.min_years,
        "must_have_ranked": r.ranked_or_flat(),
        "nice_to_have_skills": r.nice_to_have_skills,
        "ats_keywords": r.ats_keywords,
        "hard_gates": r.hard_gates,
        "archetype": r.archetype,
        "domains": r.domains,
        "responsibilities": r.responsibilities,
    }
