from __future__ import annotations

from fastapi import HTTPException, status

from copilot_box_broker.config import BrokerSettings


def require_shared_secret_config(settings: BrokerSettings) -> None:
    if settings.auth_mode != "shared_secret":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Unsupported broker auth mode: {settings.auth_mode}",
        )
    if not settings.client_token or not settings.worker_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Broker client and worker tokens must be configured.",
        )
