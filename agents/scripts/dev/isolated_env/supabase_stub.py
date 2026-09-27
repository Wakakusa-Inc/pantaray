#!/usr/bin/env python3
"""Loopback Supabase stub for the credential-free isolated env (dev tool only).

Binds 127.0.0.1 only; serves GET /auth/v1/user, POST /auth/v1/token
(password|refresh_token grants), POST /functions/v1/desktop_auth/{issue,
exchange}, the /rest/v1 wallet row + insert echo, and GET /health.

Security posture: a stub, not an auth server. JWT signatures, PKCE, and
one-time-use are NOT enforced; well-formed requests succeed for the fixed smoke
user, and the signing secret is a public constant, worthless outside loopback.
Request paths are logged to stderr (never headers or bodies, so no token
material). Issued tokens carry aud="authenticated" and iss derived from the
stub's own loopback origin.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import sys
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

SELF_JWT_USER_ID = "3f7d1f2e-0000-4000-8000-000000000001"
SELF_JWT_TTL_SECONDS = 3600
_SELF_JWT_SECRET = b"pantaray-isolated-env-local-only"
WALLET_TABLE = "user_token_wallets"
STUB_BALANCE_MICROUSD = 10_000_000_000  # $10,000 — never a limiting factor
EXCHANGE_TTL_SECONDS = 120
# desktop_auth field lengths: attempt_id=36, code_challenge/exchange_code=43,
# code_verifier=43..128, fixed by the hosted desktop_auth contract.
JWT_AUD = "authenticated"
ISSUER = ""  # set in main() from the bound loopback origin


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_self_jwt(*, aud: str, iss: str, email: str | None = None) -> str:
    """HS256 JWT for the fixed smoke user; aud/iss must match the runtime configs."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": SELF_JWT_USER_ID,
        "aud": aud,
        "iss": iss,
        "role": "authenticated",
        "email": email or f"{SELF_JWT_USER_ID}@smoke.invalid",
        "session_id": str(uuid.uuid4()),
        "iat": now,
        "exp": now + SELF_JWT_TTL_SECONDS,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(
        _SELF_JWT_SECRET, signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _decode_jwt_payload(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_len(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, str) and minimum <= len(value) <= maximum


def _user_json(sub: str, aud: str, role: str, email: str) -> dict:
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "id": sub,
        "aud": aud,
        "role": role,
        "email": email,
        "email_confirmed_at": now_iso,
        "confirmed_at": now_iso,
        "last_sign_in_at": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
        "app_metadata": {"provider": "email", "providers": ["email"]},
        "user_metadata": {},
        "identities": [],
        "is_anonymous": False,
    }


def _session_json(email: str | None) -> dict:
    now = int(time.time())
    resolved_email = email or f"{SELF_JWT_USER_ID}@smoke.invalid"
    return {
        "access_token": issue_self_jwt(aud=JWT_AUD, iss=ISSUER, email=email),
        "token_type": "bearer",
        "expires_in": SELF_JWT_TTL_SECONDS,
        "expires_at": now + SELF_JWT_TTL_SECONDS,
        "refresh_token": secrets.token_urlsafe(24),
        "user": _user_json(SELF_JWT_USER_ID, JWT_AUD, "authenticated", resolved_email),
    }


class StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PantaraySupabaseStub/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(
            f"{datetime.now(UTC).isoformat()} {format % args}",
            file=sys.stderr,
            flush=True,
        )

    def _respond(self, status: int, body: object) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> object:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def _read_json_body(self) -> dict:
        body = self._read_body()
        return body if isinstance(body, dict) else {}

    def _bearer_token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return header.removeprefix("Bearer ").strip()

    def _bearer_payload(self) -> dict | None:
        token = self._bearer_token()
        payload = _decode_jwt_payload(token) if token else None
        if payload is None:
            return None
        exp = payload.get("exp")
        if isinstance(exp, (int, float)) and exp <= time.time():
            return None
        return payload

    def _auth_user(self) -> None:
        payload = self._bearer_payload()
        if payload is None or not isinstance(payload.get("sub"), str):
            self._respond(
                401, {"code": 401, "error_code": "bad_jwt", "msg": "invalid JWT"}
            )
            return
        sub = payload["sub"]
        self._respond(
            200,
            _user_json(
                sub,
                payload.get("aud") or "authenticated",
                payload.get("role") or "authenticated",
                payload.get("email") or f"{sub}@smoke.invalid",
            ),
        )

    def _invalid_grant(self, description: str) -> None:
        self._respond(400, {"error": "invalid_grant", "error_description": description})

    def _auth_token(self) -> None:
        grant = (parse_qs(urlsplit(self.path).query).get("grant_type") or [""])[0]
        body = self._read_json_body()
        if grant == "password":
            email = body.get("email")
            if not isinstance(email, str) or not email or not body.get("password"):
                self._invalid_grant("email and password are required")
                return
            self._respond(200, _session_json(email))
        elif grant == "refresh_token":
            if not body.get("refresh_token"):
                self._invalid_grant("refresh_token is required")
                return
            self._respond(200, _session_json(None))
        else:
            self._respond(400, {"error": "unsupported_grant_type"})

    def _desktop_auth_issue(self) -> None:
        body = self._read_json_body()
        tokens = body.get("tokens")
        if not (
            _is_len(body.get("attempt_id"), 36, 36)
            and _is_len(body.get("code_challenge"), 43, 43)
            and body.get("code_challenge_method") == "S256"
            and isinstance(tokens, dict)
            and _is_len(tokens.get("access_token"), 1, 10_000)
            and _is_len(tokens.get("refresh_token"), 1, 10_000)
        ):
            self._respond(400, {"ok": False, "error": "Invalid request body."})
            return
        if self._bearer_token() != tokens["access_token"]:
            self._respond(401, {"ok": False, "error": "access_token mismatch."})
            return
        expires_at = (
            datetime.fromtimestamp(time.time() + EXCHANGE_TTL_SECONDS, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        self._respond(
            200,
            {
                "ok": True,
                "exchange_code": _b64url(secrets.token_bytes(32)),
                "expires_at": expires_at,
            },
        )

    def _desktop_auth_exchange(self) -> None:
        body = self._read_json_body()
        if not (
            _is_len(body.get("attempt_id"), 36, 36)
            and _is_len(body.get("exchange_code"), 43, 43)
            and _is_len(body.get("code_verifier"), 43, 128)
        ):
            self._respond(400, {"ok": False, "error": "Invalid request body."})
            return
        self._respond(
            200,
            {
                "ok": True,
                "user_id": SELF_JWT_USER_ID,
                "tokens": {
                    "access_token": issue_self_jwt(aud=JWT_AUD, iss=ISSUER),
                    "refresh_token": secrets.token_urlsafe(24),
                },
                "session_version": "1",
            },
        )

    def _rest(self, method: str) -> None:
        table = urlsplit(self.path).path.removeprefix("/rest/v1/").strip("/")
        if method == "GET":
            if table == WALLET_TABLE:
                self._respond(
                    200, [{"current_balance_microusd": STUB_BALANCE_MICROUSD}]
                )
            else:
                self._respond(200, [])
            return
        # POST/PATCH inserts (usage events, etc.): echo the body as a list.
        body = self._read_body()
        self._respond(201, body if isinstance(body, list) else [body])

    def _route(self, method: str) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._respond(200, {"status": "ok"})
        elif path == "/auth/v1/user" and method == "GET":
            self._auth_user()
        elif path == "/auth/v1/token" and method == "POST":
            self._auth_token()
        elif path == "/functions/v1/desktop_auth/issue" and method == "POST":
            self._desktop_auth_issue()
        elif path == "/functions/v1/desktop_auth/exchange" and method == "POST":
            self._desktop_auth_exchange()
        elif path.startswith("/rest/v1/"):
            self._rest(method)
        else:
            self.log_message("UNHANDLED %s %s", method, path)
            self._respond(404, {"message": f"stub has no route for {method} {path}"})

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._route("PATCH")

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> int:
    global ISSUER
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    ISSUER = f"http://127.0.0.1:{args.port}/auth/v1"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), StubHandler)
    print(f"[supabase_stub] listening on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
