#!/usr/bin/env python3
"""Deterministic loopback LLM proxy stub for hermetic Electron E2E (dev tool only).

Binds 127.0.0.1 only and serves the LocalLlmProxyClient contract
(POST with an urlencoded/multipart `request` form field carrying the request
JSON; see local_runtime/llm_proxy/client.py). A request that carries file
inputs — a composer image, for instance — arrives as multipart, with one part
per ``blob_ref`` alongside the `request` part. Dispatch is by
`inference_profile`:

- ``action.executing`` (parent Action THINK): replies with the next native
  tool call of the script selected by ``--script``. No ``continuation`` is
  ever returned (the Action THINK request uses continuation_mode=disabled).
- ``action.tool_thinking`` / ``activity_summary`` / ``activity_description``:
  plain-text assistant reply.
- ``memory_update``: HTTP 400 PROXY_INVALID_INPUT (non-retryable) so the
  post-success background job gives up immediately without touching the
  already-terminal Action.
- anything else: HTTP 400 PROXY_INVALID_INPUT, logged as UNHANDLED.

Scripts (one THINK request consumes one step; the counter is per process,
matching the one-Action-per-test E2E harness):

- ``simple``: draft_final_answer -> submit_final_answer.
- ``stall``: eight approval-free list/read steps with a per-THINK delay so a
  test has a wide window to press Stop, then draft/submit as fallback.
- ``approval``: ``bash pwd`` (always approval_pending: the bash capability is
  never granted by default), then draft/submit after the approve/deny resume.
  The draft answer folds the bash outcome observed in the THINK prompt into a
  ``[bash denied=<bool> executed=<bool>]`` marker so the E2E spec can assert
  that approve actually executed pwd and deny actually skipped it.

Every draft answer additionally carries an ``[images ...]`` marker whenever the
THINK request declares image inputs, so an E2E spec can tell "the image reached
the model" apart from "the run succeeded without it".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from pantaray_agents.agents.action_agent.tools.native_tool_use import STEP_NOTE_ARG
from pantaray_llm.contracts.tool_use import LlmToolCall, LlmToolUseResponse

ACTION_EXECUTING_PROFILE = "action.executing"
TEXT_PROFILES = frozenset(
    {"action.tool_thinking", "activity_summary", "activity_description"}
)
MEMORY_UPDATE_PROFILE = "memory_update"
REQUEST_FORM_FIELD = "request"
INPUT_IMAGE_BLOCK_TYPE = "input_image"

FINAL_ANSWER_TEXT = "E2E stub final answer"
STUB_TEXT_REPLY = "E2E stub text reply"
# The stall script sleeps this long before every THINK reply so the Stop test
# has a deterministic multi-second window while the run is visibly running.
STALL_THINK_DELAY_SECONDS = 1.5

type ScriptStep = tuple[str, dict[str, object]]

DRAFT_TOOL_NAME = "draft_final_answer"
# The answer is rebuilt per request by _draft_answer, which appends whatever the
# running script has to make observable to this same base text.
_DRAFT_STEP: ScriptStep = (DRAFT_TOOL_NAME, {"answer": FINAL_ANSWER_TEXT})
_SUBMIT_STEP: ScriptStep = ("submit_final_answer", {})
_STALL_READ_STEPS: list[ScriptStep] = [
    ("list", {"path": "."}),
    ("read", {"path": "."}),
] * 4

SCRIPTS: dict[str, list[ScriptStep]] = {
    "simple": [_DRAFT_STEP, _SUBMIT_STEP],
    "stall": [*_STALL_READ_STEPS, _DRAFT_STEP, _SUBMIT_STEP],
    "approval": [("bash", {"command": "pwd"}), _DRAFT_STEP, _SUBMIT_STEP],
}

SCRIPT_NAME = ""  # set in main()
_think_lock = threading.Lock()
_think_count = 0

# The approval script detects the bash step outcome from the THINK prompt,
# which embeds the tool step history as json.dumps(..., indent=2) blocks
# (formatter_parts/history.py). A denied resume renders
# `"approval_status": "denied"`; a real pwd execution renders an absolute
# path as `"stdout": "/...`. Neither token appears in the static prompt.
APPROVAL_DENIED_TOKEN = '"approval_status": "denied"'
APPROVAL_EXECUTED_TOKEN = '"stdout": "/'


@dataclass(frozen=True, slots=True)
class ProxyRequest:
    """One decoded proxy POST: the `request` JSON plus the parts keyed by blob_ref."""

    request: dict[str, object]
    files: Mapping[str, bytes]


def _parse_form_body(
    *, content_type: str, raw: bytes
) -> tuple[str | None, dict[str, bytes]]:
    """Split a proxy POST body into the `request` field and the attached file parts.

    httpx2 sends urlencoded while nothing is attached and switches to multipart as
    soon as the request carries a file input.
    """
    if "application/x-www-form-urlencoded" in content_type:
        values = parse_qs(raw.decode("utf-8")).get(REQUEST_FORM_FIELD)
        return (values[0] if values else None), {}
    if "multipart/form-data" in content_type:
        return _parse_multipart_body(content_type=content_type, raw=raw)
    return None, {}


def _parse_multipart_body(
    *, content_type: str, raw: bytes
) -> tuple[str | None, dict[str, bytes]]:
    """Read a multipart/form-data body with the stdlib email parser.

    The synthetic Content-Type line is what carries the boundary into the parser.
    File parts have no Content-Transfer-Encoding, so `decode=True` hands back the
    exact bytes that were sent.
    """
    message = BytesParser().parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + raw
    )
    parts = message.get_payload()
    if not isinstance(parts, list):
        return None, {}
    request_field: str | None = None
    files: dict[str, bytes] = {}
    for part in parts:
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if not isinstance(name, str) or not isinstance(payload, bytes):
            continue
        if name == REQUEST_FORM_FIELD:
            request_field = payload.decode("utf-8")
        else:
            files[name] = payload
    return request_field, files


def _image_descriptors(request: dict[str, object]) -> list[dict[str, object]]:
    """Every `input_image` block declared by the request messages."""
    descriptors: list[dict[str, object]] = []
    messages = request.get("messages")
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != INPUT_IMAGE_BLOCK_TYPE:
                continue
            image = block.get("image")
            if isinstance(image, dict):
                descriptors.append(image)
    return descriptors


def _is_image_delivered(
    descriptor: dict[str, object], files: Mapping[str, bytes]
) -> bool:
    blob_ref = descriptor.get("blob_ref")
    if not isinstance(blob_ref, str):
        return False
    payload = files.get(blob_ref)
    if payload is None:
        return False
    if len(payload) != descriptor.get("byte_size"):
        return False
    return hashlib.sha256(payload).hexdigest() == descriptor.get("sha256")


def _image_marker(proxy: ProxyRequest) -> str:
    """Report the image inputs of this request and whether their bytes arrived.

    A dropped image would still produce a successful run, so the final answer alone
    cannot distinguish "the model saw the image" from "the image never left the
    backend". Checking each descriptor against the multipart part it names makes
    that difference observable to an E2E spec.
    """
    descriptors = _image_descriptors(proxy.request)
    if not descriptors:
        return ""
    verified = all(
        _is_image_delivered(descriptor, proxy.files) for descriptor in descriptors
    )
    return f" [images count={len(descriptors)} bytes_verified={str(verified).lower()}]"


def _prompt_text(request: dict[str, object]) -> str:
    """Join every text block in request.messages (system + THINK prompt)."""
    texts: list[str] = []
    messages = request.get("messages")
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(block["text"])
    return "\n".join(texts)


def _bash_outcome_marker(prompt_text: str) -> str:
    """Fold the observed bash outcome into the approval script's final answer."""
    denied = APPROVAL_DENIED_TOKEN in prompt_text
    executed = APPROVAL_EXECUTED_TOKEN in prompt_text
    return f" [bash denied={str(denied).lower()} executed={str(executed).lower()}]"


def _draft_answer(proxy: ProxyRequest) -> str:
    """FINAL_ANSWER_TEXT plus the markers the running script must make observable."""
    answer = FINAL_ANSWER_TEXT
    if SCRIPT_NAME == "approval":
        answer += _bash_outcome_marker(_prompt_text(proxy.request))
    return answer + _image_marker(proxy)


def _next_think_step() -> tuple[int, ScriptStep] | None:
    global _think_count
    with _think_lock:
        index = _think_count
        _think_count += 1
    script = SCRIPTS[SCRIPT_NAME]
    if index >= len(script):
        return None
    return index, script[index]


def _tool_call_body(index: int, step: ScriptStep) -> dict[str, object]:
    """Serialize one native tool call through the shared response contract.

    The stub speaks the same wire shape LocalLlmProxyClient parses back into
    LlmToolUseResponse, so building the payload from that model (instead of a
    hand-written literal) keeps the stub from drifting when the contract changes.
    """
    name, arguments = step
    # Every supervisor tool schema requires a step_note; the scripts stay
    # note-free so the note is injected at the single serialization point.
    call_arguments: dict[str, object] = {
        STEP_NOTE_ARG: f"E2E stub step {index}: calling {name}.",
        **arguments,
    }
    tool_use = LlmToolUseResponse(
        calls=[
            LlmToolCall(call_id=f"stub-{index}", name=name, arguments=call_arguments)
        ]
    )
    return {"output": [], "tool_use": tool_use.model_dump(mode="json")}


def _text_body(text: str) -> dict[str, object]:
    return {
        "output": [
            {
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ]
    }


def _invalid_input_body(message: str) -> dict[str, object]:
    return {"error": {"code": "PROXY_INVALID_INPUT", "message": message, "details": {}}}


class StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PantarayLlmStub/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(
            f"{datetime.now(UTC).isoformat()} {format % args}",
            file=sys.stderr,
            flush=True,
        )

    def _respond(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_proxy_request(self) -> ProxyRequest | None:
        """Decode the POST body into the `request` JSON and its attached parts."""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        request_field, files = _parse_form_body(
            content_type=self.headers.get("Content-Type", ""),
            raw=raw,
        )
        if request_field is None:
            return None
        try:
            parsed = json.loads(request_field)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return ProxyRequest(request=parsed, files=files)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
            return
        self._respond(404, _invalid_input_body(f"no route for GET {self.path}"))

    def do_POST(self) -> None:  # noqa: N802
        proxy = self._read_proxy_request()
        if proxy is None:
            self.log_message("UNHANDLED non-form POST %s", self.path)
            self._respond(400, _invalid_input_body("stub expects a form request"))
            return
        request = proxy.request
        profile = request.get("inference_profile")
        if profile == ACTION_EXECUTING_PROFILE:
            self._respond_think(proxy)
            return
        if profile in TEXT_PROFILES:
            self._respond(200, _text_body(STUB_TEXT_REPLY))
            return
        if profile == MEMORY_UPDATE_PROFILE:
            self._respond(
                400, _invalid_input_body("memory_update is stubbed out in E2E")
            )
            return
        self.log_message("UNHANDLED inference_profile %r", profile)
        self._respond(400, _invalid_input_body(f"unknown profile: {profile}"))

    def _respond_think(self, proxy: ProxyRequest) -> None:
        scripted = _next_think_step()
        if scripted is None:
            self.log_message("UNHANDLED THINK request beyond script %r", SCRIPT_NAME)
            self._respond(400, _invalid_input_body("script is exhausted"))
            return
        index, step = scripted
        if step[0] == DRAFT_TOOL_NAME:
            step = (DRAFT_TOOL_NAME, {"answer": _draft_answer(proxy)})
        if SCRIPT_NAME == "stall":
            time.sleep(STALL_THINK_DELAY_SECONDS)
        self.log_message("THINK %d -> %s %s", index, step[0], json.dumps(step[1]))
        self._respond(200, _tool_call_body(index, step))


def main() -> int:
    global SCRIPT_NAME
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--script", choices=sorted(SCRIPTS), required=True)
    args = parser.parse_args()
    SCRIPT_NAME = args.script
    server = ThreadingHTTPServer(("127.0.0.1", args.port), StubHandler)
    print(
        f"[llm_stub] listening on 127.0.0.1:{args.port} script={args.script}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
