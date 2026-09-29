"""Gmail-based application status suggestions.

Read-only (`gmail.readonly`) access via a one-time OAuth flow you run yourself
on a machine with a browser (`resume-tailor gmail-auth`) — see deploy/DEPLOY.md
for the Google Cloud Console setup. This module only ever *reads* mail and
*suggests* a status; nothing is written back to Gmail and no application's
status changes until a human clicks Confirm on the web app or runs
`resume-tailor apps set-status`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Paths

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Applications past these statuses have already resolved — no point scanning them.
ACTIVE_STATUSES = ("applied", "screening", "interview")


class GmailNotConfigured(Exception):
    pass


def _secret_path(paths: Paths) -> Path:
    return paths.profile_dir / "gmail_client_secret.json"


def _token_path(paths: Paths) -> Path:
    return paths.profile_dir / "gmail_token.json"


def is_connected(paths: Paths) -> bool:
    return _token_path(paths).exists()


def run_local_auth(paths: Paths) -> None:
    """One-time interactive OAuth consent flow — run this on a machine with a
    browser (not the headless server). Writes gmail_token.json next to the
    client secret; both live under profile/ so a redeploy never touches them."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise GmailNotConfigured(
            "Gmail OAuth libraries aren't installed — `pip install 'resume-tailor[gmail]'`."
        ) from e

    secret = _secret_path(paths)
    if not secret.exists():
        raise GmailNotConfigured(
            f"{secret} not found.\n"
            "One-time setup: in Google Cloud Console, enable the Gmail API, create an "
            "OAuth client of type 'Desktop app', download its JSON, and save it at that path."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0)
    token = _token_path(paths)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json())
    try:
        token.chmod(0o600)
    except OSError:
        pass


def _credentials(paths: Paths):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = _token_path(paths)
    if not token.exists():
        raise GmailNotConfigured(
            "Gmail isn't connected yet — run `resume-tailor gmail-auth` on a machine with a "
            "browser, then copy profile/gmail_token.json here."
        )
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json())
    return creds


# --------------------------------------------------------------------------- #
# Heuristic classifier — keyword matching only, no AI call. Anything that
# doesn't clearly match stays unclassified; a human decides.
# --------------------------------------------------------------------------- #
_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("offer", (
        "pleased to offer", "excited to offer", "job offer", "offer letter",
        "extend an offer", "formal offer", "offer of employment",
    )),
    ("interview", (
        "schedule an interview", "schedule a call", "phone screen", "would like to speak",
        "next steps", "meet with the team", "set up a time to chat", "book a time",
        "technical interview", "onsite interview", "video call", "would like to invite you",
    )),
    ("screening", (
        "online assessment", "coding challenge", "take-home", "technical assessment",
        "hackerrank", "codesignal", "complete this assessment",
    )),
    ("rejected", (
        "unfortunately", "not moving forward", "other candidates", "not selected",
        "decided not to proceed", "position has been filled", "pursuing other candidates",
        "will not be moving forward", "not be proceeding", "unable to move forward",
        "have chosen to move forward with other",
    )),
]
_NOISE = (
    "we have received your application", "thank you for applying", "thanks for applying",
    "application received", "confirm receipt", "confirming we received",
)


def classify(subject: str, snippet: str) -> str | None:
    text = f"{subject}\n{snippet}".lower()
    hit = next((status for status, kws in _PATTERNS if any(k in text for k in kws)), None)
    if hit:
        return hit
    if any(n in text for n in _NOISE):
        return None  # a plain auto-acknowledgement — no status movement
    return None


@dataclass
class Suggestion:
    app_id: str
    company: str
    role: str
    current_status: str
    message_id: str
    thread_id: str
    subject: str
    snippet: str
    date: str
    from_addr: str
    suggested_status: str | None
    link: str


def scan_for_application(paths: Paths, app: dict, *, max_results: int = 8) -> list[Suggestion]:
    """Search Gmail for replies plausibly about one tracked application —
    restricted to mail received after the application was submitted."""
    from googleapiclient.discovery import build

    company = (app.get("company") or "").strip()
    if not company:
        return []
    creds = _credentials(paths)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    since = datetime.fromtimestamp(app["created_at"]).strftime("%Y/%m/%d")
    query = f'"{company}" after:{since}'
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()

    out: list[Suggestion] = []
    for m in resp.get("messages", []):
        full = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "")
        snippet = full.get("snippet", "")
        thread_id = full.get("threadId", full["id"])
        out.append(Suggestion(
            app_id=app["id"], company=company, role=app.get("role") or "",
            current_status=app["status"],
            message_id=full["id"], thread_id=thread_id,
            subject=subject, snippet=snippet, date=headers.get("Date", ""),
            from_addr=headers.get("From", ""),
            suggested_status=classify(subject, snippet),
            link=f"https://mail.google.com/mail/u/0/#inbox/{thread_id}",
        ))
    return out


def scan_active_applications(
    paths: Paths, store, *, statuses: tuple[str, ...] = ACTIVE_STATUSES,
) -> tuple[list[Suggestion], list[str]]:
    """Scan Gmail for every tracked application still in an active status.
    Returns (suggestions, errors) — one application's failure doesn't stop the
    rest. Only suggestions whose classified status differs from the current
    one are returned (nothing to confirm otherwise)."""
    suggestions: list[Suggestion] = []
    errors: list[str] = []
    apps = [a for a in store.list_applications(limit=1000) if a["status"] in statuses]
    for app in apps:
        try:
            got = scan_for_application(paths, app)
        except GmailNotConfigured:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append(f"{app.get('company') or app['id']}: {type(e).__name__}: {e}")
            continue
        suggestions.extend(
            s for s in got if s.suggested_status and s.suggested_status != app["status"]
        )
    return suggestions, errors
