"""
HTTP-level integration tests for the /analyze endpoint.

These tests go through the full Connexion/Flask stack and validate the API
contract without checking exact trait values (that is the job of
test_process_image.py). They confirm that:
  - the endpoint is reachable and returns the right status codes
  - the response envelope matches the OpenAPI contract shape
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

def upload(client, filename="sample_seeds.jpg"):
    """POST the fixture image to /analyze."""
    with open(FIXTURE_IMAGE, "rb") as f:
        return client.post("/analyze", files={"image": (filename, f, "image/jpeg")})


# ---------------------------------------------------------------------------
# Happy path — canonical envelope (the only response shape)
# ---------------------------------------------------------------------------

class TestCanonicalFormat:
    def test_returns_200(self, api_client):
        resp = upload(api_client)
        assert resp.status_code == 200

    def test_envelope_has_required_keys(self, api_client):
        resp = upload(api_client)
        payload = resp.json()
        required = {
            "schema_version", "job_id", "timestamp", "pipeline", "qc",
            "traits_emitted", "derived_images", "objects",
        }
        assert required <= payload.keys()

    def test_schema_version(self, api_client):
        resp = upload(api_client)
        assert resp.json()["schema_version"] == "1.0"

    def test_qc_pass(self, api_client):
        resp = upload(api_client)
        qc = resp.json()["qc"]
        assert qc["analysis_pass"] is True
        assert qc["color_card_present"] is True
        assert qc["size_marker_detected"] is True

    def test_object_count(self, api_client):
        resp = upload(api_client)
        objects = resp.json()["objects"]
        assert len(objects) == EXPECTED_OBJECT_COUNT

    def test_first_object_has_all_trait_keys(self, api_client):
        resp = upload(api_client)
        first_obj = resp.json()["objects"][0]
        for trait_key in EXPECTED_TRAITS_ALL:
            assert trait_key in first_obj["traits"], f"Missing trait: {trait_key}"

    def test_traits_emitted_is_all_traits(self, api_client):
        resp = upload(api_client)
        assert resp.json()["traits_emitted"] == EXPECTED_TRAITS_ALL

    def test_first_object_trait_values_not_null(self, api_client):
        resp = upload(api_client)
        first_obj = resp.json()["objects"][0]
        for trait_key in EXPECTED_TRAITS_ALL:
            assert first_obj["traits"][trait_key]["value"] is not None, (
                f"Null value for {trait_key}"
            )

    def test_derived_images_overlay_present(self, api_client):
        resp = upload(api_client)
        derived = resp.json()["derived_images"]
        assert len(derived) == 1
        assert derived[0]["role"] == "overlay"
        assert derived[0]["url"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_missing_image_returns_400(self, api_client):
        resp = api_client.post("/analyze", data={})
        assert resp.status_code == 400

    def test_invalid_extension_returns_400(self, api_client):
        resp = api_client.post(
            "/analyze",
            files={"image": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_invalid_mimetype_returns_400(self, api_client):
        resp = api_client.post(
            "/analyze",
            files={"image": ("test.jpg", io.BytesIO(b"fake"), "application/octet-stream")},
        )
        assert resp.status_code == 400
