# BreedBase Image Analysis Module

**A shared standard — plus one working example — for turning plant images into breeding data.**

Modern cameras and computer vision can measure dozens of plant traits from a single photo: seed size and shape, canopy cover, leaf architecture, disease lesion area, and more. Capturing those images is now fast and cheap. The bottleneck has moved: **deploying the analysis pipelines so they actually be used AND getting that measured data into a breeding database, in a consistent form.** Pipelines rarely transfer between programs, and breeding databases have no standard way to talk to them.

This project fixes that. It defines a **standard connector** between [BreedBase](https://breedbase.org) (a widely used breeding database) and *any* image analysis pipeline, and it ships **one fully working pipeline** — seed morphometry — as a reference example. The BreedBase interfaces turns those pipelines into a push-button trigger for the analysis, analysis tools plug in without custom glue code, and results come back in one predictable format that BreedBase can store directly, complete with quality-control flags and a record of exactly how each measurement was produced.

**In plain terms:** if you have photos of seeds, you can measure them with the included pipeline today (via a web command, Python, or Docker). If you build image analysis tools, you can make yours plug into BreedBase by following one specification. If you run BreedBase, this is how you connect analysis tools to it.

> This repository also contains the reference **seed morphometry pipeline**, usable on its own — outside BreedBase — via command line, Python, or Docker.
---
## Architecture at a glance

*The module sits between BreedBase and the analysis pipelines. BreedBase never calls a pipeline directly — it hands images to the module, and the module routes, validates, and returns standardized results.*

![Architecture diagram: BreedBase submits images to the Image Analysis Module, which routes them to any registered pipeline, validates the results, and returns standardized observations to BreedBase.](docs/img/architecture.tiff)

*BreedBase appears twice because it both **sends** the image out for analysis and **receives** the finished measurements back.*

---

## Who should read this

| I am… | I want to… | Start at |
|-------|-----------|----------|
| **Curious / evaluating** | See what this does before committing | [Quick start](#quick-start-about-2-minutes) |
| **A researcher / breeder** | Measure my own seed images | [Image capture requirements](#image-capture-requirements), then [Running the reference pipeline](#running-the-reference-pipeline) |
| **A pipeline developer** | Build an analysis tool that plugs into BreedBase | [The API contract](#the-api-contract), then [Building a compatible pipeline](#building-a-compatible-pipeline) |
| **A BreedBase admin / developer** | Connect a pipeline to BreedBase | [Architecture](#architecture-at-a-glance), then [The API contract](#the-api-contract) |
| **Evaluating the design** | Understand the architecture and rationale | [Architecture](#architecture-at-a-glance), then [Design principles](#design-principles) |

---

## Key terms

<details>
<summary>Click to expand a short glossary</summary>

- **BreedBase** — an open-source breeding database used by many public breeding programs to store trait data, pedigrees, and field trials.
- **Field Book** — a free Android app breeders use to collect trait data in the field; feeds into BreedBase.
- **BrAPI (Breeding API)** — a common data standard that lets breeding software exchange data in a consistent structure. This module's output is BrAPI-compatible.
- **Ontology / IMGSTAT** — a controlled vocabulary that gives each trait a standard name and ID so "seed diameter" means the same thing everywhere. IMGSTAT is the ontology for image-derived traits used here.
- **Trait** — a measurable characteristic (e.g., seed diameter, area).
- **Morphometry** — measurement of size and shape.
- **QC flag** — a quality-control marker on a result (e.g., "did the calibration succeed?") used to decide whether a measurement is trustworthy.
- **Provenance** — the record of how a result was produced (which pipeline, which version, when).
- **Output envelope** — the single, standard JSON structure every result comes back in.
- **Size marker** — a circular object of known real-world diameter placed in the photo, used to convert pixels to millimeters.
- **Color card** — a calibration card placed in the photo, used to correct for lighting and color differences between images.
- **FAIR** — data principles: Findable, Accessible, Interoperable, Reusable.

</details>

---

## Quick start (about 2 minutes)

Run the reference pipeline on the sample image bundled with this repository — no local Python setup required.

> **Heads-up — Docker Image Name & Version** The reference pipeline `hkmanchi/sorghum-breedbase-image-pipeline` is specific to sorghum, but the framework is crop-agnostic. Always pin an explicit version tag (`:<version>`) rather than `:latest` — see [Versioning and image tags](#versioning-and-image-tags).

```bash
docker pull hkmanchi/sorghum-breedbase-image-pipeline:<version>

docker run --rm \
  -v "$(pwd)/results:/results" \
  hkmanchi/sorghum-breedbase-image-pipeline:<version> \
  bb-analyze /app/tests/fixtures/sample_seeds.jpg --output-dir /results --output-mode all
```

You will get two files in `./results/`:

- an **annotated overlay image** — your photo with each seed outlined and numbered
- a **results file** — every trait, for every seed, with units

Example output:

| Object | Max diameter | Min diameter | Area |
|--------|-------------|-------------|------|
| obj_001 | 4.3 mm | 3.1 mm | 14.2 mm² |
| obj_002 | 4.1 mm | 3.0 mm | 13.6 mm² |

<img src="https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/blob/main/docs/img/example_overlay.tiff" alt="Example: an image of seeds on the left; the same image with each seed outlined and labeled on the right." width="600" height="400">

To go further, see [Running the reference pipeline](#running-the-reference-pipeline).


## What this repository includes

**Included:**

- A reference Flask/Connexion backend implementing the BreedBase image analysis integration layer
- A standardized API contract (OpenAPI 3.0, contract `info.version` 2.0.0) plus a standalone `envelope.schema.json` (JSON Schema 2020-12) defining how BreedBase communicates with pipelines
- A pipeline interface specification describing what any compliant pipeline must accept and return
- A complete reference pipeline (seed morphometry)
- Documentation for reproducible deployment

**Not included:** BreedBase UI code (lives in the BreedBase repository), species-specific trait ontologies, and production infrastructure such as job queues or cloud storage.

**Building your own pipeline?** Implement the interface in [Building a compatible pipeline](#building-a-compatible-pipeline) and expose a `POST /analyze` endpoint conforming to [The API contract](#the-api-contract). The seed morphometry pipeline here is the model to copy.

---

## How the integration works

BreedBase does not call pipelines directly. It submits images and metadata to this module's `POST /analyze` endpoint; the module routes the request to the right pipeline, validates the output against the contract, and returns a standardized JSON result that BreedBase stores as trait observations.

Step-by-step:

1. An image is captured in the field and stored in BreedBase (via Field Book or direct upload)
2. A user or automated process triggers analysis from the BreedBase UI
3. BreedBase submits the image to this module via `POST /analyze` (the request carries only the image; pipeline-specific tuning is internal to each pipeline)
4. The module routes the request to the registered pipeline
5. The pipeline processes the image and returns a standardized JSON result to the module
6. The module validates the result and returns it to BreedBase
7. BreedBase stores per-object trait observations and derived overlay images, associating them with the relevant stocks and projects

**The module handles for every pipeline:** HTTP routing and validation against the OpenAPI contract, input preprocessing (image decoding, metadata parsing), output schema validation, error handling, and provenance injection (timestamp, job ID). **Pipeline authors implement only the analysis logic** — no HTTP handling, schema validation, or BreedBase-specific formatting.

---

## The API Contract

The full contract is in `config/openapi.yml` (`openapi: 3.0.0`, `info.version: 2.0.0`); the canonical envelope also has a standalone, machine-checkable definition in `envelope.schema.json` (JSON Schema 2020-12). A rendered, browsable version is published at [API docs](#) *(link once GitHub Pages / Redoc is set up)*. Summary below.

### Endpoint

```
POST /analyze
```

### Request (multipart form upload)

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `image` | Yes | File (JPEG or PNG) | The image to analyze |

The request carries **only the image** — one canonical response shape, no output-shape or trait-count switches. Pipeline-specific tuning (e.g. the size-marker diameter) is configured inside the pipeline, not sent over HTTP; see [Running the reference pipeline](#running-the-reference-pipeline) for the standalone `--marker-diameter` option.

### Response

Returns the standard JSON envelope described in [The output envelope](#the-output-envelope). There is exactly one response shape.

### Example - curl

```bash
curl -X POST http://localhost:8000/analyze \
  -F "image=@path/to/image.jpg"
```

### Example - Python

```python
import requests

with open("path/to/image.jpg", "rb") as f:
    response = requests.post(
        "http://localhost:8000/analyze",
        files={"image": f},
    )

result = response.json()
```

### BrAPI compatibility

Trait keys use the format `Human-readable name|IMGSTAT:ID` (e.g., `Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008`) and are structured for direct ingestion into BreedBase as BrAPI-compatible observations. The unit is not free-standing metadata: each IMGSTAT term bundles a trait, a measurement method, and a scale (the unit), so the pipeline links every value to the IMGSTAT term whose scale matches the unit it measured in — the term, not a free-form string, is what fixes the unit.

**The IMGSTAT ID is authoritative.** The ID (e.g., `IMGSTAT:0000008`) is the canonical identifier for a trait; the human-readable label is *not* free text and must exactly match the official IMGSTAT label registered for that ID. Pipelines must emit valid IMGSTAT IDs and validate their output against a **pinned IMGSTAT release version**, so that any result keyed to a given ID means the same thing across pipelines, programs, and time. For the authoritative term list and release versions, see the [IMGSTAT ontology repo](https://github.com/USDA-ARS-GBRU/imgstat-ontology).

---

## Building a Compatible Pipeline

Any image analysis pipeline can join this framework by satisfying the interface below. The seed morphometry pipeline here is the reference — copy its structure. Full specification: `docs/PIPELINE_REQUIREMENTS.md`. To check your work, run the conformance test kit *(see [Contributing](#contributing))*.

### What a pipeline must accept

| Input | Type | Description |
|-------|------|-------------|
| Image path | string | Path to the image file on disk |
| Output directory | string | Where derived images and sidecar files are written |
| Metadata | dict (optional) | Session-level metadata passed through from BreedBase |
| Parameters | dict (optional) | Pipeline-specific parameters (e.g., marker diameter, thresholds) |

### What a pipeline must return

A JSON payload (printed to stdout or returned to the caller) containing `pipeline.name`, `pipeline.version`, `qc`, `objects`, and `traits_emitted`. See [The output envelope](#the-output-envelope) for the full structure and a complete example — it is not repeated here.

Minimum QC block:

```json
"qc": { "analysis_pass": true, "object_count": 65 }
```

`analysis_pass` must be `true` only when the result is reliable enough to store (specific to the pipeline analyzing the image). Additional QC fields (e.g., `size_marker_detected`, `color_card_present`) are encouraged and passed through to BreedBase.

### Pipeline requirements checklist

- [ ] Deterministic — the same image and parameters always produce the same output
- [ ] Every trait value is linked to an IMGSTAT term whose scale (unit) matches how it was measured
- [ ] `pipeline.name` and `pipeline.version` present in every result
- [ ] `qc.analysis_pass` accurately reflects reliability
- [ ] No hard-coded file paths
- [ ] Output written only to the designated output directory
- [ ] Runnable as a Docker container
*- [ ] Runnable as a Docker container*

### Recommended repository structure

```
my-pipeline/
├── pipelines/           # Core analysis modules
├── api/
│   ├── app.py           # Connexion/Flask server (copy from this repo)
│   └── config/openapi.yml
├── process_image.py     # analyze_image() pure function + CLI wrapper
├── cli.py               # CLI entry point
├── pyproject.toml
├── tests/
│   └── fixtures/
├── Dockerfile
└── README.md
```

The `api/` directory and `openapi.yml` contract can be reused directly with minimal change. You implement `process_image.py` and the modules under `pipelines/`.

---

## The output envelope

Every compliant pipeline returns the same JSON structure — that uniformity is what lets BreedBase store results from any pipeline without special-casing.

```json
{
  "schema_version": "1.0",
  "job_id": "3f2a1b4c-...",
  "timestamp": "2024-06-15T14:32:00Z",
  "pipeline": { "name": "seed_size_shape", "version": "0.1.0" },
  "input": { "image_filename": "tray_001.jpg" },
  "qc": {
    "analysis_pass": true,
    "color_card_present": true,
    "size_marker_detected": true,
    "object_count": 65
  },
  "traits_emitted": [
    "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008",
    "Object Minimum Diameter From Fitted Ellipse|IMGSTAT:0000009"
  ],
  "derived_images": [
    { "role": "overlay", "filename": "tray_001_overlay.jpg", "url": "..." }
  ],
  "objects": [
    {
      "object_id": "obj_001",
      "source_label": "1",
      "bbox": { "x": 713, "y": 552, "w": 42, "h": 40 },
      "qc": { "contour_found": true, "ellipse_fit_ok": true },
      "traits": {
        "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008": {
          "value": 4.3, "unit": "mm"
        }
      }
    }
  ]
}
```

### Field reference

| Field | Description |
|-------|-------------|
| `schema_version` | Version of the output-envelope contract this payload conforms to (currently `"1.0"`). Lets a consumer assert the shape at runtime instead of inferring it. Independent of `pipeline.version` and the release/Docker version |
| `job_id` | UUID assigned by the module at request time |
| `timestamp` | ISO 8601 timestamp of the analysis |
| `pipeline.name` / `pipeline.version`| Which pipeline that produced the result, and its version |
| `qc.analysis_pass` | `true` only when reliable. If `false`, do not store trait values without review |
| `qc.color_card_present` | Whether a color card was detected and applied. If `false`, color traits may be unreliable |
| `qc.size_marker_detected` | Whether the size marker was found. If `false`, dimensions are in **pixels, not mm**, and `unit` reflects that |
| `objects[].object_id` | Sequential ID, left-to-right, top-to-bottom; stable across repeated analyses |
| `traits` keys | Format `Human-readable name\|IMGSTAT:ID`. The **IMGSTAT ID is authoritative**; the label must exactly match the official IMGSTAT label for that ID (not free text) and is validated against a pinned IMGSTAT release. Each value is reported in the scale (unit) defined by its IMGSTAT term, so the term — not a free-form unit string — is what fixes the unit. See the [IMGSTAT ontology repo](https://github.com/USDA-ARS-GBRU/imgstat-ontology)

---

## Design Principles

- **Reproducibility** — deterministic outputs and versioned pipelines; the same image always produces the same result.
- **Interoperability** — OpenAPI contract and BrAPI compatibility; trait keys follow the IMGSTAT ontology for direct ingestion into BreedBase.
- **Modularity** — pipelines are pluggable; any compliant pipeline registers without changes to the integration layer.
- **Transparency** — QC flags and provenance are required fields, not optional extras.
- **Community extensibility** — the interface is an open standard; any research group can build and publish a compliant pipeline for any crop or trait class.

---

## Image capture requirements

The reference pipeline's accuracy depends on how the photo is taken. Every image must include:

- **A neutral, uncluttered background that contrasts with target object** (a plain matte sheet works well) so objects segment cleanly.
- **One color calibration card**, fully visible and unobstructed, for lighting/color correction.
- **One circular size marker of known diameter** (default assumed `0.75"`) for the pixel-to-millimeter conversion. If yours differs, pass the correct value (`--marker-diameter` / `marker_diameter_in`).
- **Even, diffuse lighting** with minimal shadows and no glare on the seeds, card, or marker.
- **Seeds/organs spread out** so they do not touch or overlap (touching objects may be merged).

<img src="https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/blob/main/docs/img/capture_example.jpg" alt="Example of a correctly set up photo: seeds spread on a neutral background with a color card and circular size marker." width="300" height="200">

If the color card or size marker is not detected, the corresponding QC flag will be `false` — see [Troubleshooting](#troubleshooting).

---

## Running the reference pipeline

The seed morphometry pipeline segments each object, applies color correction, converts pixels to millimeters using the size marker, and returns per-object morphometric traits keyed by IMGSTAT ontology IDs. It runs inside BreedBase or standalone via CLI, Python, or Docker.

### How the pipeline works

1. **Color card detection** — locate the card and apply color correction, normalizing lighting across images.
2. **Size marker detection** — the marker of known diameter sets the pixel-to-millimeter factor.
3. **Reference masking** — the card and marker are masked out so they aren't measured as objects.
4. **Object segmentation** — seeds are segmented via HSV color-space thresholding and morphological operations; connected-component analysis identifies individual objects.
5. **Object labeling** — objects labeled row-wise (left-to-right, top-to-bottom).
6. **Morphometric extraction** — area, perimeter, ellipse diameters, solidity, and convex hull area computed per object.
7. **Result packaging** — traits, QC flags, and provenance assembled into the output envelope.

### Installation

**Prerequisites:** Python 3.9+, `pip`, and the repo cloned locally:

```bash
git clone https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module
cd breedbase-image-analysis-module
```

**Core pipeline only** (CLI + Python API, no web server):

```bash
pip install .
```

**With REST API server** (adds Connexion, Flask, Gunicorn):

```bash
pip install ".[api]"
```

**Editable install for development:**

```bash
pip install -e ".[api]"
```

Verify:

```bash
bb-analyze --help
```

If not found, confirm your Python environment's `bin`/`Scripts` directory is on your `PATH`.

### Command-Line Interface

`bb-analyze` runs the pipeline on a single image. `--output-dir` is required — results are always written to files.

```bash
bb-analyze path/to/image.jpg --output-dir ./results
```

Writes and prints the paths to:

- `image_metadata_<job_id>.json` — the full output envelope
- `image_ResultImage_<job_id>.png` — your image with object boundaries and labels drawn

**Output file type:**

```bash
bb-analyze path/to/image.jpg --output-dir ./results --format json   # default
bb-analyze path/to/image.jpg --output-dir ./results --format csv    # one row per object
```

CSV flattens the `objects` array into one row per object, repeating envelope-level metadata alongside each object's fields — convenient for spreadsheets. Use JSON for programmatic or BreedBase use.

> **Note — traits emitted.** The pipeline always emits every trait it computes (all six morphometric traits). There is one canonical output. Which traits a pipeline computes is a property of the pipeline, not a request option.

**Size marker diameter** (must match your physical marker, in inches; drives pixel→mm):

```bash
bb-analyze path/to/image.jpg --output-dir ./results --marker-diameter 1.0
```

**Combined:**

```bash
bb-analyze path/to/image.jpg \
  --output-dir ./results \
  --format csv \
  --marker-diameter 0.75
```

Exits `0` on success (prints file paths); exits `1` on failure (prints a JSON error to stdout).

### Python API

`analyze_image` is a pure function — no file I/O or side effects. Use it in notebooks and batch scripts.

```python
from process_image import analyze_image

result = analyze_image("path/to/image.jpg")
```
Check image-level QC:

```python
print(result["qc"])
# {'analysis_pass': True, 'color_card_present': True,
#  'size_marker_detected': True, 'object_count': 65}
```

`analysis_pass` is `True` only when the color card, size marker, and at least one object were all detected.

Access per-object traits:

```python
for obj in result["objects"]:
    d = obj["traits"]["Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008"]
    print(f"{obj['object_id']}: {d['value']} {d['unit']}")
```

**Return value:** `qc` (dict), `objects` (list), `traits_emitted` (list), `overlay_img` (NumPy array of the annotated image).

Batch example:

```python
from pathlib import Path
from process_image import analyze_image

results = []
for img_path in sorted(Path("./session_images").glob("*.jpg")):
    result = analyze_image(str(img_path))
    if result["qc"]["analysis_pass"]:
        for obj in result["objects"]:
            row = {"image": img_path.name, "object_id": obj["object_id"]}
            row.update({k: v["value"] for k, v in obj["traits"].items()})
            results.append(row)
    else:
        print(f"WARNING: QC failed for {img_path.name} — skipping")
# results -> list of flat dicts, ready for pandas or CSV
```

### Docker

Recommended for BreedBase integration and for anyone who prefers not to manage a Python environment.

Pin an explicit version tag (`:<version>`), not `:latest` — see [Versioning and image tags](#versioning-and-image-tags).

```bash
docker pull hkmanchi/sorghum-breedbase-image-pipeline:latest   # linux/amd64
```

Run the REST API server:

```bash
docker run -p 8000:8000 hkmanchi/sorghum-breedbase-image-pipeline:<version>
```

Serves at `http://localhost:8000` (see [The API contract](#the-api-contract)).

Analyze a local image:

```bash
docker run --rm \
  -v "$(pwd)/images:/images" \
  -v "$(pwd)/results:/results" \
  hkmanchi/sorghum-breedbase-image-pipeline:<version> \
  bb-analyze /images/tray_001.jpg --output-dir /results
```

Or `docker-compose up` (see `docker-compose.yml` for ports and volumes).

---

## Versioning and image tags

Releases follow [Semantic Versioning](https://semver.org); the full policy is in [`VERSIONING.md`](https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/blob/main/VERSIONING.md). Three version numbers move independently:
 
| Version | What it tags | Where it lives |
|---------|--------------|----------------|
| **Release version** | The code and the published Docker image | git tag / GitHub Release / Docker tag (`:vX.Y.Z`) |
| **Contract version** | The transport contract | `info.version` in `config/openapi.yml` (currently `2.0.0`) |
| **Envelope `schema_version`** | The output-envelope payload shape | `schema_version` field in every result (currently `"1.0"`) |
 
**Always pin an explicit version tag; do not use `:latest`.** `:latest` is a moving pointer and can change what you run out from under you. Pinning a tag (`:vX.Y.Z`) — or, for full immutability, a digest (`@sha256:...`) — guarantees the exact image.
 
Two release lines matter for this repository:
 
- **`v1.0.1` — legacy, frozen.** The last release carrying the older BreedBase-compatibility response shape (single-trait, `?format=breedbase`). It is immutable and kept running only for older BreedBase instances that have not yet migrated. Do not build new work on it.
- **`v2.0.0` — canonical-only (forthcoming).** The first release of the standardized, single-envelope contract described in this README: `POST /analyze`, image-only request, `schema_version`-stamped envelope, no `output_mode`/`format`. It is being cut as the next release; pin `:v2.0.0` once published.
---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `bb-analyze: command not found` | Python `bin`/`Scripts` not on `PATH` | Activate your environment or add it to `PATH` |
| `size_marker_detected: false`, dimensions in pixels | Marker missing, obscured, or wrong assumed diameter | Ensure a clear circular marker is present; set `--marker-diameter` to its real size |
| `color_card_present: false` | Color card missing, obscured, or poorly lit | Include a fully visible color card; improve lighting |
| `object_count: 0` / no objects | Poor contrast, objects touching, cluttered background | Use a neutral background, spread objects apart, improve lighting |
| `analysis_pass: false` | One or more of the above | Check the individual QC flags to see which step failed |

---
## Repository Structure

```
breedbase-image-analysis-module/
│
│   # Integration framework (reusable across pipelines)
├── api/
│   ├── app.py                     # Connexion/Flask API server
│   └── config/openapi.yml         # OpenAPI 3.0 contract
│
│   # Reference pipeline: seed morphometry
├── pipelines/
│   ├── color_correction.py        # Color card detection and correction
│   ├── ref_mask.py                # Color card / size marker masking
│   ├── seed_mask.py               # Object segmentation
│   ├── object_labeling.py         # Row-wise object labeling
│   ├── shape_analysis.py          # Morphometric trait calculation
│   ├── size_marker_metadata.py    # Size marker calibration (pixels → mm)
│   ├── image_math.py              # Image math utilities
│   └── utils.py                   # Shared helpers
│
├── process_image.py               # analyze_image() (pure) + process_image() (CLI wrapper)
├── cli.py                         # bb-analyze CLI entry point
├── pyproject.toml               
│
├── tests/
│   ├── test_process_image.py
│   ├── test_api.py
│   ├── conftest.py
│   └── fixtures/
│       ├── sample_seeds.jpg
│       └── expected_output.json   # Golden output for regression testing
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt / requirements-dev.txt
```

`api/` is the reusable framework layer. `pipelines/`, `process_image.py`, and `cli.py` are the reference pipeline. Future pipeline repositories reuse `api/` and replace the rest.

---

## Reproducibility and provenance

Every result includes provenance the framework injects automatically: `pipeline.name`, `pipeline.version`, `timestamp`, `input.image_filename`, and `job_id`. This supports IMGSTAT-style image-derived trait ontologies, QC/provenance tracking, and FAIR data principles.

---
## Status and maturity

The framework and reference pipeline are **deployed and operational in a dedicated BreedBase instance**, with confirmed end-to-end flow from image to stored observation. Not yet included: job queue, cloud storage, and other production-scale infrastructure (see [What this repository includes](#what-this-repository-includes)).

---

## Contributing

This is an open standard — new pipelines and improvements are welcome. See [`CONTRIBUTING.md`](https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/blob/main/CONTRIBUTING.md) for how to propose a pipeline, and run the conformance test kit *(to be added)* to verify your pipeline produces a valid envelope before submitting.

---

## License

This repository is dual-licensed. The software and source code are licensed under the
**Apache License 2.0** (see [`LICENSE`](https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/blob/main/LICENSE)), which permits reuse, modification, and redistribution — including commercially — with attribution and an explicit patent grant.
The documentation, data, figures, and vocabulary/ontology content are licensed under
**Creative Commons Attribution 4.0 International (CC BY 4.0)** (see [`LICENSE.md`](https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/blob/main/LICENSE.md)).
Where a file could fall under either, the code license governs source code and the content
license governs prose, data, and media. Both licenses require attribution when reusing this work.

---

## Citation

If you use this framework or the reference pipeline, please cite it. A manuscript and Zenodo DOI are forthcoming; in the interim, cite this repository.

```bibtex
@software{breedbase_image_analysis_module,
  title     = {BreedBase Image Analysis Module},
  author    = {Manching, Heather and Maza, Ben and Hulse-Kemp, Amanda and Mueller, Lukas },
  year      = {2026},
  version   = {0.1.0},
  url       = {https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/tree/main}
}
```

---

