"""Load / validate / save master profiles, and profile-library operations."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from .config import DEFAULT_PROFILE, Paths
from .models import CORE_SECTIONS, MasterProfile, TailoredResume

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}$")


class ProfileError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def load_master(paths: Paths, profile: str = DEFAULT_PROFILE) -> MasterProfile:
    path = paths.master_profile(profile)
    if not path.exists():
        avail = paths.list_profiles()
        hint = (
            f"Available profiles: {', '.join(avail)}"
            if avail
            else "Run `resume-tailor init` and edit the master profile first."
        )
        raise ProfileError(f"Profile '{profile}' not found (looked for {path}).\n{hint}")
    return load_master_file(path)


def load_master_file(path: Path) -> MasterProfile:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ProfileError(f"Could not parse {path}: {e}") from e
    if not isinstance(data, dict):
        raise ProfileError(f"{path} must be a YAML mapping.")
    mp = MasterProfile.from_dict(data)
    _validate_master(mp, path)
    return mp


def load_master_meta(path: Path) -> dict:
    """Cheap read of just the `meta` block (for auto-routing). Never raises."""
    try:
        data = yaml.safe_load(path.read_text()) or {}
        m = data.get("meta") or {}
        return m if isinstance(m, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _validate_master(mp: MasterProfile, where: Path | str) -> None:
    errs: list[str] = []
    if not mp.contact.name:
        errs.append("contact.name is required")
    if not mp.experience:
        errs.append("at least one experience entry is required")
    seen: set[str] = set()
    for i, e in enumerate(mp.experience):
        tag = f"experience[{i}] ({e.client or '?'})"
        if not e.client:
            errs.append(f"{tag}: client is required")
        if not e.start:
            errs.append(f"{tag}: start (YYYY-MM) is required")
        if not e.end:
            errs.append(f"{tag}: end (YYYY-MM or Present) is required")
        if e.id in seen:
            errs.append(f"{tag}: duplicate id '{e.id}'")
        seen.add(e.id)
    if mp.meta.years_experience is not None and mp.meta.years_experience < 0:
        errs.append("meta.years_experience must be >= 0")
    sec_keys: set[str] = set()
    for s in mp.layout.sections:
        if not s.key:
            errs.append("layout: a section is missing its key")
            continue
        if not (s.key in CORE_SECTIONS or s.key.startswith("custom:")):
            errs.append(f"layout: unknown section key '{s.key}' "
                        f"(use one of {', '.join(CORE_SECTIONS)} or 'custom:<name>')")
        if s.key in sec_keys:
            errs.append(f"layout: duplicate section '{s.key}'")
        sec_keys.add(s.key)
    if errs:
        raise ProfileError(f"Invalid master profile ({where}):\n  - " + "\n  - ".join(errs))


# --------------------------------------------------------------------------- #
# Save + library operations
# --------------------------------------------------------------------------- #
def dump_master(mp: MasterProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(mp.to_yaml_dict(), sort_keys=False, allow_unicode=True))


def save_master(paths: Paths, name: str, data: dict) -> MasterProfile:
    """Validate `data` and write it to profile `name`'s master_profile.yaml."""
    name = _clean_name(name)
    if not isinstance(data, dict):
        raise ProfileError("Profile data must be a mapping.")
    mp = MasterProfile.from_dict(data)
    _validate_master(mp, f"profile '{name}'")
    dump_master(mp, paths.profiles_dir / name / "master_profile.yaml")
    return mp


def _clean_name(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"[\s_]+", "-", n)
    n = re.sub(r"[^a-z0-9-]", "", n).strip("-")
    if not _NAME_RE.match(n):
        raise ProfileError(
            f"Invalid profile name '{name}'. Use lowercase letters, digits and hyphens "
            "(1-39 chars), e.g. 'ai-engineer'."
        )
    return n


def _example_yaml() -> str:
    for cand in (
        Path(__file__).parent / "data" / "master_profile.example.yaml",
    ):
        if cand.exists():
            return cand.read_text()
    # minimal fallback
    return (
        "contact:\n  name: \"Your Name\"\n  title: \"\"\n"
        "summary: \"\"\nskill_groups: []\n"
        "experience:\n  - id: role1\n    client: \"Company\"\n    employer: \"\"\n"
        "    role: \"\"\n    location: \"\"\n    start: \"2023-01\"\n    end: \"Present\"\n"
        "    environment: []\n    bullets: []\n    bullet_library: []\n"
        "education: []\ncertifications: []\nextra_bullets: []\n"
    )


def create_profile(paths: Paths, name: str, from_name: str | None = None) -> str:
    """Create a new profile dir. Clone `from_name` if given, else scaffold from the example."""
    name = _clean_name(name)
    dest = paths.profiles_dir / name
    if dest.exists():
        raise ProfileError(f"Profile '{name}' already exists.")
    dest.mkdir(parents=True, exist_ok=True)
    if from_name:
        src = paths.master_profile(from_name)
        if not src.exists():
            shutil.rmtree(dest, ignore_errors=True)
            raise ProfileError(f"Source profile '{from_name}' not found.")
        (dest / "master_profile.yaml").write_text(src.read_text())
    else:
        (dest / "master_profile.yaml").write_text(_example_yaml())
    return name


def rename_profile(paths: Paths, old: str, new: str) -> str:
    new = _clean_name(new)
    src = paths.profiles_dir / old
    if not (src / "master_profile.yaml").exists():
        raise ProfileError(f"Profile '{old}' not found.")
    dest = paths.profiles_dir / new
    if dest.exists():
        raise ProfileError(f"Profile '{new}' already exists.")
    src.rename(dest)
    return new


def delete_profile(paths: Paths, name: str) -> None:
    if len(paths.list_profiles()) <= 1:
        raise ProfileError("Can't delete the last remaining profile.")
    d = paths.profiles_dir / name
    if not (d / "master_profile.yaml").exists():
        raise ProfileError(f"Profile '{name}' not found.")
    shutil.rmtree(d)


# --------------------------------------------------------------------------- #
# Tailored profile round-trip (used by rerender)
# --------------------------------------------------------------------------- #
def load_tailored(path: Path) -> TailoredResume:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ProfileError(f"{path} must be a YAML mapping.")
    return TailoredResume.from_dict(data)


def dump_tailored(tr: TailoredResume, path: Path) -> None:
    path.write_text(yaml.safe_dump(tr.to_yaml_dict(), sort_keys=False, allow_unicode=True))
