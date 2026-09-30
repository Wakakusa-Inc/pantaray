"""Compact index of the Memory agent's `insights/todos.md` for a Suggestion run.

The TODO file is free Markdown that grows with every Memory update (40 KB and
41 items in September 2026 production data). A bounded preview hid the later
sections, so runs spent most of their tool calls paging the file and deadline
items near its end never surfaced. The index lists every item once with the
dates stated in its text; the run reads an item's full entry only when it is a
candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# One line per item: title plus the start of its next step.
ITEM_SUMMARY_MAX_CHARS = 160
TITLE_MAX_CHARS = 90
# A deadline this far past is history, not a reason to act now.
OVERDUE_LISTING_DAYS = 3
# Items whose newest dated evidence is older than this are marked stale.
STALE_EVIDENCE_DAYS = 3
# Month/day dates further than this from the reference date belong to the
# neighboring year.
YEAR_WRAP_DAYS = 180
# The file tracks current work; a "date" outside this window is a ratio such as
# "6/6 questions", not a date.
DATE_WINDOW_PAST_DAYS = 60
DATE_WINDOW_FUTURE_DAYS = 120
# Bound on the rendered index; past it, item summaries are dropped.
INDEX_MAX_CHARS = 12_000

_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_ISO = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_JA = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")
_SLASH = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/])")
_EN = re.compile(
    r"\b("
    + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\.?\s+(\d{1,2})(?!\d)",
    re.IGNORECASE,
)
# A clock time between the cue and the date ("merged by 17:57 on 9/29") makes
# it a report of when something happened, not a deadline.
_DEADLINE_BEFORE = re.compile(
    r"(\bby|\bbefore|\buntil|\bdue|\bdeadline|期限|締切|締め切り)[^.。;:\n]{0,14}$",
    re.IGNORECASE,
)
_DEADLINE_AFTER = re.compile(
    r"^[^.。;\n]{0,12}?(deadline|期限|締切|締め切り|まで)", re.IGNORECASE
)
_BOLD_TITLE = re.compile(r"^\*\*(.+?)\*\*[:：]?\s*")
_DONE = re.compile(r"^(~~|\[x\]\s)", re.IGNORECASE)
_REF = re.compile(r"\[\[ref:[^\]]*\]\]")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


@dataclass(frozen=True, slots=True)
class TodoItem:
    section: str
    title: str
    summary: str
    due: date | None
    latest_evidence: date | None


def _resolve(month: int, day: int, year: int | None, today: date) -> date | None:
    try:
        value = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None:
        if value - today > timedelta(days=YEAR_WRAP_DAYS):
            value = value.replace(year=value.year - 1)
        elif today - value > timedelta(days=YEAR_WRAP_DAYS):
            value = value.replace(year=value.year + 1)
    if not (-DATE_WINDOW_PAST_DAYS <= (value - today).days <= DATE_WINDOW_FUTURE_DAYS):
        return None
    return value


def _dates(text: str, today: date) -> list[tuple[date, bool]]:
    """Dates stated in `text`, each with whether the wording makes it a deadline."""
    found: list[tuple[date, bool]] = []
    matches: list[tuple[re.Match[str], date | None]] = []
    for match in _ISO.finditer(text):
        matches.append(
            (match, _resolve(int(match[2]), int(match[3]), int(match[1]), today))
        )
    for pattern in (_JA, _SLASH):
        for match in pattern.finditer(text):
            matches.append((match, _resolve(int(match[1]), int(match[2]), None, today)))
    for match in _EN.finditer(text):
        month = _MONTHS[match[1].lower()]
        matches.append((match, _resolve(month, int(match[2]), None, today)))
    for match, value in matches:
        if value is None:
            continue
        deadline = bool(
            _DEADLINE_BEFORE.search(text[: match.start()])
            or _DEADLINE_AFTER.search(text[match.end() :])
        )
        found.append((value, deadline))
    return found


def _plain(text: str) -> str:
    text = _LINK.sub(r"\1", _REF.sub("", text))
    return " ".join(text.replace("`", "").split())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _blocks(markdown: str) -> list[tuple[str, list[str]]]:
    """(section, lines) per item: a top-level bullet, a sub-heading with the
    paragraphs under it, or a free paragraph. The Memory agent writes ordinary
    Markdown; so far it has used only `##` sections and bullets."""
    section = ""
    blocks: list[tuple[str, list[str]]] = []
    continues = False
    under_heading = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            # A paragraph after a blank line still belongs to a sub-heading item.
            continues = under_heading
            continue
        if line.startswith("# "):
            continues = under_heading = False
        elif line.startswith("## "):
            section = stripped[3:].strip()
            continues = under_heading = False
        elif line.startswith("#"):
            blocks.append((section, [f"**{stripped.lstrip('#').strip()}**"]))
            continues = under_heading = True
        elif line.startswith(("- ", "* ")):
            blocks.append((section, [line[2:]]))
            continues, under_heading = True, False
        elif blocks and (continues or line.startswith((" ", "\t"))):
            blocks[-1][1].append(stripped)
        else:
            blocks.append((section, [stripped]))
            continues, under_heading = True, False
    return blocks


def parse_todo_items(markdown: str, *, today: date) -> tuple[TodoItem, ...]:
    """Items of the TODO file, deduplicated, explicitly completed ones dropped."""
    items: list[TodoItem] = []
    seen: set[tuple[str, str]] = set()
    for block_section, lines in _blocks(markdown):
        text = " ".join(lines).strip()
        if _DONE.match(text):
            continue
        bold = _BOLD_TITLE.match(text)
        if bold:
            title, body = _plain(bold[1]), _plain(text[bold.end() :])
        else:
            plain = _plain(text)
            cut = min(
                (i + 1 for i in (plain.find(". "), plain.find("。")) if i >= 0),
                default=len(plain),
            )
            title, body = plain[:cut].strip(), plain[cut:].strip()
        key = (block_section, title.casefold())
        if key in seen:
            continue
        seen.add(key)
        dated = _dates(text, today)
        deadlines = sorted(value for value, is_deadline in dated if is_deadline)
        upcoming = [value for value in deadlines if value >= today]
        evidence = [value for value, is_deadline in dated if value <= today]
        items.append(
            TodoItem(
                section=block_section,
                title=_clip(title, TITLE_MAX_CHARS),
                summary=_clip(body, ITEM_SUMMARY_MAX_CHARS),
                due=upcoming[0] if upcoming else (deadlines[-1] if deadlines else None),
                latest_evidence=max(evidence) if evidence else None,
            )
        )
    return tuple(items)


def _day(value: date) -> str:
    return f"{value.month}/{value.day} ({value.strftime('%a')})"


def _due_text(due: date, today: date) -> str:
    days = (due - today).days
    if days == 0:
        return f"due {_day(due)}, today"
    if days > 0:
        return f"due {_day(due)}, in {days} day{'s' if days != 1 else ''}"
    return f"due {_day(due)}, {-days} day{'s' if days != -1 else ''} ago"


def _item_line(item: TodoItem, today: date, *, with_summary: bool) -> str:
    facts: list[str] = []
    if item.due is not None:
        facts.append(_due_text(item.due, today))
    if item.latest_evidence is not None:
        stale = (today - item.latest_evidence).days > STALE_EVIDENCE_DAYS
        facts.append(
            f"latest dated evidence {_day(item.latest_evidence)}"
            + (" (stale)" if stale else "")
        )
    else:
        facts.append("no dated evidence")
    line = f"- **{item.title}** — {'; '.join(facts)}"
    return f"{line}\n  {item.summary}" if with_summary and item.summary else line


def build_todo_index(markdown: str, *, today: date) -> str:
    """Render the index; an empty file yields an empty string."""
    items = parse_todo_items(markdown, today=today)
    if not items:
        return ""
    full = _render(items, today, with_summary=True)
    if len(full) <= INDEX_MAX_CHARS:
        return full
    compact = _render(items, today, with_summary=False)
    if len(compact) <= INDEX_MAX_CHARS:
        return compact
    marker = "\n[index truncated; grep insights/todos.md for the remaining items]"
    return compact[: INDEX_MAX_CHARS - len(marker)].rsplit("\n", 1)[0] + marker


def _render(items: tuple[TodoItem, ...], today: date, *, with_summary: bool) -> str:
    lines: list[str] = []
    deadlines = sorted(
        (
            item
            for item in items
            if item.due is not None and (today - item.due).days <= OVERDUE_LISTING_DAYS
        ),
        key=lambda item: item.due or today,
    )
    if deadlines:
        lines.append("### Stated deadlines (soonest first)")
        lines.extend(
            f"- {_due_text(item.due, today)}: **{item.title}** [{item.section}]"
            for item in deadlines
            if item.due is not None
        )
        lines.append("")
    section = None
    for item in items:
        if item.section != section:
            section = item.section
            lines.append(f"### {section or 'Unsectioned'}")
        lines.append(_item_line(item, today, with_summary=with_summary))
    return "\n".join(lines).rstrip()


__all__ = ["TodoItem", "build_todo_index", "parse_todo_items"]
