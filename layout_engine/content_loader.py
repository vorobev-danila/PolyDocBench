# content_loader.py

import json
from typing import Dict, Any, List


class ContentLoader:
    """Загрузчик контента из JSON файлов Wikipedia"""
    
    @staticmethod
    def load_json(json_path: str) -> List[Dict[str, Any]]:
        """Загружает и преобразует контент из Wikipedia JSON"""
        print(f"   Чтение файла: {json_path}")
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        elements = []
        
        # Проверяем структуру
        if "content" in data:
            # Wikipedia формат с вложенной структурой
            elements = ContentLoader._process_wikipedia_content(data["content"])
        else:
            # Простая структура
            elements = data.get("elements", data.get("content", []))
        
        print(f"   Загружено элементов: {len(elements)}")
        print(f"   Типы элементов: {ContentLoader._count_element_types(elements)}")
        
        return elements
    
    @staticmethod
    def _process_wikipedia_content(content_list: List[Dict[str, Any]], 
                                  parent_level: int = 0) -> List[Dict[str, Any]]:
        """Рекурсивно обрабатывает вложенную структуру Wikipedia контента"""
        elements = []
        
        for item in content_list:
            item_type = item.get("type", "")
            
            if item_type == "paragraph":
                elements.append({
                    "type": "paragraph",
                    "content": item.get("text", ""),
                    "metadata": {}
                })
            
            elif item_type == "heading":
                level = item.get("level", 1)
                # Преобразуем heading с уровнем в тип heading1, heading2 и т.д.
                element_type = f"heading{level}"
                
                # Добавляем сам заголовок
                elements.append({
                    "type": element_type,
                    "content": item.get("text", ""),
                    "metadata": {
                        "level": level,
                        "id": item.get("id", "")
                    }
                })
                
                # Рекурсивно обрабатываем вложенный контент
                if "content" in item and item["content"]:
                    nested_elements = ContentLoader._process_wikipedia_content(
                        item["content"], 
                        parent_level=level
                    )
                    elements.extend(nested_elements)
            
            # elif item_type == "hatnote":
            #     # Преобразуем hatnote в обычный текст с пометкой
            #     elements.append({
            #         "type": "paragraph",
            #         "content": item.get("text", ""),
            #         "metadata": {"is_hatnote": True}
            #     })
            
            # elif item_type == "image":
            #     # Пока пропускаем изображения, можно добавить позже
            #     elements.append({
            #         "type": "image",
            #         "content": item.get("caption", ""),
            #         "metadata": {
            #             "src": item.get("src", ""),
            #             "alt": item.get("alt", "")
            #         }
            #     })
            
            else:
                # Неизвестный тип, пробуем сохранить как параграф
                if "text" in item:
                    elements.append({
                        "type": "paragraph",
                        "content": item.get("text", ""),
                        "metadata": {"original_type": item_type}
                    })
        
        return elements
    
    @staticmethod
    def _count_element_types(elements: List[Dict[str, Any]]) -> Dict[str, int]:
        """Подсчитывает количество элементов по типам"""
        counts = {}
        
        for element in elements:
            elem_type = element.get("type", "unknown")
            counts[elem_type] = counts.get(elem_type, 0) + 1
        
        return counts
    
    @staticmethod
    def save_processed_content(elements: List[Dict[str, Any]], 
                              output_path: str) -> None:
        """Сохраняет обработанный контент для отладки"""
        import os
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "elements": elements,
                "metadata": {
                    "element_count": len(elements),
                    "types": ContentLoader._count_element_types(elements)
                }
            }, f, indent=2, ensure_ascii=False)
        
        print(f"   ✓ Обработанный контент сохранен: {output_path}")
        