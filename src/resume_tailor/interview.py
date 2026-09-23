"""interview_prep.md — what they will ask, and what you will say.

`defense.md` says what to resolve *before* you submit; this is the screen itself:
likely questions ranked the way the JD weights each skill, STAR stories assembled
from real master material, and a landmine list pairing every stretch claim with the
genuine work to pivot to.

`prep_payload` gathers the facts, the AI turns them into questions/answers as JSON,
`render_prep` writes the Markdown. `build_prep_fallback` produces the same JSON shape
deterministically, so `--no-llm`, the `mock` engine and a failed call all still work.
"""
from __future__ import annotations

from .models import (
    CoverageReport,
    GapReport,
    JobRequirement,
    MasterProfile,
    TailoredResume,
)

# archetype -> the behavioural ground they actually probe
ARCHETYPE_THEMES = {
    "ic": [
        ("Tell me about the hardest bug you have owned end to end.",
         "depth and persistence — they want to see you debug, not delegate"),
        ("When did you push back on a design decision?",
         "show judgement without making it a personality clash"),
    ],
    "tech-lead": [
        ("How do you split work across a team without becoming the bottleneck?",
         "delegation while staying hands-on — the whole point of the role"),
        ("Tell me about a time you had to correct a teammate's approach.",
         "lead through the code, not the org chart"),
    ],
    "architect": [
        ("Walk me through a design you would do differently today.",
         "they want trade-off reasoning and the humility to revisit it"),
        ("How do you take a team with you on an architecture decision?",
         "influence without authority"),
    ],
    "hands-on-manager": [
        ("How do you balance delivery pressure against your team's growth?",
         "they are checking you will not burn the team to hit a date"),
        ("Tell me about someone you grew into a bigger role.",
         "concrete names, concrete before/after"),
    ],
}

_GENERIC_BEHAVIORAL = [
    ("Tell me about a project that did not go well.",
     "pick a real one, own your part, land on what you changed after"),
    ("How do you get up to speed on an unfamiliar codebase?",
     "a repeatable method beats enthusiasm"),
]


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split()).strip(" .,:;()[]/")


def _risk_for(skill: str, coverage: CoverageReport, gap: GapReport) -> str:
    """stretch = not backed by real material · thin = present but not everywhere · solid."""
    n = _norm(skill)
    if any(n == _norm(g.skill) for g in gap.missing):
        return "stretch"
    if any(n in _norm(s["text"]) for s in coverage.stretch_bullets):
        return "stretch"
    item = next((i for i in coverage.items if _norm(i.skill) == n), None)
    if item is None or item.status != "full":
        return "thin"
    return "solid"


def _where(skill: str, coverage: CoverageReport) -> str:
    item = next((i for i in coverage.items if _norm(i.skill) == _norm(skill)), None)
    if item is None:
        return "nowhere on the resume"
    spots = [p for p, ok in (("summary", item.in_summary), ("skills list", item.in_skills)) if ok]
    if item.in_bullets:
        spots.append("bullets in " + ", ".join(item.in_bullets))
    return ", ".join(spots) or "nowhere on the resume"


def prep_payload(
    tr: TailoredResume,
    master: MasterProfile,
    req: JobRequirement,
    coverage: CoverageReport,
    gap: GapReport,
) -> dict:
    """Every fact the prep pack is built from — fed to the model and to the renderer."""
    by_id = {e.id: e for e in master.experience}
    tailored_by_id = {e.id: e for e in tr.experience}

    must_haves = []
    for r in sorted(req.ranked_or_flat(), key=lambda r: (-int(r.get("weight", 2)), r["skill"])):
        skill = r["skill"]
        must_haves.append({
            "skill": skill,
            "weight": int(r.get("weight", 2)),
            "risk": _risk_for(skill, coverage, gap),
            "where_on_resume": _where(skill, coverage),
        })

    experience = []
    for e in tr.experience:
        me = by_id.get(e.id)
        experience.append({
            "exp_id": e.id,
            "client": e.client or (me.client if me else ""),
            "role": e.role or (me.role if me else ""),
            "start": e.start or (me.start if me else ""),
            "end": e.end or (me.end if me else ""),
            "tailored_bullets": [
                {"text": t, "source": (e.bullet_sources[i] if i < len(e.bullet_sources) else "")}
                for i, t in enumerate(e.bullets)
            ],
            "master_bullets": list(me.bullets) if me else [],
            "bullet_library": list(me.bullet_library) if me else [],
            "environment": list(me.environment) if me else [],
        })

    stretch = []
    for s in coverage.stretch_bullets:
        me = by_id.get(s["exp_id"])
        te = tailored_by_id.get(s["exp_id"])
        stretch.append({
            "exp_id": s["exp_id"],
            "text": s["text"],
            "client": (te.client if te and te.client else (me.client if me else s["exp_id"])),
            "real_material": ((list(me.bullets) or list(me.bullet_library))[:4] if me else []),
            "real_environment": (list(me.environment)[:12] if me else []),
        })

    return {
        "target": {
            "role": req.role,
            "company": req.company or req.vendor,
            "location": req.location,
            "employment_type": req.employment_type,
            "archetype": req.archetype,
            "domains": list(req.domains),
            "responsibilities": list(req.responsibilities),
        },
        "years": {
            "required": req.min_years,
            "available": gap.years_available,
            "declared": tr.declared_years if tr.declared_years is not None else master.meta.years_experience,
        },
        "gates": [g for g in coverage.gates if g["verdict"] != "met"],
        "work_authorization": master.contact.work_authorization,
        "candidate_name": tr.contact.name or master.contact.name,
        "must_haves": must_haves,
        "experience": experience,
        "stretch": stretch,
        "missing": [g.skill for g in gap.missing],
    }


# --------------------------------------------------------------------------- #
# Deterministic fallback — same JSON shape the model returns
# --------------------------------------------------------------------------- #
def _questions_for(skill: str, weight: int, risk: str) -> list[str]:
    qs = [f"Walk me through the most complex thing you have built with {skill}."]
    if weight >= 2:
        qs.append(f"How did you decide on {skill} — what else did you consider, and why did it win?")
    if weight >= 3:
        qs.append(f"What broke in production with {skill}, and how did you track it down?")
    if risk == "stretch":
        qs.append(f"How long have you worked with {skill}, and in what depth?")
    return qs


def _first_with_number(bullets: list[str]) -> str:
    return next((b for b in bullets if any(ch.isdigit() for ch in b)), "")


def build_prep_fallback(payload: dict) -> dict:
    """A usable pack with no AI call: real questions, skeleton answers to fill in."""
    technical = []
    for mh in payload["must_haves"]:
        technical.append({
            "skill": mh["skill"],
            "weight": mh["weight"],
            "risk": mh["risk"],
            "questions": _questions_for(mh["skill"], mh["weight"], mh["risk"]),
            "your_material": f"On the resume: {mh['where_on_resume']}.",
            "pivot": "",
        })

    stories = []
    for e in payload["experience"]:
        real = e["master_bullets"] or e["bullet_library"]
        if not real and not e["tailored_bullets"]:
            continue
        headline = (e["tailored_bullets"][0]["text"] if e["tailored_bullets"]
                    else (real[0] if real else ""))
        stories.append({
            "exp_id": e["exp_id"],
            "headline": headline,
            "situation": f"{e['client']}{' — ' + e['role'] if e['role'] else ''} "
                         f"({e['start']}–{e['end']}).".strip(),
            "task": "_Fill in: what were you specifically asked to own?_",
            "action": real[0] if real else "_Fill in from your own memory of this engagement._",
            # the metric often lives in bullet_library rather than the headline bullets
            "result": (_first_with_number(e["master_bullets"] + e["bullet_library"])
                       or "_Fill in: the number you moved._"),
            "maps_to": e["environment"][:6],
        })

    arch = payload["target"].get("archetype") or ""
    themes = ARCHETYPE_THEMES.get(arch, []) + _GENERIC_BEHAVIORAL
    behavioral = [{"question": q, "angle": a} for q, a in themes]

    ask_them = [
        "What does the first 90 days look like for whoever takes this?",
        "What is the thing the last person in this seat found hardest?",
    ]
    for d in payload["target"].get("domains", [])[:2]:
        ask_them.append(f"How much {d} domain knowledge does the team expect up front?")
    for r in payload["target"].get("responsibilities", [])[:2]:
        ask_them.append(f"On \"{r}\" — is that greenfield, or picking up something in flight?")

    landmines = []
    for s in payload["stretch"]:
        landmines.append({
            "claim": s["text"],
            "if_pressed": f"Keep it at the level the bullet states — do not invent depth at {s['client']}.",
            "pivot_to": (s["real_material"][0] if s["real_material"]
                         else "the real work you did on that engagement"),
        })

    return {"technical": technical, "stories": stories, "behavioral": behavioral,
            "ask_them": ask_them, "landmines": landmines}


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
_RISK_TAG = {
    "stretch": "⚠️ **stretch** — your profile does not back this",
    "thin": "◐ thin — present, but not across summary + skills + a bullet",
    "solid": "✓ solid",
}


def render_prep(data: dict, payload: dict) -> str:
    t = payload["target"]
    L: list[str] = ["# Interview prep", ""]
    L += [f"**Target:** {t['role'] or '?'} @ {t['company'] or '?'}"
          + (f" · {t['location']}" if t["location"] else "")
          + (f" · {t['employment_type']}" if t["employment_type"] else ""), ""]
    L += ["Built from this run's tailored resume and your master profile. The ⚠️ items are "
          "where the resume is ahead of the profile — those are the questions that decide "
          "the screen.", ""]

    # 1. technical
    tech = data.get("technical") or []
    L += [f"## 1. Likely technical questions ({len(tech)} areas)", ""]
    if not tech:
        L += ["_No must-haves extracted from this JD._", ""]
    for c in tech:
        tag = _RISK_TAG.get(c.get("risk", ""), "")
        L += [f"### {c.get('skill', '?')}  <sub>weight {c.get('weight', 2)} · {tag}</sub>", ""]
        for q in c.get("questions") or []:
            L.append(f"- {q}")
        if c.get("your_material"):
            L += ["", f"**What you have:** {c['your_material']}"]
        if c.get("pivot"):
            L.append(f"**If pressed:** {c['pivot']}")
        L.append("")

    # 2. STAR
    stories = data.get("stories") or []
    L += [f"## 2. STAR stories ({len(stories)})", ""]
    if stories:
        L += ["One per engagement, from your real material. Say these out loud once before "
              "the call — the ones you have not spoken are the ones that ramble.", ""]
    for s in stories:
        L += [f"### {s.get('headline') or s.get('exp_id', '?')}", ""]
        for label, key in (("Situation", "situation"), ("Task", "task"),
                           ("Action", "action"), ("Result", "result")):
            if s.get(key):
                L.append(f"- **{label}:** {s[key]}")
        if s.get("maps_to"):
            L.append(f"- _Covers:_ {', '.join(s['maps_to'])}")
        L.append("")

    # 3. behavioural
    beh = data.get("behavioral") or []
    arch = t.get("archetype")
    L += [f"## 3. Behavioural ({len(beh)})", ""]
    if arch:
        L += [f"This JD reads as **{arch}** — the questions below are pitched at that.", ""]
    for b in beh:
        L.append(f"- **{b.get('question', '')}**")
        if b.get("angle"):
            L.append(f"  - _{b['angle']}_")
    L.append("")

    # 4. logistics — deterministic, straight from the payload
    L += ["## 4. Screening logistics", ""]
    yrs = payload.get("years") or {}
    yr, ya = yrs.get("required"), yrs.get("available")
    if yr and ya is not None and ya + 0.5 < yr:
        L.append(f"- ⚠️ **Years:** they want ~{yr:g}, your dated timeline is ~{ya:g}. "
                 "Lead with depth and scope, not tenure.")
    elif yr:
        L.append(f"- **Years:** they want ~{yr:g} — you are at ~{ya:g}." if ya is not None
                 else f"- **Years:** they want ~{yr:g}.")
    for g in payload.get("gates") or []:
        note = ("likely disqualifier — do not take the call without checking this"
                if g["verdict"] == "unmet" else "confirm before the call")
        L.append(f"- ⚠️ **Gate — {g['gate']}** ({g['verdict']}): {note}")
    if payload.get("work_authorization"):
        L.append(f"- **Work authorization:** {payload['work_authorization']}")
    if t.get("employment_type"):
        L.append(f"- **Engagement:** {t['employment_type']} — have your rate ready.")
    if t.get("location"):
        L.append(f"- **Location:** {t['location']} — confirm onsite days and travel.")
    L += ["- Have ready: rate, availability / notice period, timezone overlap.", ""]

    # 5. ask them
    ask = data.get("ask_them") or []
    L += ["## 5. Questions to ask them", ""]
    L += [f"- {q}" for q in ask] or ["_None generated._"]
    L.append("")

    # 6. landmines
    mines = data.get("landmines") or []
    L += [f"## 6. Landmines ({len(mines)})", ""]
    if not mines:
        L += ["_None — every bullet on this resume traces to real master material._", ""]
    for m in mines:
        L += [f"> {m.get('claim', '')}", ""]
        if m.get("if_pressed"):
            L.append(f"- **If pressed:** {m['if_pressed']}")
        if m.get("pivot_to"):
            L.append(f"- **Pivot to:** {m['pivot_to']}")
        L.append("")

    L += ["## Before the call", "",
          "- [ ] Every ⚠️ area above: you know what you will say",
          "- [ ] Every STAR story said out loud once",
          "- [ ] Gates confirmed, rate and availability ready",
          "- [ ] Two questions of your own you actually want answered", ""]
    return "\n".join(L)
