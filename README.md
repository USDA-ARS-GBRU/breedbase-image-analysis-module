# breedbase-image-analysis-module
A standardized, API-driven backend framework for integrating automated image analysis pipelines into BreedBase, enabling reproducible extraction of image-derived phenotypes, quality control metrics, and provenance metadata for use in breeding programs.


## 1. Overview
### Purpose
The BreedBase Image Analysis Module provides a structured, API-driven framework for integrating automated image analysis pipelines into BreedBase. It enables reproducible extraction of image-derived phenotypes, quality control metrics, and provenance metadata suitable for use in real-world breeding programs.

#### What this repository provides:
A reference Flask/Connexion backend implementation
A standardized API contract (OpenAPI-based)
A structured pipeline interface
Example pipeline implementation
Integration requirements for third-party pipelines
Documentation for reproducible deployment

#### What this repository does NOT include:
BreedBase UI code (hosted in the BreedBase repository)
Species-specific trait ontologies
Production infrastructure (e.g., queue systems, cloud storage)

## 2. Architecture
High-level data flow:
```
Field Book → BreedBase → Image Analysis Module → BreedBase → Breeder
```
Expanded:
1. Image stored in BreedBase
2. User triggers analysis
3. BreedBase submits request to this module via API
4. Pipeline processes image
5. Standardized JSON results returned
6. Observations + derived images stored in BreedBase

Holder - diagram of architecture

## 3. Design Principles

- Reproducibility — Deterministic outputs and versioned pipelines
- Interoperability — OpenAPI contract + BrAPI compatibility
- Modularity — Pipelines are pluggable
- Transparency — QC flags and provenance included
- Community extensibility — Any compliant pipeline can integrate

## 4. Repository Structure

## 5. API Contract
This module exposes a standardized API defined in: config/openapi.yml

### Primary Endpoint
POST /analyze

Expected input:
- Image file (multipart)
- Optional metadata
- Optional pipeline parameters

Returns:
- JSON payload containing:
 - Image-derived trait values
 - Units
 - QC flags
 - Provenance metadata
 - Links to derived images (if applicable)

See: examples/submit_request.example.json
See: examples/result_response.example.json

## 6. Pipeline Interface Requirements

Any pipeline integrated into this framework must:
1. Accept:
 - Path to image
 - Output directory
 - Optional metadata and parameters
2. Return:
 - JSON payload printed to stdout (or returned to caller)
 - Structured trait list
 - Units explicitly defined
 - QC indicators
 - Pipeline version and timestamp

Full specification:
docs/PIPELINE_REQUIREMENTS.md

## 7. Example Pipeline

This repository includes a reference pipeline demonstrating:
- Object masking
- Morphology extraction
- Size standard conversion
- Result packaging

Location:
```
pipelines/example_pipeline/
```
Run locally:
```
python process_image.py path/to/image.jpg results/
```

## 8. Integration with BreedBase

The BreedBase frontend:
- Triggers analysis
- Sends images via API
- Stores returned observations
- Associates outputs with stocks and projects

For BreedBase-specific integration instructions, see:

## 9. Installation

### Requirements
- Python 3.9+
- pip

### As a Python package (recommended)

Install core image analysis dependencies only:
```
pip install .
```

Install with API server dependencies (Connexion, Flask, Gunicorn):
```
pip install ".[api]"
```

Install in editable mode for development:
```
pip install -e ".[api]"
```

### Legacy (requirements.txt)
```
git clone https://github.com/...
cd breedbase-image-analysis-module
pip install -r requirements.txt
```

### Run the API server
```
python api/app.py
```
Server runs at:
```
http://localhost:8000
```

## 9a. Command-Line Interface

After installing the package, the `bb-analyze` command is available:

```
# Print JSON results to stdout (no files written)
bb-analyze path/to/image.jpg

# Save overlay image and JSON sidecar to a directory
bb-analyze path/to/image.jpg --output-dir ./results

# Emit all traits instead of the default single trait
bb-analyze path/to/image.jpg --output-mode all

# Specify size marker diameter (default: 0.75 inches)
bb-analyze path/to/image.jpg --marker-diameter 1.0

# Combine options
bb-analyze path/to/image.jpg --output-dir ./results --output-mode all --marker-diameter 0.75
```

Output is a JSON envelope printed to stdout. Exit code is 0 on success, 1 on failure.

## 9b. Python API

The pipeline can be called directly from Python without the HTTP layer:

```python
from process_image import analyze_image

result = analyze_image("path/to/image.jpg", output_mode="all")

print(result["qc"])
# {'analysis_pass': True, 'color_card_present': True,
#  'size_marker_detected': True, 'object_count': 65}

for obj in result["objects"]:
    traits = obj["traits"]
    print(obj["object_id"], traits["Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008"])
```

`analyze_image()` returns a dict with the following keys:

| Key | Description |
|-----|-------------|
| `qc` | Image-level QC flags (`analysis_pass`, `color_card_present`, `size_marker_detected`, `object_count`) |
| `objects` | List of per-object dicts, each containing `object_id`, `bbox`, `qc`, and `traits` |
| `output_mode` | `"single"` or `"all"` |
| `traits_emitted` | List of public trait keys included in this run |
| `overlay_img` | NumPy array of the annotated result image |

This function performs no file I/O and has no side effects — it is safe to call in notebooks, scripts, or other pipelines.

## 10. Development Guidelines
- Pipelines must be deterministic
- All outputs must specify units
- QC flags must be explicit
- Version string required
- No hard-coded file paths
- Avoid writing outside designated results directory

## 11. Reproducibility & Provenance
Each analysis result includes:
- pipeline_name
- pipeline_version
- analysis_timestamp
- input_filename
- Optional parameters used

This ensures compatibility with:
- IMGSTAT-style image-derived traits
- BIAO-style QC and provenance tracking
- FAIR data principles

## 12. Citation
If you use this module, please cite:

## Docker Image
Official image:
```
docker pull: hkmanchi/sorghum-breedbase-image-pipeline:latest
```
Architecture:
```
linux/amd64
```

