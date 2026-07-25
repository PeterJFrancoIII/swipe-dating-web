"""FastAPI parity adapter over the pure synthetic rendezvous store."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, cast

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from swipe_dating.domain.adult import create_adult_credential
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.matching import MatchReceipt, PresenceLease, RendezvousStore

MAX_REQUEST_BODY_BYTES = 65_536


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        strict=True,
        extra="ignore",
    )


class AdultCredentialPayload(WireModel):
    subject_id: str
    issued_at_ms: int
    expires_at_ms: int
    issuer: str = "staging-mock"
    revoked: bool = False


class PresencePayload(WireModel):
    profile_id: str
    region: str
    issued_at_ms: int
    expires_at_ms: int
    adult_credential: AdultCredentialPayload


class LikePayload(WireModel):
    sender_profile_id: str
    recipient_profile_id: str


class BlockPayload(WireModel):
    blocker_profile_id: str
    blocked_profile_id: str


class RequestBodyLimitMiddleware:
    """Buffer the small JSON body and fail before framework parsing if oversized."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                break
            body = cast(bytes, message.get("body", b""))
            total += len(body)
            if total > self.max_bytes:
                response = JSONResponse({"error": "request_body_too_large"}, status_code=400)
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)


def create_app(
    *,
    store: RendezvousStore | None = None,
    clock: Callable[[], int] | None = None,
) -> FastAPI:
    rendezvous = store if store is not None else RendezvousStore()
    now = clock if clock is not None else lambda: int(time.time() * 1_000)
    application = FastAPI(
        title="Swipe Dating Python R&D",
        version="0.1.0",
        description=(
            "Synthetic in-memory research API. No real authentication, delivery, encryption, "
            "or production approval."
        ),
    )
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

    @application.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse({"error": error.code}, status_code=400)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse({"error": "bad_request"}, status_code=400)

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse({"error": "bad_request"}, status_code=error.status_code)

    @application.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "python-rnd-synthetic-only"}

    @application.put("/v1/presence")
    async def put_presence(body: PresencePayload) -> dict[str, object]:
        adult_credential = create_adult_credential(
            subject_id=body.adult_credential.subject_id,
            issued_at_ms=body.adult_credential.issued_at_ms,
            expires_at_ms=body.adult_credential.expires_at_ms,
            issuer=body.adult_credential.issuer,
            revoked=body.adult_credential.revoked,
        )
        lease = rendezvous.publish_presence(
            profile_id=body.profile_id,
            region=body.region,
            issued_at_ms=body.issued_at_ms,
            expires_at_ms=body.expires_at_ms,
            adult_credential=adult_credential,
        )
        return _lease_to_wire(lease)

    @application.delete("/v1/presence/{profile_id}")
    async def delete_presence(profile_id: str) -> dict[str, bool]:
        return {"withdrawn": rendezvous.withdraw_presence(profile_id)}

    @application.get("/v1/discovery")
    async def get_discovery(
        region: Annotated[str, Query()],
        requester_profile_id: Annotated[str, Query(alias="requesterProfileId")],
        limit: Annotated[int, Query()] = 20,
    ) -> dict[str, list[str]]:
        return {
            "profileIds": list(
                rendezvous.discover(
                    region=region,
                    requester_profile_id=requester_profile_id,
                    now_ms=now(),
                    limit=limit,
                )
            )
        }

    @application.post("/v1/likes")
    async def post_like(body: LikePayload) -> dict[str, object]:
        receipt = rendezvous.record_like(
            sender_profile_id=body.sender_profile_id,
            recipient_profile_id=body.recipient_profile_id,
            now_ms=now(),
        )
        return {
            "matched": receipt is not None,
            "receipt": _receipt_to_wire(receipt) if receipt is not None else None,
        }

    @application.post("/v1/blocks", status_code=204)
    async def post_block(body: BlockPayload) -> Response:
        rendezvous.block(
            blocker_profile_id=body.blocker_profile_id,
            blocked_profile_id=body.blocked_profile_id,
        )
        return Response(status_code=204)

    return application


def _lease_to_wire(lease: PresenceLease) -> dict[str, object]:
    return {
        "profileId": lease.profile_id,
        "region": lease.region,
        "issuedAtMs": lease.issued_at_ms,
        "expiresAtMs": lease.expires_at_ms,
    }


def _receipt_to_wire(receipt: MatchReceipt) -> dict[str, object]:
    return {
        "profileA": receipt.profile_a,
        "profileB": receipt.profile_b,
        "matchedAtMs": receipt.matched_at_ms,
    }


app = create_app()
