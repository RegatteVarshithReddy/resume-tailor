"""Re-apply locked fields from the master profile onto the tailored resume.

Guarantees: same clients, same employers/vendors, same locations, same
start/end dates, same number and order of engagements — no matter what the
LLM returned.
"""

from __future__ import annotations

from .models import (
    Contact,
    MasterProfile,
    TailoredExperience,
    TailoredResume,
)


def lock_invariants(master: MasterProfile, tr: TailoredResume) -> list[str]:
    warnings: list[str] = []

    # contact + education + certifications always come straight from master
    tr.contact = Contact(**vars(master.contact))
    tr.education = list(master.education)
    tr.certifications = list(master.certifications)

    by_id = {e.id: e for e in tr.experience}
    rebuilt: list[TailoredExperience] = []

    for me in master.experience:
        te = by_id.get(me.id)
        if te is None:
            warnings.append(
                f"LLM omitted experience '{me.id}' ({me.client}); rebuilt from master bullets."
            )
            te = TailoredExperience(
                id=me.id, role=me.role, summary=me.summary, bullets=list(me.bullets),
                bullet_sources=[f"bullet:{i}" for i in range(len(me.bullets))],
            )

        # note drift before overwriting
        if te.client and _slug(te.client) != _slug(me.client):
            warnings.append(f"[{me.id}] client changed by LLM ('{te.client}' -> '{me.client}'); reverted.")
        if te.start and te.start != me.start:
            warnings.append(f"[{me.id}] start changed by LLM ('{te.start}' -> '{me.start}'); reverted.")
        if te.end and te.end != me.end:
            warnings.append(f"[{me.id}] end changed by LLM ('{te.end}' -> '{me.end}'); reverted.")

        # hard lock
        te.id = me.id
        te.client = me.client
        te.employer = me.employer
        te.location = me.location
        te.start = me.start
        te.end = me.end
        if not te.role:
            te.role = me.role
        if not te.bullets:
            te.bullets = list(me.bullets) or list(me.bullet_library)
            te.bullet_sources = [f"bullet:{i}" for i in range(len(te.bullets))]
            warnings.append(f"[{me.id}] LLM returned no bullets; used master bullets.")
        # keep bullet_sources parallel to bullets (pad unknowns)
        te.bullet_sources = (list(te.bullet_sources) + [""] * len(te.bullets))[: len(te.bullets)]
        rebuilt.append(te)

    extra = [eid for eid in by_id if eid not in {m.id for m in master.experience}]
    for eid in extra:
        warnings.append(f"LLM invented experience '{eid}' not in master; dropped.")

    tr.experience = rebuilt

    if not tr.summary:
        tr.summary = master.summary
        warnings.append("LLM returned no summary; used master summary.")
    if not tr.skill_groups:
        tr.skill_groups = list(master.skill_groups)
        warnings.append("LLM returned no skill groups; used master skill groups.")

    return warnings


def _slug(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())
