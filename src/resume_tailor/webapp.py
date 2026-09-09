"""resume-tailor web app: dashboard + application tracker + background jobs.

Dependency-light: stdlib http.server routing + Jinja2 templates.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .config import (
    DEFAULT_ENGINE,
    DEFAULT_MODEL,
    MODEL_CHOICES,
    PROVIDERS,
    Paths,
    Settings,
    clear_secret,
    load_ui_state,
    save_secret,
    save_settings,
    save_ui_state,
)
from .pipeline import VARIANT_ANGLES
from .jobs import submit_rerender, submit_tailor
from .models import CORE_SECTIONS, MasterProfile, SectionSpec
from .profile_io import (
    ProfileError,
    create_profile,
    delete_profile,
    load_master,
    load_master_meta,
    rename_profile,
    save_master,
)
from .store import STATUSES, Store
from .webforms import parse_profile_form

_TPL_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TPL_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _fmt_ts(v) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


_env.filters["timestamp"] = _fmt_ts

_CTYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
}

DOWNLOADS = [
    ("resume.pdf", "Resume PDF"),
    ("resume.docx", "Resume DOCX"),
    ("cover_letter.pdf", "Cover letter PDF"),
    ("cover_letter.docx", "Cover letter DOCX"),
    ("cover_letter.txt", "Cover letter text"),
    ("match.md", "Match score"),
    ("coverage.md", "Coverage map"),
    ("gap_report.md", "Gap report"),
    ("comparison.md", "Variant comparison"),
    ("tailored_profile.yaml", "Tailored profile (editable)"),
    ("requirements.json", "Extracted requirements"),
    ("job.txt", "Job description"),
    ("warnings.txt", "Warnings"),
]


class App:
    def __init__(self, paths: Paths, settings: Settings):
        self.paths = paths
        self.settings = settings
        self.store = Store(paths.db)

    # -- helpers -----------------------------------------------------
    def render(self, tpl: str, **ctx) -> bytes:
        ctx.setdefault("version", __version__)
        ctx.setdefault("engine", self.settings.engine)
        ctx.setdefault("profiles", self.paths.list_profiles())
        ctx.setdefault("statuses", STATUSES)
        return _env.get_template(tpl).render(**ctx).encode("utf-8")

    def _files_for(self, out_dir: str) -> list[dict]:
        d = Path(out_dir)
        out = []
        for name, label in DOWNLOADS:
            f = d / name
            if f.exists():
                out.append({"label": label, "name": name,
                            "url": "/file?path=" + urllib.parse.quote(str(f))})
        return out

    def _safe_output_path(self, raw: str) -> Path | None:
        base = self.paths.outputs.resolve()
        p = Path(raw).resolve()
        if base in p.parents and p.is_file():
            return p
        return None

    # -- pages -----------------------------------------------------
    def page_dashboard(self) -> bytes:
        ui = load_ui_state(self.paths.root)
        return self.render(
            "dashboard.html",
            counts=self.store.counts_by_status(),
            recent=self.store.list_applications(limit=15),
            jobs=[j for j in self.store.recent_jobs(8) if j["state"] in ("queued", "running")],
            default_bullets=6,
            review_rounds=self.settings.review_rounds,
            variant_angles=list(VARIANT_ANGLES.keys()),
            picked_variants=set(ui.get("variants") or []),
            model_choices=[(k, v["label"]) for k, v in MODEL_CHOICES.items()],
            model_current=(ui.get("model") or self.settings.model or DEFAULT_MODEL),
        )

    def page_apps(self, qs: dict) -> bytes:
        status = (qs.get("status") or [""])[0] or None
        profile = (qs.get("profile") or [""])[0] or None
        return self.render(
            "apps.html",
            apps=self.store.list_applications(status=status, profile=profile),
            f_status=status, f_profile=profile,
            counts=self.store.counts_by_status(),
        )

    def _read_json(self, p: Path) -> dict:
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def page_app(self, aid: str) -> bytes | None:
        app = self.store.get_application(aid)
        if not app:
            return None
        d = Path(app["out_dir"])
        rd = lambda name: (d / name).read_text() if (d / name).exists() else ""  # noqa: E731
        try:
            missing = json.loads(app.get("missing_json") or "[]")
        except json.JSONDecodeError:
            missing = []
        variants = []
        for angle in VARIANT_ANGLES:
            vd = d / angle
            if (vd / "match.json").exists():
                mj = self._read_json(vd / "match.json")
                cj = self._read_json(vd / "coverage.json")
                variants.append({
                    "angle": angle, "score": mj.get("score"),
                    "coverage": round((cj.get("fraction") or 0) * 100),
                    "stretch": cj.get("stretch", 0),
                    "files": [
                        {"label": lbl, "name": nm,
                         "url": "/file?path=" + urllib.parse.quote(str(vd / nm))}
                        for nm, lbl in DOWNLOADS if (vd / nm).exists()
                    ],
                })
        return self.render(
            "app.html",
            app=app, files=self._files_for(app["out_dir"]),
            gap_report=rd("gap_report.md"), cover_letter=rd("cover_letter.txt"),
            coverage_md=rd("coverage.md"), match_md=rd("match.md"),
            comparison_md=rd("comparison.md"),
            match=self._read_json(d / "match.json"),
            coverage=self._read_json(d / "coverage.json"),
            variants=variants, missing=missing,
        )

    def page_job(self, jid: str) -> bytes | None:
        job = self.store.get_job(jid)
        if not job:
            return None
        return self.render("job.html", job=job)

    # -- profile library -----------------------------------------
    def page_profiles(self) -> bytes:
        rows = []
        for n in self.paths.list_profiles():
            meta = load_master_meta(self.paths.master_profile(n))
            rows.append({
                "name": n,
                "label": meta.get("label") or "",
                "years": meta.get("years_experience"),
                "role_family": ", ".join(str(x) for x in (meta.get("role_family") or [])),
            })
        return self.render("profiles.html", rows=rows)

    def _edit_ctx(self, name: str, spare: int, err: str = "", mp=None) -> dict:
        mp = mp or load_master(self.paths, name)
        by_key = {s.key: s for s in mp.layout.sections}
        core = [by_key.get(k) or SectionSpec(key=k, show=False) for k in CORE_SECTIONS]
        custom = [s for s in mp.layout.sections if s.is_custom]
        return {
            "name": name, "mp": mp, "spare": spare, "error": err,
            "core_sections": core, "custom_sections": custom,
            "core_keys": list(CORE_SECTIONS),
        }

    def page_profile_edit(self, name: str, spare: int = 2, err: str = "", mp=None) -> bytes | None:
        try:
            ctx = self._edit_ctx(name, spare, err, mp)
        except ProfileError:
            return None
        return self.render("profile_edit.html", **ctx)

    # -- profile actions ---------------------------------------------
    def act_profile_save(self, name: str, form: dict):
        data = parse_profile_form(form)
        save_master(self.paths, name, data)

    def act_profile_new(self, form: dict) -> str:
        name = (form.get("name") or [""])[0]
        return create_profile(self.paths, name)

    def act_profile_clone(self, src: str, form: dict) -> str:
        new = (form.get("new_name") or [""])[0]
        return create_profile(self.paths, new, from_name=src)

    def act_profile_rename(self, src: str, form: dict) -> str:
        new = (form.get("new_name") or [""])[0]
        return rename_profile(self.paths, src, new)

    def act_profile_delete(self, name: str) -> None:
        delete_profile(self.paths, name)

    # -- settings tab ------------------------------------------------
    def _provider_rows(self, s: Settings, discovered: dict | None = None) -> list[dict]:
        discovered = discovered or {}
        rows = []
        for name, preset in PROVIDERS.items():
            cfg = s.provider_config(name)
            models = list(dict.fromkeys(list(preset.get("models", [])) + discovered.get(name, [])))
            rows.append({
                "name": name,
                "label": preset["label"],
                "kind": preset["kind"],
                "is_compat": preset["kind"] == "openai-compat",
                "needs_key": bool(preset.get("needs_key")),
                "key_env": preset.get("key_env"),
                "base_url": cfg["base_url"],
                "model": cfg["model"],
                "models": models,
                "signup": preset.get("signup"),
                "help": preset.get("help"),
                "has_key": bool(s.provider_key(name, self.paths.root)),
                "active": name == (s.engine or DEFAULT_ENGINE),
            })
        return rows

    def page_settings(self, *, saved: bool = False, err: str = "",
                      banner: str = "", discovered: dict | None = None) -> bytes:
        self.settings = Settings.load(self.paths.root)
        s = self.settings
        return self.render(
            "settings.html",
            rows=self._provider_rows(s, discovered),
            s=s, weights=s.match_weights, page_sizes=["letter", "a4"],
            active_engine=s.engine or DEFAULT_ENGINE,
            saved=saved, err=err, banner=banner,
        )

    def _apply_settings_form(self, form: dict) -> None:
        g = lambda k, d="": (form.get(k) or [d])[0].strip()  # noqa: E731
        engine = g("engine") or DEFAULT_ENGINE
        if engine not in PROVIDERS:
            raise ValueError(f"Unknown provider: {engine}")

        providers: dict = {}
        for name, preset in PROVIDERS.items():
            entry: dict = {}
            if (m := g(f"model_{name}")):
                entry["model"] = m
            if preset["kind"] == "openai-compat" and (b := g(f"base_url_{name}")):
                entry["base_url"] = b.rstrip("/")
            if entry:
                providers[name] = entry
            # API keys -> secrets.yaml only
            if form.get(f"clear_key_{name}"):
                clear_secret(name, self.paths.root)
            elif (k := g(f"key_{name}")) and set(k) != {"•"}:
                save_secret(name, k, self.paths.root)

        try:
            rounds = max(0, min(3, int(g("review_rounds") or "2")))
        except ValueError:
            rounds = 2
        weights = {}
        for wk in ("coverage", "years", "domain", "archetype"):
            try:
                weights[wk] = round(float(g(f"w_{wk}")), 3)
            except ValueError:
                pass

        data = {
            "engine": engine,
            "claude_binary": self.settings.claude_binary or "claude",
            "providers": providers,
            "llm_timeout": self.settings.llm_timeout,
            "make_pdf": g("make_pdf", "1") == "1",
            "page_size": g("page_size") or "letter",
            "accent_color": g("accent_color") or "#1F4E79",
            "review_rounds": rounds,
        }
        if len(weights) == 4:
            data["match_weights"] = weights
        save_settings(self.paths, data)
        self.settings = Settings.load(self.paths.root)

    def act_settings(self, form: dict) -> tuple[str, dict]:
        """Save, then optionally test/refresh one provider. -> (banner, discovered)."""
        self._apply_settings_form(form)
        do = (form.get("do") or [""])[0]
        if ":" not in do:
            return "", {}
        verb, name = do.split(":", 1)
        if name not in PROVIDERS:
            return "", {}
        from .llm import LLMError, get_engine
        try:
            eng = get_engine(self.settings, override=name)
            if verb == "refresh":
                got = eng.list_models() if hasattr(eng, "list_models") else []
                return (f"{name}: found {len(got)} model(s)." if got
                        else f"{name}: no models returned."), {name: got}
            out = eng.ping() if hasattr(eng, "ping") else eng.complete("", "ok")
            return f"✓ {name} OK — model {getattr(eng, 'model', '?')} replied {out[:60]!r}", {}
        except LLMError as e:
            return f"✗ {name} — {e}", {}
        except Exception as e:  # noqa: BLE001
            return f"✗ {name} — {type(e).__name__}: {e}", {}

    def job_json(self, jid: str) -> bytes | None:
        job = self.store.get_job(jid)
        if not job:
            return None
        return json.dumps({
            "id": job["id"], "state": job["state"], "kind": job["kind"],
            "app_id": job["app_id"], "log": job["log"], "error": job["error"],
        }).encode()

    # -- actions ---------------------------------------------------
    def act_run(self, form: dict) -> str:
        jd = (form.get("jd") or [""])[0].strip()
        if not jd:
            raise ValueError("Job description is required.")
        variants = [v for v in form.get("variants", []) if v in VARIANT_ANGLES]
        try:
            rounds = max(0, min(3, int((form.get("review_rounds") or [""])[0])))
        except (TypeError, ValueError):
            rounds = self.settings.review_rounds
        model = (form.get("model") or [""])[0].strip().lower()
        model = model if model in MODEL_CHOICES else ""
        save_ui_state({"variants": variants, "model": model}, self.paths.root)
        params = {
            "profile": (form.get("profile") or ["auto"])[0],
            "jd_text": jd,
            "company": (form.get("company") or [""])[0].strip(),
            "role": (form.get("role") or [""])[0].strip(),
            "aggressive": (form.get("mode") or ["aggressive"])[0] != "conservative",
            "max_bullets": int((form.get("bullets") or ["6"])[0] or 6),
            "make_pdf": (form.get("pdf") or ["1"])[0] == "1",
            "review_rounds": rounds,
            "variants": variants,
            "model": model or None,
        }
        return submit_tailor(self.store, self.paths, self.settings, params)

    def act_status(self, aid: str, form: dict) -> None:
        st = (form.get("status") or [""])[0]
        if st in STATUSES:
            self.store.update_application(aid, status=st)

    def act_note(self, aid: str, form: dict) -> None:
        self.store.update_application(aid, notes=(form.get("notes") or [""])[0])

    def act_rerender(self, aid: str) -> str:
        return submit_rerender(self.store, self.paths, self.settings, aid)

    def act_promote(self, aid: str, form: dict) -> None:
        import shutil

        angle = (form.get("angle") or [""])[0]
        app = self.store.get_application(aid)
        if not app or angle not in VARIANT_ANGLES:
            raise ValueError("Unknown application or variant.")
        d = Path(app["out_dir"])
        vd = d / angle
        if not (vd / "match.json").exists():
            raise ValueError(f"Variant '{angle}' not found for this run.")
        for f in vd.iterdir():
            if f.is_file():
                shutil.copy2(f, d / f.name)
        mj = self._read_json(vd / "match.json")
        self.store.update_application(
            aid, match_score=mj.get("score"), variant_chosen=angle
        )

    def act_delete(self, aid: str) -> None:
        self.store.delete_application(aid)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"resume-tailor/{__version__}"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body: bytes, ctype="text/html; charset=utf-8", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _redirect(self, loc: str):
            self.send_response(303)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _form(self) -> dict:
            n = int(self.headers.get("Content-Length", 0))
            return urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))

        def _err(self, code, msg):
            self._send(code, app.render("error.html", message=msg, code=code), extra=None)

        # -- GET --------------------------------------------------
        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            path, qs = u.path, urllib.parse.parse_qs(u.query)
            try:
                if path == "/healthz":
                    return self._send(200, b"ok", "text/plain")
                if path in ("/", "/dashboard"):
                    return self._send(200, app.page_dashboard())
                if path == "/apps":
                    return self._send(200, app.page_apps(qs))
                if path == "/profiles":
                    return self._send(200, app.page_profiles())
                if path == "/settings":
                    return self._send(200, app.page_settings())
                m = re.fullmatch(r"/profiles/([a-z0-9-]+)/edit", path)
                if m:
                    try:
                        spare = max(0, min(30, int((qs.get("rows") or ["2"])[0])))
                    except ValueError:
                        spare = 2
                    body = app.page_profile_edit(m.group(1), spare=spare)
                    return self._send(200, body) if body else self._err(404, "Profile not found.")
                m = re.fullmatch(r"/apps/([A-Za-z0-9_]+)", path)
                if m:
                    body = app.page_app(m.group(1))
                    return self._send(200, body) if body else self._err(404, "Application not found.")
                m = re.fullmatch(r"/jobs/([A-Za-z0-9_]+)\.json", path)
                if m:
                    body = app.job_json(m.group(1))
                    return self._send(200, body, "application/json") if body else self._err(404, "job?")
                m = re.fullmatch(r"/jobs/([A-Za-z0-9_]+)", path)
                if m:
                    body = app.page_job(m.group(1))
                    return self._send(200, body) if body else self._err(404, "Job not found.")
                if path == "/file":
                    return self._serve_file(qs)
                return self._err(404, "Not found.")
            except Exception as e:  # noqa: BLE001
                return self._err(500, f"{type(e).__name__}: {e}")

        def _serve_file(self, qs):
            raw = (qs.get("path") or [""])[0]
            p = app._safe_output_path(raw)
            if not p:
                return self._err(404, "File not found or outside outputs/.")
            data = p.read_bytes()
            self._send(200, data, _CTYPES.get(p.suffix, "application/octet-stream"),
                       extra={"Content-Disposition": f'inline; filename="{p.name}"'})

        # -- POST -------------------------------------------------
        def do_POST(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            try:
                if path == "/run":
                    jid = app.act_run(self._form())
                    return self._redirect(f"/jobs/{jid}")
                if path == "/settings":
                    try:
                        banner, discovered = app.act_settings(self._form())
                    except ValueError as e:
                        return self._send(400, app.page_settings(err=str(e)))
                    return self._send(200, app.page_settings(saved=True, banner=banner,
                                                             discovered=discovered))
                if path == "/profiles/new":
                    try:
                        n = app.act_profile_new(self._form())
                    except ProfileError as e:
                        return self._err(400, str(e))
                    return self._redirect(f"/profiles/{n}/edit")
                m = re.fullmatch(r"/profiles/([a-z0-9-]+)/clone", path)
                if m:
                    try:
                        n = app.act_profile_clone(m.group(1), self._form())
                    except ProfileError as e:
                        return self._err(400, str(e))
                    return self._redirect(f"/profiles/{n}/edit")
                m = re.fullmatch(r"/profiles/([a-z0-9-]+)/rename", path)
                if m:
                    try:
                        n = app.act_profile_rename(m.group(1), self._form())
                    except ProfileError as e:
                        return self._err(400, str(e))
                    return self._redirect("/profiles")
                m = re.fullmatch(r"/profiles/([a-z0-9-]+)/delete", path)
                if m:
                    try:
                        app.act_profile_delete(m.group(1))
                    except ProfileError as e:
                        return self._err(400, str(e))
                    return self._redirect("/profiles")
                m = re.fullmatch(r"/profiles/([a-z0-9-]+)", path)
                if m:
                    form = self._form()
                    try:
                        app.act_profile_save(m.group(1), form)
                    except ProfileError as e:
                        # re-render the form with the submitted values + the error
                        mp = MasterProfile.from_dict(parse_profile_form(form))
                        body = app.page_profile_edit(m.group(1), spare=2, err=str(e), mp=mp)
                        return self._send(400, body) if body else self._err(400, str(e))
                    return self._redirect(f"/profiles/{m.group(1)}/edit")
                m = re.fullmatch(r"/apps/([A-Za-z0-9_]+)/status", path)
                if m:
                    app.act_status(m.group(1), self._form())
                    return self._redirect(f"/apps/{m.group(1)}")
                m = re.fullmatch(r"/apps/([A-Za-z0-9_]+)/note", path)
                if m:
                    app.act_note(m.group(1), self._form())
                    return self._redirect(f"/apps/{m.group(1)}")
                m = re.fullmatch(r"/apps/([A-Za-z0-9_]+)/rerender", path)
                if m:
                    jid = app.act_rerender(m.group(1))
                    return self._redirect(f"/jobs/{jid}")
                m = re.fullmatch(r"/apps/([A-Za-z0-9_]+)/promote", path)
                if m:
                    app.act_promote(m.group(1), self._form())
                    return self._redirect(f"/apps/{m.group(1)}")
                m = re.fullmatch(r"/apps/([A-Za-z0-9_]+)/delete", path)
                if m:
                    app.act_delete(m.group(1))
                    return self._redirect("/apps")
                return self._err(404, "Not found.")
            except ValueError as e:
                return self._err(400, str(e))
            except Exception as e:  # noqa: BLE001
                return self._err(500, f"{type(e).__name__}: {e}")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000,
          paths: Paths | None = None, settings: Settings | None = None) -> None:
    paths = paths or Paths.resolve()
    settings = settings or Settings.load()
    app = App(paths, settings)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
