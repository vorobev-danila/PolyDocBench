"""Ground-truth export helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from polydocbench.document.schema import FORMAT_SCHEMA_VERSION
from polydocbench.gt.schema import validate_gt_document


def export_json(data: dict[str, Any], output_path: str | Path, indent: int = 2) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")


class GroundTruthExporter:
    """Export PolyDocBench layout results to JSON ground truth."""

    def __init__(self, config: Any | None = None) -> None:
        self.config = config

    def export(self, layout_result: Any, output_path: str | Path) -> dict[str, Any]:
        output_path = Path(output_path)

        try:
            gt_data = self._get_gt_data(layout_result)
            gt_data.setdefault("schema_version", FORMAT_SCHEMA_VERSION)
            gt_data.setdefault("metadata", {})
            gt_data["metadata"].setdefault("format_version", gt_data["schema_version"])
            gt_data["metadata"]["export_time"] = datetime.now().isoformat()
            validate_gt_document(gt_data)

            self._save_to_json(gt_data, output_path)
            return {
                "success": True,
                "path": str(output_path),
                "size": output_path.stat().st_size if output_path.exists() else 0,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _get_gt_data(self, layout_result: Any) -> dict[str, Any]:
        if hasattr(layout_result, "ground_truth") and layout_result.ground_truth:
            return layout_result.ground_truth

        if not hasattr(layout_result, "to_dict"):
            raise ValueError("layout_result must provide to_dict() or ground_truth")

        return self._prepare_gt_data(layout_result.to_dict())

    def _prepare_gt_data(self, layout_dict: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": FORMAT_SCHEMA_VERSION,
            "metadata": {
                "generator": "PolyDocBench",
                "export_time": datetime.now().isoformat(),
                "format_version": FORMAT_SCHEMA_VERSION,
                "coordinate_system": "points (1/72 inch)",
                "origin": "bottom-left",
            },
            "reading_order": {"blocks": [], "lines": []},
            "pages": layout_dict.get("pages", []),
            "elements": layout_dict.get("elements", []),
        }

    def _save_to_json(self, data: dict[str, Any], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        export_config = self._config_get("render.export", {})
        pretty_print = export_config.get("pretty_print", True) if isinstance(export_config, dict) else True
        indent_size = export_config.get("indent_size", 2) if isinstance(export_config, dict) else 2
        indent = indent_size if pretty_print else None
        path.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")

    def _config_get(self, key: str, default: Any = None) -> Any:
        if self.config is None:
            return default

        get = getattr(self.config, "get", None)
        if callable(get):
            return get(key, default)

        if isinstance(self.config, dict):
            value: Any = self.config
            for part in key.split("."):
                if not isinstance(value, dict) or part not in value:
                    return default
                value = value[part]
            return value

        return default
