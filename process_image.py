import sys
import argparse
import os
import uuid
import json
import logging
from datetime import datetime, timezone
import cv2

from helpers.utils import enforce_https, readimage
from helpers.object_labeling import label_objects_rowwise
from masking.ref_mask import create_chip_mask, create_masks
from masking.seed_mask import create_seed_mask
from analysis.color_correction import apply_color_correction
from pipelines.size_marker_metadata import size_marker
from analysis.shape_analysis import calculate_size_shape

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


def process_image(image_path, results_dir, host_url=None, marker_diameter_in=0.75):
    """
    Run the reference image analysis pipeline on a single image.

    Returns a Python dict (result envelope). Caller is responsible for printing JSON.
    Raises exceptions on failure.
    """
    os.makedirs(results_dir, exist_ok=True)
    job_id = str(uuid.uuid4())

    # Read image
    img, img_filename = readimage(filename=image_path)

    # Reference masks (color card + size marker)
    cc_mask, sm_mask = create_masks(img, raise_errors=False)

    # Chip mask for color correction
    chip_mask = create_chip_mask(img, cc_mask)

    # Color correction
    corrected_img = apply_color_correction(img, chip_mask)

    # Seed masks
    seed_mask = create_seed_mask(corrected_img, cc_mask, sm_mask)

    # Size marker metadata
    sm_metadata = size_marker(sm_mask, marker_diameter_in)
    # sm_detected = next((item["value"] for item in sm_metadata if item["trait"] == "size_marker_detected"), False)

    # Label objects
    labeled_mask, labeled_img = label_objects_rowwise(
        seed_mask, corrected_img, output_mask_path=None, display_result=False
    )

    # Shape analysis
    size_data, overlay_img = calculate_size_shape(labeled_img, labeled_mask, sm_metadata)

    # Output filenames
    filename = os.path.basename(image_path)
    name_no_ext = os.path.splitext(filename)[0]

    composite_image_name = f"{name_no_ext}_ResultImage_{job_id}.png"
    composite_image_path = os.path.join(results_dir, composite_image_name)
    cv2.imwrite(composite_image_path, overlay_img)

    # Host URL handling
    host_url = os.environ.get('HOSTURL') if not host_url else host_url
    host_url = enforce_https(host_url) if host_url else host_url
    composite_url = f"{host_url}/download/{composite_image_name}" if host_url else composite_image_path

    # QC flags (minimal but useful)
    # NOTE: if masks are not uint8/binary, convert to boolean safely
    color_card_present = bool(cc_mask is not None and int(cc_mask.max()) > 0)
    size_marker_present = bool(sm_mask is not None and int(sm_mask.max()) > 0)
    object_count = len(size_data)

    analysis_pass = True
    # Example prerequisite logic (tune to your standard):
    if object_count == 0:
        analysis_pass = False

    # Build objects list with trait dicts
    TRAIT_KEY = "Object Maximum Diameter From Fitted Ellipse|IMGSTAT:0000008"
    objects = []
    for idx, (seed_key, seed_data) in enumerate(size_data.items(), start=1):
        obj_id = f"obj_{idx:03d}"
        trait_value = seed_data.get("obj_diam_max_ellipse", None)
        trait_value = round(float(trait_value), 2) if trait_value is not None else None

        objects.append({
            "object_id": obj_id,
            "source_label": str(seed_key),
            "traits": {
                TRAIT_KEY: {"value": trait_value, "unit": "mm"}
            }
        })

    envelope = {
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "input": {
            "image_path": image_path,
            "image_filename": filename
        },
        "qc": {
            "analysis_pass": analysis_pass,
            "color_card_present": color_card_present,
            "size_marker_present": size_marker_present,
            "object_count": object_count
        },
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
    args = parser.parse_args()

    try:
        payload = process_image(
            args.image_path,
            args.results_dir,
            host_url=args.host_url,
            marker_diameter_=args.marker_diameter_in
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
