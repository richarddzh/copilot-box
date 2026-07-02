from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
from starlette.datastructures import Headers

from copilot_box_broker.config import BrokerSettings

PrincipalKind = Literal["client", "worker"]


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    subject: str
    app_id: str
    claims: dict[str, object]


def require_auth_config(settings: BrokerSettings) -> None:
    if settings.auth_mode == "shared_secret":
        if not settings.client_token or not settings.worker_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Broker client and worker tokens must be configured.",
            )
        return
    if settings.auth_mode == "entra_id":
        if not settings.entra_tenant_id or not settings.entra_audience:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Broker Entra tenant id and audience must be configured.",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Unsupported broker auth mode: {settings.auth_mode}",
    )


def authenticate_websocket(
    headers: Headers,
    settings: BrokerSettings,
    kind: PrincipalKind,
) -> Principal | None:
    require_auth_config(settings)
    if settings.auth_mode == "shared_secret":
        expected = settings.client_token if kind == "client" else settings.worker_token
        header_name = "x-copilot-box-token" if kind == "client" else "x-copilot-box-worker-token"
        if headers.get(header_name) != expected:
            return None
        return Principal(kind=kind, subject=kind, app_id="", claims={})

    authorization = headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return _authenticate_entra_token(token.strip(), settings, kind)


def _authenticate_entra_token(
    token: str,
    settings: BrokerSettings,
    kind: PrincipalKind,
) -> Principal | None:
    try:
        jwks_client = PyJWKClient(_jwks_url(settings.entra_tenant_id))
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.entra_audience,
            issuer=_issuer(settings.entra_tenant_id),
        )
    except PyJWTError:
        return None

    app_id = _claim_text(claims, "azp") or _claim_text(claims, "appid")
    allowed_app_ids = (
        settings.entra_allowed_client_app_ids
        if kind == "client"
        else settings.entra_allowed_worker_app_ids
    )
    if allowed_app_ids and app_id not in allowed_app_ids:
        return None

    required_scope = settings.entra_required_client_scope if kind == "client" else ""
    if required_scope and required_scope not in str(claims.get("scp", "")).split():
        return None

    required_role = settings.entra_required_worker_role if kind == "worker" else ""
    roles = claims.get("roles", [])
    if required_role and not (isinstance(roles, list) and required_role in roles):
        return None

    subject = _claim_text(claims, "oid") or _claim_text(claims, "sub") or app_id or kind
    return Principal(kind=kind, subject=subject, app_id=app_id, claims=dict(claims))


def _issuer(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/v2.0"


def _jwks_url(tenant_id: str) -> str:
    return f"{_issuer(tenant_id)}/discovery/v2.0/keys"


def _claim_text(claims: dict[str, object], name: str) -> str:
    value = claims.get(name)
    return value if isinstance(value, str) else ""
