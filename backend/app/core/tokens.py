from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.config import settings
from app.models import UserRole, utc_now


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(message: str) -> str:
    digest = hmac.new(settings.auth_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def issue_token(subject: str, role: UserRole, token_kind: str, expires_delta: timedelta) -> str:
    issued_at = utc_now()
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": subject,
        "role": role.value,
        "kind": token_kind,
        "jti": uuid4().hex,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + expires_delta).timestamp()),
    }
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(f"{encoded_header}.{encoded_payload}")
    return f"{encoded_header}.{encoded_payload}.{signature}"


def decode_token(token: str, expected_kind: str) -> dict:
    try:
        encoded_header, encoded_payload, signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed bearer token.") from exc

    message = f"{encoded_header}.{encoded_payload}"
    if not hmac.compare_digest(signature, _sign(message)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token signature.")

    payload = json.loads(_b64decode(encoded_payload))
    if payload.get("kind") != expected_kind:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token type.")
    if int(payload.get("exp", 0)) < int(utc_now().timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token expired.")
    return payload
