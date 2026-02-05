# pipelines/size_marker_metadata.py
import numpy as np
import cv2
import math

INCH_TO_MM = 25.4

def size_marker(sm_mask, marker_diameter_in):
    """
    Compute size marker calibration factors from a binary mask.

    Args:
        sm_mask: binary-ish mask (uint8/bool) where marker pixels > 0
        marker_diameter_in: physical marker diameter in inches

    Returns:
        metadata: list[dict] rows with keys: object, trait, value
                  Always includes 'size_marker_detected' (bool).
                  Includes calibration factors:
                    - px_per_mm
                    - px2_per_mm2
                    - mm_per_px
                    - mm2_per_px2
    """

    def row(trait, value):
        return {"object": "SizeMarker", "trait": trait, "value": value}

    metadata = []

    if sm_mask is None:
        metadata.append(row("size_marker_detected", False))
        return metadata

    # Ensure uint8 0/255 for OpenCV ops
    sm_u8 = sm_mask.astype(np.uint8)
    if sm_u8.max() > 1:
        sm_u8 = (sm_u8 > 0).astype(np.uint8)
    sm_u8 *= 255

    m = cv2.moments(sm_u8, binaryImage=True)
    if m["m00"] == 0:
        metadata.append(row("size_marker_detected", False))
        return metadata

    contours, _ = cv2.findContours(sm_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        metadata.append(row("size_marker_detected", False))
        return metadata

    cnt = max(contours, key=cv2.contourArea)
    marker_area_px2 = float(m["m00"])

    # Need >= 5 points to fit ellipse
    if len(cnt) < 5:
        metadata.append(row("size_marker_detected", False))
        metadata.append(row("marker_area_px2", marker_area_px2))
        return metadata

    try:
        (cx, cy), axes, angle = cv2.fitEllipse(cnt)
    except cv2.error:
        metadata.append(row("size_marker_detected", False))
        metadata.append(row("marker_area_px2", marker_area_px2))
        return metadata
    
    major_axis_px = float(max(axes))
    minor_axis_px = float(min(axes))

    marker_diameter_mm = float(marker_diameter_in) * INCH_TO_MM
    r_mm = marker_diameter_mm / 2.0
    marker_area_mm2 = math.pi * (r_mm ** 2)

    # Calibration: pixels per mm (and pixels^2 per mm^2)
    px_per_mm = major_axis_px / marker_diameter_mm if marker_diameter_mm else None
    px2_per_mm2 = marker_area_px2 / marker_area_mm2 if marker_area_mm2 else None

    calibration_valid = bool(px_per_mm and px_per_mm > 0 and px2_per_mm2 and px2_per_mm2 > 0)

    # Inverses (often handy)
    mm_per_px = (1.0 / px_per_mm) if px_per_mm else None
    mm2_per_px2 = (1.0 / px2_per_mm2) if px2_per_mm2 else None

    axis_ratio = (major_axis_px / minor_axis_px) if minor_axis_px else None

    metadata.extend([
        row("size_marker_detected", True),
        row("marker_diameter_in", float(marker_diameter_in)),
        row("marker_diameter_mm", float(marker_diameter_mm)),
        row("marker_area_mm2", float(marker_area_mm2)),
        row("centroid_x_px", float(cx)),
        row("centroid_y_px", float(cy)),
        row("marker_area_px2", marker_area_px2),
        row("major_axis_length_px", major_axis_px),
        row("minor_axis_length_px", minor_axis_px),
        row("axis_ratio", float(axis_ratio) if axis_ratio is not None else None),
        row("px_per_mm", float(px_per_mm)),
        row("px2_per_mm2", float(px2_per_mm2)),
        row("mm_per_px", float(mm_per_px) if mm_per_px is not None else None),
        row("mm2_per_px2", float(mm2_per_px2) if mm2_per_px2 is not None else None),
        row("calibration_valid", calibration_valid),
    ])

    return metadata
