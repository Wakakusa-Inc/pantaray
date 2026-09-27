"""The hermetic E2E LLM stub must speak the LocalLlmProxyClient wire contract.

Only the Electron E2E suite (macOS runner, several minutes) drives the stub end
to end, so a native tool-use contract change that leaves the stub behind
otherwise surfaces as opaque "Action execution failed." specs.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from pantaray_agents.agents.action_agent.tools.native_tool_use import split_step_note
from pantaray_agents.local_runtime.llm_proxy.response_parsing import extract_tool_use

STUB_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "dev"
    / "isolated_env"
    / "llm_stub.py"
)


def _load_stub() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e2e_llm_stub", STUB_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses (and anything else that looks a class up by __module__) read
    # sys.modules during class creation, so the module has to be registered
    # before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script_name", ["simple", "stall", "approval"])
def test_stub_script_steps_parse_as_native_tool_calls(script_name: str) -> None:
    stub = _load_stub()
    steps = stub.SCRIPTS[script_name]

    for index, step in enumerate(steps):
        body = stub._tool_call_body(index, step)

        parsed = extract_tool_use(body)
        assert parsed is not None
        assert [call.name for call in parsed.calls] == [step[0]]
        # The supervisor THINK strips the required step_note before dispatch;
        # a stub call without one would loop in the repair path instead.
        note, handler_arguments = split_step_note(parsed.calls[0].arguments)
        assert note
        assert handler_arguments == step[1]
        # Action THINK requests use continuation_mode=disabled, and the client
        # rejects a response that carries continuation state anyway.
        assert parsed.continuation is None
