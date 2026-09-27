import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from pantaray_agents.schema.context_source import (
    SourceTransition,
    SourceTransitionResult,
)

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[4]
        / "frontend/shared/context_source.fixtures.json"
    ).read_text()
)
REQUEST = TypeAdapter(SourceTransition)
RESULT = TypeAdapter(SourceTransitionResult)


@pytest.mark.parametrize("variant", FIXTURES["transitions"])
def test_electron_requests_use_the_backend_wire_contract(variant):
    payload = FIXTURES["transitions"][variant]
    parsed = REQUEST.validate_json(json.dumps(payload))
    assert parsed.model_dump(mode="json") == payload


@pytest.mark.parametrize("variant", FIXTURES["results"])
def test_backend_results_use_the_electron_wire_contract(variant):
    payload = FIXTURES["results"][variant]
    parsed = RESULT.validate_json(json.dumps(payload))
    assert parsed.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "field", ["executable", "config_path", "store_path", "user_id"]
)
def test_control_requests_cannot_select_paths_or_override_the_authenticated_subject(
    field,
):
    payload = deepcopy(FIXTURES["transitions"]["activate"])
    payload[field] = "caller-controlled"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        REQUEST.validate_json(json.dumps(payload))


@pytest.mark.parametrize("version", [0, 2, True, "1"])
def test_activation_rejects_incompatible_or_coerced_protocol_versions(version):
    payload = deepcopy(FIXTURES["transitions"]["activate"])
    payload["recorder_binding"]["protocol_version"] = version
    with pytest.raises(ValidationError):
        REQUEST.validate_json(json.dumps(payload))


def test_activation_rejects_an_arbitrary_path_inside_the_recorder_binding():
    payload = deepcopy(FIXTURES["transitions"]["activate"])
    payload["recorder_binding"]["store_path"] = "/another-subject/store"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        REQUEST.validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "variant,field", [("activate", "issued_epoch"), ("suspend", "expected_epoch")]
)
@pytest.mark.parametrize("epoch", ["", "not-an-epoch", 12, None])
def test_transition_rejects_an_invalid_target_epoch(variant, field, epoch):
    payload = deepcopy(FIXTURES["transitions"][variant])
    payload[field] = epoch
    with pytest.raises(ValidationError):
        REQUEST.validate_json(json.dumps(payload))


@pytest.mark.parametrize("field", ["user_id", "epoch", "store_id", "policy_revision"])
def test_ready_cannot_omit_a_source_binding_component(field):
    payload = deepcopy(FIXTURES["results"]["ready"])
    del payload["state"]["binding"][field]
    with pytest.raises(ValidationError, match="missing"):
        RESULT.validate_json(json.dumps(payload))


def test_unknown_result_cannot_be_read_as_success():
    payload = deepcopy(FIXTURES["results"]["ready"])
    payload["kind"] = "unknown"
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        RESULT.validate_json(json.dumps(payload))


def test_blocked_result_cannot_contain_a_ready_state():
    payload = deepcopy(FIXTURES["results"]["ready"])
    payload["kind"] = "blocked"
    with pytest.raises(ValidationError):
        RESULT.validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "variant,field", [("activate", "issued_epoch"), ("suspend", "expected_epoch")]
)
def test_transition_cannot_target_an_unspecified_generation(variant, field):
    payload = deepcopy(FIXTURES["transitions"][variant])
    del payload[field]
    with pytest.raises(ValidationError, match="missing"):
        REQUEST.validate_json(json.dumps(payload))


def test_blocked_state_cannot_be_encoded_as_an_applied_transition():
    payload = deepcopy(FIXTURES["results"]["blocked"])
    payload["kind"] = "applied"
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        RESULT.validate_json(json.dumps(payload))
