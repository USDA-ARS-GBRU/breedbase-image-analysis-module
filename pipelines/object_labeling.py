# helpers/object_labeling.py
import cv2
import numpy as np
import matplotlib.pyplot as plt


def label_objects_rowwise(binary, orig_img, output_mask_path=None, display_result=False):
    """
    Detect connected objects in a binary mask, group into rows (by y proximity),
    order left-to-right within rows, assign sequential labels (1..N), and return:
        - labeled_mask (uint16): label IDs match downstream shape analysis
        - overlay_img (BGR): original image with label indices drawn outside bbox

    Label placement: just outside each object's bounding box so it does not
    occlude the seed outline drawn later by shape_analysis.
    """

    overlay = orig_img.copy()

    # Ensure binary is uint8 0/255
    bin_u8 = binary.astype(np.uint8)
    if bin_u8.max() <= 1:
        bin_u8 = (bin_u8 > 0).astype(np.uint8) * 255
    else:
        bin_u8 = (bin_u8 > 0).astype(np.uint8) * 255

    contours, _ = cv2.findContours(
        bin_u8,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        raise ValueError("No objects found in the binary image.")

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

        objects.append({
            "centroid": (cx, cy),
            "contour": cnt,
            "bbox": (x, y, w, h)
        })

    if not objects:
        raise ValueError("No valid objects after filtering.")

    # Row grouping threshold
    med_h = float(np.median(heights))
    row_thresh = max(5, int(med_h * 0.75))

    # Sort objects by y-coordinate
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

    rows.append(current_row)

    # Sort each row left-to-right
    rows = [
        sorted(row, key=lambda o: o["centroid"][0])
        for row in rows
    ]

    ordered = [obj for row in rows for obj in row]

    # Use uint16 to avoid overflow if many objects
    labeled_mask = np.zeros(bin_u8.shape, dtype=np.uint16)

    # Image-based font scaling (robust across resolutions)
    img_h, img_w = overlay.shape[:2]
    font_scale = float(np.clip(img_h / 1400.0, 0.45, 1.6))
    thickness = int(np.clip(img_h / 900.0, 1, 3))

    def label_origin_outside_bbox(bbox, img_shape):
        """
        Place label just outside bounding box.
        Prefer top-left; fallback right/bottom if off-canvas.
        """
        x, y, w, h = bbox
        H, W = img_shape[:2]

        pad = int(np.clip(0.25 * min(w, h), 6, 30))

        tx = x - pad
        ty = y - pad

        if tx < 0:
            tx = x + w + pad
        tx = int(np.clip(tx, 0, W - 1))

        if ty < 0:
            ty = y + h + pad
        ty = int(np.clip(ty, 0, H - 1))

        return tx, ty

    for idx, obj in enumerate(ordered, start=1):
        cv2.drawContours(
            labeled_mask,
            [obj["contour"]],
            -1,
            int(idx),
            thickness=-1
        )

        text = str(idx)
        org = label_origin_outside_bbox(obj["bbox"], overlay.shape)

        # Draw outline for readability
        cv2.putText(
            overlay,
            text,
            org,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            thickness + 2,
            cv2.LINE_AA
        )

        # Draw foreground text
        cv2.putText(
            overlay,
            text,
            org,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 0, 0),
            thickness,
            cv2.LINE_AA
        )

    if display_result:
        plt.imshow(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
        plt.title("Labeled Overlay (labels outside bbox)")
        plt.axis("off")
        plt.show()

    if output_mask_path:
        cv2.imwrite(output_mask_path, labeled_mask)

    return labeled_mask, overlay
