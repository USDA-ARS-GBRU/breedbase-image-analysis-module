# masking/chip_mask.py
#
# PURPOSE
# -------
# Detects the 24 colored chips on an X-Rite ColorChecker Classic Mini card
# that has already been located in the image (via cc_mask from create_masks()).
# Outputs a labeled uint8 mask where every chip circle is filled with a
# stable label value (CHIP_LABELS) tied to the canonical chip identity, not
# the card's physical orientation in the image.
#
# PIPELINE SUMMARY
# ----------------
#   1. Derive card bounding box and tilt angle from the cc_mask contour.
#   2. Deskew the bounding-box crop so brightness profiles run parallel to
#      chip rows/columns.
#   3. Detect chip row and column centres from dark valleys in the profiles.
#   4. Estimate chip radius from detected centre-to-centre spacing.
#   5. Map chip centres from deskewed-crop space back to full-image space.
#   6. Validate that the centres fall inside cc_mask.
#   7. Sample mean BGR colour at each centre; convert everything to CIE Lab.
#   8. Run linear assignment (Hungarian algorithm) to match detected chips
#      to reference colors — this resolves card orientation automatically.
#   9. Re-rank the six neutral gray chips by luminance to fix swap errors.
#  10. Paint each chip circle on a blank mask using its stable label value.

from __future__ import annotations
from typing import List, Optional, Tuple

import cv2
import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.optimize import linear_sum_assignment
from scipy.signal import find_peaks


# ---------------------------------------------------------------------------
# ColorChecker Classic Mini reference values (canonical row-major order)
# ---------------------------------------------------------------------------
# These are the standard sRGB values (D50 illuminant, gamma-encoded) for each
# chip in the order printed on the card: row 0 top-left → row 5 bottom-right,
# reading left to right.  Row 5 is the neutral gray ramp (chips 18–23).
#
# FAILURE RISK: if the card is a different version of the ColorChecker
# (e.g., the full 24-patch SG, or a non-X-Rite card), these values will not
# match and the assignment step will produce large ΔE errors → empty mask.

REFERENCE_RGB: np.ndarray = np.array([
    [115,  82,  68],   #  0  dark skin
    [194, 150, 130],   #  1  light skin
    [ 98, 122, 157],   #  2  blue sky
    [ 87, 108,  67],   #  3  foliage
    [133, 128, 177],   #  4  blue flower
    [103, 189, 170],   #  5  bluish green
    [214, 126,  44],   #  6  orange
    [ 80,  91, 166],   #  7  purplish blue
    [193,  90,  99],   #  8  moderate red
    [ 94,  60, 108],   #  9  purple
    [157, 188,  64],   # 10  yellow green
    [224, 163,  46],   # 11  orange yellow
    [ 56,  61, 150],   # 12  blue
    [ 70, 148,  73],   # 13  green
    [175,  54,  60],   # 14  red
    [231, 199,  31],   # 15  yellow
    [187,  86, 149],   # 16  magenta
    [  8, 133, 161],   # 17  cyan
    [243, 243, 242],   # 18  white
    [200, 200, 200],   # 19  neutral 8
    [160, 160, 160],   # 20  neutral 6.5
    [122, 122, 121],   # 21  neutral 5
    [ 85,  85,  85],   # 22  neutral 3.5
    [ 52,  52,  52],   # 23  black
], dtype=np.float32)

# CHIP_LABELS[i] is the uint8 pixel value written into the output mask for
# canonical chip i.  Values are evenly spaced from 240 (chip 0, dark skin)
# down to 10 (chip 23, black) so downstream code can map pixel value → chip
# identity with a simple linear formula.
#
# NOTE: labels are assigned by canonical index, NOT by detected brightness —
# so label 240 always means "dark skin" regardless of exposure.
CHIP_LABELS: np.ndarray = np.round(
    np.linspace(240, 10, len(REFERENCE_RGB))
).astype(np.uint8)

# Human-readable chip names in canonical order, used for overlay annotation.
CHIP_NAMES: List[str] = [
    "dark skin", "light skin", "blue sky", "foliage",
    "blue flower", "bluish green", "orange", "purplish blue",
    "moderate red", "purple", "yellow green", "orange yellow",
    "blue", "green", "red", "yellow",
    "magenta", "cyan", "white", "neutral 8",
    "neutral 6.5", "neutral 5", "neutral 3.5", "black",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rgb_to_lab_batch(rgb_255: np.ndarray) -> np.ndarray:
    """
    Convert an (N, 3) array of RGB values in [0, 255] to CIE Lab.

    WHY: CIE Lab is used for color matching because Euclidean distance in Lab
    space is perceptually uniform (ΔE76), making chip-to-reference assignment
    more accurate than matching in raw RGB or BGR.

    Steps
    -----
    1. Divide by 255 to get normalized float32 values in [0, 1].
    2. Reshape to a single-row image so cv2.cvtColor accepts it.
       cv2.cvtColor requires at least a 2-D array (H×W×C).
    3. Convert RGB→Lab using the D65 white point (cv2 default).
    4. Reshape back to (N, 3) before returning.

    Parameters
    ----------
    rgb_255 : np.ndarray, shape (N, 3), float32
        RGB values expected in [0, 255].  Values outside this range will
        still be processed but may produce Lab values outside the normal
        gamut.

    Returns
    -------
    np.ndarray, shape (N, 3), float32
        CIE Lab values: L in [0, 100], a and b roughly in [-127, 127].

    FAILURE RISKS
    -------------
    - Input must be RGB, not BGR.  Passing BGR will silently produce wrong
      Lab values, causing poor chip-to-reference matching.
    - If rgb_255 is empty (N=0), cv2.cvtColor will raise an error.
    - cv2 uses the D65 white point; REFERENCE_RGB was defined under D50.
      The resulting systematic offset is absorbed by the Hungarian assignment
      but could inflate ΔE values slightly near the threshold.
    """
    # Normalize to [0, 1] and ensure float32 for cv2
    rgb_f = (rgb_255 / 255.0).astype(np.float32)

    # Reshape (N,3) → (1,N,3) so cv2.cvtColor treats it as a 1-row image,
    # apply the colorspace conversion, then flatten back to (N,3).
    lab   = cv2.cvtColor(rgb_f.reshape(1, -1, 3), cv2.COLOR_RGB2Lab)
    return lab.reshape(-1, 3)


def _find_chip_centers_1d(
    profile: np.ndarray,
    card_dim: int,
    smooth_size: int = 10,
    valley_threshold: Optional[int] = None,
    valley_threshold_offset: int = 10,
    min_valley_distance: int = 50,
    edge_margin_frac: float = 0.06,
    min_band_width_frac: float = 0.60,
    max_band_width_frac=1.75,
) -> List[float]:
    """
    Locate chip centres along one axis of the card from its mean brightness
    profile.

    WHY: Chip separators (thin dark lines between chips), the card frame, the
    label strip at the top, and the ruler strip at the bottom all appear as
    dark valleys in the mean brightness profile.  Chip interiors are the
    bright bands between consecutive valleys.  The midpoint of each qualifying
    bright band is taken as the chip centre along this axis.

    Algorithm
    ---------
      1. Smooth the profile with a uniform (box) filter to suppress pixel-level
         noise that could produce spurious valleys.
      2. Compute the effective valley threshold adaptively from the smoothed
         profile minimum, or use the explicitly supplied value if provided.
      3. Find dark valleys (find_peaks on the negated profile) where brightness
         is below the effective threshold with at least min_valley_distance
         separation.
      4. Prepend 0 and append card_dim to the valley list so the regions at
         both ends of the card are also treated as bounding separators.
      5. Compute the midpoint of each interval between consecutive separators.
      6. Discard midpoints that lie within edge_margin_frac of the card edge —
         these come from the outer frame or bounding-box crop slivers.
      7. Discard bands narrower than min_band_width_frac × median band width.
         The label strip (top) and ruler strip (bottom) are roughly half the
         width of a chip row, so this step removes them reliably.

    Parameters
    ----------
    profile : np.ndarray
        Per-pixel mean brightness along the axis (length = card_dim).
        Typically the row-wise mean (axis=1) for row detection, or column-wise
        mean (axis=0) for column detection.
    card_dim : int
        Card extent in pixels along this axis (height for rows, width for cols).
    smooth_size : int
        Uniform-filter kernel width.  Too small → noisy profile with false
        valleys; too large → valleys near card edges get blurred away.
    valley_threshold : int or None
        Brightness ceiling: a valley is only accepted if its smoothed value
        is below this threshold.  When None (default), the threshold is set
        adaptively as int(smooth.min()) + valley_threshold_offset, which
        anchors detection to the actual profile minimum and remains robust
        across a wide range of illumination conditions.  Pass an explicit
        integer to override adaptive behaviour, e.g. for diagnostic purposes
        or non-standard card types.

        Empirical reference values for the Calibrite Mini under typical
        conditions:
          Baseline (diffuse ambient):  adaptive threshold ≈ 26–33
          S1 Level 2 (direct sun):     adaptive threshold ≈ 69
        The ~40-point separation between conditions confirms that an offset
        of 10 is conservative — well above baseline separator darkness and
        well below chip interior brightness under all tested conditions.
    valley_threshold_offset : int
        Offset added to the smoothed profile minimum when computing the
        adaptive threshold.  Default 10.  Increase if separators are
        consistently missed under high-contrast illumination; decrease if
        false valleys appear inside chip regions under low-contrast
        conditions.  Only used when valley_threshold is None.
    min_valley_distance : int
        Minimum pixel gap between accepted valleys.  Should be well below the
        narrowest chip dimension.  Too small → double-detections on wide
        separators; too large → adjacent chip separators merged.
    edge_margin_frac : float
        Fraction of card_dim defining the outer exclusion zone.  A band whose
        midpoint is within this fraction of either edge is discarded.
    min_band_width_frac : float
        Bands narrower than this fraction of the median inset band width are
        discarded as label/ruler strip artefacts.

    Returns
    -------
    List[float]
        Chip centre pixel offsets from the card bounding-box origin,
        in ascending order.  Returns [] if no qualifying bands remain.

    FAILURE RISKS
    -------------
    - Shallow separators under high-ambient illumination: adaptive threshold
      handles this by anchoring to the actual profile minimum, but if
      valley_threshold_offset is too small the threshold may still fall below
      the shallowest separator and miss it.  Increase valley_threshold_offset
      if fewer valleys than expected are returned under bright conditions.
    - False valleys under very uneven illumination: if chip interiors vary
      substantially in brightness across the card, some interior regions may
      dip below the adaptive threshold.  The min_band_width_frac filter
      provides partial protection by discarding anomalously narrow bands, but
      a large valley_threshold_offset increases this risk.  The default of 10
      was validated against baseline and S1 Level 2 conditions for the
      Calibrite Mini.
    - Dark chip interiors (very underexposed card): chip regions may fall
      below the adaptive threshold → false valleys inside chips → too many
      bands.  An explicit valley_threshold below the chip interior brightness
      is more reliable than adaptive mode under severe underexposure.
    - Severe tilt not corrected upstream: off-axis averaging dilutes valleys,
      making them appear brighter → missed separators.
    - Partial card crop (cc_mask too small): edge portions cut off → the
      algorithm may find too few bands or the wrong number.
    - Variable strip width (non-standard card): min_band_width_frac may
      accidentally discard real chip rows or keep the strip row.
    - If the card is very small in the image (< ~50 px per chip dimension),
      min_valley_distance may need to be reduced or profiles become too noisy.
    """
    # Step 1: smooth to suppress pixel noise that would create spurious valleys.
    smooth = uniform_filter1d(profile.astype(float), size=smooth_size)

    # Step 2: compute the effective valley threshold.
    # When valley_threshold is None, anchor adaptively to the smoothed profile
    # minimum plus a fixed offset.  This makes detection robust to illumination
    # conditions that raise the absolute brightness of chip separators — as
    # observed under S1 Level 2 (direct overhead sun), where separators sat at
    # ~59 in the smoothed profile, causing the previous hard-coded threshold of
    # 55 to miss all valleys.  Under baseline conditions the adaptive threshold
    # resolves to ~26–33; under S1 Level 2 it resolves to ~69, in both cases
    # correctly bracketing the separator brightness.
    if valley_threshold is None:
        effective_threshold = int(smooth.min()) + valley_threshold_offset
    else:
        effective_threshold = valley_threshold

    # Step 3: find dark valleys (invert profile so peaks become valleys).
    # height=-effective_threshold means the inverted profile must exceed
    # -effective_threshold, i.e. the original brightness must be below
    # effective_threshold.
    valleys, _ = find_peaks(-smooth, height=-effective_threshold,
                            distance=min_valley_distance)

    # Step 4: create separator list including the two card edges (0 and card_dim)
    # so the first and last chip regions are bounded on their outer sides.
    seps  = np.concatenate([[0], valleys, [card_dim]])

    # Step 5: build the list of (start, end) bands between consecutive separators.
    bands = [(seps[i], seps[i + 1]) for i in range(len(seps) - 1)]

    # Step 6: discard edge bands whose midpoint falls within the outer margin.
    # These arise from the card frame or from bounding-box crop slivers that
    # extend beyond the card edge slightly.
    margin = edge_margin_frac * card_dim
    inset  = [(s, e) for s, e in bands
              if margin < (s + e) / 2.0 < card_dim - margin]
    if not inset:
        return []

    # Step 7: discard bands narrower than min_band_width_frac × median width.
    # The label strip and ruler strip are narrower than chip rows; this filter
    # removes them while retaining all full-height chip rows.
    widths = np.array([e - s for s, e in inset], dtype=float)
    min_w  = min_band_width_frac * float(np.median(widths))
    max_w = max_band_width_frac * float(np.median(widths))
    qualifying = [
        (s + e) / 2.0 for s, e in inset
        if (e - s) >= min_w and (e - s) <= max_w
    ]
    return qualifying
    # Return the midpoint of each qualifying band as the chip centre offset.
    # return [(s + e) / 2.0 for s, e in inset if (e - s) >= min_w]


def _estimate_radius(chip_rows: List[float], chip_cols: List[float]) -> int:
    """
    Estimate chip circle radius as a fraction of the median centre-to-centre
    spacing.

    WHY: The sampling radius used in _sample_mean_bgr and the drawing radius
    used in cv2.circle must be small enough to stay within a single chip but
    large enough to average over a meaningful area.  Using 15% of the median
    inter-chip spacing achieves this across a wide range of image scales.

    Steps
    -----
    1. Collect all adjacent-centre spacings from both the row and column lists.
    2. Take the median spacing (robust to outliers from non-uniform grids).
    3. Multiply by 0.15 and round down to int; clamp to minimum 5 px.

    Parameters
    ----------
    chip_rows : List[float]
        Row (y-axis) chip centre offsets in ascending order.
    chip_cols : List[float]
        Column (x-axis) chip centre offsets in ascending order.

    Returns
    -------
    int
        Estimated chip radius in pixels.

    FAILURE RISKS
    -------------
    - If only one chip is detected on an axis (len == 1), no spacings are
      collected from that axis; the other axis must provide enough data.
    - If both lists have length 1, spacings is empty and the fallback 10 px
      is returned, which may be too large or too small depending on image scale.
    - Using 0.15 × spacing is conservative (chip occupies ~30% of the cell).
      For cards with very thin separators the radius could overlap the border,
      slightly contaminating the sampled color.
    """
    spacings = []
    for centers in (chip_rows, chip_cols):
        for i in range(len(centers) - 1):
            # Adjacent-centre spacing along this axis
            spacings.append(centers[i + 1] - centers[i])

    # Return at least 5 px; fall back to 10 px if no spacings were collected.
    return max(5, int(np.median(spacings) * 0.13)) if spacings else 10


def _sample_mean_bgr(
    img: np.ndarray, cx: int, cy: int, radius: int
) -> np.ndarray:
    """
    Compute the mean BGR colour in a square patch of half-side `radius`
    centred at pixel (cx, cy).

    WHY: Averaging over a patch rather than reading a single pixel reduces
    the effect of dust, highlights, or compression artefacts on any one pixel.

    Steps
    -----
    1. Clamp patch boundaries to the image extent so patches near the border
       are not out-of-bounds.
    2. Extract the sub-array and compute per-channel mean across both spatial
       dimensions (axis 0 and 1).

    Parameters
    ----------
    img : np.ndarray
        Full BGR image; must be at least 2-D.
    cx, cy : int
        Patch centre in image-space pixels.  (cx = column, cy = row).
    radius : int
        Half-side of the square sampling patch in pixels.

    Returns
    -------
    np.ndarray, shape (3,), float32
        Mean [B, G, R] values.  Returns [0, 0, 0] if the clamped patch is
        empty (e.g. cx/cy entirely outside the image).

    FAILURE RISKS
    -------------
    - If cx or cy is far outside the image (e.g. mapping error), the clamped
      patch will be empty and [0,0,0] is returned, which in Lab space is a
      very dark color — this may still get assigned to a dark reference chip
      instead of being flagged as missing.
    - A small radius (e.g. 5 px) on a low-resolution image provides very few
      pixels to average; a single dust speck can strongly bias the result.
    - Works correctly for single-channel images only if the caller converts the
      result appropriately; the function returns a 3-element vector regardless.
    """
    h, w  = img.shape[:2]

    # Clamp to image bounds to handle centres near the edge.
    patch = img[
        max(0, cy - radius): min(h, cy + radius),
        max(0, cx - radius): min(w, cx + radius),
    ]

    # Return channel-wise mean, or zeros if the patch is empty.
    return patch.mean(axis=(0, 1)).astype(np.float32) if patch.size > 0 \
        else np.zeros(3, dtype=np.float32)


def _rotate_points(
    points: List[Tuple[int, int]],
    angle_deg: float,
    cx: float,
    cy: float,
) -> List[Tuple[int, int]]:
    """
    Rotate a list of (x, y) integer pixel coordinates by angle_deg degrees
    around centre (cx, cy) using a 2-D rotation matrix.

    WHY: Chip centres are detected in a deskewed (rotated) crop coordinate
    system.  This function maps them back to the original image coordinate
    system so that masks and overlays align with the actual image content.

    Positive angle_deg rotates counter-clockwise (standard mathematical
    convention). To undo a deskew rotation of θ degrees, pass -θ here.

    Steps
    -----
    1. Early exit if angle_deg == 0 (no rotation needed).
    2. Convert degrees to radians and precompute cos/sin.
    3. For each point: translate to origin, apply 2-D rotation, translate back.
    4. Round to nearest integer pixel.

    Parameters
    ----------
    points : list of (x, y) int tuples
    angle_deg : float
        Rotation angle in degrees.
    cx, cy : float
        Centre of rotation in image space (e.g. the card's centroid).

    Returns
    -------
    List of (x, y) integer tuples.

    FAILURE RISKS
    -------------
    - Rounding to integer pixels introduces up to 0.5 px error per point.
      For small chips this is negligible, but at very low resolutions it can
      cause the sampling patch to partially overlap the chip border.
    - If cx/cy is far from the card centre (e.g. minAreaRect centroid is
      wrong due to mask noise), all chips will be offset in the output image.
    - Passing +tilt_deg instead of -tilt_deg (or vice versa) will rotate
      chips in the wrong direction, misplacing all centres.
    """
    if angle_deg == 0.0:
        return points

    # Precompute rotation matrix coefficients
    rad   = np.deg2rad(angle_deg)
    cos_a = np.cos(rad)
    sin_a = np.sin(rad)

    rotated = []
    for x, y in points:
        # Translate to rotation origin
        dx = x - cx
        dy = y - cy
        # Apply 2-D rotation
        rx = cos_a * dx - sin_a * dy + cx
        ry = sin_a * dx + cos_a * dy + cy
        rotated.append((int(round(rx)), int(round(ry))))
    return rotated


def _draw_overlay(
    img: np.ndarray,
    chip_centers: List[Tuple[int, int]],
    det_to_can: np.ndarray,
    radius: int,
) -> np.ndarray:
    """
    Draw a diagnostic overlay on a copy of img: a filled red circle at each
    detected chip centre with its canonical chip name annotated in cyan above.

    WHY: Provides a visual QC output so the analyst can verify that all 24
    chips were correctly detected and assigned without reading numeric arrays.

    Steps
    -----
    1. Copy the image so the original is not modified.
    2. For each detected chip centre:
       a. Skip if the centre is outside the image (bounds check).
       b. Look up the canonical chip name via det_to_can.
       c. Draw a filled red circle of the estimated chip radius.
       d. Put the truncated chip name in cyan above the circle.

    Parameters
    ----------
    img : np.ndarray
        Full BGR image (not modified in place).
    chip_centers : list of (cx, cy)
        Detected chip centres in image space, indexed by detected order.
    det_to_can : np.ndarray, shape (n_chips,), int
        Mapping from detected chip index → canonical reference index.
    radius : int
        Chip circle radius in pixels.

    Returns
    -------
    np.ndarray
        BGR image with overlay drawn.

    FAILURE RISKS
    -------------
    - Font scale 0.4 and thickness 1 are hard-coded for ~2000–3000 px images.
      At very high resolution labels will be tiny; at very low resolution they
      will overlap each other or fall outside the image.
    - Text origin (cx - 30, cy - radius - 4) can be negative for chips near
      the top edge.  cv2.putText silently clips these, so no crash, but the
      label will not be visible.
    - CHIP_NAMES[can_i][:8] truncates all names to 8 characters for compactness;
      some names (e.g. "bluish green") become harder to read.
    - If det_to_can contains an out-of-range index, CHIP_NAMES lookup will
      raise an IndexError.
    """
    vis        = img.copy()
    font       = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4
    thickness  = 1
    text_color = (0, 255, 255)   # cyan (BGR)
    dot_color  = (0, 0, 255)     # red  (BGR)

    for det_i, (cx, cy) in enumerate(chip_centers):
        h, w = vis.shape[:2]
        # Skip chip centres that fall outside the image boundary
        if not (0 <= cy < h and 0 <= cx < w):
            continue
        can_i = int(det_to_can[det_i])
        # Truncate name to 8 characters to keep the label compact
        name  = CHIP_NAMES[can_i][:8]
        # Filled circle at the chip centre
        cv2.circle(vis, (cx, cy), radius, dot_color, -1)
        # Chip name text positioned above the circle
        cv2.putText(
            vis, name,
            (cx - 30, cy - radius - 4),
            font, font_scale, text_color, thickness,
            cv2.LINE_AA,
        )

    return vis


# ---------------------------------------------------------------------------
# Public drawing helper
# ---------------------------------------------------------------------------

def draw_chip_overlay(
    img        : np.ndarray,
    chip_data  : dict,
    color      : tuple = (0, 255, 255),
) -> np.ndarray:
    """
    Draw chip detection results onto an existing image in place.

    Annotates each detected chip as an outlined (unfilled) circle with its
    canonical chip name printed above it. Designed to be called on an
    already-annotated QC overlay (e.g. from label_objects_rowwise) so that
    chip locations are visible alongside fruit masks without a separate
    overlay image.

    Parameters
    ----------
    img : np.ndarray
        BGR image to annotate IN PLACE. Must be the same spatial dimensions
        as the image used to call create_chip_mask. Pass img.copy() first
        if the original must be preserved.
    chip_data : dict
        Dict returned by create_chip_mask(..., return_chip_data=True) with
        keys 'chip_centers', 'det_to_can', 'radius'. If chip detection
        failed, chip_data will contain empty values and this function
        returns img unchanged.
    color : tuple
        BGR color for the circle outline and text. Default (0, 255, 255)
        cyan, which is visible against the white backdrop and does not
        clash with the red (fruit) or magenta (CC) annotations already
        present on the QC overlay.

    Returns
    -------
    np.ndarray
        The same img array, annotated in place. The return value is
        provided for convenience; the original array is modified.

    Notes
    -----
    Circle thickness is scaled to the image height using the same formula
    used for CC and SM mask contours in process_images.py so all overlay
    annotations are visually consistent at different image resolutions.
    Font scale is also matched to the existing QC overlay convention.
    """
    chip_centers = chip_data.get("chip_centers", [])
    det_to_can   = chip_data.get("det_to_can",   np.empty(0, dtype=int))
    radius       = chip_data.get("radius",        0)

    # Nothing to draw if detection produced no centers
    if len(chip_centers) == 0 or radius == 0:
        return img

    h, w     = img.shape[:2]
    font     = cv2.FONT_HERSHEY_SIMPLEX

    # Scale thickness and font to match QC overlay convention from process_images.py:
    #   font_scale = clip(img_h / 1400, 0.45, 1.6)
    #   thickness  = clip(img_h / 900,  1,    3)
    font_scale = float(np.clip(h / 1400.0, 0.45, 1.6))
    thickness  = int(np.clip(h / 900.0, 1, 3))

    for det_i, (cx, cy) in enumerate(chip_centers):
        # Skip centers outside the image boundary
        if not (0 <= cy < h and 0 <= cx < w):
            continue

        can_i = int(det_to_can[det_i])

        # Outlined (unfilled) circle — thickness > 0, not -1
        cv2.circle(img, (cx, cy), radius, color, thickness, cv2.LINE_AA)

        # Chip name truncated to 8 characters, positioned above the circle.
        # cv2.putText clips silently if the text origin is outside the frame.
        name = CHIP_NAMES[can_i][:8]
        tx   = cx - 28
        ty   = max(cy - radius - 4, 12)
        # Black outline for legibility on any background
        cv2.putText(img, name, (tx, ty), font, font_scale * 0.55,
                    (0, 0, 0), thickness + 1, cv2.LINE_AA)
        cv2.putText(img, name, (tx, ty), font, font_scale * 0.55,
                    color, thickness, cv2.LINE_AA)

    return img


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def create_chip_mask(
    img: np.ndarray,
    cc_mask: np.ndarray,
    reference_rgb: np.ndarray = REFERENCE_RGB,
    n_cols: int = 4,
    n_rows: int = 6,
    valley_threshold: Optional[int] = None,
    valley_threshold_offset: int = 10,
    min_valley_distance: int = 50,
    edge_margin_frac: float = 0.06,
    min_band_width_frac: float = 0.60,
    max_band_width_frac=1.75,
    min_valid_chip_fraction: float = 0.75,
    max_acceptable_delta_e: float = 60.0,
    return_overlay: bool = False,
    return_chip_data: bool = False,
) -> np.ndarray | Tuple[np.ndarray, np.ndarray] | Tuple[np.ndarray, dict]:
    """
    Detect color calibration card chips and return a labelled mask in which
    each chip circle carries a label corresponding to its canonical chip
    index, regardless of card orientation in the image.

    Chip positions are found from the brightness profile of the card interior,
    making detection robust to thick borders, label strips, and ruler strips.
    Each detected chip is matched to its reference color via linear assignment
    in CIE Lab space (scipy.optimize.linear_sum_assignment), which resolves
    card orientation automatically without any user-supplied positional
    parameters.

    Parameters
    ----------
    img : np.ndarray
        Full BGR image.
    cc_mask : np.ndarray
        Binary mask (0 / 255) of the full card region as produced by
        create_masks(). Must cover the entire card including border,
        label strip, and ruler strip.
    reference_rgb : np.ndarray, shape (N, 3), float32
        Reference RGB values (0–255) for each chip in canonical row-major
        order. Defaults to REFERENCE_RGB for the ColorChecker Classic Mini.
        Pass a different array to support other card types.
    n_cols : int
        Number of chip columns on the card.
    n_rows : int
        Number of chip rows on the card.
    valley_threshold : int or None
        Passed directly to _find_chip_centers_1d. When None (default), the
        threshold is computed adaptively as int(smooth.min()) +
        valley_threshold_offset for each brightness profile independently.
        Pass an explicit integer to override adaptive behaviour. See
        _find_chip_centers_1d for full documentation and empirical reference
        values.
    valley_threshold_offset : int
        Offset added to the smoothed profile minimum when computing the
        adaptive threshold. Default 10. Only used when valley_threshold is
        None. See _find_chip_centers_1d for guidance on tuning this value.
    min_valley_distance : int
        Minimum pixel distance between consecutive valleys. Should be safely
        below the narrowest chip dimension in pixels.
    edge_margin_frac : float
        Card-edge exclusion zone as a fraction of card dimension, applied to
        both edges on each axis.
    min_band_width_frac : float
        Bands narrower than this fraction of the median inset band width are
        discarded as label-strip or ruler-strip artefacts.
    min_valid_chip_fraction : float
        Minimum fraction of detected chip centres that must fall inside
        cc_mask for the result to be accepted.
    max_acceptable_delta_e : float
        Upper bound on mean CIE76 ΔE across all matched chips. Detections
        where the mean match error exceeds this threshold are rejected and
        an empty mask is returned.
    return_overlay : bool
        If True, also return a BGR overlay image with each chip marked as a
        filled red circle and its canonical name annotated in cyan above it.
        Default False.
    return_chip_data : bool
        If True, also return a dict containing the chip detection results
        needed to draw chip annotations onto an external image (e.g. the
        pipeline QC overlay). The dict has keys:
            'chip_centers' : list of (cx, cy) int tuples in image space
            'det_to_can'   : np.ndarray, shape (n_chips,), int — mapping
                             from detected chip index to canonical index
            'radius'       : int — chip circle radius in pixels
        If detection fails, the dict is {'chip_centers': [], 'det_to_can':
        np.empty(0, int), 'radius': 0} so callers can always unpack it
        safely without a None check. Default False.

        return_overlay and return_chip_data are independent and can both be
        True simultaneously, in which case the return order is:
            chip_mask, overlay, chip_data

    Returns
    -------
    chip_mask : np.ndarray
        uint8 labelled mask, same spatial size as img. Each chip is a filled
        circle whose pixel value equals CHIP_LABELS[canonical_index], where
        canonical_index is the chip's position in reference_rgb. Background
        is 0. Returns a zero mask if any validation step fails.
    overlay : np.ndarray, only present when return_overlay=True
        BGR copy of img with chip circles and name labels drawn. Returned as
        the second element of a tuple: ``mask, overlay = create_chip_mask(...,
        return_overlay=True)``. If detection fails, overlay is a plain copy
        of img with no annotations.
    chip_data : dict, only present when return_chip_data=True
        Dict with keys 'chip_centers', 'det_to_can', 'radius'. Use with
        draw_chip_overlay() to annotate an external image (e.g. the pipeline
        QC overlay) without re-running chip detection. If detection fails,
        chip_data contains empty/zero values so callers need no None check.
        When both return_overlay and return_chip_data are True, the return
        order is (chip_mask, overlay, chip_data).

    Notes
    -----
    CHIP_LABELS = linspace(240, 10, N), so label 240 = canonical chip 0
    (dark skin) and label 10 = canonical chip 23 (black). These values are
    stable across images regardless of how the card was oriented at capture.
    """
    # ------------------------------------------------------------------
    # Initialisation: allocate an empty (all-zero) mask at the full image
    # size and define _fail() as the unified early-exit path.
    # _fail() returns either the empty mask alone or a (mask, plain-copy)
    # tuple so the return type is always consistent with return_overlay.
    # ------------------------------------------------------------------
    h, w  = img.shape[:2]
    empty = np.zeros((h, w), dtype=np.uint8)

    # Empty chip_data returned on any failure path so callers need no None check.
    _empty_chip_data: dict = {
        "chip_centers": [],
        "det_to_can":   np.empty(0, dtype=int),
        "radius":       0,
    }

    def _fail():
        # Returns an all-zero mask, plus an un-annotated copy of img and/or
        # empty chip_data dict depending on which return flags are set.
        # Using a list then unpacking keeps the logic clean for all four
        # combinations of (return_overlay, return_chip_data).
        result = [empty]
        if return_overlay:
            result.append(img.copy())
        if return_chip_data:
            result.append(_empty_chip_data)
        return tuple(result) if len(result) > 1 else result[0]

    # Guard: cc_mask must exist and contain at least one non-zero pixel.
    # FAILURE RISK: if create_masks() did not find the card, cc_mask will be
    # all zeros here and the function returns an empty mask immediately.
    if cc_mask is None or np.max(cc_mask) == 0:
        return _fail()

    # Guard: reference_rgb must have exactly n_rows × n_cols entries.
    # FAILURE RISK: passing reference_rgb for a different card model (wrong
    # chip count) causes an immediate failure rather than a silent mismatch.
    n_chips = n_rows * n_cols
    if len(reference_rgb) != n_chips:
        return _fail()

    # ------------------------------------------------------------------
    # Step 1: card bounding box and rotation angle from cc_mask
    #
    # WHY: The card may be tilted in the image.  Profiling a tilted card with
    # axis-aligned row/column means would smear brightness across multiple
    # chips per row, obscuring the dark valley separators.  We measure the
    # tilt angle here so we can deskew the crop before profiling.
    #
    # HOW:
    #   a) Binarise cc_mask and find its external contour.
    #   b) Fit a minimum-area rotated rectangle (minAreaRect) to the contour.
    #      minAreaRect always puts the shorter side as size[0] (width) and
    #      the longer side as size[1] (height), and reports an angle in
    #      (-90, 0].  The angle is the orientation of the "width" side
    #      relative to the horizontal x-axis.
    #   c) Derive tilt_deg — the deviation of the long axis from vertical:
    #        size[0] >= size[1]  → width is the long side;
    #                               long axis from horiz = mar_angle,
    #                               tilt from vertical   = mar_angle + 90
    #        size[0] <  size[1]  → height is the long side (normal portrait);
    #                               long axis from horiz = mar_angle + 90,
    #                               tilt from vertical   = mar_angle
    #   d) Wrap tilt_deg to (-45, 45] to prevent large spurious rotations
    #      at the 0°/-90° boundary (e.g. a perfectly upright card reports
    #      mar_angle = -90, giving tilt_deg = 0 after wrapping).
    #
    # FAILURE RISKS:
    # - If cc_mask has multiple disjoint regions (noise blobs), the largest
    #   contour is taken; smaller noise blobs are ignored.
    # - If the card bounding box is smaller than 20×20 px the result is too
    #   small to detect chips reliably → empty mask returned.
    # - Heavy cc_mask dilation/erosion artifacts can skew minAreaRect and
    #   produce a wrong tilt angle, causing the deskewed profiles to still
    #   be tilted.
    # ------------------------------------------------------------------
    cc_bin      = (cc_mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(cc_bin, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return _fail()

    # Take the largest contour as the card outline
    card_cnt       = max(contours, key=cv2.contourArea)

    # Axis-aligned bounding box: used for the initial crop region
    x0, y0, w0, h0 = cv2.boundingRect(card_cnt)
    if w0 < 20 or h0 < 20:
        return _fail()

    # Minimum-area rotated rectangle: provides tilt angle and centroid
    mar_center, mar_size, mar_angle = cv2.minAreaRect(card_cnt)

    # Determine tilt of the long axis from vertical
    if mar_size[0] >= mar_size[1]:
        # Width side is longer → long axis is at mar_angle from horizontal
        tilt_deg = mar_angle + 90.0
    else:
        # Height side is longer (portrait orientation) → long axis is at
        # mar_angle + 90 from horizontal, so tilt from vertical = mar_angle
        tilt_deg = mar_angle

    # Wrap tilt_deg to (-45, 45] to keep the small-tilt assumption valid
    # and avoid large spurious counter-rotations from edge cases at 0°/-90°
    while tilt_deg > 45.0:
        tilt_deg -= 90.0
    while tilt_deg <= -45.0:
        tilt_deg += 90.0

    # Card centroid in image space — centre of rotation when mapping chip
    # centres back from deskewed-crop coordinates to full-image coordinates
    card_cx = mar_center[0]
    card_cy = mar_center[1]

    # Convert to grayscale for brightness profiling
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Crop the axis-aligned bounding box of the card
    card_crop_raw = gray[y0: y0 + h0, x0: x0 + w0]
    crop_cx, crop_cy = w0 / 2.0, h0 / 2.0

    # Deskew the crop by rotating by -tilt_deg around its centre.
    # BORDER_REPLICATE fills any new edge pixels with the nearest border
    # pixel value rather than black, which prevents artificial dark valleys
    # at the rotated corners from corrupting the brightness profiles.
    if abs(tilt_deg) > 0.1:
        M_deskew  = cv2.getRotationMatrix2D(
            (crop_cx, crop_cy), tilt_deg, 1.0
        )
        card_gray = cv2.warpAffine(
            card_crop_raw, M_deskew, (w0, h0),
            borderMode=cv2.BORDER_REPLICATE,
        )
    else:
        # Tilt is negligible — use the raw crop directly to avoid an
        # unnecessary (and lossless-but-slow) warpAffine call
        card_gray = card_crop_raw

    # ------------------------------------------------------------------
    # Step 2: detect chip row and column centres from brightness profiles
    #
    # WHY: Mean brightness collapsed across one axis produces a 1-D profile
    # where each chip appears as a bright band and each separator (frame line,
    # inter-chip gap, label strip, ruler strip) appears as a dark valley.
    # _find_chip_centers_1d extracts the midpoint of each qualifying band.
    #
    # card_gray.mean(axis=1) → per-row mean → shape (h0,) → detects ROW centres
    # card_gray.mean(axis=0) → per-column mean → shape (w0,) → detects COL centres
    #
    # FAILURE RISKS:
    # - Insufficient contrast between chips and separators → valleys not found
    #   → too few or zero centres → empty mask returned.
    # - Wrong n_rows / n_cols parameters → chip count check in Step 4 fails.
    # - Card only partially visible (e.g. cropped at image border) → some
    #   chip bands not present in the profile → wrong centre count.
    # ------------------------------------------------------------------
    chip_rows = _find_chip_centers_1d(
        card_gray.mean(axis=1), h0,
        valley_threshold=valley_threshold,
        valley_threshold_offset=valley_threshold_offset,
        min_valley_distance=min_valley_distance,
        edge_margin_frac=edge_margin_frac,
        min_band_width_frac=min_band_width_frac,
        max_band_width_frac=max_band_width_frac,
    )
    chip_cols = _find_chip_centers_1d(
        card_gray.mean(axis=0), w0,
        valley_threshold=valley_threshold,
        valley_threshold_offset=valley_threshold_offset,
        min_valley_distance=min_valley_distance,
        edge_margin_frac=edge_margin_frac,
        min_band_width_frac=min_band_width_frac,
        max_band_width_frac=max_band_width_frac,
    )
    # print(f"[CHIP DEBUG] crop: w0={w0}, h0={h0}")
    # print(f"[CHIP DEBUG] chip_rows ({len(chip_rows)}): {[round(r/h0, 3) for r in chip_rows]}")
    # print(f"[CHIP DEBUG] chip_cols ({len(chip_cols)}): {[round(c/w0, 3) for c in chip_cols]}")

    if len(chip_rows) == 0 or len(chip_cols) == 0:
        return _fail()

    # ------------------------------------------------------------------
    # Step 3: chip radius from actual detected spacing
    #
    # WHY: The radius is used both for color sampling (Step 6) and for
    # painting chip circles on the output mask (Step 9).  Deriving it from
    # the detected inter-chip spacing makes it scale-invariant — the same
    # code works for cards occupying very different fractions of the image.
    # ------------------------------------------------------------------
    radius = _estimate_radius(chip_rows, chip_cols)

    # ------------------------------------------------------------------
    # Step 4: build chip centres and map from deskewed-crop space to image
    #
    # WHY: chip_rows and chip_cols are offsets within the deskewed crop,
    # not the full image.  Two transformations are needed:
    #   a) Add bounding-box origin (x0, y0) to get axis-aligned image coords.
    #   b) Rotate by +tilt_deg (undo the deskew) around the card centroid
    #      (mar_center) to get the correct position on the tilted card.
    #
    # The cross-product of chip_rows × chip_cols gives all n_rows × n_cols
    # chip centres.  Row index iterates in the outer loop so the flat list
    # is in row-major order matching reference_rgb.
    #
    # FAILURE RISK: if len(chip_rows) × len(chip_cols) ≠ n_chips (e.g. a
    # spurious extra row or missing column was detected), the count check
    # immediately returns an empty mask rather than silently producing a
    # misaligned assignment.
    # ------------------------------------------------------------------
    chip_centers_deskewed = [
        (int(x0 + cx), int(y0 + ry))
        for ry in chip_rows
        for cx in chip_cols
    ]

    # Validate that the number of detected chip centres matches expectations
    if len(chip_centers_deskewed) != n_chips:
        return _fail()

    # Rotate chip centres back to full-image coordinates by undoing the deskew.
    # Note the sign convention: the deskew applied rotation +tilt_deg to the
    # crop, so the inverse (mapping back to image space) applies -tilt_deg.
    chip_centers = _rotate_points(
        chip_centers_deskewed, tilt_deg, card_cx, card_cy
    )
    # print(f"[CHIP DEBUG] x0={x0}, y0={y0}")
    # print(f"[CHIP DEBUG] mar_center={mar_center}")
    # print(f"[CHIP DEBUG] tilt_deg={tilt_deg:.3f}")
    # print(f"[CHIP DEBUG] chip_centers[:4]={chip_centers[:4]}")

    # ------------------------------------------------------------------
    # Step 5: validate chip centres lie inside cc_mask
    #
    # WHY: If the mapping went wrong (e.g. wrong tilt or wrong bounding box),
    # chip centres will land outside the masked card region.  Requiring that
    # at least min_valid_chip_fraction of them fall inside cc_mask provides a
    # sanity check before expensive color sampling and assignment.
    #
    # FAILURE RISK: min_valid_chip_fraction = 0.75 means up to 6 of 24 chips
    # can be out-of-mask before the result is rejected.  If the cc_mask is
    # slightly smaller than the true card (tight crop), valid chips near the
    # edge may be counted as invalid, triggering a false failure.
    # ------------------------------------------------------------------
    valid_count = sum(
        1 for cx, cy in chip_centers
        if 0 <= cy < h and 0 <= cx < w and cc_bin[cy, cx] > 0
    )
    if valid_count < min_valid_chip_fraction * n_chips:
        return _fail()

    # ------------------------------------------------------------------
    # Step 6: extract mean BGR at each chip centre, convert to CIE Lab
    #
    # WHY: Color comparison is done in CIE Lab space because Euclidean
    # distance (ΔE76) there is approximately perceptually uniform, giving
    # more reliable chip-to-reference matching than raw BGR or RGB.
    #
    # HOW:
    #   a) Sample a square BGR patch of radius `radius` at each centre and
    #      average to a single BGR triple.
    #   b) Reverse the channel order (BGR → RGB) for the colorspace
    #      conversion, which expects RGB input.
    #   c) Convert both detected and reference colors to Lab in a single
    #      batch call.
    #
    # FAILURE RISK: if a chip centre is at the image edge, the clamped patch
    # may be very small or partially outside, giving a biased color sample.
    # The subsequent assignment will still attempt to assign that chip, but
    # the mean ΔE check (Step 7) may catch gross errors.
    # ------------------------------------------------------------------
    detected_bgr = np.array(
        [_sample_mean_bgr(img, cx, cy, radius) for cx, cy in chip_centers],
        dtype=np.float32,
    )

    # BGR → RGB (reverse last axis) before converting to Lab
    detected_rgb  = detected_bgr[:, ::-1]
    detected_lab  = _rgb_to_lab_batch(detected_rgb)
    reference_lab = _rgb_to_lab_batch(reference_rgb.astype(np.float32))

    # ------------------------------------------------------------------
    # Step 7: linear assignment in Lab space (Hungarian algorithm)
    #
    # WHY: The card may be in any of four orientations (0°, 90°, 180°, 270°).
    # Rather than hard-coding an orientation parameter, we build a cost matrix
    # of CIE76 ΔE between every detected chip and every reference chip, then
    # find the minimum-cost bijective matching.  This automatically identifies
    # which detected chip corresponds to which canonical reference, resolving
    # orientation without any manual input.
    #
    # HOW:
    #   diff[i,j,:] = detected_lab[i] - reference_lab[j]   (broadcast)
    #   costs[i,j]  = ||diff[i,j,:]||₂  (Euclidean = ΔE76)
    #   linear_sum_assignment minimises sum of costs[row_ind[k], col_ind[k]]
    #   → row_ind[k] = detected index, col_ind[k] = canonical index
    #
    # Validation: if mean ΔE > max_acceptable_delta_e the overall match is
    # poor (wrong card type, severe color cast, or failed detection), so an
    # empty mask is returned rather than propagating bad assignments.
    #
    # FAILURE RISKS:
    # - Severe global illumination color cast can shift all chips uniformly,
    #   inflating ΔE and potentially exceeding max_acceptable_delta_e.
    # - Very similar chips (adjacent neutral grays) may be swapped by the
    #   assignment under uneven illumination; Step 8 corrects this for the
    #   gray ramp specifically.
    # - Cost matrix is n_chips × n_chips (24×24), so the Hungarian algorithm
    #   is fast (O(n³)); no performance concern here.
    # - If detected_lab contains [0,0,0] entries (empty patches), those
    #   chips will be matched to the darkest reference chip, which may or
    #   may not be correct.
    # ------------------------------------------------------------------

    # Build cost matrix: shape (n_chips, n_chips), where costs[i,j] = ΔE
    # between detected chip i and reference chip j
    diff  = detected_lab[:, np.newaxis, :] - reference_lab[np.newaxis, :, :]
    costs = np.sqrt((diff ** 2).sum(axis=2))

    # Find the minimum-cost one-to-one assignment
    row_ind, col_ind = linear_sum_assignment(costs)

    # Compute mean ΔE across all matched pairs and reject if too high
    mean_delta_e = costs[row_ind, col_ind].mean()
    if mean_delta_e > max_acceptable_delta_e:
        return _fail()

    # ------------------------------------------------------------------
    # Step 8: correct gray ramp assignment by luminance rank
    #
    # WHY: Canonical chips 18–23 (white → black) are spectrally identical
    # except for luminance — they differ only in how light or dark they are.
    # Under uneven illumination or exposure variation the global Lab
    # assignment can swap adjacent ramp chips because their ΔE values are
    # similar and small absolute differences can push the cost-minimum in
    # the wrong direction.
    #
    # CORRECTION: luminance rank is the only reliable discriminator for this
    # monotone series.  Regardless of absolute exposure, the relative order
    # white > neutral8 > neutral6.5 > neutral5 > neutral3.5 > black must
    # hold.  We therefore:
    #   a) Find which detected chip indices were assigned to canonical 18–23.
    #   b) Sort them by measured CIE L* (descending).
    #   c) Reassign: rank 0 (brightest) → canonical 18 (white), ...,
    #      rank 5 (darkest) → canonical 23 (black).
    #
    # This correction is applied in-place on det_to_can after the global
    # assignment is complete; it does not affect any of the 18 chromatic chips.
    #
    # FAILURE RISKS:
    # - If the global assignment placed a chromatic chip into the gray ramp
    #   slot (very unusual; would require mean ΔE near max_acceptable_delta_e),
    #   this correction would still re-sort those slots by L* and reassign
    #   them to canonical 18–23, which may make things worse.
    # - If two gray ramp chips have identical measured L* (e.g. identical
    #   exposure on a flat-lit card), sorted() is stable so their relative
    #   order is preserved — the assignment may still be wrong but won't crash.
    # ------------------------------------------------------------------

    # Initialise the detected→canonical mapping array from linear_sum_assignment
    det_to_can = np.empty(n_chips, dtype=int)
    for di, ci in zip(row_ind, col_ind):
        det_to_can[di] = ci

    # Canonical indices for the neutral gray ramp (white through black)
    gray_ramp_canonical = list(range(18, 24))

    # Find which detected chip was initially assigned to each gray ramp slot
    ramp_det_indices = [
        int(np.where(det_to_can == ci)[0][0])
        for ci in gray_ramp_canonical
    ]

    # Extract the measured CIE L* value for each ramp chip
    ramp_L_values = detected_lab[ramp_det_indices, 0]

    # Sort ramp chips by descending L* so rank 0 = brightest (white = 18)
    sorted_ramp = sorted(zip(ramp_L_values, ramp_det_indices), reverse=True)
    for rank, (_, di) in enumerate(sorted_ramp):
        det_to_can[di] = 18 + rank   # reassign: 18=white, 23=black

    # ------------------------------------------------------------------
    # Step 9: paint chip circles onto the output mask
    #
    # WHY: The final product is a uint8 mask where each chip circle is filled
    # with a stable label value (CHIP_LABELS[canonical_index]) so downstream
    # code can identify any chip by its pixel value without needing to know
    # card orientation.  Background stays at 0.
    #
    # HOW: For each detected chip centre, fill a circle of `radius` pixels
    # with the label value corresponding to its assigned canonical index.
    # Centres outside the image bounds are silently skipped (same guard as
    # in _draw_overlay).
    #
    # FAILURE RISKS:
    # - If radius is larger than the chip, adjacent chip circles will overlap
    #   and the later-drawn chip will overwrite earlier pixels.  _estimate_radius
    #   uses 15% of spacing which is conservative, so this should not occur
    #   unless the card is very small in the image.
    # - If a chip centre is just outside the image boundary (0 ≤ cx < w etc.
    #   check fails), that chip will not appear in the mask.  Downstream code
    #   that expects all 24 labels present will need to handle missing chips.
    # ------------------------------------------------------------------
    chip_mask_out = np.zeros((h, w), dtype=np.uint8)
    for det_i, (cx, cy) in enumerate(chip_centers):
        if 0 <= cy < h and 0 <= cx < w:
            label = int(CHIP_LABELS[det_to_can[det_i]])
            cv2.circle(chip_mask_out, (cx, cy), radius, label, -1)

    # Return mask, plus overlay and/or chip_data as requested.
    # Order when both flags are True: (chip_mask, overlay, chip_data).
    result = [chip_mask_out]
    if return_overlay:
        result.append(_draw_overlay(img, chip_centers, det_to_can, radius))
    if return_chip_data:
        result.append({
            "chip_centers": chip_centers,
            "det_to_can":   det_to_can,
            "radius":       radius,
        })
    return tuple(result) if len(result) > 1 else result[0]