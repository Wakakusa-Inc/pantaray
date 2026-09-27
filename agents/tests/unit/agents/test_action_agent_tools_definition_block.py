from __future__ import annotations

from dataclasses import replace

import pytest
from jsonschema import SchemaError

from pantaray_agents.agents.action_agent.support.formatter import ActionAgentFormatter
from pantaray_agents.agents.action_agent.tools import TOOL_REGISTRY
from pantaray_agents.agents.action_agent.tools.base import (
    FieldSpec,
    InputSpec,
    ToolDefinition,
    ToolGuideSpec,
    ToolSpec,
    VariantSpec,
    tool_execution_policy,
)
from pantaray_agents.agents.action_agent.tools.memory_search_tool import (
    MEMORY_SEARCH_FOCUS_PROMPT_TYPE,
)


def test_tool_definition_rejects_invalid_output_schema_at_construction() -> None:
    with pytest.raises(SchemaError):
        replace(TOOL_REGISTRY["bash"], output_schema={"type": "invalid-type"})


def test_tools_definition_block_includes_guide_and_schema_descriptions() -> None:
    formatter = ActionAgentFormatter(TOOL_REGISTRY)
    block = formatter.build_tools_definition_block()

    # Format anchors
    assert "Tool: " in block
    assert "Description:" in block
    assert "Args schema:" in block
    assert "- args:" in block
    assert "What:" not in block
    assert "When:" in block
    assert "How:" not in block
    assert "Pitfalls:" not in block

    # One known tool should appear
    assert "Tool: Memory Search" in block
    assert "ID: memory_search" in block
    assert "organized stock knowledge" in block
    assert "timestamped flow knowledge" in block
    assert "Search by shared anchors" in block
    assert "focus='stable_knowledge'" in block
    assert "- required query: string" in block
    assert f"- focus: {MEMORY_SEARCH_FOCUS_PROMPT_TYPE}" in block
    assert "- time_hint: object" in block
    assert "Tool: Bash" in block
    assert "ID: bash" in block
    assert "- required command: string" in block
    assert "- cwd: string" in block
    assert "- timeout_ms: integer" not in block
    assert "required order_by: enum['created_at', 'updated_at']" not in block
    assert "- check_item_title:" not in block
    assert "- requirement_id:" not in block
    assert "ID: read" in block
    assert "offset is the 1-based starting line" in block
    assert "continue with offset=next_offset" in block
    assert "never request an offset greater than total_lines" in block
    assert "Use next_offset from a prior read result" in block
    assert "limit is the count of lines to return from that start" in block
    assert "ID: list" in block
    assert "List is not paginated" in block
    assert "do not pass offset" in block
    assert "This is a hard cap, not a page size" in block


def test_tool_prompt_contracts_default_to_multiline_guide_sections() -> None:
    for tool in TOOL_REGISTRY.values():
        description = tool.prompt_contract.description

        assert description.startswith("Purpose:\n"), tool.tool_id
        assert "\n\nWhen:\n" in description, tool.tool_id
        assert "\n\nAvoid:\n" in description, tool.tool_id


def test_tools_definition_block_describes_structured_apply_patch() -> None:
    formatter = ActionAgentFormatter(TOOL_REGISTRY)
    block = formatter.build_tools_definition_block()

    assert "Use changes[] with exactly one add, update, or delete operation" in block
    assert "exactly one edit location" in block
    assert "status=needs_read" in block
    assert "read, grep, and glob tools" in block
    assert "path may be absolute or relative to the current workspace cwd" in block
    assert "before_lines" in block
    assert "old_lines" in block
    assert "new_lines" in block
    assert "after_lines" in block
    assert "<OMITTED>" in block
    assert "nearby location hints" in block
    assert "trailing_newline" in block
    assert "Do not use patch DSL or unified diff text" in block
    assert "*** Begin Patch" not in block


def test_tools_definition_block_explains_edit_command_processing_boundaries() -> None:
    formatter = ActionAgentFormatter(TOOL_REGISTRY)
    block = formatter.build_tools_definition_block()

    assert "Use this to directly create, update, or delete workspace files" in block
    assert (
        "fix and retry apply_patch instead of switching to bash or run_python" in block
    )
    assert "Run workspace scripts, virtual-environment tools" in block
    assert "Pipes, redirections, heredocs, and multiple commands are supported" in block
    assert "commands that write files as their normal side effect" in block
    assert "Use read/apply_patch for normal source inspection and direct file" in block
    assert (
        "Do not use run_python as a fallback to bypass a rejected apply_patch" in block
    )


def test_tools_definition_block_renders_generalized_discriminator_and_variant_metadata() -> (
    None
):
    custom_tool = ToolDefinition.from_spec(
        ToolSpec(
            tool_id="custom_tool",
            name="Custom Tool",
            description="x",
            guide=ToolGuideSpec(what="Tool", when="testing", pitfalls="none"),
            execution_policy=tool_execution_policy(
                intent_class="read_only",
                default_timeout_ms=None,
            ),
            input_spec=InputSpec(
                variants=(
                    VariantSpec(
                        discriminator_field="mode",
                        discriminator_value="fast",
                        fields=(
                            FieldSpec(
                                name="query",
                                schema={"type": "string"},
                                required=True,
                                prompt_type="string",
                                description="Search query.",
                            ),
                            FieldSpec(
                                name="limit",
                                schema={"type": "integer"},
                                required=False,
                                prompt_type="integer",
                                description="Fast mode limit.",
                            ),
                        ),
                    ),
                    VariantSpec(
                        discriminator_field="mode",
                        discriminator_value="slow",
                        fields=(
                            FieldSpec(
                                name="query",
                                schema={"type": "string"},
                                required=True,
                                prompt_type="string",
                                description="Search query.",
                            ),
                            FieldSpec(
                                name="timeout_ms",
                                schema={"type": "integer"},
                                required=False,
                                prompt_type="integer",
                                description="Slow mode timeout.",
                            ),
                        ),
                    ),
                )
            ),
            output_schema={"type": "object", "properties": {}, "required": []},
        )
    )

    formatter = ActionAgentFormatter({"custom_tool": custom_tool})
    block = formatter.build_tools_definition_block()

    assert "mode='fast'" in block
    assert "mode='slow'" in block
    assert "required query: string" in block
    assert "desc: Search query." in block
    assert "- limit: integer" in block
    assert "desc: Fast mode limit." in block
    assert "- timeout_ms: integer" in block
    assert "desc: Slow mode timeout." in block
