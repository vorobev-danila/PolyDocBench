"""
Базовый класс для рендереров элементов
"""

from typing import Dict, Any, Tuple
from reportlab.pdfgen import canvas


class BaseElementRenderer:
    """Базовый рендерер элементов"""
    
    def __init__(self, canvas_obj: canvas.Canvas, config, font_manager):
        self.canvas = canvas_obj
        self.config = config
        self.font_manager = font_manager
    
    def render(self, element: Dict[str, Any]) -> None:
        """Рендерит элемент (должен быть реализован в подклассах)"""
        raise NotImplementedError("Метод render должен быть реализован в подклассе")
    
    def _get_bbox_coords(self, element: Dict[str, Any]) -> Tuple[float, float, float, float]:
        """Извлекает координаты bounding box из элемента"""
        bbox = element.get("bbox", {})
        x = bbox.get("x", 0)
        y = bbox.get("y", 0)
        width = bbox.get("width", 0)
        height = bbox.get("height", 0)
        return x, y, width, height