"""OpenCV-based image preprocessing: deskew, denoise, contrast normalization.

This corrects in-plane rotation (skew) only -- it does not correct
perspective/keystone distortion from off-angle phone photography. That is a
separate, harder problem (needs corner/quad detection and a homography, not
a simple rotation) and is deliberately out of scope here. See the PR
description for the plan to revisit it once real fixtures show whether it
actually matters in practice.
"""

from dataclasses import dataclass
from typing import Final

import cv2
import numpy as np

# Deskew: Hough line detection tuning.
_CANNY_LOW_THRESHOLD: Final = 50
_CANNY_HIGH_THRESHOLD: Final = 150
_HOUGH_VOTE_THRESHOLD: Final = 100
_HOUGH_MIN_LINE_LENGTH_RATIO: Final = 0.25
_HOUGH_MAX_LINE_GAP: Final = 10

# Denoise: fastNlMeansDenoising measured a higher PSNR-vs-clean recovery than
# medianBlur on the synthetic ruled-sheet sample (24.85 dB vs 18.65 dB,
# median blur was actually worse than no denoising at all on this
# line-heavy image) -- see the PR description for the experiment.
_DENOISE_FILTER_STRENGTH: Final = 10.0
_DENOISE_TEMPLATE_WINDOW_SIZE: Final = 7
_DENOISE_SEARCH_WINDOW_SIZE: Final = 21

# Contrast normalization: min-max intensity stretch to the full 8-bit range.
_CONTRAST_STRETCH_MIN: Final = 0
_CONTRAST_STRETCH_MAX: Final = 255


@dataclass(frozen=True)
class DeskewResult:
    """Outcome of deskewing one image."""

    corrected_image: np.ndarray
    detected_angle_degrees: float


def _to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _fold_angle_degrees(angle_degrees: float) -> float:
    """Fold a line angle into (-45, 45].

    A ruled sheet has both near-horizontal and near-vertical lines. A
    vertical line rotated by the sheet's skew angle theta reports an angle
    of 90 + theta, which folds back to theta here too -- so lines in either
    orientation contribute to the same skew estimate.
    """
    folded = angle_degrees % 90.0
    if folded > 45.0:
        folded -= 90.0
    return folded


def _rotate(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    border_value = (255.0, 255.0, 255.0)
    return cv2.warpAffine(
        image,
        rotation_matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value,
    )  # type: ignore[call-overload]


def deskew(image: np.ndarray) -> DeskewResult:
    """Detect in-plane rotation from ruled lines and rotate it away."""
    gray = _to_grayscale(image)
    edges = cv2.Canny(gray, _CANNY_LOW_THRESHOLD, _CANNY_HIGH_THRESHOLD, apertureSize=3)
    min_line_length = int(min(gray.shape) * _HOUGH_MIN_LINE_LENGTH_RATIO)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=_HOUGH_VOTE_THRESHOLD,
        minLineLength=min_line_length,
        maxLineGap=_HOUGH_MAX_LINE_GAP,
    )

    if lines is None:
        return DeskewResult(corrected_image=image.copy(), detected_angle_degrees=0.0)

    folded_angles = [
        _fold_angle_degrees(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
        for (x1, y1, x2, y2) in lines[:, 0, :]
    ]
    # Image-space angle (y grows downward) is the negation of the angle
    # cv2.getRotationMatrix2D expects to describe the same visual rotation.
    detected_angle_degrees = -float(np.median(folded_angles))

    corrected_image = _rotate(image, -detected_angle_degrees)
    return DeskewResult(
        corrected_image=corrected_image,
        detected_angle_degrees=detected_angle_degrees,
    )


def denoise(image: np.ndarray) -> np.ndarray:
    """Reduce sensor/scan noise with Non-local Means denoising."""
    if image.ndim == 2:
        return cv2.fastNlMeansDenoising(
            image,
            None,
            _DENOISE_FILTER_STRENGTH,
            _DENOISE_TEMPLATE_WINDOW_SIZE,
            _DENOISE_SEARCH_WINDOW_SIZE,
        )
    return cv2.fastNlMeansDenoisingColored(
        image,
        None,
        _DENOISE_FILTER_STRENGTH,
        _DENOISE_FILTER_STRENGTH,
        _DENOISE_TEMPLATE_WINDOW_SIZE,
        _DENOISE_SEARCH_WINDOW_SIZE,
    )


def normalize_contrast(image: np.ndarray) -> np.ndarray:
    """Stretch intensity to the full 8-bit range (min-max contrast stretch)."""
    if image.ndim == 2:
        return cv2.normalize(  # type: ignore[call-overload]
            image, None, _CONTRAST_STRETCH_MIN, _CONTRAST_STRETCH_MAX, cv2.NORM_MINMAX
        )

    lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, red_green, blue_yellow = cv2.split(lab_image)
    lightness = cv2.normalize(  # type: ignore[call-overload]
        lightness, None, _CONTRAST_STRETCH_MIN, _CONTRAST_STRETCH_MAX, cv2.NORM_MINMAX
    )
    normalized_lab_image = cv2.merge((lightness, red_green, blue_yellow))
    return cv2.cvtColor(normalized_lab_image, cv2.COLOR_LAB2BGR)


def preprocess(image: np.ndarray) -> np.ndarray:
    """Run the full pipeline: deskew, then denoise, then normalize contrast."""
    deskewed = deskew(image).corrected_image
    denoised = denoise(deskewed)
    return normalize_contrast(denoised)
