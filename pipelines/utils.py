# helpers/utils.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np

PathLike = Union[str, os.PathLike]
INCH_TO_MM = 25.4

# --------------------------------------------------------------------
# enforce_https – Ensures a URL uses HTTPS by replacing an http:// 
# prefix with https:// if present
# --------------------------------------------------------------------

def enforce_https(url: Optional[str], *, allow_http_localhost: bool = True) -> Optional[str]:
    """
    Upgrade an http:// URL to https://.

    Args:
        url: Input URL (or None).
        allow_http_localhost: If True, do not force https for localhost/127.0.0.1
        (useful in local dev where TLS isn't configured).

    Returns:
        Updated URL string (or None if input was None).
    """
    if not url:
        return url

    if allow_http_localhost:
        if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
            return url
    
    if url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url

# --------------------------------------------------------------------
# Read an image from file and return img, path, and img_filename
# --------------------------------------------------------------------

def readimage(filename: PathLike, *, auto_rotate: bool = True) -> Tuple[np.ndarray, str]:
    """
    Read an image from disk.

    Notes:
        - Uses OpenCV (BGR format)
        - Optionally rotates portrait images 90 degrees clockwise

    Args:
        filename: Path to image file.
        auto_rotate: If True, rotate 90 degrees clockwise when height > width.

    Returns:
        (img_bgr, img_filename)

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError: if OpenCV cannot decode/read the image.
    """
    path = Path(filename)
    if not path.exists():
        raise FileNotFoundError(f"Image path does not exist: {path}")
    
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Invalid image path: {path}")

    if auto_rotate:
        h, w = img.shape[:2]
        if w < h:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

    return img, path


# --------------------------------------------------------------------
# Apply binary mask to original image
# --------------------------------------------------------------------
def apply_mask(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    Apply a binary-ish mask to an image (zero out pixels where mask is False/0).

    Args:
        img: Input image (H x W x C) or (H x W)
        mask: Mask (H x W) where non-zero means "keep".

    Returns:
        Masked image (same shape as img).

    Raises:
        ValueError: if shapes are incompatible.
    """
    if img.ndim not in (2,3):
        raise ValueError(f"img must be 2D or 3D, got shape={img.shape}")
    if mask.ndim != 2:
        raise ValueError(f"mask must be 2D (H x W), got shape={mask.shape}")
    if img.shape[0] != mask.shape[0] or img.shape[1] != mask.shape[1]:
        raise ValueError(f"mask shape {mask.shape} does not match image shape {img.shape[:2]}")

    keep = mask > 0
    out = img.copy()

    if img.ndim == 2:
        out[~keep] = 0
    else:
        out[~keep, :] = 0
        
    return out

# --------------------------------------------------------------------
# Ensure mask is uint8 0/255
# --------------------------------------------------------------------
def ensure_u8_mask(mask: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """
    Normalize a "binary-ish" mask into uint8 0/255.

    Args:
        mask: None, bool mask, 0/1 mask, or 0/255 mask.

    Returns:
        uint8 mask with values in {0, 255}, or None if input is None.
    """
    if mask is None:
        return None
        
    m = (mask > 0).astype(np.uint8) * 255

    return m 








