from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from copilot_box.config import AppSettings
from copilot_box.sessions import SessionMode, SessionRecord, SessionStore


@dataclass(frozen=True)
class PromptRequest:
    prompt: str
    work_dir: Path
    session_mode: SessionMode = "auto"
    session_id: str | None = None
    timeout_seconds: float | None = None
    model: str | None = None


@dataclass(frozen=True)
class PromptResult:
    session_id: str
    created_session: bool
    work_dir: Path
    output: str


class AgentAdapter(Protocol):
    async def send_prompt(
        self,
        *,
        session: SessionRecord,
        prompt: str,
        timeout_seconds: float,
        model: str | None,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        pass


class CopilotSdkAgentAdapter:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    async def send_prompt(
        self,
        *,
        session: SessionRecord,
        prompt: str,
        timeout_seconds: float,
        model: str | None,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        from copilot import CopilotClient, PermissionHandler
        from copilot.session_events import (
            AssistantMessageData,
            AssistantMessageDeltaData,
            SessionErrorData,
        )

        base_directory = self._settings.agent.base_directory
        if base_directory is not None:
            base_directory.mkdir(parents=True, exist_ok=True)

        chunks: list[str] = []
        final_message: str | None = None
        errors: list[str] = []

        def on_event(event: object) -> None:
            nonlocal final_message
            data = getattr(event, "data", None)
            match data:
                case AssistantMessageDeltaData() as delta:
                    chunks.append(delta.delta_content)
                    if on_delta is not None:
                        on_delta(delta.delta_content)
                case AssistantMessageData() as message:
                    final_message = message.content
                case SessionErrorData() as error:
                    errors.append(error.message)

        permission_handler = (
            PermissionHandler.approve_all
            if self._settings.agent.approve_all_tool_requests
            else None
        )

        async with CopilotClient(
            working_directory=str(session.work_dir),
            base_directory=str(base_directory) if base_directory is not None else None,
        ) as client:
            copilot_session = await client.create_session(
                session_id=session.session_id,
                working_directory=str(session.work_dir),
                model=model,
                on_permission_request=permission_handler,
                on_event=on_event,
                streaming=True,
                enable_session_store=True,
            )
            try:
                event = await copilot_session.send_and_wait(
                    prompt,
                    timeout=timeout_seconds,
                    agent_mode="autopilot",
                )
                data = getattr(event, "data", None) if event is not None else None
                if isinstance(data, AssistantMessageData):
                    final_message = data.content
            finally:
                await copilot_session.disconnect()

        if final_message:
            return final_message
        if chunks:
            return "".join(chunks)
        if errors:
            raise RuntimeError("; ".join(errors))
        return ""


class EchoAgentAdapter:
    async def send_prompt(
        self,
        *,
        session: SessionRecord,
        prompt: str,
        timeout_seconds: float,
        model: str | None,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        del timeout_seconds, model
        output = f"[echo:{session.session_id}] {prompt}"
        if on_delta is not None:
            on_delta(output)
        return output


class AgentService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        session_store: SessionStore | None = None,
        adapter: AgentAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._session_store = session_store or SessionStore(settings)
        self._adapter = adapter or _build_adapter(settings)

    async def handle_prompt(
        self,
        request: PromptRequest,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> PromptResult:
        session, created = self._session_store.select_session(
            mode=request.session_mode,
            work_dir=request.work_dir,
            requested_session_id=request.session_id,
        )
        output = await self._adapter.send_prompt(
            session=session,
            prompt=request.prompt,
            timeout_seconds=request.timeout_seconds or self._settings.agent.timeout_seconds,
            model=request.model if request.model is not None else self._settings.agent.model,
            on_delta=on_delta,
        )
        self._session_store.touch(session.session_id)
        return PromptResult(
            session_id=session.session_id,
            created_session=created,
            work_dir=session.work_dir,
            output=output,
        )


def _build_adapter(settings: AppSettings) -> AgentAdapter:
    if settings.agent.adapter == "github_copilot_sdk":
        return CopilotSdkAgentAdapter(settings)
    if settings.agent.adapter == "echo":
        return EchoAgentAdapter()
    raise ValueError(f"unsupported agent adapter: {settings.agent.adapter}")
