from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List

import numpy as np
from PIL import Image, ImageFilter, ImageStat

# OpenCV is optional — there is no prebuilt wheel for some Python versions.
# When unavailable we fall back to PIL/numpy implementations.
try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore
    _HAS_CV2 = False


@dataclass
class ImageQualityReport:
    overall_quality: str  # GOOD, WARNING, POOR
    is_acceptable: bool
    blur_variance: float
    blur_quality: str
    mean_brightness: float
    brightness_quality: str
    skew_angle: float
    skew_quality: str
    signal_to_noise_ratio: float
    noise_quality: str
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


def _load_pil_gray(image_data: bytes) -> Image.Image:
    pil_img = Image.open(io.BytesIO(image_data))
    if pil_img.mode != "L":
        pil_img = pil_img.convert("L")
    return pil_img


def _load_gray_array(image_data: bytes) -> np.ndarray:
    return np.array(_load_pil_gray(image_data))


def assess_blur(gray: np.ndarray) -> tuple[float, str]:
    """Laplacian variance — higher = sharper. numpy fallback if no cv2."""
    if _HAS_CV2:
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    else:
        # numpy Laplacian kernel convolution (approximation)
        gy, gx = np.gradient(gray.astype("float64"))
        variance = float((gx**2 + gy**2).var())
        # scale to roughly match cv2 Laplacian variance magnitude
        variance *= 4
    if variance > 150:
        quality = "GOOD"
    elif variance >= 100:
        quality = "WARNING"
    else:
        quality = "POOR"
    return variance, quality


def assess_brightness(gray: np.ndarray) -> tuple[float, str]:
    mean_brightness = float(np.mean(gray))
    quality = "GOOD" if 40 <= mean_brightness <= 220 else "WARNING"
    return mean_brightness, quality


def detect_skew(gray: np.ndarray) -> tuple[float, str]:
    """Estimate skew angle. Only meaningful with cv2; otherwise returns 0/GOOD."""
    if not _HAS_CV2:
        return 0.0, "GOOD"
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        if lines is None:
            return 0.0, "GOOD"
        angles = []
        for line in lines[:20]:
            _, theta = line[0]
            angles.append(np.degrees(theta) - 90)
        if not angles:
            return 0.0, "GOOD"
        median_angle = float(np.median(angles))
        quality = "WARNING" if abs(median_angle) > 10 else "GOOD"
        return median_angle, quality
    except Exception:
        return 0.0, "GOOD"


def assess_noise(gray: np.ndarray) -> tuple[float, str]:
    try:
        mean = float(np.mean(gray))
        std = float(np.std(gray))
        snr = mean / (std + 1e-6)
        quality = "GOOD" if snr > 5 else "WARNING"
        return snr, quality
    except Exception:
        return 10.0, "GOOD"


def analyze_image_quality(image_data: bytes) -> ImageQualityReport:
    """Run full image quality analysis on raw image bytes."""
    gray = _load_gray_array(image_data)

    blur_var, blur_quality = assess_blur(gray)
    brightness, brightness_quality = assess_brightness(gray)
    skew_angle, skew_quality = detect_skew(gray)
    snr, noise_quality = assess_noise(gray)

    issues: List[str] = []
    recommendations: List[str] = []

    if blur_quality == "POOR":
        issues.append("Image is too blurry (low sharpness)")
        recommendations.append("Re-scan or re-photograph with better focus")
    elif blur_quality == "WARNING":
        issues.append("Image may be slightly blurry")
        recommendations.append("Consider rescanning if fields are unreadable")

    if brightness_quality == "WARNING":
        if brightness < 40:
            issues.append("Image is too dark")
            recommendations.append("Increase lighting or scanner brightness")
        else:
            issues.append("Image is overexposed")
            recommendations.append("Reduce lighting or scanner brightness")

    if skew_quality == "WARNING":
        issues.append(f"Document is skewed by {skew_angle:.1f} degrees")
        recommendations.append("Straighten the document before scanning")

    if noise_quality == "WARNING":
        issues.append("High image noise detected")
        recommendations.append("Use a higher quality scanner or camera")

    poor_count = sum(q == "POOR" for q in [blur_quality, brightness_quality, skew_quality, noise_quality])
    warning_count = sum(q == "WARNING" for q in [blur_quality, brightness_quality, skew_quality, noise_quality])

    if poor_count > 0 or warning_count >= 2:
        overall = "POOR"
        is_acceptable = False
    elif warning_count == 1:
        overall = "WARNING"
        is_acceptable = True
    else:
        overall = "GOOD"
        is_acceptable = True

    return ImageQualityReport(
        overall_quality=overall,
        is_acceptable=is_acceptable,
        blur_variance=blur_var,
        blur_quality=blur_quality,
        mean_brightness=brightness,
        brightness_quality=brightness_quality,
        skew_angle=skew_angle,
        skew_quality=skew_quality,
        signal_to_noise_ratio=snr,
        noise_quality=noise_quality,
        issues=issues,
        recommendations=recommendations,
    )


def preprocess_image(image_data: bytes) -> bytes:
    """
    Preprocess image for OCR. Uses cv2 when available (denoise+threshold+deskew),
    otherwise a PIL-based fallback (grayscale + autocontrast + sharpen).
    Returns processed PNG bytes.
    """
    if _HAS_CV2:
        gray = _load_gray_array(image_data)
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) > 10:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = 90 + angle
            if abs(angle) > 0.5:
                (h, w) = thresh.shape
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                thresh = cv2.warpAffine(thresh, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        _, buffer = cv2.imencode(".png", thresh)
        return buffer.tobytes()

    # PIL fallback
    from PIL import ImageOps
    pil = _load_pil_gray(image_data)
    pil = ImageOps.autocontrast(pil)
    pil = pil.filter(ImageFilter.SHARPEN)
    out = io.BytesIO()
    pil.save(out, format="PNG")
    return out.getvalue()