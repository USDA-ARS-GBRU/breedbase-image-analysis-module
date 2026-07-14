"""
Fixture-driven conformance tests (Conformance_Test_Kit_Plan.md, Artifact 4).
================================================================================
Drives conformance.validate() against the fixture library (Artifact 7) in all three
modes (default / --strict / --pipeline-output) and asserts each invalid fixture fails
*for the intended reason*, not merely that it fails. This is the behavioral suite on
top of validate.py; the schema-direct `test_envelope_schema.py` is kept as an
independent lower layer that still passes if validate.py regresses.

Run:  pytest tests/test_conformance.py
================================================================================
"""
import json
import pathlib

import pytest

from conformance import Problem, validate

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    """Parse a fixture file into a dict."""
    return json.loads((FIX / name).read_text())


def _complete(envelope):
    """Re-inject the volatile module-injected fields the golden fixture strips
    (`job_id`, `derived_images`) so it can be validated as a FULL envelope in default
    mode — mirrors tests/test_envelope_schema.py. Purpose-built fixtures already carry
    these, so this is only needed for expected_output.json.
    """
    envelope.setdefault("job_id", "00000000-0000-0000-0000-0000000000ff")
    envelope.setdefault("derived_images", [
        {"role": "overlay", "filename": "sample_seeds_ResultImage_test.png",
         "url": "http://example.com/overlay.png"},
    ])
    return envelope


# ---------------------------------------------------------------------------
# Valid fixtures — zero problems in default mode.
# ---------------------------------------------------------------------------
VALID_DEFAULT = [
    "valid_minimal.json",
    "valid_extra_fields.json",     # extras are legal by default (Decision 1)
    "valid_null_unit.json",        # dimensionless unit: null is legal (revised item 2)
    "valid_failed_analysis.json",  # analysis_pass:false + empty arrays is legal
    "valid_contour_failure.json",  # object with bbox:null / null traits is legal
]


@pytest.mark.parametrize("name", VALID_DEFAULT)
def test_valid_fixtures_pass(name):
    assert validate(load(name)) == [], f"{name} should be valid in default mode"


def test_golden_passes():
    """The existing golden envelope must stay conformant (if it doesn't, the schema is
    wrong, not the fixture). Checked two ways: completed → default, and raw → pipeline
    output mode (it lacks job_id/derived_images as stripped volatiles)."""
    assert validate(_complete(load("expected_output.json"))) == []
    assert validate(load("expected_output.json"), pipeline_output=True) == []


# ---------------------------------------------------------------------------
# --strict: clean envelopes still pass; extras get rejected.
# ---------------------------------------------------------------------------
CLEAN_UNDER_STRICT = [
    "valid_minimal.json",
    "valid_null_unit.json",
    "valid_failed_analysis.json",
    "valid_contour_failure.json",
]


@pytest.mark.parametrize("name", CLEAN_UNDER_STRICT)
def test_clean_fixtures_also_pass_strict(name):
    """--strict must not over-reject envelopes that have no unknown fields."""
    assert validate(load(name), strict=True) == [], \
        f"{name} has no extras and should pass --strict"


def test_extra_fields_fail_under_strict():
    """valid_extra_fields passes by default but must fail --strict, and each of the
    three planted extras should be named."""
    env = load("valid_extra_fields.json")
    assert validate(env) == []                      # lenient by default
    problems = validate(env, strict=True)
    assert problems                                 # strict actually tightens
    blob = " ".join(f"{p.path} {p.message}" for p in problems)
    for extra in ("run_label", "color_card_prsent", "confidence"):
        assert extra in blob, f"--strict should flag the unknown field {extra!r}"


# ---------------------------------------------------------------------------
# Invalid fixtures — must fail default mode FOR THE INTENDED REASON.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,needle", [
    ("invalid_missing_qc.json",           "analysis_pass"),
    ("invalid_bad_traitkey.json",         "IMGSTAT"),
    ("invalid_missing_valuekey.json",     "value"),
    ("invalid_wrong_schema_version.json", "schema_version"),
])
def test_invalid_fixtures_fail_for_the_right_reason(name, needle):
    problems = validate(load(name))
    assert problems, f"{name} should be invalid"
    blob = " ".join(f"{p.path} {p.message}" for p in problems)
    assert needle in blob, \
        f"{name} should fail on {needle!r}; got {[str(p) for p in problems]}"


# ---------------------------------------------------------------------------
# --pipeline-output: raw pipeline output (no job_id/derived_images) passes only
# when the mode is on; the default failures should name those two fields.
# ---------------------------------------------------------------------------
def test_pipeline_output_mode():
    env = load("valid_pipeline_output_raw.json")
    default_problems = validate(env)
    assert default_problems, "raw pipeline output should fail default (missing provenance)"
    blob = " ".join(f"{p.path} {p.message}" for p in default_problems)
    assert "job_id" in blob and "derived_images" in blob
    assert validate(env, pipeline_output=True) == [], \
        "raw pipeline output should pass under --pipeline-output"


# ---------------------------------------------------------------------------
# --strict success-implies-output conditional.
# ---------------------------------------------------------------------------
def test_strict_conditional_passed_but_empty():
    env = load("invalid_passed_but_empty.json")
    assert validate(env) == []                      # structurally valid by default
    problems = validate(env, strict=True)
    assert problems, "analysis_pass:true with empty output must fail --strict"
    blob = " ".join(f"{p.path} {p.message}" for p in problems)
    assert "objects" in blob and "traits_emitted" in blob


# ---------------------------------------------------------------------------
# Problem object shape.
# ---------------------------------------------------------------------------
def test_problem_structure():
    problems = validate(load("invalid_missing_qc.json"))
    assert problems and all(isinstance(p, Problem) for p in problems)
    p = problems[0]
    assert p.message and hasattr(p, "path") and p.severity == "error"
