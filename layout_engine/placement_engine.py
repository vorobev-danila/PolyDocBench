# placement_engine.py

from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from core.containers import Page, Container
from core.primitives import BBox
from utils.bbox_calculator import BBoxCalculator, TextLineInfo
from .column_strategy import ColumnStrategy


class PlacementStatus(Enum):
    PLACED = "placed"
    NEED_NEW_COLUMN = "need_new_column"
    NEED_NEW_PAGE = "need_new_page"
    TOO_LARGE = "too_large"


@dataclass
class PlacedLine:
    """Информация о размещенном элементе (строка, изображение, формула)"""
    text: str
    bbox: BBox
    font_size: float
    font_family: str
    is_first_line: bool
    container_id: str
    page_number: int
    line_index: int
    paragraph_id: Optional[str] = None
    element_type: Optional[str] = None


@dataclass
class PlacementResult:
    success: bool
    placed_lines: List[PlacedLine] = field(default_factory=list)
    remaining_text: Optional[str] = None
    paragraph_bbox: Optional[BBox] = None
    total_height: float = 0.0
    column_index: Optional[int] = None
    message: str = ""

    @property
    def line_count(self) -> int:
        return len(self.placed_lines)

    def add_line(self, line: PlacedLine):
        self.placed_lines.append(line)
        self.total_height += line.bbox.height


class PlacementEngine:
    """
    Универсальный движок размещения элементов документа:
    текст, заголовки, строки, изображения, формулы, таблицы.
    """

    def __init__(
        self,
        bbox_calculator: BBoxCalculator,
        page_factory: Optional[Callable[[], Page]] = None,
        column_strategy: Optional[ColumnStrategy] = None
    ):
        self.bbox_calculator = bbox_calculator
        self.page_factory = page_factory
        self.column_strategy = column_strategy

        self.all_containers: List[Container] = []
        self.current_container: Optional[Container] = None
        self.current_column_index: int = 0
        self.current_page_number: int = 1

        self.debug_log: List[str] = []

    # ---------------------------
    # Настройка страниц и контейнеров
    # ---------------------------

    def setup_page(self, page: Page):
        self.current_page_number = page.number
        self.setup_containers(page.containers)
        self.debug_log.append(f"Setup page {page.number}")

    def setup_containers(self, containers: List[Container]):
        self.all_containers = containers
        for container in containers:
            container.reset()

        # ВСЕГДА начинаем с ПЕРВОЙ колонки на новой странице
        self.current_column_index = 0
        self.current_container = containers[0] if containers else None
        
        # Обновляем стратегию
        if self.column_strategy and containers:
            self.column_strategy.current_column_index = 0
        
        self.debug_log.append(f"Setup {len(containers)} containers, starting at column 0")

    # ---------------------------
    # Универсальный метод размещения
    # ---------------------------

    def prepare_element(
        self,
        element_data: Dict[str, Any],
        typography: Dict[str, Any],
        layout_type: str = "single_column"
    ) -> PlacementResult:
        element_type = element_data.get("type", "text_line")
        handler = self._get_handler(element_type)
        return handler(element_data, typography, layout_type)

    def _get_handler(self, element_type: str):
        handlers = {
            "paragraph": self._place_text_element,
            "text": self._place_text_element,
            "heading1": self._place_heading_element,
            "heading2": self._place_heading_element,
            "heading3": self._place_heading_element,
            "heading4": self._place_heading_element,
            "heading5": self._place_heading_element,
            "text_line": self._place_text_line,
            "image": self._place_graphic_element,
            "formula": self._place_graphic_element,
            "table": self._place_graphic_element,
        }
        return handlers.get(element_type, self._place_text_element)

    # ---------------------------
    # Размещение текстовых элементов
    # ---------------------------

    def _place_text_element(self, element_data, typography, layout_type):
        text = element_data.get("content", "")
        font_size = typography.get("body_size", 10)
        line_height_ratio = typography.get("line_height", 1.2)
        first_line_indent = typography.get("first_line_indent", 20)
        paragraph_spacing = typography.get("paragraph_spacing", 10)

        para_id = f"para_{id(element_data)}"
        result = PlacementResult(success=False)

        
        if not self.current_container:
            result.message = "No container available"
            return result

        lines_info: List[TextLineInfo] = self.bbox_calculator.split_into_lines(
            text=text,
            max_width=self.current_container.width,
            font_size=font_size,
            line_height_ratio=line_height_ratio,
            first_line_indent=first_line_indent
        )

        if not lines_info:
            result.message = "No lines generated"
            return result

        # Размещаем строки по контейнерам/страницам
        lines_to_place = lines_info.copy()
        while lines_to_place:
            line_info = lines_to_place[0]
            status = self._try_place_line(line_info)
            
            if status == PlacementStatus.PLACED:
                placed_line = self._create_placed_line(line_info, len(result.placed_lines), para_id, "text_line")
                result.add_line(placed_line)
                lines_to_place.pop(0)
                
            elif status == PlacementStatus.NEED_NEW_COLUMN:
                # Пытаемся переключиться на следующую колонку
                if self._try_switch_column():
                    # УСПЕШНО: переключились, продолжаем со следующей строкой
                    continue
                else:
                    # Не удалось переключиться на другую колонку - нужна новая страница
                    if not self._create_new_page():
                        result.message = "Cannot create new page for remaining lines"
                        break
                    
            elif status == PlacementStatus.NEED_NEW_PAGE:
                if not self._create_new_page():
                    result.message = "Cannot create new page"
                    break
                    
            else:
                result.message = f"Line too tall: {line_info.height:.1f}pt"
                break

        # Итоговый BBox параграфа
        if result.placed_lines:
            result.success = True
            result.paragraph_bbox = self._calculate_paragraph_bbox(result.placed_lines)
            
            # Добавляем отступ после параграфа
            if self.current_container and paragraph_spacing > 0:
                # Проверяем, помещается ли отступ
                if self.current_container.can_fit(paragraph_spacing):
                    self.current_container.place(paragraph_spacing)
                else:
                    # Если не помещается - переходим на следующую колонку/страницу
                    pass

        return result
    
    # Переписываем _try_switch_column для последовательного потока:
    def _try_switch_column(self) -> bool:
        """
        Переключается на следующую колонку справа.
        Возвращает True если переключились, False если это последняя колонка.
        """
        if not self.all_containers or len(self.all_containers) <= 1:
            return False
        
        # Пытаемся перейти на следующую колонку
        next_index = self.current_column_index + 1
        
        if next_index < len(self.all_containers):
            # Переключаемся на следующую колонку
            self.current_column_index = next_index
            self.current_container = self.all_containers[next_index]
            
            # Обновляем стратегию если есть
            if self.column_strategy:
                self.column_strategy.current_column_index = next_index
            
            self.debug_log.append(f"Switched to next column: {next_index}")
            return True
        else:
            # Это последняя колонка на странице
            self.debug_log.append("Last column reached, need new page")
            return False
    
    def _create_new_page(self) -> bool:
        """Создает новую страницу и сбрасывает на первую колонку"""
        if not self.page_factory:
            return False
        
        new_page = self.page_factory()
        self.setup_page(new_page)
        
        # Сбрасываем на первую колонку новой страницы
        if self.column_strategy:
            self.column_strategy.reset_for_new_page(new_page.number)
        
        return True

    def _place_text_line(self, element_data, typography, layout_type):
        # Обертка для одиночной строки
        return self._place_text_element(element_data, typography, layout_type)

    def _place_heading_element(self, element_data, typography, layout_type):
        # Заголовки размещаем как блок (одна строка)
        text = element_data.get("content", "")
        font_size = typography.get("heading_size", 14)
        line_height = font_size * 1.2

        result = PlacementResult(success=False)
        if not self.current_container:
            result.message = "No container"
            return result

        if self.current_container.can_fit(line_height):
            bbox = self.current_container.place(line_height)
            placed_line = PlacedLine(
                text=text,
                bbox=bbox,
                font_size=font_size,
                font_family="",
                is_first_line=True,
                container_id=self.current_container.id,
                page_number=self.current_page_number,
                line_index=0,
                element_type="heading"
            )
            result.add_line(placed_line)
            result.success = True
            result.paragraph_bbox = bbox
        else:
            result.message = "Heading too large"

        return result

    # ---------------------------
    # Размещение графики (image, formula, table)
    # ---------------------------

    def _place_graphic_element(self, element_data, typography, layout_type):
        width = element_data.get("width", 100)
        height = element_data.get("height", 100)

        result = PlacementResult(success=False)
        if not self.current_container:
            result.message = "No container"
            return result

        if self.current_container.can_fit(height):
            bbox = self.current_container.place(height)
            placed_line = PlacedLine(
                text="",
                bbox=bbox,
                font_size=0,
                font_family="",
                is_first_line=True,
                container_id=self.current_container.id,
                page_number=self.current_page_number,
                line_index=0,
                element_type=element_data.get("type")
            )
            result.add_line(placed_line)
            result.success = True
            result.paragraph_bbox = bbox
        else:
            if self._try_switch_column() or self._create_new_page():
                return self._place_graphic_element(element_data, typography, layout_type)
            else:
                result.message = "Element too large"

        return result

    # ---------------------------
    # Низкоуровневая логика
    # ---------------------------

    def _try_place_line(self, line_info: TextLineInfo) -> PlacementStatus:
        if not self.current_container:
            return PlacementStatus.TOO_LARGE

        if self.current_container.can_fit(line_info.height):
            return PlacementStatus.PLACED
        else:
            # Не помещается в текущую колонку
            if len(self.all_containers) > 1:
                # Есть другие колонки - пытаемся переключиться
                return PlacementStatus.NEED_NEW_COLUMN
            elif self.page_factory:
                # Одна колонка - нужна новая страница
                return PlacementStatus.NEED_NEW_PAGE
            else:
                return PlacementStatus.TOO_LARGE

    def _create_placed_line(self, line_info, line_index, paragraph_id, element_type):
        bbox = self.current_container.place(line_info.height)
        if bbox is None:
            raise RuntimeError("Failed to place line")

        indent = getattr(line_info, "indent", 0)
        bbox.x += indent
        bbox.width = getattr(line_info, "width", bbox.width)

        return PlacedLine(
            text=getattr(line_info, "text", ""),
            bbox=bbox,
            font_size=getattr(line_info, "font_size", 0),
            font_family=getattr(line_info, "font_family", ""),
            is_first_line=getattr(line_info, "is_first_line", True),
            container_id=self.current_container.id,
            page_number=self.current_page_number,
            line_index=line_index,
            paragraph_id=paragraph_id,
            element_type=element_type
        )

    def _calculate_paragraph_bbox(self, placed_lines: List[PlacedLine]) -> Optional[BBox]:
        if not placed_lines:
            return None
        min_x = min(line.bbox.x for line in placed_lines)
        min_y = min(line.bbox.y for line in placed_lines)
        max_x = max(line.bbox.x + line.bbox.width for line in placed_lines)
        max_y = max(line.bbox.y + line.bbox.height for line in placed_lines)
        page = placed_lines[0].bbox.page
        return BBox(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y, page=page)


    # ---------------------------
    # Отладка
    # ---------------------------

    def get_debug_log(self) -> List[str]:
        return self.debug_log.copy()

    def clear_debug_log(self):
        self.debug_log.clear()
