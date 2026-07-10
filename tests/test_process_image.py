"""
Integration tests for process_image.process_image().

These tests call the pipeline directly (no HTTP layer) and compare output
against tests/fixtures/expected_output.json (the golden file).

Generate the golden file once before running:
    python tests/generate_golden.py
"""

import pytest

# Volatile fields generated fresh on every run — excluded from comparison.
VOLATILE_KEYS = {"job_id", "timestamp", "input", "derived_images"}

# Acceptable relative tolerance for float trait values (0.5%).
# Tiny floating-point differences can occur across OS/library versions.
TRAIT_REL_TOL = 0.005

EXPECTED_TRAITS_ALL = [
    "Object Area From Segmentation Mask|IMGSTAT:0000006",
    "Object Convex Hull Area|IMGSTAT:0000007",
    "Object Perimeter From Segmentation Mask|IMGSTAT:0000010",
    "Object Solidity|IMGSTAT:0000011",
    "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008",
    "Object Minimum Diameter From Fitted Ellipse|IMGSTAT:0000009",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_pipeline(fixture_image, tmp_path):
    from process_image import process_image
    return process_image(fixture_image, str(tmp_path))


# ---------------------------------------------------------------------------
# Envelope structure
# ---------------------------------------------------------------------------

class TestEnvelopeStructure:
    def test_required_top_level_keys(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        required = {
            "schema_version", "job_id", "timestamp", "pipeline", "input",
            "qc", "traits_emitted", "derived_images", "objects",
        }
        assert required <= result.keys()

    def test_schema_version(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["schema_version"] == "1.0"

    def test_pipeline_metadata(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["pipeline"]["name"] == "seed_size_shape"
        assert result["pipeline"]["version"] == "0.1.0"

    def test_derived_images_entry(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert len(result["derived_images"]) == 1
        assert result["derived_images"][0]["role"] == "overlay"
        assert result["derived_images"][0]["filename"]


# ---------------------------------------------------------------------------
# QC flags
# ---------------------------------------------------------------------------

class TestQCFlags:
    def test_qc_matches_golden(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["qc"] == golden_output["qc"]

    def test_analysis_pass(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["qc"]["analysis_pass"] is True

    def test_color_card_present(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["qc"]["color_card_present"] is True

    def test_size_marker_detected(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["qc"]["size_marker_detected"] is True


# ---------------------------------------------------------------------------
# Canonical-only trait emission (always all traits — no output_mode)
# ---------------------------------------------------------------------------

class TestTraitEmission:
    def test_emits_six_traits(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["traits_emitted"] == golden_output["traits_emitted"]
        assert len(result["traits_emitted"]) == 6

    def test_trait_keys_match(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert result["traits_emitted"] == EXPECTED_TRAITS_ALL

    def test_all_objects_have_expected_trait_keys(self, fixture_image, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        for obj in result["objects"]:
            for trait_key in EXPECTED_TRAITS_ALL:
                assert trait_key in obj["traits"], (
                    f"Missing trait '{trait_key}' on {obj['object_id']}"
                )


# ---------------------------------------------------------------------------
# Object-level results vs golden
# ---------------------------------------------------------------------------

class TestObjectResults:
    def test_object_count_matches_golden(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        assert len(result["objects"]) == len(golden_output["objects"])

    def test_object_ids_match_golden(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        actual_ids = [o["object_id"] for o in result["objects"]]
        expected_ids = [o["object_id"] for o in golden_output["objects"]]
        assert actual_ids == expected_ids

    def test_object_qc_flags_match_golden(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        for actual_obj, expected_obj in zip(result["objects"], golden_output["objects"]):
            assert actual_obj["qc"] == expected_obj["qc"], (
                f"QC mismatch for {actual_obj['object_id']}"
            )

    def test_trait_values_within_tolerance_of_golden(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        for actual_obj, expected_obj in zip(result["objects"], golden_output["objects"]):
            obj_id = actual_obj["object_id"]
            for trait_key, expected_trait in expected_obj["traits"].items():
                assert trait_key in actual_obj["traits"], (
                    f"Missing trait '{trait_key}' on {obj_id}"
                )
                actual_val = actual_obj["traits"][trait_key]["value"]
                expected_val = expected_trait["value"]

                if expected_val is None:
                    assert actual_val is None, (
                        f"{obj_id} / {trait_key}: expected None, got {actual_val}"
                    )
                else:
                    assert actual_val == pytest.approx(expected_val, rel=TRAIT_REL_TOL), (
                        f"{obj_id} / {trait_key}: got {actual_val}, expected {expected_val}"
                    )

    def test_trait_units_match_golden(self, fixture_image, golden_output, tmp_path):
        result = run_pipeline(fixture_image, tmp_path)
        for actual_obj, expected_obj in zip(result["objects"], golden_output["objects"]):
            for trait_key, expected_trait in expected_obj["traits"].items():
                actual_unit = actual_obj["traits"][trait_key]["unit"]
                assert actual_unit == expected_trait["unit"], (
                    f"{actual_obj['object_id']} / {trait_key}: "
                    f"unit {actual_unit!r} != {expected_trait['unit']!r}"
                )
