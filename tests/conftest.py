import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "sample_seeds.jpg"
GOLDEN_FILE = Path(__file__).resolve().parent / "fixtures" / "expected_output.json"


@pytest.fixture(scope="session")
def fixture_image():
    assert FIXTURE_IMAGE.exists(), f"Fixture image not found: {FIXTURE_IMAGE}"
    return str(FIXTURE_IMAGE)


@pytest.fixture(scope="session")
def golden_output():
    assert GOLDEN_FILE.exists(), (
        f"Golden file not found: {GOLDEN_FILE}\n"
        "Generate it by running:  python tests/generate_golden.py"
    )
    with open(GOLDEN_FILE) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def api_client():
    from api.app import app as connexion_app
    with connexion_app.test_client() as client:
        yield client
