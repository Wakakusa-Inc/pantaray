from __future__ import annotations

import pytest

from pantaray_agents.utils.structured_artifact_patch import (
    StructuredArtifactPatchError,
    apply_structured_artifact_patch,
    parse_structured_artifact_patch_request,
)


def test_structured_artifact_patch_updates_markdown_bullet_without_prefix_escape() -> (
    None
):
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": "#### Project: Pantaray"},
                        {"op": "remove", "text": "- Current Focus: old"},
                        {"op": "add", "text": "- Current Focus: new"},
                        {"op": "context", "text": "- Project Summary: stable"},
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(
        base_text=(
            "#### Project: Pantaray\n- Current Focus: old\n- Project Summary: stable\n"
        ),
        patch=patch,
    )

    assert updated == (
        "#### Project: Pantaray\n- Current Focus: new\n- Project Summary: stable\n"
    )


def test_structured_artifact_patch_treats_refs_as_plain_text() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": "#### Project"},
                        {
                            "op": "remove",
                            "text": '- Old [[ref:ref_existing note:"evidence"]]',
                        },
                        {
                            "op": "add",
                            "text": '- New [[ref:ref_unknown note:"new evidence"]]',
                        },
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(
        base_text='#### Project\n- Old [[ref:ref_existing note:"evidence"]]\n',
        patch=patch,
    )

    assert updated == '#### Project\n- New [[ref:ref_unknown note:"new evidence"]]\n'


def test_structured_artifact_patch_uses_context_as_nearby_hint() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {
                            "op": "context",
                            "text": "## Interests/Preferences (Inferred from Facts & Context)",
                        },
                        {"op": "remove", "text": "- Manual Synthesis: old"},
                        {"op": "add", "text": "- Manual Synthesis: new"},
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(
        base_text=(
            "## Interests/Preferences (Inferred from Facts & Context)\n"
            "- Tool Preference: keep\n"
            "- Manual Synthesis: old\n"
        ),
        patch=patch,
    )

    assert updated == (
        "## Interests/Preferences (Inferred from Facts & Context)\n"
        "- Tool Preference: keep\n"
        "- Manual Synthesis: new\n"
    )


def test_structured_artifact_patch_allows_omitted_middle_in_remove_line() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": "## Preferences"},
                        {
                            "op": "remove",
                            "text": (
                                "- Manual Synthesis:<OMITTED>"
                                "(Confidence: 0.8 - observed repeatedly)"
                            ),
                        },
                        {"op": "add", "text": "- Manual Synthesis: updated"},
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(
        base_text=(
            "## Preferences\n"
            "- Manual Synthesis: User prefers concrete repo-grounded fixes. "
            "(Confidence: 0.8 - observed repeatedly)\n"
        ),
        patch=patch,
    )

    assert updated == "## Preferences\n- Manual Synthesis: updated\n"


def test_structured_artifact_patch_allows_omitted_middle_in_context_line() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {
                            "op": "context",
                            "text": "- Project Summary:<OMITTED>(Confidence: 0.9)",
                        },
                        {"op": "remove", "text": "- Current Focus: old"},
                        {"op": "add", "text": "- Current Focus: new"},
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(
        base_text=(
            "- Project Summary: Long description with refs. (Confidence: 0.9)\n"
            "- Current Focus: old\n"
        ),
        patch=patch,
    )

    assert updated == (
        "- Project Summary: Long description with refs. (Confidence: 0.9)\n"
        "- Current Focus: new\n"
    )


def test_structured_artifact_patch_treats_omission_marker_as_literal_add_text() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "add", "text": "Literal <OMITTED> marker"},
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(base_text="", patch=patch)

    assert updated == "Literal <OMITTED> marker\n"


def test_structured_artifact_patch_rejects_multiple_omission_markers() -> None:
    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        parse_structured_artifact_patch_request(
            {
                "chunks": [
                    {
                        "lines": [
                            {
                                "op": "remove",
                                "text": "prefix<OMITTED>middle<OMITTED>suffix",
                            },
                            {"op": "add", "text": "replacement"},
                        ]
                    }
                ]
            }
        )

    assert "PATCH_STRUCTURED_INVALID_OMISSION" in str(exc_info.value)
    assert exc_info.value.details["line_index"] == 0


def test_structured_artifact_patch_rejects_empty_omission_prefix_or_suffix() -> None:
    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        parse_structured_artifact_patch_request(
            {
                "chunks": [
                    {
                        "lines": [
                            {"op": "remove", "text": "prefix<OMITTED>"},
                            {"op": "add", "text": "replacement"},
                        ]
                    }
                ]
            }
        )

    assert "PATCH_STRUCTURED_INVALID_OMISSION" in str(exc_info.value)


def test_structured_artifact_patch_rejects_ambiguous_omitted_line() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {
                            "op": "remove",
                            "text": "- Manual Synthesis:<OMITTED>(Confidence: 0.8)",
                        },
                        {"op": "add", "text": "- Manual Synthesis: updated"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        apply_structured_artifact_patch(
            base_text=(
                "- Manual Synthesis: first. (Confidence: 0.8)\n"
                "- Manual Synthesis: second. (Confidence: 0.8)\n"
            ),
            patch=patch,
        )

    assert "PATCH_CONTEXT_AMBIGUOUS" in str(exc_info.value)


def test_structured_artifact_patch_does_not_match_overlapping_omission_parts() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "remove", "text": "abc<OMITTED>bc"},
                        {"op": "add", "text": "replacement"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        apply_structured_artifact_patch(base_text="abc\n", patch=patch)

    assert "PATCH_CONTEXT_NOT_FOUND" in str(exc_info.value)


def test_structured_artifact_patch_rejects_context_hint_too_far_from_remove() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": "## Section"},
                        {"op": "remove", "text": "- Target: old"},
                        {"op": "add", "text": "- Target: new"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        base_text = (
            "## Section\n"
            + "\n".join(f"- filler {i}" for i in range(81))
            + "\n- Target: old\n"
        )
        apply_structured_artifact_patch(
            base_text=base_text,
            patch=patch,
        )

    assert "PATCH_CONTEXT_NOT_FOUND" in str(exc_info.value)


def test_structured_artifact_patch_bounds_repeated_start_candidates() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": ""},
                        {"op": "remove", "text": "- Target: missing"},
                        {"op": "add", "text": "- Target: new"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        apply_structured_artifact_patch(
            base_text=("\n".join("" for _ in range(50)) + "\n"),
            patch=patch,
        )

    assert "PATCH_CONTEXT_NOT_FOUND" in str(exc_info.value)


def test_structured_artifact_patch_reports_missing_current_document_line() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": "#### Project: Pantaray"},
                        {"op": "remove", "text": "- Current Focus: missing"},
                        {"op": "add", "text": "- Current Focus: new"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        apply_structured_artifact_patch(
            base_text="#### Project: Pantaray\n- Current Focus: old\n",
            patch=patch,
        )

    assert "PATCH_CONTEXT_NOT_FOUND" in str(exc_info.value)
    assert exc_info.value.details["chunk_index"] == 0
    assert exc_info.value.details["line_index"] == 1
    assert exc_info.value.details["op"] == "remove"
    assert exc_info.value.details["text"] == "- Current Focus: missing"


def test_structured_artifact_patch_reports_original_line_index_after_add_line() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "context", "text": "#### Project: Pantaray"},
                        {"op": "add", "text": "- Current Focus: new"},
                        {"op": "remove", "text": "- Current Focus: missing"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        apply_structured_artifact_patch(
            base_text="#### Project: Pantaray\n- Current Focus: old\n",
            patch=patch,
        )

    assert exc_info.value.details["line_index"] == 2


def test_structured_artifact_patch_allows_insertion_only_for_empty_document() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "add", "text": "# Structured Facts"},
                        {"op": "add", "text": ""},
                        {"op": "add", "text": "- First fact"},
                    ]
                }
            ]
        }
    )

    updated = apply_structured_artifact_patch(base_text="", patch=patch)

    assert updated == "# Structured Facts\n\n- First fact\n"


def test_structured_artifact_patch_rejects_ambiguous_context() -> None:
    patch = parse_structured_artifact_patch_request(
        {
            "chunks": [
                {
                    "lines": [
                        {"op": "remove", "text": "- Status: old"},
                        {"op": "add", "text": "- Status: new"},
                    ]
                }
            ]
        }
    )

    with pytest.raises(StructuredArtifactPatchError) as exc_info:
        apply_structured_artifact_patch(
            base_text="- Status: old\n- Other\n- Status: old\n",
            patch=patch,
        )

    assert "PATCH_CONTEXT_AMBIGUOUS" in str(exc_info.value)
    assert exc_info.value.details["chunk_index"] == 0
