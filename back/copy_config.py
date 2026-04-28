#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для копирования config.yaml в директорию C:\temp\chatbot\
Это необходимо, так как API использует конфиг из этой директории.
"""

import os
import shutil
from pathlib import Path

def copy_config():
    """Копирует config.yaml в C:\temp\chatbot\"""
    
    # Определяем пути
    script_dir = Path(__file__).parent
    source_config = script_dir / "project" / "config.yaml"
    target_dir = Path(r"C:\temp\chatbot")
    target_config = target_dir / "config.yaml"
    
    # Проверяем существование исходного файла
    if not source_config.exists():
        print(f"[ERROR] Исходный файл не найден: {source_config}")
        return False
    
    # Создаем целевую директорию, если её нет
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Целевая директория: {target_dir}")
    
    # Копируем файл
    try:
        shutil.copy2(source_config, target_config)
        print(f"[INFO] Конфигурация успешно скопирована:")
        print(f"[INFO]   Из: {source_config}")
        print(f"[INFO]   В: {target_config}")
        
        # Выводим содержимое для проверки
        with open(target_config, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"\n[INFO] Содержимое конфига:")
            print("=" * 50)
            print(content)
            print("=" * 50)
        
        return True
    except Exception as e:
        print(f"[ERROR] Ошибка при копировании: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("Копирование config.yaml в C:\\temp\\chatbot\\")
    print("=" * 50)
    
    if copy_config():
        print("\n[SUCCESS] Конфигурация успешно обновлена!")
        print("[INFO] Перезапустите Django сервер для применения изменений.")
    else:
        print("\n[ERROR] Не удалось скопировать конфигурацию.")



