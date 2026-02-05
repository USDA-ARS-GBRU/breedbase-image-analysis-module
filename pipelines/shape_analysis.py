import numpy as np
import cv2


# --------------------------------------------------------------------
# Computes per-object size and shape metrics (area, hull area, solidity,
# perimeter, and ellipse axes) from a labeled mask, converts them to
# metric units using size marker calibration metadata (px/mm and px^2/mm^2),
# and returns both the measurements and a visualization overlay image.
# --------------------------------------------------------------------

def calculate_size_shape(img, labeled_objects, sm_metadata):
    """
    Compute per-object size/shape metrics from a labeled mask and convert to
    metric units using size marker calibration metadata.

    Expected calibration traits in sm_metadata:
      - 'px_per_mm'   : pixels per millimeter (px/mm)
      - 'px2_per_mm2' : pixels^2 per millimeter^2 (px^2/mm^2)

    Conversions:
      - length_mm  = length_px  / px_per_mm
      - area_mm2   = area_px2   / px2_per_mm2

    Args:
        img: RGB image (uint8).
        labeled_objects: labeled mask where 0=background and positive integers are objects.
        sm_metadata: list of dicts with keys including 'trait' and 'value'.

    Returns:
        metrics_by_label: dict keyed by label id (int) -> dict with traits/bbox/qc
        overlay_img: image copy for optional visualization overlays
    """

    # Pull calibration factors (raise clearly if missing)
    px_per_mm = _get_meta(sm_metadata, "px_per_mm")
    px2_per_mm2 = _get_meta(sm_metadata, "px2_per_mm2")

    overlay_img = img.copy()
    metrics_by_label = {}

    # Iterate actual labels (does not assume labels are contiguous 1..N)
    labels = sorted(int(v) for v in np.unique(labeled_objects) if v != 0)

    for label in labels:
        obj_mask = (labeled_objects == label).astype(np.uint8) * 255

        # Find external contours only; choose largest contour as object boundary
        contours, _ = cv2.findContours(obj_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            metrics_by_label[label] = {"qc": {"contour_found": False}}
            continue

        contour = max(contours, key=cv2.contourArea)

        # Basic geometry in pixel units
        area_px2 = float(cv2.countNonZero(obj_mask))
        perimeter_px = float(cv2.arcLength(contour, closed=True))

        # Convex hull metrics
        hull = cv2.convexHull(contour)
        hull_area_px2 = float(cv2.contourArea(hull))
        solidity = (area_px2 / hull_area_px2) if hull_area_px2 > 0 else None

        # Ellipse fitting (requires >= 5 points)
        ellipse_major_px = None
        ellipse_minor_px = None
        ellipse_fit_ok = False
        if len(contour) >= 5:
            try:
                (_, _), axes, _ = cv2.fitEllipse(contour)
                # axes are full lengths (major/minor diameters) in pixels
                ellipse_major_px = float(max(axes))
                ellipse_minor_px = float(min(axes))
                ellipse_fit_ok = True
            except cv2.error:
                ellipse_fit_ok = False

        # Bounding box (useful for debug / downstream cropping)
        x, y, w, h = cv2.boundingRect(contour)

        # Convert to metric units
        area_mm2 = (area_px2 / px2_per_mm2) if px2_per_mm2 else None
        hull_area_mm2 = (hull_area_px2 / px2_per_mm2) if px2_per_mm2 else None
        perimeter_mm = (perimeter_px / px_per_mm) if px_per_mm else None
        major_mm = (ellipse_major_px / px_per_mm) if (ellipse_major_px is not None and px_per_mm) else None
        minor_mm = (ellipse_minor_px / px_per_mm) if (ellipse_minor_px is not None and px_per_mm) else None

        metrics_by_label[label] = {
            "traits": {
                "obj_area_mask": area_mm2,
                "obj_area_hull": hull_area_mm2,
                "obj_solidity": solidity,
                "obj_perimeter_mask": perimeter_mm,
                "obj_diam_max_ellipse": major_mm,
                "obj_diam_min_ellipse": minor_mm,
            },
            "bbox": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            "qc": {
                "contour_found": True,
                "ellipse_fit_ok": ellipse_fit_ok,
            },
        }

    return metrics_by_label, overlay_img

def _get_meta(sm_metadata, key):
    return next((item["value"] for item in sm_metadata if item["trait"] == key), None)
