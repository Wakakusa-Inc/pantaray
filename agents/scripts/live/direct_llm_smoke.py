"""Live smoke of the direct LLM route against the real OpenAI API.

Reads the key from the OPENAI_API_KEY environment variable and never prints it.
Drives `LocalLlmProxyClient.generate_content` exactly as an agent does, with the
store configured the way the control socket configures it (no cloud session, a
stored API-key connection), so the request crosses the real route decision,
request builder, direct dispatcher, adapter and transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
import sys
import tempfile
import traceback
import zlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pantaray_agents.local_runtime.llm_proxy.client import LocalLlmProxyClient
from pantaray_agents.local_runtime.runtime.connection_store import (
    ApiKeyConnection,
    set_llm_connection,
)
from pantaray_agents.local_runtime.runtime.identity import register_logged_out_owner
from pantaray_agents.local_runtime.runtime.session_store import mark_configured
from pantaray_agents.proxy_errors import build_llm_proxy_agent_error
from pantaray_agents.utils.llm_types import types
from pantaray_agents.utils.trace_context import TraceContextManager
from pantaray_llm.contracts.action_turn import LlmActionTurnRequest
from pantaray_llm.contracts.tool_use import (
    LlmToolDefinition,
    LlmToolResult,
    LlmToolUseRequest,
)
from pantaray_llm.errors import LlmProxyExecutionError
from pantaray_llm.profiles import (
    ACTION_EXECUTING_PROFILE_ID,
    ACTIVITY_SUMMARY_PROFILE_ID,
)

OWNER = "live-smoke-owner"
MODEL = os.environ.get("SMOKE_MODEL", "gpt-6-luna")
UNUSED_PROXY_URL = "https://unused.invalid/v1/llm/proxy"

ECHO_TOOL = LlmToolDefinition.model_validate(
    {
        "name": "lookup_capital",
        "description": "Look up the capital city of a country.",
        "parameters": {
            "type": "object",
            "properties": {"country": {"type": "string"}},
            "required": ["country"],
            "additionalProperties": False,
        },
    }
)


FINISH_TOOL = LlmToolDefinition.model_validate(
    {
        "name": "finish",
        "description": "Report the final answer to the user.",
        "parameters": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }
)
TOOL_PROMPT = (
    "Find the capital of France with lookup_capital, then report it with finish."
)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


def red_png(size: int = 64) -> bytes:
    row = b"\x00" + b"\xff\x00\x00" * size
    raw = row * size

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


async def generate(contents: list[object], config: object, job: str):
    with TraceContextManager(user_id=OWNER, local_job_id=job):
        return await LocalLlmProxyClient(
            proxy_url=UNUSED_PROXY_URL
        ).aio.models.generate_content(contents=contents, config=config)


def describe(result: object) -> str:
    text = getattr(result, "text", "")
    meta = getattr(result, "meta", None)
    usage = getattr(result, "usage_metadata", None)
    return f"text={text[:120]!r} meta={meta} usage={usage}"


async def case_text() -> str:
    result = await generate(
        ["Reply with exactly the word: pong"],
        types.GenerateContentConfig(inference_profile=ACTIVITY_SUMMARY_PROFILE_ID),
        "smoke-text",
    )
    assert "pong" in result.text.lower(), result.text
    assert result.meta and result.meta["upstream_provider"] == "openai"
    assert result.usage_metadata
    return describe(result)


async def case_structured() -> str:
    result = await generate(
        ["What is 2 + 3? Put only the number in `answer`."],
        types.GenerateContentConfig(
            inference_profile=ACTIVITY_SUMMARY_PROFILE_ID,
            response_mime_type="application/json",
            response_schema=Answer,
        ),
        "smoke-structured",
    )
    assert isinstance(result.parsed, Answer), type(result.parsed)
    assert "5" in result.parsed.answer, result.parsed
    return f"parsed={result.parsed!r}"


async def case_tool_roundtrip() -> str:
    first = await generate(
        [TOOL_PROMPT],
        types.GenerateContentConfig(
            inference_profile=ACTION_EXECUTING_PROFILE_ID,
            tool_use=LlmToolUseRequest(
                tools=[ECHO_TOOL, FINISH_TOOL], continuation_mode="stateless"
            ),
        ),
        "smoke-tool-1",
    )
    assert first.tool_calls, f"no tool call: {describe(first)}"
    assert first.tool_continuation is not None
    call = first.tool_calls[0]
    second = await generate(
        [TOOL_PROMPT],
        types.GenerateContentConfig(
            inference_profile=ACTION_EXECUTING_PROFILE_ID,
            tool_use=LlmToolUseRequest(
                tools=[ECHO_TOOL, FINISH_TOOL],
                continuation_mode="stateless",
                continuation=first.tool_continuation,
                tool_result=LlmToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    output={"capital": "Paris"},
                ),
            ),
        ),
        "smoke-tool-2",
    )
    seen = second.text.lower() + " ".join(
        str(c.arguments).lower() for c in second.tool_calls
    )
    assert "paris" in seen, describe(second)
    return (
        f"call={call.name}({call.arguments}) -> "
        f"calls={[(c.name, c.arguments) for c in second.tool_calls]} {describe(second)}"
    )


async def case_action_turn() -> str:
    result = await generate(
        [TOOL_PROMPT],
        types.GenerateContentConfig(
            inference_profile=ACTION_EXECUTING_PROFILE_ID,
            system_instruction="You are an agent. Call tools to do the task.",
            tool_use=LlmActionTurnRequest(
                mode="action_turn", tools=[ECHO_TOOL, FINISH_TOOL]
            ),
        ),
        "smoke-action-turn",
    )
    assert result.action_turn is not None, describe(result)
    return f"action_turn={result.action_turn.model_dump(exclude_none=True)}"


async def case_image(tmp: Path) -> str:
    payload = red_png()
    path = tmp / "red.png"
    path.write_bytes(payload)
    result = await generate(
        [
            "What single color fills this image? Answer with one word.",
            {
                "file_data": {
                    "blob_ref": "smoke_red_png",
                    "application_ref": "tool_attachment:smoke-image",
                    "filename": "red.png",
                    "mime_type": "image/png",
                    "blob_path": str(path),
                    "byte_size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            },
        ],
        types.GenerateContentConfig(inference_profile=ACTIVITY_SUMMARY_PROFILE_ID),
        "smoke-image",
    )
    assert "red" in result.text.lower(), describe(result)
    return describe(result)


async def case_bad_key() -> str:
    set_llm_connection(
        ApiKeyConnection(provider="openai", model=MODEL, api_key="sk-invalid-smoke")
    )
    try:
        await generate(
            ["hello"],
            types.GenerateContentConfig(inference_profile=ACTIVITY_SUMMARY_PROFILE_ID),
            "smoke-bad-key",
        )
    except LlmProxyExecutionError as error:
        details = build_llm_proxy_agent_error(
            exception=error, error_code_prefix="ACTION"
        ).error_details
        assert error.error_code == "PROXY_AUTHENTICATION_FAILED", error.error_code
        assert error.retryable is False
        assert details and details["suggested_action"] == "configure_connection"
        return f"code={error.error_code} action={details['suggested_action']}"
    raise AssertionError("an invalid key was accepted")


async def main() -> int:
    key = os.environ.get("OPENAI_API_KEY", "").strip().strip("'\"")
    if not key:
        print("OPENAI_API_KEY is not set")
        return 2
    register_logged_out_owner(OWNER)
    mark_configured()
    connection = ApiKeyConnection(provider="openai", model=MODEL, api_key=key)
    failures = 0
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        cases = [
            ("text", case_text),
            ("structured", case_structured),
            ("tool_roundtrip", case_tool_roundtrip),
            ("action_turn", case_action_turn),
            ("image", lambda: case_image(tmp)),
            ("bad_key", case_bad_key),
        ]
        for name, run in cases:
            if name != "bad_key":
                set_llm_connection(connection)
            try:
                detail = await run()
                print(f"PASS {name}: {detail}")
            except Exception as error:  # smoke harness: report every failure kind
                failures += 1
                text = "".join(traceback.format_exception(error))
                print(f"FAIL {name}: {text.replace(key, '<redacted>')[-3000:]}")
    print(f"model={MODEL} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
