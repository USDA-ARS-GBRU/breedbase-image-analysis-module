# masking/seed_mask.py
import cv2
import numpy as np
from scipy.ndimage import binary_fill_holes
from skimage.morphology import remove_small_objects

# --------------------------------------------------------------------
# Isolate seed from corrected image
# --------------------------------------------------------------------

def create_seed_mask(corrected_img, cc_mask, sm_mask):

    # # Adaptive Thresholding
    # gray = cv2.cvtColor(corrected_img, cv2.COLOR_BGR2GRAY)
    # binary = cv2.adaptiveThreshold(gray, 255,
    #                                   cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
    #                                   cv2.THRESH_BINARY_INV,
    #                                   blockSize=55,
    #                                   C=2)
    hsv = cv2.cvtColor(corrected_img, cv2.COLOR_BGR2HSV)
    h_channel = hsv[:, :, 0]
    v_channel = hsv[:, :, 2]
    _, h_binary = cv2.threshold(h_channel, 60, 255, cv2.THRESH_BINARY_INV)
    _, v_binary = cv2.threshold(v_channel, 140, 255, cv2.THRESH_BINARY_INV)
    binary = cv2.bitwise_or(h_binary, v_binary)
    
    # Remove colorcard and size marker with previous masks
    seed_mask = cv2.subtract(binary, cc_mask)
    seed_mask = cv2.subtract(seed_mask, sm_mask)
    
    #Convert to booleon for some morphology filters. 
    bool_img = seed_mask.astype(bool)
    
    # Find and fill contours
    bool_img = binary_fill_holes(bool_img)
    bool_img = remove_small_objects(bool_img, 100)
    binary = np.copy(bool_img.astype(np.uint8) * 255)
    
    return binary