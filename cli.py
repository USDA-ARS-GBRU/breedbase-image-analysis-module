"""
cli.py — standalone entry point for the BreedBase image analysis pipeline.

Usage:
    bb-analyze image.jpg                          # prints JSON to stdout
    bb-analyze image.jpg --output-dir ./results   # saves overlay + JSON sidecar
    bb-analyze image.jpg --output-mode all        # emit all traits
"""

import sys
import os
import json
import logging
import argparse
import uuid
from datetime import datetime, timezone

from process_image import analyze_image, PIPELINE_NAME, PIPELINE_VERSION


def main():
    parser = argparse.ArgumentParser(
        description="Run the BreedBase image analysis pipeline on a single image."
    )
    parser.add_argument("image_path", help="Path to the input image")
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Directory to save overlay image and JSON sidecar (optional)",
    )
    parser.add_argument(
        "--output-mode",
        choices=["single", "all"],
        default=None,
        help="Emit one trait (single) or all traits (all). Defaults to OUTPUT_MODE env var or 'single'.",
    )
    parser.add_argument(
        "--marker-diameter",
        type=float,
        default=0.75,
        help="Physical diameter of the size marker in inches (default: 0.75)",
    )
    parser.add_argument(
        "--host-url",
        default=None,
        help="Base URL used to build download links in derived_images (optional)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    try:
        result = analyze_image(
            args.image_path,
            marker_diameter_in=args.marker_diameter,
            output_mode=args.output_mode,
        )
    except Exception as e:
        logging.error("Pipeline failed: %s", e)
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        sys.exit(1)

    job_id = str(uuid.uuid4())
    filename = os.path.basename(args.image_path)
    name_no_ext = os.path.splitext(filename)[0]

    derived_images = []
    if args.output_dir:
        import cv2
        os.makedirs(args.output_dir, exist_ok=True)

        overlay_name = f"{name_no_ext}_ResultImage_{job_id}.png"
        overlay_path = os.path.join(args.output_dir, overlay_name)
        cv2.imwrite(overlay_path, result["overlay_img"])

        host_url = args.host_url.rstrip("/") + "/" if args.host_url else None
        overlay_url = f"{host_url}download/{overlay_name}" if host_url else overlay_path
        derived_images = [{"role": "overlay", "filename": overlay_name, "url": overlay_url}]

        sidecar_name = f"{name_no_ext}_metadata_{job_id}.json"
        sidecar_path = os.path.join(args.output_dir, sidecar_name)

    envelope = {
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "input": {"image_filename": filename},
        "qc": result["qc"],
        "output_mode": result["output_mode"],
        "traits_emitted": result["traits_emitted"],
        "derived_images": derived_images,
        "objects": result["objects"],
    }

    if args.output_dir:
        with open(sidecar_path, "w") as f:
            json.dump(envelope, f, indent=2)

    print(json.dumps(envelope))
    sys.exit(0)


if __name__ == "__main__":
    main()
