from __future__ import annotations

import asyncio
from pathlib import Path

from copilot_box.agent import AgentService, EchoAgentAdapter, PromptRequest
from copilot_box.config import (
    AgentSettings,
    AppSettings,
    SessionSettings,
    StorageSettings,
    WorkDirSettings,
)


def make_settings(tmp_path: Path) -> AppSettings:
    root = tmp_path / "work"
    root.mkdir()
    return AppSettings(
        storage=StorageSettings(account_url="https://example.blob.core.windows.net"),
        sessions=SessionSettings(state_dir=tmp_path / "state", ttl_seconds=86400),
        workdirs=WorkDirSettings(allowed_roots=(root,)),
        agent=AgentSettings(adapter="echo", model=None, base_directory=tmp_path / "copilot-home"),
    )


def test_agent_service_creates_and_continues_session(tmp_path: Path) -> None:
    asyncio.run(_run_agent_service_creates_and_continues_session(tmp_path))


async def _run_agent_service_creates_and_continues_session(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed_roots[0] / "repo"
    work_dir.mkdir()
    service = AgentService(settings=settings, adapter=EchoAgentAdapter())

    first = await service.handle_prompt(PromptRequest(prompt="hello", work_dir=work_dir))
    second = await service.handle_prompt(PromptRequest(prompt="again", work_dir=work_dir))

    assert first.created_session is True
    assert second.created_session is False
    assert second.session_id == first.session_id
    assert "again" in second.output
