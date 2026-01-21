# containers.py

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from .primitives import BBox, DocumentElement

@dataclass
class Container:
    id: str
    x: float # левая координата
    y: float # нижняя координата
    width: float
    height: float
    type: str = "single_column"
    elements: List[DocumentElement] = field(default_factory=list)
    page: int = 1

    cursor_y: float = field(init=False)

    def __post_init__(self):
        self.cursor_y = self.y + self.height
        self.elements = [] if self.elements is None else self.elements

    @property
    def available_height(self) -> float:
        return max(0.0, self.cursor_y - self.y)

    def can_fit(self, element_height: float) -> bool:
        return element_height <= self.available_height

    def place(self, element_height: float) -> Optional[BBox]:
        if not self.can_fit(element_height):
            return None

        bbox = BBox(
            x=self.x,
            y=self.cursor_y - element_height,
            width=self.width,
            height=element_height,
            page=self.page
        )

        # ЕДИНСТВЕННОЕ изменение состояния !!!!!!
        self.cursor_y -= element_height

        return bbox

    def add_element(self, element):
        self.elements.append(element)

    def reset(self):
        self.cursor_y = self.y + self.height
        self.elements.clear()


@dataclass
class Page:
    """Страница документа"""
    number: int
    width: float = 595.0   # A4 ширина в pts
    height: float = 842.0  # A4 высота в pts
    containers: List[Container] = field(default_factory=list)

    def add_container(self, container: Container):
        """Добавляет контейнер на страницу."""
        self.containers.append(container)

    def create_single_column(self, margins: Dict[str, float] = None) -> Container:
        """
        Создает одноколоночный layout на странице
        Args:
            margins: Поля страницы {top, bottom, left, right}
        Returns:
            Container: Созданный контейнер
        """
        if margins is None:
            margins = {"top": 50, "bottom": 50, "left": 50, "right": 50}
        
        container = Container(
            id="main_content",
            x=margins["left"],
            y=margins["bottom"],
            width=self.width - margins["left"] - margins["right"],
            height=self.height - margins["top"] - margins["bottom"],
            type="single_column",
            page=self.number
        )

        self.add_container(container)
        return container

    def create_multi_column(self, num_columns: int = 2, 
                           gutter: float = 20.0,
                           margins: Dict[str, float] = None) -> List[Container]:
        """
        Создает многоколоночный layout на странице
        Args:
            num_columns: Количество колонок (1, 2, 3)
            gutter: Расстояние между колонками
            margins: Поля страницы {top, bottom, left, right}
        Returns:
            List[Container]: Список созданных контейнеров-колонок
        """
        if margins is None:
            margins = {"top": 50, "bottom": 50, "left": 50, "right": 50}

        # Доступная ширина для контента
        content_width = self.width - margins["left"] - margins["right"]
        content_height = self.height - margins["top"] - margins["bottom"]

        # Ширина одной колонки с учетом промежутков
        column_width = (content_width - gutter * (num_columns - 1)) / num_columns

        containers = []

        for i in range(num_columns):
            column_x = margins["left"] + i * (column_width + gutter)
            
            container = Container(
                id=f"column_{i+1}",
                x=column_x,
                y=margins["bottom"],
                width=column_width,
                height=content_height,
                type=f"column_{num_columns}",
                page=self.number
            )

            containers.append(container)
            self.add_container(container)

        return containers
