from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionSettings:
    state_dir: Path
    ttl_seconds: int = 86400
    max_concurrent_requests: int = 1


@dataclass(frozen=True)
class WorkDirSettings:
    allowed_roots: tuple[Path, ...]


@dataclass(frozen=True)
class AgentSettings:
    adapter: str = "github_copilot_sdk"
    model: str | None = "gpt-5"
    timeout_seconds: float = 120
    approve_all_tool_requests: bool = True
    base_directory: Path | None = None


@dataclass(frozen=True)
class AppSettings:
    sessions: SessionSettings
    workdirs: WorkDirSettings
    agent: AgentSettings


def load_settings(path: Path) -> AppSettings:
    config_path = path.expanduser().resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    sessions = raw.get("sessions", {})
    workdirs = raw.get("workdirs", {})
    agent = raw.get("agent", {})

    state_dir = _path_from_config(sessions.get("state_dir"), base_dir, "sessions.state_dir")
    allowed_roots = tuple(
        _path_from_config(value, base_dir, "workdirs.allowed_roots")
        for value in workdirs.get("allowed_roots", [])
    )
    if not allowed_roots:
        raise ValueError("workdirs.allowed_roots must contain at least one path")

    base_directory_value = agent.get("base_directory")
    base_directory = (
        _path_from_config(base_directory_value, base_dir, "agent.base_directory")
        if base_directory_value
        else state_dir / "copilot-home"
    )

    return AppSettings(
        sessions=SessionSettings(
            state_dir=state_dir,
            ttl_seconds=int(sessions.get("ttl_seconds", 86400)),
            max_concurrent_requests=int(sessions.get("max_concurrent_requests", 1)),
        ),
        workdirs=WorkDirSettings(allowed_roots=allowed_roots),
        agent=AgentSettings(
            adapter=str(agent.get("adapter", "github_copilot_sdk")),
            model=_optional_str(agent.get("model", "gpt-5")),
            timeout_seconds=float(agent.get("timeout_seconds", 120)),
            approve_all_tool_requests=bool(agent.get("approve_all_tool_requests", True)),
            base_directory=base_directory,
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
