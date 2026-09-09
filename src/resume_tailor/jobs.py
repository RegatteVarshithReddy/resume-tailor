"""In-process background job runner for the web app.

Single worker thread (jobs are long and single-user); state + logs in the store.
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Paths, Settings
from .pipeline import rerender, run_tailor
from .store import Store

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rt-job")


def submit_tailor(store: Store, paths: Paths, settings: Settings, params: dict) -> str:
    """params: profile, jd_text, company, role, aggressive(bool), max_bullets(int),
    make_pdf(bool), review_rounds(int|None), variants(list[str]), model(str|None)."""
    jid = store.create_job("tailor", params)
    _pool.submit(_run_tailor_job, jid, store, paths, settings, params)
    return jid


def submit_rerender(store: Store, paths: Paths, settings: Settings, app_id: str) -> str:
    jid = store.create_job("rerender", {"app_id": app_id})
    _pool.submit(_run_rerender_job, jid, store, paths, settings, app_id)
    return jid


def _run_tailor_job(jid, store: Store, paths: Paths, settings: Settings, params: dict) -> None:
    store.update_job(jid, state="running")
    log = lambda m: store.append_job_log(jid, m)  # noqa: E731
    try:
        result = run_tailor(
            paths=paths,
            settings=settings,
            profile=params.get("profile", "default"),
            jd_text=params["jd_text"],
            company=params.get("company") or None,
            role=params.get("role") or None,
            model=params.get("model") or None,
            aggressive=params.get("aggressive", True),
            max_bullets=int(params.get("max_bullets", 6)),
            make_pdf=params.get("make_pdf", True),
            review_rounds=params.get("review_rounds"),
            variants=params.get("variants") or [],
            progress=log,
        )
        g = result.gap
        aid = store.create_application(
            profile=result.profile,
            company=result.tailored.target_company or params.get("company"),
            role=result.tailored.target_role or params.get("role"),
            mode=result.mode,
            out_dir=str(result.out_dir),
            gap_matched=len(g.matched),
            gap_partial=len(g.partial),
            gap_missing=len(g.missing),
            years_required=g.years_required,
            years_available=g.years_available,
            pdf_engine=result.pdf_engine,
            warnings=len(result.warnings),
            missing=[m.skill for m in g.missing],
            match_score=(result.match.score if result.match else None),
            variant_chosen=(result.variants[0].angle if result.variants else ""),
        )
        store.update_job(jid, state="done", app_id=aid)
        log(f"application {aid} saved")
    except Exception as e:  # noqa: BLE001
        store.update_job(jid, state="error", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        log(f"ERROR: {e}")


def _run_rerender_job(jid, store: Store, paths: Paths, settings: Settings, app_id: str) -> None:
    store.update_job(jid, state="running", app_id=app_id)
    try:
        app = store.get_application(app_id)
        if not app:
            raise RuntimeError(f"application {app_id} not found")
        ty = Path(app["out_dir"]) / "tailored_profile.yaml"
        result = rerender(paths=paths, settings=settings, tailored_yaml=str(ty))
        store.update_application(app_id, pdf_engine=result.pdf_engine)
        store.update_job(jid, state="done")
        store.append_job_log(jid, "re-rendered")
    except Exception as e:  # noqa: BLE001
        store.update_job(jid, state="error", error=str(e))
        store.append_job_log(jid, f"ERROR: {e}")
