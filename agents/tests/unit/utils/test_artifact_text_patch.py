from __future__ import annotations

import pytest

from pantaray_agents.utils.artifact_text_patch import (
    ArtifactPatchApplyError,
    ArtifactPatchFormatError,
    ArtifactPatchPathError,
    ArtifactPatchTarget,
    apply_artifact_text_patch,
)


def test_applies_create_patch_to_empty_artifact() -> None:
    result = apply_artifact_text_patch(
        target=ArtifactPatchTarget(
            logical_path="structured_facts.md",
            base_text="",
        ),
        patch_text="\n".join(
            [
                "--- structured_facts.md",
                "+++ structured_facts.md",
                "@@ -0,0 +1,4 @@",
                "+# Structured Facts",
                "+",
                "+## Organization: Pantaray",
                "+- Initial fact.",
            ]
        ),
    )

    assert result.updated_text == (
        "# Structured Facts\n\n## Organization: Pantaray\n- Initial fact.\n"
    )


def test_applies_multiple_hunks_to_single_artifact() -> None:
    base_text = "\n".join(
        [
            "# Structured Facts",
            "",
            "## Organization: Pantaray",
            "Old status.",
            "",
            "## Organization: Individual",
            "Old note.",
            "",
        ]
    )

    result = apply_artifact_text_patch(
        target=ArtifactPatchTarget(
            logical_path="structured_facts.md",
            base_text=base_text,
        ),
        patch_text="\n".join(
            [
                "--- a/structured_facts.md",
                "+++ b/structured_facts.md",
                "@@ -3,3 +3,3 @@",
                " ## Organization: Pantaray",
                "-Old status.",
                "+New status.",
                " ",
                "@@ -6,3 +6,3 @@",
                " ## Organization: Individual",
                "-Old note.",
                "+New note.",
                " ",
            ]
        ),
    )

    assert "New status." in result.updated_text
    assert "New note." in result.updated_text
    assert "Old status." not in result.updated_text
    assert "Old note." not in result.updated_text


def test_applies_patch_to_artifact_without_trailing_newline() -> None:
    result = apply_artifact_text_patch(
        target=ArtifactPatchTarget(
            logical_path="long_term.md",
            base_text="Existing insight data.",
        ),
        patch_text="\n".join(
            [
                "--- a/long_term.md",
                "+++ b/long_term.md",
                "@@ -1 +1 @@",
                "-Existing insight data.",
                "\\ No newline at end of file",
                "+Updated insight data",
                "\\ No newline at end of file",
            ]
        ),
    )

    assert result.updated_text == "Updated insight data"


def test_applies_patch_when_hunk_lines_look_like_file_headers() -> None:
    result = apply_artifact_text_patch(
        target=ArtifactPatchTarget(
            logical_path="structured_facts.md",
            base_text="-- old section\n",
        ),
        patch_text="\n".join(
            [
                "--- structured_facts.md",
                "+++ structured_facts.md",
                "@@ -1 +1 @@",
                "--- old section",
                "+++ new section",
            ]
        ),
    )

    assert result.updated_text == "++ new section\n"


def test_rejects_raw_markdown_without_hunk_with_actionable_message() -> None:
    with pytest.raises(ArtifactPatchFormatError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="",
            ),
            patch_text="# Structured Facts\n\n## Organization: Pantaray\n",
        )

    message = str(exc_info.value)
    assert "PATCH_FORMAT_MISSING_HEADER" in message
    assert "*** Begin Patch" in message
    assert "*** Update File: structured_facts.md" in message
    assert "--- structured_facts.md" not in message


def test_rejects_patch_without_hunk_with_actionable_message() -> None:
    with pytest.raises(ArtifactPatchFormatError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="",
            ),
            patch_text="\n".join(
                [
                    "--- structured_facts.md",
                    "+++ structured_facts.md",
                    "+# Structured Facts",
                ]
            ),
        )

    message = str(exc_info.value)
    assert "PATCH_FORMAT_MISSING_HUNK" in message
    assert "@@" in message
    assert "*** Update File: structured_facts.md" in message


def test_rejects_malformed_patch_dsl_without_unified_diff_guidance() -> None:
    with pytest.raises(ArtifactPatchFormatError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="old\n",
            ),
            patch_text="\n".join(
                [
                    "note before patch",
                    "*** Begin Patch",
                    "*** Update File: structured_facts.md",
                    "@@",
                    "-old",
                    "+new",
                    "*** End Patch",
                ]
            ),
        )

    message = str(exc_info.value)
    assert "PATCH_DSL_ENVELOPE_ERROR" in message
    assert "*** Begin Patch" in message
    assert "*** Update File: structured_facts.md" in message
    assert "--- structured_facts.md" not in message


def test_rejects_wrong_target_path() -> None:
    with pytest.raises(ArtifactPatchPathError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="",
            ),
            patch_text="\n".join(
                [
                    "--- facts.md",
                    "+++ facts.md",
                    "@@ -0,0 +1 @@",
                    "+# Facts",
                ]
            ),
        )

    message = str(exc_info.value)
    assert "PATCH_PATH_MISMATCH" in message
    assert "structured_facts.md" in message


def test_rejects_artifact_header_with_space_suffix_as_wrong_path() -> None:
    with pytest.raises(ArtifactPatchPathError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="old\n",
            ),
            patch_text="\n".join(
                [
                    "--- structured_facts.md extra",
                    "+++ structured_facts.md extra",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                ]
            ),
        )

    assert "PATCH_PATH_MISMATCH" in str(exc_info.value)


@pytest.mark.parametrize(
    "old_header,new_header",
    [
        ("/dev/null", "structured_facts.md"),
        ("structured_facts.md", "/dev/null"),
        ("/dev/null", "/dev/null"),
    ],
)
def test_rejects_dev_null_headers_for_artifacts(
    old_header: str,
    new_header: str,
) -> None:
    with pytest.raises(ArtifactPatchPathError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="existing\n",
            ),
            patch_text="\n".join(
                [
                    f"--- {old_header}",
                    f"+++ {new_header}",
                    "@@ -1 +1 @@",
                    "-existing",
                    "+updated",
                ]
            ),
        )

    assert "PATCH_PATH_DEV_NULL_UNSUPPORTED" in str(exc_info.value)


def test_rejects_patch_apply_failure_with_patch_stderr() -> None:
    with pytest.raises(ArtifactPatchApplyError) as exc_info:
        apply_artifact_text_patch(
            target=ArtifactPatchTarget(
                logical_path="structured_facts.md",
                base_text="old\n",
            ),
            patch_text="\n".join(
                [
                    "--- structured_facts.md",
                    "+++ structured_facts.md",
                    "@@ -1 +1 @@",
                    "-missing",
                    "+new",
                ]
            ),
        )

    message = str(exc_info.value)
    assert "PATCH_APPLY_REJECTED" in message
    assert "structured_facts.md" in message
    assert "*** Begin Patch" in message
    assert "*** Update File: structured_facts.md" in message
