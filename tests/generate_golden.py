"""
Run this script once to generate tests/fixtures/expected_output.json from an
existing pipeline result. Re-run it only when an intentional pipeline change
should update the golden baseline.

Usage:
    python tests/generate_golden.py

The script looks for the most recent sample_seeds metadata JSON in results/,
strips volatile fields (job_id, timestamp, input, derived_images), and writes
the stable portion to tests/fixtures/expected_output.json.
"""

import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

VOLATILE_KEYS = {"job_id", "timestamp", "input", "derived_images"}


def find_source():
    pattern = str(RESULTS_DIR / "sample_seeds_metadata_*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        sys.exit(
            f"No results found matching:\n  {pattern}\n\n"
            "Upload uploads/sample_seeds.jpg to the running API first, then re-run."
        )
    return matches[-1]


def main():
    source_path = find_source()
    print(f"Source: {source_path}")

    with open(source_path) as f:
        data = json.load(f)

    clean = {k: v for k, v in data.items() if k not in VOLATILE_KEYS}

    FIXTURES_DIR.mkdir(exist_ok=True)
    out_path = FIXTURES_DIR / "expected_output.json"
    with open(out_path, "w") as f:
        json.dump(clean, f, indent=2)

    print(f"Written:  {out_path}")
    print(f"  pipeline:       {clean['pipeline']}")
    print(f"  schema_version: {clean['schema_version']}")
    print(f"  qc:             {clean['qc']}")
    print(f"  objects:        {len(clean['objects'])}")


if __name__ == "__main__":
    main()
