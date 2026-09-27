"""Markdownセクション抽出ユーティリティのユニットテスト。"""

from pantaray_agents.utils.markdown_sections import extract_markdown_section


def test_extract_markdown_section_returns_section_including_heading() -> None:
    md = (
        "# Top\n\n"
        "Intro.\n\n"
        "## Ongoing And Past Initiatives and Projects\n"
        "- A\n"
        "- B\n\n"
        "## Other\n"
        "X\n"
    )
    out = extract_markdown_section(
        markdown=md,
        heading_text="Ongoing And Past Initiatives and Projects",
    )
    assert out.startswith("## Ongoing And Past Initiatives and Projects")
    assert "- A" in out and "- B" in out
    assert "## Other" not in out


def test_extract_markdown_section_returns_empty_when_missing() -> None:
    md = "# Top\n\n## Something else\n- X\n"
    out = extract_markdown_section(markdown=md, heading_text="Nope")
    assert out == ""


def test_extract_markdown_section_handles_trailing_spaces_and_case() -> None:
    md = "## Ongoing And Past Initiatives and Projects   \n- A\n\n## Next\n- X\n"
    out = extract_markdown_section(
        markdown=md,
        heading_text="Ongoing And Past Initiatives and Projects",
    )
    assert "- A" in out
    assert "## Next" not in out


def test_extract_markdown_section_stops_at_same_or_higher_level_heading() -> None:
    md = (
        "### Ongoing And Past Initiatives and Projects\n"
        "- A\n"
        "#### Sub\n"
        "- sub\n"
        "### Next Same Level\n"
        "- B\n"
    )
    out = extract_markdown_section(
        markdown=md,
        heading_text="Ongoing And Past Initiatives and Projects",
    )
    assert "- A" in out
    assert "#### Sub" in out
    assert "### Next Same Level" not in out


def test_extract_markdown_section_returns_first_match_when_multiple() -> None:
    md = (
        "## Ongoing And Past Initiatives and Projects\n"
        "- First\n"
        "## Other\n"
        "X\n"
        "## Ongoing And Past Initiatives and Projects\n"
        "- Second\n"
    )
    out = extract_markdown_section(
        markdown=md,
        heading_text="Ongoing And Past Initiatives and Projects",
    )
    assert "- First" in out
    assert "- Second" not in out
