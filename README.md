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
- Python 3.10+
- pip or conda
- OpenCV (if using reference pipeline)

### Setup
```
git clone https://github.com/...
cd breedbase-image-analysis-module
pip install -r requirements.txt
```

### Run
```
python app.py
```
Server runs at:
```
http://localhost:8000
```

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



