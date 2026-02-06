# masking/seed_mask.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

import cv2
import numpy as np
from scipy.ndimage import binary_fill_holes
from skimage.morphology import remove_small_objects

def _ensure_u8_binary_mask(mask: Optional[np.ndarray], shape_hw: Tuple[int, int]) -> np.ndarray:
    """
    Normalize mask into uint8 0/255 with the requested HxW shape.
    If mask is None, returns all-zeros
    """

    h, w = shape_hw
    if mask is None:
        return np.zeros((h, w), dtype=np.uint8)

    if not isinstance(mask, np.ndarray):
        raise ValueError(f"Mask must be a numpy array or None. Got: {type(mask)}")

    if mask.ndim != 2:
        raise ValueError(f"Mask must be 2D (H x W). Got shape={mask.shape}")

    if mask.shape != (h, w):
        raise ValueError(f"Mask shape {mask.shape} does not match image shape {(h, w)}")

    return (mask > 0).astype(np.uint8) * 255

# --------------------------------------------------------------------
# Isolate seed from corrected image
# --------------------------------------------------------------------

def create_seed_mask(
    corrected_img: np.ndarray, 
    cc_mask: Optional[np.ndarray], 
    sm_mask: Optional[np.ndarray],
    *,
    h_thresh: int = 60,
    v_thresh: int = 140,
    min_object_size: int = 100,
    fill_holes = bool = True,
    return_qc: bool = False,
) -> Union[np.ndarray, Tuple[np.ndarray, Dict[str, Any]]]:
    """
    Create a binary mask of seed objects from a color-corrected BGR image.

    - Works even if cc_mask/sm_mask are None (treated as zeros)
    - Validates input shapes and types. 
    - Returns optional QC dict without forcing pipeline refactors.

    Args:
        corrected_img: BGR image (H x W x 3), uint8 recommended.
        cc_mask: color card mask (H x W), values > 0 indicate card pixels (or None).
        sm_mask: size marker mask (H x W), values > 0 indicate marker pixels (or None).
        h_thresh: threshold on HSV H channel (invert threshold).
        v_thresh: threshold on HSV V channel (invert threshold).
        min_object_size: remove connected components smaller than this (in pixels).
        fill_holes: whether to fill holes inside objects.
        return_qc: if True, return (mask, qc_dict). If False, return mask only.

    Returns:
        seed_mask_u8: uint8 mask (H x W) with values {0,255}
        qc (optional): dict with helpful flags and counts
    
    """

    qc: Dict[str, Any] = {
        "seed_mask_created": False,
        "reason": None,
        "cc_mask_present": False,
        "sm_mask_present": False,
        "seed_pixels": 0,
    }

    # --- Validate image ---
    if corrected_img is None or not isinstance(corrected_img, np.ndarray):
        raise ValueError("corrected_img must be a numpy array (HxWx3 BGR).")

    if corrected_img.ndim != 3 or corrected_img.shape[2] != 3:
        raise ValueError(f"corrected_img must be HxWx3. Got shape={corrected_img.shape}")

    h, w = corrected_img.shape[:2]

    # --- Normalize masks ---
    cc_u8 = _ensure_u8_binary_mask(cc_mask, (h, w))
    sm_u8 = _ensure_u8_binary_mask(sm_mask, (h, w))

    qc["cc_mask_present"] = bool(int(cc_u8.max()) > 0)
    qc["sm_mask_present"] = bool(int(sm_u8.max()) > 0)

    # --- Build seed candidate mask in HSV space ---
    try:
        hsv = cv2.cvtColor(corrected_img, cv2.COLOR_BGR2HSV)
    except Exception as e:
        qc["reason"] = f"HSV conversion failed: {type(e).__name__}: {e}"
        empty = np.zeros((h, w), dtype=np.uint8)
        return (empty, qc) if return_qc else empty

    
    h_channel = hsv[:, :, 0]
    v_channel = hsv[:, :, 2]

    h_thresh = int(np.clip(h_thresh, 0, 255))
    v_thresh = int(np.clip(v_thresh, 0, 255))

    # Inverse thresholds to capture darker / lower-H regions
    _, h_binary = cv2.threshold(h_channel, h_thresh, 255, cv2.THRESH_BINARY_INV)
    _, v_binary = cv2.threshold(v_channel, v_thresh, 255, cv2.THRESH_BINARY_INV)
    
    binary = cv2.bitwise_or(h_binary, v_binary)
    
    # --- Remove colorcard and size marker with previous masks ---
    if qc["cc_mask_present"]:
        binary = cv2.bitwise_and(binary, cv2.bitwise_not(cc_u8))
    if qc["sm_mask_present"]:
        binary = cv2.bitwise_and(binary, cv2.bitwise_not(sm_u8))

    # --- Morphology cleanup ---
    bool_img = (binary > 0)

    if fill_holes:
        bool_img = binary_fill_holes(bool_img)

    if min_object_size and min_object_size > 0:
        bool_img = remove_small_objects(bool_img, min_size=int(min_object_size))
        
    seed_mask_u8 = (bool_img.astype(np.uint8) * 255)

    qc["seed_pixels"] = int(seed_mask_u8.sum() // 255)
    qc["seed_mask_created"] = True
    qc["reason"] = None if qc["seed_pixels"] > 0 else "seed mask is empty after filtering"

    return (seed_mask_u8, qc) if return_qc else seed_mask_u8
    