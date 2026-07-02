from __future__ import annotations

from pathlib import Path

import pytest

from copilot_box.config import AgentSettings, AppSettings, SessionSettings, WorkDirSettings
from copilot_box.sessions import SessionStore, WorkDirNotAllowedError


def make_settings(tmp_path: Path) -> AppSettings:
    root = tmp_path / "work"
    root.mkdir()
    return AppSettings(
        sessions=SessionSettings(state_dir=tmp_path / "state", ttl_seconds=86400),
        workdirs=WorkDirSettings(allowed_roots=(root,)),
        agent=AgentSettings(adapter="echo", base_directory=tmp_path / "copilot-home"),
    )


def test_auto_reuses_latest_session_for_same_work_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed_roots[0] / "repo"
    work_dir.mkdir()
    store = SessionStore(settings)

    first, created_first = store.select_session(mode="auto", work_dir=work_dir)
    second, created_second = store.select_session(mode="auto", work_dir=work_dir)

    assert created_first is True
    assert created_second is False
    assert second.session_id == first.session_id


def test_continue_requires_existing_session_in_same_work_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed_roots[0] / "repo"
    other_dir = settings.workdirs.allowed_roots[0] / "other"
    work_dir.mkdir()
    other_dir.mkdir()
    store = SessionStore(settings)
    record, _ = store.select_session(mode="new", work_dir=work_dir)

    with pytest.raises(ValueError, match="belongs to"):
        store.select_session(
            mode="continue", work_dir=other_dir, requested_session_id=record.session_id
        )


def test_rejects_work_dir_outside_allowed_roots(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = SessionStore(settings)

    with pytest.raises(WorkDirNotAllowedError):
        store.select_session(mode="auto", work_dir=tmp_path / "outside")
