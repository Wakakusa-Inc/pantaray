"""The Pending work index a Suggestion run reads instead of the whole TODO file."""

from datetime import date

from pantaray_agents.agents.suggestion_agent import todo_index
from pantaray_agents.agents.suggestion_agent.todo_index import (
    build_todo_index,
    parse_todo_items,
)

TODAY = date(2026, 9, 29)


def test_deadlines_come_first_soonest_first_with_days_left() -> None:
    index = build_todo_index(
        "# TODOs\n\n"
        "## llm-jp -> 2026 October retreat\n"
        "- **Participation details by October 2**: supply them if missing.\n\n"
        "## Xer -> Operations\n"
        "- **SHIFT invoice**: handle it against the September 30 deadline "
        "shown in the DM on 9/28.\n"
        "- **Contract**: 10月5日までに返送する。\n",
        today=TODAY,
    )

    head = index.split("\n\n", 1)[0].splitlines()
    assert head == [
        "### Stated deadlines (soonest first)",
        "- due 9/30 (Wed), in 1 day: **SHIFT invoice** [Xer -> Operations]",
        "- due 10/2 (Fri), in 3 days: **Participation details by October 2** "
        "[llm-jp -> 2026 October retreat]",
        "- due 10/5 (Mon), in 6 days: **Contract** [Xer -> Operations]",
    ]
    # An item that survives only in a late section is still listed.
    assert "latest dated evidence 9/28 (Mon)" in index


def test_report_times_and_ratios_are_not_deadlines_or_evidence() -> None:
    (item,) = parse_todo_items(
        "- **Release**: Claude reported all four merged into develop by 17:57 JST "
        "on 9/29; replay passed 6/6 questions and 18/18 time ranges.\n",
        today=TODAY,
    )

    assert item.due is None
    assert item.latest_evidence == date(2026, 9, 29)


def test_explicitly_completed_and_repeated_items_are_listed_once_or_not_at_all() -> (
    None
):
    items = parse_todo_items(
        "## Pantaray\n"
        "- ~~**Merge PR #1467**~~ merged on 9/26.\n"
        "- **Review PR #45**: first note.\n"
        "- **Review PR #45**: repeated note.\n"
        "## Other\n"
        "- **Review PR #45**: a different project keeps its own item.\n",
        today=TODAY,
    )

    assert [(item.section, item.title, item.summary) for item in items] == [
        ("Pantaray", "Review PR #45", "first note."),
        ("Other", "Review PR #45", "a different project keeps its own item."),
    ]


def test_paragraphs_and_sub_headings_are_items_too() -> None:
    items = parse_todo_items(
        "Observed: prepare the estimate for the other project.\n\n"
        "## Xer\n### Invoice\nSend it by 10/3.\n\nCheck the address first.\n",
        today=TODAY,
    )

    assert [(item.title, item.summary, item.due) for item in items] == [
        ("Observed: prepare the estimate for the other project.", "", None),
        ("Invoice", "Send it by 10/3. Check the address first.", date(2026, 10, 3)),
    ]


def test_a_long_file_drops_summaries_before_items(monkeypatch) -> None:
    monkeypatch.setattr(todo_index, "INDEX_MAX_CHARS", 900)
    markdown = "## Work\n" + "".join(
        f"- **Item {number}**: {'detail ' * 30}\n" for number in range(12)
    )

    index = build_todo_index(markdown, today=TODAY)

    assert len(index) <= 900
    assert "**Item 11**" in index
    assert "detail" not in index
