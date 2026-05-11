"""Reusable scan degradation pipeline extracted from the research notebook."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path
from typing import Any


ImageArray = Any
DegradationFn = Callable[[ImageArray], ImageArray]


def _require_cv2():
    import cv2

    return cv2


def _require_numpy():
    import numpy as np

    return np


def render_pdf_page(pdf_path: str | Path, page_index: int = 0, dpi: int = 200) -> tuple[ImageArray, float]:
    """Render one PDF page to an RGB image array and return its PDF-to-pixel zoom."""

    import fitz
    from PIL import Image

    np = _require_numpy()

    document = fitz.open(pdf_path)
    try:
        page = document[page_index]
        zoom = dpi / 72
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        return np.array(image), zoom
    finally:
        document.close()


def degrade_resolution(image: ImageArray, scale_range: tuple[float, float] = (0.4, 0.8)) -> ImageArray:
    cv2 = _require_cv2()

    height, width = image.shape[:2]
    scale = random.uniform(*scale_range)
    small = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_CUBIC)


def illumination_gradient(image: ImageArray) -> ImageArray:
    np = _require_numpy()

    height, width = image.shape[:2]
    gradient = np.linspace(random.uniform(0.8, 1.0), random.uniform(0.8, 1.0), width)
    mask = np.tile(gradient, (height, 1))
    output = image.astype(np.float32) * mask[..., None]
    return np.clip(output, 0, 255).astype(np.uint8)


def ink_morphology(image: ImageArray, mode: str = "erode") -> ImageArray:
    cv2 = _require_cv2()
    np = _require_numpy()

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    transformed = cv2.erode(binary, kernel, iterations=1) if mode == "erode" else cv2.dilate(binary, kernel, iterations=1)
    return cv2.cvtColor(transformed, cv2.COLOR_GRAY2RGB)


def random_affine(image: ImageArray) -> ImageArray:
    cv2 = _require_cv2()

    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), random.uniform(-2, 2), 1.0)
    matrix[0, 1] += random.uniform(-0.05, 0.05)
    return cv2.warpAffine(image, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE)


def jpeg_artifacts(image: ImageArray, quality_range: tuple[int, int] = (30, 70)) -> ImageArray:
    cv2 = _require_cv2()

    quality = random.randint(*quality_range)
    _, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


NOISE_PROFILES: dict[str, list[DegradationFn]] = {
    "light_scan": [degrade_resolution, illumination_gradient, jpeg_artifacts],
    "medium_scan": [degrade_resolution, random_affine, illumination_gradient, jpeg_artifacts],
    "heavy_scan": [degrade_resolution, random_affine, illumination_gradient, ink_morphology, jpeg_artifacts],
}


def apply_pipeline(image: ImageArray, pipeline: list[DegradationFn]) -> ImageArray:
    """Apply a sequence of degradation functions."""

    output = image.copy()
    for fn in pipeline:
        if fn is ink_morphology:
            output = fn(output, random.choice(["erode", "dilate"]))
        else:
            output = fn(output)
    return output


def pdf_to_noisy_images(
    pdf_path: str | Path,
    output_dir: str | Path,
    page_index: int = 0,
    n_variants: int = 3,
    seed: int = 42,
    dpi: int = 200,
    profiles: list[str] | None = None,
) -> dict[str, object]:
    """Render a PDF page and save noisy JPEG variants for each profile."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    np = _require_numpy()
    random.seed(seed)
    np.random.seed(seed)

    selected_profiles = profiles or list(NOISE_PROFILES)
    unknown_profiles = sorted(set(selected_profiles) - set(NOISE_PROFILES))
    if unknown_profiles:
        raise ValueError(f"Unknown degradation profiles: {', '.join(unknown_profiles)}")

    base_image, zoom = render_pdf_page(pdf_path, page_index=page_index, dpi=dpi)
    written: list[str] = []
    for profile_name in selected_profiles:
        pipeline = NOISE_PROFILES[profile_name]
        for index in range(n_variants):
            image = apply_pipeline(base_image, pipeline)
            target = output_path / f"{profile_name}_{index}.jpg"
            Image.fromarray(image).save(target, "JPEG", quality=95)
            written.append(str(target))

    return {"zoom": zoom, "images": written, "profiles": selected_profiles}
