"""error_handling.pyのテスト"""

import json

import pytest
from fastapi import HTTPException
from starlette.responses import JSONResponse

from pantaray_agents.agents.core import AgentDependencyConfigError
from pantaray_agents.schema.agent.base import ErrorSeverity, ErrorType
from pantaray_agents.utils.error_handling import (
    general_exception_handler,
    http_exception_handler,
    public_agent_http_error_handler,
)


class MockRequest:
    def __init__(self, method="GET", url="http://testserver/", headers=None):
        self.method = method
        self.url = MockURL(url)
        self.headers = headers or {}


class MockURL:
    def __init__(self, url_string):
        self.path = url_string.replace("http://testserver", "")
        if not self.path:
            self.path = "/"


@pytest.mark.asyncio
async def test_http_exception_handler():
    """http_exception_handlerのテスト"""
    request = MockRequest(headers={"X-Request-ID": "req-403"})  # type: ignore
    exc = HTTPException(status_code=403, detail="Forbidden access")
    response = await http_exception_handler(request, exc)  # type: ignore
    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    assert response.headers.get("X-Request-ID") == "req-403"
    content = response.body.decode()
    # http_exception_handlerはFastAPIのデフォルトの挙動に近いため、"error_code"などはない
    assert "Forbidden access" in content
    # assert "http://testserver/" in content # request_infoはデフォルトでは含まれない


@pytest.mark.asyncio
async def test_http_exception_handler_5xx_is_sanitized():
    """5xx の HTTPException は detail をそのまま返さず、常にサニタイズされること"""
    request = MockRequest(headers={"X-Request-ID": "req-500"})  # type: ignore
    exc = HTTPException(status_code=500, detail="Sensitive detail")
    response = await http_exception_handler(request, exc)  # type: ignore
    assert response.status_code == 500
    assert response.headers.get("X-Request-ID") == "req-500"
    body = json.loads(response.body.decode())
    assert "detail" in body
    assert isinstance(body["detail"], dict)
    assert body["detail"]["error_code"] == "HTTP_EXCEPTION_SERVER_ERROR"
    assert body["detail"]["error_type"] == ErrorType.INTERNAL_ERROR.value
    assert body["detail"]["severity"] == ErrorSeverity.ERROR.value
    assert body["detail"]["error_details"]["request_id"] == "req-500"
    assert "Sensitive detail" not in response.body.decode()


@pytest.mark.asyncio
async def test_http_exception_handler_preserves_headers():
    """HTTPException の headers（例: Retry-After）をレスポンスへ引き継ぐこと"""
    request = MockRequest(headers={"X-Request-ID": "req-429"})  # type: ignore
    exc = HTTPException(
        status_code=429,
        detail={"error": "Rate limit exceeded"},
        headers={"Retry-After": "10"},
    )
    response = await http_exception_handler(request, exc)  # type: ignore
    assert response.status_code == 429
    assert response.headers.get("X-Request-ID") == "req-429"
    assert response.headers.get("Retry-After") == "10"


# @pytest.mark.asyncio
# async def test_validation_exception_handler():
#     """validation_exception_handlerのテスト"""
#     request = MockRequest()
#     # pydantic_core.ErrorDetailsのリストを作成
#     raw_errors = [
#         ErrorDetails(
#             type="missing",
#             loc=("body", "field1"),
#             msg="Field required",
#             input={},
#         )
#     ]
#     exc = ValidationError.from_exception_data(title="TestValidation", line_errors=raw_errors)
#
#     response = await validation_exception_handler(request, exc) # type: ignore
#     assert isinstance(response, JSONResponse)
#     assert response.status_code == 422
#     content = response.body.decode()
#     assert "VALIDATION_ERROR" in content
#     assert "Field required" in content
#     assert "field1" in content
#     assert "http://testserver/" in content # request_info

# @pytest.mark.asyncio
# async def test_generic_exception_handler():
#     """generic_exception_handlerのテスト"""
#     request = MockRequest()
#     exc = Exception("Something went wrong")
#     response = await generic_exception_handler(request, exc) # type: ignore
#     assert isinstance(response, JSONResponse)
#     assert response.status_code == 500
#     content = response.body.decode()
#     assert "UNHANDLED_EXCEPTION" in content
#     assert "Something went wrong" in content
#     assert "http://testserver/" in content # request_info


@pytest.mark.asyncio
async def test_general_exception_handler():
    """汎用例外ハンドラのテスト"""
    mock_request = MockRequest(
        method="POST",
        url="http://testserver/general_error",
        headers={"X-Request-ID": "req-err"},
    )
    exc = RuntimeError("A deliberate runtime error occurred")

    # general_exception_handler を直接呼び出す
    # 実際には FastAPI の例外処理メカニズム経由で呼び出される
    response = await general_exception_handler(mock_request, exc)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.headers.get("X-Request-ID") == "req-err"

    content = json.loads(response.body.decode())
    assert "detail" in content
    detail_content = content["detail"]

    assert (
        detail_content["error_type"] == ErrorType.INTERNAL_ERROR.value
    )  # Enumの値を比較
    assert detail_content["error_code"] == "UNEXPECTED_SERVER_ERROR"
    # 外部へは生の例外文字列を返さない
    assert detail_content["error_message"] == (
        "The operation failed due to an internal error."
    )
    assert detail_content["severity"] == ErrorSeverity.ERROR.value  # Enumの値を比較
    assert "error_details" in detail_content
    assert detail_content["error_details"]["request_id"] == "req-err"
    # スタックトレース等の詳細は返さない
    assert "stack_trace" not in detail_content["error_details"]


@pytest.mark.asyncio
async def test_public_agent_http_error_handler() -> None:
    request = MockRequest(
        method="POST",
        url="http://testserver/agents/config",
        headers={"X-Request-ID": "req-dep"},
    )
    exc = AgentDependencyConfigError("agent dependency is misconfigured")

    response = await public_agent_http_error_handler(request, exc)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.headers.get("X-Request-ID") == "req-dep"

    body = json.loads(response.body.decode())
    assert body["detail"]["error_code"] == "AGENT_DEPENDENCY_CONFIG_ERROR"
    assert body["detail"]["error_details"]["request_id"] == "req-dep"
