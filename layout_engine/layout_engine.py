# layout_engine.py

from typing import Dict, Any, List
from core.containers import Page
from core.primitives import DocumentElement
from .layout_result import LayoutResult
from .placement_engine import PlacementEngine, PlacedLine
from .content_loader import ContentLoader
from .template_manager import TemplateManager
from .column_strategy import ColumnStrategy
from utils.bbox_calculator import BBoxCalculator


class LayoutEngine:
    """Координатор верстки документа с универсальным PlacementEngine"""

    def __init__(
        self,
        template_config_path: str = "render/configs/layout_templates.yaml",
        font_path: str = None
    ):
        self.page_factory = lambda: self._create_new_page()
        self.template_manager = TemplateManager(template_config_path)
        self.bbox_calculator = BBoxCalculator(font_path=font_path)
        self.column_strategy = ColumnStrategy()
        self.placement_engine = PlacementEngine(
            bbox_calculator=self.bbox_calculator,
            page_factory=self.page_factory,
            column_strategy=self.column_strategy
        )

        self.layout_result = LayoutResult()
        self.current_page: Page = None
        self.current_template: Dict[str, Any] = None

    # ---------------------------
    # Основной метод верстки
    # ---------------------------

    def layout_document(
        self,
        json_path: str,
        template_name: str = "simple_article"
    ) -> LayoutResult:
        print(f"\nНачало верстки документа...")
        self.layout_result = LayoutResult()

        # Загружаем контент
        content_loader = ContentLoader()
        elements = content_loader.load_json(json_path)

        # Подготавливаем шаблон
        self.current_template = self.template_manager.get_template(template_name)

        # Создаем первую страницу
        self.current_page = self._create_page_from_template(self.current_template, 1)
        self.layout_result.add_page(self.current_page)
        self.placement_engine.setup_page(self.current_page)

        # Размещаем элементы
        self._place_elements(elements)

        # Формируем ground truth
        self.layout_result.prepare_ground_truth()

        print(f"Верстка завершена!")
        return self.layout_result

    # ---------------------------
    # Размещение элементов
    # ---------------------------

    def _place_elements(self, elements: List[Dict[str, Any]]):
        for idx, element_data in enumerate(elements, 1):
            elem_type = element_data.get("type", "text_line")
            placement_result = self.placement_engine.prepare_element(
                element_data,
                self.current_template.get("typography", {}),
                self.current_template.get("layout_type", "single_column")
            )

            if not placement_result.success:
                print(f"Элемент {idx}: {elem_type} не удалось разместить: {placement_result.message}")
                continue

            # --- основной элемент ---
            main_id = f"{elem_type}_{len(self.layout_result.elements)+1}"
            main_element = DocumentElement(
                id=main_id,
                type=elem_type,
                content=element_data.get("content", ""),
                bbox=placement_result.paragraph_bbox,
                dimensions={
                    "line_count": placement_result.line_count,
                    "total_height": placement_result.total_height,
                    "remaining_text": placement_result.remaining_text
                }
            )
            self.layout_result.add_element(main_element)

            # --- line_elements только для обычного текста ---
            if not elem_type.startswith("heading"):
                for line_index, placed_line in enumerate(placement_result.placed_lines):
                    line_element = DocumentElement(
                        id=f"{main_id}_line_{line_index+1}",
                        type=placed_line.element_type or "text_line",
                        content=placed_line.text,
                        bbox=placed_line.bbox,
                        dimensions={
                            "font_size": placed_line.font_size,
                            "font_family": placed_line.font_family,
                            "line_index": placed_line.line_index,
                            "paragraph_id": placed_line.paragraph_id,
                            "container_id": placed_line.container_id,
                            "page_number": placed_line.page_number
                        }
                    )
                    self.layout_result.add_element(line_element)
                    self._add_element_to_container(placed_line, line_element)


    def _add_element_to_container(self, placed_line: PlacedLine, element: DocumentElement):
        for page in self.layout_result.pages:
            for container in page.containers:
                if container.id == placed_line.container_id:
                    container.add_element(element)
                    return

    # ---------------------------
    # Создание страниц
    # ---------------------------

    def _create_page_from_template(self, template: Dict[str, Any], page_num: int) -> Page:
        base_settings = self.template_manager.get_base_settings()
        page_width = template.get("page_width", base_settings.get("page_width", 595.0))
        page_height = template.get("page_height", base_settings.get("page_height", 842.0))
        page = Page(number=page_num, width=page_width, height=page_height)

        layout_type = template.get("layout_type", "single_column")
        margins = template.get("margins", {"top": 50, "bottom": 50, "left": 50, "right": 50})

        if layout_type == "single_column":
            page.create_single_column(margins)
        elif layout_type == "two_column":
            gutter = template.get("columns", {}).get("gutter", 20)
            page.create_multi_column(num_columns=2, gutter=gutter, margins=margins)
        elif layout_type == "three_column":
            gutter = template.get("columns", {}).get("gutter", 15)
            page.create_multi_column(num_columns=3, gutter=gutter, margins=margins)
        else:
            page.create_single_column(margins)

        return page

    def _create_new_page(self) -> Page:
        new_page_num = len(self.layout_result.pages) + 1
        new_page = self._create_page_from_template(self.current_template, new_page_num)
        self.layout_result.add_page(new_page)
        self.placement_engine.setup_page(new_page)
        return new_page
