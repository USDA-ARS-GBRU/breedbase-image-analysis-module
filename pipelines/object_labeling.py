# helpers/object_labeling.py
import cv2
import numpy as np
import matplotlib.pyplot as plt

# --------------------------------------------------------------------
# Detects connected objects in a binary image, groups them into rows
# based on vertical proximity, orders them left-to-right within each
# row, assigns sequential labels (1..N), and returns both a labeled mask
# and an annotated visualization image.
#
# Label placement: draws the index just OUTSIDE each object's bounding box
# (so it does not occlude the object outline/overlay drawn downstream).
# --------------------------------------------------------------------
def label_objects_rowwise(binary, orig_img, output_mask_path=None, display_result=False):
     """
    Args:
        binary: binary-ish mask (uint8/bool). Foreground > 0.
        orig_img: BGR image used as the overlay canvas.
        output_mask_path: optional file path to save the labeled mask.
        display_result: if True, show overlay via matplotlib.

    Returns:
        labeled_mask: uint16 mask with labels 0=background, 1..N objects
        overlay_img: BGR image with readable label indices drawn outside each bbox
    """
    
    overlay = orig_img.copy()
    
    # Ensure binary is uint8 0/255 for OpenCV contour ops
    bin_u8 = binary.astype(np.uint8)
    if bin_u8.max() <= 1:
        bin_u8 = (bin_u8 > 0).astype(np.uint8) * 255
    else:
        bin_u8 = (bin_u8 > 0).astype(np.uint8) * 255
        
    # Find contours
    contours, _ = cv2.findContours(bin_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("No objects found in the binary image.")

    # Object metadata
    objects = []
    heights = []
    widths = []
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area <= 0:
            continue

        M = cv2.moments(cnt)
        if M["m00"] <= 0:
            continue

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        x, y, w, h = cv2.boundingRect(cnt)

        heights.append(h)
        widths.append(w)
        objects.append({"centroid": (cx, cy), "contour": cnt, "bbox": (x, y, w, h)})

    if not objects or not heights:
        raise ValueError("Unable to determine object sizes from contours.")

    # Row grouping threshold
    med_h = float(np.median(heights))
    row_thresh = max(5, int(med_h * 0.75))
    
    # Group objects into rows by proximity in the y-direction
    y_coords = np.array([obj["centroid"][1] for obj in objects])
    sorted_indices = np.argsort(y_coords)
    sorted_objects = [objects[i] for i in sorted_indices]

    rows = []
    current_row = [sorted_objects[0]]
    current_y = sorted_objects[0]["centroid"][1]

    for obj in sorted_objects[1:]:
        if abs(obj["centroid"][1] - current_y) < row_thresh:
            current_row.append(obj)
        else:
            rows.append(current_row)
            current_row = [obj]
            current_y = obj["centroid"][1]
    rows.append(current_row)  # Add the last row

    # Sort each row from left to right, then flatten
    rows = [sorted(row, key=lambda o: o["centroid"][0]) for row in rows]
    ordered = [obj for row in rows for obj in row]

    # Create labeled mask (uint16 in case there are more than 255 objects)
    labeled_mask = np.zeros(bin_u8.shape, dtype=np.uint16)

    # Image-scale-aware font sizing (robust across resolutions)
    img_h, img_w = overlay.shape[:2]
    font_scale = float(np.clip(img_h / 1400.0, 0.45, 1.6))
    thickness = int(np.clip(img_h / 900.0, 1, 3))

    def _label_origin_outside_bbox(bbox, img_shape):
        """
        Choose a label origin just outside the object's bbox, preferring top-left.
        Falls back to right/bottom if off-canvas, then clamps to image bounds.
        """
        x, y, w, h = bbox
        H, W = img_shape[:2]

        # Padding scales with object size, clamped for robustness
        pad = int(np.clip(0.25 * min(w, h), 6, 30))

        # Prefer top-left outside bbox
        tx, ty = x - pad, y - pad

        # If off-canvas horizontally, move to right of bbox
        if tx < 0:
            tx = x + w + pad
        # If still off-canvas, clamp
        tx = int(np.clip(tx, 0, W - 1))

        # If off-canvas vertically, move below bbox
        if ty < 0:
            ty = y + h + pad
        ty = int(np.clip(ty, 0, H - 1))

        return tx, ty
    
    for idx, obj in enumerate(ordered, start=1):
        cv2.drawContours(labeled_mask, [obj["contour"]], -1, int(idx), thickness=-1)

        text = str(idx)  # use f"{idx:03d}" if you want 3-digit IDs
        org = _label_origin_outside_bbox(obj["bbox"], overlay.shape)

        # Draw outline then foreground text for readability on any background
        cv2.putText(
            overlay, text, org,
            cv2.FONT_HERSHEY_SIMPLEX, font_scale,
            (0, 0, 0), thickness + 2, cv2.LINE_AA
        )
        cv2.putText(
            overlay, text, org,
            cv2.FONT_HERSHEY_SIMPLEX, font_scale,
            (255, 0, 0), thickness, cv2.LINE_AA
        )

    if display_result:
        # colorful = label2rgb(labeled_mask)
        # colorful2 = (255*colorful).astype(np.uint8)
        plt.imshow(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
        plt.title(f"Labeled Overlay")
        plt.show()

    if output_mask_path:
        cv2.imwrite(output_mask_path, labeled_mask)

    return labeled_mask, overlay

