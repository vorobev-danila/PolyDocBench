# column_strategy.py

class ColumnStrategy:
    """Стратегия последовательного заполнения колонок"""
    
    def __init__(self):
        self.current_column_index: int = 0
        self.page_column_starts = {}  # Для отслеживания начала колонок на странице
    
    def select_column(self, element_data, containers, current_index: int) -> int:
        """
        Всегда возвращает текущую колонку.
        Переключение на следующую происходит только при переполнении.
        """
        return current_index
    
    def find_alternative_column(self, element_height, current_index, containers):
        """
        Ищет следующую свободную колонку справа.
        Если достигли конца - возвращает None (нужна новая страница).
        """
        # Проверяем все колонки справа от текущей
        for i in range(current_index + 1, len(containers)):
            if containers[i].can_fit(element_height):
                return i
        
        # Больше колонок нет - нужна новая страница
        return None
    
    def reset_for_new_page(self, page_num: int):
        """Сброс на начало страницы"""
        self.current_column_index = 0
        self.page_column_starts[page_num] = 0
        print(f"   Страница {page_num}: начинаем с колонки 0")
    
    def switch_to_next_column(self, containers) -> bool:
        """Переключается на следующую колонку"""
        if not containers or self.current_column_index >= len(containers) - 1:
            return False
        
        self.current_column_index += 1
        print(f"   Переключение на колонку {self.current_column_index}")
        return True