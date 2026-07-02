from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class RequestRecord:
    blob_name: str
    etag: str
    status: str


class RequestStore:
    def __init__(self, state_dir: Path) -> None:
        self._db_path = state_dir / "requests.sqlite3"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def is_terminal(self, blob_name: str, etag: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status
                FROM requests
                WHERE blob_name = ? AND etag = ?
                """,
                (blob_name, etag),
            ).fetchone()
        return row is not None and row[0] in {"completed", "failed"}

    def mark(self, blob_name: str, etag: str, status: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO requests(blob_name, etag, status, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(blob_name, etag)
                DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
                """,
                (blob_name, etag, status, now),
            )

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    blob_name TEXT NOT NULL,
                    etag TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(blob_name, etag)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)
