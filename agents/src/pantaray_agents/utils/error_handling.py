import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from pantaray_agents.agents.core import PublicAgentHTTPError
from pantaray_agents.utils.public_error import normalize_request_id, public_agent_error

logger = logging.getLogger(__name__)


# --- Exception Handlers ---


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI の `HTTPException` を安全にハンドリングする。

    ポリシー:
        - 4xx は `exc.detail` をそのまま返す（意図的に提示するユーザー向け情報の想定）。
        - 5xx は `exc.detail` を返さない（漏えい防止のため常にサニタイズ）。

    Args:
        request: FastAPI の Request。
        exc: 発生した HTTPException。

    Returns:
        JSONResponse。
    """

    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    logger.warning(
        "HTTPException caught: status_code=%s request_id=%s detail=%s",
        exc.status_code,
        request_id,
        exc.detail,
        exc_info=False,  # Don't log stack trace for expected HTTP exceptions
    )
    headers = dict(getattr(exc, "headers", None) or {})
    headers["X-Request-ID"] = request_id
    if exc.status_code >= 500:
        # 5xx は detail を外部へ返さない（内部構成・秘匿値漏えい防止）
        agent_error = public_agent_error(
            error_code="HTTP_EXCEPTION_SERVER_ERROR",
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": agent_error.model_dump(exclude_none=True)},
            headers=headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},  # Keep FastAPI's default structure for 4xx
        headers=headers,
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕捉例外（5xx）を安全にハンドリングする。

    重要:
        - スタックトレースや `str(exc)` はレスポンスへ含めない（LOG_LEVEL に依存しない）。
        - 詳細はログへ（`exc_info=True`）残し、外部には `error_code` と `request_id` を返す。

    Args:
        request: FastAPI の Request。
        exc: 未捕捉例外。

    Returns:
        JSONResponse（500）。
    """

    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    logger.error(
        "Unhandled exception caught: request_id=%s path=%s",
        request_id,
        request.url.path,
        exc_info=True,  # Log stack trace
    )
    agent_error = public_agent_error(
        error_code="UNEXPECTED_SERVER_ERROR",
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": agent_error.model_dump(exclude_none=True)},
        headers={"X-Request-ID": request_id},
    )


async def public_agent_http_error_handler(
    request: Request, exc: PublicAgentHTTPError
) -> JSONResponse:
    """公開可能な内部例外をサニタイズして返す。"""

    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    logger.error(
        "Public agent HTTP error: request_id=%s path=%s error_code=%s error=%s",
        request_id,
        request.url.path,
        exc.error_code,
        exc,
        exc_info=True,
    )
    agent_error = public_agent_error(
        error_code=exc.error_code,
        request_id=request_id,
        error_type=exc.error_type,
        severity=exc.severity,
        error_message=exc.public_message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": agent_error.model_dump(exclude_none=True)},
        headers={"X-Request-ID": request_id},
    )


# You can add more specific exception handlers here if needed
# async def validation_exception_handler(request: Request, exc: ValueError):
#     logger.warning("Validation error: %s", str(exc), exc_info=False)
#     error_detail = create_error_response_detail(
#         exc,
#         error_type=ErrorType.VALIDATION_ERROR,
#         error_code="REQUEST_VALIDATION_ERROR",
#         severity=ErrorSeverity.WARNING,
#     )
#     return JSONResponse(
#         status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
#         content={"detail": error_detail},
#     )
