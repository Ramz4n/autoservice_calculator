# -*- coding: utf-8 -*-
"""
Конфигурация подключения к базе данных MariaDB

Настройки хранятся в файле: config/.env
"""

import os
import sys
from dotenv import load_dotenv


def get_base_path():
    """Получить базовый путь приложения (работает и для PyInstaller)"""
    if getattr(sys, 'frozen', False):
        # Запущено как exe (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Запущено как скрипт
        return os.path.dirname(__file__)


# Загружаем переменные из config/.env файла
_base_path = get_base_path()
_env_path = os.path.join(_base_path, 'config', '.env')
load_dotenv(_env_path)


def load_config():
    """Загрузить конфигурацию из переменных окружения"""
    return {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': int(os.getenv('DB_PORT', 3306)),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD', ''),
        'database': os.getenv('DB_NAME', 'alexauto'),
        'charset': 'utf8mb4',
        'autocommit': False,
    }


# Загружаем конфигурацию при импорте модуля
DB_CONFIG = load_config()
