from __future__ import annotations

from unittest.mock import patch

from pantaray_agents.local_runtime.memory_references.reference_ids import (
    build_activity_reference_id,
    build_activity_reference_ids_for_targets,
)


def test_build_activity_reference_ids_for_targets_disambiguates_duplicate_targets() -> (
    None
):
    target_memory_keys = (
        "activity_log:log-1",
        "activity_log:log-1",
        "activity_log:log-2",
    )

    result = build_activity_reference_ids_for_targets(
        target_memory_keys=target_memory_keys
    )

    assert result == (
        build_activity_reference_id(target_memory_key="activity_log:log-1"),
        build_activity_reference_id(
            target_memory_key="activity_log:log-1",
            disambiguation_index=1,
        ),
        build_activity_reference_id(target_memory_key="activity_log:log-2"),
    )


def test_build_activity_reference_ids_for_targets_retries_on_hash_collision() -> None:
    with patch(
        "pantaray_agents.local_runtime.memory_references.reference_ids.build_activity_reference_id",
        side_effect=(
            "ref_collision",
            "ref_collision",
            "ref_collision_02",
        ),
    ) as mock_builder:
        result = build_activity_reference_ids_for_targets(
            target_memory_keys=("activity_log:log-1", "activity_log:log-2")
        )

    assert result == ("ref_collision", "ref_collision_02")
    assert mock_builder.call_args_list == [
        ((), {"target_memory_key": "activity_log:log-1", "disambiguation_index": 0}),
        ((), {"target_memory_key": "activity_log:log-2", "disambiguation_index": 0}),
        ((), {"target_memory_key": "activity_log:log-2", "disambiguation_index": 1}),
    ]
