"""Reporting helpers for metrics that can be undefined."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import mean


def mean_available(values: Iterable[float | int | None]) -> float | None:
    available = [float(value) for value in values if value is not None]
    return mean(available) if available else None


def format_metric(value: float | int | None, precision: int = 4) -> str:
    return f"{value:.{precision}f}" if value is not None else "N/A"
