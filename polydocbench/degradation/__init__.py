"""Synthetic scan degradation helpers."""

from .debug import draw_gt_overlay
from .geometry import transform_gt_to_image_gt
from .scans import NOISE_PROFILES, pdf_to_noisy_dataset, pdf_to_noisy_images, render_pdf_page

__all__ = [
    "NOISE_PROFILES",
    "draw_gt_overlay",
    "pdf_to_noisy_dataset",
    "pdf_to_noisy_images",
    "render_pdf_page",
    "transform_gt_to_image_gt",
]
