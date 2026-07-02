from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from copilot_box.agent import AgentService, EchoAgentAdapter
from copilot_box.blob_storage import RequestBlob
from copilot_box.config import (
    AgentSettings,
    AppSettings,
    SessionSettings,
    StorageSettings,
    WorkDirSettings,
)
from copilot_box.request_store import RequestStore
from copilot_box.requests import StorageRequestProcessor


@dataclass
class FakeClaimedBlob:
    name: str
    etag: str
    payload: str
    completed: bool = False
    abandoned: bool = False

    def read_text(self) -> str:
        return self.payload

    def complete(self) -> None:
        self.completed = True

    def abandon(self) -> None:
        self.abandoned = True


class FakeBlobStorage:
    def __init__(self) -> None:
        self.requests: dict[str, tuple[str, str]] = {}
        self.claims: list[FakeClaimedBlob] = []
        self.responses: dict[str, str] = {}
        self.dead_letters: dict[str, str] = {}

    def add_request(self, name: str, payload: dict | str, etag: str = "etag-1") -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.requests[name] = (text, etag)

    def list_requests(self, *, prefix: str, limit: int) -> list[RequestBlob]:
        blobs = [
            RequestBlob(name=name, etag=etag)
            for name, (_, etag) in sorted(self.requests.items())
            if name.startswith(prefix)
        ]
        return blobs[:limit]

    def try_claim_request(self, blob: RequestBlob) -> FakeClaimedBlob | None:
        payload, _ = self.requests[blob.name]
        claim = FakeClaimedBlob(name=blob.name, etag=blob.etag, payload=payload)
        self.claims.append(claim)
        return claim

    def write_response_json(self, blob_name: str, payload: str) -> None:
        self.responses[blob_name] = payload

    def write_dead_letter_json(self, blob_name: str, payload: str) -> None:
        self.dead_letters[blob_name] = payload


def make_settings(tmp_path: Path, *, adapter: str = "echo") -> AppSettings:
    root = tmp_path / "work"
    root.mkdir()
    return AppSettings(
        storage=StorageSettings(
            account_url="https://example.blob.core.windows.net",
            request_prefix="requests/",
            max_requests_per_poll=10,
        ),
        sessions=SessionSettings(state_dir=tmp_path / "state", ttl_seconds=86400),
        workdirs=WorkDirSettings(allowed_roots=(root,)),
        agent=AgentSettings(adapter=adapter, model=None, base_directory=tmp_path / "copilot-home"),
    )


def test_process_once_handles_request_and_writes_response(tmp_path: Path) -> None:
    asyncio.run(_process_once_handles_request_and_writes_response(tmp_path))


async def _process_once_handles_request_and_writes_response(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed_roots[0] / "repo"
    work_dir.mkdir()
    storage = FakeBlobStorage()
    storage.add_request(
        "requests/repo/001.json",
        {
            "protocolVersion": "2026-07-02",
            "requestId": "req-1",
            "workDir": str(work_dir),
            "session": {"mode": "auto"},
            "agent": {"prompt": "hello"},
            "response": {"prefix": "responses/req-1"},
        },
    )
    processor = StorageRequestProcessor(
        settings=settings,
        blob_storage=storage,
        agent_service=AgentService(settings=settings, adapter=EchoAgentAdapter()),
        request_store=RequestStore(settings.sessions.state_dir),
    )

    results = await processor.process_once()

    assert results[0].status == "succeeded"
    assert results[0].request_id == "req-1"
    assert storage.claims[0].completed is True
    final = json.loads(storage.responses["responses/req-1/999999.final.json"])
    assert final["status"] == "succeeded"
    assert final["requestId"] == "req-1"
    assert "hello" in final["output"]


def test_process_once_reuses_session_for_same_work_dir(tmp_path: Path) -> None:
    asyncio.run(_process_once_reuses_session_for_same_work_dir(tmp_path))


async def _process_once_reuses_session_for_same_work_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    work_dir = settings.workdirs.allowed_roots[0] / "repo"
    work_dir.mkdir()
    storage = FakeBlobStorage()
    for index, prompt in enumerate(["first", "second"], start=1):
        storage.add_request(
            f"requests/repo/{index:03d}.json",
            {
                "protocolVersion": "2026-07-02",
                "requestId": f"req-{index}",
                "workDir": str(work_dir),
                "session": {"mode": "auto"},
                "agent": {"prompt": prompt},
                "response": {"prefix": f"responses/req-{index}"},
            },
            etag=f"etag-{index}",
        )
    processor = StorageRequestProcessor(
        settings=settings,
        blob_storage=storage,
        agent_service=AgentService(settings=settings, adapter=EchoAgentAdapter()),
        request_store=RequestStore(settings.sessions.state_dir),
    )

    results = await processor.process_once()

    assert [result.status for result in results] == ["succeeded", "succeeded"]
    assert results[0].session_id == results[1].session_id
    assert results[0].session_id is not None


def test_process_once_dead_letters_disallowed_work_dir(tmp_path: Path) -> None:
    asyncio.run(_process_once_dead_letters_disallowed_work_dir(tmp_path))


async def _process_once_dead_letters_disallowed_work_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    storage = FakeBlobStorage()
    storage.add_request(
        "requests/bad/001.json",
        {
            "protocolVersion": "2026-07-02",
            "requestId": "bad-1",
            "workDir": str(tmp_path / "outside"),
            "session": {"mode": "auto"},
            "agent": {"prompt": "hello"},
            "response": {"prefix": "responses/bad-1"},
        },
    )
    processor = StorageRequestProcessor(
        settings=settings,
        blob_storage=storage,
        agent_service=AgentService(settings=settings, adapter=EchoAgentAdapter()),
        request_store=RequestStore(settings.sessions.state_dir),
    )

    results = await processor.process_once()

    assert results[0].status == "failed"
    assert storage.claims[0].abandoned is True
    assert "bad-1.json" in storage.dead_letters
    final = json.loads(storage.responses["responses/bad-1/999999.final.json"])
    assert final["status"] == "failed_terminal"


def test_process_once_dead_letters_invalid_json(tmp_path: Path) -> None:
    asyncio.run(_process_once_dead_letters_invalid_json(tmp_path))


async def _process_once_dead_letters_invalid_json(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    storage = FakeBlobStorage()
    storage.add_request("requests/bad-json/001.json", "{not-json")
    processor = StorageRequestProcessor(
        settings=settings,
        blob_storage=storage,
        agent_service=AgentService(settings=settings, adapter=EchoAgentAdapter()),
        request_store=RequestStore(settings.sessions.state_dir),
    )

    results = await processor.process_once()

    assert results[0].status == "failed"
    assert storage.claims[0].abandoned is True
    dead_letter = json.loads(storage.dead_letters["requests-bad-json-001.json.json"])
    assert dead_letter["failure"]["type"] == "invalid_request"
