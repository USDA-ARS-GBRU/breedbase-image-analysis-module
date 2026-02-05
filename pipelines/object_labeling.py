# helpers/object_labeling.py
import cv2
import numpy as np
import matplotlib.pyplot as plt

# --------------------------------------------------------------------
# Detects connected objects in a binary image, groups them into rows 
# based on vertical proximity, orders them left-to-right within each 
# row, assigns sequential labels, and returns both a labeled mask 
# and an annotated visualization image.
# --------------------------------------------------------------------
def label_objects_rowwise(binary, orig_img, output_mask_path=None, display_result=False):

    original = orig_img.copy()
    # Find contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("No objects found in the binary image.")

    # Compute centroids and bounding box heights
    objects = []
    heights = []
    widths = []
    for cnt in contours:
        M = cv2.moments(cnt)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            _, _, w, h = cv2.boundingRect(cnt)
            heights.append(h)
            widths.append(w)
            objects.append({'centroid': (cx, cy), 'contour': cnt})

    if not heights:
        raise ValueError("Unable to determine object sizes.")
    row_thresh = int(np.median(heights) * 0.75)
    font_size = int(np.median(heights) * 0.02)
    lab_dev = int(np.median(widths))
    
    # Group objects into rows by proximity in the y-direction
    y_coords = np.array([obj['centroid'][1] for obj in objects])
    sorted_indices = np.argsort(y_coords)
    sorted_objects = [objects[i] for i in sorted_indices]

    rows = []
    current_row = [sorted_objects[0]]
    current_y = sorted_objects[0]['centroid'][1]

    for obj in sorted_objects[1:]:
        if abs(obj['centroid'][1] - current_y) < row_thresh:
            current_row.append(obj)
        else:
            rows.append(current_row)
            current_row = [obj]
            current_y = obj['centroid'][1]
    rows.append(current_row)  # Add the last row

    # Sort each row from left to right
    for i in range(len(rows)):
        rows[i] = sorted(rows[i], key=lambda obj: obj['centroid'][0])

    # Flatten the ordered list row-by-row
    ordered = [obj for row in rows for obj in row]

    # Create labeled mask
    labeled_mask = np.zeros_like(binary, dtype=np.uint8)
    for idx, obj in enumerate(ordered):
        cv2.drawContours(labeled_mask, [obj['contour']], -1, int(idx + 1), thickness=-1)
        cx, cy = obj['centroid']
        cv2.putText(
            original,
            str(idx + 1),
            (cx - np.uint8(lab_dev), cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            np.uint8(font_size),
            (255, 0, 0),
            12,
            cv2.LINE_AA
        )

    if display_result:
        # colorful = label2rgb(labeled_mask)
        # colorful2 = (255*colorful).astype(np.uint8)
        plt.imshow(cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
        plt.title(f"Labeled Mask")
        plt.show()

    if output_mask_path:
        cv2.imwrite(output_mask_path, labeled_mask)

    return labeled_mask, original

