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
class BrokerState:
    workers: dict[str, WorkerConnection] = field(default_factory=dict)
    clients: dict[str, WebSocket] = field(default_factory=dict)
    requests: dict[str, RequestRoute] = field(default_factory=dict)

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

    return app


async def _route_client_message(
    state: BrokerState,
    connection_id: str,
    websocket: WebSocket,
    message: dict[str, Any],
) -> None:
    message_type = message.get("type")
    if message_type not in {"agent.request", "report.read"}:
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
    try:
        await route.client_websocket.send_json(message)
    finally:
        if message.get("type") in {"agent.final", "report.content", "error"}:
            worker = state.workers.get(route.worker_id)
            if worker is not None:
                worker.busy = False
            state.requests.pop(request_id, None)


async def _remove_worker(state: BrokerState, worker_id: str) -> None:
    state.workers.pop(worker_id, None)
    failed_request_ids = [
        request_id
        for request_id, route in state.requests.items()
        if route.worker_id == worker_id
    ]
    for request_id in failed_request_ids:
        route = state.requests.pop(request_id)
        try:
            await route.client_websocket.send_json(
                _error(
                    request_id,
                    "worker_disconnected",
                    "Worker disconnected while processing request.",
                )
            )
        except (BrokenResourceError, ClosedResourceError, RuntimeError) as exc:
            print(f"client disconnected before worker error delivery: {exc}")


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
