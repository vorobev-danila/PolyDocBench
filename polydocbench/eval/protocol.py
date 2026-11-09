"""Evaluation protocol identity, independent of document schema versions."""

from __future__ import annotations

from typing import Any


EVALUATION_PROTOCOL_VERSION = "0.2"


def result_protocol_version(rows: list[dict[str, Any]]) -> str:
    """Reject aggregates mixing legacy and versioned evaluation results."""
    versions = {str(row.get("evaluation_protocol_version", "legacy")) for row in rows}
    if len(versions) > 1:
        raise ValueError("Cannot aggregate different evaluation protocols; use separate result directories.")
    if versions == {"0.3"}:
        policies = {row.get("scope_policy_id") for row in rows}
        if len(policies) != 1 or None in policies:
            raise ValueError("Cannot aggregate missing/different visibility policies or geometry engines")
        if len({row.get("scope_task") for row in rows}) != 1 or len({row.get("scope_unit") for row in rows}) != 1:
            raise ValueError("Cannot aggregate different visibility tasks/annotation units")
    return next(iter(versions), EVALUATION_PROTOCOL_VERSION)
