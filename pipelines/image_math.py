# helpers/image_math.py
import cv2
import numpy as np
import math


# --------------------------------------------------------------------
# _approx_quad: Iteratively adjusts polygon approximation tolerance to 
# find a 4-vertex contour approximation, returning the quadrilateral if found.
# --------------------------------------------------------------------

def _approx_quad(cnt, start=0.006, stop=0.06, step=0.002):
    """Try to get a 4-vertex approx by sweeping epsilon. Return approx or None."""
    perim = cv2.arcLength(cnt, True)
    if perim <= 0:
        return None
    eps = start
    while eps <= stop:
        approx = cv2.approxPolyDP(cnt, eps * perim, True)
        if len(approx) == 4:
            return approx
        eps += step
    return None

# --------------------------------------------------------------------
# _angle_cos – Computes the cosine of the angle at a given vertex using 
# vector dot product to quantify angular deviation.
# --------------------------------------------------------------------

def _angle_cos(p0, p1, p2):
    """Cosine of angle at p1 formed by p0-p1-p2."""
    v1 = p0 - p1
    v2 = p2 - p1
    denom = (np.linalg.norm(v1) * np.linalg.norm(v2)) + 1e-9
    return float(np.dot(v1, v2) / denom)


# --------------------------------------------------------------------
# _quad_rect_score – Scores how closely a contour resembles a rectangle 
# based on convexity, right-angle similarity, fill ratio within a 
# minimum-area bounding box, and expected aspect ratio. 
# --------------------------------------------------------------------

def _quad_rect_score(approx, cnt):
    """Score how 'rectangle-like' a 4-pt approx is."""
    if approx is None or len(approx) != 4:
        return 0.0
    # Convexity
    if not cv2.isContourConvex(approx):
        return 0.0

    pts = approx[:, 0, :]  # (4,2)
    # Sort points to have consistent angle checks?
    # Using minAreaRect to get rectangularity (area / box_area)
    area = cv2.contourArea(cnt)
    rect = cv2.minAreaRect(cnt)
    box = cv2.boxPoints(rect)
    box_area = cv2.contourArea(box.astype(np.float32))
    rect_fill = 0.0 if box_area <= 0 else (area / box_area)

    # Angle closeness to 90° via cosine near 0
    # order points by angle around centroid
    c = pts.mean(axis=0)
    angs = np.arctan2(pts[:,1]-c[1], pts[:,0]-c[0])
    order = np.argsort(angs)
    q = pts[order]

    cosines = []
    for i in range(4):
        p_prev = q[(i-1) % 4]
        p = q[i]
        p_next = q[(i+1) % 4]
        cosines.append(abs(_angle_cos(p_prev, p, p_next)))
    # 0 is perfect right angle. Penalize large cosines.
    angle_score = 1.0 - min(1.0, float(np.mean(cosines)))  # closer to 1 is better

    # Aspect ratio closeness to typical color card (~1.5 for 24-chip 6x4)
    w, h = rect[1]
    if w <= 1e-6 or h <= 1e-6:
        ar_score = 0.0
    else:
        ar = max(w, h) / min(w, h)
        target = 1.5
        ar_score = max(0.0, 1.0 - abs(ar - target) / target)  # 1 if exact, declines with distance

    # Combine scores (weights can be tuned)
    score = 0.5 * angle_score + 0.3 * rect_fill + 0.2 * ar_score
    return score

# --------------------------------------------------------------------
# _circle_score – Scores how closely a contour resembles a circle using 
# circularity and how tightly it fits within its minimum enclosing circle.
# --------------------------------------------------------------------

def _circle_score(cnt):
    """Score how circle-like a contour is (circularity + tightness in enclosing circle)."""
    area = cv2.contourArea(cnt)
    perim = cv2.arcLength(cnt, True)
    if area <= 0 or perim <= 0:
        return 0.0

    # Circularity: 1.0 for perfect circle
    circularity = 4.0 * math.pi * area / (perim * perim)

    # Tightness in enclosing circle
    (x, y), r = cv2.minEnclosingCircle(cnt)
    circle_area = math.pi * (r ** 2)
    if circle_area <= 0:
        tight = 0.0
    else:
        tight = area / circle_area  # <= 1.0; closer to 1 is better

    # Combine (weights can be tuned)
    score = 0.7 * min(1.0, circularity) + 0.3 * min(1.0, tight)
    return float(score)


