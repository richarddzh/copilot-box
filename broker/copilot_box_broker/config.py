from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerSettings:
    auth_mode: str
    client_token: str
    worker_token: str
    entra_tenant_id: str = ""
    entra_audience: str = ""
    entra_allowed_client_app_ids: tuple[str, ...] = ()
    entra_allowed_worker_app_ids: tuple[str, ...] = ()
    entra_required_client_scope: str = ""
    entra_required_worker_role: str = ""

    @classmethod
    def from_env(cls) -> BrokerSettings:
        return cls(
            auth_mode=os.getenv("COPILOT_BOX_BROKER_AUTH_MODE", "shared_secret").strip().lower(),
            client_token=os.getenv("COPILOT_BOX_CLIENT_SHARED_TOKEN", ""),
            worker_token=os.getenv("COPILOT_BOX_WORKER_SHARED_TOKEN", ""),
            entra_tenant_id=os.getenv("COPILOT_BOX_ENTRA_TENANT_ID", ""),
            entra_audience=os.getenv("COPILOT_BOX_ENTRA_AUDIENCE", ""),
            entra_allowed_client_app_ids=_csv_env("COPILOT_BOX_ENTRA_ALLOWED_CLIENT_APP_IDS"),
            entra_allowed_worker_app_ids=_csv_env("COPILOT_BOX_ENTRA_ALLOWED_WORKER_APP_IDS"),
            entra_required_client_scope=os.getenv(
                "COPILOT_BOX_ENTRA_REQUIRED_CLIENT_SCOPE",
                "",
            ),
            entra_required_worker_role=os.getenv(
                "COPILOT_BOX_ENTRA_REQUIRED_WORKER_ROLE",
                "",
            ),
        )


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in os.getenv(name, "").split(",")
        if item.strip()
    )
