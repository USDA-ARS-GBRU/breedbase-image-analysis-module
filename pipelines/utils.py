# helpers/utils.py
import cv2
import numpy as np
import os



# --------------------------------------------------------------------
# enforce_https – Ensures a URL uses HTTPS by replacing an http:// 
# prefix with https:// if present
# --------------------------------------------------------------------

def enforce_https(url):
    if url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url

# --------------------------------------------------------------------
#Read an image from file and return img, path, and img_filename
# --------------------------------------------------------------------

def readimage(filename):
    img = cv2.imread(filename)
    if img is None:
        raise ValueError(f"Invalid image path: {filename}")
    _, img_filename = os.path.split(filename)
    if np.shape(img)[1] < np.shape(img)[0]:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return img, img_filename


# --------------------------------------------------------------------
# Apply binary mask to original image
# --------------------------------------------------------------------
def apply_mask(img, mask):
    array_data = img.copy()
    array_data[np.where(mask == 0)] = 0
    return array_data

