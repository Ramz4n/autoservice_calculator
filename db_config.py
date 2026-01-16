# -*- coding: utf-8 -*-
"""
Конфигурация подключения к базе данных MariaDB

Настройки хранятся в файле: config/database.json
"""

import json
import os

# Путь к файлу конфигурации
CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'database.json')


def load_config():
    """Загрузить конфигурацию из JSON файла"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        return {
            'host': config.get('host', 'localhost'),
            'port': int(config.get('port', 3306)),
            'user': config.get('user', 'root'),
            'password': config.get('password', ''),
            'database': config.get('database', 'alexauto'),
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci',
            'autocommit': False,
        }
    except FileNotFoundError:
        print(f"ОШИБКА: Файл конфигурации не найден: {CONFIG_FILE}")
        print("Создайте файл config/database.json с параметрами подключения.")
        raise
    except json.JSONDecodeError as e:
        print(f"ОШИБКА: Неверный формат JSON в файле {CONFIG_FILE}")
        print(f"Детали: {e}")
        raise


# Загружаем конфигурацию при импорте модуля
DB_CONFIG = load_config()
