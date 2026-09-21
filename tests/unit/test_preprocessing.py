"""Preprocessing tests against synthetically distorted images.

Golden fixtures (real scanned sheets) aren't ready yet, so these tests
generate a clean synthetic ruled-sheet sample and apply known, controlled
distortions to it, rather than waiting. Once real golden fixtures land,
this module should gain an integration test against them too -- see the PR
description for the human "look at a real fixture" checkpoint that this
synthetic suite deliberately can't close on its own.
"""

import cv2
import numpy as np

from app.preprocessing import denoise, deskew, normalize_contrast, preprocess

MAX_RESIDUAL_SKEW_DEGREES = 0.5
KNOWN_SKEW_ANGLE_DEGREES = 7.0
SKEW_DETECTION_TOLERANCE_DEGREES = 1.0

GAUSSIAN_NOISE_SIGMA = 25.0
MIN_DENOISE_PSNR_IMPROVEMENT_DB = 1.0

CONTRAST_DIM_FACTOR = 0.4
MIN_CONTRAST_STDDEV_IMPROVEMENT_RATIO = 1.2


def make_clean_sample(width: int = 400, height: int = 300) -> np.ndarray:
    """A synthetic ruled sheet: grid lines plus solid blocks standing in for text."""
    image = np.full((height, width), 255, dtype=np.uint8)
    for y in range(0, height, 30):
        cv2.line(image, (0, y), (width, y), 0, 2)
    for x in range(0, width, 50):
        cv2.line(image, (x, 0), (x, height), 0, 2)
    for row in range(0, height - 30, 30):
        for col in range(0, width - 50, 50):
            cv2.rectangle(image, (col + 10, row + 8), (col + 40, row + 22), 0, thickness=-1)
    return image


def rotate_reference(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    """Rotate by a known angle using the same convention as pipeline._rotate."""
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    return cv2.warpAffine(
        image,
        rotation_matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )


def add_gaussian_noise(image: np.ndarray, sigma: float = GAUSSIAN_NOISE_SIGMA) -> np.ndarray:
    noise = np.random.default_rng(seed=0).normal(0, sigma, image.shape)
    noisy = image.astype(np.float64) + noise
    return np.clip(noisy, 0, 255).astype(np.uint8)


def dim_contrast(image: np.ndarray, factor: float = CONTRAST_DIM_FACTOR) -> np.ndarray:
    """Compress the dynamic range toward mid-gray, simulating a washed-out scan."""
    midpoint = 128.0
    dimmed = midpoint + (image.astype(np.float64) - midpoint) * factor
    return np.clip(dimmed, 0, 255).astype(np.uint8)


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    if mse == 0:
        return float("inf")
    return 20 * np.log10(255.0 / np.sqrt(mse))


def test_deskew_detects_known_rotation_angle() -> None:
    clean = make_clean_sample()
    skewed = rotate_reference(clean, KNOWN_SKEW_ANGLE_DEGREES)

    result = deskew(skewed)

    angle_error = abs(result.detected_angle_degrees - KNOWN_SKEW_ANGLE_DEGREES)
    assert angle_error < SKEW_DETECTION_TOLERANCE_DEGREES


def test_deskew_corrects_rotation_below_residual_threshold() -> None:
    clean = make_clean_sample()
    skewed = rotate_reference(clean, KNOWN_SKEW_ANGLE_DEGREES)

    corrected = deskew(skewed).corrected_image
    residual = deskew(corrected).detected_angle_degrees

    assert abs(residual) < MAX_RESIDUAL_SKEW_DEGREES


def test_deskew_leaves_already_straight_image_unchanged_in_angle() -> None:
    clean = make_clean_sample()

    result = deskew(clean)

    assert abs(result.detected_angle_degrees) < SKEW_DETECTION_TOLERANCE_DEGREES


def test_denoise_improves_psnr_against_clean_reference() -> None:
    clean = make_clean_sample()
    noisy = add_gaussian_noise(clean)

    denoised = denoise(noisy)

    psnr_before = psnr(noisy, clean)
    psnr_after = psnr(denoised, clean)
    assert psnr_after - psnr_before > MIN_DENOISE_PSNR_IMPROVEMENT_DB


def test_normalize_contrast_increases_intensity_spread() -> None:
    clean = make_clean_sample()
    dimmed = dim_contrast(clean)

    normalized = normalize_contrast(dimmed)

    stddev_before = float(np.std(dimmed))
    stddev_after = float(np.std(normalized))
    assert stddev_after > stddev_before * MIN_CONTRAST_STDDEV_IMPROVEMENT_RATIO


def test_deskew_returns_original_unchanged_when_no_lines_found() -> None:
    blank = np.full((100, 100), 255, dtype=np.uint8)

    result = deskew(blank)

    assert result.detected_angle_degrees == 0.0
    assert np.array_equal(result.corrected_image, blank)


def test_preprocess_handles_color_images() -> None:
    clean = make_clean_sample()
    color = cv2.cvtColor(clean, cv2.COLOR_GRAY2BGR)
    distorted = rotate_reference(color, KNOWN_SKEW_ANGLE_DEGREES)
    distorted = dim_contrast(distorted)

    result = preprocess(distorted)

    assert result.shape == color.shape
    stddev_before = float(np.std(dim_contrast(color)))
    stddev_after = float(np.std(result))
    assert stddev_after > stddev_before * MIN_CONTRAST_STDDEV_IMPROVEMENT_RATIO


def test_preprocess_corrects_skew_denoise_and_contrast_together() -> None:
    clean = make_clean_sample()
    distorted = rotate_reference(clean, KNOWN_SKEW_ANGLE_DEGREES)
    distorted = add_gaussian_noise(distorted)
    distorted = dim_contrast(distorted)

    result = preprocess(distorted)

    residual_skew = deskew(result).detected_angle_degrees
    assert abs(residual_skew) < MAX_RESIDUAL_SKEW_DEGREES

    stddev_before = float(np.std(dim_contrast(clean)))
    stddev_after = float(np.std(result))
    assert stddev_after > stddev_before * MIN_CONTRAST_STDDEV_IMPROVEMENT_RATIO
