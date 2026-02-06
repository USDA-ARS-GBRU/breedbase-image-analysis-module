# masking/ref_mask.py

from __future__ import annotations

from typing import Tuple, Optional

import cv2
import numpy as np
import math
from scipy.ndimage import binary_fill_holes
from skimage.morphology import remove_small_objects

from pipelines.utils import apply_mask
from pipelines.image_math import _approx_quad, _quad_rect_score, _circle_score


# ==========================================================
# COLOR CARD + SIZE MARKER DETECTION
# ==========================================================

def create_masks(img: np.ndarray, raise_errors: bool = True) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect rectangle-like (color card) and circle-like (size marker)
    contours in image and return separate binary masks.

    Always returns valid uint8 masks.
    Raises only if raise_errors=True.
    """

    if img is None or img.ndim != 3:
        raise ValueError("create_masks expects BGR image (HxWx3).")

    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception as e:
        if raise_errors:
            raise RuntimeError(f"Grayscale conversion failed: {e}")
        return _empty_masks(img)

    # Adaptive threshold
    seed_mask = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=51,
        C=5
    )

    # Cleanup
    bool_img = binary_fill_holes(seed_mask.astype(bool))
    seed_mask = (bool_img.astype(np.uint8) * 255)
    seed_mask = cv2.morphologyEx(seed_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    contours, _ = cv2.findContours(seed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    H, W = seed_mask.shape
    min_area = H * W * 0.005

    best_rect = {"score": 0.0, "cnt": None}
    best_circle = {"score": 0.0, "cnt": None}

    for cnt in contours:
        if cv2.contourArea(cnt) <= min_area:
            continue

        # Rectangle scoring
        quad = _approx_quad(cnt, start=0.006, stop=0.06, step=0.002)
        rect_score = _quad_rect_score(quad, cnt) if quad is not None else 0.0
        if rect_score > best_rect["score"]:
            best_rect = {"score": rect_score, "cnt": cnt}

        # Circle scoring
        circ_score = _circle_score(cnt)
        if circ_score > best_circle["score"]:
            best_circle = {"score": circ_score, "cnt": cnt}

    cc_mask = np.zeros_like(seed_mask)
    sm_mask = np.zeros_like(seed_mask)

    cc_cnt = best_rect["cnt"]
    sm_cnt = best_circle["cnt"]

    # Prevent same contour for both
    if cc_cnt is not None and sm_cnt is not None and cc_cnt is sm_cnt:
        if best_rect["score"] >= best_circle["score"]:
            sm_cnt = None
        else:
            cc_cnt = None

    if cc_cnt is not None:
        cv2.drawContours(cc_mask, [cc_cnt], -1, 255, -1)

    if sm_cnt is not None:
        cv2.drawContours(sm_mask, [sm_cnt], -1, 255, -1)

    if raise_errors:
        if cc_cnt is None:
            raise RuntimeError("No color card (rectangle) detected.")
        if sm_cnt is None:
            raise RuntimeError("No size marker (circle) detected.")

    return cc_mask, sm_mask


def _empty_masks(img):
    h, w = img.shape[:2]
    return np.zeros((h, w), dtype=np.uint8), np.zeros((h, w), dtype=np.uint8)


# ==========================================================
# CHIP MASK (FOR COLOR CORRECTION)
# ==========================================================

def create_chip_mask(img: np.ndarray, cc_mask: Optional[np.ndarray]) -> np.ndarray:
    """
    Create chip mask for color correction.

    Returns uint8 mask (may be empty if detection fails).
    Never raises hard errors.
    """

    h, w = img.shape[:2]

    if cc_mask is None or np.max(cc_mask) == 0:
        return np.zeros((h, w), dtype=np.uint8)

    try:
        masked = apply_mask(img, cc_mask)
        hsv = cv2.cvtColor(masked, cv2.COLOR_BGR2HSV)
        v_channel = hsv[:, :, 2]
    except Exception:
        return np.zeros((h, w), dtype=np.uint8)

    _, binary_mask = cv2.threshold(v_channel, 75, 255, cv2.THRESH_BINARY)

    bool_img = remove_small_objects(binary_mask.astype(bool), 200)
    bool_img = binary_fill_holes(bool_img)
    binary_mask = (bool_img.astype(np.uint8) * 255)

    contours, _ = cv2.findContours(binary_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return np.zeros((h, w), dtype=np.uint8)

    areas = [cv2.contourArea(cnt) for cnt in contours]
    if not areas:
        return np.zeros((h, w), dtype=np.uint8)

    target_square_area = np.median(areas)
    if target_square_area == 0:
        return np.zeros((h, w), dtype=np.uint8)

    filtered = [
        cnt for cnt in contours
        if 0.8 < (cv2.contourArea(cnt) / target_square_area) < 1.2
    ]

    if not filtered:
        return np.zeros((h, w), dtype=np.uint8)

    try:
        rect_pts = np.concatenate(
            [[np.array(cv2.minAreaRect(cnt)[0]).astype(int)] for cnt in filtered]
        )
        rect = cv2.minAreaRect(rect_pts)
        box_points = cv2.boxPoints(rect).astype("float32")
    except Exception:
        return np.zeros((h, w), dtype=np.uint8)

    centers = [[i * 100, j * 100] for j in range(6) for i in range(4)]
    try:
        new_rect = cv2.minAreaRect(np.array(centers))
        box_points_new = cv2.boxPoints(new_rect).astype("float32")
        m_transform = cv2.getPerspectiveTransform(box_points_new, box_points)
        new_centers = cv2.transform(np.array([centers]), m_transform)[0][:, 0:2]
    except Exception:
        return np.zeros((h, w), dtype=np.uint8)

    chip_mask = np.zeros((h, w), dtype=np.uint8)

    for pt in new_centers:
        x, y = int(pt[0]), int(pt[1])
        if 0 <= x < w and 0 <= y < h:
            cv2.circle(chip_mask, (x, y), 5, 255, -1)

    return chip_mask
