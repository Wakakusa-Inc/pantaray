import pytest


def test_apply_unified_diff_replaces_line() -> None:
    from pantaray_agents.utils.unified_diff import apply_unified_diff

    base = "a\nb\nc\n"
    diff = "--- a/file.md\n+++ b/file.md\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
    assert apply_unified_diff(base, diff) == "a\nB\nc\n"


def test_apply_unified_diff_inserts_line() -> None:
    from pantaray_agents.utils.unified_diff import apply_unified_diff

    base = "a\nc\n"
    diff = "--- a/file.md\n+++ b/file.md\n@@ -1,2 +1,3 @@\n a\n+b\n c\n"
    assert apply_unified_diff(base, diff) == "a\nb\nc\n"


def test_apply_unified_diff_deletes_line() -> None:
    from pantaray_agents.utils.unified_diff import apply_unified_diff

    base = "a\nb\nc\n"
    diff = "--- a/file.md\n+++ b/file.md\n@@ -1,3 +1,2 @@\n a\n-b\n c\n"
    assert apply_unified_diff(base, diff) == "a\nc\n"


def test_apply_unified_diff_creates_from_empty() -> None:
    from pantaray_agents.utils.unified_diff import apply_unified_diff

    base = ""
    diff = "--- a/file.md\n+++ b/file.md\n@@ -0,0 +1,2 @@\n+a\n+b\n"
    assert apply_unified_diff(base, diff) == "a\nb"


def test_apply_unified_diff_raises_on_context_mismatch() -> None:
    from pantaray_agents.utils.unified_diff import (
        UnifiedDiffApplyError,
        apply_unified_diff,
    )

    base = "a\nb\nc\n"
    diff = "--- a/file.md\n+++ b/file.md\n@@ -1,3 +1,3 @@\n a\n-x\n+B\n c\n"
    with pytest.raises(UnifiedDiffApplyError):
        _ = apply_unified_diff(base, diff)
