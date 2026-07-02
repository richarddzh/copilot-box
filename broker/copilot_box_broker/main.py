from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from anyio import BrokenResourceError, ClosedResourceError
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from copilot_box_broker.config import BrokerSettings

PROTOCOL_VERSION = "2026-07-02"


@dataclass
class WorkerConnection:
    websocket: WebSocket
    worker_id: str
    display_name: str
    allowed_work_dirs: tuple[str, ...]
    report_workspace: dict[str, Any]
    busy: bool = False


@dataclass
class RequestRoute:
    client_connection_id: str
    client_websocket: WebSocket
    worker_id: str


@dataclass
class ActiveSession:
    request_id: str
    worker_id: str
    work_dir: str
    prompt: str
    status: str
    created_at: str
    updated_at: str
    subscribers: dict[str, WebSocket] = field(default_factory=dict)
    session_id: str | None = None
    created_session: bool | None = None
    output_so_far: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "workerId": self.worker_id,
            "workDir": self.work_dir,
            "sessionId": self.session_id,
            "status": self.status,
            "prompt": self.prompt,
            "outputPreview": self.output_so_far[-500:],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "activeSession": self.summary(),
            "outputSoFar": self.output_so_far,
            "events": self.events,
        }


@dataclass
class BrokerState:
    workers: dict[str, WorkerConnection] = field(default_factory=dict)
    clients: dict[str, WebSocket] = field(default_factory=dict)
    requests: dict[str, RequestRoute] = field(default_factory=dict)
    active_sessions: dict[str, ActiveSession] = field(default_factory=dict)

    def worker_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "workerId": worker.worker_id,
                "displayName": worker.display_name,
                "allowedWorkDirs": list(worker.allowed_work_dirs),
                "reportWorkspace": worker.report_workspace,
                "busy": worker.busy,
            }
            for worker in self.workers.values()
        ]

    def active_session_summaries(self) -> list[dict[str, Any]]:
        return [
            session.summary()
            for session in self.active_sessions.values()
            if session.status == "running"
        ]


def create_app(settings: BrokerSettings | None = None) -> FastAPI:
    resolved_settings = settings or BrokerSettings.from_env()
    app = FastAPI(title="Copilot Box Broker", version="0.1.0")
    state = BrokerState()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws/worker")
    async def worker_ws(websocket: WebSocket) -> None:
        if websocket.headers.get("x-copilot-box-worker-token") != resolved_settings.worker_token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        worker_id: str | None = None
        try:
            hello = await websocket.receive_json()
            if hello.get("type") != "worker.hello":
                await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
                return
            worker_id = str(hello.get("workerId") or "").strip()
            if not worker_id:
                await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
                return
            allowed_work_dirs = tuple(str(item) for item in hello.get("allowedWorkDirs", []))
            state.workers[worker_id] = WorkerConnection(
                websocket=websocket,
                worker_id=worker_id,
                display_name=str(hello.get("displayName") or worker_id),
                allowed_work_dirs=allowed_work_dirs,
                report_workspace=hello.get("reportWorkspace") or {"enabled": False},
            )
            await websocket.send_json(
                _message(
                    "broker.worker.accepted",
                    payload={"workerId": worker_id},
                )
            )
            while True:
                message = await websocket.receive_json()
                await _route_worker_message(state, message)
        except WebSocketDisconnect:
            pass
        finally:
            if worker_id is not None:
                await _remove_worker(state, worker_id)

    @app.websocket("/ws/client")
    async def client_ws(websocket: WebSocket) -> None:
        if websocket.headers.get("x-copilot-box-token") != resolved_settings.client_token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        connection_id = f"client-{uuid.uuid4().hex}"
        state.clients[connection_id] = websocket
        try:
            hello = await websocket.receive_json()
            if hello.get("type") != "client.hello":
                await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
                return
            await websocket.send_json(
                _message(
                    "broker.hello",
                    payload={
                        "connectionId": connection_id,
                        "availableWorkers": state.worker_summaries(),
                        "activeSessions": state.active_session_summaries(),
                    },
                )
            )
            while True:
                message = await websocket.receive_json()
                await _route_client_message(state, connection_id, websocket, message)
        except WebSocketDisconnect:
            pass
        finally:
            state.clients.pop(connection_id, None)
            for active in state.active_sessions.values():
                active.subscribers.pop(connection_id, None)

    return app


async def _route_client_message(
    state: BrokerState,
    connection_id: str,
    websocket: WebSocket,
    message: dict[str, Any],
) -> None:
    message_type = message.get("type")
    if message_type not in {"agent.request", "report.read", "session.join"}:
        await websocket.send_json(
            _error(
                message.get("requestId"),
                "unsupported_message",
                f"Unsupported message type: {message_type}",
                retryable=False,
            )
        )
        return

    request_id = str(message.get("requestId") or "").strip()
    payload = message.get("payload") or {}
    if message_type == "session.join":
        await _join_session(state, connection_id, websocket, request_id, payload)
        return

    worker_id = str(payload.get("workerId") or "").strip()
    worker = state.workers.get(worker_id)
    if not worker:
        await websocket.send_json(
            _error(request_id, "worker_not_available", "Requested worker is not connected.")
        )
        return
    if message_type == "agent.request" and worker.busy:
        await websocket.send_json(_error(request_id, "worker_busy", "Worker is busy."))
        return
    if (
        message_type == "agent.request"
        and str(payload.get("workDir") or "").strip() not in worker.allowed_work_dirs
    ):
        await websocket.send_json(
            _error(request_id, "workdir_not_allowed", "Work dir is not in worker whitelist.")
        )
        return

    if message_type == "agent.request":
        worker.busy = True
        active = ActiveSession(
            request_id=request_id,
            worker_id=worker_id,
            work_dir=str(payload.get("workDir") or "").strip(),
            prompt=str((payload.get("agent") or {}).get("prompt") or ""),
            status="running",
            created_at=_utc_now(),
            updated_at=_utc_now(),
            subscribers={connection_id: websocket},
        )
        state.active_sessions[request_id] = active
    state.requests[request_id] = RequestRoute(
        client_connection_id=connection_id,
        client_websocket=websocket,
        worker_id=worker_id,
    )
    if message_type == "agent.request":
        await websocket.send_json(
            _message("broker.accepted", request_id=request_id, payload={"workerId": worker_id})
        )
    await worker.websocket.send_json(message)


async def _route_worker_message(state: BrokerState, message: dict[str, Any]) -> None:
    request_id = str(message.get("requestId") or "").strip()
    route = state.requests.get(request_id)
    if route is None:
        return
    active = state.active_sessions.get(request_id)
    if active is not None:
        _record_worker_event(active, message)
    try:
        if active is not None:
            await _broadcast(active, message)
        else:
            await route.client_websocket.send_json(message)
    finally:
        if message.get("type") in {"agent.final", "report.content", "error"}:
            worker = state.workers.get(route.worker_id)
            if worker is not None and message.get("type") != "report.content":
                worker.busy = False
            state.requests.pop(request_id, None)
            if message.get("type") != "report.content":
                state.active_sessions.pop(request_id, None)


async def _remove_worker(state: BrokerState, worker_id: str) -> None:
    state.workers.pop(worker_id, None)
    failed_request_ids = [
        request_id
        for request_id, route in state.requests.items()
        if route.worker_id == worker_id
    ]
    for request_id in failed_request_ids:
        route = state.requests.pop(request_id)
        message = _error(
            request_id,
            "worker_disconnected",
            "Worker disconnected while processing request.",
        )
        active = state.active_sessions.pop(request_id, None)
        if active is not None:
            await _broadcast(active, message)
            continue
        try:
            await route.client_websocket.send_json(message)
        except (BrokenResourceError, ClosedResourceError, RuntimeError) as exc:
            print(f"client disconnected before worker error delivery: {exc}")


async def _join_session(
    state: BrokerState,
    connection_id: str,
    websocket: WebSocket,
    join_request_id: str,
    payload: dict[str, Any],
) -> None:
    active_request_id = str(
        payload.get("requestId") or payload.get("activeRequestId") or ""
    ).strip()
    worker_id = str(payload.get("workerId") or "").strip()
    active = state.active_sessions.get(active_request_id)
    if active is None or active.status != "running":
        await websocket.send_json(
            _error(join_request_id, "active_session_not_found", "Active session was not found.")
        )
        return
    if worker_id and active.worker_id != worker_id:
        await websocket.send_json(
            _error(join_request_id, "worker_mismatch", "Active session belongs to another worker.")
        )
        return
    active.subscribers[connection_id] = websocket
    await websocket.send_json(
        _message("session.snapshot", request_id=active.request_id, payload=active.snapshot())
    )


async def _broadcast(active: ActiveSession, message: dict[str, Any]) -> None:
    stale: list[str] = []
    for connection_id, websocket in active.subscribers.items():
        try:
            await websocket.send_json(message)
        except (BrokenResourceError, ClosedResourceError, RuntimeError):
            stale.append(connection_id)
    for connection_id in stale:
        active.subscribers.pop(connection_id, None)


def _record_worker_event(active: ActiveSession, message: dict[str, Any]) -> None:
    message_type = message.get("type")
    payload = message.get("payload") or {}
    active.updated_at = _utc_now()
    if message_type == "session.started":
        active.session_id = payload.get("sessionId")
        active.created_session = payload.get("createdSession")
        active.work_dir = str(payload.get("workDir") or active.work_dir)
        active.status = str(payload.get("status") or "running")
    elif message_type == "agent.delta":
        active.output_so_far += str(payload.get("text") or "")
    elif message_type == "agent.final":
        active.session_id = payload.get("sessionId") or active.session_id
        active.output_so_far = str(payload.get("output") or active.output_so_far)
        active.status = str(payload.get("status") or "succeeded")
    elif message_type == "error":
        active.status = "failed"
    active.events.append(message)


def _message(
    message_type: str,
    *,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": message_type,
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": f"msg-{uuid.uuid4().hex}",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }
    if request_id:
        message["requestId"] = request_id
    return message


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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


app = create_app()


if os.getenv("COPILOT_BOX_BROKER_DEBUG_IMPORT") == "1":
    print(app)
