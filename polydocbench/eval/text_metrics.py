"""Text normalization and OCR quality metrics."""

from __future__ import annotations

import re
from collections.abc import Sequence


def normalize_text(text: str) -> str:
    """Lowercase text and collapse whitespace for OCR comparisons."""

    return re.sub(r"\s+", " ", text.lower()).strip()


def edit_distance(source: Sequence[str] | str, target: Sequence[str] | str) -> int:
    """Compute Levenshtein distance without optional binary dependencies."""

    previous = list(range(len(target) + 1))
    for i, source_item in enumerate(source, start=1):
        current = [i]
        for j, target_item in enumerate(target, start=1):
            cost = 0 if source_item == target_item else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def cer(gt: str, prediction: str) -> float:
    """Character error rate."""

    gt = normalize_text(gt)
    prediction = normalize_text(prediction)
    return edit_distance(gt, prediction) / max(1, len(gt))


def wer(gt: str, prediction: str) -> float:
    """Word error rate."""

    gt_words = normalize_text(gt).split()
    prediction_words = normalize_text(prediction).split()
    return edit_distance(gt_words, prediction_words) / max(1, len(gt_words))

