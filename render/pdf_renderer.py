"""
PDFRenderer v2 — современный, line-based, чистый
"""

import os
from datetime import datetime
from typing import Dict, Any
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from .config import RenderConfig
from .font_manager import FontManager
from .debug_renderer import DebugRenderer
from .ground_truth_exporter import GroundTruthExporter
from .element_renderers.text import TextRenderer
from .element_renderers.heading import HeadingRenderer


class PDFRenderer:
    """Универсальный координатор рендеринга PDF"""

    def __init__(self, config_path: str = None, debug: bool = True):
        # Конфигурация
        self.config = RenderConfig(config_path)
        self.debug_mode = debug

        # Font manager
        self.font_manager = FontManager(self.config)
        self.font_manager.register_fonts()

        # Ground truth
        self.gt_exporter = GroundTruthExporter(self.config)

        # Реестр рендереров элементов
        self.renderer_registry = {
            "text": TextRenderer,
            "text_line": TextRenderer,
            "paragraph": TextRenderer,  # legacy, можно убрать после миграции
            "heading1": HeadingRenderer,
            "heading2": HeadingRenderer,
            "heading3": HeadingRenderer,
            "heading4": HeadingRenderer,
            "heading5": HeadingRenderer,
            "heading6": HeadingRenderer,
            # новые типы добавлять сюда
        }

        # Состояние
        self.current_page = 1
        self.debug_renderer = None  # создается при render

    # ------------------------------------------------------------------
    # Основной метод рендеринга
    # ------------------------------------------------------------------
    def render(self, layout_result, output_pdf: str = "output/output.pdf") -> Dict[str, Any]:
        """Рендерит LayoutResult в PDF и сохраняет ground truth"""
        if not layout_result or not hasattr(layout_result, "to_dict"):
            raise ValueError("layout_result должен быть экземпляром LayoutResult")

        # Подготовка
        layout_dict = layout_result.to_dict()
        os.makedirs(os.path.dirname(output_pdf), exist_ok=True)

        # Создаем canvas
        c = canvas.Canvas(output_pdf, pagesize=A4)

        # Устанавливаем метаданные документа
        self._set_metadata(c)

        # Создаем debug renderer
        if self.debug_mode:
            self.debug_renderer = DebugRenderer(c, self.config)

        # Группируем элементы по страницам
        elements_by_page = self._group_elements_by_page(layout_dict)

        # Рендерим страницы
        for page_num in sorted(elements_by_page.keys()):
            if page_num > 1:
                c.showPage()
            self.current_page = page_num

            for element in elements_by_page[page_num]:
                self._render_element(c, element)

        # Сохраняем PDF
        c.save()

        # Ground truth
        gt_path = output_pdf.replace(".pdf", "_gt.json")
        self.gt_exporter.export(layout_result, gt_path)

        return {
            "pdf_path": output_pdf,
            "gt_path": gt_path,
            "page_count": len(elements_by_page),
            "element_count": sum(len(v) for v in elements_by_page.values()),
            "render_time": datetime.now().isoformat()
        }

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------
    def _get_renderer(self, element_type: str, canvas_obj: canvas.Canvas):
        """Возвращает рендерер для типа элемента"""
        cls = self.renderer_registry.get(element_type)
        if not cls:
            cls = TextRenderer
        return cls(canvas_obj, self.config, self.font_manager)

    def _render_element(self, canvas_obj: canvas.Canvas, element: Dict[str, Any]) -> None:
        """Рендерит один элемент с debug"""
        try:
            bbox = element.get("bbox", {})
            page_num = bbox.get("page", 1)
            if page_num != self.current_page:
                return

            # Рендерим элемент
            renderer = self._get_renderer(element.get("type", "text"), canvas_obj)
            renderer.render(element)

            # Debug
            if self.debug_mode and self.debug_renderer and bbox:
                self.debug_renderer.render_bbox(
                    element,
                    bbox.get("x", 0),
                    bbox.get("y", 0),
                    bbox.get("width", 0),
                    bbox.get("height", 0)
                )
        except Exception as e:
            print(f"⚠️ Ошибка рендеринга элемента {element.get('id', 'unknown')}: {e}")

    def _group_elements_by_page(self, layout_dict: Dict[str, Any]) -> Dict[int, list]:
        """Группирует элементы по страницам"""
        elements_by_page = {}
        for element in layout_dict.get("elements", []):
            page = element.get("bbox", {}).get("page", 1)
            elements_by_page.setdefault(page, []).append(element)
        return elements_by_page

    def _set_metadata(self, c: canvas.Canvas) -> None:
        """Устанавливает метаданные PDF"""
        try:
            md = self.config.get("render.pdf.metadata", {})
            c.setTitle(md.get("title", "PolyDocBench PDF"))
            c.setAuthor(md.get("author", "PolyDocBench Generator"))
            c.setSubject(md.get("subject", "Synthetic OCR benchmark"))
            c.setCreator(md.get("creator", "PolyDocBench"))
            c.setProducer(md.get("producer", "PolyDocBench"))
            c.setKeywords(md.get("keywords", "OCR, document, GT"))
        except Exception as e:
            print(f"⚠️ Ошибка установки метаданных: {e}")


# ------------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------------
def render_layout_result(layout_result, output_pdf: str = "output/output.pdf"):
    """Адаптер для совместимости"""
    renderer = PDFRenderer()
    return renderer.render(layout_result, output_pdf)


def create_simple_pdf(text: str, output_path: str = "output/simple.pdf"):
    """Простой PDF для теста"""
    from .element_renderers.text import TextRenderer
    renderer = PDFRenderer()

    layout_dict = {
        "pages": [{"page_number": 1, "width": 595, "height": 842, "containers": []}],
        "elements": [{
            "id": "test_1",
            "type": "text_line",
            "content": text,
            "bbox": {"x": 50, "y": 700, "width": 495, "height": 50, "page": 1},
            "dimensions": {"font_size": 12, "font_name": "Helvetica"}
        }]
    }

    from layout_engine.layout_result import LayoutResult  # если хочешь использовать LayoutResult
    # Для быстрого теста можно обернуть dict в LayoutResult с методом to_dict()
    class DummyLayoutResult:
        def to_dict(self):
            return layout_dict
        ground_truth = {}

    dummy_result = DummyLayoutResult()
    return renderer.render(dummy_result, output_path)
