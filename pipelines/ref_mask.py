# masking/ref_mask.py
import cv2
import numpy as np
import math
from pipelines.utils import apply_mask
from pipelines.image_math import _approx_quad, _quad_rect_score, _circle_score
from scipy.ndimage import binary_fill_holes
from skimage.morphology import remove_small_objects

# --------------------------------------------------------------------
# Detects and isolates the most rectangle-like contour (color card) 
# and most circle-like contour (size marker) in an image using adaptive 
# thresholding, morphological cleanup, contour scoring, and returns 
# separate binary masks for each.
# --------------------------------------------------------------------

def create_masks(img, raise_errors=True):
    # --- Thresholding & cleanup ---
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    seed_mask = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
        blockSize=51, C=5
    )

    bool_img = seed_mask.astype(bool)
    bool_img = binary_fill_holes(bool_img)
    seed_mask = (bool_img.astype(np.uint8) * 255)

    seed_mask = cv2.morphologyEx(seed_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    contours, _ = cv2.findContours(seed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    H, W = seed_mask.shape
    min_area = H * W * 0.005  # tune as needed

    # --- Score candidates ---
    best_rect = {"score": 0.0, "cnt": None}
    best_circle = {"score": 0.0, "cnt": None}

    for cnt in contours:
        if cv2.contourArea(cnt) <= min_area:
            continue

        # Rectangle score
        quad = _approx_quad(cnt, start=0.006, stop=0.06, step=0.002)
        rect_score = _quad_rect_score(quad, cnt) if quad is not None else 0.0
        if rect_score > best_rect["score"]:
            best_rect = {"score": rect_score, "cnt": cnt}

        # Circle score
        circ_score = _circle_score(cnt)
        if circ_score > best_circle["score"]:
            best_circle = {"score": circ_score, "cnt": cnt}

    # --- Build separate masks for the single best of each class ---
    cc_mask = np.zeros_like(seed_mask)
    sm_mask = np.zeros_like(seed_mask)

    # To avoid picking the same contour for both, prefer the higher-scoring class and
    # then suppress that contour for the other class if they are the same object.
    cc_cnt = best_rect["cnt"]
    sm_cnt = best_circle["cnt"]

    if cc_cnt is not None and sm_cnt is not None and cc_cnt is sm_cnt:
        # If the same contour is top for both, keep it where it scores higher.
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
            raise RuntimeError("Error: No color card (rectangle) detected.")
        if sm_cnt is None:
            raise RuntimeError("Error: No size marker (circle) detected.")

    return cc_mask, sm_mask



# --------------------------------------------------------------------
# Create masks for each chip in colorcard - used for color correction
# --------------------------------------------------------------------

def create_chip_mask(img, cc_mask):
    #Create image with only colorcard. 
    masked = apply_mask(img, cc_mask)
    
    #Convert to v_channel
    hsv = cv2.cvtColor(masked, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    
    # Apply binary thresholding using the peak value
    _, binary_mask = cv2.threshold(v_channel, 75, 255, cv2.THRESH_BINARY)
    bool_img = binary_mask.astype(bool)
    
    # Find and fill contours
    bool_img = remove_small_objects(bool_img, 200)
    bool_img = binary_fill_holes(bool_img)
    binary_mask = np.copy(bool_img.astype(np.uint8) * 255)
    # pcv.plot_image(binary_mask)
    
    debug_img = img.copy()
    filtered_contours, _ = cv2.findContours(binary_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    target_square_area = np.median([cv2.contourArea(cnt) for cnt in filtered_contours])
    # Filter contours again, keep only those within 20% of median area
    filtered_contours = [contour for contour in filtered_contours if
                         (0.8 < (cv2.contourArea(contour) / target_square_area) < 1.2)]
    # cv2.drawContours(debug_img, filtered_contours, -1, color=(255, 50, 250), thickness=5)
    # pcv.plot_image(debug_img)
    
    # Initialize chip shape lists
    marea, mwidth, mheight = [], [], []
    # Loop over our contours and size data about them
    for cnt in filtered_contours:
        marea.append(cv2.contourArea(cnt))
        _, wh, _ = cv2.minAreaRect(cnt)  # Rotated rectangle
        mwidth.append(wh[0])
        mheight.append(wh[1])
    
    # Concatenate all contours into one array and find the minimum area rectangle
    rect = np.concatenate([[np.array(cv2.minAreaRect(i)[0]).astype(int)] for i in filtered_contours])
    rect = cv2.minAreaRect(rect)
    box_points = cv2.boxPoints(rect)
    box = np.int_(box_points) # Convert to integer coordinates
    # Draw the rotated rectangle on the original image
    # min_rect = cv2.drawContours(np.zeros(img.shape[0:2]), [box], 0, (255), 2) # Green color, 2 thickness
    # pcv.plot_image(min_rect)
    
    # Get the corners of the rectangle
    corners = np.array(np.intp(cv2.boxPoints(rect)))
    # Determine which corner most likely contains the white chip
    white_index = np.argmin([np.mean(math.dist(img[corner[1], corner[0], :], (255, 255, 255))) for corner in corners])
    # print(white_index)
    corners = corners[np.argsort([math.dist(corner, corners[white_index]) for corner in corners])[[0, 1, 3, 2]]]
    # Increment amount is arbitrary, cell distances rescaled during perspective transform
    increment = 100
    centers = [[int(0 + i * increment), int(0 + j * increment)] for j in range(6) for i in range(4)]
    
    # Find the minimum area rectangle of the chip centers
    new_rect = cv2.minAreaRect(np.array(centers))
    # Get the corners of the rectangle
    box_points = cv2.boxPoints(new_rect).astype("float32")
    # Calculate the perspective transform matrix from the minimum area rectangle
    m_transform = cv2.getPerspectiveTransform(box_points, corners.astype("float32"))
    # Transform the chip centers using the perspective transform matrix
    new_centers = cv2.transform(np.array([centers]), m_transform)[0][:, 0:2]
    
    # Loop over the new chip centers and draw them on the RGB image and labeled mask
    marker_labeled_mask = np.zeros(np.shape(img)[:2], dtype=np.uint8)
    debug_img = img.copy()
    for i, pt in enumerate(new_centers):
        cv2.circle(marker_labeled_mask, new_centers[i], 5, (i + 1) * 10, -1)
        cv2.circle(debug_img, new_centers[i], 5, (255, 255, 0), -1)
        cv2.putText(debug_img, text=str(i), org=pt, fontScale=1, color=(255, 0, 255),
                    fontFace=cv2.FONT_HERSHEY_SIMPLEX, thickness=5)
    return marker_labeled_mask