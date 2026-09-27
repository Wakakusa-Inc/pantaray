from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.local_runtime.tooling.brokering.broker_protocol import (
    ApplyPatchToolArgs,
)


def test_apply_patch_add_requires_new_lines_field() -> None:
    with pytest.raises(ValidationError):
        ApplyPatchToolArgs.model_validate(
            {
                "changes": [
                    {
                        "op": "add",
                        "path": "created.txt",
                        "trailing_newline": False,
                    }
                ]
            }
        )


def test_apply_patch_update_requires_new_lines_field() -> None:
    with pytest.raises(ValidationError):
        ApplyPatchToolArgs.model_validate(
            {
                "changes": [
                    {
                        "op": "update",
                        "path": "todo.txt",
                        "edits": [{"old_lines": ["remove me"]}],
                    }
                ]
            }
        )


def test_apply_patch_update_allows_explicit_empty_new_lines() -> None:
    parsed = ApplyPatchToolArgs.model_validate(
        {
            "changes": [
                {
                    "op": "update",
                    "path": "todo.txt",
                    "edits": [{"old_lines": ["remove me"], "new_lines": []}],
                }
            ]
        }
    )

    assert parsed.changes[0].op == "update"


def test_apply_patch_update_allows_optional_location_hints() -> None:
    parsed = ApplyPatchToolArgs.model_validate(
        {
            "changes": [
                {
                    "op": "update",
                    "path": "todo.txt",
                    "edits": [
                        {
                            "before_lines": ["# Section"],
                            "old_lines": ["remove me"],
                            "new_lines": ["replacement"],
                            "after_lines": ["# Next"],
                        }
                    ],
                }
            ]
        }
    )

    edit = parsed.changes[0].edits[0]
    assert edit.before_lines == ["# Section"]
    assert edit.after_lines == ["# Next"]


def test_apply_patch_rejects_multiple_changes() -> None:
    with pytest.raises(ValidationError):
        ApplyPatchToolArgs.model_validate(
            {
                "changes": [
                    {
                        "op": "add",
                        "path": "first.txt",
                        "new_lines": ["first"],
                        "trailing_newline": True,
                    },
                    {
                        "op": "add",
                        "path": "second.txt",
                        "new_lines": ["second"],
                        "trailing_newline": True,
                    },
                ]
            }
        )


def test_apply_patch_update_rejects_multiple_edits() -> None:
    with pytest.raises(ValidationError):
        ApplyPatchToolArgs.model_validate(
            {
                "changes": [
                    {
                        "op": "update",
                        "path": "todo.txt",
                        "edits": [
                            {"old_lines": ["first"], "new_lines": ["one"]},
                            {"old_lines": ["second"], "new_lines": ["two"]},
                        ],
                    }
                ]
            }
        )
