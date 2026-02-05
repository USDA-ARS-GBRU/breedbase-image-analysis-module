import sys
import argparse
import os
import uuid
import json
import logging
from datetime import datetime, timezone
import cv2
import math

from pipelines.utils import enforce_https, readimage
from pipelines.object_labeling import label_objects_rowwise
from pipelines.ref_mask import create_chip_mask, create_masks
from pipelines.seed_mask import create_seed_mask
from pipelines.color_correction import apply_color_correction
from pipelines.size_marker_metadata import size_marker
from pipelines.shape_analysis import calculate_size_shape

# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------
os.makedirs('logs', exist_ok=True)
LOG_FILE = os.path.join('logs', 'server.log')
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [process_image] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stderr)
    ]
)

PIPELINE_NAME = os.getenv("PIPELINE_NAME", "seed_size_shape")
PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "0.1.0")

# --------------------------------------------------------------------
# Working on multi-trait schema, but adding switch for POC
# --------------------------------------------------------------------
DEFAULT_OUTPUT_MODE = os.getenv("OUTPUT_MODE", "single").lower()  # "single" or "all"

# --------------------------------------------------------------------
# Internal metric keys from analysis/shape_analysis.py 
# -> (Public trait key, unit, rounding digits)
# --------------------------------------------------------------------

TRAITS_MAP = {
        # internal_key: (public_trait_key, unit, ndigits)
        "obj_area_mask": ("Object Area From Segmentation Mask|IMGSTAT:0000006", "mm^2", 2),
        "obj_area_hull": ("Object Convex Hull Area|IMGSTAT:0000007", "mm^2", 2),
        "obj_perimeter_mask": ("Object Perimeter From Segmentation Mask|IMGSTAT:0000010", "mm", 2),
        "obj_solidity": ("Object Solidity|IMGSTAT:0000011", None, 4),
        "obj_diam_max_ellipse": ("Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008", "mm", 2),
        "obj_diam_min_ellipse": ("Object Minimum Diameter From Fitted Ellipse|IMGSTAT:0000009", "mm", 2),
    }

def select_internal_trait_keys(output_mode: str):
    """
    POC mode emits a single trait but keeps the same output schema.
    """
    output_mode = (output_mode or "single").lower()
    if output_mode == "all":
        return list(TRAITS_MAP.keys())
    # POC default: only one trait
    return ["obj_diam_max_ellipse"]

def _to_float(x):
    """Best-effort conversion to float; returns None if not convertible."""
    if x is None:
        return None
    try:
        # Handles numpy scalars cleanly
        return float(x)
    except (TypeError, ValueError):
        return None

def safe_round(x, ndigits=2):
    """
    Convert to float and round safely.
    Returns None for None, non-numeric, NaN, or Inf.
    """
    fx = _to_float(x)
    if fx is None or math.isnan(fx) or math.isinf(fx):
        return None
    return round(fx, ndigits)

def _meta_value(sm_metadata, trait, default=None):
    return next((item["value"] for item in sm_metadata if item.get("trait") == trait), default)

def process_image(image_path, results_dir, host_url=None, marker_diameter_in=0.75, output_mode=None):
    """
    Run the reference image analysis pipeline on a single image.

    Returns a Python dict (result envelope). Caller is responsible for printing JSON.
    Raises exceptions on failure.
    """
    
    os.makedirs(results_dir, exist_ok=True)
    job_id = str(uuid.uuid4())
    
    output_mode = (output_mode or DEFAULT_OUTPUT_MODE).lower()
    selected_keys = select_internal_trait_keys(output_mode)
    
    traits_emitted = [TRAITS_MAP[k][0] for k in selected_keys]

    # --------------------------------------------------------------------
    # Read image
    # --------------------------------------------------------------------
    img, img_filename = readimage(filename=image_path)

    # --------------------------------------------------------------------
    # Reference masks (color card + size marker)
    # --------------------------------------------------------------------
    cc_mask, sm_mask = create_masks(img, raise_errors=False)

    # Chip mask for color correction
    chip_mask = create_chip_mask(img, cc_mask)

    # Color correction
    corrected_img = apply_color_correction(img, chip_mask)

    # --------------------------------------------------------------------
    # Seed/object masks
    # --------------------------------------------------------------------
    seed_mask = create_seed_mask(corrected_img, cc_mask, sm_mask)

    # --------------------------------------------------------------------
    # Size marker metadata (calibration)
    # --------------------------------------------------------------------
    sm_metadata = size_marker(sm_mask, marker_diameter_in)
    size_marker_detected = bool(_meta_value(sm_metadata, "size_marker_detected", False))

    # --------------------------------------------------------------------
    # Label objects
    # --------------------------------------------------------------------
    labeled_mask, labeled_img = label_objects_rowwise(
        seed_mask, corrected_img, output_mask_path=None, display_result=False
    )

    # --------------------------------------------------------------------
    # Shape analysis (only if calibration present)
    # --------------------------------------------------------------------
    size_data = {}
    overlay_img = labeled_img.copy()

    if size_marker_detected:
        size_data, overlay_img = calculate_size_shape(labeled_img, labeled_mask, sm_metadata)

    # --------------------------------------------------------------------
    # Output filenames
    # --------------------------------------------------------------------
    filename = os.path.basename(image_path)
    name_no_ext = os.path.splitext(filename)[0]

    composite_image_name = f"{name_no_ext}_ResultImage_{job_id}.png"
    composite_image_path = os.path.join(results_dir, composite_image_name)
    cv2.imwrite(composite_image_path, overlay_img)

    # Host URL handling
    host_url = os.environ.get('HOSTURL') if not host_url else host_url
    host_url = enforce_https(host_url) if host_url else host_url
    composite_url = f"{host_url}/download/{composite_image_name}" if host_url else composite_image_path

    # --------------------------------------------------------------------
    # QC flags (image-level)
    # --------------------------------------------------------------------
    color_card_present = bool(cc_mask is not None and int(cc_mask.max()) > 0)
    object_count = len(size_data)
    
    analysis_pass = True
    if not size_marker_detected:
        analysis_pass = False
    if object_count == 0:
        analysis_pass = False

    # --------------------------------------------------------------------
    # Build objects list with trait dicts (one or many traits with switch)
    # --------------------------------------------------------------------
    
    objects = []
    if analysis_pass:
        for idx, (label_id, obj_data) in enumerate(size_data.items(), start=1):
            obj_id = f"obj_{idx:03d}"
            
            traits_in = (obj_data or {}).get("traits", {})
            traits_out = {}
    
    
            for internal_key in selected_keys:
                public_key, unit, ndigits = TRAITS_MAP[internal_key]
                raw = traits_in.get(internal_key, None)
                val = safe_round(raw, ndigits=ndigits) if ndigits is not None else _to_float(raw)
                traits_out[public_key] = {"value": val, "unit": unit}
            
            objects.append({
                "object_id": obj_id,
                "source_label": str(label_id),
                "bbox": (obj_data or {}).get("bbox"),
                "qc": (obj_data or {}).get("qc"),
                "traits": traits_out,
            })


    # --------------------------------------------------------------------
    # Canonical envelope v1
    # --------------------------------------------------------------------
    envelope = {
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "input": {"image_filename": filename},
        "qc": {
            "analysis_pass": analysis_pass,
            "color_card_present": color_card_present,
            "size_marker_detected": size_marker_detected,
            "object_count": object_count
        },
        "output_mode": output_mode,
        "traits_emitted": traits_emitted,
        "derived_images": [
            {"role": "overlay", "filename": composite_image_name, "url": composite_url}
        ],
        "objects": objects
    }

    # Save JSON sidecar
    result_json_name = f"{name_no_ext}_metadata_{job_id}.json"
    result_json_path = os.path.join(results_dir, result_json_name)
    with open(result_json_path, 'w') as f:
        json.dump(envelope, f, indent=2)

    return envelope


def main():
    parser = argparse.ArgumentParser(description="Run the reference image analysis pipeline.")
    parser.add_argument("image_path", help="Path to the input image")
    parser.add_argument("results_dir", help="Directory to save outputs")
    parser.add_argument("--host_url", help="Base URL for download links")
    parser.add_argument("--marker_diameter_in", type=float, default=0.75,
                    help="Physical diameter of the size marker in inches (default: 0.75)")
    parser.add_argument("--output_mode", choices=["single", "all"], default=DEFAULT_OUTPUT_MODE,
                    help="Emit a single trait (POC) or all traits (default from OUTPUT_MODE env).")
    args = parser.parse_args()

    try:
        payload = process_image(
            args.image_path,
            args.results_dir,
            host_url=args.host_url,
            marker_diameter_in=args.marker_diameter_in,
            output_mode=args.output_mode
        )
        print(json.dumps(payload))
        sys.exit(0)

    except Exception as e:
        logging.exception("Pipeline failed")
        error_payload = {
            "error": str(e),
            "error_type": type(e).__name__
        }
        print(json.dumps(error_payload))
        sys.exit(1)


if __name__ == "__main__":
    main()
