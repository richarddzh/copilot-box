from __future__ import annotations

from pathlib import Path

import pytest

from copilot_box.config import (
    AgentSettings,
    AppSettings,
    BrokerClientSettings,
    ReportSettings,
    SessionSettings,
    WorkDirSettings,
)
from copilot_box.sessions import SessionStore, WorkDirNotAllowedError


def make_settings(tmp_path: Path) -> AppSettings:
    root = tmp_path / "work"
    root.mkdir()
    repo = root / "repo"
    repo.mkdir()
    other = root / "other"
    other.mkdir()
    return AppSettings(
        broker=BrokerClientSettings(),
        sessions=SessionSettings(state_dir=tmp_path / "state", ttl_seconds=86400),
        workdirs=WorkDirSettings(allowed=(repo, other)),
        agent=AgentSettings(adapter="echo", base_directory=tmp_path / "copilot-home"),
        reports=ReportSettings(),
    )


def test_auto_reuses_latest_session_for_same_work_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed[0]
    store = SessionStore(settings)

    first, created_first = store.select_session(mode="auto", work_dir=work_dir)
    second, created_second = store.select_session(mode="auto", work_dir=work_dir)

    assert created_first is True
    assert created_second is False
    assert second.session_id == first.session_id


def test_continue_requires_existing_session_in_same_work_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed[0]
    other_dir = settings.workdirs.allowed[1]
    store = SessionStore(settings)
    record, _ = store.select_session(mode="new", work_dir=work_dir)

    with pytest.raises(ValueError, match="belongs to"):
        store.select_session(
            mode="continue", work_dir=other_dir, requested_session_id=record.session_id
        )


def test_rejects_work_dir_outside_whitelist(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = SessionStore(settings)

    with pytest.raises(WorkDirNotAllowedError):
        store.select_session(mode="auto", work_dir=tmp_path / "outside")
