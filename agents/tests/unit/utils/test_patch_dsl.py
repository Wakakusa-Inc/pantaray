from __future__ import annotations

import pytest

from pantaray_agents.utils.patch_dsl import (
    PatchContextAmbiguousError,
    PatchContextNotFoundError,
    PatchDslError,
    PatchDslPathError,
    PatchOperation,
    apply_patch_dsl_to_text,
    derive_file_changes,
    extract_patch_dsl_paths,
    has_patch_dsl_markers,
    is_patch_dsl,
    parse_patch_dsl,
)


def test_patch_dsl_updates_markdown_bullets_without_unified_hunk_counts() -> None:
    base = "\n".join(
        [
            "# Structured Facts",
            "",
            "#### Design System",
            "- **Audit**: Old audit.",
            "",
        ]
    )
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: structured_facts.md",
            "@@",
            " #### Design System",
            "-- **Audit**: Old audit.",
            "+- **Audit**: Conducted a comprehensive audit.",
            "*** End Patch",
        ]
    )

    result = apply_patch_dsl_to_text(
        base_text=base,
        patch_text=patch_text,
        expected_path="structured_facts.md",
    )

    assert result.updated_text == "\n".join(
        [
            "# Structured Facts",
            "",
            "#### Design System",
            "- **Audit**: Conducted a comprehensive audit.",
            "",
        ]
    )


def test_patch_dsl_rejects_ambiguous_context() -> None:
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: long_term.md",
            "@@",
            " repeated",
            "+inserted",
            "*** End Patch",
        ]
    )

    with pytest.raises(PatchContextAmbiguousError):
        apply_patch_dsl_to_text(
            base_text="repeated\nx\nrepeated\n",
            patch_text=patch_text,
            expected_path="long_term.md",
        )


def test_patch_dsl_rejects_missing_context() -> None:
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: long_term.md",
            "@@",
            "-missing",
            "+replacement",
            "*** End Patch",
        ]
    )

    with pytest.raises(PatchContextNotFoundError):
        apply_patch_dsl_to_text(
            base_text="current\n",
            patch_text=patch_text,
            expected_path="long_term.md",
        )


def test_patch_dsl_rejects_wrong_artifact_path() -> None:
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: other.md",
            "@@",
            "-old",
            "+new",
            "*** End Patch",
        ]
    )

    with pytest.raises(PatchDslPathError):
        apply_patch_dsl_to_text(
            base_text="old\n",
            patch_text=patch_text,
            expected_path="long_term.md",
        )


def test_patch_dsl_extracts_paths_for_workspace_apply_patch() -> None:
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: /Users/example/project/new.txt",
            "+new",
            "*** Update File: /Users/example/project/src/app.py",
            "@@",
            "-old",
            "+new",
            "*** Delete File: obsolete.txt",
            "*** End Patch",
        ]
    )

    assert extract_patch_dsl_paths(patch_text) == (
        "/Users/example/project/new.txt",
        "/Users/example/project/src/app.py",
        "obsolete.txt",
    )


def test_patch_dsl_derives_workspace_add_update_delete_and_move() -> None:
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: new.txt",
            "+new",
            "*** Update File: old.txt",
            "*** Move to: moved.txt",
            "@@",
            "-old",
            "+updated",
            "*** Delete File: stale.txt",
            "*** End Patch",
        ]
    )
    documents = {
        "old.txt": "old\n",
        "stale.txt": "delete me\n",
    }

    changes = derive_file_changes(parse_patch_dsl(patch_text), documents)

    assert [
        (change.operation, change.path, change.move_path) for change in changes
    ] == [
        (PatchOperation.ADD, "new.txt", None),
        (PatchOperation.MOVE, "old.txt", "moved.txt"),
        (PatchOperation.DELETE, "stale.txt", None),
    ]
    assert changes[0].new_text == "new\n"
    assert changes[1].new_text == "updated\n"
    assert changes[2].new_text == ""


@pytest.mark.parametrize("patch_text", ["", "   ", "\n\n"])
def test_is_patch_dsl_is_false_for_blank_text(patch_text: str) -> None:
    assert is_patch_dsl(patch_text) is False


def test_patch_dsl_markers_detect_malformed_envelope() -> None:
    assert has_patch_dsl_markers(
        "\n".join(
            [
                "*** Begin Patch ***",
                "*** Add File: todo.md",
                "+new",
                "*** End Patch ***",
            ]
        )
    )
    assert not has_patch_dsl_markers(
        "--- todo.md\n+++ todo.md\n@@ -1 +1 @@\n-old\n+new\n"
    )


@pytest.mark.parametrize(
    "patch_text",
    [
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: a.txt",
                "@@",
                "-old",
                "+new",
                "*** Update File: a.txt",
                "@@",
                "-new",
                "+newer",
                "*** End Patch",
            ]
        ),
        "\n".join(
            [
                "*** Begin Patch",
                "*** Delete File: a.txt",
                "*** Update File: a.txt",
                "@@",
                "-old",
                "+new",
                "*** End Patch",
            ]
        ),
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: a.txt",
                "*** Move to: b.txt",
                "@@",
                "-old",
                "+new",
                "*** Add File: b.txt",
                "+created",
                "*** End Patch",
            ]
        ),
    ],
)
def test_patch_dsl_rejects_conflicting_paths_in_one_patch(patch_text: str) -> None:
    with pytest.raises(PatchDslError, match="PATCH_DSL_PATH_CONFLICT"):
        derive_file_changes(parse_patch_dsl(patch_text), {"a.txt": "old\n"})


def test_patch_dsl_error_exposes_machine_readable_code() -> None:
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: missing.txt",
            "@@",
            "-old",
            "+new",
            "*** End Patch",
        ]
    )

    with pytest.raises(PatchDslError) as exc_info:
        derive_file_changes(parse_patch_dsl(patch_text), {})

    assert exc_info.value.code == "PATCH_DSL_TARGET_MISSING"
