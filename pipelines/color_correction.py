# analysis/color_correction.py
import cv2
import numpy as np
import logging



# --------------------------------------------------------------------
# Builds a normalized reference color matrix (chip number + RGB) matched 
# to the detected number of chips in chip_mask, selecting between two 
# reference card definitions and ordering chips to match the card layout.
# --------------------------------------------------------------------

def format_ref_matrix_cal(chip_mask):
    # Count the number of chips identified in chip_mask (gives an idea of which color card was used)
    N_chips = len(np.unique(chip_mask))-1
    # Dependency based on color card used
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
        
        
        chip_nb = np.arange(1, N_chips+1)
        color_matrix_wo_chip_nb = ref/255.
        color_matrix = np.concatenate((chip_nb.reshape(N_chips, 1), color_matrix_wo_chip_nb), axis=1)
    
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
        # array of indices from 1 to N chips in order to match the chip numbering
        # in the color card specs. Later when used for indexing, we subtract the 1.
        idx = np.arange(N_chips)+1
        chip_nb = np.arange(10, 10*N_chips+1, 10)
        # indices in the shape of the color card
        cc_indices = idx.reshape((4, 6), order='C')
        # rotate the indices depending on the specified orientation
        cc_indices_rot = np.rot90(cc_indices, k=3, axes=(0, 1))
        # arange color values based on the indices
        color_matrix_wo_chip_nb = ref[(cc_indices_rot-1).reshape(-1), :]/255.
        # add chip number compatible with other PlantCV functions
        # chip_nb = np.arange(10, 10*N_chips+1, 10)
        color_matrix = np.concatenate((chip_nb.reshape(N_chips, 1), color_matrix_wo_chip_nb), axis=1)

    return color_matrix


# --------------------------------------------------------------------
# Computes per-chip mean RGB values from an image using a labeled chip 
# mask and returns a matrix of chip IDs with their average channel intensities.
# --------------------------------------------------------------------

def extract_chip_colors(rgb_img, mask):
    """Calculate the average value of pixels in each color chip for each color channel.

    Inputs:
    rgb_img         = RGB image with color chips visualized
    mask        = a gray-scale img with unique values for each segmented space, representing unique, discrete
                    color chips.

    Outputs:
    color_matrix        = a 22x4 matrix containing the average red value, average green value, and average blue value
                            for each color chip.
    headers             = a list of 4 headers corresponding to the 4 columns of color_matrix respectively

    :param rgb_img: numpy.ndarray
    :param mask: numpy.ndarray
    :return headers: string array
    :return color_matrix: numpy.ndarray
    """
    # Check for RGB input
    if len(np.shape(rgb_img)) != 3:
        #fatal_error("Input rgb_img is not an RGB image.")
        raise ValueError("Input rgb_img is not an RGB image.")
    # Check mask for gray-scale
    if len(np.shape(mask)) != 2:
        # fatal_error("Input mask is not an gray-scale image.")
        raise ValueError("Input mask is not an gray-scale image.")

    img_dtype = rgb_img.dtype
    # normalization value as max number if the type is unsigned int
    max_val = 1.0
    if img_dtype.kind == 'u':
        max_val = np.iinfo(img_dtype).max

    # convert to float and normalize to work with values between 0-1
    rgb_img = rgb_img.astype(np.float64)/max_val

    # create empty color_matrix
    color_matrix = np.zeros((len(np.unique(mask))-1, 4))

    # create headers
    headers = ["chip_number", "r_avg", "g_avg", "b_avg"]

    # declare row_counter variable and initialize to 0
    row_counter = 0

    # for each unique color chip calculate each average RGB value
    for i in np.unique(mask):
        if i != 0:
            chip = rgb_img[np.where(mask == i)]
            color_matrix[row_counter][0] = i
            color_matrix[row_counter][1] = np.mean(chip[:, 2])
            color_matrix[row_counter][2] = np.mean(chip[:, 1])
            color_matrix[row_counter][3] = np.mean(chip[:, 0])
            row_counter += 1

    return color_matrix


# --------------------------------------------------------------------
# Fits an affine color transform from measured chip colors to reference 
# chip colors (optionally subsetting chips for custom cards) and applies 
# that transform to every pixel to produce a color-corrected image.
# --------------------------------------------------------------------

def apply_color_correction(rgb_img, chip_mask):
    h, w, c = rgb_img.shape
    source_matrix = extract_chip_colors(rgb_img ,chip_mask)
    target_matrix = format_ref_matrix_cal(chip_mask)

    # number of references
    n = source_matrix.shape[0]

    # For custom color card, we do not use all of the chips for color correction (1-8,13-21,25,27-32)
    # We need to subset both source and target to account for this. 

    if n > 25:
        indices = np.hstack([np.arange(start, end) for start, end in [(0, 8), (12, 21), (24, 25), (26, 32)]])
        source_matrix = source_matrix[indices]
        target_matrix = target_matrix[indices]
    
    n = source_matrix.shape[0]
    # the column zero (index) of the matrices is not used in this model
    # augment matrix of source values with a column of 1s for the constant part of
    # the affine transformation
    S = np.concatenate((source_matrix[:, 1:].copy(), np.ones((n, 1))), axis=1)

    # make vectors of target values for each color
    T = target_matrix[:, 1:].copy()
    tr = T[:, 0]
    tg = T[:, 1]
    tb = T[:, 2]

    # calculate regression vector for each color as the pseudoinverse of the source
    # values matrix multiplied by each color target vector
    ar = np.matmul(np.linalg.pinv(S), tr)
    ag = np.matmul(np.linalg.pinv(S), tg)
    ab = np.matmul(np.linalg.pinv(S), tb)

    img_rgb = cv2.cvtColor(rgb_img, cv2.COLOR_BGR2RGB)
    # reshape image as a 2D array where the rows are pixels and the columns are color channels
    # and augment the channels with a column of 1s for the affine transformation
    img_pix = np.concatenate((img_rgb.reshape(h*w, c).astype(np.float64)/255, np.ones((h*w, 1))), axis=1)

    # calculate the corrected colors, eliminate values outside the range [0-1] and
    # convert to [0-255] uint8
    img_r_cc = (255*np.clip(np.matmul(img_pix, ar), 0, 1)).astype(np.uint8)
    img_g_cc = (255*np.clip(np.matmul(img_pix, ag), 0, 1)).astype(np.uint8)
    img_b_cc = (255*np.clip(np.matmul(img_pix, ab), 0, 1)).astype(np.uint8)

    # reconstruct the RGB (actually BGR for openCV) image
    corrected_img = np.stack((img_b_cc, img_g_cc, img_r_cc), axis=1).reshape(h, w, c)

    return corrected_img