from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from starlette.requests import HTTPConnection

AUTHENTICATION_REQUIRED_DETAIL = "Authentication required. Please sign in again."

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

# Resolves a bearer token to the authenticated user id, or raises HTTPException.
# Each app installs its own implementation on `app.state.authenticate_request`:
# the local runtime verifies its own API token, the cloud verifies Supabase JWTs.
type RequestAuthenticator = Callable[[str | None], Awaitable[str]]


def authentication_failed_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTHENTICATION_REQUIRED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_id_from_token(
    connection: HTTPConnection,
    token: str | None = Depends(oauth2_scheme),
) -> str:
    authenticate = cast(RequestAuthenticator, connection.app.state.authenticate_request)
    return await authenticate(token)
