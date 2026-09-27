from __future__ import annotations

import pytest

import pantaray_llm.providers.schema_compiler as schema_compiler_module
from pantaray_agents.agents.action_agent.tools import (
    TOOL_REGISTRY,
    build_native_action_tools,
)
from pantaray_agents.schema.agent.base import JSONValue
from pantaray_llm.providers.schema_compiler import (
    MAX_PROVIDER_SCHEMA_DEPTH,
    MAX_PROVIDER_SCHEMA_NODES,
    MAX_PROVIDER_SCHEMA_ONE_OF_BRANCHES,
    ProviderSchemaCompilationError,
    ProviderSchemaDecodeError,
    compile_provider_schema,
)


def test_openai_compiler_preserves_canonical_constraints() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 20,
                    "pattern": "^[a-z]+$",
                },
                "score": {"type": "number", "minimum": 0, "maximum": 1},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "integer"},
                },
            },
            "additionalProperties": False,
        },
        usage="structured_output",
    )

    properties = compiled.wire_schema["properties"]
    assert isinstance(properties, dict)
    assert properties["name"] == {
        "anyOf": [
            {
                "type": "string",
                "minLength": 2,
                "maxLength": 20,
                "pattern": "^[a-z]+$",
            },
            {"type": "null"},
        ]
    }
    assert properties["score"] == {
        "anyOf": [
            {"type": "number", "minimum": 0, "maximum": 1},
            {"type": "null"},
        ]
    }
    assert properties["items"] == {
        "anyOf": [
            {
                "type": "array",
                "minItems": 1,
                "items": {"type": "integer"},
            },
            {"type": "null"},
        ]
    }


def test_openai_decoder_restores_nested_optional_omissions() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "required": ["rows"],
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {
                            "id": {"type": "integer"},
                            "note": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                }
            },
            "additionalProperties": False,
        },
        usage="structured_output",
    )

    assert compiled.decode(
        {"rows": [{"id": 1, "note": None}, {"id": 2, "note": "kept"}]}
    ) == {"rows": [{"id": 1}, {"id": 2, "note": "kept"}]}


def test_compiler_converts_const_and_disjoint_one_of() -> None:
    canonical = {
        "type": "object",
        "required": ["decision"],
        "properties": {
            "decision": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["kind"],
                        "properties": {"kind": {"const": "continue"}},
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "required": ["kind"],
                        "properties": {"kind": {"const": "complete"}},
                        "additionalProperties": False,
                    },
                ]
            }
        },
        "additionalProperties": False,
    }

    compiled = compile_provider_schema(
        schema=canonical,
        usage="structured_output",
    )
    properties = compiled.wire_schema["properties"]
    assert isinstance(properties, dict)
    decision = properties["decision"]
    assert isinstance(decision, dict)
    assert "oneOf" not in decision
    assert decision["anyOf"][0]["properties"]["kind"]["enum"] == ["continue"]


def test_compiler_rejects_nested_one_of_with_sibling_any_of() -> None:
    with pytest.raises(
        ProviderSchemaCompilationError,
        match="cannot preserve sibling keyword anyOf",
    ) as exc_info:
        compile_provider_schema(
            schema={
                "type": "object",
                "properties": {
                    "value": {
                        "oneOf": [{"type": "string"}, {"type": "number"}],
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                    }
                },
                "additionalProperties": False,
            },
            usage="structured_output",
        )

    assert exc_info.value.path == "$.properties.value.anyOf"
    assert exc_info.value.keyword == "anyOf"


def test_compiler_rejects_const_outside_sibling_enum() -> None:
    with pytest.raises(
        ProviderSchemaCompilationError,
        match="const value is not present in sibling enum",
    ) as exc_info:
        compile_provider_schema(
            schema={
                "type": "object",
                "properties": {"status": {"const": True, "enum": [1]}},
                "additionalProperties": False,
            },
            usage="structured_output",
        )

    assert exc_info.value.path == "$.properties.status.enum"
    assert exc_info.value.keyword == "enum"


def test_compiler_rejects_ambiguous_one_of() -> None:
    with pytest.raises(ProviderSchemaCompilationError, match="not provably disjoint"):
        compile_provider_schema(
            schema={
                "type": "object",
                "properties": {
                    "value": {
                        "oneOf": [
                            {"type": "number", "minimum": 0},
                            {"type": "number", "maximum": 10},
                        ]
                    }
                },
                "additionalProperties": False,
            },
            usage="structured_output",
        )


def test_compiler_rejects_integer_number_one_of_as_overlapping() -> None:
    with pytest.raises(ProviderSchemaCompilationError, match="not provably disjoint"):
        compile_provider_schema(
            schema={
                "type": "object",
                "properties": {
                    "value": {
                        "oneOf": [
                            {"type": "integer"},
                            {"type": "number"},
                        ]
                    }
                },
                "additionalProperties": False,
            },
            usage="structured_output",
        )


def test_compiler_preserves_disjoint_string_number_one_of() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "properties": {
                "value": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "number"},
                    ]
                }
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        usage="structured_output",
    )

    properties = compiled.wire_schema["properties"]
    assert isinstance(properties, dict)
    assert properties["value"] == {"anyOf": [{"type": "string"}, {"type": "number"}]}


def test_compiler_rejects_oversized_one_of_before_pairwise_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_pairwise_check(_branches: list[JSONValue]) -> bool:
        raise AssertionError("pairwise check must not run for an oversized oneOf")

    monkeypatch.setattr(
        schema_compiler_module,
        "_branches_are_pairwise_disjoint",
        fail_pairwise_check,
    )
    branches: list[JSONValue] = [
        {"const": index} for index in range(MAX_PROVIDER_SCHEMA_ONE_OF_BRANCHES + 1)
    ]

    with pytest.raises(ProviderSchemaCompilationError) as exc_info:
        compile_provider_schema(
            schema={"oneOf": branches},
            usage="structured_output",
        )

    assert exc_info.value.path == "$.oneOf"
    assert exc_info.value.keyword == "oneOf"
    assert str(MAX_PROVIDER_SCHEMA_ONE_OF_BRANCHES) in str(exc_info.value)


def test_compiler_rejects_schema_over_node_limit() -> None:
    with pytest.raises(ProviderSchemaCompilationError, match="node count"):
        compile_provider_schema(
            schema={
                "enum": [str(index) for index in range(MAX_PROVIDER_SCHEMA_NODES + 1)]
            },
            usage="structured_output",
        )


def test_compiler_rejects_schema_over_depth_limit() -> None:
    schema: dict[str, JSONValue] = {"type": "string"}
    for _ in range(MAX_PROVIDER_SCHEMA_DEPTH):
        schema = {"type": "array", "items": schema}

    with pytest.raises(ProviderSchemaCompilationError, match="maximum depth"):
        compile_provider_schema(
            schema=schema,
            usage="structured_output",
        )


def test_schema_complexity_validation_preserves_normal_schema() -> None:
    canonical: dict[str, JSONValue] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }

    compiled = compile_provider_schema(
        schema=canonical,
        usage="structured_output",
    )

    assert compiled.canonical_schema is canonical
    assert compiled.wire_schema == canonical


def test_openai_compiler_rejects_unrepresentable_keyword() -> None:
    with pytest.raises(ProviderSchemaCompilationError) as exc_info:
        compile_provider_schema(
            schema={
                "type": "object",
                "allOf": [{"properties": {"name": {"type": "string"}}}],
            },
            usage="structured_output",
        )

    assert exc_info.value.keyword == "allOf"
    assert exc_info.value.path == "$"


def test_decoder_enforces_canonical_schema_after_provider_decoding() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "required": ["score"],
            "properties": {"score": {"type": "integer", "minimum": 1}},
            "additionalProperties": False,
        },
        usage="structured_output",
    )

    with pytest.raises(ProviderSchemaDecodeError) as exc_info:
        compiled.decode({"score": 0})

    assert exc_info.value.path == "score"
    assert exc_info.value.keyword == "minimum"


def test_openai_compiler_flattens_root_discriminated_union() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "oneOf": [
                {
                    "type": "object",
                    "required": ["kind", "query"],
                    "properties": {
                        "kind": {"const": "search"},
                        "query": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": ["kind", "path"],
                    "properties": {
                        "kind": {"const": "read"},
                        "path": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ],
        },
        usage="tool_parameters",
    )

    assert "anyOf" not in compiled.wire_schema
    assert "oneOf" not in compiled.wire_schema
    assert compiled.wire_schema["additionalProperties"] is False
    assert compiled.wire_schema["required"] == ["kind", "query", "path"]
    assert compiled.post_validation_keywords == ("oneOf",)
    assert compiled.decode({"kind": "search", "query": "term", "path": None}) == {
        "kind": "search",
        "query": "term",
    }


def test_openai_compiler_rejects_root_union_siblings_it_cannot_preserve() -> None:
    with pytest.raises(ProviderSchemaCompilationError) as exc_info:
        compile_provider_schema(
            schema={
                "type": "object",
                "properties": {"tenant": {"type": "string"}},
                "required": ["tenant"],
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {"kind": {"const": "search"}},
                        "required": ["kind"],
                    },
                    {
                        "type": "object",
                        "properties": {"kind": {"const": "read"}},
                        "required": ["kind"],
                    },
                ],
            },
            usage="tool_parameters",
        )

    assert exc_info.value.path == "$.properties"
    assert exc_info.value.keyword == "properties"


def test_openai_compiler_rejects_free_form_object() -> None:
    with pytest.raises(ProviderSchemaCompilationError) as exc_info:
        compile_provider_schema(
            schema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "object",
                        "additionalProperties": True,
                    }
                },
                "additionalProperties": False,
            },
            usage="tool_parameters",
        )

    assert exc_info.value.path == "$.properties.context"
    assert exc_info.value.keyword == "properties"


def test_openai_compiler_strips_unique_items_and_unsupported_format() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "required": ["refs", "url", "center"],
            "properties": {
                "refs": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "url": {"type": "string", "minLength": 1, "format": "uri"},
                "center": {"type": "string", "format": "date-time"},
            },
            "additionalProperties": False,
        },
        usage="tool_parameters",
    )

    properties = compiled.wire_schema["properties"]
    assert isinstance(properties, dict)
    assert properties["refs"] == {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "minLength": 1},
    }
    assert properties["url"] == {"type": "string", "minLength": 1}
    assert properties["center"] == {"type": "string", "format": "date-time"}

    with pytest.raises(ProviderSchemaDecodeError) as exc_info:
        compiled.decode({"refs": ["a", "a"], "url": "https://x.test", "center": "now"})
    assert exc_info.value.keyword == "uniqueItems"


def test_openai_compiler_keeps_properties_named_after_stripped_keywords() -> None:
    compiled = compile_provider_schema(
        schema={
            "type": "object",
            "required": ["format", "contains"],
            "properties": {
                "format": {"type": "string"},
                "contains": {"type": "string"},
            },
            "additionalProperties": False,
        },
        usage="tool_parameters",
    )

    assert compiled.wire_schema["properties"] == {
        "format": {"type": "string"},
        "contains": {"type": "string"},
    }


# Independent copy of the OpenAI strict-validator constraints so the sweep does
# not trust the compiler's own constants.
_OPENAI_REJECTED_WIRE_KEYWORDS = frozenset(
    {
        "allOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
        "additionalItems",
        "contains",
        "maxContains",
        "maxProperties",
        "minContains",
        "minProperties",
        "patternProperties",
        "propertyNames",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
    }
)
_OPENAI_VALID_WIRE_FORMATS = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "ipv4",
        "ipv6",
        "uuid",
    }
)


def _assert_openai_wire_node(node: JSONValue, path: str) -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            _assert_openai_wire_node(item, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return
    for key, item in node.items():
        assert key not in _OPENAI_REJECTED_WIRE_KEYWORDS, f"{path}.{key}"
        if key == "format":
            assert item in _OPENAI_VALID_WIRE_FORMATS, f"{path}.format={item!r}"
        if key == "properties" and isinstance(item, dict):
            for name, subschema in item.items():
                _assert_openai_wire_node(subschema, f"{path}.properties.{name}")
        else:
            _assert_openai_wire_node(item, f"{path}.{key}")


def test_all_action_native_tool_schemas_compile_for_openai() -> None:
    tools = build_native_action_tools(TOOL_REGISTRY)

    for tool in tools:
        compiled = compile_provider_schema(
            schema=tool.parameters,
            usage="tool_parameters",
        )
        _assert_openai_wire_node(compiled.wire_schema, f"$.{tool.name}")
