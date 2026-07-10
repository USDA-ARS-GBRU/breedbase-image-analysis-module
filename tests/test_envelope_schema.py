"""
Conformance test: real envelopes must validate against the canonical
envelope.schema.json (API_Standardization_Tracker.md Subtask 5).
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "conformance" / "envelope.schema.json"
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "expected_output.json"


@pytest.fixture(scope="session")
def schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def golden_envelope():
    with open(GOLDEN_PATH) as f:
        data = json.load(f)
    # Golden fixture has volatile fields (job_id, timestamp, input,
    # derived_images) stripped for stable comparison; add back the fields
    # the schema requires so this exercises a realistic full envelope.
    data.setdefault("job_id", "11111111-1111-1111-1111-111111111111")
    data.setdefault("derived_images", [
        {"role": "overlay", "filename": "sample_seeds_ResultImage_test.png", "url": "http://example.com/x.png"}
    ])
    return data


def test_golden_envelope_is_schema_valid(schema, golden_envelope):
    jsonschema.Draft202012Validator(schema).validate(golden_envelope)


def test_failure_envelope_is_schema_valid(schema, golden_envelope):
    """analysis_pass:false with empty objects/traits_emitted must still validate."""
    failure_envelope = copy.deepcopy(golden_envelope)
    failure_envelope["qc"] = {
        "analysis_pass": False,
        "color_card_present": True,
        "size_marker_detected": False,
        "object_count": 0,
    }
    failure_envelope["objects"] = []
    failure_envelope["traits_emitted"] = []
    jsonschema.Draft202012Validator(schema).validate(failure_envelope)


def test_missing_qc_analysis_pass_is_invalid(schema, golden_envelope):
    invalid_envelope = copy.deepcopy(golden_envelope)
    del invalid_envelope["qc"]["analysis_pass"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid_envelope)


def test_bad_trait_key_is_invalid(schema, golden_envelope):
    invalid_envelope = copy.deepcopy(golden_envelope)
    first_obj = invalid_envelope["objects"][0]
    first_obj["traits"]["Object Max Diameter"] = {"value": 4.3, "unit": "mm"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid_envelope)


def test_wrong_schema_version_is_invalid(schema, golden_envelope):
    invalid_envelope = copy.deepcopy(golden_envelope)
    invalid_envelope["schema_version"] = "0.9"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid_envelope)
