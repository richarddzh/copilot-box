from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from copilot_box.agent import AgentService, PromptRequest
from copilot_box.blob_storage import BlobStorage
from copilot_box.config import AppSettings
from copilot_box.request_store import RequestStore
from copilot_box.sessions import SessionMode


class ClientInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    user_id: str | None = Field(default=None, alias="userId")


class SessionInfo(BaseModel):
    mode: SessionMode = "auto"
    session_id: str | None = Field(default=None, alias="sessionId")


class AgentInfo(BaseModel):
    prompt: str
    model: str | None = None
    timeout_seconds: float | None = Field(default=None, alias="timeoutSeconds")


class ResponseInfo(BaseModel):
    container: str | None = None
    prefix: str | None = None


class StorageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    protocol_version: str = Field(alias="protocolVersion")
    request_id: str = Field(alias="requestId")
    created_at: str | None = Field(default=None, alias="createdAt")
    client: ClientInfo | None = None
    work_dir: Path = Field(alias="workDir")
    session: SessionInfo = Field(default_factory=SessionInfo)
    agent: AgentInfo
    response: ResponseInfo | None = None


@dataclass(frozen=True)
class ProcessedRequest:
    request_id: str
    status: Literal["succeeded", "failed", "skipped"]
    response_prefix: str | None = None
    session_id: str | None = None
    error: str | None = None


class StorageRequestProcessor:
    def __init__(
        self,
        *,
        settings: AppSettings,
        blob_storage: BlobStorage,
        agent_service: AgentService | None = None,
        request_store: RequestStore | None = None,
    ) -> None:
        self._settings = settings
        self._blob_storage = blob_storage
        self._agent_service = agent_service or AgentService(settings=settings)
        self._request_store = request_store or RequestStore(settings.sessions.state_dir)

    async def process_once(self) -> list[ProcessedRequest]:
        processed: list[ProcessedRequest] = []
        blobs = self._blob_storage.list_requests(
            prefix=self._settings.storage.request_prefix,
            limit=self._settings.storage.max_requests_per_poll,
        )
        for blob in blobs:
            if self._request_store.is_terminal(blob.name, blob.etag):
                processed.append(
                    ProcessedRequest(request_id=blob.name, status="skipped")
                )
                continue

            claim = self._blob_storage.try_claim_request(blob)
            if claim is None:
                continue

            self._request_store.mark(blob.name, blob.etag, "processing")
            try:
                processed.append(await self._process_claim(claim))
                self._request_store.mark(blob.name, blob.etag, "completed")
                claim.complete()
            except Exception as exc:
                self._request_store.mark(blob.name, blob.etag, "failed")
                try:
                    claim.abandon()
                finally:
                    processed.append(
                        ProcessedRequest(
                            request_id=blob.name,
                            status="failed",
                            error=str(exc),
                        )
                    )
        return processed

    async def _process_claim(self, claim) -> ProcessedRequest:
        raw_request = claim.read_text()
        try:
            request = StorageRequest.model_validate_json(raw_request)
        except Exception as exc:
            self._write_raw_dead_letter(
                source_blob_name=claim.name,
                raw_request=raw_request,
                error_message=str(exc),
            )
            raise

        prefix = _response_prefix(request, claim.name)
        self._write_event(
            prefix,
            1,
            {
                "type": "accepted",
                "requestId": request.request_id,
                "createdAt": _now(),
            },
        )
        self._write_event(
            prefix,
            2,
            {
                "type": "running",
                "requestId": request.request_id,
                "createdAt": _now(),
            },
        )

        try:
            result = await self._agent_service.handle_prompt(
                PromptRequest(
                    prompt=request.agent.prompt,
                    work_dir=request.work_dir,
                    session_mode=request.session.mode,
                    session_id=request.session.session_id,
                    timeout_seconds=request.agent.timeout_seconds,
                    model=request.agent.model,
                )
            )
        except Exception as exc:
            payload = {
                "type": "final",
                "status": "failed_terminal",
                "requestId": request.request_id,
                "createdAt": _now(),
                "error": {
                    "message": str(exc),
                    "retryable": False,
                },
            }
            self._write_event(prefix, 999999, payload)
            self._write_dead_letter(request, claim.name, payload)
            raise

        self._write_event(
            prefix,
            999999,
            {
                "type": "final",
                "status": "succeeded",
                "requestId": request.request_id,
                "sessionId": result.session_id,
                "createdSession": result.created_session,
                "workDir": str(result.work_dir),
                "output": result.output,
                "completedAt": _now(),
            },
        )
        return ProcessedRequest(
            request_id=request.request_id,
            status="succeeded",
            response_prefix=prefix,
            session_id=result.session_id,
        )

    def _write_event(self, prefix: str, sequence: int, payload: dict[str, Any]) -> None:
        blob_name = f"{prefix}/{sequence:06d}.{payload['type']}.json"
        self._blob_storage.write_response_json(
            blob_name,
            json.dumps(
                {"protocolVersion": "2026-07-02", "sequence": sequence, **payload},
                ensure_ascii=False,
                indent=2,
            ),
        )

    def _write_dead_letter(
        self,
        request: StorageRequest,
        source_blob_name: str,
        failure_payload: dict[str, Any],
    ) -> None:
        dead_letter_name = f"{_safe_name(request.request_id or source_blob_name)}.json"
        self._blob_storage.write_dead_letter_json(
            dead_letter_name,
            json.dumps(
                {
                    "sourceBlob": source_blob_name,
                    "request": request.model_dump(mode="json", by_alias=True),
                    "failure": failure_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    def _write_raw_dead_letter(
        self,
        *,
        source_blob_name: str,
        raw_request: str,
        error_message: str,
    ) -> None:
        dead_letter_name = f"{_safe_name(source_blob_name)}.json"
        self._blob_storage.write_dead_letter_json(
            dead_letter_name,
            json.dumps(
                {
                    "sourceBlob": source_blob_name,
                    "rawRequest": raw_request,
                    "failure": {
                        "type": "invalid_request",
                        "message": error_message,
                        "retryable": False,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


def _response_prefix(request: StorageRequest, source_blob_name: str) -> str:
    if request.response and request.response.prefix:
        return request.response.prefix.strip("/")
    return source_blob_name.removesuffix(".json")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)


def _now() -> str:
    return datetime.now(UTC).isoformat()
