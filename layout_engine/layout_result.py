# layout_result.py

from dataclasses import dataclass, field
from typing import Dict, Any, List
from datetime import datetime

from core.containers import Page, Container
from core.primitives import DocumentElement

@dataclass
class LayoutResult:
    """Результат работы Layout Engine"""
    pages: List[Page] = field(default_factory=list)
    elements: List[DocumentElement] = field(default_factory=list)
    ground_truth: Dict[str, Any] = field(default_factory=dict)

    def add_page(self, page: Page):
        self.pages.append(page)

    def add_element(self, element: DocumentElement):
        self.elements.append(element)

    def prepare_ground_truth(self, generator_name: str = "PolyDocBench"):
        """Подготавливает ground truth данные"""
        pages_gt = []
        for page in self.pages:
            page_info = {
                "page_number": page.number,
                "width": page.width,
                "height": page.height,
                "containers": []
            }

            for container in page.containers:
                container_info = {
                    "id": container.id,
                    "type": container.type,
                    "bbox": {
                        "x": container.x,
                        "y": container.y,
                        "width": container.width,
                        "height": container.height,
                        "page": page.number
                    },
                    "element_count": len(container.elements),
                    "available_height": container.available_height,
                    "elements": [
                        {
                            "id": e.id,
                            "type": e.type,
                            "content": e.content,
                            "bbox": e.bbox.as_dict() if e.bbox else None,
                            "dimensions": e.dimensions
                        }
                        for e in getattr(container, "elements", [])
                    ]
                }
                page_info["containers"].append(container_info)

            pages_gt.append(page_info)
        
        self.ground_truth = {
            "metadata": {
                "generator": generator_name,
                "version": "1.0",
                "page_count": len(self.pages),
                "element_count": len(self.elements),
                "timestamp": datetime.now().isoformat()
            },
            "pages": pages_gt,
            "elements": [
                {
                    "id": e.id,
                    "type": e.type,
                    "content": e.content,
                    "bbox": e.bbox.as_dict() if e.bbox else None,
                    "dimensions": e.dimensions
                }
                for e in self.elements
            ]
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует результат в словарь (полная структура с элементами в контейнерах)"""
        return {
            "pages": [
                {
                    "number": page.number,
                    "width": page.width,
                    "height": page.height,
                    "containers": [
                        {
                            "id": c.id,
                            "type": c.type,
                            "x": c.x,
                            "y": c.y,
                            "width": c.width,
                            "height": c.height,
                            "elements": [
                                {
                                    "id": e.id,
                                    "type": e.type,
                                    "content": e.content,
                                    "bbox": e.bbox.as_dict() if e.bbox else None,
                                    "dimensions": e.dimensions
                                }
                                for e in getattr(c, "elements", [])
                            ]
                        }
                        for c in page.containers
                    ]
                }
                for page in self.pages
            ],
            "elements": [
                {
                    "id": e.id,
                    "type": e.type,
                    "content": e.content,
                    "bbox": e.bbox.as_dict() if e.bbox else None,
                    "dimensions": e.dimensions
                }
                for e in self.elements
            ]
        }
