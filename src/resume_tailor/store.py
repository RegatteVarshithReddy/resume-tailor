"""SQLite store for applications and background jobs.

Single-user, low-volume; stdlib sqlite3 with WAL is plenty.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

STATUSES = ["draft", "applied", "screening", "interview", "offer", "rejected", "archived"]
JOB_STATES = ["queued", "running", "done", "error"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id            TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    profile       TEXT NOT NULL,
    company       TEXT,
    role          TEXT,
    mode          TEXT,                 -- aggressive | conservative
    status        TEXT NOT NULL DEFAULT 'draft',
    out_dir       TEXT NOT NULL,
    gap_matched   INTEGER DEFAULT 0,
    gap_partial   INTEGER DEFAULT 0,
    gap_missing   INTEGER DEFAULT 0,
    years_required REAL,
    years_available REAL,
    pdf_engine    TEXT,
    warnings      INTEGER DEFAULT 0,
    notes         TEXT DEFAULT '',
    missing_json  TEXT DEFAULT '[]',
    match_score   REAL,
    variant_chosen TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    state       TEXT NOT NULL DEFAULT 'queued',
    kind        TEXT NOT NULL,          -- tailor | rerender
    params_json TEXT NOT NULL,
    app_id      TEXT,
    log         TEXT DEFAULT '',
    error       TEXT DEFAULT ''
);
"""


def now() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    return (prefix + uuid.uuid4().hex[:10])


@dataclass
class Store:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            # additive migrations for DBs created before a column existed
            for col, decl in (("match_score", "REAL"), ("variant_chosen", "TEXT DEFAULT ''")):
                try:
                    c.execute(f"ALTER TABLE applications ADD COLUMN {col} {decl}")
                except sqlite3.OperationalError:
                    pass  # duplicate column name — already migrated

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- applications --------------------------------------------------
    def create_application(self, **fields: Any) -> str:
        aid = fields.pop("id", None) or new_id("app_")
        ts = now()
        row = {
            "id": aid, "created_at": ts, "updated_at": ts,
            "profile": fields.get("profile", "default"),
            "company": fields.get("company"), "role": fields.get("role"),
            "mode": fields.get("mode"), "status": fields.get("status", "draft"),
            "out_dir": fields["out_dir"],
            "gap_matched": fields.get("gap_matched", 0),
            "gap_partial": fields.get("gap_partial", 0),
            "gap_missing": fields.get("gap_missing", 0),
            "years_required": fields.get("years_required"),
            "years_available": fields.get("years_available"),
            "pdf_engine": fields.get("pdf_engine"),
            "warnings": fields.get("warnings", 0),
            "notes": fields.get("notes", ""),
            "missing_json": json.dumps(fields.get("missing", [])),
            "match_score": fields.get("match_score"),
            "variant_chosen": fields.get("variant_chosen", ""),
        }
        cols = ", ".join(row)
        ph = ", ".join(f":{k}" for k in row)
        with self._conn() as c:
            c.execute(f"INSERT INTO applications ({cols}) VALUES ({ph})", row)
        return aid

    def update_application(self, aid: str, **fields: Any) -> None:
        if "missing" in fields:
            fields["missing_json"] = json.dumps(fields.pop("missing"))
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = aid
        with self._conn() as c:
            c.execute(f"UPDATE applications SET {sets} WHERE id = :id", fields)

    def get_application(self, aid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
        return dict(r) if r else None

    def list_applications(
        self, status: str | None = None, profile: str | None = None, limit: int = 200
    ) -> list[dict]:
        q = "SELECT * FROM applications"
        where, args = [], []
        if status:
            where.append("status = ?")
            args.append(status)
        if profile:
            where.append("profile = ?")
            args.append(profile)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def delete_application(self, aid: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM applications WHERE id = ?", (aid,))

    def counts_by_status(self, profile: str | None = None) -> dict[str, int]:
        q = "SELECT status, COUNT(*) n FROM applications"
        args: list[Any] = []
        if profile:
            q += " WHERE profile = ?"
            args.append(profile)
        q += " GROUP BY status"
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # -- jobs --------------------------------------------------------
    def create_job(self, kind: str, params: dict) -> str:
        jid = new_id("job_")
        ts = now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs (id, created_at, updated_at, state, kind, params_json) "
                "VALUES (?,?,?,?,?,?)",
                (jid, ts, ts, "queued", kind, json.dumps(params)),
            )
        return jid

    def update_job(self, jid: str, **fields: Any) -> None:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = jid
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {sets} WHERE id = :id", fields)

    def append_job_log(self, jid: str, line: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET log = log || ?, updated_at = ? WHERE id = ?",
                (line.rstrip("\n") + "\n", now(), jid),
            )

    def get_job(self, jid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        return dict(r) if r else None

    def recent_jobs(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            ]
