import requests
from bs4 import BeautifulSoup
import json
import re
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urljoin

class WikiParser:
    def __init__(self, debug=False):
        self.soup = None
        self.debug = debug
        
    def _debug(self, message):
        if self.debug:
            print(f"DEBUG: {message}")
        
    def parse_from_url(self, url: str) -> Dict[str, Any]:
        """Парсинг страницы Википедии по URL"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return self.parse_html(response.text, url)
        except requests.RequestException as e:
            return {"error": f"Ошибка загрузки страницы: {str(e)}"}
    
    def parse_from_file(self, file_path: str, url: str = "") -> Dict[str, Any]:
        """Парсинг страницы Википедии из HTML-файла"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                html_content = file.read()
            return self.parse_html(html_content, url)
        except Exception as e:
            return {"error": f"Ошибка чтения файла: {str(e)}"}
    
    def parse_html(self, html_content: str, url: str = "") -> Dict[str, Any]:
        """Основной метод парсинга HTML"""
        self.soup = BeautifulSoup(html_content, 'html.parser')
        
        # Извлекаем заголовок страницы
        title = self._extract_title()
        
        # Находим основной контейнер с контентом
        content_div = self.soup.find("div", class_="mw-parser-output")
        if not content_div:
            return {"error": "Не найден основной контейнер с контентом"}
        
        self._debug(f"Найден контейнер mw-parser-output, начинаем парсинг...")
        
        # Инициализируем структуру документа
        doc = {
            "title": title,
            "url": url,
            "content": []
        }
        
        # Используем метод последовательного обхода DOM
        return self._parse_by_dom_traversal(content_div, doc)
    
    def _parse_by_dom_traversal(self, content_div, doc):
        """Метод последовательного обхода DOM для поиска заголовков и контента"""
        self._debug("=== ПОСЛЕДОВАТЕЛЬНЫЙ ОБХОД DOM ===")
        
        # Находим ВСЕ элементы, которые могут быть заголовками или контентами
        all_candidates = content_div.find_all([
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 
            'table', 'div', 'figure', 'dl', 'dd'
        ])
        
        # Фильтруем только релевантные элементы
        relevant_elements = []
        for element in all_candidates:
            # Пропускаем элементы, которые не находятся в основном потоке контента
            if not self._is_content_element(element):
                continue
            
            # Проверяем, является ли элемент заголовком
            is_heading = bool(self._extract_heading_info(element))
            
            # ФИЛЬТР: если это h-тег внутри mw-heading div, пропускаем его
            if (element.name and element.name.startswith('h') and 
                element.parent and element.parent.name == 'div' and
                element.parent.get('class') and 
                any('mw-heading' in cls for cls in element.parent.get('class', []))):
                self._debug(f"Пропущен дублирующий h-тег внутри mw-heading: {element.name}")
                continue
                
            element_type = self._get_element_type_name(element)
            
            relevant_elements.append({
                'element': element,
                'is_heading': is_heading,
                'type': element_type
            })
        
        self._debug(f"Найдено релевантных элементов: {len(relevant_elements)}")
        
        # Строим иерархию
        return self._build_hierarchy_from_elements(relevant_elements, doc)
    
    def _is_content_element(self, element):
        """Проверяет, является ли элемент частью основного контента"""
        # Пропускаем технические элементы
        if element.name in ['style', 'link', 'script', 'meta']:
            return False
        
        # ВКЛЮЧАЕМ блоки dl и dd для обработки формул
        if element.name in ['dl', 'dd']:
            return True
        
        # Пропускаем элементы с определенными классами
        skip_classes = ['mw-empty-elt', 'mw-editsection', 'navbox', 'infobox', 'reference']
        element_classes = element.get('class', [])
        if any(skip_cls in element_classes for skip_cls in skip_classes if isinstance(skip_cls, str)):
            return False
        
        # Пропускаем полностью пустые параграфы
        if element.name == 'p' and not element.get_text(strip=True):
            return False
        
        return True
    
    def _get_element_type_name(self, element):
        """Возвращает читаемое имя типа элемента"""
        if element.name.startswith('h'):
            return f"heading_{element.name}"
        elif element.name == 'p':
            return "paragraph"
        elif element.name in ['ul', 'ol']:
            return "list"
        elif element.name == 'table':
            return "table"
        elif element.name == 'figure':
            return "figure"
        elif element.name == 'dl':
            return "definition_list"
        elif element.name == 'dd':
            return "definition_description"
        elif element.name == 'div':
            if 'thumb' in element.get('class', []):
                return "thumbnail"
            elif 'hatnote' in element.get('class', []):
                return "hatnote"
            elif 'mw-heading' in str(element.get('class', [])):
                return "mw_heading"
            else:
                return "div"
        else:
            return element.name
    
    

    def _build_hierarchy_from_elements(self, elements, doc):
        """Строит иерархию из списка элементов"""
        self._debug("=== ПОСТРОЕНИЕ ИЕРАРХИИ ИЗ ЭЛЕМЕНТОВ ===")
        
        result_content = []
        stack = [{'node': {'type': 'root', 'content': result_content}, 'level': 0}]
        current_section_content = []
        
        # Отслеживаем последний обработанный заголовок, чтобы избежать дублирования
        last_heading_text = None
        
        for item in elements:
            element = item['element']
            
            if item['is_heading']:
                # Это заголовок - создаем новую секцию
                heading_info = self._extract_heading_info(element)
                if not heading_info:
                    continue
                    
                level, text, element_id = heading_info
                
                # ПРОВЕРКА НА ДУБЛИРОВАНИЕ: пропускаем, если это тот же заголовок
                if text == last_heading_text:
                    self._debug(f"Пропущен дублирующий заголовок: '{text}'")
                    continue
                    
                last_heading_text = text
                
                # Создаем узел для предыдущей секции, если есть контент
                if current_section_content and stack:
                    current_parent = stack[-1]['node']
                    if 'content' not in current_parent:
                        current_parent['content'] = []
                    current_parent['content'].extend(current_section_content)
                    current_section_content = []
                
                # Создаем новый узел заголовка
                heading_node = {
                    "type": "heading",
                    "level": level,
                    "text": text,
                    "id": element_id,
                    "content": []
                }
                
                # Находим правильного родителя
                while len(stack) > 1 and stack[-1]['level'] >= level:
                    stack.pop()
                
                # Добавляем заголовок к текущему родителю
                current_parent = stack[-1]['node']
                if 'content' not in current_parent:
                    current_parent['content'] = []
                current_parent['content'].append(heading_node)
                
                # Добавляем в стек как нового родителя
                stack.append({'node': heading_node, 'level': level})
                
                self._debug(f"Создан заголовок H{level}: '{text}'")
                
            else:
                # Это контент - добавляем к текущей секции
                content_item = self._parse_content_element(element)
                if content_item:
                    # Если это формула - добавляем напрямую
                    if content_item.get('type') == 'formula':
                        current_section_content.append(content_item)
                        self._debug(f"Добавлена формула: {content_item.get('latex', '')[:30]}...")
                    else:
                        # Обычный контент
                        current_section_content.append(content_item)
                        self._debug(f"Добавлен контент: {content_item['type']}")
        
        # Добавляем оставшийся контент
        if current_section_content and stack:
            current_parent = stack[-1]['node']
            if 'content' not in current_parent:
                current_parent['content'] = []
            current_parent['content'].extend(current_section_content)
        
        doc['content'] = result_content
        return doc
    
    def _parse_math_element(self, element) -> Optional[Dict[str, Any]]:
        """Парсит математические элементы"""
        if not element.name:
            return None
        
        math_data = {}
        
        # СЛУЧАЙ 1: span с классом mwe-math-element (основной контейнер)
        if (element.name == 'span' and 
            'mwe-math-element' in element.get('class', [])):
            
            # Ищем MathML (семантическая разметка)
            mathml_elem = element.find('span', class_='mwe-math-mathml-inline')
            if mathml_elem:
                math_tag = mathml_elem.find('math')
                if math_tag:
                    # Очищаем MathML от лишних пробелов
                    mathml_str = re.sub(r'>\s+<', '><', str(math_tag).strip())
                    math_data['mathml'] = mathml_str
                    
                    # Извлекаем LaTeX из annotation
                    annotation = math_tag.find('annotation', encoding='application/x-tex')
                    if annotation:
                        latex_text = annotation.get_text(strip=True)
                        # Убираем обрамляющие displaystyle если есть
                        latex_text = re.sub(r'^{\\displaystyle\s*', '', latex_text)
                        latex_text = re.sub(r'\s*}$', '', latex_text)
                        math_data['latex'] = latex_text
            
            # Ищем изображение формулы (fallback)
            img_elem = element.find('img', class_='mwe-math-fallback-image-inline')
            if img_elem:
                src = img_elem.get('src', '')
                if src:
                    if not src.startswith(('http:', 'https:')):
                        src = urljoin('https://wikimedia.org', src)
                    math_data['image_src'] = src
                    math_data['alt_text'] = img_elem.get('alt', '')
            
            # Извлекаем alttext из MathML
            if 'mathml' in math_data:
                mathml_soup = BeautifulSoup(math_data['mathml'], 'html.parser')
                math_tag = mathml_soup.find('math')
                if math_tag:
                    math_data['alttext'] = math_tag.get('alttext', '')
        
        # СЛУЧАЙ 2: Прямой тег <math> (редко, но бывает)
        elif element.name == 'math':
            mathml_str = re.sub(r'>\s+<', '><', str(element).strip())
            math_data['mathml'] = mathml_str
            math_data['alttext'] = element.get('alttext', '')
            annotation = element.find('annotation', encoding='application/x-tex')
            if annotation:
                latex_text = annotation.get_text(strip=True)
                latex_text = re.sub(r'^{\\displaystyle\s*', '', latex_text)
                latex_text = re.sub(r'\s*}$', '', latex_text)
                math_data['latex'] = latex_text
        
        # Если нашли какие-то данные формулы
        if math_data:
            # Определяем тип формулы (inline/display)
            classes = element.get('class', [])
            parent_classes = element.parent.get('class', []) if element.parent else []
            all_classes = classes + parent_classes
            
            math_type = 'display' if any('display' in str(cls) for cls in all_classes) else 'inline'
            
            # ТОЛЬКО нужные поля
            return {
                "type": "formula",
                "formula_type": math_type,
                "mathml": math_data.get('mathml'),
                "latex": math_data.get('latex'),
                "image_src": math_data.get('image_src'),
                "alt_text": math_data.get('alt_text'),
                "alttext": math_data.get('alttext')
            }
        
        return None
    
    def _parse_content_element(self, element) -> Optional[Dict[str, Any]]:
        """Парсит отдельный элемент контента"""
        if not element.name:
            return None
            
        if element.name == "p":
            # Парсим параграф БЕЗ извлечения формул
            text = element.get_text(strip=True)
            if text:
                return {
                    "type": "paragraph",
                    "text": text
                }
                
        elif element.name == "dd":
            # ОСОБАЯ ОБРАБОТКА для блоков dd - извлекаем только ПЕРВУЮ формулу
            formula_elements = self._find_all_formulas_in_element(element)
            
            for formula_element in formula_elements:
                formula_data = self._parse_math_element(formula_element)
                if formula_data:
                    # Возвращаем только ПЕРВУЮ найденную формулу
                    return formula_data
            
            # Если формул нет, но есть текст - создаем paragraph
            text = element.get_text(strip=True)
            if text:
                return {
                    "type": "paragraph", 
                    "text": text
                }
                
        elif element.name == "dl":
            # Блок определения - пропускаем, так как формулы уже извлечены из dd
            return None
                
        elif element.name in ["ul", "ol"]:
            items = []
            for li in element.find_all("li", recursive=False):
                item_text = li.get_text(strip=True)
                if item_text:
                    items.append({"text": item_text})
            if items:
                return {
                    "type": "list",
                    "list_type": "ordered" if element.name == "ol" else "unordered",
                    "items": items
                }
                
        elif element.name == "table":
            rows = []
            for tr in element.find_all("tr"):
                row = []
                for td in tr.find_all(["td", "th"]):
                    cell_text = td.get_text(strip=True)
                    if cell_text:
                        row.append({
                            "text": cell_text,
                            "is_header": td.name == "th"
                        })
                if row:
                    rows.append(row)
            if rows:
                return {"type": "table", "rows": rows}
                
        elif element.name == "img":
            src = element.get("src", "")
            if src and not src.startswith(('http:', 'https:')):
                src = urljoin('https://commons.wikimedia.org', src)
            return {
                "type": "image",
                "src": src,
                "alt": element.get("alt", "")
            }
            
        elif element.name == "div" and "thumb" in element.get("class", []):
            img = element.find("img")
            if img:
                src = img.get("src", "")
                if src and not src.startswith(('http:', 'https:')):
                    src = urljoin('https://commons.wikimedia.org', src)
                caption_elem = element.find("div", class_="thumbcaption")
                caption = caption_elem.get_text(strip=True) if caption_elem else ""
                return {
                    "type": "image",
                    "src": src,
                    "caption": caption,
                    "alt": img.get("alt", "")
                }
                
        elif element.name == "figure":
            img = element.find("img")
            if img:
                src = img.get("src", "")
                if src and not src.startswith(('http:', 'https:')):
                    src = urljoin('https://commons.wikimedia.org', src)
                caption_elem = element.find("figcaption")
                caption = caption_elem.get_text(strip=True) if caption_elem else ""
                return {
                    "type": "image",
                    "src": src,
                    "caption": caption,
                    "alt": img.get("alt", "")
                }
                
        elif element.name == "div" and "hatnote" in element.get("class", []):
            text = element.get_text(strip=True)
            if text:
                return {"type": "hatnote", "text": text}
        
        return None
    
    def _find_all_formulas_in_element(self, element) -> List[Any]:
        """Ищет ВСЕ математические формулы внутри элемента"""
        formulas = []
        
        # Ищем span с классом mwe-math-element
        math_spans = element.find_all('span', class_='mwe-math-element')
        formulas.extend(math_spans)
        
        # Ищем прямые теги math
        math_tags = element.find_all('math')
        formulas.extend(math_tags)
        
        return formulas
    
    def _extract_heading_info(self, element) -> Optional[tuple]:
        """Извлекает информацию о заголовке из элемента"""
        
        # Div с классом mw-heading (английская Википедия) - ПРИОРИТЕТ
        if (element.name == 'div' and 
            element.get('class') and 
            any('mw-heading' in cls for cls in element.get('class', []))):
            
            # Ищем h-тег внутри
            for h_tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                h_elem = element.find(h_tag)
                if h_elem:
                    try:
                        level = int(h_tag[1])
                        header_text = h_elem.get_text(strip=True)
                        header_id = h_elem.get('id', '')
                        header_text = re.sub(r'\s*\[edit\]\s*', '', header_text)
                        if header_text:
                            return level, header_text, header_id
                    except ValueError:
                        continue
            
            # Извлекаем из класса и текста
            for cls in element.get('class', []):
                if cls.startswith('mw-heading') and len(cls) > 10:
                    try:
                        level = int(cls[10:])
                        header_text = element.get_text(strip=True)
                        header_text = re.sub(r'\s*\[edit\]\s*', '', header_text)
                        header_text = re.sub(r'\s*\[.*?\]\s*', '', header_text)
                        header_id = element.get('id', '')
                        
                        if header_text and 1 <= level <= 6:
                            return level, header_text.strip(), header_id
                    except (ValueError, IndexError):
                        continue
        
        # Прямые теги h1-h6 - только если они НЕ внутри mw-heading
        if element.name and element.name.startswith('h'):
            # Проверяем, не находится ли этот h-тег внутри mw-heading div
            parent = element.parent
            if (parent and parent.name == 'div' and 
                parent.get('class') and 
                any('mw-heading' in cls for cls in parent.get('class', []))):
                # Это h-тег внутри mw-heading - уже обработан выше, пропускаем
                return None
            
            try:
                level = int(element.name[1])
                if 1 <= level <= 6:
                    header_text = element.get_text(strip=True)
                    header_id = element.get('id', '')
                    # Убираем текст "[edit]"
                    header_text = re.sub(r'\s*\[edit\]\s*', '', header_text)
                    if header_text:
                        return level, header_text, header_id
            except ValueError:
                pass
        
        return None
    
    def _extract_title(self) -> str:
        """Извлекает заголовок страницы"""
        title_element = self.soup.find("h1", class_="firstHeading")
        if title_element:
            return title_element.get_text(strip=True)
        title_element = self.soup.find("h1")
        if title_element:
            return title_element.get_text(strip=True)
        return ""
    
    def to_json(self, data: Dict[str, Any], indent: int = 2) -> str:
        """Конвертирует структуру в JSON строку"""
        return json.dumps(data, ensure_ascii=False, indent=indent)
    
    def save_to_file(self, data: Dict[str, Any], filename: str):
        """Сохраняет структуру в JSON файл"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def print_structure(self, data: Dict[str, Any], max_depth: int = 4):
        """Печатает структуру документа в читаемом виде"""
        def print_node(node, depth=0):
            if depth > max_depth:
                return
            indent = "  " * depth
            if node.get("type") == "heading":
                content_count = len(node.get("content", []))
                print(f"{indent}📁 H{node['level']}: {node['text']} (id: {node.get('id', '')}) [контент: {content_count}]")
                if "content" in node:
                    for child in node["content"]:
                        print_node(child, depth + 1)
            else:
                type_icons = {
                    "paragraph": "📝", "list": "📋", "table": "📊", "image": "🖼️",
                    "formula": "𝛢", "hatnote": "📌"
                }
                icon = type_icons.get(node["type"], "▪️")
                
                if node["type"] == "formula":
                    latex_preview = node.get('latex', '')[:30] + "..." if node.get('latex') else "no LaTeX"
                    preview = f"𝛢 {latex_preview}"
                else:
                    preview = node.get("text", "")[:50] + "..." if node.get("text") else f"{node['type']}"
                
                print(f"{indent}{icon} {node['type']}: {preview}")
        
        print(f"📖 {data['title']}")
        
        # Выводим основные разделы
        if "content" in data:
            for item in data["content"]:
                print_node(item, 1)


# Тестирование
def test_wiki_formulas(url: str):
    """Тест с сбором формул"""
    parser = WikiParser(debug=True)
    
    result = parser.parse_from_url(url)
    
    if "error" not in result:
        print("\n=== ФИНАЛЬНАЯ СТРУКТУРА ===")
        parser.print_structure(result, max_depth=4)
        
        # Статистика
        formula_count = 0
        def count_formulas(node):
            nonlocal formula_count
            if node.get("type") == "formula":
                formula_count += 1
            if "content" in node:
                for child in node["content"]:
                    count_formulas(child)
        
        for item in result.get("content", []):
            count_formulas(item)
        
        print(f"\n📊 СТАТИСТИКА:")
        print(f"   Формулы: {formula_count}")
        
        # Сохраняем результат
        parser.save_to_file(result, "wiki_formulas_isl.json")
        print(f"\n💾 Сохранено в wiki_formulas_isl.json")
        
        # Детальный вывод формул
        print(f"\n🔍 ФОРМУЛЫ:")
        def print_formulas(node, depth=0):
            indent = "  " * depth
            if node.get("type") == "formula":
                latex = node.get('latex', 'Нет')
                print(f"{indent}𝛢 {latex}")
            if "content" in node:
                for child in node["content"]:
                    print_formulas(child, depth + 1)
        
        for item in result.get("content", []):
            print_formulas(item, 1)
        
    else:
        print(f"Ошибка: {result['error']}")

if __name__ == "__main__":
    print("Тестирование парсера Википедии с формулами")
    print("=" * 50)
    
    # Тестируем на странице с формулами
    url = 'https://is.wikipedia.org/wiki/L%C3%ADnuleg_v%C3%B6rpun'
    test_wiki_formulas(url)