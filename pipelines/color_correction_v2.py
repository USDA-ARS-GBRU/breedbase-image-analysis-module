	# color/color_correction.py

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from pipelines.create_chip_mask_v3 import CHIP_LABELS, REFERENCE_RGB

logger = logging.getLogger(__name__)

# Supported correction methods
METHODS = ("affine", "root_polynomial", "lab_affine")

# Number of skipped LOO folds above which an image is flagged as unreliable
# for method comparison purposes.
LOO_SKIP_FLAG_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Feature matrix construction
# ---------------------------------------------------------------------------

def _build_features(rgb: np.ndarray, method: str) -> np.ndarray:
    """
    Build the regression feature matrix for a given correction method.

    Parameters
    ----------
    rgb : np.ndarray, shape (N, 3), float64, values in [0, 1]
        Per-chip mean RGB values.
    method : str
        "affine"          — [R  G  B  1]               → shape (N, 4)
        "root_polynomial" — [R  G  B  √R  √G  √B
                             √(RG)  √(RB)  √(GB)  1]  → shape (N, 10)

    Returns
    -------
    np.ndarray, shape (N, n_features)
    """
    R, G, B = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    if method == "affine":
        return np.column_stack([R, G, B, np.ones(len(R))])
    elif method == "root_polynomial":
        return np.column_stack([
            R, G, B,
            np.sqrt(np.abs(R)),
            np.sqrt(np.abs(G)),
            np.sqrt(np.abs(B)),
            np.sqrt(np.abs(R * G)),
            np.sqrt(np.abs(R * B)),
            np.sqrt(np.abs(G * B)),
            np.ones(len(R)),
        ])
    else:
        raise ValueError(
            f"Unknown method '{method}'. Valid options: {METHODS}"
        )


# ---------------------------------------------------------------------------
# L*a*b* feature matrix and correction helpers
# ---------------------------------------------------------------------------

def _build_features_lab_ab(ab: np.ndarray) -> np.ndarray:
    """
    Build the affine feature matrix for a*b* correction.

    Parameters
    ----------
    ab : np.ndarray, shape (N, 2), float64
        a* and b* channel values in OpenCV uint8 LAB scale [0, 255].

    Returns
    -------
    np.ndarray, shape (N, 3)  — [a, b, 1]
    """
    return np.column_stack([ab, np.ones(len(ab))])


def _rgb_norm_to_lab(rgb_norm: np.ndarray) -> np.ndarray:
    """
    Convert normalized RGB float [0, 1] to OpenCV uint8 L*a*b* float64.

    Parameters
    ----------
    rgb_norm : np.ndarray, shape (N, 3), float64, values in [0, 1]

    Returns
    -------
    np.ndarray, shape (N, 3), float64
        L in [0, 255], a and b in [0, 255] (128 = neutral).
    """
    bgr_u8 = (rgb_norm[:, ::-1] * 255.0).clip(0, 255).astype(np.uint8)
    return (
        cv2.cvtColor(bgr_u8.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB)
        .reshape(-1, 3)
        .astype(np.float64)
    )


def _fit_and_apply_lab(
    bgr_img           : np.ndarray,
    source_rgb        : np.ndarray,
    target_rgb        : np.ndarray,
    correct_luminance : bool,
    max_condition_number: float,
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], float]:
    """
    Fit an affine correction in L*a*b* chrominance (a*, b*) only and
    apply it to the full image.  L* passes through unchanged unless
    correct_luminance=True, which adds a 1D linear L* fit.

    Motivation
    ----------
    Affine correction in RGB couples luminance and chrominance.  For
    curved fruit, specular highlight-edge pixels sit near the boundary
    of the chip training gamut in RGB space, causing the affine transform
    to extrapolate in a direction that corrupts hue (manifesting as
    orange-red corrected hue on green fruit).  In L*a*b* space these
    same pixels are high-L* but their a*b* values remain near the green
    cluster centroid, so the 2D a*b* affine interpolates rather than
    extrapolates.  Corrected hue on highlight-edge pixels is therefore
    stable regardless of fruit curvature.

    Parameters
    ----------
    bgr_img : np.ndarray, uint8, shape (H, W, 3)
    source_rgb : np.ndarray, shape (N, 3), float64, values in [0, 1]
        Per-chip mean RGB from the image.
    target_rgb : np.ndarray, shape (N, 3), float64, values in [0, 1]
        Corresponding sRGB reference values.
    correct_luminance : bool
        If True, also fit a 1D linear L* correction from chip data.
        Default False.  L* correction is appropriate only when a
        consistent luminance reference is available across all images;
        for per-image ColorChecker correction under variable field
        illumination, leaving L* uncorrected is preferred.
    max_condition_number : float
        Reject the regression if the a*b* feature matrix condition
        number exceeds this threshold.

    Returns
    -------
    corrected_bgr : np.ndarray, uint8, shape (H, W, 3)
    coeffs_ab : np.ndarray, shape (3, 2)
        Fitted a*b* affine coefficients.
    coeffs_l : np.ndarray, shape (2,) or None
        Fitted L* linear coefficients, or None if correct_luminance=False.
    condition_number : float
        Condition number of the a*b* feature matrix.
    """
    source_lab = _rgb_norm_to_lab(source_rgb)
    target_lab = _rgb_norm_to_lab(target_rgb)

    # Fit 2D a*b* affine: [a, b, 1] -> [a', b']
    S_ab  = _build_features_lab_ab(source_lab[:, 1:3])
    cond  = float(np.linalg.cond(S_ab))

    if not np.isfinite(cond) or cond > max_condition_number:
        raise RuntimeError(
            f"a*b* regression matrix ill-conditioned (cond={cond:.3g})"
        )

    coeffs_ab = np.linalg.pinv(S_ab) @ target_lab[:, 1:3]  # (3, 2)

    # Optional 1D linear L* fit: [L, 1] -> L'
    coeffs_l = None
    if correct_luminance:
        S_l      = np.column_stack([source_lab[:, 0], np.ones(len(source_lab))])
        coeffs_l = np.linalg.pinv(S_l) @ target_lab[:, 0]  # (2,)

    # Apply to full image
    h, w, _ = bgr_img.shape
    img_lab  = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2LAB).astype(np.float64)
    flat     = img_lab.reshape(-1, 3)

    corrected              = flat.copy()
    S_ab_img               = _build_features_lab_ab(flat[:, 1:3])
    corrected[:, 1:3]      = np.clip(S_ab_img @ coeffs_ab, 0.0, 255.0)

    if correct_luminance and coeffs_l is not None:
        S_l_img            = np.column_stack([flat[:, 0], np.ones(len(flat))])
        corrected[:, 0]    = np.clip(S_l_img @ coeffs_l, 0.0, 255.0)

    corrected_lab_img = corrected.reshape(h, w, 3).astype(np.uint8)
    corrected_bgr     = cv2.cvtColor(corrected_lab_img, cv2.COLOR_LAB2BGR)

    return corrected_bgr, coeffs_ab, coeffs_l, cond


# ---------------------------------------------------------------------------
# Chip color extraction
# ---------------------------------------------------------------------------

def _extract_chip_colors(
    bgr_img: np.ndarray,
    chip_mask: np.ndarray,
    label_to_canonical: Dict[int, int],
) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """
    Extract per-chip mean RGB and corresponding reference RGB.

    Returns
    -------
    source_rgb : np.ndarray, shape (N, 3), float64
        Mean RGB per chip from the image, normalized to [0, 1].
    target_rgb : np.ndarray, shape (N, 3), float64
        Corresponding REFERENCE_RGB entries, normalized to [0, 1].
    chip_labels : List[int]
        Chip label values in ascending order (matches row order of arrays).
    """
    chip_labels = sorted([int(v) for v in np.unique(chip_mask) if v != 0])
    n = len(chip_labels)
    source_rgb = np.zeros((n, 3), dtype=np.float64)
    target_rgb = np.zeros((n, 3), dtype=np.float64)

    img_f = bgr_img.astype(np.float64) / 255.0

    for row, label in enumerate(chip_labels):
        if label not in label_to_canonical:
            raise ValueError(
                f"chip label {label} not found in CHIP_LABELS — "
                "chip_mask was not produced by create_chip_mask()"
            )
        canonical_i      = label_to_canonical[label]
        pixels_bgr       = img_f[chip_mask == label]
        if pixels_bgr.size == 0:
            raise ValueError(f"chip label {label} has no pixels in mask")
        source_rgb[row]  = pixels_bgr.mean(axis=0)[::-1]   # BGR → RGB
        target_rgb[row]  = REFERENCE_RGB[canonical_i] / 255.0

    return source_rgb, target_rgb, chip_labels


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fit_and_apply(
    bgr_img: np.ndarray,
    source_rgb: np.ndarray,
    target_rgb: np.ndarray,
    method: str,
    max_condition_number: float,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Fit correction coefficients and apply to the full image.

    Returns
    -------
    corrected_bgr : np.ndarray
    coeffs : np.ndarray, shape (n_features, 3)
    condition_number : float
    """
    S    = _build_features(source_rgb, method)
    cond = float(np.linalg.cond(S))

    if not np.isfinite(cond) or cond > max_condition_number:
        raise RuntimeError(
            f"regression matrix ill-conditioned (cond={cond:.3g})"
        )

    coeffs = np.linalg.pinv(S) @ target_rgb   # (n_features, 3)

    h, w, _ = bgr_img.shape
    img_rgb  = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB).astype(np.float64) / 255.0
    pix      = img_rgb.reshape(-1, 3)
    pix_feat = _build_features(pix, method)
    corrected_f   = np.clip(pix_feat @ coeffs, 0.0, 1.0)
    corrected_rgb = (corrected_f.reshape(h, w, 3) * 255).astype(np.uint8)
    corrected_bgr = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)

    return corrected_bgr, coeffs, cond


def _post_correction_delta_e(
    corrected_bgr: np.ndarray,
    chip_mask: np.ndarray,
    chip_labels: List[int],
    target_rgb: np.ndarray,
) -> float:
    """Mean Euclidean error in normalized RGB space after correction."""
    f64 = corrected_bgr.astype(np.float64) / 255.0
    errors = []
    for row, label in enumerate(chip_labels):
        pixels = f64[chip_mask == label]
        if pixels.size == 0:
            continue
        mean_rgb = pixels.mean(axis=0)[::-1]   # BGR → RGB
        errors.append(float(np.sqrt(((mean_rgb - target_rgb[row]) ** 2).sum())))
    return float(np.mean(errors)) if errors else float("nan")


def _fail(
    reason: str,
    img: np.ndarray,
    qc: Dict[str, Any],
    fail_behavior: str,
    exc_type: type = RuntimeError,
    exc: Optional[Exception] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Set qc reason and either return passthrough or raise."""
    qc["reason"] = reason
    if fail_behavior == "raise":
        raise (exc if exc is not None else exc_type(reason))
    return img, qc


# ---------------------------------------------------------------------------
# Public: apply_color_correction
# ---------------------------------------------------------------------------

def apply_color_correction(
    bgr_img: np.ndarray,
    chip_mask: np.ndarray,
    *,
    method: str = "affine",
    fail_behavior: str = "passthrough",
    min_chips: int = 24,
    max_condition_number: float = 1e8,
    correct_luminance: bool = False,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Fit a color correction transform from detected chip colors to reference
    values and apply it to the full image.

    The chip_mask must be the output of create_chip_mask(). Each non-zero
    pixel value is a CHIP_LABELS entry that maps directly to a canonical
    chip index and its REFERENCE_RGB row — no additional orientation
    remapping is applied here.

    Parameters
    ----------
    bgr_img : np.ndarray
        Input BGR image, uint8, shape (H, W, 3).
    chip_mask : np.ndarray
        Labeled chip mask from create_chip_mask(), shape (H, W), uint8.
    method : str
        Correction method. One of:

        "affine" (default)
            Fits [R G B 1] → [R' G' B'] using a 4×3 matrix in RGB space.
            Fast, well-conditioned, robust. Suitable for global
            illumination and white balance correction. May extrapolate
            incorrectly at specular highlight-edge pixels on curved fruit,
            producing anomalous hue in the corrected output.

        "root_polynomial"
            Fits [R G B √R √G √B √(RG) √(RB) √(GB) 1] → [R' G' B']
            using a 10×3 matrix. Captures nonlinear illumination
            effects. Requires more chips to remain well-conditioned
            but is overdetermined with 24 chips.

        "lab_affine"
            Fits an affine transform on the a* and b* channels of
            L*a*b* space only: [a, b, 1] → [a', b']. L* passes through
            unchanged (or receives a 1D linear fit when
            correct_luminance=True). Recommended when the fruit pool
            contains curved specimens that exhibit anomalous corrected
            hue under the RGB affine method. Highlight-edge pixels on
            curved surfaces have a*b* values near the chip cluster
            centroid regardless of luminance, so the 2D a*b* affine
            interpolates rather than extrapolates at those pixels.

    fail_behavior : str
        "passthrough" (default) — return original image on failure.
        "raise" — raise the exception instead.
    min_chips : int
        Minimum chips required. Default 24 (all chips required).
    max_condition_number : float
        Reject the regression if its condition number exceeds this.
    correct_luminance : bool
        Only meaningful when method="lab_affine". If True, a 1D linear
        L* correction is fitted from chip data alongside the a*b* affine.
        Default False. Leave False for per-image field correction where
        a consistent absolute luminance reference is unavailable.

    Returns
    -------
    corrected_bgr : np.ndarray
        Color-corrected BGR image, or original if correction failed/skipped.
    qc : dict
        color_correction_applied : bool
        color_card_present : bool
        chips_detected : int
        method : str
        correct_luminance : bool
            Echoes the correct_luminance argument. Always False for
            non-lab_affine methods.
        condition_number : float or None
        mean_pre_delta_e : float or None
            Mean Euclidean error in normalized RGB before correction.
        mean_post_delta_e : float or None
            Mean Euclidean error in normalized RGB after correction.
        reason : str or None
    """
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}'. Valid options: {METHODS}")

    # correct_luminance is only valid for lab_affine; ignore silently otherwise
    _correct_lum = correct_luminance and method == "lab_affine"

    qc: Dict[str, Any] = {
        "color_correction_applied": False,
        "color_card_present":       False,
        "chips_detected":           0,
        "method":                   method,
        "correct_luminance":        _correct_lum,
        "condition_number":         None,
        "mean_pre_delta_e":         None,
        "mean_post_delta_e":        None,
        "reason":                   None,
    }

    # Input validation
    if bgr_img is None or not isinstance(bgr_img, np.ndarray):
        return _fail("Input image is None or invalid",
                     bgr_img, qc, fail_behavior, ValueError)
    if bgr_img.ndim != 3 or bgr_img.shape[2] != 3:
        return _fail(
            f"Expected HxWx3 BGR image, got shape "
            f"{getattr(bgr_img, 'shape', None)}",
            bgr_img, qc, fail_behavior, ValueError,
        )
    if chip_mask is None or not isinstance(chip_mask, np.ndarray) \
            or chip_mask.ndim != 2:
        return _fail(
            "chip_mask is missing or invalid; skipping color correction",
            bgr_img, qc, fail_behavior,
        )

    # Chip inventory
    chip_labels_found = sorted([int(v) for v in np.unique(chip_mask) if v != 0])
    qc["chips_detected"]     = len(chip_labels_found)
    qc["color_card_present"] = qc["chips_detected"] > 0

    if qc["chips_detected"] < min_chips:
        return _fail(
            f"insufficient chips for correction "
            f"(detected={qc['chips_detected']}, min={min_chips})",
            bgr_img, qc, fail_behavior,
        )

    label_to_canonical = {int(CHIP_LABELS[i]): i
                          for i in range(len(CHIP_LABELS))}

    try:
        source_rgb, target_rgb, chip_labels = _extract_chip_colors(
            bgr_img, chip_mask, label_to_canonical
        )

        pre_errors = np.sqrt(((source_rgb - target_rgb) ** 2).sum(axis=1))
        qc["mean_pre_delta_e"] = float(pre_errors.mean())

        if method == "lab_affine":
            corrected_bgr, _, _, cond = _fit_and_apply_lab(
                bgr_img, source_rgb, target_rgb,
                _correct_lum, max_condition_number,
            )
        else:
            corrected_bgr, _, cond = _fit_and_apply(
                bgr_img, source_rgb, target_rgb, method, max_condition_number
            )
        qc["condition_number"] = cond

        qc["mean_post_delta_e"] = _post_correction_delta_e(
            corrected_bgr, chip_mask, chip_labels, target_rgb
        )

        qc["color_correction_applied"] = True
        return corrected_bgr, qc

    except Exception as exc:
        msg = f"color correction failed: {type(exc).__name__}: {exc}"
        logger.exception(msg)
        return _fail(msg, bgr_img, qc, fail_behavior, type(exc), exc)


# ---------------------------------------------------------------------------
# Public: compare_correction_methods
# ---------------------------------------------------------------------------

def compare_correction_methods(
    images: List[Tuple[np.ndarray, np.ndarray]],
    *,
    max_condition_number: float = 1e8,
    skip_flag_threshold: int = LOO_SKIP_FLAG_THRESHOLD,
    print_summary: bool = True,
) -> Dict[str, Any]:
    """
    Compare affine and root-polynomial correction on a set of images using
    leave-one-out (LOO) cross-validation on the 24 color chips.

    For each image and each method, the function fits a correction on 23
    chips and evaluates the predicted color of the held-out chip, rotating
    through all 24 chips.  The mean LOO delta E is the primary comparison
    metric because it estimates generalization performance — how well the
    transform corrects colors not used in fitting — rather than in-sample
    fit quality which always favors more complex models.

    Near-singular LOO folds (condition number above max_condition_number)
    are skipped and noted in per-image QC.  If more than skip_flag_threshold
    folds are skipped for a single image, that image is flagged as unreliable
    for comparison purposes and excluded from the cross-method aggregate.

    Parameters
    ----------
    images : list of (bgr_img, chip_mask) tuples
        Each element is a pair as returned by the upstream pipeline.
        chip_mask must be the output of create_chip_mask().
    max_condition_number : float
        Condition number ceiling for LOO fold acceptance.
    skip_flag_threshold : int
        Maximum number of skipped LOO folds before an image is flagged
        and excluded from the aggregate summary. Default 2.
    print_summary : bool
        If True, print a formatted summary table to stdout.

    Returns
    -------
    dict with the following structure:

        per_image : List[dict]
            One entry per input image with keys:
                image_index : int
                flagged : bool
                    True if skipped folds > skip_flag_threshold for any
                    method, indicating the LOO estimate is unreliable.
                affine : dict
                    loo_mean_delta_e, loo_std_delta_e, loo_min, loo_max,
                    skipped_folds, per_fold_errors (list, None = skipped)
                root_polynomial : dict
                    same keys as affine
                lab_affine : dict
                    same keys as affine. LOO fitting is performed in
                    L*a*b* space (a*b* channels only); errors are
                    converted back to normalized RGB space for
                    comparability with the other methods.

        aggregate : dict
            Computed over non-flagged images only:
                n_images_included : int
                n_images_flagged : int
                affine : dict
                    mean_loo_delta_e, std_loo_delta_e
                root_polynomial : dict
                    same keys
                lab_affine : dict
                    same keys
                recommended_method : str
                    The method with the lower mean LOO delta E across
                    non-flagged images.  "inconclusive" if the minimum
                    difference between any two methods is less than 0.005
                    (half a percentage point in normalized RGB space).
                mean_delta_e_difference : float
                    affine mean minus root_polynomial mean (positive =
                    root_polynomial is better). Retained for
                    backwards compatibility. Compare lab_affine via
                    the per-method aggregate entries directly.
    """
    label_to_canonical = {int(CHIP_LABELS[i]): i
                          for i in range(len(CHIP_LABELS))}

    per_image_results = []

    for img_idx, (bgr_img, chip_mask) in enumerate(images):
        img_result: Dict[str, Any] = {
            "image_index": img_idx,
            "flagged":     False,
        }

        # Extract chip colors for this image
        try:
            source_rgb, target_rgb, _ = _extract_chip_colors(
                bgr_img, chip_mask, label_to_canonical
            )
        except Exception as exc:
            logger.warning(
                f"Image {img_idx}: chip extraction failed — {exc}. Skipping."
            )
            img_result["flagged"] = True
            img_result["flag_reason"] = str(exc)
            for m in METHODS:
                img_result[m] = None
            per_image_results.append(img_result)
            continue

        n = len(source_rgb)

        # Pre-compute LAB representations once per image for lab_affine LOO
        source_lab = _rgb_norm_to_lab(source_rgb)
        target_lab = _rgb_norm_to_lab(target_rgb)

        for method in METHODS:
            loo_errors: List[Optional[float]] = []
            skipped = 0

            for i in range(n):
                train_idx = [j for j in range(n) if j != i]

                if method == "lab_affine":
                    # Fit a*b* affine on 23 chips in LAB space; evaluate
                    # held-out chip error in normalized RGB space for
                    # comparability with the RGB-space methods.
                    S_train = _build_features_lab_ab(source_lab[train_idx, 1:3])
                    T_train = target_lab[train_idx, 1:3]

                    cond = float(np.linalg.cond(S_train))
                    if not np.isfinite(cond) or cond > max_condition_number:
                        loo_errors.append(None)
                        skipped += 1
                        continue

                    coeffs   = np.linalg.pinv(S_train) @ T_train
                    S_test   = _build_features_lab_ab(source_lab[[i], 1:3])
                    pred_ab  = (S_test @ coeffs)[0]  # (2,) predicted a*, b*

                    # Reconstruct LAB using source L* (L not corrected)
                    pred_lab_px = np.array(
                        [source_lab[i, 0], pred_ab[0], pred_ab[1]],
                        dtype=np.float64,
                    )
                    pred_lab_u8 = (
                        np.clip(pred_lab_px, 0, 255)
                        .astype(np.uint8)
                        .reshape(1, 1, 3)
                    )
                    pred_bgr   = cv2.cvtColor(pred_lab_u8, cv2.COLOR_LAB2BGR)
                    pred_rgb   = pred_bgr[0, 0, ::-1].astype(np.float64) / 255.0

                    err = float(np.sqrt(((pred_rgb - target_rgb[i]) ** 2).sum()))

                else:
                    S_train = _build_features(source_rgb[train_idx], method)
                    T_train = target_rgb[train_idx]

                    cond = float(np.linalg.cond(S_train))
                    if not np.isfinite(cond) or cond > max_condition_number:
                        loo_errors.append(None)
                        skipped += 1
                        continue

                    coeffs = np.linalg.pinv(S_train) @ T_train
                    S_test = _build_features(source_rgb[[i]], method)
                    pred   = (S_test @ coeffs)[0]
                    err    = float(np.sqrt(((pred - target_rgb[i]) ** 2).sum()))

                loo_errors.append(err)

            valid = [e for e in loo_errors if e is not None]
            img_result[method] = {
                "loo_mean_delta_e": float(np.mean(valid)) if valid else None,
                "loo_std_delta_e":  float(np.std(valid))  if valid else None,
                "loo_min":          float(np.min(valid))  if valid else None,
                "loo_max":          float(np.max(valid))  if valid else None,
                "skipped_folds":    skipped,
                "per_fold_errors":  loo_errors,
            }

        # Flag image if any method skipped too many folds
        for method in METHODS:
            if img_result[method] is not None and \
                    img_result[method]["skipped_folds"] > skip_flag_threshold:
                img_result["flagged"] = True
                img_result["flag_reason"] = (
                    f"{method}: {img_result[method]['skipped_folds']} "
                    f"LOO folds skipped (threshold={skip_flag_threshold})"
                )

        per_image_results.append(img_result)

    # ------------------------------------------------------------------
    # Aggregate over non-flagged images
    # ------------------------------------------------------------------
    included = [r for r in per_image_results if not r["flagged"]]
    flagged  = [r for r in per_image_results if r["flagged"]]

    agg: Dict[str, Any] = {
        "n_images_included": len(included),
        "n_images_flagged":  len(flagged),
    }

    for method in METHODS:
        means = [
            r[method]["loo_mean_delta_e"]
            for r in included
            if r[method] is not None and r[method]["loo_mean_delta_e"] is not None
        ]
        agg[method] = {
            "mean_loo_delta_e": float(np.mean(means)) if means else None,
            "std_loo_delta_e":  float(np.std(means))  if means else None,
        }

    # Recommended method: lowest mean LOO delta E across all three methods.
    # "inconclusive" if the two best methods differ by less than 0.005.
    method_means = {
        m: agg[m]["mean_loo_delta_e"]
        for m in METHODS
        if agg[m]["mean_loo_delta_e"] is not None
    }
    if len(method_means) >= 2:
        best   = min(method_means, key=method_means.__getitem__)
        second = sorted(method_means, key=method_means.__getitem__)[1]
        gap    = method_means[second] - method_means[best]
        agg["recommended_method"] = "inconclusive" if gap < 0.005 else best
    else:
        agg["recommended_method"] = "inconclusive"

    # Backwards-compatible affine vs root_polynomial difference
    if (agg["affine"]["mean_loo_delta_e"] is not None and
            agg["root_polynomial"]["mean_loo_delta_e"] is not None):
        agg["mean_delta_e_difference"] = float(
            agg["affine"]["mean_loo_delta_e"]
            - agg["root_polynomial"]["mean_loo_delta_e"]
        )
    else:
        agg["mean_delta_e_difference"] = None

    result = {"per_image": per_image_results, "aggregate": agg}

    # ------------------------------------------------------------------
    # Optional printed summary
    # ------------------------------------------------------------------
    if print_summary:
        _print_summary(result)

    return result


def _print_summary(result: Dict[str, Any]) -> None:
    """Print a formatted summary table of the comparison results."""
    agg = result["aggregate"]
    per = result["per_image"]

    print("\n" + "=" * 84)
    print("  Color Correction Method Comparison")
    print("=" * 84)
    print(f"  Images included in aggregate: {agg['n_images_included']}")
    print(f"  Images flagged / excluded:    {agg['n_images_flagged']}")
    print()

    # Per-image table
    print(
        f"  {'Img':>4}  {'Flagged':>7}  "
        f"{'Affine LOO dE':>14}  "
        f"{'RootPoly LOO dE':>16}  "
        f"{'LABaffine LOO dE':>17}  "
        f"{'Skips(A/RP/LA)':>14}"
    )
    print("  " + "-" * 80)
    for r in per:
        idx  = r["image_index"]
        flag = "YES" if r["flagged"] else "no"
        af   = r.get("affine")
        rp   = r.get("root_polynomial")
        la   = r.get("lab_affine")

        def _fmt(m):
            if m and m["loo_mean_delta_e"] is not None:
                return f"{m['loo_mean_delta_e']:.4f} +/-{m['loo_std_delta_e']:.4f}"
            return "  n/a"

        af_sk = af["skipped_folds"] if af else "-"
        rp_sk = rp["skipped_folds"] if rp else "-"
        la_sk = la["skipped_folds"] if la else "-"

        print(
            f"  {idx:>4}  {flag:>7}  "
            f"{_fmt(af):>14}  "
            f"{_fmt(rp):>16}  "
            f"{_fmt(la):>17}  "
            f"{af_sk!s:>4}/{rp_sk!s:>2}/{la_sk!s:<3}"
        )

    # Aggregate
    print()
    print("  Aggregate (non-flagged images only):")
    for method in METHODS:
        m = agg[method]
        if m["mean_loo_delta_e"] is not None:
            print(
                f"    {method:>18}: mean LOO dE = {m['mean_loo_delta_e']:.4f} "
                f"+/- {m['std_loo_delta_e']:.4f}"
            )
        else:
            print(f"    {method:>18}: n/a")

    print()
    rec  = agg.get("recommended_method", "inconclusive")
    diff = agg.get("mean_delta_e_difference")
    print(f"  Recommendation: {rec.upper()}")
    if diff is not None:
        print(f"  dE difference (affine - root_poly): {diff:+.4f}  "
              f"(positive = root_poly better)")
    if rec == "inconclusive":
        print("  (gap < 0.005 between best methods — prefer affine for stability)")
    print("=" * 84 + "\n")
