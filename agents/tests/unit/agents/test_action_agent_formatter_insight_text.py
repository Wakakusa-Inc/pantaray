import pytest

from pantaray_agents.agents.action_agent.support.formatter import ActionAgentFormatter


@pytest.mark.usefixtures("tokyo_local_zone")
def test_short_term_insight_lines_show_local_time() -> None:
    text = ActionAgentFormatter().build_insight_text(
        None,
        [
            {
                "short_term_insight_data": "Drafted the estimate.",
                "created_at": "2026-09-26T21:50:00.000000Z",
            }
        ],
    )

    assert "- [2026-09-27T06:50+09:00] Drafted the estimate." in text
