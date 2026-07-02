from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from copilot_box.agent import AgentService, PromptRequest
from copilot_box.config import AppSettings

PROTOCOL_VERSION = "2026-07-02"


async def run_worker(*, settings: AppSettings, max_requests: int | None = None) -> None:
    if not settings.broker.url:
        raise ValueError("broker.url is required for service run")
    if not settings.broker.worker_id:
        raise ValueError("broker.worker_id is required for service run")
    if settings.broker.auth_mode == "shared_secret" and not settings.broker.worker_token:
        raise ValueError("broker.worker_token is required for service run")
    if settings.broker.auth_mode == "entra_id" and not settings.broker.entra_scope:
        raise ValueError("broker.entra_scope is required for Entra ID broker auth")

    processed = 0
    while max_requests is None or processed < max_requests:
        try:
            async with _connect(settings) as websocket:
                processed += await _serve_connection(
                    settings=settings,
                    websocket=websocket,
                    max_requests=None if max_requests is None else max_requests - processed,
                )
        except Exception as exc:
            if max_requests is not None:
                raise
            print(f"worker connection failed: {exc}")
            await asyncio.sleep(settings.broker.reconnect_seconds)


async def _serve_connection(
    *,
    settings: AppSettings,
    websocket: WebSocketClientProtocol,
    max_requests: int | None,
) -> int:
    await websocket.send(
        json.dumps(
            _message(
                "worker.hello",
                root={
                    "workerId": settings.broker.worker_id,
                    "displayName": settings.broker.display_name or settings.broker.worker_id,
                    "allowedWorkDirs": [str(path) for path in settings.workdirs.allowed],
                    "reportWorkspace": {
                        "enabled": settings.reports.enabled,
                        "root": (
                            str(settings.reports.root_dir)
                            if settings.reports.root_dir
                            else None
                        ),
                    },
                    "capabilities": {
                        "models": [],
                        "streaming": True,
                        "markdown": True,
                        "maxConcurrentRequests": 1,
                        "singleActiveSession": True,
                        "reportRead": settings.reports.enabled,
                    },
                },
            ),
            ensure_ascii=False,
        )
    )
    processed = 0
    service = AgentService(settings=settings)
    request_lock = asyncio.Lock()

    async for raw in websocket:
        message = json.loads(raw)
        if message.get("type") == "report.read":
            await _handle_report_read(settings, websocket, message)
            continue
        if message.get("type") != "agent.request":
            continue
        if request_lock.locked():
            await websocket.send(
                json.dumps(
                    _error(message.get("requestId"), "worker_busy", "Worker is busy."),
                    ensure_ascii=False,
                )
            )
            continue
        async with request_lock:
            await _handle_request(settings, service, websocket, message)
            processed += 1
            if max_requests is not None and processed >= max_requests:
                return processed
    return processed


def _connect(settings: AppSettings):
    headers = _auth_headers(settings)
    kwargs: dict[str, Any] = {
        "ping_interval": settings.broker.heartbeat_seconds,
    }
    header_argument = (
        "additional_headers"
        if "additional_headers" in inspect.signature(websockets.connect).parameters
        else "extra_headers"
    )
    kwargs[header_argument] = headers
    return websockets.connect(settings.broker.url, **kwargs)


def _auth_headers(settings: AppSettings) -> dict[str, str]:
    if settings.broker.auth_mode == "shared_secret":
        return {"X-Copilot-Box-Worker-Token": settings.broker.worker_token}
    if settings.broker.auth_mode == "entra_id":
        return {"Authorization": f"Bearer {_entra_access_token(settings)}"}
    raise ValueError(f"unsupported broker auth mode: {settings.broker.auth_mode}")


def _entra_access_token(settings: AppSettings) -> str:
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    if settings.broker.entra_client_id and settings.broker.entra_client_secret:
        if not settings.broker.entra_tenant_id:
            raise ValueError("broker.entra_tenant_id is required for client secret auth")
        credential = ClientSecretCredential(
            tenant_id=settings.broker.entra_tenant_id,
            client_id=settings.broker.entra_client_id,
            client_secret=settings.broker.entra_client_secret,
        )
    else:
        managed_identity_client_id = settings.broker.entra_client_id or None
        credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)
    try:
        return credential.get_token(settings.broker.entra_scope).token
    finally:
        credential.close()


async def _handle_request(
    settings: AppSettings,
    service: AgentService,
    websocket: WebSocketClientProtocol,
    message: dict[str, Any],
) -> None:
    request_id = str(message.get("requestId") or "")
    event_queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
    sender_task = asyncio.create_task(_send_stream_events(websocket, request_id, event_queue))
    try:
        payload = message.get("payload") or {}
        session = payload.get("session") or {}
        agent = payload.get("agent") or {}
        result = await service.handle_prompt(
            PromptRequest(
                prompt=str(agent.get("prompt") or ""),
                work_dir=Path(str(payload.get("workDir") or "")),
                session_mode=session.get("mode") or "auto",
                session_id=session.get("sessionId"),
                timeout_seconds=agent.get("timeoutSeconds"),
                model=agent.get("model"),
            ),
            on_delta=lambda text: event_queue.put_nowait(("delta", text)),
            on_started=lambda session_record, created: event_queue.put_nowait(
                (
                    "session.started",
                    {
                        "sessionId": session_record.session_id,
                        "createdSession": created,
                        "workDir": str(session_record.work_dir),
                        "status": "running",
                    },
                )
            ),
        )
        await event_queue.put(None)
        await sender_task
        await websocket.send(
            json.dumps(
                _message(
                    "agent.final",
                    request_id=request_id,
                    payload={
                        "status": "succeeded",
                        "sessionId": result.session_id,
                        "createdSession": result.created_session,
                        "workDir": str(result.work_dir),
                        "output": result.output,
                        "contentType": "text/markdown",
                        "reportPath": None,
                    },
                ),
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        await event_queue.put(None)
        await sender_task
        await websocket.send(
            json.dumps(
                _error(request_id, "agent_failed", str(exc), retryable=False),
                ensure_ascii=False,
            )
        )


async def _handle_report_read(
    settings: AppSettings,
    websocket: WebSocketClientProtocol,
    message: dict[str, Any],
) -> None:
    request_id = str(message.get("requestId") or "")
    try:
        if not settings.reports.enabled or settings.reports.root_dir is None:
            raise ValueError("report workspace is not enabled")
        payload = message.get("payload") or {}
        relative_path = str(payload.get("path") or "").strip()
        report_path = _resolve_report_path(settings.reports.root_dir, relative_path)
        size = report_path.stat().st_size
        if size > settings.reports.max_file_bytes:
            raise ValueError(
                f"report is too large: {size} bytes; max: {settings.reports.max_file_bytes}"
            )
        content = report_path.read_text(encoding="utf-8")
        await websocket.send(
            json.dumps(
                _message(
                    "report.content",
                    request_id=request_id,
                    payload={
                        "path": relative_path,
                        "contentType": _content_type(report_path),
                        "content": content,
                    },
                ),
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        await websocket.send(
            json.dumps(
                _error(request_id, "report_read_failed", str(exc), retryable=False),
                ensure_ascii=False,
            )
        )


def _resolve_report_path(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise ValueError("report path must be a safe relative path")
    resolved_root = root.resolve(strict=False)
    resolved_path = (resolved_root / relative_path).resolve(strict=False)
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError("report path escapes report workspace")
    if not resolved_path.is_file():
        raise ValueError(f"report was not found: {relative_path}")
    return resolved_path


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix in {".html", ".htm"}:
        return "text/html"
    return "text/plain"


async def _send_stream_events(
    websocket: WebSocketClientProtocol,
    request_id: str,
    event_queue: asyncio.Queue[tuple[str, Any] | None],
) -> None:
    sequence = 1
    while True:
        event = await event_queue.get()
        if event is None:
            return
        event_type, payload = event
        if event_type == "session.started":
            await websocket.send(
                json.dumps(
                    _message("session.started", request_id=request_id, payload=payload),
                    ensure_ascii=False,
                )
            )
            continue
        await websocket.send(
            json.dumps(
                _message(
                    "agent.delta",
                    request_id=request_id,
                    payload={
                        "role": "assistant",
                        "sequence": sequence,
                        "text": payload,
                        "contentType": "text/markdown",
                    },
                ),
                ensure_ascii=False,
            )
        )
        sequence += 1


def _message(
    message_type: str,
    *,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
    root: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": message_type,
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": f"msg-{uuid.uuid4().hex}",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if request_id:
        message["requestId"] = request_id
    if payload is not None:
        message["payload"] = payload
    if root:
        message.update(root)
    return message


def _error(
    request_id: str | None,
    code: str,
    message: str,
    *,
    retryable: bool = True,
) -> dict[str, Any]:
    return _message(
        "error",
        request_id=request_id,
        payload={"code": code, "message": message, "retryable": retryable},
    )
