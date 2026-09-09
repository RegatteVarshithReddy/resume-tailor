"""LLM engines. Default routes through the local `claude` CLI (uses your Claude Code
subscription, no per-token API billing). Also: Anthropic API (native SDK) and any
OpenAI-compatible endpoint — OpenAI, Gemini, OpenRouter, Ollama, LM Studio, vLLM…"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import replace

from .config import PROVIDERS, Settings


class LLMError(Exception):
    pass


def _loads(s: str) -> dict:
    """json.loads, tolerating raw control chars (literal newlines/tabs) inside strings —
    models routinely emit those in long resume bullets."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return json.loads(s, strict=False)


def _repair(s: str) -> str:
    """Last-ditch: escape bare control characters that sit inside string literals."""
    out, in_str, esc = [], False, False
    for ch in s:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\" and in_str:
            out.append(ch)
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str and ch in "\n\r\t\b\f":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}[ch])
            continue
        out.append(ch)
    return "".join(out)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response (tolerates ``` fences / prose /
    raw control chars in strings)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
        t = t.strip()

    candidates = [t]
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(t[start : end + 1])

    last_err: Exception | None = None
    for chunk in candidates:
        for attempt in (chunk, _repair(chunk)):
            try:
                return _loads(attempt)
            except json.JSONDecodeError as e:
                last_err = e
    if last_err:
        raise LLMError(f"Model did not return valid JSON: {last_err}\n---\n{text[:2000]}") from last_err
    raise LLMError(f"No JSON object found in model response:\n{text[:2000]}")


class Engine:
    name = "base"

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def complete_json(self, system: str, prompt: str) -> dict:
        return extract_json(self.complete(system, prompt))


class ClaudeCLIEngine(Engine):
    name = "claude-cli"

    def __init__(self, settings: Settings):
        self.binary = shutil.which(settings.claude_binary) or settings.claude_binary
        self.model = settings.provider_config("claude-cli")["model"]
        self.timeout = settings.llm_timeout
        if not shutil.which(self.binary) and not shutil.which(settings.claude_binary):
            raise LLMError(
                "`claude` CLI not found on PATH. Install Claude Code, or pick a different "
                "provider on the Settings page (Anthropic / OpenAI / Gemini / Ollama / …)."
            )

    def ping(self) -> str:
        return self.complete("", "Reply with exactly: ok").strip()[:40]

    def complete(self, system: str, prompt: str) -> str:
        cmd = [self.binary, "-p", "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        if system:
            cmd += ["--append-system-prompt", system]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude CLI timed out after {self.timeout}s") from e
        if proc.returncode != 0:
            raise LLMError(
                f"claude CLI failed (exit {proc.returncode}):\n{proc.stderr.strip() or proc.stdout.strip()}"
            )
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"Could not parse claude CLI output: {e}\n{proc.stdout[:1000]}") from e
        if env.get("is_error"):
            raise LLMError(f"claude CLI returned an error: {env.get('result')}")
        return env.get("result", "")


class AnthropicAPIEngine(Engine):
    name = "anthropic"

    def __init__(self, settings: Settings):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise LLMError("The Anthropic SDK is not installed — run: pip install 'resume-tailor[api]' "
                           "(or pick OpenAI/Gemini/OpenRouter, which need no SDK).") from e
        import anthropic

        key = settings.provider_key("anthropic")
        if not key:
            raise LLMError("No Anthropic API key — set ANTHROPIC_API_KEY or add it on the Settings page.")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = settings.provider_config("anthropic")["model"] or "claude-sonnet-5"
        self.timeout = settings.llm_timeout

    def complete(self, system: str, prompt: str) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=system or None,
            messages=[{"role": "user", "content": prompt}],
            timeout=self.timeout,
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def ping(self) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=8,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}], timeout=30,
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


class OllamaEngine(Engine):
    name = "ollama"

    def __init__(self, settings: Settings):
        self.url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.llm_timeout

    def complete(self, system: str, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "system": system,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.4},
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Ollama call failed: {e}") from e
        return data.get("response", "")


class OpenAICompatEngine(Engine):
    """Any endpoint speaking OpenAI's POST /chat/completions — OpenAI, Gemini (its
    OpenAI-compat URL), OpenRouter, Groq, Ollama, LM Studio, vLLM, llama.cpp, …
    Pure stdlib: no `openai` package required."""

    def __init__(self, settings: Settings, provider: str | None = None):
        cfg = settings.provider_config(provider)
        self.name = self.provider = cfg["name"]
        self.base_url = cfg["base_url"]
        self.model = cfg["model"]
        self.api_key = settings.provider_key(cfg["name"])
        self.timeout = settings.llm_timeout
        if not self.base_url:
            raise LLMError(f"Provider '{self.provider}' has no base URL — set one on the Settings page.")
        if not self.model:
            raise LLMError(f"Provider '{self.provider}' has no model — set one on the Settings page.")
        if cfg["needs_key"] and not self.api_key:
            hint = f" (env {cfg['key_env']})" if cfg.get("key_env") else ""
            raise LLMError(f"No API key for '{self.provider}'{hint} — add it on the Settings page.")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _post(self, path: str, body: dict, _retry_no_temp: bool = True) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode(),
            headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode(errors="replace")[:800]
            except Exception:  # noqa: BLE001
                detail = ""
            if _retry_no_temp and e.code == 400 and "temperature" in detail.lower():
                body.pop("temperature", None)          # o-series / some models reject it
                return self._post(path, body, _retry_no_temp=False)
            raise LLMError(f"{self.provider} HTTP {e.code} on {path}: {detail or e.reason}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Cannot reach {self.provider} at {self.base_url} — {e.reason}. "
                           "Is the server running / the base URL right?") from e
        except (TimeoutError, json.JSONDecodeError) as e:
            raise LLMError(f"{self.provider} call failed: {e}") from e

    def complete(self, system: str, prompt: str) -> str:
        msgs = ([{"role": "system", "content": system}] if system else [])
        msgs.append({"role": "user", "content": prompt})
        data = self._post("/chat/completions",
                          {"model": self.model, "messages": msgs,
                           "temperature": 0.4, "stream": False})
        try:
            ch = data["choices"][0]
            return (ch.get("message") or {}).get("content") or ch.get("text") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"{self.provider}: unexpected response shape: {str(data)[:600]}") from e

    def list_models(self) -> list[str]:
        """GET /models — for the Settings 'Refresh' button (and `ollama pull`ed tags)."""
        req = urllib.request.Request(f"{self.base_url}/models", headers=self._headers())
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        items = data.get("data") if isinstance(data, dict) else data
        out = [(m.get("id") if isinstance(m, dict) else str(m)) for m in (items or [])]
        return sorted({m for m in out if m})

    def ping(self) -> str:
        data = self._post("/chat/completions",
                          {"model": self.model, "max_tokens": 8, "temperature": 0, "stream": False,
                           "messages": [{"role": "user", "content": "Reply with exactly: ok"}]})
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()


class MockEngine(Engine):
    """Deterministic, offline, no key — `--engine mock` / `engine: mock`.
    Canned (not real) output, for tests, CI and trying the flow with zero setup."""

    name = "mock"

    def __init__(self, settings: Settings | None = None):
        self.model = "mock"

    def complete(self, system: str, prompt: str) -> str:
        s = (system or "").lower()
        if "recruiter" in s or "extract the requirements" in prompt.lower():
            return json.dumps(self._extract(prompt))
        return json.dumps(self._tailor(prompt))

    def ping(self) -> str:
        return "ok"

    @staticmethod
    def _extract(prompt: str) -> dict:
        import re

        m = re.search(r'"""\n(.*?)\n"""', prompt, re.S)
        jd = m.group(1) if m else prompt
        vocab = ("Python", "Java", "JavaScript", "TypeScript", "AWS", "Azure", "GCP",
                 "Kubernetes", "Docker", "React", "Angular", "SQL", "PostgreSQL", "MySQL",
                 "Kafka", "Terraform", "Ansible", "Spring Boot", "Django", "FastAPI",
                 "CI/CD", "REST API", "GraphQL", "Go", "Snowflake", "Airflow", "Spark")
        skills = [k for k in vocab if re.search(re.escape(k), jd, re.I)][:8] or ["Python", "SQL"]
        ym = re.search(r"(\d+)\+?\s*years", jd, re.I)
        role = next((ln.strip() for ln in jd.splitlines() if ln.strip()), "Role")[:80]
        return {
            "company": "", "vendor": "", "role": role, "location": "", "employment_type": "",
            "min_years": int(ym.group(1)) if ym else None,
            "must_have_ranked": [{"skill": k, "weight": 3 if i == 0 else 2}
                                 for i, k in enumerate(skills)],
            "must_have_skills": skills, "nice_to_have_skills": [], "ats_keywords": skills,
            "hard_gates": [f"{ym.group(1)}+ years"] if ym else [],
            "archetype": "ic", "domains": [], "responsibilities": [],
        }

    @staticmethod
    def _tailor(prompt: str) -> dict:
        import re

        ids, seen = [], set()
        for i in re.findall(r'"id":\s*"([^"]+)"', prompt):
            if " " in i or len(i) > 40 or i in seen:   # skip the schema placeholder line
                continue
            seen.add(i)
            ids.append(i)
        skills = list(dict.fromkeys(re.findall(r'"skill":\s*"([^"]+)"', prompt)))[:8]
        lead = skills[:3] or ["the required stack"]
        exp = [{
            "id": i, "role": "", "summary": "",
            "bullets": [{"text": f"Delivered {sk} work mapped to the requirement.",
                         "source": "bullet:0"} for sk in lead],
        } for i in ids]
        return {
            "target_company": "", "target_role": "",
            "summary": ("Engineer aligned to the target requirement covering "
                        + ", ".join(skills[:5] or ["core skills"]) + "."),
            "skill_groups": [{"category": "Core", "skills": skills or ["Python"]}],
            "experience": exp,
            "cover_letter": ("Dear Hiring Manager,\n\nMy background maps directly onto this "
                             "requirement.\n\nRegards,\nCandidate"),
        }


def _build_engine(settings: Settings, name: str) -> Engine:
    if name == "mock":
        return MockEngine(settings)
    if name in ("claude-cli", "claude", "cli"):
        return ClaudeCLIEngine(settings)
    if name in ("api", "anthropic"):
        return AnthropicAPIEngine(settings)
    kind = (PROVIDERS.get(name) or {}).get("kind")
    if kind == "claude-cli":
        return ClaudeCLIEngine(settings)
    if kind == "anthropic":
        return AnthropicAPIEngine(settings)
    if kind == "openai-compat" or name in ("ollama", "local") or name not in PROVIDERS:
        # known compat provider, a legacy alias, or a user-named custom provider
        return OpenAICompatEngine(settings, provider=("ollama" if name == "local" else name))
    raise LLMError(f"Unknown provider '{name}'. See `resume-tailor engines`.")


def get_engine(settings: Settings, override: str | None = None,
               model: str | None = None) -> Engine:
    name = (override or settings.engine or "claude-cli").lower()
    if name == "api":
        name = "anthropic"
    eng = _build_engine(settings, name)
    if model:
        # per-run --model override: claude-cli expands opus/sonnet/haiku, others take it raw
        eng.model = (replace(settings, model=model).resolve_model("claude-cli")
                     if isinstance(eng, ClaudeCLIEngine) else model)
    return eng
