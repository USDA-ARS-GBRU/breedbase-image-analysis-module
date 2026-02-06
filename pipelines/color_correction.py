# analysis/color_correction.py
from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def format_ref_matrix_cal(chip_mask: np.ndarray) -> np.ndarray:
    """
    Build reference color matrix based on detected number of color chips.

    Args:
        chip_mask: labeled mask where unique non-zero values respresent chips

    Returns:
        color_matrix: (N x 4) matrix:
            column 0 = chip number
            columns 1-3 = normalized reference RGB values (0-1)
    """

    if chip_mask.ndim != 2:
        raise ValueError("chip_mask must be 2D")
        
    # Count the number of chips identified in chip_mask (gives an idea of which color card was used)
    N_chips = len(np.unique(chip_mask))-1
    if N_chips <= 0:
        raise ValueError("No color chips detected in chip_mask")

    # --- Extended card (e.g. citrus card) ---
    if N_chips > 26:
        ref = np.array([[ 92,  95, 152],
                        [171, 120,  99],
                        [210, 148, 118],
                        [131, 146, 170],
                        [129, 152, 101],
                        [156, 141, 176],
                        [107, 186, 155],
                        [205,  90,  89],
                        [108, 125,  81],
                        [135, 146,  78],
                        [204, 122,  74],
                        [206, 134,  71],
                        [ 93, 167, 106],
                        [209, 127,  65],
                        [114, 116, 167],
                        [212, 104, 102],
                        [152, 104, 142],
                        [154, 181,  72],
                        [210, 150,  59],
                        [211, 175,  51],
                        [ 89, 160, 172],
                        [186, 159,  72],
                        [207, 151,  66],
                        [204, 122,  74],
                        [214, 103, 135],
                        [214, 217, 207],
                        [211, 213, 202],
                        [209, 207, 190],
                        [200, 196, 174],
                        [188, 181, 160],
                        [163, 161, 143],
                        [140, 138, 124]], dtype=np.float64)
            # Source for bins https://citrusvariety.ucr.edu/citrus-varieties/fruit-quality-evaluation-data
        if N_chips > ref.shape[0]:
            raise ValueError(
                f"Detected {N_chips} chips but reference supports {ref.shape[0]}"
            )
        
        chip_nb = np.arange(1, N_chips + 1)
        color_matrix_wo_chip_nb = ref[:N_chips] / 255.0
        color_matrix = np.concatenate(
            (chip_nb.reshape(N_chips, 1), color_matrix_wo_chip_nb), 
            axis=1,
        )

    # --- Standard 24-chip color card ---
    else:
        ref = np.array([[115, 82, 68],  # dark skin
                        [194, 150, 130],  # light skin
                        [98, 122, 157],  # blue sky
                        [87, 108, 67],  # foliage
                        [133, 128, 177],  # blue flower
                        [103, 189, 170],  # bluish green
                        [214, 126, 44],  # orange
                        [80, 91, 166],  # purplish blue
                        [193, 90, 99],  # moderate red
                        [94, 60, 108],  # purple
                        [157, 188, 64],  # yellow green
                        [224, 163, 46],  # orange yellow
                        [56, 61, 150],  # blue
                        [70, 148, 73],  # green
                        [175, 54, 60],  # red
                        [231, 199, 31],  # yellow
                        [187, 86, 149],  # magenta
                        [8, 133, 161],  # cyan
                        [243, 243, 242],  # white (.05*)
                        [200, 200, 200],  # neutral 8 (.23*)
                        [160, 160, 160],  # neutral 6.5 (.44*)
                        [122, 122, 121],  # neutral 5 (.7*)
                        [85, 85, 85],  # neutral 3.5 (1.05*)
                        [52, 52, 52]], dtype=np.float64)  # black (1.50*)
        
        if N_chips != 24:
            raise ValueError(
                f"Expected 24-chip card, but detected {N_chips} chips"
            )

        # array of indices from 1 to N chips in order to match the chip numbering
        idx = np.arange(N_chips) + 1
        chip_nb = np.arange(10, 10 * N_chips + 1, 10)
        
        # indices in the shape of the color card
        cc_indices = idx.reshape((4, 6), order='C')
        
        # rotate the indices depending on the specified orientation
        cc_indices_rot = np.rot90(cc_indices, k=3, axes=(0, 1))
        # arange color values based on the indices
        
        color_matrix_wo_chip_nb = (
            ref[(cc_indices_rot - 1).reshape(-1), :] / 255.0
        )
        
    return np.concatenate((chip_nb.reshape(N_chips, 1), color_matrix_wo_chip_nb), axis=1)


def extract_chip_colors(bgr_img: np.ndarray, chip_mask: np.ndarray) -> np.ndarray:
    """
    Compute per-chip mean RGB values from labeled chip mask.

    Args:
        bgr_img: BGR image (H x W x 3)
        chip_mask: labeled mask (H x W), unique non-zero = chips ID

    Returns:
        color_matrix: (N x 4)
            column 0 = chip number
            columns 1-3 = normalized mean RGB values (0-1)
    """
    
    # Check for RGB input
    if bgr_img.ndim != 3 or bgr_img.shape[2] != 3:
        raise ValueError("bgr_img must be HxWx3")
    # Check mask for gray-scale
    if chip_mask.ndim != 2:
        raise ValueError("chip_mask must be 2D")
    
    # convert to float and normalize to work with values between 0-1
    img_norm = bgr_img.astype(np.float64) / 255.0

    chip_ids = [i for i in np.unique(chip_mask) if i != 0]
    if not chip_ids:
        raise ValueError("No labeled chips found in mask.")
    
    # create empty color_matrix
    color_matrix = np.zeros((length(chip_ids), 4), dtype=np.float64)


    for row_idx, chip_id in enumerate(chip_ids):
        chip_pixels = img_norm[chip_mask == chip_id]

        if chip_pixels.size == 0:
            continue

        # OpenCV BGR -> convert to RGB order
        color_matrix[row_idx, 0] = chip_id
        color_matrix[row_idx, 1] = np.mean(chip_pixels[:, 2]) # R
        color_matrix[row_idx, 2] = np.mean(chip_pixels[:, 1]) # G
        color_matrix[row_idx, 3] = np.mean(chip_pixels[:, 0]) # B

    return color_matrix
    

def apply_color_correction(
    bgr_img: np.ndarray, 
    chip_mask: np.ndarray,
    *,
    fail_behavior: str = "passthrough",
    min_chips: int = 12,
    max_condition_number: float = 1e8,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Fit affine color transform using reference color chips and apply to image.

    - If correction fails for any reason, returns original image unchaged (default).
    - Returns a qc dict describing what happened. 
    
    Args:
        bgr_img: Input BGR image.
        chip_mask: Labeled chip mask.
        fail_behavior:
            - "passthrough" (default): return original image on failure
            - "raise": raise exception on failure
        min_chips: minimum number of detected chips required to attempt correction.
        max_condition_number: if regression matrix is ill-conditioned above this, 
                              treat as failure.

    Returns:
        corrected_bgr: corrected image (or original if skipped or failed)
        qc: dict with fields:
            - color_correction_applied (bool)
            - color_card_present (bool)
            - chips_detected (int)
            - reason (str or None)
    """

    qc: Dict[str, Any] = {
        "color_correction_applied": False,
        "color_card_present": False,
        "chips_detected": 0,
        "reason": None,
    }

    # Basic validation
    if bgr_img is None or not isinstance(bgr_img, np.ndarray):
        msg = "Input image is None or invalid"
        qc["reason"] = msg
        if fail_behavior == "raise":
            raise ValueError(msg)
        return bgr_img, qc

    if bgr_img.ndim != 3 or bgr_img.shape[2] != 3:
        msg = f"Expected HxWx3 BGR image, got shape={getattr(bgr_img, 'shape', None)}"
        qc["reason"] = msg
        if fail_behavior == "raise":
            raise ValueError(msg)
        return bgr_img, qc

    if chip_mask is None or not isinstance(chip_mask, np.ndarray) or chip_mask.ndim != 2:
        # No chip_mask -> skip correction
        qc["reason"] = "chip_mask is missing or invalid; skipping color correction"
        return bgr_img, qc

    # Count chips (uniwue non-zero ids)
    chip_ids = [int(i) for i in np.unique(chip_mask) if i != 0]
    qc["chips_detected"] = len(chip_ids)
    qc["color_card_present"] = qc["chips_detected"] > 0

    if qc["chips_detected"] < min_chips:
        qc["reason"] = f"insufficient chips for correction (detected={qc['chips_detected']}, min={min_chips})"
        return bgr_img, qc

    try:
    
        source_matrix = extract_chip_colors(bgr_img, chip_mask)
        target_matrix = format_ref_matrix_cal(chip_mask)
    
        if source_matrix.shape != target_matrix.shape:
            raise ValueError(
                f"source/target matrix shape mismatch: {source_matrix.shape} vs {target_matrix.shape}"
            )
            
        # number of references
        n = source_matrix.shape[0]
    
        # Subset for extended reference card
        if n > 25:
            indices = np.hstack(
                [np.arange(start, end) for start, end in [(0, 8), (12, 21), (24, 25), (26, 32)]]
            )
            source_matrix = source_matrix[indices]
            target_matrix = target_matrix[indices]
            n = source_matrix.shape[0]
        
        # --- Build regression system: S * coeffs ~= T ---
        S = np.concatenate(
            (source_matrix[:, 1:].copy(), np.ones((n, 1))), 
            axis=1,
        ) # (n x 4)
    
        # make vectors of target values for each color
        T = target_matrix[:, 1:] # (n x 3)

        # Ill-conditioning check
        cond = np.linalg.cond(S)
        if not np.isfinite(cond) or cond > max_condition_number:
            raise RuntimeError(f"regression matrix ill-conditioned (cond={cond:.3g})")
        
        coeffs = np.linalg.pinv(S) @ T # (4 x 3)
    
        # --- Apply transform ---
        h, w, _ = bgr_img.shape
        img_rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
        
        pix = img_rgb.reshape(h * w, c).astype(np.float64) / 255.0
        pix_aug = np.concatenate((pix, np.ones((h * w, 1))), axis=1) # (hw x 4)
    
        corrected = np.clip(pix_aug @ coeffs, 0, 1)
    
        corrected_rgb = (corrected.reshape(h, w, 3) * 255).astype(np.uint8)
    
        # reconstruct the RGB (actually BGR for openCV) image
        corrected_bgr = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)

        qc["color_correction_applied"] = True
        qc["reason"] = None
        return corrected_bgr, qc
    
    except Exception as e:
        qc["reason"] = f"color correction failed: {type(e).__name__}: {e}"
        logger.exception(qc["reason"])

        if fail_behavior == "raise":
            raise
        return bgr_img, qc


