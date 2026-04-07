# BreedBase Image Analysis Module

A standardized, API-driven framework for integrating automated image analysis pipelines into BreedBase. The module defines the interface contract that any compliant pipeline must satisfy, handles communication between BreedBase and registered pipelines, and returns structured, ontology-keyed trait measurements with QC flags and provenance metadata suitable for storage as breeding observations.

This repository also provides a fully functional **seed morphometry pipeline** as the reference implementation. It demonstrates how the framework operates end to end and is available for direct use outside of BreedBase via CLI, Python API, or Docker.

**Field Book → BreedBase → Image Analysis Module → BreedBase → Breeder**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Who Should Read This](#2-who-should-read-this)
3. [Architecture and Integration Flow](#3-architecture-and-integration-flow)
4. [The API Contract](#4-the-api-contract)
5. [Building a Compatible Pipeline](#5-building-a-compatible-pipeline)
6. [The Standardized Output Envelope](#6-the-standardized-output-envelope)
7. [Design Principles](#7-design-principles)
8. [Reference Implementation: Seed Morphometry Pipeline](#8-reference-implementation-seed-morphometry-pipeline)
   - [8.1 How the Pipeline Works](#81-how-the-pipeline-works)
   - [8.2 Installation](#82-installation)
   - [8.3 Usage: Command-Line Interface](#83-usage-command-line-interface)
   - [8.4 Usage: Python API](#84-usage-python-api)
   - [8.5 Usage: Docker](#85-usage-docker)
9. [Repository Structure](#9-repository-structure)
10. [Reproducibility and Provenance](#10-reproducibility-and-provenance)
11. [Citation](#11-citation)

---

## 1. Overview

### What this repository provides

- A reference Flask/Connexion backend implementing the BreedBase image analysis integration layer
- A standardized API contract (OpenAPI 3.0) defining how BreedBase communicates with analysis pipelines
- A structured pipeline interface specification describing what any compliant pipeline must accept and return
- A complete reference pipeline (seed morphometry) demonstrating the framework in practice
- Documentation for reproducible deployment

### What this repository does NOT include

- BreedBase UI code (hosted in the BreedBase repository)
- Species-specific trait ontologies
- Production infrastructure such as job queues or cloud storage

### How future pipeline repositories relate to this one

This repository defines the standard. Independent image analysis pipelines intended for BreedBase integration should implement the interface described in [Section 5](#5-building-a-compatible-pipeline) and expose a `POST /analyze` endpoint conforming to the API contract in [Section 4](#4-the-api-contract). The seed morphometry pipeline in this repository is the model for what those repositories should look like.

---

## 2. Who Should Read This

This README serves several distinct audiences. Use the table below to find your entry point.

| I am... | I want to... | Start at |
|---------|-------------|----------|
| A **BreedBase administrator or developer** | Connect an existing or new pipeline to BreedBase | [Section 3](#3-architecture-and-integration-flow), then [Section 4](#4-the-api-contract) |
| A **pipeline developer** | Build a new image analysis pipeline that integrates with BreedBase | [Section 4](#4-the-api-contract), then [Section 5](#5-building-a-compatible-pipeline) |
| A **researcher** who wants to run the seed morphometry pipeline directly | Use the pipeline outside of BreedBase | [Section 8](#8-reference-implementation-seed-morphometry-pipeline) |
| A **developer evaluating the framework** | Understand the architecture and design decisions | [Section 3](#3-architecture-and-integration-flow), then [Section 7](#7-design-principles) |

---

## 3. Architecture and Integration Flow

### System overview

```
Field Book → BreedBase → Image Analysis Module → BreedBase → Breeder
```

The Image Analysis Module sits between BreedBase and any registered analysis pipeline. BreedBase does not call pipelines directly. Instead, it submits images and metadata to this module's `POST /analyze` endpoint, which routes the request to the appropriate pipeline, validates the output against the interface contract, and returns a standardized JSON envelope that BreedBase stores as trait observations.

### Step-by-step integration flow

1. An image is captured in the field and stored in BreedBase (via Field Book or direct upload)
2. A user or automated process triggers analysis from the BreedBase UI
3. BreedBase submits the image to this module via `POST /analyze`, including optional pipeline parameters and metadata
4. The module routes the request to the registered pipeline
5. The pipeline processes the image and returns a standardized JSON result to the module
6. The module validates the result and returns it to BreedBase
7. BreedBase stores per-object trait observations and derived overlay images, associating them with the relevant stocks and projects

### What the module handles on behalf of pipelines

- HTTP request routing and validation against the OpenAPI contract
- Input preprocessing (image decoding, metadata parsing)
- Output schema validation before results are returned to BreedBase
- Error handling and failure response formatting
- Provenance field injection (timestamp, job ID)

Pipeline authors implement only the analysis logic. They do not need to implement HTTP handling, schema validation, or BreedBase-specific formatting.

---

## 4. The API Contract

The full contract is defined in `config/openapi.yml`. This section summarizes the key details.

### Primary endpoint

```
POST /analyze
```

### Request

Multipart form upload:

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `image` | Yes | File (JPEG or PNG) | The image to analyze |
| `output_mode` | No | string | `single` (default) or `all` — controls how many traits are emitted |
| `format` | No | string | `canonical` (default) or `breedbase` — response format variant |
| `marker_diameter_in` | No | float | Physical diameter of the size reference marker in inches (default: `0.75`) |

### Response

The endpoint returns the standardized JSON envelope described in [Section 6](#6-the-standardized-output-envelope).

### Example request using curl

```bash
curl -X POST http://localhost:8000/analyze \
  -F "image=@path/to/image.jpg" \
  -F "output_mode=all"
```

### Example request using Python

```python
import requests

with open("path/to/image.jpg", "rb") as f:
    response = requests.post(
        "http://localhost:8000/analyze",
        files={"image": f},
        data={"output_mode": "all"}
    )

result = response.json()
```

### BrAPI compatibility

Trait keys in the output follow the IMGSTAT ontology format (`Human-readable name|ONTOLOGY:ID`) and are structured for direct ingestion into BreedBase as BrAPI-compatible observations. Units are always explicit. See [Section 6](#6-the-standardized-output-envelope) for the full output structure.

---

## 5. Building a Compatible Pipeline

Any image analysis pipeline can be integrated into this framework by satisfying the interface contract described here. The seed morphometry pipeline in this repository is the reference implementation — its structure, inputs, outputs, and packaging are the model for what a compatible pipeline repository should look like.

Full specification: `docs/PIPELINE_REQUIREMENTS.md`

### What a pipeline must accept

| Input | Type | Description |
|-------|------|-------------|
| Image path | string | Path to the image file on disk |
| Output directory | string | Directory where derived images and sidecar files should be written |
| Metadata | dict (optional) | Session-level metadata passed through from the BreedBase request |
| Parameters | dict (optional) | Pipeline-specific analysis parameters (e.g., marker diameter, thresholds) |

### What a pipeline must return

The pipeline must return a JSON payload (printed to stdout or returned to the caller) containing:

| Field | Required | Description |
|-------|----------|-------------|
| `pipeline.name` | Yes | Pipeline identifier string |
| `pipeline.version` | Yes | Semantic version string (e.g., `"1.0.0"`) |
| `qc` | Yes | Image-level QC flags — see below |
| `objects` | Yes | List of per-object records — see below |
| `traits_emitted` | Yes | List of trait keys included in this result |

#### Required QC flags

```json
"qc": {
  "analysis_pass": true,
  "object_count": 65
}
```

`analysis_pass` must be `true` only when the pipeline considers the result reliable enough to store as observations. Additional pipeline-specific QC fields (e.g., `size_marker_detected`, `color_card_present`) are encouraged and will be passed through to BreedBase.

#### Per-object record structure

```json
{
  "object_id": "obj_001",
  "bbox": { "x": 713, "y": 552, "w": 42, "h": 40 },
  "qc": { "contour_found": true },
  "traits": {
    "Trait Human-Readable Name|ONTOLOGY:ID": {
      "value": 4.3,
      "unit": "mm"
    }
  }
}
```

Trait keys must follow the `Name|ONTOLOGY:ID` format. Values and units must always be explicit — never omit units or leave them implicit.

### Pipeline requirements checklist

- [ ] Deterministic — the same image and parameters always produce the same output
- [ ] All trait values include explicit units
- [ ] `pipeline.name` and `pipeline.version` present in every result
- [ ] `qc.analysis_pass` accurately reflects result reliability
- [ ] No hard-coded file paths
- [ ] Output written only to the designated output directory
- [ ] Installable as a Python package or runnable as a Docker container

### Recommended repository structure for a new pipeline

A new pipeline repository should follow the structure of this repository:

```
my-pipeline/
├── pipelines/           # Core analysis modules
├── api/
│   ├── app.py           # Connexion/Flask server (can be copied from this repo)
│   └── config/openapi.yml
├── process_image.py     # analyze_image() pure function + CLI wrapper
├── cli.py               # CLI entry point
├── pyproject.toml
├── tests/
│   └── fixtures/
├── Dockerfile
└── README.md
```

The `api/` directory and `openapi.yml` contract can be reused directly from this repository with minimal modification. Pipeline authors implement `process_image.py` and the modules under `pipelines/`.

---

## 6. The Standardized Output Envelope

All pipelines registered with this framework return results in the same JSON envelope structure. This standardization is what allows BreedBase to store results from any compliant pipeline without format-specific handling.

### Full envelope example

```json
{
  "job_id": "3f2a1b4c-...",
  "timestamp": "2024-06-15T14:32:00Z",
  "pipeline": {
    "name": "seed_size_shape",
    "version": "0.1.0"
  },
  "input": {
    "image_filename": "tray_001.jpg"
  },
  "qc": {
    "analysis_pass": true,
    "color_card_present": true,
    "size_marker_detected": true,
    "object_count": 65
  },
  "output_mode": "all",
  "traits_emitted": [
    "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008",
    "Object Minimum Diameter From Fitted Ellipse|IMGSTAT:0000009"
  ],
  "derived_images": [
    {
      "role": "overlay",
      "filename": "tray_001_overlay.jpg",
      "url": "..."
    }
  ],
  "objects": [
    {
      "object_id": "obj_001",
      "source_label": "1",
      "bbox": { "x": 713, "y": 552, "w": 42, "h": 40 },
      "qc": {
        "contour_found": true,
        "ellipse_fit_ok": true
      },
      "traits": {
        "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008": {
          "value": 4.3,
          "unit": "mm"
        }
      }
    }
  ]
}
```

### Field reference

| Field | Description |
|-------|-------------|
| `job_id` | UUID assigned by the module at request time |
| `timestamp` | ISO 8601 timestamp of the analysis |
| `pipeline.name` | Pipeline that produced the result |
| `pipeline.version` | Pipeline version for reproducibility tracking |
| `qc.analysis_pass` | `true` only when the result is reliable. If `false`, do not store trait values without manual review |
| `qc.color_card_present` | Whether a color calibration card was detected and applied. If `false`, color-derived traits may be unreliable |
| `qc.size_marker_detected` | Whether the size reference marker was found. If `false`, dimensional measurements are in pixels, not millimeters, and the `unit` field reflects this |
| `objects[].object_id` | Sequential identifier assigned left-to-right, top-to-bottom. Consistent across repeated analyses of the same image |
| `traits` keys | Follow `Human-readable name\|ONTOLOGY:ID` format. Value and unit are always explicit |

---

## 7. Design Principles

- **Reproducibility** — deterministic outputs and versioned pipelines; the same image always produces the same result
- **Interoperability** — OpenAPI contract and BrAPI compatibility; trait keys follow IMGSTAT ontology for direct ingestion into BreedBase
- **Modularity** — pipelines are pluggable; any compliant pipeline can register with the framework without changes to the integration layer
- **Transparency** — QC flags and provenance are required fields, not optional additions
- **Community extensibility** — the pipeline interface is an open standard; independent research groups can develop and publish compliant pipelines for any crop or trait class

---

## 8. Reference Implementation: Seed Morphometry Pipeline

The seed morphometry pipeline included in this repository is the reference implementation of the framework. It demonstrates how to satisfy the pipeline interface contract, structure a compliant repository, and expose analysis functionality via the framework's REST endpoint.

The pipeline accepts photographs of plant seeds or organs placed alongside a color calibration card and a circular size marker. It segments each object individually, applies color correction, converts pixel measurements to millimeters using the size marker, and returns per-object morphometric traits keyed by IMGSTAT ontology identifiers.

The pipeline is also available for direct use outside of BreedBase via CLI, Python API, or Docker — useful for standalone research workflows, batch processing, or evaluation before BreedBase deployment.

---

### 8.1 How the Pipeline Works

Each image is processed through these steps in order:

1. **Color card detection** — the calibration card is located and used to apply color correction, normalizing lighting variation across images and sessions
2. **Size marker detection** — the circular size marker of known physical diameter establishes the pixel-to-millimeter conversion factor for the image
3. **Reference masking** — the color card and size marker are masked out so they are not segmented as objects
4. **Object segmentation** — seeds or organs are segmented using HSV color-space thresholding and morphological operations; connected component analysis identifies individual objects
5. **Object labeling** — objects are labeled row-wise (left-to-right, top-to-bottom)
6. **Morphometric extraction** — area, perimeter, ellipse diameters, solidity, and convex hull area are computed per object
7. **Result packaging** — trait values, QC flags, and provenance metadata are assembled into the standardized output envelope

---

### 8.2 Installation

#### Prerequisites

- Python 3.9 or higher
- `pip`
- The repository cloned locally:

```bash
git clone https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module
cd breedbase-image-analysis-module
```

#### Install options

**Core pipeline only** (CLI + Python API, no web server):

```bash
pip install .
```

Sufficient for the CLI and Python API. Choose this if you do not need to run a local HTTP server.

**With REST API server** (adds Connexion, Flask, and Gunicorn):

```bash
pip install ".[api]"
```

Choose this to serve the REST endpoint locally or deploy the server for BreedBase integration.

**Editable install for development:**

```bash
pip install -e ".[api]"
```

#### Verify installation

```bash
bb-analyze --help
```

If the command is not found, confirm that your Python environment's `bin` or `Scripts` directory is on your `PATH`.

---

### 8.3 Usage: Command-Line Interface

The `bb-analyze` command is the fastest way to run the pipeline on a single image outside of BreedBase.

#### Basic usage

```bash
# Print JSON results to the terminal
bb-analyze path/to/image.jpg
```

#### Save results to a directory

```bash
bb-analyze path/to/image.jpg --output-dir ./results
```

Writes two files to `./results/`:
- `image_result.json` — the full JSON output
- `image_overlay.jpg` — the original image with object boundaries and labels drawn

#### Emit all traits

```bash
# Default emits a single trait (proof-of-concept mode)
# Use --output-mode all to extract all six morphometric traits
bb-analyze path/to/image.jpg --output-mode all
```

#### Specify size marker diameter

```bash
# Default assumes a 0.75-inch circular marker
# Override if your marker has a different known physical diameter
bb-analyze path/to/image.jpg --marker-diameter 1.0
```

The `--marker-diameter` value must match the physical diameter of the circular reference object present in your image, in inches. This value drives the pixel-to-millimeter conversion.

#### Combining options

```bash
bb-analyze path/to/image.jpg \
  --output-dir ./results \
  --output-mode all \
  --marker-diameter 0.75
```

On success, exits with code `0`. On failure, exits with code `1`. Output follows the envelope described in [Section 6](#6-the-standardized-output-envelope).

---

### 8.4 Usage: Python API

The Python API exposes the pipeline as a pure function with no file I/O or side effects. Use this in notebooks, batch scripts, and custom pipelines.

#### Basic call

```python
from process_image import analyze_image

result = analyze_image("path/to/image.jpg", output_mode="all")
```

#### Checking image-level QC

```python
print(result["qc"])
# {
#   'analysis_pass': True,
#   'color_card_present': True,
#   'size_marker_detected': True,
#   'object_count': 65
# }
```

`analysis_pass` is `True` only when the color card, size marker, and at least one object were all successfully detected. If `False`, trait values may be unreliable.

#### Accessing per-object traits

```python
for obj in result["objects"]:
    obj_id = obj["object_id"]
    diameter = obj["traits"]["Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008"]
    print(f"{obj_id}: {diameter['value']} {diameter['unit']}")
# obj_001: 4.3 mm
# obj_002: 4.1 mm
```

#### Return value reference

| Key | Type | Description |
|-----|------|-------------|
| `qc` | dict | Image-level QC flags |
| `objects` | list | Per-object records, each with `object_id`, `bbox`, `qc`, and `traits` |
| `output_mode` | str | `"single"` or `"all"` |
| `traits_emitted` | list | Trait keys included in this result |
| `overlay_img` | ndarray | NumPy array of the annotated result image |

#### Batch processing example

```python
from pathlib import Path
from process_image import analyze_image

image_dir = Path("./session_images")
results = []

for img_path in sorted(image_dir.glob("*.jpg")):
    result = analyze_image(str(img_path), output_mode="all")
    if result["qc"]["analysis_pass"]:
        for obj in result["objects"]:
            row = {"image": img_path.name, "object_id": obj["object_id"]}
            row.update({k: v["value"] for k, v in obj["traits"].items()})
            results.append(row)
    else:
        print(f"WARNING: QC failed for {img_path.name} — skipping")

# results is a list of flat dicts suitable for pandas or CSV export
```

---

### 8.5 Usage: Docker

Docker is the recommended deployment path for BreedBase integration and for researchers who prefer not to manage a Python environment.

#### Pull the image

```bash
docker pull hkmanchi/sorghum-breedbase-image-pipeline:latest
```

Architecture: `linux/amd64`

#### Run the REST API server

```bash
docker run -p 8000:8000 hkmanchi/sorghum-breedbase-image-pipeline:latest
```

The server starts at `http://localhost:8000` and accepts requests as described in [Section 4](#4-the-api-contract). This is the standard deployment mode for BreedBase integration.

#### Analyze a local image directly

```bash
docker run --rm \
  -v "$(pwd)/images:/images" \
  -v "$(pwd)/results:/results" \
  hkmanchi/sorghum-breedbase-image-pipeline:latest \
  bb-analyze /images/tray_001.jpg --output-dir /results --output-mode all
```

Mount your local `images/` and `results/` directories into the container. Results are written to your local `results/` directory.

#### Using docker-compose

```bash
docker-compose up
```

See `docker-compose.yml` for port mapping and volume mount configuration.

---

## 9. Repository Structure

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
│   ├── ref_mask.py                # Color card and size marker masking
│   ├── seed_mask.py               # Object segmentation
│   ├── object_labeling.py         # Row-wise object labeling
│   ├── shape_analysis.py          # Morphometric trait calculation
│   ├── size_marker_metadata.py    # Size marker calibration (pixels → mm)
│   ├── image_math.py              # Image math utilities
│   └── utils.py                   # Shared helpers
│
├── process_image.py               # analyze_image() — pure function
│                                  # process_image() — CLI-facing wrapper
├── cli.py                         # bb-analyze CLI entry point
├── pyproject.toml                 # Package definition and dependencies
│
├── tests/
│   ├── test_process_image.py      # Pipeline integration tests
│   ├── test_api.py                # HTTP-level API tests
│   ├── conftest.py                # Shared fixtures
│   └── fixtures/
│       ├── sample_seeds.jpg
│       └── expected_output.json   # Golden output for regression testing
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt / requirements-dev.txt
```

The `api/` directory is the integration framework layer. `pipelines/`, `process_image.py`, and `cli.py` are the reference pipeline. Future pipeline repositories reuse `api/` and replace everything else.

---

## 10. Reproducibility and Provenance

Every result from any compliant pipeline includes the following provenance fields, which the framework injects automatically:

| Field | Description |
|-------|-------------|
| `pipeline.name` | Name of the pipeline that produced the result |
| `pipeline.version` | Semantic version string |
| `timestamp` | ISO 8601 analysis timestamp |
| `input.image_filename` | Original input filename |
| `job_id` | UUID for this analysis run |

This ensures compatibility with:

- IMGSTAT-style image-derived trait ontologies
- BIAO-style QC and provenance tracking
- FAIR data principles (Findable, Accessible, Interoperable, Reusable)

---

## 11. Citation

If you use this framework or the reference pipeline in your research, please cite:

*(Citation forthcoming)*

