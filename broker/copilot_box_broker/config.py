from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerSettings:
    auth_mode: str
    client_token: str
    worker_token: str

    @classmethod
    def from_env(cls) -> BrokerSettings:
        return cls(
            auth_mode=os.getenv("COPILOT_BOX_BROKER_AUTH_MODE", "shared_secret"),
            client_token=os.getenv("COPILOT_BOX_CLIENT_SHARED_TOKEN", ""),
            worker_token=os.getenv("COPILOT_BOX_WORKER_SHARED_TOKEN", ""),
        )
