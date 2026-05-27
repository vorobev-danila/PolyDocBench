"""Metrics for semantic-block text returned in model reading order."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .block_matching import BlockMatch, match_semantic_blocks
from .ordering import kendall_tau, pairwise_accuracy
from .text_metrics import cer, normalize_text, wer


def evaluate_semantic_ordering(
    gt_blocks: list[dict[str, Any]],
    predicted_blocks: list[dict[str, Any]],
    *,
    min_similarity: float = 0.3,
    max_gt_span: int = 3,
) -> tuple[dict[str, float | int], list[BlockMatch]]:
    """Evaluate OCR text in returned order and order of matched semantic blocks."""
    gt_text = join_ordered_text(gt_blocks)
    predicted_text = join_ordered_text(predicted_blocks)
    token_scores = token_bag_scores(gt_text, predicted_text)
    matches = match_semantic_blocks(
        gt_blocks,
        predicted_blocks,
        min_similarity=min_similarity,
        max_gt_span=max_gt_span,
    )
    gt_order = [block["id"] for block in gt_blocks]
    predicted_order = [gt_id for match in matches for gt_id in match.gt_ids]
    matched_gt_ids = set(predicted_order)
    return (
        {
            "ordered_CER": cer(gt_text, predicted_text),
            "ordered_WER": wer(gt_text, predicted_text),
            **token_scores,
            "kendall_tau": kendall_tau(gt_order, predicted_order),
            "pairwise_accuracy": pairwise_accuracy(gt_order, predicted_order),
            "matched_block_ratio": len(matched_gt_ids) / max(1, len(gt_blocks)),
            "matched_prediction_ratio": len(matches) / max(1, len(predicted_blocks)),
            "num_gt_blocks": len(gt_blocks),
            "num_predicted_blocks": len(predicted_blocks),
            "num_matched_gt_blocks": len(matched_gt_ids),
        },
        matches,
    )


def join_ordered_text(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(str(block.get("text", "")).strip() for block in blocks if str(block.get("text", "")).strip())


def token_bag_scores(gt_text: str, predicted_text: str) -> dict[str, float]:
    gt_tokens = Counter(normalize_text(gt_text).split())
    predicted_tokens = Counter(normalize_text(predicted_text).split())
    overlap = sum((gt_tokens & predicted_tokens).values())
    precision = overlap / max(1, sum(predicted_tokens.values()))
    recall = overlap / max(1, sum(gt_tokens.values()))
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"token_precision": precision, "token_recall": recall, "token_F1": f1}
