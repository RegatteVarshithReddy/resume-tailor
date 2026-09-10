"""defense.md — the "be ready to explain this" sheet.

`coverage.md` says *what* is thin; this says *what to do about it in a screen*:
every stretch bullet paired with the real work you can pivot to for that
engagement, plus the gates and gaps to confirm before you submit. Deterministic.
"""
from __future__ import annotations

from .models import CoverageReport, GapReport, JobRequirement, MasterProfile, TailoredResume


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split()).strip(" .,:;()[]/")


def build_defense(
    tr: TailoredResume,
    gap: GapReport,
    coverage: CoverageReport,
    req: JobRequirement,
    master: MasterProfile,
) -> str:
    by_id = {e.id: e for e in master.experience}
    L: list[str] = ["# Defense sheet", ""]
    L += [f"**Target:** {req.role or '?'} @ {req.company or req.vendor or '?'}", ""]
    L += ["Everything below is a claim on the tailored resume that your master profile "
          "does **not** fully back. Before you submit — and before any screen — decide for "
          "each one: cut it, or be ready to speak to it.", ""]

    # 1. stretch bullets, each with the real material for that engagement
    stretch = coverage.stretch_bullets
    L += [f"## 1. Stretch bullets ({len(stretch)})", ""]
    if not stretch:
        L += ["_None — every bullet traces to real master material._", ""]
    for s in stretch:
        me = by_id.get(s["exp_id"])
        where = me.client if me else s["exp_id"]
        L += [f"### {where}", "", f"> {s['text']}", ""]
        if me:
            real = list(me.bullets) or list(me.bullet_library)
            if real:
                L.append("What you actually did here (pivot to this):")
                L += [f"- {b}" for b in real[:5]]
            if me.environment:
                L.append("")
                L.append(f"_Real environment:_ {', '.join(me.environment[:14])}")
        L += ["", "_Action: cut it, or land a genuine story that supports it._", ""]

    # 2. must-haves absent from the master profile entirely
    must = {_norm(r["skill"]) for r in req.ranked_or_flat()}
    absent = [g.skill for g in gap.missing if _norm(g.skill) in must] or [g.skill for g in gap.missing]
    L += [f"## 2. Must-haves not in your master profile ({len(absent)})", ""]
    if absent:
        L += ["The JD asks for these and nothing in your profile documents them. Aggressive "
              "mode may have woven them in as stretch bullets (section 1); conservative mode "
              "left them out.", ""]
        L += [f"- **{s}**" for s in absent] + [""]
    else:
        L += ["_None — the profile covers every must-have._", ""]

    # 3. hard gates
    open_gates = [g for g in coverage.gates if g["verdict"] != "met"]
    L += [f"## 3. Hard gates to confirm ({len(open_gates)})", ""]
    if open_gates:
        for g in open_gates:
            tip = ("likely disqualifier — do not submit unless it changed"
                   if g["verdict"] == "unmet" else
                   "confirm you actually meet this before submitting")
            L.append(f"- **{g['gate']}** — {g['verdict']}: {tip}")
        L.append("")
    else:
        L += ["_None flagged._", ""]

    # 4. years
    yr, ya = gap.years_required, gap.years_available
    if yr and ya is not None and ya + 0.5 < yr:
        L += ["## 4. Experience shortfall", "",
              f"JD wants ~{yr:g} yrs; your dated timeline is ~{ya:g} yrs "
              f"(~{yr - ya:g}-yr gap). Expect it to come up — lead with depth, not tenure.", ""]

    # 5. thin (present but not fully covered), weight-3 first
    thin = [i for i in coverage.gaps() if i.status != "absent"]
    thin.sort(key=lambda i: (-i.weight, i.skill.lower()))
    if thin:
        L += [f"## 5. Thin coverage ({len(thin)})", "",
              "Present, but not across summary + skills + a bullet — expect a drill-down:", ""]
        for i in thin:
            spots = ", ".join(p for p, ok in (("summary", i.in_summary), ("skills", i.in_skills),
                                              ("a bullet", bool(i.in_bullets))) if ok)
            L.append(f"- **{i.skill}** (weight {i.weight}) — only in {spots}")
        L.append("")

    L += ["## Before you submit", "",
          "- [ ] Every section-1 bullet: kept with a real story, or cut",
          "- [ ] Every section-3 gate: confirmed true for you",
          "- [ ] Section-2 skills: you can honestly place each on the exposure↔expert scale",
          "- [ ] Rate, work authorization, location, availability ready for the recruiter call", ""]
    return "\n".join(L)
