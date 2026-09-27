from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.memory_catalog.errors import (
    MemoryLinkValidationError,
)
from pantaray_agents.local_runtime.memory_catalog.models import MemoryDocument
from pantaray_agents.local_runtime.memory_catalog.reference_edits import (
    insert_memory_reference,
)
from pantaray_agents.local_runtime.memory_references.reference_parser import (
    extract_markdown_references,
)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_reference_selects_repeated_block_and_preserves_other_files(
    newline: str,
) -> None:
    source = newline.join(("# Topic", "", "- Same claim", "", "- Same claim", ""))
    untouched = MemoryDocument("insights/other.md", "Untouched\r\n")
    documents, anchor = insert_memory_reference(
        documents=(MemoryDocument("facts/main.md", source), untouched),
        source_path="facts/main.md",
        exact_text="- Same claim",
        occurrence=2,
        local_ref_id="ref_host_issued",
        note='Evidence with "quotes" and \\path',
    )
    assert documents[0].content.startswith(
        "# Topic\n\n- Same claim\n\n- Same claim [[ref:"
    )
    assert documents[0].content.endswith("]]\n")
    assert documents[1] == untouched
    assert anchor == "- Same claim"
    references = extract_markdown_references(documents[0].content)
    assert len(references) == 1
    assert references[0].local_ref_id == "ref_host_issued"
    assert references[0].note == 'Evidence with "quotes" and \\path'


def test_reference_can_attach_to_block_that_already_has_a_reference() -> None:
    documents, anchor = insert_memory_reference(
        documents=(
            MemoryDocument("facts/main.md", '- Claim [[ref:ref_old note:"prior"]]\n'),
        ),
        source_path="facts/main.md",
        exact_text="- Claim",
        occurrence=1,
        local_ref_id="ref_new",
        note="new evidence",
    )
    assert anchor == "- Claim"
    assert [
        ref.local_ref_id for ref in extract_markdown_references(documents[0].content)
    ] == ["ref_old", "ref_new"]


@pytest.mark.parametrize(
    "path, exact_text, occurrence, note",
    [
        ("facts/missing.md", "- Claim", 1, "evidence"),
        ("facts/main.md", "Claim substring", 1, "evidence"),
        ("facts/main.md", "# Heading", 1, "evidence"),
        ("facts/main.md", "- Claim", 2, "evidence"),
        ("facts/main.md", "- Claim", 0, "evidence"),
        ("facts/main.md", "- Claim", 1, "bad\nnote"),
    ],
)
def test_reference_rejects_invalid_anchor_or_note(
    path: str, exact_text: str, occurrence: int, note: str
) -> None:
    with pytest.raises(MemoryLinkValidationError):
        insert_memory_reference(
            documents=(MemoryDocument("facts/main.md", "# Heading\n\n- Claim\n"),),
            source_path=path,
            exact_text=exact_text,
            occurrence=occurrence,
            local_ref_id="ref_new",
            note=note,
        )


@pytest.mark.parametrize("before", ["", '- Claim [[ref:ref_old note:"old"]]'])
@pytest.mark.parametrize(
    "malformed",
    ['[[ref:ref_new note:"x"]', "[[ref:ref_new", '[[ref:ref_new note:"unterminated'],
)
def test_text_replacement_rejects_new_malformed_reference_prefix(before, malformed):
    from pantaray_agents.local_runtime.memory_catalog.reference_edits import (
        validate_reference_text_replacement,
    )

    with pytest.raises(MemoryLinkValidationError):
        validate_reference_text_replacement(
            path="facts/main.md", before=before, after=malformed
        )


def test_text_replacement_keeps_existing_malformed_literal_lines():
    from pantaray_agents.local_runtime.memory_catalog.reference_edits import (
        validate_reference_text_replacement,
    )

    literal = '[[ref:ref_external note:"incomplete"]'
    validate_reference_text_replacement(
        path="facts/main.md", before=f"- Old\n\n{literal}", after=f"- New\n\n{literal}"
    )
    validate_reference_text_replacement(
        path="facts/main.md", before=literal, after="- Removed"
    )


@pytest.mark.parametrize(
    "after",
    [
        '- Claim [[ref:ref_new note:"invented"]]',
        '- Claim [[ref:ref_old note:"changed"]]',
        '- Claim [[ref:ref_old note:"note"]] [[ref:ref_old note:"note"]]',
        '- Claim [[ref:ref_old note:"note"]',
    ],
)
def test_text_replacement_rejects_forged_or_damaged_tag(after):
    from pantaray_agents.local_runtime.memory_catalog.reference_edits import (
        validate_reference_text_replacement,
    )

    with pytest.raises(MemoryLinkValidationError):
        validate_reference_text_replacement(
            path="facts/main.md",
            before='- Claim [[ref:ref_old note:"note"]]',
            after=after,
        )
