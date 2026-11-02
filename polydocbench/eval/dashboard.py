"""Interactive reporting for OCR experiment metrics."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .protocol import result_protocol_version
from .quality import aggregate_ocr_counts
from .reporting import format_metric


def write_ocr_dashboard(output_path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write a self-contained Plotly dashboard for OCR quality experiment rows."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as exc:
        raise RuntimeError('Install visualization dependencies with: uv pip install -e ".[ocr]"') from exc

    output_path = Path(output_path)
    protocol_version = result_protocol_version(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        figure = go.Figure()
        figure.add_annotation(text="No experiment metrics were generated.", showarrow=False, font={"size": 18})
        figure.update_layout(title="PolyDocBench OCR Quality Dashboard", template="plotly_white")
        figure.write_html(output_path, include_plotlyjs=True, full_html=True)
        return output_path

    profiles = _ordered_values(rows, "profile", ["clean", "light_scan", "medium_scan", "heavy_scan"])
    languages = _ordered_values(rows, "language")
    templates = _ordered_values(rows, "template", ["simple_article", "scientific_paper", "magazine_layout"])
    use_micro = bool(rows) and all("micro_CER" in row for row in rows)
    cer_metric, wer_metric = ("micro_CER", "micro_WER") if use_micro else ("CER", "WER")
    cer_label, wer_label = ("Micro CER", "Micro WER") if use_micro else ("CER", "WER")
    detection_metric = "line_F1" if use_micro else "matched_ratio"
    detection_label = "Line F1" if use_micro else "Matched Ratio"

    figure = make_subplots(
        rows=3,
        cols=2,
        specs=[[{}, {}], [{}, {}], [{"type": "table", "colspan": 2}, None]],
        subplot_titles=(
            f"{cer_label} by Language and Noise Profile",
            f"{wer_label} by Layout Template and Noise Profile",
            "IoU by Language and Noise Profile",
            f"{detection_label} by Layout Template and Noise Profile",
            "Aggregated Metrics",
        ),
        row_heights=[0.28, 0.28, 0.44],
        vertical_spacing=0.1,
    )
    colors = {
        "clean": "#457b9d",
        "light_scan": "#2a9d8f",
        "medium_scan": "#e9c46a",
        "heavy_scan": "#e76f51",
    }

    for profile in profiles:
        color = colors.get(profile)
        figure.add_trace(
            go.Bar(
                name=profile,
                legendgroup=profile,
                x=languages,
                y=_group_means(rows, "language", languages, cer_metric, profile),
                marker_color=color,
                hovertemplate="%{x}<br>" + cer_label + "=%{y:.4f}<extra>" + profile + "</extra>",
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
                y=_group_means(rows, "template", templates, wer_metric, profile),
                marker_color=color,
                hovertemplate="%{x}<br>" + wer_label + "=%{y:.4f}<extra>" + profile + "</extra>",
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
                y=_group_means(rows, "language", languages, "IoU", profile),
                marker_color=color,
                hovertemplate="%{x}<br>IoU=%{y:.4f}<extra>" + profile + "</extra>",
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
                y=_group_means(rows, "template", templates, detection_metric, profile),
                marker_color=color,
                hovertemplate="%{x}<br>" + detection_label + "=%{y:.4f}<extra>" + profile + "</extra>",
            ),
            row=2,
            col=2,
        )

    summary_rows = _summary_rows(rows)
    figure.add_trace(
        go.Table(
            header={
                "values": ["Language", "Template", "Noise", "Samples", "Macro CER*", "Macro WER*", "IoU", "Matched", "Micro CER", "Micro WER", "Line F1"],
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
                    [f'{row["CER"]:.4f}' for row in summary_rows],
                    [f'{row["WER"]:.4f}' for row in summary_rows],
                    [f'{row["IoU"]:.4f}' for row in summary_rows],
                    [f'{row["matched_ratio"]:.4f}' for row in summary_rows],
                    [format_metric(row["micro_CER"]) for row in summary_rows],
                    [format_metric(row["micro_WER"]) for row in summary_rows],
                    [format_metric(row["line_F1"]) for row in summary_rows],
                ],
                "fill_color": "#f7f9fb",
                "align": "left",
            },
        ),
        row=3,
        col=1,
    )

    figure.update_layout(
        title={
            "text": f"PolyDocBench OCR Quality Dashboard<br><sup>{len(rows)} evaluated scan variants; protocol {protocol_version}; *mean of per-page line means</sup>",
            "x": 0.02,
        },
        barmode="group",
        template="plotly_white",
        height=1280,
        margin={"l": 55, "r": 35, "t": 100, "b": 35},
        legend={"title": {"text": "Noise profile"}, "orientation": "h", "y": 1.04, "x": 0.62},
    )
    figure.update_yaxes(title_text=cer_label, row=1, col=1)
    figure.update_yaxes(title_text=wer_label, row=1, col=2)
    figure.update_yaxes(title_text="IoU", row=2, col=1)
    figure.update_yaxes(title_text=detection_label, row=2, col=2)
    figure.write_html(output_path, include_plotlyjs=True, full_html=True)
    return output_path


def _ordered_values(rows: list[dict[str, Any]], key: str, preferred: list[str] | None = None) -> list[str]:
    values = {str(row[key]) for row in rows}
    preferred = preferred or []
    return [value for value in preferred if value in values] + sorted(values - set(preferred))


def _group_means(
    rows: list[dict[str, Any]],
    dimension: str,
    values: list[str],
    metric: str,
    profile: str,
) -> list[float | None]:
    if metric in {"micro_CER", "micro_WER", "line_F1"}:
        return [aggregate_ocr_counts([
            row for row in rows if row["profile"] == profile and str(row[dimension]) == value
        ])[metric] for value in values]
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
                "CER": mean(float(row["CER"]) for row in group),
                "WER": mean(float(row["WER"]) for row in group),
                "IoU": mean(float(row["IoU"]) for row in group),
                "matched_ratio": mean(float(row["matched_ratio"]) for row in group),
                **aggregate_ocr_counts(group),
            }
        )
    return summary
