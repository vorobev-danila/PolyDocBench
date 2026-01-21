"""
Простой скрипт запуска рендеринга документа
"""

import os
import sys
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from layout_engine.layout_engine import LayoutEngine
from render.pdf_renderer import PDFRenderer

def main():
    """Основной запуск pipeline"""
    config = {
        "json_path": "wiki_formulas_ru.json", # wiki_formulas_franch
        "template_name": "scientific_paper", # simple_article scientific_paper magazine_layout
        "font_path": "DejaVu Sans/DejaVuSans.ttf",
        "output_dir": "output",
        "debug_mode": True,
        "show_bboxes": True
    }

    # Проверяем файлы
    errors = []
    if not os.path.exists(config["json_path"]):
        errors.append(f"JSON файл не найден: {config['json_path']}")
    if config["font_path"] and not os.path.exists(config["font_path"]):
        errors.append(f"Файл шрифта не найден: {config['font_path']}")
        config["font_path"] = None
    
    if errors:
        for error in errors:
            print(f"⚠️ {error}")
        return {"success": False, "errors": errors}

    os.makedirs(config["output_dir"], exist_ok=True)

    try:
        # Инициализация layout engine
        layout_engine = LayoutEngine(
            template_config_path="render/configs/layout_templates.yaml",
            font_path=config["font_path"]
        )

        # Верстка документа
        layout_result = layout_engine.layout_document(
            json_path=config["json_path"],
            template_name=config["template_name"]
        )

        # Настройка renderer
        renderer = PDFRenderer(debug=config["debug_mode"])
        if not config["show_bboxes"]:
            renderer.config.set("render.debug.show_bboxes", False)

        # Выходные пути
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = os.path.join(config["output_dir"], f"document_{timestamp}.pdf")
        gt_path = os.path.join(config["output_dir"], f"document_{timestamp}_gt.json")

        # Рендеринг
        renderer.render(layout_result, pdf_path)

        # Краткая сводка
        print(f"PDF создан: {pdf_path}")
        print(f"Ground truth создан: {gt_path}")
        print(f"Страниц: {len(layout_result.pages)}, Элементов: {len(layout_result.elements)}")

        return {
            "success": True,
            "pdf_path": pdf_path,
            "gt_path": gt_path,
            "pages": len(layout_result.pages),
            "elements": len(layout_result.elements)
        }

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    result = main()
    if result.get("success"):
        print(f"✅ Рендеринг успешно завершен: {result['pdf_path']}")
    else:
        print(f"✗ Рендеринг не выполнен: {result.get('error', 'Неизвестная ошибка')}")
