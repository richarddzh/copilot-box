from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrokerClientSettings:
    url: str = ""
    worker_id: str = ""
    auth_mode: str = "shared_secret"
    worker_token: str = ""
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_scope: str = ""
    display_name: str = ""
    reconnect_seconds: float = 5
    heartbeat_seconds: float = 30


@dataclass(frozen=True)
class SessionSettings:
    state_dir: Path
    ttl_seconds: int = 86400
    max_concurrent_requests: int = 1
    single_active_session: bool = True


@dataclass(frozen=True)
class WorkDirSettings:
    allowed: tuple[Path, ...]


@dataclass(frozen=True)
class AgentSettings:
    adapter: str = "github_copilot_sdk"
    model: str | None = "gpt-5"
    timeout_seconds: float = 120
    approve_all_tool_requests: bool = True
    base_directory: Path | None = None


@dataclass(frozen=True)
class ReportSettings:
    enabled: bool = False
    root_dir: Path | None = None
    max_file_bytes: int = 1048576


@dataclass(frozen=True)
class AppSettings:
    broker: BrokerClientSettings
    sessions: SessionSettings
    workdirs: WorkDirSettings
    agent: AgentSettings
    reports: ReportSettings


def load_settings(path: Path) -> AppSettings:
    config_path = path.expanduser().resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    broker = raw.get("broker", {})
    sessions = raw.get("sessions", {})
    workdirs = raw.get("workdirs", {})
    agent = raw.get("agent", {})
    reports = raw.get("reports", {})

    state_dir = _path_from_config(sessions.get("state_dir"), base_dir, "sessions.state_dir")
    allowed_workdirs = tuple(
        _path_from_config(value, base_dir, "workdirs.allowed")
        for value in workdirs.get("allowed", [])
    )
    if not allowed_workdirs:
        raise ValueError("workdirs.allowed must contain at least one path")

    base_directory_value = agent.get("base_directory")
    base_directory = (
        _path_from_config(base_directory_value, base_dir, "agent.base_directory")
        if base_directory_value
        else state_dir / "copilot-home"
    )

    return AppSettings(
        broker=BrokerClientSettings(
            url=str(broker.get("url", "")).strip(),
            worker_id=str(broker.get("worker_id", "")).strip(),
            auth_mode=str(broker.get("auth_mode", "shared_secret")).strip().lower(),
            worker_token=str(broker.get("worker_token", "")).strip(),
            entra_tenant_id=str(broker.get("entra_tenant_id", "")).strip(),
            entra_client_id=str(broker.get("entra_client_id", "")).strip(),
            entra_client_secret=str(broker.get("entra_client_secret", "")).strip(),
            entra_scope=str(broker.get("entra_scope", "")).strip(),
            display_name=str(broker.get("display_name", "")).strip(),
            reconnect_seconds=float(broker.get("reconnect_seconds", 5)),
            heartbeat_seconds=float(broker.get("heartbeat_seconds", 30)),
        ),
        sessions=SessionSettings(
            state_dir=state_dir,
            ttl_seconds=int(sessions.get("ttl_seconds", 86400)),
            max_concurrent_requests=int(sessions.get("max_concurrent_requests", 1)),
            single_active_session=bool(sessions.get("single_active_session", True)),
        ),
        workdirs=WorkDirSettings(allowed=allowed_workdirs),
        agent=AgentSettings(
            adapter=str(agent.get("adapter", "github_copilot_sdk")),
            model=_optional_str(agent.get("model", "gpt-5")),
            timeout_seconds=float(agent.get("timeout_seconds", 120)),
            approve_all_tool_requests=bool(agent.get("approve_all_tool_requests", True)),
            base_directory=base_directory,
        ),
        reports=ReportSettings(
            enabled=bool(reports.get("enabled", False)),
            root_dir=(
                _path_from_config(reports.get("root_dir"), base_dir, "reports.root_dir")
                if reports.get("root_dir")
                else None
            ),
            max_file_bytes=int(reports.get("max_file_bytes", 1048576)),
        ),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_from_config(value: Any, base_dir: Path, field_name: str) -> Path:
    if not value:
        raise ValueError(f"{field_name} is required")

    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)
