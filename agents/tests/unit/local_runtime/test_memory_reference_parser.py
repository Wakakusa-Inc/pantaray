from __future__ import annotations

from pantaray_agents.local_runtime.memory_references import (
    extract_markdown_references,
    remove_reference_ids,
    remove_reference_occurrences,
    replace_reference_ids,
    replace_reference_occurrences,
)


def test_extract_markdown_references_reads_anchor_and_note() -> None:
    markdown = (
        '- First line [[ref:ref_a note:"same concern"]]\n- Second line [[ref:ref_b]]'
    )

    occurrences = extract_markdown_references(markdown)

    assert [occurrence.local_ref_id for occurrence in occurrences] == ["ref_a", "ref_b"]
    assert occurrences[0].note == "same concern"
    assert occurrences[0].anchor_text == "- First line"
    assert occurrences[1].note is None
    assert occurrences[1].anchor_text == "- Second line"


def test_replace_reference_ids_updates_only_reference_identifier() -> None:
    markdown = '- Example [[ref:ref_old note:"same concern"]]'

    result = replace_reference_ids(
        markdown,
        {"ref_old": "ref_new"},
    )

    assert result == '- Example [[ref:ref_new note:"same concern"]]'


def test_remove_reference_ids_drops_only_targeted_markup() -> None:
    markdown = (
        '- Keep [[ref:ref_keep note:"same concern"]]\n'
        '- Drop [[ref:ref_drop note:"stale"]]'
    )

    result = remove_reference_ids(markdown, {"ref_drop"})

    assert result == ('- Keep [[ref:ref_keep note:"same concern"]]\n- Drop')


def test_replace_reference_occurrences_updates_only_targeted_occurrence() -> None:
    markdown = (
        '- First [[ref:ref_same note:"same concern"]]\n'
        '- Second [[ref:ref_same note:"same concern"]]'
    )

    result = replace_reference_occurrences(markdown, {1: "ref_other"})

    assert result == (
        '- First [[ref:ref_same note:"same concern"]]\n'
        '- Second [[ref:ref_other note:"same concern"]]'
    )


def test_remove_reference_occurrences_drops_only_targeted_occurrence() -> None:
    markdown = (
        '- First [[ref:ref_same note:"same concern"]]\n'
        '- Second [[ref:ref_same note:"same concern"]]'
    )

    result = remove_reference_occurrences(markdown, {1})

    assert result == ('- First [[ref:ref_same note:"same concern"]]\n- Second')


def test_remove_reference_occurrences_preserves_unrelated_spacing() -> None:
    markdown = (
        "| Col  | Value |\n"
        "| ---- | ----- |\n"
        "| A    | one   |\n"
        "```text\n"
        "keep    repeated spaces\tand tabs\n"
        "```\n"
        "- Drop [[ref:ref_drop]]\n"
        "trailing spaces stay   \n"
    )

    result = remove_reference_ids(markdown, {"ref_drop"})

    assert result == (
        "| Col  | Value |\n"
        "| ---- | ----- |\n"
        "| A    | one   |\n"
        "```text\n"
        "keep    repeated spaces\tand tabs\n"
        "```\n"
        "- Drop\n"
        "trailing spaces stay   \n"
    )
