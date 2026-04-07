"""
HTTP-level integration tests for the /upload endpoint.

These tests go through the full Connexion/Flask stack and validate the API
contract without checking exact trait values (that is the job of
test_process_image.py). They confirm that:
  - the endpoint is reachable and returns the right status codes
  - the response envelope matches the OpenAPI contract shape
  - all three response formats work (canonical, single, legacy)
  - expected error cases return appropriate 4xx codes
"""

import io
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "sample_seeds.jpg"

EXPECTED_OBJECT_COUNT = 65

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

def upload(client, query="", filename="sample_seeds.jpg"):
    """POST the fixture image to /upload with optional query string."""
    with open(FIXTURE_IMAGE, "rb") as f:
        url = f"/upload{query}"
        return client.post(url, files={"image": (filename, f, "image/jpeg")})


# ---------------------------------------------------------------------------
# Happy path — canonical format (default)
# ---------------------------------------------------------------------------

class TestCanonicalFormat:
    def test_returns_200(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        assert resp.status_code == 200

    def test_envelope_has_required_keys(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        payload = resp.json()
        required = {
            "job_id", "timestamp", "pipeline", "qc",
            "output_mode", "traits_emitted", "derived_images", "objects",
        }
        assert required <= payload.keys()

    def test_qc_pass(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        qc = resp.json()["qc"]
        assert qc["analysis_pass"] is True
        assert qc["color_card_present"] is True
        assert qc["size_marker_detected"] is True

    def test_object_count(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        objects = resp.json()["objects"]
        assert len(objects) == EXPECTED_OBJECT_COUNT

    def test_first_object_has_all_trait_keys(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        first_obj = resp.json()["objects"][0]
        for trait_key in EXPECTED_TRAITS_ALL:
            assert trait_key in first_obj["traits"], f"Missing trait: {trait_key}"

    def test_first_object_trait_values_not_null(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        first_obj = resp.json()["objects"][0]
        for trait_key in EXPECTED_TRAITS_ALL:
            assert first_obj["traits"][trait_key]["value"] is not None, (
                f"Null value for {trait_key}"
            )

    def test_derived_images_overlay_present(self, api_client):
        resp = upload(api_client, "?output_mode=all")
        derived = resp.json()["derived_images"]
        assert len(derived) == 1
        assert derived[0]["role"] == "overlay"
        assert derived[0]["url"]


# ---------------------------------------------------------------------------
# Output mode: single
# ---------------------------------------------------------------------------

class TestSingleMode:
    def test_single_mode_output_mode_field(self, api_client):
        resp = upload(api_client, "?output_mode=single")
        assert resp.json()["output_mode"] == "single"

    def test_single_mode_one_trait_emitted(self, api_client):
        resp = upload(api_client, "?output_mode=single")
        traits_emitted = resp.json()["traits_emitted"]
        assert len(traits_emitted) == 1
        assert traits_emitted[0] == "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008"

    def test_single_mode_each_object_has_one_trait(self, api_client):
        resp = upload(api_client, "?output_mode=single")
        for obj in resp.json()["objects"]:
            assert len(obj["traits"]) == 1


# ---------------------------------------------------------------------------
# Legacy BreedBase format
# ---------------------------------------------------------------------------

class TestLegacyFormat:
    def test_legacy_format_keys(self, api_client):
        resp = upload(api_client, "?format=breedbase")
        payload = resp.json()
        assert {"image_link", "trait_name", "results", "info"} <= payload.keys()

    def test_legacy_format_result_count(self, api_client):
        resp = upload(api_client, "?format=breedbase")
        assert len(resp.json()["results"]) == EXPECTED_OBJECT_COUNT

    def test_legacy_format_result_keys(self, api_client):
        resp = upload(api_client, "?format=breedbase")
        first = next(iter(resp.json()["results"].values()))
        assert {"trait_value", "image_link"} <= first.keys()

    def test_legacy_format_bb_alias(self, api_client):
        resp = upload(api_client, "?format=bb")
        assert resp.status_code == 200
        assert "results" in resp.json()

    def test_legacy_format_info_is_qc(self, api_client):
        resp = upload(api_client, "?format=breedbase")
        info = resp.json()["info"]
        assert info["analysis_pass"] is True


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_missing_image_returns_400(self, api_client):
        resp = api_client.post("/upload", data={})
        assert resp.status_code == 400

    def test_invalid_extension_returns_400(self, api_client):
        resp = api_client.post(
            "/upload",
            files={"image": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_invalid_mimetype_returns_400(self, api_client):
        resp = api_client.post(
            "/upload",
            files={"image": ("test.jpg", io.BytesIO(b"fake"), "application/octet-stream")},
        )
        assert resp.status_code == 400
