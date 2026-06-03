"""Interactive reporting for structure evaluation metrics."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def write_structure_dashboard(output_path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write a self-contained Plotly dashboard for Docling structure metrics."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as exc:
        raise RuntimeError('Install visualization dependencies with: uv pip install -e ".[structure]"') from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        figure = go.Figure()
        figure.add_annotation(text="No structure metrics were generated.", showarrow=False, font={"size": 18})
        figure.update_layout(title="PolyDocBench Structure Evaluation Dashboard", template="plotly_white")
        figure.write_html(output_path, include_plotlyjs=True, full_html=True)
        return output_path

    profiles = _ordered_values(rows, "profile", ["light_scan", "medium_scan", "heavy_scan"])
    languages = _ordered_values(rows, "language")
    templates = _ordered_values(rows, "template", ["simple_article", "scientific_paper", "magazine_layout"])

    figure = make_subplots(
        rows=3,
        cols=2,
        specs=[[{}, {}], [{}, {}], [{"type": "table", "colspan": 2}, None]],
        subplot_titles=(
            "Structure Score by Language and Noise Profile",
            "Detection F1 by Layout Template and Noise Profile",
            "Type Accuracy by Language and Noise Profile",
            "Mean IoU by Layout Template and Noise Profile",
            "Aggregated Metrics",
        ),
        row_heights=[0.28, 0.28, 0.44],
        vertical_spacing=0.1,
    )
    colors = {"light_scan": "#2a9d8f", "medium_scan": "#e9c46a", "heavy_scan": "#e76f51"}

    for profile in profiles:
        color = colors.get(profile)
        figure.add_trace(
            go.Bar(
                name=profile,
                legendgroup=profile,
                x=languages,
                y=_group_means(rows, "language", languages, "structure_score", profile),
                marker_color=color,
                hovertemplate="%{x}<br>score=%{y:.4f}<extra>" + profile + "</extra>",
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Bar(
                name=profile,
                legendgroup=profile,
                showlegend=False,
                x=templates,
                y=_group_means(rows, "template", templates, "detection_F1", profile),
                marker_color=color,
                hovertemplate="%{x}<br>F1=%{y:.4f}<extra>" + profile + "</extra>",
            ),
            row=1,
            col=2,
        )
        figure.add_trace(
            go.Bar(
                name=profile,
                legendgroup=profile,
                showlegend=False,
                x=languages,
                y=_group_means(rows, "language", languages, "type_accuracy", profile),
                marker_color=color,
                hovertemplate="%{x}<br>type=%{y:.4f}<extra>" + profile + "</extra>",
            ),
            row=2,
            col=1,
        )
        figure.add_trace(
            go.Bar(
                name=profile,
                legendgroup=profile,
                showlegend=False,
                x=templates,
                y=_group_means(rows, "template", templates, "mean_iou", profile),
                marker_color=color,
                hovertemplate="%{x}<br>IoU=%{y:.4f}<extra>" + profile + "</extra>",
            ),
            row=2,
            col=2,
        )

    summary_rows = _summary_rows(rows)
    figure.add_trace(
        go.Table(
            header={
                "values": ["Language", "Template", "Noise", "Samples", "Score", "Det F1", "Type Acc", "Mean IoU"],
                "fill_color": "#213547",
                "font": {"color": "white"},
                "align": "left",
            },
            cells={
                "values": [
                    [row["language"] for row in summary_rows],
                    [row["template"] for row in summary_rows],
                    [row["profile"] for row in summary_rows],
                    [row["count"] for row in summary_rows],
                    [f'{row["structure_score"]:.4f}' for row in summary_rows],
                    [f'{row["detection_F1"]:.4f}' for row in summary_rows],
                    [f'{row["type_accuracy"]:.4f}' for row in summary_rows],
                    [f'{row["mean_iou"]:.4f}' for row in summary_rows],
                ],
                "fill_color": "#f7f9fb",
                "align": "left",
            },
        ),
        row=3,
        col=1,
    )
    figure.update_layout(
        title={"text": f"PolyDocBench Structure Evaluation Dashboard<br><sup>{len(rows)} evaluated scans</sup>", "x": 0.02},
        barmode="group",
        template="plotly_white",
        height=1280,
        margin={"l": 55, "r": 35, "t": 100, "b": 35},
        legend={"title": {"text": "Noise profile"}, "orientation": "h", "y": 1.04, "x": 0.62},
    )
    figure.write_html(output_path, include_plotlyjs=True, full_html=True)
    return output_path


def _ordered_values(rows: list[dict[str, Any]], key: str, preferred: list[str] | None = None) -> list[str]:
    values = {str(row[key]) for row in rows}
    preferred = preferred or []
    return [value for value in preferred if value in values] + sorted(values - set(preferred))


def _group_means(rows: list[dict[str, Any]], dimension: str, values: list[str], metric: str, profile: str) -> list[float | None]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["profile"] == profile:
            grouped[str(row[dimension])].append(float(row[metric]))
    return [mean(grouped[value]) if grouped[value] else None for value in values]


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["language"], row["template"], row["profile"])].append(row)
    summary = []
    for (language, template, profile), group in sorted(grouped.items()):
        summary.append(
            {
                "language": language,
                "template": template,
                "profile": profile,
                "count": len(group),
                "structure_score": mean(float(row["structure_score"]) for row in group),
                "detection_F1": mean(float(row["detection_F1"]) for row in group),
                "type_accuracy": mean(float(row["type_accuracy"]) for row in group),
                "mean_iou": mean(float(row["mean_iou"]) for row in group),
            }
        )
    return summary
