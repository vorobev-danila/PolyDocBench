"""
Рендерер отладочной информации
"""

from typing import Dict, Any
from reportlab.pdfgen import canvas


class DebugRenderer:
    """Рендерер отладочной информации (Bounding Boxes)"""
    
    def __init__(self, canvas_obj: canvas.Canvas, config):
        self.canvas = canvas_obj
        self.config = config
    
    def render_bbox(self, element: Dict[str, Any], 
                   x: float, y: float, width: float, height: float) -> None:
        """Рисует bounding box для элемента"""
        debug_config = self.config.get("render.debug", {})
        
        if not debug_config.get("show_bboxes", True):
            return
        
        elem_type = element.get("type", "")
        color_map = self.config.get("render.colors.debug", {})
        
        # Цвета для разных типов элементов
        if elem_type in ["text", "paragraph"]:
            color_hex = color_map.get("text_bbox", "#FF0000")
        elif elem_type == "heading1":
            color_hex = color_map.get("heading_bbox", "#00FF00")
        elif elem_type == "heading2":
            color_hex = color_map.get("heading_bbox", "#00FF00")
        elif elem_type == "heading3":
            color_hex = color_map.get("heading_bbox", "#00FF00")
        elif elem_type == "heading4":
            color_hex = color_map.get("heading_bbox", "#00FF00")
        elif elem_type == "heading5":
            color_hex = color_map.get("heading_bbox", "#00FF00")
        elif elem_type == "heading6":
            color_hex = color_map.get("heading_bbox", "#00FF00")
        elif elem_type == "image":
            color_hex = color_map.get("image_bbox", "#0000FF")
        elif elem_type == "text_line":
            color_hex = color_map.get("table_bbox", "#800080")
        elif elem_type == "single_column":
            color_hex = color_map.get("container", "#FFA500")
        elif elem_type == "column_1":
            color_hex = color_map.get("container", "#FFA500")
        elif elem_type == "column_2":
            color_hex = color_map.get("container", "#FFA500")
        elif elem_type == "column_3":
            color_hex = color_map.get("container", "#FFA500")
        else:
            color_hex = "#888888"
        
        # Конвертируем hex в RGB
        if color_hex.startswith("#"):
            r = int(color_hex[1:3], 16) / 255.0
            g = int(color_hex[3:5], 16) / 255.0
            b = int(color_hex[5:7], 16) / 255.0
        else:
            r, g, b = 1.0, 0.0, 0.0
        
        alpha = debug_config.get("bbox_alpha", 0.3)
        line_width = debug_config.get("bbox_line_width", 0.8)
        
        # Устанавливаем цвет и толщину
        self.canvas.setStrokeColorRGB(r, g, b, alpha=alpha)
        self.canvas.setLineWidth(line_width)
        
        # Рисуем прямоугольник
        self.canvas.rect(x, y, width, height, stroke=1, fill=0)
        
        # Подпись с ID элемента
        if debug_config.get("show_ids", False):
            self.canvas.setFont("Helvetica", 6)
            self.canvas.setFillColorRGB(r, g, b, alpha=0.8)
            element_id = element.get("id", "unknown")
            self.canvas.drawString(x + 2, y + height - 8, f"ID: {element_id}")
    
    def render_line_debug(self, element: Dict[str, Any], lines: list, 
                         x: float, y: float, line_height: float, font_size: float) -> None:
        """Рисует отладочную информацию о строках текста"""
        debug_config = self.config.get("render.debug", {})
        
        if not debug_config.get("show_line_debug", False):
            return
        
        width = element.get("bbox", {}).get("width", 0)
        
        self.canvas.setStrokeColorRGB(0, 0, 1, alpha=0.2)
        self.canvas.setLineWidth(0.3)
        
        # Рисуем линии для каждой строки
        for i in range(len(lines) + 1):
            line_y = y + (line_height * i)
            self.canvas.line(x, line_y, x + width, line_y)
            
            # Подписываем номер строки
            if i < len(lines):
                self.canvas.setFont("Helvetica", 6)
                self.canvas.setFillColorRGB(0, 0, 1, alpha=0.5)
                self.canvas.drawString(x + 5, line_y - 10, f"строка {i+1}")