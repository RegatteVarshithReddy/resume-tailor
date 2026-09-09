"""Parse the structured profile-editor form (flat + indexed fields) into the
`master_profile.yaml` mapping that `profile_io.save_master` expects.

Field names:
  contact.<field>                         flat
  summary, extra_bullets                  flat (extra_bullets: one per line)
  meta.label / .role_family / .years_experience / .seniority / .notes
  exp.<i>.<field>   client employer role location start end summary
  exp.<i>.environment / .bullets / .bullet_library    (textarea, one per line)
  skill.<i>.category / .skills
  edu.<i>.degree / .field / .institution / .location / .year
  cert.<i>.name / .issuer / .year
  sec.<i>.key / .title / .show / .style / .max_items / .date_format / .content
  *.<i>.order      optional numeric sort key per row
"""

from __future__ import annotations

import re

CONTACT_FIELDS = (
    "name", "title", "email", "phone", "location", "linkedin", "website",
    "work_authorization",
)


def _s(form: dict, key: str) -> str:
    v = form.get(key)
    return (v[0].strip() if v else "")


def _lines(s: str) -> list[str]:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()]


def _csv_or_lines(s: str) -> list[str]:
    s = s or ""
    if "\n" in s:
        return _lines(s)
    return [x.strip() for x in s.split(",") if x.strip()]


def _rows(form: dict, prefix: str) -> list[dict]:
    pat = re.compile(rf"^{re.escape(prefix)}\.(\d+)\.(.+)$")
    bucket: dict[int, dict] = {}
    for k, vals in form.items():
        m = pat.match(k)
        if not m:
            continue
        bucket.setdefault(int(m.group(1)), {})[m.group(2)] = (vals[0] if vals else "")
    ordered: list[tuple[float, int, dict]] = []
    for i, row in bucket.items():
        raw = str(row.pop("order", i)).strip()
        try:
            o = float(raw)
        except ValueError:
            o = float(i)
        ordered.append((o, i, row))
    ordered.sort(key=lambda t: (t[0], t[1]))
    return [row for _, _, row in ordered]


def parse_profile_form(form: dict) -> dict:
    d: dict = {}
    d["contact"] = {f: _s(form, f"contact.{f}") for f in CONTACT_FIELDS}
    d["summary"] = _s(form, "summary")
    d["extra_bullets"] = _lines(_s(form, "extra_bullets"))
    d["meta"] = {
        "label": _s(form, "meta.label"),
        "role_family": _csv_or_lines(_s(form, "meta.role_family")),
        "years_experience": _s(form, "meta.years_experience") or None,
        "seniority": _s(form, "meta.seniority"),
        "notes": _s(form, "meta.notes"),
    }

    exp = []
    for r in _rows(form, "exp"):
        g = r.get
        if not (g("client", "").strip() or g("role", "").strip() or g("start", "").strip()):
            continue
        exp.append({
            "id": g("id", "").strip(),
            "client": g("client", "").strip(),
            "employer": g("employer", "").strip(),
            "role": g("role", "").strip(),
            "location": g("location", "").strip(),
            "start": g("start", "").strip(),
            "end": g("end", "").strip(),
            "environment": _csv_or_lines(g("environment", "")),
            "summary": g("summary", "").strip(),
            "bullets": _lines(g("bullets", "")),
            "bullet_library": _lines(g("bullet_library", "")),
        })
    d["experience"] = exp

    skills = []
    for r in _rows(form, "skill"):
        cat = r.get("category", "").strip()
        sk = _csv_or_lines(r.get("skills", ""))
        if cat or sk:
            skills.append({"category": cat, "skills": sk})
    d["skill_groups"] = skills

    edu = []
    for r in _rows(form, "edu"):
        if any(r.get(f, "").strip() for f in ("degree", "field", "institution")):
            edu.append({f: r.get(f, "").strip()
                        for f in ("degree", "field", "institution", "location", "year")})
    d["education"] = edu

    certs = []
    for r in _rows(form, "cert"):
        if r.get("name", "").strip():
            certs.append({f: r.get(f, "").strip() for f in ("name", "issuer", "year")})
    d["certifications"] = certs

    secs = []
    for r in _rows(form, "sec"):
        key = r.get("key", "").strip()
        if not key:
            continue
        spec: dict = {
            "key": key,
            "title": r.get("title", "").strip(),
            "show": r.get("show", "").strip().lower() in ("1", "on", "true", "yes"),
            "style": r.get("style", "").strip(),
            "max_items": r.get("max_items", "").strip() or None,
            "date_format": r.get("date_format", "").strip(),
        }
        if key.startswith("custom:"):
            spec["content"] = _lines(r.get("content", ""))
        secs.append(spec)
    if secs:
        d["layout"] = {"sections": secs}
    return d
