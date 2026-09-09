"""resume-tailor command line."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .config import DEFAULT_PROFILE, Paths, Settings, project_root

app = typer.Typer(
    add_completion=False,
    help="Tailor a full resume + cover letter to a vendor job requirement. "
    "Clients and work durations stay locked.",
)
apps_app = typer.Typer(add_completion=False, help="Browse the application tracker.")
app.add_typer(apps_app, name="apps")
profile_app = typer.Typer(add_completion=False, help="Manage the resume-profile library.")
app.add_typer(profile_app, name="profile")


def _err(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _read_data(name: str) -> str:
    try:
        from importlib.resources import files

        return (files("resume_tailor") / "data" / name).read_text()
    except Exception:  # noqa: BLE001
        return (Path(__file__).parent / "data" / name).read_text()


def _record_application(paths: Paths, result) -> str:
    from .store import Store

    g = result.gap
    store = Store(paths.db)
    return store.create_application(
        profile=result.profile,
        company=result.tailored.target_company or result.req.company,
        role=result.tailored.target_role or result.req.role,
        mode=result.mode,
        out_dir=str(result.out_dir),
        gap_matched=len(g.matched), gap_partial=len(g.partial), gap_missing=len(g.missing),
        years_required=g.years_required, years_available=g.years_available,
        pdf_engine=result.pdf_engine, warnings=len(result.warnings),
        missing=[m.skill for m in g.missing],
    )


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"resume-tailor {__version__}")


@app.command()
def init(
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile", "-p", help="Profile name to scaffold."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Scaffold profile/profiles/<name>/master_profile.yaml and profile/settings.yaml."""
    paths = Paths.resolve()
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.outputs.mkdir(parents=True, exist_ok=True)
    (paths.profiles_dir / profile).mkdir(parents=True, exist_ok=True)

    # migrate a legacy single-file profile into profiles/default/
    if paths.legacy_master.exists() and not (paths.profiles_dir / DEFAULT_PROFILE / "master_profile.yaml").exists():
        (paths.profiles_dir / DEFAULT_PROFILE).mkdir(parents=True, exist_ok=True)
        dest = paths.profiles_dir / DEFAULT_PROFILE / "master_profile.yaml"
        dest.write_text(paths.legacy_master.read_text())
        paths.legacy_master.rename(paths.legacy_master.with_suffix(".yaml.migrated"))
        typer.secho(f"migrated legacy master_profile.yaml -> {dest}", fg=typer.colors.GREEN)

    targets = [
        (paths.profiles_dir / profile / "master_profile.yaml", "master_profile.example.yaml"),
        (paths.settings, "settings.example.yaml"),
    ]
    wrote = []
    for target, data_name in targets:
        if target.exists() and not force:
            typer.secho(f"kept   {target}  (exists, use --force)", fg=typer.colors.YELLOW)
            continue
        target.write_text(_read_data(data_name))
        wrote.append(target)
        typer.secho(f"wrote  {target}", fg=typer.colors.GREEN)
    if wrote:
        typer.echo(f"\nNext: edit the master profile for '{profile}', then run:")
        typer.echo(f"  resume-tailor tailor --profile {profile} --jd path/to/job.txt")


@app.command()
def profiles() -> None:
    """List available master profiles."""
    names = Paths.resolve().list_profiles()
    if not names:
        _err("No profiles. Run `resume-tailor init`.")
    for n in names:
        typer.echo(n)


@app.command()
def models() -> None:
    """List the model choices for --model / the dashboard picker."""
    from .config import MODEL_CHOICES

    current = (Settings.load().model or "").strip().lower()
    for key, m in MODEL_CHOICES.items():
        mark = typer.style("  ← current", fg=typer.colors.CYAN) if key == current else ""
        typer.echo(f"  {key:8} {m['label']}{mark}")
    if current and current not in MODEL_CHOICES:
        typer.echo(f"\n  settings.model is '{current}' (custom id — passed straight to the engine)")
    typer.echo("\n  Set a default in profile/settings.yaml (model:) or override per run with --model.")


@app.command()
def engines() -> None:
    """List AI providers and whether each is ready (key present / reachable config)."""
    from .config import PROVIDERS

    s = Settings.load()
    for name, p in PROVIDERS.items():
        cfg = s.provider_config(name)
        ready = "ready" if (not p.get("needs_key") or s.provider_key(name)) else "needs key"
        active = typer.style("  ← active", fg=typer.colors.CYAN) if name == s.engine else ""
        base = f"  {cfg['base_url']}" if cfg["base_url"] else ""
        typer.echo(f"  {name:11} {ready:9} model={cfg['model'] or '-'}{base}{active}")
    typer.echo("\n  Configure these on the web Settings tab, or set `engine:` + `providers:` in "
               "settings.yaml.\n  Keys: env var (e.g. OPENAI_API_KEY) or profile/secrets.yaml.")


# ---- profile library subcommands ---------------------------------------
@profile_app.command("show")
def profile_show(name: str = typer.Argument(...)) -> None:
    """Print a profile's metadata, section layout and computed years."""
    from .profile_io import load_master

    try:
        mp = load_master(Paths.resolve(), name)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    m = mp.meta
    typer.echo(f"name              {name}")
    typer.echo(f"label             {m.label or '—'}")
    typer.echo(f"role_family       {', '.join(m.role_family) or '—'}")
    typer.echo(f"years_experience  {m.years_experience if m.years_experience is not None else '—'} "
               f"(dated timeline ~{mp.years_experience()})")
    typer.echo(f"seniority         {m.seniority or '—'}")
    typer.echo(f"experience        {len(mp.experience)} entries")
    typer.echo("sections          " + ", ".join(
        (s.key + ("" if s.show else " (hidden)")) for s in mp.layout.sections))


@profile_app.command("new")
def profile_new(
    name: str = typer.Argument(...),
    from_: Optional[str] = typer.Option(None, "--from", help="Clone this existing profile."),
) -> None:
    """Create a new profile (blank, or cloned with --from)."""
    from .profile_io import create_profile

    try:
        n = create_profile(Paths.resolve(), name, from_name=from_)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    typer.secho(f"created profile '{n}'", fg=typer.colors.GREEN)


@profile_app.command("rename")
def profile_rename(old: str = typer.Argument(...), new: str = typer.Argument(...)) -> None:
    """Rename a profile."""
    from .profile_io import rename_profile

    try:
        n = rename_profile(Paths.resolve(), old, new)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    typer.secho(f"{old} -> {n}", fg=typer.colors.GREEN)


@profile_app.command("delete")
def profile_delete(name: str = typer.Argument(...)) -> None:
    """Delete a profile (its master_profile.yaml is removed)."""
    from .profile_io import delete_profile

    try:
        delete_profile(Paths.resolve(), name)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    typer.secho(f"deleted '{name}'", fg=typer.colors.GREEN)


@profile_app.command("set")
def profile_set(
    name: str = typer.Argument(...),
    years: Optional[float] = typer.Option(None, "--years", help="meta.years_experience"),
    role_family: Optional[str] = typer.Option(None, "--role-family",
                                              help="Comma-separated, replaces the list."),
    label: Optional[str] = typer.Option(None, "--label"),
    seniority: Optional[str] = typer.Option(None, "--seniority"),
) -> None:
    """Quick edit of a profile's metadata without opening the YAML."""
    from .profile_io import load_master, save_master

    paths = Paths.resolve()
    try:
        d = load_master(paths, name).to_yaml_dict()
        meta = d.get("meta") or {}
        if years is not None:
            meta["years_experience"] = years
        if role_family is not None:
            meta["role_family"] = [x.strip() for x in role_family.split(",") if x.strip()]
        if label is not None:
            meta["label"] = label
        if seniority is not None:
            meta["seniority"] = seniority
        d["meta"] = meta
        save_master(paths, name, d)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    typer.secho(f"updated '{name}' metadata", fg=typer.colors.GREEN)


@app.command()
def gap(
    jd: Optional[Path] = typer.Option(None, "--jd", help="Job description file."),
    jd_text: Optional[str] = typer.Option(None, "--jd-text", help="Job description text."),
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile", "-p"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Heuristic parse only, no AI call."),
    engine: Optional[str] = typer.Option(None, "--engine", help="claude-cli | anthropic | openai | gemini | openrouter | ollama | custom (see `resume-tailor engines`)"),
    model: Optional[str] = typer.Option(None, "--model", help="opus | sonnet | haiku (or a full id)."),
) -> None:
    """Show the skills-gap report for a JD without generating documents."""
    from .llm import get_engine
    from .matcher import build_gap_report, estimate_match, heuristic_parse_jd, select_profile
    from .pipeline import extract_requirement, read_jd
    from .profile_io import load_master

    paths = Paths.resolve()
    settings = Settings.load()
    try:
        raw = read_jd(str(jd) if jd else None, jd_text)
        req = (
            heuristic_parse_jd(raw)
            if no_llm
            else extract_requirement(get_engine(settings, engine, model=model), raw, use_llm=True)
        )
        chosen, reason = select_profile(paths, req, profile)
        if (profile or "").lower() in ("", "auto"):
            typer.secho(f"  · profile: {chosen} ({reason})", fg=typer.colors.BRIGHT_BLACK)
        master = load_master(paths, chosen)
        report = build_gap_report(master, req)
        est = estimate_match(master, req, report, settings.match_weights)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    typer.echo(report.to_markdown(req))
    typer.secho(f"\nEstimated match (pre-tailor): {est.score}/100", fg=typer.colors.CYAN, bold=True)
    for w in est.weak_points:
        typer.echo(f"  · {w}")


@app.command()
def tailor(
    jd: Optional[Path] = typer.Option(None, "--jd", help="Job description file."),
    jd_text: Optional[str] = typer.Option(None, "--jd-text", help="JD text (or pipe via stdin)."),
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile", "-p", help="Master profile to use."),
    company: Optional[str] = typer.Option(None, "--company"),
    role: Optional[str] = typer.Option(None, "--role"),
    engine: Optional[str] = typer.Option(None, "--engine", help="claude-cli | anthropic | openai | gemini | openrouter | ollama | custom (see `resume-tailor engines`)"),
    model: Optional[str] = typer.Option(
        None, "--model", help="opus | sonnet | haiku (or a full model id). "
        "Default from settings; see `resume-tailor models`."),
    bullets: int = typer.Option(6, "--bullets", help="Max bullets per experience."),
    conservative: bool = typer.Option(False, "--conservative",
                                      help="Only rephrase real experience; do not weave in missing skills."),
    no_pdf: bool = typer.Option(False, "--no-pdf"),
    out: Optional[str] = typer.Option(None, "--out", help="Output subfolder name."),
    no_track: bool = typer.Option(False, "--no-track", help="Do not record this run in the tracker."),
    review_rounds: Optional[int] = typer.Option(
        None, "--review-rounds", help="Self-critique/revise passes (default from settings; 0 = off)."),
    variants: Optional[str] = typer.Option(
        None, "--variants", help="Comma list of angles (aggressive,conservative,ic,lead) -> comparison."),
) -> None:
    """Generate the tailored resume + cover letter (docx + pdf), a gap report,
    a coverage map and a match score."""
    from .pipeline import run_tailor

    paths = Paths.resolve()
    settings = Settings.load()

    raw_stdin = None
    if not jd and not jd_text and not sys.stdin.isatty():
        raw_stdin = sys.stdin.read().strip() or None

    angle_list = [a.strip() for a in (variants or "").split(",") if a.strip()]

    try:
        result = run_tailor(
            paths=paths, settings=settings, profile=profile,
            jd_file=str(jd) if jd else None, jd_text=jd_text or raw_stdin,
            company=company, role=role, engine_name=engine, model=model,
            aggressive=not conservative, max_bullets=bullets,
            make_pdf=not no_pdf, out_dir=out,
            review_rounds=review_rounds, variants=angle_list,
            progress=lambda m: typer.secho(f"  · {m}", fg=typer.colors.BRIGHT_BLACK),
        )
    except Exception as e:  # noqa: BLE001
        _err(f"{type(e).__name__}: {e}")
        return

    aid = None
    if not no_track:
        try:
            aid = _record_application(paths, result)
        except Exception as e:  # noqa: BLE001
            typer.secho(f"  (tracker write failed: {e})", fg=typer.colors.YELLOW)

    g = result.gap
    typer.secho(f"\n✔ Output: {result.out_dir}", fg=typer.colors.GREEN, bold=True)
    if aid:
        typer.echo(f"  tracked as: {aid}")
    typer.echo(f"  profile: {result.profile} · mode: {result.mode}")
    typer.echo(f"  gap: {len(g.matched)} matched · {len(g.partial)} partial · {len(g.missing)} missing")
    if g.years_required:
        typer.echo(f"  experience: need ~{g.years_required} yrs / have ~{g.years_available} yrs")
    typer.echo(f"  pdf engine: {result.pdf_engine}")
    if result.match:
        typer.secho(f"  match: {result.match.score}/100", fg=typer.colors.CYAN, bold=True)
    if result.coverage:
        c = result.coverage
        typer.echo(f"  coverage: {round(c.coverage_fraction() * 100)}%  "
                   f"({sum(1 for i in c.items if i.status == 'full')}/{len(c.items)} full, "
                   f"{len(c.stretch_bullets)} stretch)")
    if result.variants:
        best = sorted(result.variants,
                      key=lambda v: (-v.match.score, len(v.coverage.stretch_bullets)))[0]
        typer.echo("  variants: " + ", ".join(
            f"{v.angle} {v.match.score}/100" for v in result.variants)
            + f"  → recommended: {best.angle}")
    for key in ("resume_docx", "resume_pdf", "cover_letter_docx", "cover_letter_pdf",
                "match", "coverage", "comparison", "gap_report", "tailored_profile"):
        if key in result.files:
            typer.echo(f"  - {result.files[key]}")
    if result.warnings:
        typer.secho(f"\n  {len(result.warnings)} warning(s) (see warnings.txt):", fg=typer.colors.YELLOW)
        for w in result.warnings[:8]:
            typer.echo(f"    · {w}")
    if result.match and result.match.weak_points:
        typer.secho("\n  What's weak — fix or be ready to defend:", fg=typer.colors.YELLOW)
        for w in result.match.weak_points:
            typer.echo(f"    · {w}")
    elif g.missing:
        typer.secho("\n  Missing from your master profile — review before you send:",
                    fg=typer.colors.YELLOW)
        typer.echo("    " + ", ".join(m.skill for m in g.missing))


@app.command()
def render(
    tailored: Path = typer.Argument(..., help="Path to a tailored_profile.yaml to re-render."),
    no_pdf: bool = typer.Option(False, "--no-pdf"),
) -> None:
    """Re-render docx/pdf from an edited tailored_profile.yaml."""
    from .pipeline import rerender

    try:
        result = rerender(paths=Paths.resolve(), settings=Settings.load(),
                          tailored_yaml=str(tailored), make_pdf=not no_pdf)
    except Exception as e:  # noqa: BLE001
        _err(str(e))
        return
    typer.secho(f"✔ Re-rendered into {result.out_dir} (pdf: {result.pdf_engine})", fg=typer.colors.GREEN)
    for p in result.files.values():
        typer.echo(f"  - {p}")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Launch the local web app (dashboard + application tracker)."""
    from .webapp import serve

    typer.secho(f"resume-tailor  ->  http://{host}:{port}", fg=typer.colors.GREEN)
    typer.echo(f"project root: {project_root()}   (Ctrl+C to stop)")
    serve(host, port)


# ---- apps subcommands -----------------------------------------------------
@apps_app.command("list")
def apps_list(
    status: Optional[str] = typer.Option(None, "--status"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p"),
) -> None:
    """List tracked applications."""
    from .store import Store

    rows = Store(Paths.resolve().db).list_applications(status=status, profile=profile)
    if not rows:
        typer.echo("(none)")
        return
    for a in rows:
        typer.echo(
            f"{a['id']}  {a['status']:<9} {a['profile']:<14} "
            f"{(a['company'] or '—')[:28]:<28} {(a['role'] or '')[:30]:<30} "
            f"gap {a['gap_matched']}/{a['gap_partial']}/{a['gap_missing']}"
        )


@apps_app.command("show")
def apps_show(app_id: str = typer.Argument(...)) -> None:
    """Show one application."""
    from .store import Store

    a = Store(Paths.resolve().db).get_application(app_id)
    if not a:
        _err(f"no such application: {app_id}")
    for k, v in a.items():
        typer.echo(f"{k:16} {v}")


@apps_app.command("set-status")
def apps_set_status(app_id: str = typer.Argument(...), status: str = typer.Argument(...)) -> None:
    """Set an application's status (draft/applied/screening/interview/offer/rejected/archived)."""
    from .store import STATUSES, Store

    if status not in STATUSES:
        _err(f"status must be one of: {', '.join(STATUSES)}")
    Store(Paths.resolve().db).update_application(app_id, status=status)
    typer.secho(f"{app_id} -> {status}", fg=typer.colors.GREEN)


@apps_app.command("note")
def apps_note(app_id: str = typer.Argument(...), text: str = typer.Argument(...)) -> None:
    """Set an application's notes."""
    from .store import Store

    Store(Paths.resolve().db).update_application(app_id, notes=text)
    typer.secho("saved", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
