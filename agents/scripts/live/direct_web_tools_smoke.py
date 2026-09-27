"""Live smoke of the direct web-tools route against the real Tavily API.

Reads TAVILY_API_KEY from the environment and never prints it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

from pantaray_agents.local_runtime.runtime.connection_store import (
    WebSearchCredential,
    set_web_search_credential,
)
from pantaray_agents.local_runtime.runtime.identity import register_logged_out_owner
from pantaray_agents.local_runtime.runtime.session_store import mark_configured
from pantaray_agents.local_runtime.web_tools.client import (
    WebContentExecutionError,
    invoke_web_tools_wrapper,
)
from pantaray_llm.web_tools.profiles import (
    WEB_EXTRACT_PROFILE_ID,
    WEB_SEARCH_PROFILE_ID,
)

OWNER = "live-smoke-owner"


async def call(tool_id: str, profile: str, args: dict[str, object]):
    return await invoke_web_tools_wrapper(
        tool_id=tool_id,
        web_tool_profile=profile,
        args=args,
        context={"user_id": OWNER, "request_id": f"smoke-{tool_id}"},
        max_retries=1,
    )


async def main() -> int:
    key = os.environ.get("TAVILY_API_KEY", "").strip().strip("'\"")
    if not key:
        print("TAVILY_API_KEY is not set")
        return 2
    register_logged_out_owner(OWNER)
    mark_configured()
    failures = 0
    cases = [
        (
            "web_search",
            WEB_SEARCH_PROFILE_ID,
            {"query": "Python programming language official site"},
            key,
        ),
        (
            "web_extract",
            WEB_EXTRACT_PROFILE_ID,
            {"urls": ["https://www.python.org/"]},
            key,
        ),
        ("web_search", WEB_SEARCH_PROFILE_ID, {"query": "hello"}, "tvly-invalid-smoke"),
    ]
    for tool_id, profile, args, use_key in cases:
        set_web_search_credential(WebSearchCredential(api_key=use_key))
        label = tool_id if use_key == key else f"{tool_id}(bad key)"
        try:
            response = await call(tool_id, profile, args)
            result = response.get("result") or {}
            summary = {
                k: (len(v) if isinstance(v, list) else type(v).__name__)
                for k, v in result.items()
            }
            ok = response["status"] == "success" and use_key == key
            print(
                f"{'PASS' if ok else 'FAIL'} {label}: status={response['status']} result_keys={summary} error={response.get('error')}"
            )
            failures += 0 if ok else 1
        except WebContentExecutionError as error:
            expected = use_key != key
            action = getattr(error, "suggested_action", None)
            ok = (
                expected
                and error.error_code == "PROXY_AUTHENTICATION_FAILED"
                and action == "configure_connection"
            )
            print(
                f"{'PASS' if ok else 'FAIL'} {label}: code={error.error_code} retryable={error.retryable} action={action}"
            )
            failures += 0 if ok else 1
        except Exception as error:  # smoke harness: report every failure kind
            failures += 1
            print(
                f"FAIL {label}: {''.join(traceback.format_exception(error)).replace(key, '<redacted>')[-1500:]}"
            )
    print(f"failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
