"""
cli.py — standalone entry point for the BreedBase image analysis pipeline.

Usage:
    bb-analyze image.jpg --output-dir ./results
    bb-analyze image.jpg --output-dir ./results --format csv
"""

import sys
import os
import csv
import io
import json
import logging
import argparse
import uuid
from datetime import datetime, timezone

from process_image import (
    analyze_image,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    DEFAULT_MARKER_DIAMETER_IN,
)


def _to_csv(envelope):
    qc = envelope["qc"]
    pipeline = envelope["pipeline"]
    rows = []
    for obj in envelope["objects"]:
        row = {
            "job_id": envelope["job_id"],
            "timestamp": envelope["timestamp"],
            "pipeline_name": pipeline["name"],
            "pipeline_version": pipeline["version"],
            "image_filename": envelope["input"]["image_filename"],
            "qc_analysis_pass": qc.get("analysis_pass"),
            "qc_color_card_present": qc.get("color_card_present"),
            "qc_size_marker_detected": qc.get("size_marker_detected"),
            "object_count": qc.get("object_count"),
            "object_id": obj["object_id"],
            "source_label": obj["source_label"],
            "bbox_x": obj["bbox"]["x"],
            "bbox_y": obj["bbox"]["y"],
            "bbox_w": obj["bbox"]["w"],
            "bbox_h": obj["bbox"]["h"],
            "qc_contour_found": obj["qc"].get("contour_found"),
            "qc_ellipse_fit_ok": obj["qc"].get("ellipse_fit_ok"),
        }
        for trait_key, trait_val in obj["traits"].items():
            row[trait_key] = trait_val["value"]
        rows.append(row)

    if not rows:
        return ""

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(
        description="Run the BreedBase image analysis pipeline on a single image."
    )
    parser.add_argument("image_path", help="Path to the input image")
    parser.add_argument(
        "--output-dir", "-o",
        required=True,
        help="Directory to save the overlay image and results sidecar",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format for the results sidecar (default: json)",
    )
    parser.add_argument(
        "--marker-diameter",
        type=float,
        default=DEFAULT_MARKER_DIAMETER_IN,
        help=f"Physical diameter of the size marker in inches (default: {DEFAULT_MARKER_DIAMETER_IN})",
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
        )
    except Exception as e:
        logging.error("Pipeline failed: %s", e)
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        sys.exit(1)

    job_id = str(uuid.uuid4())
    filename = os.path.basename(args.image_path)
    name_no_ext = os.path.splitext(filename)[0]

    import cv2
    os.makedirs(args.output_dir, exist_ok=True)

    overlay_name = f"{name_no_ext}_ResultImage_{job_id}.png"
    overlay_path = os.path.join(args.output_dir, overlay_name)
    cv2.imwrite(overlay_path, result["overlay_img"])

    host_url = args.host_url.rstrip("/") + "/" if args.host_url else None
    overlay_url = f"{host_url}download/{overlay_name}" if host_url else overlay_path
    derived_images = [{"role": "overlay", "filename": overlay_name, "url": overlay_url}]

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "input": {"image_filename": filename},
        "qc": result["qc"],
        "traits_emitted": result["traits_emitted"],
        "derived_images": derived_images,
        "objects": result["objects"],
    }

    sidecar_name = f"{name_no_ext}_metadata_{job_id}.{args.format}"
    sidecar_path = os.path.join(args.output_dir, sidecar_name)

    if args.format == "json":
        with open(sidecar_path, "w") as f:
            json.dump(envelope, f, indent=2)
    else:
        with open(sidecar_path, "w", newline="") as f:
            f.write(_to_csv(envelope))

    print(f"Overlay:  {overlay_path}")
    print(f"Results:  {sidecar_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
