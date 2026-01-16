# -*- coding: utf-8 -*-
"""
Скрипт миграции данных из SQLite в MariaDB

Этот скрипт переносит все данные из существующей SQLite базы данных
в новую MariaDB базу данных.

Использование:
    python migrate_to_mariadb.py

ВАЖНО: Перед запуском убедитесь, что:
1. Сервер MariaDB запущен
2. Настройки подключения в db_config.py корректны
3. Файл autoservice.db находится в той же папке
"""

import sqlite3
import mysql.connector
from mysql.connector import Error as MySQLError
import os
import sys

# Импортируем конфигурацию MariaDB
from db_config import DB_CONFIG


def migrate_data():
    """Выполнить миграцию данных из SQLite в MariaDB"""

    sqlite_db = "autoservice.db"

    # Проверяем существование SQLite базы
    if not os.path.exists(sqlite_db):
        print(f"Ошибка: Файл {sqlite_db} не найден!")
        print("Миграция не требуется - нет данных для переноса.")
        return False

    print("=" * 60)
    print("Миграция данных из SQLite в MariaDB")
    print("=" * 60)

    # Подключаемся к SQLite
    print("\n[1/7] Подключение к SQLite...")
    try:
        sqlite_conn = sqlite3.connect(sqlite_db)
        sqlite_cursor = sqlite_conn.cursor()
        print("      OK - SQLite подключен")
    except Exception as e:
        print(f"      ОШИБКА: {e}")
        return False

    # Подключаемся к MariaDB
    print("\n[2/7] Подключение к MariaDB...")
    try:
        config = DB_CONFIG.copy()
        db_name = config.pop('database')

        # Создаём базу данных если не существует
        maria_conn = mysql.connector.connect(**config)
        maria_cursor = maria_conn.cursor()
        maria_cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        maria_conn.commit()
        maria_cursor.close()
        maria_conn.close()

        # Подключаемся к созданной базе
        config['database'] = db_name
        maria_conn = mysql.connector.connect(**config)
        maria_cursor = maria_conn.cursor()
        print("      OK - MariaDB подключен")
    except MySQLError as e:
        print(f"      ОШИБКА: {e}")
        print("\nПроверьте:")
        print("  1. Запущен ли сервер MariaDB")
        print("  2. Правильность настроек в db_config.py")
        sqlite_conn.close()
        return False

    # Создаём таблицы в MariaDB
    print("\n[3/7] Создание таблиц в MariaDB...")
    try:
        # Таблица работников
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS workers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        # Таблица марок машин
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS car_brands (
                id INT AUTO_INCREMENT PRIMARY KEY,
                brand_name VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        # Таблица моделей машин
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS car_models (
                id INT AUTO_INCREMENT PRIMARY KEY,
                brand_id INT NOT NULL,
                model_name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (brand_id) REFERENCES car_brands(id) ON DELETE CASCADE,
                UNIQUE KEY unique_brand_model (brand_id, model_name)
            ) ENGINE=InnoDB
        ''')

        # Таблица работ
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS works (
                id INT AUTO_INCREMENT PRIMARY KEY,
                worker_id INT NOT NULL,
                description TEXT NOT NULL,
                amount DECIMAL(12,2) NOT NULL,
                work_date DATE NOT NULL,
                car_brand VARCHAR(255),
                car_model VARCHAR(255),
                car_number VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        ''')

        # Таблица расходов
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                description TEXT NOT NULL,
                amount DECIMAL(12,2) NOT NULL,
                expense_date DATE NOT NULL,
                category VARCHAR(255) NOT NULL,
                is_income TINYINT(1) DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        # Таблица запчастей
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS parts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                work_id INT NOT NULL,
                part_name TEXT NOT NULL,
                part_price DECIMAL(12,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        ''')

        # Таблица ключевых слов
        maria_cursor.execute('''
            CREATE TABLE IF NOT EXISTS keywords (
                id INT AUTO_INCREMENT PRIMARY KEY,
                keyword VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        maria_conn.commit()
        print("      OK - Таблицы созданы")
    except MySQLError as e:
        print(f"      ОШИБКА: {e}")
        sqlite_conn.close()
        maria_conn.close()
        return False

    # Мигрируем данные
    tables_to_migrate = [
        ('workers', 'id, full_name, created_at'),
        ('car_brands', 'id, brand_name, created_at'),
        ('car_models', 'id, brand_id, model_name, created_at'),
        ('works', 'id, worker_id, description, amount, work_date, car_brand, car_model, car_number, created_at'),
        ('expenses', 'id, description, amount, expense_date, category, created_at'),
        ('parts', 'id, work_id, part_name, part_price, created_at'),
    ]

    total_records = 0

    for i, (table, columns) in enumerate(tables_to_migrate, start=4):
        print(f"\n[{i}/7] Миграция таблицы '{table}'...")

        try:
            # Получаем данные из SQLite
            sqlite_cursor.execute(f"SELECT {columns} FROM {table}")
            rows = sqlite_cursor.fetchall()

            if not rows:
                print(f"      Пропуск - таблица пуста")
                continue

            # Подготавливаем INSERT для MariaDB
            col_list = columns.split(', ')
            placeholders = ', '.join(['%s'] * len(col_list))

            # Отключаем проверку внешних ключей на время вставки
            maria_cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

            # Очищаем таблицу перед вставкой
            maria_cursor.execute(f"DELETE FROM {table}")

            # Вставляем данные
            insert_query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

            for row in rows:
                # Преобразуем None в NULL совместимый формат
                row = tuple(None if v is None else v for v in row)
                maria_cursor.execute(insert_query, row)

            # Сбрасываем auto_increment если есть id
            if 'id' in col_list:
                max_id = max(row[0] for row in rows) if rows else 0
                maria_cursor.execute(f"ALTER TABLE {table} AUTO_INCREMENT = {max_id + 1}")

            maria_cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            maria_conn.commit()

            print(f"      OK - перенесено {len(rows)} записей")
            total_records += len(rows)

        except Exception as e:
            print(f"      ОШИБКА: {e}")
            maria_cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            maria_conn.rollback()

    # Закрываем соединения
    sqlite_conn.close()
    maria_conn.close()

    print("\n" + "=" * 60)
    print(f"Миграция завершена успешно!")
    print(f"Всего перенесено записей: {total_records}")
    print("=" * 60)

    # Предлагаем переименовать старую базу
    print("\nРекомендация: переименуйте старый файл SQLite:")
    print(f"  {sqlite_db} -> {sqlite_db}.backup")
    print("\nЭто предотвратит случайное использование старой базы.")

    return True


if __name__ == "__main__":
    print()
    try:
        success = migrate_data()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nМиграция прервана пользователем.")
        sys.exit(1)
    except Exception as e:
        print(f"\nКритическая ошибка: {e}")
        sys.exit(1)
