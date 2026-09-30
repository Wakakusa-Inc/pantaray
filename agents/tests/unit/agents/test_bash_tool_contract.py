from __future__ import annotations

from pantaray_agents.agents.action_agent.tools import (
    BASH_TOOL,
    GLOB_TOOL,
    GREP_TOOL,
    LIST_TOOL,
    SUPERVISOR_SINGLE_REACT_TOOL_IDS,
    TOOL_REGISTRY,
)


def _field_description(field_name: str) -> str:
    for field in BASH_TOOL.prompt_contract.args:
        if field.name == field_name:
            return field.description
    raise AssertionError(f"missing field: {field_name}")


def _tool_field_description(tool_id: str, field_name: str) -> str:
    tool = TOOL_REGISTRY[tool_id]
    for field in tool.prompt_contract.args:
        if field.name == field_name:
            return field.description
    raise AssertionError(f"missing field: {tool_id}.{field_name}")


def test_bash_tool_contract_explains_shell_scope_and_lifetime() -> None:
    command_description = _field_description("command")
    cwd_description = _field_description("cwd")
    combined = "\n".join(
        [
            BASH_TOOL.description,
            BASH_TOOL.guide.what,
            BASH_TOOL.guide.when,
            BASH_TOOL.guide.pitfalls,
            command_description,
            cwd_description,
        ]
    )

    assert "non-interactive shell command or script" in combined
    assert "Pipes, redirections, heredocs" in command_description
    assert "environment assignments" in command_description
    assert "Set cwd to a workspace path" in cwd_description
    assert "path arguments are relative to cwd" in combined
    assert (
        "Direct file content edits should normally go through apply_patch" in combined
    )
    assert "HOME unless use_login_environment is set, are temporary" in combined
    assert "user's command network setting" in combined
    assert "finite execution timeout" in combined
    assert "Shell startup files are not loaded" in combined


def test_discovery_tool_contracts_explain_read_scope_path_semantics() -> None:
    assert "local" in LIST_TOOL.prompt_contract.description
    assert "local" in GLOB_TOOL.prompt_contract.description
    assert "local" in GREP_TOOL.prompt_contract.description
    assert [arg.name for arg in LIST_TOOL.prompt_contract.args] == [
        "path",
        "max_depth",
        "limit",
    ]
    assert [arg.name for arg in GLOB_TOOL.prompt_contract.args] == [
        "base_path",
        "pattern",
        "limit",
    ]
    assert [arg.name for arg in GREP_TOOL.prompt_contract.args] == [
        "base_path",
        "pattern",
        "include_glob",
        "max_matches",
    ]
    discovery_guides = "\n".join(
        [
            LIST_TOOL.guide.pitfalls,
            GLOB_TOOL.guide.pitfalls,
            GREP_TOOL.guide.pitfalls,
        ]
    )
    assert "local path" in discovery_guides
    assert "Workspace Path Rules" in discovery_guides
    assert "Read/search access" in discovery_guides
    assert "Relative paths" in discovery_guides
    assert "truncated=true" in discovery_guides
    assert "truncation_reason" in discovery_guides
    assert "retry_hint" in discovery_guides
    assert "warning" in discovery_guides
    assert "next_action_hint" not in discovery_guides
    list_contract = "\n".join(
        [
            LIST_TOOL.guide.pitfalls,
            _tool_field_description("list", "max_depth"),
            _tool_field_description("list", "limit"),
        ]
    )
    assert "List is not paginated" in list_contract
    assert "do not pass offset" in list_contract
    assert "do not expect next_offset" in list_contract
    assert "1-500" in list_contract
    assert "not a page size" in list_contract
    assert "narrower path or smaller max_depth" in list_contract
    assert "literal text" in GREP_TOOL.guide.pitfalls
    assert "include_glob" in GREP_TOOL.guide.pitfalls


def test_discovery_tools_are_local_parent_tools() -> None:
    for tool in (LIST_TOOL, GLOB_TOOL, GREP_TOOL):
        assert TOOL_REGISTRY[tool.tool_id] is tool
        assert tool.tool_id in SUPERVISOR_SINGLE_REACT_TOOL_IDS


def test_command_tools_ask_for_outside_write_folders_with_a_user_facing_reason() -> (
    None
):
    # The model sees the tool description, not per-field descriptions.
    description = BASH_TOOL.prompt_contract.description
    assert (
        "Give justification whenever you set use_login_environment or "
        "additional_write_folders" in description
    )
    assert "Do not ask the user in chat first" in description
    assert "language of the user's request" in description
    assert "naming only the service the command actually uses" in description
    assert "Do not include command names, paths, or file names" in description
    assert (
        "additional_write_folders and justification exactly as the bash tool"
        in TOOL_REGISTRY["run_python"].prompt_contract.description
    )
    assert "approved cwd" not in _field_description("use_login_environment")
