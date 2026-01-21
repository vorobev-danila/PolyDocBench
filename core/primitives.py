# primitives.py

from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class BBox:
    """Bounding Box с координатами"""
    x: float          # левая координата
    y: float          # нижняя координата
    width: float
    height: float
    page: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "page": self.page
        }


@dataclass
class DocumentElement:
    """Базовый класс для всех элементов документа"""
    id: str
    type: str  # "line", "heading", "image", "formula", "table"
    content: Any
    bbox: Optional[BBox] = None
    dimensions: Optional[Dict[str, Any]] = None
 