from __future__ import annotations

from pantaray_agents.local_runtime.memory_catalog.fragments import parse_document


def test_parse_document_keeps_markdown_table_header_with_rows() -> None:
    blocks = parse_document(
        "facts/example.md",
        "# Values\n\n| Name | Value |\n| --- | --- |\n| A | B |\n",
    )

    table = next(block for block in blocks if block.block_kind == "table")

    assert table.content_text == "| Name | Value |\n| --- | --- |\n| A | B |"
    assert table.heading_path == "Values"
    assert table.start_offset == len("# Values\n\n")


def test_parse_document_keeps_preceding_paragraph_outside_table() -> None:
    blocks = parse_document(
        "facts/example.md",
        "Context before the table.\n| Name | Value |\n| --- | --- |\n| A | B |\n",
    )

    visible = [
        (block.block_kind, block.content_text)
        for block in blocks
        if block.block_kind != "document_root"
    ]

    assert visible == [
        ("paragraph", "Context before the table."),
        ("table", "| Name | Value |\n| --- | --- |\n| A | B |"),
    ]


def test_parse_document_does_not_treat_pipe_text_as_table_without_separator() -> None:
    blocks = parse_document(
        "facts/example.md",
        "A | B is ordinary prose.\nAnother sentence.\n",
    )

    paragraph = next(block for block in blocks if block.block_kind == "paragraph")

    assert paragraph.content_text == "A | B is ordinary prose. Another sentence."
