"""
Экспортер ground truth данных
"""

import json
import os
from datetime import datetime
from typing import Dict, Any


class GroundTruthExporter:
    """Экспортер ground truth данных"""
    
    def __init__(self, config):
        self.config = config
    
    def export(self, layout_result, output_path: str) -> Dict[str, Any]:
        """Экспортирует ground truth в JSON файл"""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Если уже есть ground_truth, используем его
            if hasattr(layout_result, 'ground_truth') and layout_result.ground_truth:
                gt_data = layout_result.ground_truth
            else:
                # Иначе создаем из to_dict()
                layout_dict = layout_result.to_dict()
                gt_data = self._prepare_gt_data(layout_dict)
            
            # Добавляем время экспорта
            gt_data["metadata"]["export_time"] = datetime.now().isoformat()
            
            # Сохраняем в файл
            self._save_to_json(gt_data, output_path)
            
            return {
                "success": True,
                "path": output_path,
                "size": os.path.getsize(output_path) if os.path.exists(output_path) else 0
            }
            
        except Exception as e:
            print(f"   ❌ Ошибка экспорта ground truth: {e}")
            return {"success": False, "error": str(e)}
    
    def _prepare_gt_data(self, layout_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Подготавливает данные для экспорта"""
        return {
            "metadata": {
                "generator": "PolyDocBench",
                "export_time": datetime.now().isoformat(),
                "format_version": "1.0",
                "coordinate_system": "points (1/72 inch)",
                "origin": "bottom-left"
            },
            "pages": layout_dict.get("pages", []),
            "elements": layout_dict.get("elements", [])
        }
    
    def _save_to_json(self, data: Dict[str, Any], path: str) -> None:
        """Сохраняет данные в JSON файл"""
        export_config = self.config.get("render.export", {})
        indent = export_config.get("indent_size", 2) if export_config.get("pretty_print", True) else None
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        
        print(f"   ✓ Ground truth сохранен: {path}")