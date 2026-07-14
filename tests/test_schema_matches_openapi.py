"""
Single-source-of-truth drift guard (Conformance_Test_Kit_Plan.md, Artifact 5).
================================================================================
The canonical envelope is defined twice: authoritatively in
`conformance/envelope.schema.json`, and partially in the OpenAPI transport spec
`api/config/openapi.yml`. This test makes sure they never DISAGREE.

It is a **permanent one-directional subset guard**, not a transitional one: the
spec stays OpenAPI 3.0 for good (the 3.1 upgrade is declined — Connexion 3.3.0
can't parse 3.1; see reviews/contract_change_impact_map.md §3), so it will never
fully express the envelope (no `qc.analysis_pass` requirement, no trait-key
pattern, no value/unit constraints, untyped bbox). Those live in the standalone
schema by design. So we only assert that everything the SPEC requires is also
required by the SCHEMA — never the reverse.

Comparison is intentionally shallow (required-sets + property names). The spec
types things loosely on purpose (qc: {type: object}, value/unit nullable), so
deep type-equality would be brittle and is not attempted.
================================================================================
"""
import json
import pathlib

import pytest

yaml = pytest.importorskip("yaml")  # PyYAML; in the [dev] extra. Skip cleanly if absent.

# --- Locate the two contract files -----------------------------------------
# Repo layout: tests/  and  conformance/  and  api/config/  share a common root.
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "conformance" / "envelope.schema.json"

# The spec lives at api/config/openapi.yml (confirmed by the impact map — NOT the
# plan's original config/openapi.yml). Try that first, tolerate the older layout.
OPENAPI_CANDIDATES = (
    ROOT / "api" / "config" / "openapi.yml",
    ROOT / "config" / "openapi.yml",
)

# Rename is done: /analyze is current. Keep /upload only as a tolerant fallback
# for an old spec copy.
CANDIDATE_PATHS = ("/analyze", "/upload")


def _openapi_path():
    for p in OPENAPI_CANDIDATES:
        if p.is_file():
            return p
    return None


def _envelope_from_openapi(spec):
    """Walk to the 200-response JSON body schema of the analyze operation."""
    for path in CANDIDATE_PATHS:
        try:
            return (spec["paths"][path]["post"]["responses"]["200"]
                        ["content"]["application/json"]["schema"])
        except (KeyError, TypeError):
            continue
    return None


def _load_spec_envelope():
    """Return the spec's envelope response schema, or skip with a visible reason."""
    path = _openapi_path()
    if path is None:
        pytest.skip("openapi.yml not found; standalone schema is authoritative (Decision 2)")
    spec = yaml.safe_load(path.read_text())
    oapi = _envelope_from_openapi(spec)
    if not oapi or "properties" not in oapi:
        pytest.skip("openapi.yml does not specify the /analyze envelope body; "
                    "standalone schema authoritative (Decision 2)")
    return oapi


def _load_schema():
    return json.loads(SCHEMA.read_text())


# ---------------------------------------------------------------------------
# 1. The guard: everything the spec REQUIRES must also be required by the schema.
# ---------------------------------------------------------------------------
def test_schema_is_superset_of_openapi():
    oapi = _load_spec_envelope()
    schema = _load_schema()

    # Top-level required sets.
    spec_required = set(oapi.get("required", []))
    schema_required = set(schema.get("required", []))
    missing = spec_required - schema_required
    assert not missing, (
        f"openapi.yml requires top-level field(s) the JSON Schema does not: {sorted(missing)}"
    )

    # Object-item required sets (objects[].items.required — object_id, traits).
    spec_obj = (oapi.get("properties", {}).get("objects", {})
                    .get("items", {}))
    schema_obj = (schema.get("properties", {}).get("objects", {})
                      .get("items", {}))
    spec_obj_required = set(spec_obj.get("required", []))
    schema_obj_required = set(schema_obj.get("required", []))
    obj_missing = spec_obj_required - schema_obj_required
    assert not obj_missing, (
        f"openapi.yml requires objects[] field(s) the JSON Schema does not: {sorted(obj_missing)}"
    )


# ---------------------------------------------------------------------------
# 2. Every property the spec NAMES at the top level must exist in the schema,
#    so a rename/removal on one side can't silently drift them apart.
# ---------------------------------------------------------------------------
def test_openapi_property_names_exist_in_schema():
    oapi = _load_spec_envelope()
    schema = _load_schema()
    schema_props = set(schema.get("properties", {}))
    spec_props = set(oapi.get("properties", {}))
    unknown = spec_props - schema_props
    assert not unknown, (
        f"openapi.yml names top-level propert(ies) absent from the JSON Schema: "
        f"{sorted(unknown)} (rename/removed on one side?)"
    )


# ---------------------------------------------------------------------------
# 3. PERMANENT documentation marker — the spec is partial ON PURPOSE.
#    Do NOT convert this to a hard assertion: OpenAPI 3.1 is declined, so the spec
#    will never fully express the envelope. Kept skipped so the boundary is visible
#    in the test report.
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason="Permanent by design: openapi.yml stays 3.0 (3.1 declined — "
                         "Connexion 3.3.0 can't parse it; impact map §3), so it will "
                         "never fully express the envelope. envelope.schema.json is the "
                         "permanent authority for qc.analysis_pass, the trait-key "
                         "pattern, value/unit, and bbox. DO NOT promote to an assertion.")
def test_openapi_fully_expresses_envelope():
    oapi = _load_spec_envelope()
    schema = _load_schema()
    assert set(oapi.get("required", [])) == set(schema.get("required", []))
