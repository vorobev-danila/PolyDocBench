# template_manager.py

from typing import Dict, Any
import yaml


class TemplateManager:
    """Управление шаблонами верстки"""
    
    def __init__(self, config_path: str = "render/configs/layout_templates.yaml"):
        self.config_path = config_path
        self.template_config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию шаблонов"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def get_template(self, template_name: str = "simple_article") -> Dict[str, Any]:
        """Возвращает шаблон по имени"""
        templates = self.template_config.get("templates", {})
        
        if template_name in templates:
            print(f"   Выбран шаблон: {template_name}")
            return templates[template_name]
        else:
            print(f"   ⚠️ Шаблон '{template_name}' не найден, используем 'simple_article'")
            return templates.get("simple_article", {})
    
    def get_base_settings(self) -> Dict[str, Any]:
        """Возвращает базовые настройки"""
        return self.template_config.get("base_settings", {})
