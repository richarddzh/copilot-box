from __future__ import annotations

from copilot_box_broker.config import BrokerSettings
from copilot_box_broker.main import create_app
from fastapi.testclient import TestClient


def make_client() -> TestClient:
    settings = BrokerSettings(
        auth_mode="shared_secret",
        client_token="client-token",
        worker_token="worker-token",
    )
    return TestClient(create_app(settings=settings))


def test_websocket_routes_streaming_agent_messages() -> None:
    client = make_client()

    with client.websocket_connect(
        "/ws/worker",
        headers={"X-Copilot-Box-Worker-Token": "worker-token"},
    ) as worker:
        worker.send_json(
            {
                "type": "worker.hello",
                "workerId": "worker-1",
                "displayName": "Worker 1",
                "allowedWorkDirs": ["Q:\\gitroot\\copilot-box"],
                "capabilities": {"streaming": True, "markdown": True},
            }
        )
        assert worker.receive_json()["type"] == "broker.worker.accepted"

        with client.websocket_connect(
            "/ws/client",
            headers={"X-Copilot-Box-Token": "client-token"},
        ) as app_client:
            app_client.send_json({"type": "client.hello", "clientId": "android-test"})
            hello = app_client.receive_json()
            assert hello["type"] == "broker.hello"
            assert hello["payload"]["availableWorkers"][0]["allowedWorkDirs"] == [
                "Q:\\gitroot\\copilot-box"
            ]

            app_client.send_json(
                {
                    "type": "agent.request",
                    "requestId": "req-1",
                    "payload": {
                        "workerId": "worker-1",
                        "workDir": "Q:\\gitroot\\copilot-box",
                        "session": {"mode": "auto", "sessionId": None},
                        "agent": {"prompt": "hello", "model": None, "timeoutSeconds": 120},
                    },
                }
            )
            assert app_client.receive_json()["type"] == "broker.accepted"
            forwarded = worker.receive_json()
            assert forwarded["type"] == "agent.request"
            assert forwarded["requestId"] == "req-1"

            worker.send_json(
                {
                    "type": "agent.delta",
                    "requestId": "req-1",
                    "payload": {"sequence": 1, "text": "**hi**", "contentType": "text/markdown"},
                }
            )
            assert app_client.receive_json()["payload"]["text"] == "**hi**"

            worker.send_json(
                {
                    "type": "agent.final",
                    "requestId": "req-1",
                    "payload": {
                        "status": "succeeded",
                        "sessionId": "sess_1",
                        "output": "**hi**",
                        "contentType": "text/markdown",
                    },
                }
            )
            assert app_client.receive_json()["payload"]["sessionId"] == "sess_1"


def test_websocket_routes_report_read() -> None:
    client = make_client()

    with client.websocket_connect(
        "/ws/worker",
        headers={"X-Copilot-Box-Worker-Token": "worker-token"},
    ) as worker:
        worker.send_json(
            {
                "type": "worker.hello",
                "workerId": "worker-1",
                "allowedWorkDirs": ["Q:\\gitroot\\copilot-box"],
                "reportWorkspace": {"enabled": True, "root": "Q:\\reports"},
            }
        )
        worker.receive_json()

        with client.websocket_connect(
            "/ws/client",
            headers={"X-Copilot-Box-Token": "client-token"},
        ) as app_client:
            app_client.send_json({"type": "client.hello"})
            hello = app_client.receive_json()
            assert hello["payload"]["availableWorkers"][0]["reportWorkspace"]["enabled"] is True

            app_client.send_json(
                {
                    "type": "report.read",
                    "requestId": "report-1",
                    "payload": {"workerId": "worker-1", "path": "reports/req-1/index.md"},
                }
            )
            forwarded = worker.receive_json()
            assert forwarded["type"] == "report.read"
            assert forwarded["payload"]["path"] == "reports/req-1/index.md"

            worker.send_json(
                {
                    "type": "report.content",
                    "requestId": "report-1",
                    "payload": {
                        "path": "reports/req-1/index.md",
                        "contentType": "text/markdown",
                        "content": "# Report",
                    },
                }
            )
            response = app_client.receive_json()
            assert response["type"] == "report.content"
            assert response["payload"]["content"] == "# Report"


def test_websocket_rejects_busy_worker() -> None:
    client = make_client()

    with client.websocket_connect(
        "/ws/worker",
        headers={"X-Copilot-Box-Worker-Token": "worker-token"},
    ) as worker:
        worker.send_json(
            {
                "type": "worker.hello",
                "workerId": "worker-1",
                "allowedWorkDirs": ["Q:\\gitroot\\copilot-box"],
            }
        )
        worker.receive_json()
        with client.websocket_connect(
            "/ws/client",
            headers={"X-Copilot-Box-Token": "client-token"},
        ) as app_client:
            app_client.send_json({"type": "client.hello"})
            app_client.receive_json()
            request = {
                "type": "agent.request",
                "requestId": "req-1",
                "payload": {
                    "workerId": "worker-1",
                    "workDir": "Q:\\gitroot\\copilot-box",
                    "session": {"mode": "auto"},
                    "agent": {"prompt": "hello"},
                },
            }
            app_client.send_json(request)
            assert app_client.receive_json()["type"] == "broker.accepted"
            worker.receive_json()

            request["requestId"] = "req-2"
            app_client.send_json(request)
            error = app_client.receive_json()
            assert error["type"] == "error"
            assert error["payload"]["code"] == "worker_busy"
