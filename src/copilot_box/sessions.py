from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from copilot_box.config import AppSettings

SessionMode = Literal["auto", "new", "continue"]


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    work_dir: Path
    created_at: datetime
    last_active_at: datetime
    status: str


class WorkDirNotAllowedError(ValueError):
    pass


class SessionStore:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._db_path = settings.sessions.state_dir / "sessions.sqlite3"
        self._settings.sessions.state_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def resolve_work_dir(self, work_dir: Path) -> Path:
        resolved = work_dir.expanduser().resolve(strict=False)
        if not any(_same_path(resolved, allowed) for allowed in self._settings.workdirs.allowed):
            allowed = ", ".join(str(path) for path in self._settings.workdirs.allowed)
            raise WorkDirNotAllowedError(
                f"work dir is not in the configured whitelist: {resolved}; allowed: {allowed}"
            )
        return resolved

    def select_session(
        self,
        *,
        mode: SessionMode,
        work_dir: Path,
        requested_session_id: str | None = None,
    ) -> tuple[SessionRecord, bool]:
        resolved = self.resolve_work_dir(work_dir)

        if mode == "new":
            return self.create_session(resolved, requested_session_id), True

        if mode == "continue":
            if not requested_session_id:
                raise ValueError("session_id is required when session mode is 'continue'")
            record = self.get_session(requested_session_id)
            if record is None:
                raise ValueError(f"session was not found: {requested_session_id}")
            if _normalize_path(record.work_dir) != _normalize_path(resolved):
                raise ValueError(
                    f"session {requested_session_id} belongs to {record.work_dir}, "
                    f"not {resolved}"
                )
            self.touch(record.session_id)
            return record, False

        if requested_session_id:
            record = self.get_session(requested_session_id)
            if record is not None:
                if _normalize_path(record.work_dir) != _normalize_path(resolved):
                    raise ValueError(
                        f"session {requested_session_id} belongs to {record.work_dir}, "
                        f"not {resolved}"
                    )
                self.touch(record.session_id)
                return record, False
            return self.create_session(resolved, requested_session_id), True

        record = self.find_latest_active_session(resolved)
        if record is not None:
            self.touch(record.session_id)
            return record, False

        return self.create_session(resolved), True

    def create_session(self, work_dir: Path, session_id: str | None = None) -> SessionRecord:
        now = _utc_now()
        record = SessionRecord(
            session_id=session_id or f"sess_{uuid.uuid4().hex}",
            work_dir=work_dir,
            created_at=now,
            last_active_at=now,
            status="active",
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id, work_dir, created_at, last_active_at, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    str(record.work_dir),
                    _format_dt(record.created_at),
                    _format_dt(record.last_active_at),
                    record.status,
                ),
            )
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, work_dir, created_at, last_active_at, status
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def find_latest_active_session(self, work_dir: Path) -> SessionRecord | None:
        cutoff = _utc_now() - timedelta(seconds=self._settings.sessions.ttl_seconds)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, work_dir, created_at, last_active_at, status
                FROM sessions
                WHERE status = 'active' AND last_active_at >= ?
                ORDER BY last_active_at DESC
                """,
                (_format_dt(cutoff),),
            ).fetchall()

        normalized = _normalize_path(work_dir)
        for row in rows:
            record = _record_from_row(row)
            if _normalize_path(record.work_dir) == normalized:
                return record
        return None

    def touch(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET last_active_at = ?, status = 'active'
                WHERE session_id = ?
                """,
                (_format_dt(_utc_now()), session_id),
            )

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    work_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_workdir_active
                ON sessions(work_dir, status, last_active_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)


def _record_from_row(row: tuple[str, str, str, str, str]) -> SessionRecord:
    return SessionRecord(
        session_id=row[0],
        work_dir=Path(row[1]),
        created_at=_parse_dt(row[2]),
        last_active_at=_parse_dt(row[3]),
        status=row[4],
    )


def _same_path(left: Path, right: Path) -> bool:
    return _normalize_path(left) == _normalize_path(right)


def _normalize_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_dt(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
