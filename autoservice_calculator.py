# -*- coding: utf-8 -*-
"""
Калькулятор для автосервиса
Приложение для учёта работ сотрудников
"""

import mysql.connector
from mysql.connector import Error as MySQLError
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date
from tkcalendar import DateEntry
import json
import qrcode
from PIL import Image, ImageTk
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import tempfile
import re
import customtkinter as ctk

# Импорт конфигурации базы данных
from db_config import DB_CONFIG

# Путь к файлу настроек приложения
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'config', 'settings.json')

# Настройка темы CustomTkinter
ctk.set_appearance_mode("light")  # "dark" или "light"
ctk.set_default_color_theme("blue")  # "blue", "green", "dark-blue"


class TreeviewTooltip:
    """Всплывающая подсказка для Treeview при наведении на ячейку"""

    def __init__(self, treeview, columns=None):
        self.treeview = treeview
        self.columns = columns  # Список колонок для которых показывать tooltip (None = все)
        self.tooltip = None
        self.current_item = None
        self.current_column = None

        # Привязываем события
        self.treeview.bind('<Motion>', self.on_motion)
        self.treeview.bind('<Leave>', self.hide_tooltip)

    def on_motion(self, event):
        """Обработка движения мыши"""
        # Определяем элемент и колонку под курсором
        item = self.treeview.identify_row(event.y)
        column = self.treeview.identify_column(event.x)

        if not item or not column:
            self.hide_tooltip()
            return

        # Преобразуем #1, #2 в индекс колонки
        col_index = int(column.replace('#', '')) - 1
        columns = self.treeview['columns']

        if col_index < 0 or col_index >= len(columns):
            self.hide_tooltip()
            return

        col_name = columns[col_index]

        # Проверяем, нужно ли показывать tooltip для этой колонки
        if self.columns and col_name not in self.columns:
            self.hide_tooltip()
            return

        # Если это тот же элемент и колонка - не обновляем
        if item == self.current_item and column == self.current_column:
            return

        self.current_item = item
        self.current_column = column

        # Получаем текст ячейки
        values = self.treeview.item(item, 'values')
        if not values or col_index >= len(values):
            self.hide_tooltip()
            return

        text = str(values[col_index])

        # Показываем tooltip только если текст достаточно длинный
        if len(text) > 20:
            self.show_tooltip(event.x_root, event.y_root, text)
        else:
            self.hide_tooltip()

    def show_tooltip(self, x, y, text):
        """Показать tooltip"""
        self.hide_tooltip()

        self.tooltip = tk.Toplevel(self.treeview)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x + 15}+{y + 10}")

        # Создаём рамку и текст
        frame = tk.Frame(self.tooltip, bg='#ffffe0', relief='solid', borderwidth=1)
        frame.pack()

        # Разбиваем длинный текст на строки
        max_width = 60
        lines = []
        words = text.split()
        current_line = ""
        for word in words:
            if len(current_line + " " + word) <= max_width:
                current_line = (current_line + " " + word).strip()
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        wrapped_text = '\n'.join(lines) if lines else text

        label = tk.Label(frame, text=wrapped_text, bg='#ffffe0', fg='black',
                        font=('Segoe UI', 11), justify=tk.LEFT, padx=8, pady=5)
        label.pack()

    def hide_tooltip(self, event=None):
        """Скрыть tooltip"""
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None
        self.current_item = None
        self.current_column = None


class LabelTooltip:
    """Всплывающая подсказка для CTkLabel с детальной информацией"""

    def __init__(self, label, format_currency_func, is_expense=True):
        self.label = label
        self.format_currency = format_currency_func
        self.is_expense = is_expense  # True для расходов, False для доходов
        self.tooltip = None
        self.data = []  # Список кортежей (category, description, amount, date)

        # Привязываем события
        self.label.bind('<Enter>', self.show_tooltip)
        self.label.bind('<Leave>', self.hide_tooltip)

    def set_data(self, data):
        """Установить данные для tooltip"""
        self.data = data

    def show_tooltip(self, event):
        """Показать tooltip"""
        if not self.data:
            return

        self.hide_tooltip()

        # Получаем позицию label на экране
        x = self.label.winfo_rootx()
        y = self.label.winfo_rooty() + self.label.winfo_height() + 5

        self.tooltip = tk.Toplevel(self.label)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")

        # Цвета в зависимости от типа
        if self.is_expense:
            amount_color = '#c62828'  # Красный для расходов
            sign = "-"
        else:
            amount_color = '#2e7d32'  # Зелёный для доходов
            sign = "+"

        # Создаём рамку
        frame = tk.Frame(self.tooltip, bg='#fffde7', relief='solid', borderwidth=1)
        frame.pack()

        # Заголовок
        header = tk.Label(frame, text="Категория | Описание | Сумма | Дата",
                         bg='#fffde7', fg='#333', font=('Segoe UI', 10, 'bold'),
                         padx=10, pady=5)
        header.pack(anchor=tk.W)

        # Разделитель
        tk.Frame(frame, bg='#ccc', height=1).pack(fill=tk.X, padx=5)

        # Данные (максимум 15 записей)
        for i, (category, desc, amount, expense_date) in enumerate(self.data[:15]):
            amount = float(amount)
            # Форматируем дату
            if isinstance(expense_date, str):
                display_date = datetime.strptime(expense_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            else:
                display_date = expense_date.strftime('%d.%m.%Y')

            # Обрезаем длинное описание
            short_desc = desc[:25] + '...' if len(desc) > 25 else desc
            short_cat = category[:15] + '...' if len(category) > 15 else category

            # Строка с данными (сумму выводим отдельно с цветом)
            row_frame = tk.Frame(frame, bg='#fffde7')
            row_frame.pack(anchor=tk.W, fill=tk.X, padx=10)

            text_part = f"{short_cat} | {short_desc} | "
            tk.Label(row_frame, text=text_part, bg='#fffde7', fg='#333',
                    font=('Segoe UI', 9), pady=2, anchor=tk.W).pack(side=tk.LEFT)

            # Сумма с цветом и знаком
            amount_text = f"{sign}{self.format_currency(amount)}"
            tk.Label(row_frame, text=amount_text, bg='#fffde7', fg=amount_color,
                    font=('Segoe UI', 9, 'bold'), pady=2, anchor=tk.W).pack(side=tk.LEFT)

            tk.Label(row_frame, text=f" | {display_date}", bg='#fffde7', fg='#333',
                    font=('Segoe UI', 9), pady=2, anchor=tk.W).pack(side=tk.LEFT)

        # Если записей больше 15
        if len(self.data) > 15:
            more_label = tk.Label(frame, text=f"... и ещё {len(self.data) - 15} записей",
                                 bg='#fffde7', fg='#666', font=('Segoe UI', 9, 'italic'),
                                 padx=10, pady=5)
            more_label.pack(anchor=tk.W)

    def hide_tooltip(self, event=None):
        """Скрыть tooltip"""
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class Database:
    """Класс для работы с базой данных MariaDB"""

    def __init__(self):
        self.config = DB_CONFIG.copy()
        self.db_name = self.config.pop('database')
        self._ensure_database_exists()
        self.config['database'] = self.db_name
        self.create_tables()

    def _ensure_database_exists(self):
        """Создать базу данных, если она не существует"""
        try:
            conn = mysql.connector.connect(**self.config)
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.db_name}` "
                          f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
            cursor.close()
            conn.close()
        except MySQLError as e:
            messagebox.showerror("Ошибка подключения к БД",
                f"Не удалось подключиться к серверу MariaDB.\n\n"
                f"Проверьте:\n"
                f"1. Запущен ли сервер MariaDB\n"
                f"2. Правильность настроек в db_config.py\n\n"
                f"Ошибка: {e}")
            raise

    def get_connection(self):
        """Получить соединение с базой данных"""
        return mysql.connector.connect(**self.config)

    def create_tables(self):
        """Создание таблиц в базе данных"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Таблица работников
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        # Таблица марок машин
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS car_brands (
                id INT AUTO_INCREMENT PRIMARY KEY,
                brand_name VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        # Таблица моделей машин
        cursor.execute('''
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS works (
                id INT AUTO_INCREMENT PRIMARY KEY,
                worker_id INT NOT NULL,
                description TEXT NOT NULL,
                amount DECIMAL(12,2) NOT NULL,
                work_date DATE NOT NULL,
                car_brand VARCHAR(255),
                car_model VARCHAR(255),
                car_number VARCHAR(50),
                mileage VARCHAR(50),
                vin VARCHAR(20),
                order_number VARCHAR(20) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        ''')

        # Добавляем колонку mileage если её нет (для существующих баз)
        try:
            cursor.execute("ALTER TABLE works ADD COLUMN mileage VARCHAR(50)")
        except:
            pass  # Колонка уже существует

        # Добавляем колонку vin если её нет (для существующих баз)
        try:
            cursor.execute("ALTER TABLE works ADD COLUMN vin VARCHAR(20)")
        except:
            pass  # Колонка уже существует

        # Добавляем колонку order_number если её нет (для существующих баз)
        try:
            cursor.execute("ALTER TABLE works ADD COLUMN order_number VARCHAR(20) UNIQUE")
        except:
            pass  # Колонка уже существует

        # Таблица расходов/доходов
        cursor.execute('''
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS parts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                work_id INT NOT NULL,
                part_name TEXT NOT NULL,
                part_price DECIMAL(12,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        ''')

        # Таблица ключевых слов для автодополнения
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS keywords (
                id INT AUTO_INCREMENT PRIMARY KEY,
                keyword VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        ''')

        # Добавляем колонки если их нет (для существующих баз)
        try:
            cursor.execute("ALTER TABLE works ADD COLUMN car_brand VARCHAR(255)")
        except MySQLError:
            pass
        try:
            cursor.execute("ALTER TABLE works ADD COLUMN car_model VARCHAR(255)")
        except MySQLError:
            pass
        try:
            cursor.execute("ALTER TABLE works ADD COLUMN car_number VARCHAR(50)")
        except MySQLError:
            pass
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN is_income TINYINT(1) DEFAULT 0")
        except MySQLError:
            pass

        conn.commit()
        conn.close()

    # --- Методы для работы с работниками ---

    def add_worker(self, full_name):
        """Добавить работника"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO workers (full_name) VALUES (%s)", (full_name,))
            conn.commit()
            return True
        except mysql.connector.IntegrityError:
            return False
        finally:
            conn.close()

    def delete_worker(self, worker_id):
        """Удалить работника и все его записи"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM works WHERE worker_id = %s", (worker_id,))
        cursor.execute("DELETE FROM workers WHERE id = %s", (worker_id,))
        conn.commit()
        conn.close()

    def get_all_workers(self):
        """Получить всех работников"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, full_name FROM workers ORDER BY full_name")
        workers = cursor.fetchall()
        conn.close()
        return workers

    # --- Методы для работы с марками и моделями ---

    def add_car_brand(self, brand_name):
        """Добавить марку машины"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO car_brands (brand_name) VALUES (%s)", (brand_name,))
            conn.commit()
            return True
        except mysql.connector.IntegrityError:
            return False
        finally:
            conn.close()

    def add_car_model(self, brand_id, model_name):
        """Добавить модель машины"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO car_models (brand_id, model_name) VALUES (%s, %s)",
                         (brand_id, model_name))
            conn.commit()
            return True
        except mysql.connector.IntegrityError:
            return False
        finally:
            conn.close()

    def get_all_car_brands(self):
        """Получить все марки машин"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, brand_name FROM car_brands ORDER BY brand_name")
        brands = cursor.fetchall()
        conn.close()
        return brands

    def get_car_models_by_brand(self, brand_id):
        """Получить модели машины по марке"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, model_name FROM car_models WHERE brand_id = %s ORDER BY model_name",
                      (brand_id,))
        models = cursor.fetchall()
        conn.close()
        return models

    def get_brand_id_by_name(self, brand_name):
        """Получить ID марки по названию"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM car_brands WHERE LOWER(brand_name) = LOWER(%s)", (brand_name,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def search_car_brands(self, search_text):
        """Поиск марок машин по началу названия (без учёта регистра)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT brand_name FROM car_brands WHERE LOWER(brand_name) LIKE LOWER(%s) ORDER BY brand_name LIMIT 10",
                      (f"{search_text}%",))
        brands = [row[0] for row in cursor.fetchall()]
        conn.close()
        return brands

    def search_car_models(self, brand_name, search_text=""):
        """Поиск моделей машин по марке и промежуточным буквам

        Если search_text пустой - возвращает все модели марки
        Если search_text не пустой - ищет по промежуточным буквам (например, 'kra' найдет 'iskra')
        """
        brand_id = self.get_brand_id_by_name(brand_name)
        if not brand_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()

        if not search_text or search_text == "":
            # Если поиск пустой, возвращаем все модели для этой марки
            cursor.execute(
                "SELECT model_name FROM car_models WHERE brand_id = %s ORDER BY model_name",
                (brand_id,)
            )
        else:
            # Создаем паттерн для поиска по промежуточным буквам
            # Например, "kra" становится "%k%r%a%"
            pattern = "%" + "%".join(search_text.lower()) + "%"
            cursor.execute(
                "SELECT model_name FROM car_models WHERE brand_id = %s AND LOWER(model_name) LIKE %s ORDER BY model_name LIMIT 20",
                (brand_id, pattern)
            )

        models = [row[0] for row in cursor.fetchall()]
        conn.close()
        return models

    def delete_car_brand(self, brand_id):
        """Удалить марку машины и все её модели"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM car_models WHERE brand_id = %s", (brand_id,))
        cursor.execute("DELETE FROM car_brands WHERE id = %s", (brand_id,))
        conn.commit()
        conn.close()

    def delete_car_model(self, model_id):
        """Удалить модель машины"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM car_models WHERE id = %s", (model_id,))
        conn.commit()
        conn.close()

    def import_brands_models_from_dict(self, data):
        """Импортировать марки и модели из словаря {brand: [models]}"""
        conn = self.get_connection()
        cursor = conn.cursor()
        added_brands = 0
        added_models = 0

        for brand_name, models in data.items():
            try:
                cursor.execute("INSERT INTO car_brands (brand_name) VALUES (%s)", (brand_name,))
                brand_id = cursor.lastrowid
                added_brands += 1
            except mysql.connector.IntegrityError:
                cursor.execute("SELECT id FROM car_brands WHERE brand_name = %s", (brand_name,))
                brand_id = cursor.fetchone()[0]

            for model_name in models:
                try:
                    cursor.execute("INSERT INTO car_models (brand_id, model_name) VALUES (%s, %s)",
                                 (brand_id, model_name))
                    added_models += 1
                except mysql.connector.IntegrityError:
                    pass

        conn.commit()
        conn.close()
        return added_brands, added_models

    # --- Методы для работы с записями о работах ---

    def generate_order_number(self):
        """Генерировать уникальный номер заказа"""
        import random
        conn = self.get_connection()
        cursor = conn.cursor()
        while True:
            # Формат: 8 случайных цифр (90 млн вариантов)
            order_number = str(random.randint(10000000, 99999999))
            cursor.execute("SELECT id FROM works WHERE order_number = %s", (order_number,))
            if not cursor.fetchone():
                conn.close()
                return order_number

    def add_work(self, worker_id, description, amount, work_date, car_brand="", car_model="", car_number="", mileage="", vin=""):
        """Добавить запись о работе и вернуть ID"""
        order_number = self.generate_order_number()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO works (worker_id, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, order_number) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (worker_id, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, order_number)
        )
        work_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return work_id

    def update_work(self, work_id, worker_id, description, amount, work_date, car_brand="", car_model="", car_number="", mileage="", vin=""):
        """Обновить запись о работе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE works
            SET worker_id = %s, description = %s, amount = %s, work_date = %s,
                car_brand = %s, car_model = %s, car_number = %s, mileage = %s, vin = %s
            WHERE id = %s
        ''', (worker_id, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, work_id))
        conn.commit()
        conn.close()

    def get_work_by_id(self, work_id):
        """Получить работу по ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, wk.worker_id, w.full_name, wk.description, wk.amount,
                   wk.work_date, wk.car_brand, wk.car_model, wk.car_number, wk.mileage, wk.vin
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.id = %s
        ''', (work_id,))
        work = cursor.fetchone()
        conn.close()
        return work

    def delete_parts_by_work_id(self, work_id):
        """Удалить все запчасти для работы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM parts WHERE work_id = %s", (work_id,))
        conn.commit()
        conn.close()

    def get_works_by_period(self, date_from, date_to):
        """Получить работы за период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.work_date, wk.car_brand, wk.car_model, wk.car_number, wk.order_number
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.work_date BETWEEN %s AND %s
            ORDER BY w.full_name, wk.work_date
        ''', (date_from, date_to))
        works = cursor.fetchall()
        conn.close()
        return works

    def get_works_by_car_number(self, car_number):
        """Получить все работы по госномеру"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.work_date, wk.car_brand, wk.car_model, wk.car_number, wk.order_number
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE UPPER(wk.car_number) LIKE %s
            ORDER BY wk.work_date DESC
        ''', (f'%{car_number.upper()}%',))
        works = cursor.fetchall()
        conn.close()
        return works

    def get_summary_by_period(self, date_from, date_to):
        """Получить сводку по работникам за период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT w.full_name, SUM(wk.amount) as total, COUNT(wk.id) as work_count
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.work_date BETWEEN %s AND %s
            GROUP BY w.id
            ORDER BY total DESC
        ''', (date_from, date_to))
        summary = cursor.fetchall()
        conn.close()
        return summary

    def get_recent_works(self, limit=50):
        """Получить последние записи о работах"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.work_date, wk.car_brand, wk.car_model, wk.car_number
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            ORDER BY wk.created_at DESC, wk.id DESC
            LIMIT %s
        ''', (limit,))
        works = cursor.fetchall()
        conn.close()
        return works

    # --- Методы для работы с расходами ---

    def add_expense(self, description, amount, expense_date, category, is_income=False):
        """Добавить запись о расходе или доходе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO expenses (description, amount, expense_date, category, is_income) VALUES (%s, %s, %s, %s, %s)",
            (description, amount, expense_date, category, 1 if is_income else 0)
        )
        conn.commit()
        conn.close()

    def get_expenses_by_period(self, date_from, date_to):
        """Получить расходы за период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT description, amount, expense_date, category
            FROM expenses
            WHERE expense_date BETWEEN %s AND %s
            ORDER BY expense_date DESC
        ''', (date_from, date_to))
        expenses = cursor.fetchall()
        conn.close()
        return expenses

    def get_recent_expenses(self, limit=50):
        """Получить последние записи о расходах и доходах"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, description, amount, expense_date, category, COALESCE(is_income, 0) as is_income
            FROM expenses
            ORDER BY created_at DESC, id DESC
            LIMIT %s
        ''', (limit,))
        expenses = cursor.fetchall()
        conn.close()
        return expenses

    def delete_expense(self, expense_id):
        """Удалить расход"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
        conn.commit()
        conn.close()

    def get_total_expenses_by_period(self, date_from, date_to):
        """Получить общую сумму расходов за период (только расходы, без доходов)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(amount), 0) as total
            FROM expenses
            WHERE expense_date BETWEEN %s AND %s AND (is_income = 0 OR is_income IS NULL)
        ''', (date_from, date_to))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    def get_total_income_by_period(self, date_from, date_to):
        """Получить общую сумму доходов за период (только доходы)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(amount), 0) as total
            FROM expenses
            WHERE expense_date BETWEEN %s AND %s AND is_income = 1
        ''', (date_from, date_to))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    def get_detailed_expenses_by_period(self, date_from, date_to):
        """Получить детальный список расходов за период (только расходы)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT category, description, amount, expense_date
            FROM expenses
            WHERE expense_date BETWEEN %s AND %s AND (is_income = 0 OR is_income IS NULL)
            ORDER BY expense_date DESC
        ''', (date_from, date_to))
        expenses = cursor.fetchall()
        conn.close()
        return expenses

    def get_detailed_income_by_period(self, date_from, date_to):
        """Получить детальный список доходов за период (только доходы)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT category, description, amount, expense_date
            FROM expenses
            WHERE expense_date BETWEEN %s AND %s AND is_income = 1
            ORDER BY expense_date DESC
        ''', (date_from, date_to))
        income = cursor.fetchall()
        conn.close()
        return income

    # --- Методы для работы с запчастями ---

    def add_parts(self, work_id, parts_list):
        """Добавить запчасти к работе
        parts_list: список кортежей (part_name, part_price)
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        for part_name, part_price in parts_list:
            cursor.execute(
                "INSERT INTO parts (work_id, part_name, part_price) VALUES (%s, %s, %s)",
                (work_id, part_name, part_price)
            )
        conn.commit()
        conn.close()

    def get_parts_by_work_id(self, work_id):
        """Получить запчасти по ID работы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT part_name, part_price
            FROM parts
            WHERE work_id = %s
            ORDER BY id
        ''', (work_id,))
        parts = cursor.fetchall()
        conn.close()
        return parts

    def get_work_with_parts_by_car(self, car_brand, car_model, car_number):
        """Получить работы с запчастями по машине"""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Получаем работы по машине
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.work_date,
                   wk.car_brand, wk.car_model, wk.car_number
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.car_brand = %s AND wk.car_model = %s AND wk.car_number = %s
            ORDER BY wk.work_date DESC
        ''', (car_brand, car_model, car_number))
        works = cursor.fetchall()
        conn.close()
        return works

    # --- Методы для работы с ключевыми словами ---

    def add_keyword(self, keyword):
        """Добавить ключевое слово"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO keywords (keyword) VALUES (%s)",
                (keyword,)
            )
            conn.commit()
            return True
        except MySQLError:
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_all_keywords(self):
        """Получить все ключевые слова"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, keyword FROM keywords ORDER BY keyword")
        keywords = cursor.fetchall()
        conn.close()
        return keywords

    def search_keywords(self, prefix):
        """Поиск ключевых слов по префиксу (без учёта регистра)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT keyword FROM keywords WHERE LOWER(keyword) LIKE LOWER(%s) ORDER BY keyword LIMIT 10",
            ('%' + prefix + '%',)
        )
        keywords = [row[0] for row in cursor.fetchall()]
        conn.close()
        return keywords

    def delete_keyword(self, keyword_id):
        """Удалить ключевое слово"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM keywords WHERE id = %s", (keyword_id,))
        conn.commit()
        conn.close()

    def import_keywords_from_list(self, keywords):
        """Импортировать ключевые слова из списка"""
        conn = self.get_connection()
        cursor = conn.cursor()
        added = 0
        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue
            try:
                cursor.execute(
                    "INSERT INTO keywords (keyword) VALUES (%s)",
                    (keyword,)
                )
                added += 1
            except MySQLError:
                pass  # Пропускаем дубликаты
        conn.commit()
        conn.close()
        return added



class AutoServiceApp:
    """Главный класс приложения"""

    def __init__(self, root):
        self.root = root
        self.root.title("Калькулятор автосервиса")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        self.db = Database()

        # Настройка стилей
        self.setup_styles()

        # Создание вкладок
        self.notebook = ctk.CTkTabview(root, command=self.on_tab_changed)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Вкладка "Добавить" с подвкладками
        self.notebook.add("Добавить")
        self.add_frame = self.notebook.tab("Добавить")

        # Создаём вложенный Tabview для подвкладок
        self.add_notebook = ctk.CTkTabview(self.add_frame)
        self.add_notebook.pack(fill=tk.BOTH, expand=True)

        # Подвкладка работников
        self.add_notebook.add("Мастера")
        self.workers_frame = self.add_notebook.tab("Мастера")
        self.setup_workers_tab()

        # Подвкладка марок и моделей
        self.add_notebook.add("Марки и модели")
        self.cars_frame = self.add_notebook.tab("Марки и модели")
        self.setup_cars_tab()

        # Подвкладка ключевых слов
        self.add_notebook.add("Ключевые слова")
        self.keywords_frame = self.add_notebook.tab("Ключевые слова")
        self.setup_keywords_tab()

        # Вкладка добавления работ
        self.notebook.add("Добавить работу")
        self.works_frame = self.notebook.tab("Добавить работу")
        self.setup_works_tab()

        # Вкладка отчётов
        self.notebook.add("Отчёты")
        self.reports_frame = self.notebook.tab("Отчёты")
        self.setup_reports_tab()

        # Вкладка расходов и доходов
        self.notebook.add("Финансы")
        self.expenses_frame = self.notebook.tab("Финансы")
        self.setup_expenses_tab()

        # Загрузка данных
        self.refresh_workers_list()
        self.refresh_workers_combo()
        self.refresh_expenses()
        self.refresh_keywords_list()

    def on_tab_changed(self):
        """Обработчик переключения вкладок"""
        current_tab = self.notebook.get()
        if current_tab == "Отчёты":
            # Автоматически обновляем отчёт при переключении на вкладку
            self.generate_report(show_empty_message=False)

    def format_currency(self, amount):
        """Форматирование суммы в формат: 1.000.000 руб."""
        # Определяем знак
        sign = "-" if amount < 0 else ""
        amount = abs(amount)

        # Форматируем число с двумя знаками после запятой
        formatted = f"{amount:.2f}"
        # Разделяем на целую и дробную части
        parts = formatted.split('.')
        integer_part = parts[0]
        decimal_part = parts[1]

        # Добавляем точки как разделители тысяч
        integer_with_separators = ""
        for i, digit in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                integer_with_separators = "." + integer_with_separators
            integer_with_separators = digit + integer_with_separators

        # Возвращаем отформатированную строку
        return f"{sign}{integer_with_separators},{decimal_part} руб."

    def load_settings(self):
        """Загрузить настройки из JSON файла"""
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'master_percent': 50}

    def save_settings(self, settings):
        """Сохранить настройки в JSON файл"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")

    def on_percent_changed(self, *args):
        """Обработчик изменения процента мастеру"""
        try:
            percent_str = self.percent_var.get().replace(',', '.')
            if percent_str:
                percent = float(percent_str)
                settings = self.load_settings()
                settings['master_percent'] = percent
                self.save_settings(settings)
        except ValueError:
            pass

    def setup_entry_context_menu(self, entry_widget):
        """Добавляет контекстное меню с функциями копирования/вставки для поля ввода"""
        # Создаем контекстное меню
        context_menu = tk.Menu(entry_widget, tearoff=0)

        def cut_text():
            try:
                if entry_widget.select_present():
                    entry_widget.clipboard_clear()
                    entry_widget.clipboard_append(entry_widget.selection_get())
                    entry_widget.delete("sel.first", "sel.last")
            except:
                pass

        def copy_text():
            try:
                if entry_widget.select_present():
                    entry_widget.clipboard_clear()
                    entry_widget.clipboard_append(entry_widget.selection_get())
            except:
                pass

        def paste_text():
            try:
                text = entry_widget.clipboard_get()
                try:
                    # Для CTkEntry используем insert в позицию курсора
                    entry_widget.insert(tk.INSERT, text)
                except:
                    # Если не работает, вставляем в конец
                    current = entry_widget.get()
                    entry_widget.delete(0, tk.END)
                    entry_widget.insert(0, current + text)
            except:
                pass

        def select_all():
            try:
                entry_widget.select_range(0, tk.END)
                entry_widget.icursor(tk.END)
            except:
                pass

        context_menu.add_command(label="Вырезать", command=cut_text)
        context_menu.add_command(label="Копировать", command=copy_text)
        context_menu.add_command(label="Вставить", command=paste_text)
        context_menu.add_separator()
        context_menu.add_command(label="Выделить всё", command=select_all)

        def show_context_menu(event):
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()

        # Привязываем контекстное меню к правой кнопке мыши
        entry_widget.bind("<Button-3>", show_context_menu)

        # Привязываем горячие клавиши (return "break" чтобы остановить стандартную обработку)
        def paste_wrapper(e):
            paste_text()
            return "break"

        def copy_wrapper(e):
            copy_text()
            return "break"

        def cut_wrapper(e):
            cut_text()
            return "break"

        def select_all_wrapper(e):
            select_all()
            return "break"

        entry_widget.bind("<Control-v>", paste_wrapper)
        entry_widget.bind("<Control-V>", paste_wrapper)
        entry_widget.bind("<Control-m>", paste_wrapper)  # Ctrl+M (только на английской раскладке)
        entry_widget.bind("<Control-M>", paste_wrapper)
        entry_widget.bind("<Control-c>", copy_wrapper)
        entry_widget.bind("<Control-C>", copy_wrapper)
        entry_widget.bind("<Control-x>", cut_wrapper)
        entry_widget.bind("<Control-X>", cut_wrapper)
        entry_widget.bind("<Control-a>", select_all_wrapper)
        entry_widget.bind("<Control-A>", select_all_wrapper)

    def setup_styles(self):
        """Настройка стилей"""
        style = ttk.Style()

        # Используем тему clam для отображения вертикальных разделителей
        style.theme_use('clam')

        style.configure("Title.TLabel", font=("Arial", 14, "bold"))
        style.configure("Header.TLabel", font=("Arial", 11, "bold"))

        # Настройка Treeview для отображения сетки с разделителями
        style.configure("Treeview",
                       rowheight=32,
                       borderwidth=1,
                       relief="solid",
                       background="white",
                       fieldbackground="white",
                       font=("Segoe UI", 12))
        style.configure("Treeview.Heading",
                       borderwidth=1,
                       relief="solid",
                       background="#e0e0e0",
                       font=("Segoe UI", 11, "bold"))

        # Настройка цветов для чередующихся строк и выделения
        style.map('Treeview',
                 background=[('selected', '#0078d7')],
                 foreground=[('selected', 'white')])

        # Теги для чередующихся строк (zebra stripes)
        self.row_tags = ('oddrow', 'evenrow')

    # ===== ВКЛАДКА РАБОТНИКОВ =====

    def setup_workers_tab(self):
        """Настройка вкладки работников"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.workers_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Верхняя панель - добавление работника
        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=20)

        ctk.CTkLabel(add_frame, text="ФИО:").pack(side=tk.LEFT, padx=5, pady=5)
        self.worker_name_entry = ctk.CTkEntry(add_frame, width=400, fg_color="white", text_color="black")
        self.worker_name_entry.pack(side=tk.LEFT, padx=5, pady=5)

        ctk.CTkButton(add_frame, text="Добавить", command=self.add_worker, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5, pady=5)

        # Список работников
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(fill=tk.X, pady=10)

        # Таблица работников (без колонки ID) - ширина по родительскому контейнеру
        columns = ("name",)
        self.workers_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.workers_tree.heading("name", text="ФИО мастера")
        self.workers_tree.column("name", width=500, stretch=True, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.workers_tree.yview)
        self.workers_tree.configure(yscrollcommand=scrollbar.set)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.workers_tree.tag_configure('oddrow', background='#ffffff')
        self.workers_tree.tag_configure('evenrow', background='#f0f0f0')

        self.workers_tree.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)

        # Кнопка удаления
        ctk.CTkButton(center_container, text="Удалить выбранного мастера",
                   command=self.delete_worker, width=550, fg_color="red", hover_color="darkred").pack(anchor=tk.CENTER, pady=10)

    def add_worker(self):
        """Добавить работника"""
        name = self.worker_name_entry.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Введите ФИО мастера!")
            return

        if self.db.add_worker(name):
            messagebox.showinfo("Успех", f"Мастер '{name}' добавлен!")
            self.worker_name_entry.delete(0, tk.END)
            self.refresh_workers_list()
            self.refresh_workers_combo()
        else:
            messagebox.showerror("Ошибка", "Мастер с таким ФИО уже существует!")

    def delete_worker(self):
        """Удалить работника"""
        selected = self.workers_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите мастера для удаления!")
            return

        item = self.workers_tree.item(selected[0])
        worker_id = item['tags'][0]  # ID хранится в тегах
        worker_name = item['values'][0]  # Имя в первой колонке

        if messagebox.askyesno("Подтверждение",
                               f"Удалить мастера '{worker_name}'?\n\nВсе записи о его работах также будут удалены!"):
            self.db.delete_worker(worker_id)
            messagebox.showinfo("Успех", "Мастер удалён!")
            self.refresh_workers_list()
            self.refresh_workers_combo()

    def refresh_workers_list(self):
        """Обновить список работников"""
        for item in self.workers_tree.get_children():
            self.workers_tree.delete(item)

        row_index = 0
        for worker in self.db.get_all_workers():
            worker_id, worker_name = worker

            # Определяем тег для чередующихся строк
            row_tag = 'oddrow' if row_index % 2 == 0 else 'evenrow'

            # Вставляем только имя в таблицу, ID сохраняем в тегах вместе с цветом
            self.workers_tree.insert("", tk.END, values=(worker_name,), tags=(worker_id, row_tag))

            row_index += 1

    # ===== ВКЛАДКА ДОБАВЛЕНИЯ РАБОТ =====

    def setup_works_tab(self):
        """Настройка вкладки добавления работ"""
        # Используем прокручиваемый фрейм для поддержки маленьких экранов
        main_frame = ctk.CTkScrollableFrame(self.works_frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Центрированный контейнер для всех элементов
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        title = ctk.CTkLabel(
            center_container,
            text="Добавить запись о работе",
            font=("Segoe UI", 20, "bold"),
            anchor="w"
        )
        title.pack(fill=tk.X, pady=(0, 10))

        # Выбор работника
        row1 = ctk.CTkFrame(center_container)
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text="Мастер:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.worker_combo = ctk.CTkComboBox(row1, width=350, fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.worker_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Марка машины с автокомплитом
        row_car_brand = ctk.CTkFrame(center_container)
        row_car_brand.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_car_brand, text="Марка машины:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.car_brand_entry = ctk.CTkEntry(row_car_brand, width=250, fg_color="white", text_color="black")
        self.car_brand_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.car_brand_entry.bind('<KeyRelease>', self.on_brand_keyrelease)
        self.car_brand_entry.bind('<FocusOut>', self.on_brand_focus_out)

        # Listbox для автокомплита марки
        self.brand_listbox = tk.Listbox(row_car_brand, height=5, width=30, takefocus=False)
        self.brand_listbox_visible = False
        self.brand_listbox.bind('<<ListboxSelect>>', self.on_brand_select)

        # Модель машины с автокомплитом
        row_car_model = ctk.CTkFrame(center_container)
        row_car_model.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_car_model, text="Модель машины:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.car_model_entry = ctk.CTkEntry(row_car_model, width=250, fg_color="white", text_color="black")
        self.car_model_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.car_model_entry.bind('<KeyRelease>', self.on_model_keyrelease)
        self.car_model_entry.bind('<FocusOut>', self.on_model_focus_out)

        # Listbox для автокомплита модели
        self.model_listbox = tk.Listbox(row_car_model, height=5, width=30, takefocus=False)
        self.model_listbox_visible = False
        self.model_listbox.bind('<<ListboxSelect>>', self.on_model_select)

        # Номер машины и пробег
        row_car_number = ctk.CTkFrame(center_container)
        row_car_number.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_car_number, text="Госномер:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.car_number_entry = ctk.CTkEntry(row_car_number, width=100, fg_color="white", text_color="black")
        self.car_number_entry.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(row_car_number, text="Пробег:", width=80, anchor="w").pack(side=tk.LEFT, padx=(20, 5))
        self.mileage_entry = ctk.CTkEntry(row_car_number, width=100, fg_color="white", text_color="black")
        self.mileage_entry.pack(side=tk.LEFT, padx=5)

        # VIN номер (необязательное поле)
        row_vin = ctk.CTkFrame(center_container)
        row_vin.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_vin, text="VIN:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.vin_entry = ctk.CTkEntry(row_vin, width=200, fg_color="white", text_color="black")
        self.vin_entry.pack(side=tk.LEFT, padx=5)

        # Контекстное меню для VIN (правая кнопка - вставить)
        self.vin_context_menu = tk.Menu(self.root, tearoff=0)
        self.vin_context_menu.add_command(label="Вставить", command=self.paste_to_vin)
        self.vin_entry.bind("<Button-3>", self.show_vin_context_menu)

        # Описание работы
        row2 = ctk.CTkFrame(center_container)
        row2.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row2, text="Что сделал:", width=150, anchor="w").pack(side=tk.LEFT, padx=5, pady=5)
        self.work_desc_entry = ctk.CTkTextbox(row2, width=400, height=80, fg_color="white", text_color="black", wrap="word")
        self.work_desc_entry.pack(side=tk.LEFT, padx=5, fill=tk.BOTH, expand=True)
        self.work_desc_entry.bind('<KeyRelease>', self.on_description_keyrelease)
        self.work_desc_entry.bind('<FocusOut>', self.on_description_focus_out)

        # Listbox для автокомплита ключевых слов
        self.keyword_listbox = tk.Listbox(row2, height=5, width=40, takefocus=False)
        self.keyword_listbox_visible = False
        self.keyword_listbox.bind('<Double-Button-1>', self.on_keyword_select)

        # Сумма
        row3 = ctk.CTkFrame(center_container)
        row3.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row3, text="Сумма (руб.):", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.amount_entry = ctk.CTkEntry(row3, width=200, fg_color="white", text_color="black")
        self.amount_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Секция запчастей (внутри центрированного контейнера)
        parts_left_container = ctk.CTkFrame(center_container)
        parts_left_container.pack(anchor=tk.W, pady=10)

        # Таблица запчастей
        parts_table_frame = ctk.CTkFrame(parts_left_container)
        parts_table_frame.pack(pady=5)

        columns = ("part_name", "part_price")
        self.parts_tree = ttk.Treeview(parts_table_frame, columns=columns, show="headings", height=3)
        self.parts_tree.heading("part_name", text="Название запчасти")
        self.parts_tree.heading("part_price", text="Цена")

        self.parts_tree.column("part_name", width=400)
        self.parts_tree.column("part_price", width=150, anchor=tk.CENTER)

        scrollbar_parts = ttk.Scrollbar(parts_table_frame, orient=tk.VERTICAL, command=self.parts_tree.yview)
        self.parts_tree.configure(yscrollcommand=scrollbar_parts.set)

        self.parts_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_parts.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления под таблицей
        parts_delete_button = ctk.CTkButton(parts_left_container, text="Удалить выбранную запчасть",
                   command=self.remove_part_from_list, width=550, fg_color="red", hover_color="darkred")
        parts_delete_button.pack(pady=5)

        # Ввод запчасти под кнопкой удаления
        parts_input_frame = ctk.CTkFrame(parts_left_container)
        parts_input_frame.pack(pady=5)

        ctk.CTkLabel(parts_input_frame, text="Название запчасти:").pack(anchor=tk.W, padx=5, pady=2)
        self.part_name_entry = ctk.CTkEntry(parts_input_frame, width=550, fg_color="white", text_color="black")
        self.part_name_entry.pack(padx=5, pady=2)

        # Добавляем контекстное меню для вставки
        self.setup_entry_context_menu(self.part_name_entry)

        ctk.CTkLabel(parts_input_frame, text="Цена запчасти:").pack(anchor=tk.W, padx=5, pady=2)
        self.part_price_entry = ctk.CTkEntry(parts_input_frame, width=550, fg_color="white", text_color="black")
        self.part_price_entry.pack(padx=5, pady=2)

        ctk.CTkButton(parts_input_frame, text="Добавить запчасть",
                   command=self.add_part_to_list, width=550).pack(pady=5)

        # Список запчастей (временное хранилище)
        self.parts_list = []

        # Кнопка добавления
        ctk.CTkButton(center_container, text="Добавить запись",
                   command=self.add_work, width=550, height=50, fg_color="green", hover_color="darkgreen").pack(anchor=tk.CENTER, pady=20)

    # Обработчики автокомплита для марки
    def on_brand_keyrelease(self, event):
        """Обработчик ввода текста для марки"""
        search_text = self.car_brand_entry.get().strip()
        if len(search_text) < 1:
            self.hide_brand_listbox()
            return

        brands = self.db.search_car_brands(search_text)
        if brands:
            self.show_brand_listbox(brands)
        else:
            self.hide_brand_listbox()

    def show_brand_listbox(self, brands):
        """Показать список марок"""
        self.brand_listbox.delete(0, tk.END)
        for brand in brands:
            self.brand_listbox.insert(tk.END, brand)
        if not self.brand_listbox_visible:
            self.brand_listbox.pack(side=tk.LEFT, padx=5)
            self.brand_listbox_visible = True

    def hide_brand_listbox(self):
        """Скрыть список марок"""
        if self.brand_listbox_visible:
            self.brand_listbox.pack_forget()
            self.brand_listbox_visible = False

    def show_vin_context_menu(self, event):
        """Показать контекстное меню для поля VIN"""
        self.vin_context_menu.tk_popup(event.x_root, event.y_root)

    def paste_to_vin(self):
        """Вставить текст из буфера обмена в поле VIN"""
        try:
            clipboard_text = self.root.clipboard_get()
            self.vin_entry.insert(tk.END, clipboard_text)
        except tk.TclError:
            pass  # Буфер обмена пуст

    def on_brand_select(self, event):
        """Обработчик выбора марки из списка"""
        selection = self.brand_listbox.curselection()
        if selection:
            brand = self.brand_listbox.get(selection[0])
            self.car_brand_entry.delete(0, tk.END)
            self.car_brand_entry.insert(0, brand)
            self.hide_brand_listbox()

            # Автоматически показываем все модели выбранной марки
            models = self.db.search_car_models(brand, "")
            if models:
                # Очищаем поле модели и переводим фокус на него
                self.car_model_entry.delete(0, tk.END)
                self.show_model_listbox(models)
                self.car_model_entry.focus_set()

    def on_brand_focus_out(self, event):
        """Скрыть список при потере фокуса"""
        self.root.after(200, self.hide_brand_listbox)

    # Обработчики автокомплита для модели
    def on_model_keyrelease(self, event):
        """Обработчик ввода текста для модели"""
        brand = self.car_brand_entry.get().strip()
        if not brand:
            self.hide_model_listbox()
            return

        search_text = self.car_model_entry.get().strip()
        # Теперь показываем модели даже если search_text пустой
        models = self.db.search_car_models(brand, search_text)
        if models:
            self.show_model_listbox(models)
        else:
            self.hide_model_listbox()

    def show_model_listbox(self, models):
        """Показать список моделей"""
        self.model_listbox.delete(0, tk.END)
        for model in models:
            self.model_listbox.insert(tk.END, model)
        if not self.model_listbox_visible:
            self.model_listbox.pack(side=tk.LEFT, padx=5)
            self.model_listbox_visible = True

    def hide_model_listbox(self):
        """Скрыть список моделей"""
        if self.model_listbox_visible:
            self.model_listbox.pack_forget()
            self.model_listbox_visible = False

    def on_model_select(self, event):
        """Обработчик выбора модели из списка"""
        selection = self.model_listbox.curselection()
        if selection:
            model = self.model_listbox.get(selection[0])
            self.car_model_entry.delete(0, tk.END)
            self.car_model_entry.insert(0, model)
            self.hide_model_listbox()

    def on_model_focus_out(self, event):
        """Скрыть список при потере фокуса"""
        self.root.after(200, self.hide_model_listbox)

    # Обработчики автокомплита для ключевых слов
    def on_description_keyrelease(self, event):
        """Обработчик ввода текста для описания работы"""
        # Получаем текст до позиции курсора
        try:
            text = self.work_desc_entry.get("1.0", "insert")
        except:
            self.hide_keyword_listbox()
            return

        # Находим последнее слово (после пробела, запятой или новой строки)
        words = re.split(r'[\s,\n]+', text)
        last_word = words[-1] if words else ""

        if len(last_word) < 1:
            self.hide_keyword_listbox()
            return

        keywords = self.db.search_keywords(last_word)
        if keywords:
            self.show_keyword_listbox(keywords)
        else:
            self.hide_keyword_listbox()

    def show_keyword_listbox(self, keywords):
        """Показать список ключевых слов"""
        self.keyword_listbox.delete(0, tk.END)
        for keyword in keywords:
            self.keyword_listbox.insert(tk.END, keyword)
        if not self.keyword_listbox_visible:
            self.keyword_listbox.pack(side=tk.LEFT, padx=5)
            self.keyword_listbox_visible = True
        # Возвращаем фокус на поле ввода
        self.work_desc_entry.focus_set()

    def hide_keyword_listbox(self):
        """Скрыть список ключевых слов"""
        if self.keyword_listbox_visible:
            self.keyword_listbox.pack_forget()
            self.keyword_listbox_visible = False

    def on_keyword_select(self, event):
        """Обработчик выбора ключевого слова из списка"""
        selection = self.keyword_listbox.curselection()
        if selection:
            keyword = self.keyword_listbox.get(selection[0])

            # Получаем весь текст для проверки дубликатов
            try:
                full_text = self.work_desc_entry.get("1.0", tk.END).lower()
            except:
                return

            # Проверяем, есть ли уже это слово в тексте
            if keyword.lower() in full_text:
                messagebox.showinfo("Внимание", f"Слово '{keyword}' уже используется!")
                self.hide_keyword_listbox()
                self.work_desc_entry.focus_set()
                return

            # Получаем текущий текст и позицию курсора
            try:
                text = self.work_desc_entry.get("1.0", "insert")
            except:
                return

            # Находим последнее слово и заменяем его
            words = re.split(r'([\s,\n]+)', text)
            if words:
                # Удаляем последнее непустое слово
                while words and (not words[-1] or re.match(r'^[\s,\n]+$', words[-1])):
                    words.pop()
                if words:
                    words.pop()  # Удаляем последнее слово

            # Собираем новый текст с запятой после ключевого слова
            new_text = ''.join(words) + keyword + ", "

            # Заменяем текст в поле
            self.work_desc_entry.delete("1.0", tk.END)
            self.work_desc_entry.insert("1.0", new_text)

            # Перемещаем курсор в конец
            self.work_desc_entry.see(tk.END)

            self.hide_keyword_listbox()

    def on_description_focus_out(self, event):
        """Скрыть список при потере фокуса"""
        def check_and_hide():
            # Проверяем, что фокус не в keyword_listbox и не в work_desc_entry
            try:
                focused = self.root.focus_get()
                if focused != self.keyword_listbox and focused != self.work_desc_entry._textbox:
                    self.hide_keyword_listbox()
            except:
                self.hide_keyword_listbox()
        self.root.after(200, check_and_hide)

    def refresh_workers_combo(self):
        """Обновить выпадающий список работников"""
        workers = self.db.get_all_workers()
        self.workers_data = {w[1]: w[0] for w in workers}
        worker_names = list(self.workers_data.keys())
        self.worker_combo.configure(values=worker_names)
        if workers:
            self.worker_combo.set(worker_names[0])

    def add_part_to_list(self):
        """Добавить запчасть в список"""
        part_name = self.part_name_entry.get().strip()
        if not part_name:
            messagebox.showwarning("Внимание", "Введите название запчасти!")
            return

        try:
            part_price = float(self.part_price_entry.get().replace(',', '.'))
            if part_price <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную цену запчасти!")
            return

        # Добавляем в список
        self.parts_list.append((part_name, part_price))

        # Обновляем таблицу
        self.parts_tree.insert("", tk.END, values=(part_name, self.format_currency(part_price)))

        # Очищаем поля ввода
        self.part_name_entry.delete(0, tk.END)
        self.part_price_entry.delete(0, tk.END)

        # Обновляем общую стоимость
        self.update_total_cost()

    def remove_part_from_list(self):
        """Удалить запчасть из списка"""
        selected = self.parts_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите запчасть для удаления!")
            return

        # Получаем индекс выбранного элемента
        item_index = self.parts_tree.index(selected[0])

        # Удаляем из списка
        del self.parts_list[item_index]

        # Удаляем из таблицы
        self.parts_tree.delete(selected[0])

        # Обновляем общую стоимость
        self.update_total_cost()

    def update_total_cost(self):
        """Обновить общую стоимость работы + запчасти"""
        # Метод оставлен для совместимости, но больше ничего не отображает
        pass

    def add_work(self):
        """Добавить или обновить запись о работе"""
        if not self.worker_combo.get():
            messagebox.showwarning("Внимание", "Выберите мастера!")
            return

        description = self.work_desc_entry.get("1.0", "end-1c").strip()
        if not description:
            messagebox.showwarning("Внимание", "Введите описание работы!")
            return

        try:
            amount = float(self.amount_entry.get().replace(',', '.'))
            if amount <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную сумму!")
            return

        worker_id = self.workers_data[self.worker_combo.get()]
        car_brand = self.car_brand_entry.get().strip()
        car_model = self.car_model_entry.get().strip()
        car_number = self.car_number_entry.get().strip().upper()
        mileage = self.mileage_entry.get().strip()
        vin = self.vin_entry.get().strip().upper()

        # Проверяем, редактируем ли существующую запись
        if hasattr(self, 'editing_work_id') and self.editing_work_id:
            # Получаем оригинальную дату записи
            original_work = self.db.get_work_by_id(self.editing_work_id)
            if original_work:
                work_date = original_work[5]  # work_date из оригинальной записи
                if hasattr(work_date, 'strftime'):
                    work_date = work_date.strftime('%Y-%m-%d')
            else:
                work_date = datetime.now().strftime('%Y-%m-%d')

            # Обновляем запись
            self.db.update_work(self.editing_work_id, worker_id, description, amount, work_date, car_brand, car_model, car_number, mileage, vin)

            # Удаляем старые запчасти и добавляем новые
            self.db.delete_parts_by_work_id(self.editing_work_id)
            if self.parts_list:
                self.db.add_parts(self.editing_work_id, self.parts_list)

            messagebox.showinfo("Успех", "Запись обновлена!")

            # Сбрасываем режим редактирования
            self.editing_work_id = None
        else:
            # Автоматически используем текущую дату для новой записи
            work_date = datetime.now().strftime('%Y-%m-%d')

            # Добавляем работу и получаем ID
            work_id = self.db.add_work(worker_id, description, amount, work_date, car_brand, car_model, car_number, mileage, vin)

            # Если есть запчасти - сохраняем их
            if self.parts_list:
                self.db.add_parts(work_id, self.parts_list)

            messagebox.showinfo("Успех", "Запись добавлена!")

        # Очищаем форму
        self.work_desc_entry.delete("1.0", "end")
        self.amount_entry.delete(0, tk.END)
        self.car_brand_entry.delete(0, tk.END)
        self.car_model_entry.delete(0, tk.END)
        self.car_number_entry.delete(0, tk.END)
        self.mileage_entry.delete(0, tk.END)
        self.vin_entry.delete(0, tk.END)

        # Очищаем список запчастей
        self.parts_list = []
        for item in self.parts_tree.get_children():
            self.parts_tree.delete(item)

        # Обновляем общую стоимость
        self.update_total_cost()

    # ===== ВКЛАДКА ОТЧЁТОВ =====

    def setup_reports_tab(self):
        """Настройка вкладки отчётов"""
        # Выбор периода
        period_frame = ctk.CTkFrame(self.reports_frame)
        period_frame.pack(fill=tk.X, padx=10, pady=10)
        title = ctk.CTkLabel(
            period_frame,
            text="Выберите период",
            font=("Segoe UI", 20, "bold"),
            anchor="center"
        )

        title.pack(fill=tk.X, pady=(0, 10))

        dates_frame = ctk.CTkFrame(period_frame)
        dates_frame.pack()

        ctk.CTkLabel(dates_frame, text="С:").pack(side=tk.LEFT, padx=5)
        self.date_from = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy',
                                    locale='ru_RU')
        self.date_from.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(dates_frame, text="По:").pack(side=tk.LEFT, padx=15)
        self.date_to = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy',
                                  locale='ru_RU')
        self.date_to.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(dates_frame, text="% мастеру:").pack(side=tk.LEFT, padx=(20, 5))
        settings = self.load_settings()
        self.percent_var = tk.StringVar(value=str(settings.get('master_percent', 50)))
        self.percent_var.trace_add('write', self.on_percent_changed)
        self.percent_entry = ctk.CTkEntry(dates_frame, width=80,
                                          textvariable=self.percent_var, fg_color="white", text_color="black")
        self.percent_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkLabel(dates_frame, text="%").pack(side=tk.LEFT)

        ctk.CTkButton(dates_frame, text="Сформировать отчёт",
                   command=self.generate_report).pack(side=tk.LEFT, padx=20)

        # Сводка по работникам
        summary_frame = ctk.CTkFrame(self.reports_frame)
        summary_frame.pack(fill=tk.X, padx=10, pady=10)
        title_masters = ctk.CTkLabel(
            summary_frame,
            text="Сводка по мастерам",
            font=("Segoe UI", 20, "bold"),
            anchor="center")
        title_masters.pack(fill=tk.X, pady=(0, 10))

        columns = ("name", "count", "total", "percent")
        self.summary_tree = ttk.Treeview(summary_frame, columns=columns, show="headings", height=6)
        self.summary_tree.heading("name", text="ФИО мастера")
        self.summary_tree.heading("count", text="Кол-во работ")
        self.summary_tree.heading("total", text="Итого заработано")
        self.summary_tree.heading("percent", text="% мастеру")

        self.summary_tree.column("name", width=250)
        self.summary_tree.column("count", width=100, anchor=tk.CENTER)
        self.summary_tree.column("total", width=140, anchor=tk.CENTER)
        self.summary_tree.column("percent", width=120, anchor=tk.CENTER)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.summary_tree.tag_configure('oddrow', background='#ffffff')
        self.summary_tree.tag_configure('evenrow', background='#f0f0f0')

        self.summary_tree.pack(fill=tk.X)

        # Общая сумма - фрейм с разноцветными label-ами
        self.total_frame = ctk.CTkFrame(summary_frame)
        self.total_frame.pack(pady=10)

        # Зелёный цвет для доходов/прибыли, красный для расходов
        green_color = "#2e7d32"
        red_color = "#c62828"

        # Загружаем процент из настроек для начального отображения
        settings = self.load_settings()
        initial_percent = settings.get('master_percent', 50)

        self.income_label = ctk.CTkLabel(self.total_frame, text="ДОХОД (работы): 0,00 руб.",
                                        font=("Arial", 12, "bold"), text_color=green_color)
        self.income_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.other_income_label = ctk.CTkLabel(self.total_frame, text="Прочий доход: 0,00 руб.",
                                              font=("Arial", 12, "bold"), text_color=green_color)
        self.other_income_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.expenses_label = ctk.CTkLabel(self.total_frame, text="РАСХОДЫ: 0,00 руб.",
                                          font=("Arial", 12, "bold"), text_color=red_color)
        self.expenses_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.masters_label = ctk.CTkLabel(self.total_frame, text=f"Мастерам ({initial_percent:.0f}%): 0,00 руб.",
                                         font=("Arial", 12, "bold"), text_color=red_color)
        self.masters_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.profit_label = ctk.CTkLabel(self.total_frame, text="ЧИСТАЯ ПРИБЫЛЬ: 0,00 руб.",
                                        font=("Arial", 12, "bold"), text_color=green_color)
        self.profit_label.pack(side=tk.LEFT, padx=5)

        # Tooltip для "Прочий доход" и "РАСХОДЫ"
        self.other_income_tooltip = LabelTooltip(self.other_income_label, self.format_currency, is_expense=False)
        self.expenses_tooltip = LabelTooltip(self.expenses_label, self.format_currency, is_expense=True)

        # История (детальный отчёт)
        detail_frame = ctk.CTkFrame(self.reports_frame)
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        title = ctk.CTkLabel(
            detail_frame,
            text="История",
            font=("Segoe UI", 20, "bold"),
            anchor="center"
        )
        title.pack(fill=tk.X, pady=(0, 10))

        # Кнопки и поиск
        button_frame = ctk.CTkFrame(detail_frame)
        button_frame.pack(fill=tk.X, pady=5)

        # Левая часть - поиск по госномеру
        search_frame = ctk.CTkFrame(button_frame)
        search_frame.pack(side=tk.LEFT, padx=10)
        ctk.CTkLabel(search_frame, text="Госномер:").pack(side=tk.LEFT, padx=5)
        self.search_car_number_entry = ctk.CTkEntry(search_frame, width=120, fg_color="white", text_color="black")
        self.search_car_number_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(search_frame, text="Поиск", width=80, command=self.search_by_car_number).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(search_frame, text="Сброс", width=80, command=self.reset_search).pack(side=tk.LEFT, padx=5)

        # Правая часть - кнопка формирования листа наряда
        ctk.CTkButton(button_frame, text="Сформировать лист наряд по выбранной записи",
                   command=self.generate_work_order_from_report).pack(side=tk.RIGHT, padx=10)

        columns = ("order_num", "name", "car", "desc", "amount", "parts", "parts_price", "date")
        self.report_tree = ttk.Treeview(detail_frame, columns=columns, show="headings", height=12)

        # Заголовки с сортировкой
        for col, text in [("order_num", "№ заказа"), ("name", "Мастер"), ("car", "Машина"),
                          ("desc", "Выполненная работа"), ("amount", "Сумма работ"),
                          ("parts", "Количество запчастей"), ("parts_price", "Цена запчастей"), ("date", "Дата")]:
            self.report_tree.heading(col, text=text, command=lambda c=col: self.sort_report_tree(c))

        self.report_sort_reverse = {}  # Для отслеживания направления сортировки

        self.report_tree.column("order_num", width=80, anchor=tk.CENTER)
        self.report_tree.column("name", width=100)
        self.report_tree.column("car", width=120)
        self.report_tree.column("desc", width=180)
        self.report_tree.column("amount", width=5, anchor=tk.CENTER)
        self.report_tree.column("parts", width=5)
        self.report_tree.column("parts_price", width=5, anchor=tk.CENTER)
        self.report_tree.column("date", width=5, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.report_tree.yview)
        self.report_tree.configure(yscrollcommand=scrollbar.set)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.report_tree.tag_configure('oddrow', background='#ffffff')
        self.report_tree.tag_configure('evenrow', background='#f0f0f0')
        self.report_tree.tag_configure('part', background='#e8e8e8', foreground='#555555')

        # Tooltip для колонки "Выполненная работа"
        self.report_tooltip = TreeviewTooltip(self.report_tree, columns=['desc'])

        self.report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Контекстное меню для редактирования записей
        self.report_context_menu = tk.Menu(self.report_tree, tearoff=0)
        self.report_context_menu.add_command(label="Редактировать", command=self.edit_work_from_report)
        self.report_tree.bind('<Button-3>', self.show_report_context_menu)

        # Словарь для хранения work_id по item_id
        self.report_work_ids = {}

        # Переменная для режима редактирования
        self.editing_work_id = None

    def show_report_context_menu(self, event):
        """Показать контекстное меню для записи в истории"""
        # Выбираем элемент под курсором
        item = self.report_tree.identify_row(event.y)
        if item:
            self.report_tree.selection_set(item)
            # Проверяем, что это не запчасть (дочерний элемент)
            parent = self.report_tree.parent(item)
            if not parent:  # Это основная запись, не запчасть
                self.report_context_menu.post(event.x_root, event.y_root)

    def edit_work_from_report(self):
        """Редактировать выбранную запись из истории"""
        selection = self.report_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запись для редактирования!")
            return

        item_id = selection[0]

        # Проверяем, что это не запчасть
        if self.report_tree.parent(item_id):
            messagebox.showwarning("Внимание", "Выберите основную запись, а не запчасть!")
            return

        # Получаем work_id
        work_id = self.report_work_ids.get(item_id)
        if not work_id:
            messagebox.showerror("Ошибка", "Не удалось найти ID записи!")
            return

        # Получаем полные данные работы из базы
        work = self.db.get_work_by_id(work_id)
        if not work:
            messagebox.showerror("Ошибка", "Запись не найдена в базе данных!")
            return

        # work: (id, worker_id, full_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin)
        _, worker_id, worker_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin = work

        # Устанавливаем режим редактирования
        self.editing_work_id = work_id

        # Очищаем форму
        self.work_desc_entry.delete("1.0", "end")
        self.amount_entry.delete(0, tk.END)
        self.car_brand_entry.delete(0, tk.END)
        self.car_model_entry.delete(0, tk.END)
        self.car_number_entry.delete(0, tk.END)
        self.mileage_entry.delete(0, tk.END)
        self.vin_entry.delete(0, tk.END)

        # Заполняем форму данными
        self.worker_combo.set(worker_name)
        self.work_desc_entry.insert("1.0", description)
        self.amount_entry.insert(0, str(amount))
        if car_brand:
            self.car_brand_entry.insert(0, car_brand)
        if car_model:
            self.car_model_entry.insert(0, car_model)
        if car_number:
            self.car_number_entry.insert(0, car_number)
        if mileage:
            self.mileage_entry.insert(0, mileage)
        if vin:
            self.vin_entry.insert(0, vin)

        # Загружаем запчасти
        self.parts_list = []
        for item in self.parts_tree.get_children():
            self.parts_tree.delete(item)

        work_parts = self.db.get_parts_by_work_id(work_id)
        if work_parts:
            for part_name, part_price in work_parts:
                self.parts_list.append((part_name, float(part_price)))
                self.parts_tree.insert("", tk.END, values=(part_name, self.format_currency(float(part_price))))

        self.update_total_cost()

        # Переключаемся на вкладку "Добавить работу"
        self.notebook.set("Добавить работу")

        messagebox.showinfo("Редактирование", f"Загружена запись для редактирования.\nПосле внесения изменений нажмите 'Добавить запись' для сохранения.")

    def search_by_car_number(self):
        """Поиск записей по госномеру"""
        car_number = self.search_car_number_entry.get().strip()
        if not car_number:
            messagebox.showwarning("Внимание", "Введите госномер для поиска!")
            return

        # Очищаем таблицу
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)
        self.report_work_ids = {}

        # Получаем записи по госномеру
        works = self.db.get_works_by_car_number(car_number)

        row_index = 0
        for row in works:
            work_id, name, desc, amount, work_date, car_brand, car_model, car_number_db, order_number = row
            amount = float(amount)

            if isinstance(work_date, str):
                display_date = datetime.strptime(work_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            else:
                display_date = work_date.strftime('%d.%m.%Y')

            car_info = ""
            if car_brand or car_model or car_number_db:
                parts = [car_brand or '', car_model or '', car_number_db or '']
                car_info = ' '.join(p for p in parts if p)

            work_parts = self.db.get_parts_by_work_id(work_id)
            parts_total = 0
            if work_parts:
                for part_name, part_price in work_parts:
                    parts_total += float(part_price)

            row_tag = 'oddrow' if row_index % 2 == 0 else 'evenrow'

            parent_id = self.report_tree.insert("", tk.END, values=(
                order_number or "-",
                name,
                car_info,
                desc,
                self.format_currency(amount),
                f"Запчастей: {len(work_parts) if work_parts else 0}",
                self.format_currency(parts_total) if parts_total > 0 else "-",
                display_date
            ), tags=(row_tag,))

            self.report_work_ids[parent_id] = work_id

            if work_parts:
                for part_name, part_price in work_parts:
                    self.report_tree.insert(parent_id, tk.END, values=(
                        "",
                        "",
                        "",
                        f"  └─ {part_name}",
                        "",
                        "",
                        self.format_currency(part_price),
                        ""
                    ), tags=('part',))

            row_index += 1

        if not works:
            messagebox.showinfo("Информация", f"Записей с госномером '{car_number}' не найдено.")

    def reset_search(self):
        """Сбросить поиск и показать записи за период"""
        self.search_car_number_entry.delete(0, tk.END)
        self.generate_report()

    def sort_report_tree(self, col):
        """Сортировка таблицы истории по столбцу"""
        # Получаем только родительские элементы (не запчасти)
        items = [(self.report_tree.set(item, col), item) for item in self.report_tree.get_children('')
                 if not self.report_tree.parent(item)]

        # Определяем направление сортировки
        reverse = self.report_sort_reverse.get(col, False)

        # Специальная сортировка для разных типов данных
        def sort_key(x):
            val = x[0]
            if col == "amount" or col == "parts_price":
                # Убираем "руб." и форматирование для числовой сортировки
                try:
                    clean = val.replace(' руб.', '').replace('.', '').replace(',', '.').replace('-', '0')
                    return float(clean)
                except:
                    return 0
            elif col == "date":
                # Сортировка по дате
                try:
                    return datetime.strptime(val, '%d.%m.%Y')
                except:
                    return datetime.min
            elif col == "parts":
                # Извлекаем число из "Запчастей: X"
                try:
                    return int(val.replace('Запчастей: ', ''))
                except:
                    return 0
            elif col == "order_num":
                # Числовая сортировка для номера заказа
                try:
                    return int(val) if val != "-" else 0
                except:
                    return 0
            else:
                return val.lower() if val else ""

        items.sort(key=sort_key, reverse=reverse)

        # Перемещаем элементы в новом порядке
        for index, (val, item) in enumerate(items):
            self.report_tree.move(item, '', index)

        # Меняем направление для следующего клика
        self.report_sort_reverse[col] = not reverse

    def generate_report(self, show_empty_message=True):
        """Сформировать отчёт за период"""
        date_from = self.date_from.get_date().strftime('%Y-%m-%d')
        date_to = self.date_to.get_date().strftime('%Y-%m-%d')

        if date_from > date_to:
            messagebox.showwarning("Внимание", "Дата 'С' не может быть больше даты 'По'!")
            return

        # Получаем процент
        try:
            percent = float(self.percent_var.get().replace(',', '.'))
            if percent < 0 or percent > 100:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректный процент (0-100)!")
            return

        # Очистка таблиц
        for item in self.summary_tree.get_children():
            self.summary_tree.delete(item)
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)

        # Очищаем словарь work_id
        self.report_work_ids = {}

        # Сводка
        summary = self.db.get_summary_by_period(date_from, date_to)
        grand_total = 0
        total_percent_sum = 0
        summary_row_index = 0
        for row in summary:
            name, total, count = row
            total = float(total)  # MariaDB возвращает Decimal
            grand_total += total
            worker_share = total * percent / 100
            total_percent_sum += worker_share

            # Определяем тег для чередующихся строк
            row_tag = 'oddrow' if summary_row_index % 2 == 0 else 'evenrow'

            self.summary_tree.insert("", tk.END, values=(
                name,
                count,
                self.format_currency(total),
                self.format_currency(worker_share)
            ), tags=(row_tag,))

            summary_row_index += 1

        # Получаем расходы и доходы за период
        total_expenses = float(self.db.get_total_expenses_by_period(date_from, date_to))
        other_income = float(self.db.get_total_income_by_period(date_from, date_to))
        total_income = grand_total + other_income
        net_profit = total_income - total_expenses - total_percent_sum

        # Получаем детальные данные для tooltip
        detailed_expenses = self.db.get_detailed_expenses_by_period(date_from, date_to)
        detailed_income = self.db.get_detailed_income_by_period(date_from, date_to)

        # Обновляем данные для tooltip
        self.expenses_tooltip.set_data(detailed_expenses)
        self.other_income_tooltip.set_data(detailed_income)

        # Обновляем каждый label отдельно
        self.income_label.configure(text=f"ДОХОД (работы): {self.format_currency(grand_total)}")
        self.other_income_label.configure(text=f"Прочий доход: {self.format_currency(other_income)}")
        self.expenses_label.configure(text=f"РАСХОДЫ: {self.format_currency(total_expenses)}")
        self.masters_label.configure(text=f"Мастерам ({percent:.0f}%): {self.format_currency(total_percent_sum)}")

        # Цвет прибыли зависит от значения
        profit_color = "#2e7d32" if net_profit >= 0 else "#c62828"  # Зелёный если >= 0, красный если < 0
        self.profit_label.configure(text=f"ЧИСТАЯ ПРИБЫЛЬ: {self.format_currency(net_profit)}", text_color=profit_color)

        # Детальный отчёт
        works = self.db.get_works_by_period(date_from, date_to)
        row_index = 0
        for row in works:
            work_id, name, desc, amount, work_date, car_brand, car_model, car_number, order_number = row
            amount = float(amount)  # MariaDB возвращает Decimal
            # Преобразование даты для отображения (MariaDB возвращает объекты date)
            if isinstance(work_date, str):
                display_date = datetime.strptime(work_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            else:
                display_date = work_date.strftime('%d.%m.%Y')

            # Формируем строку с информацией о машине
            car_info = ""
            if car_brand or car_model or car_number:
                parts = [car_brand or '', car_model or '', car_number or '']
                car_info = ' '.join(p for p in parts if p)

            # Получаем запчасти для этой работы
            work_parts = self.db.get_parts_by_work_id(work_id)
            parts_total = 0

            if work_parts:
                for part_name, part_price in work_parts:
                    parts_total += float(part_price)

            # Определяем тег для чередующихся строк
            row_tag = 'oddrow' if row_index % 2 == 0 else 'evenrow'

            # Добавляем основную запись о работе
            parent_id = self.report_tree.insert("", tk.END, values=(
                order_number or "-",
                name,
                car_info,
                desc,
                self.format_currency(amount),
                f"Запчастей: {len(work_parts) if work_parts else 0}",
                self.format_currency(parts_total) if parts_total > 0 else "-",
                display_date
            ), tags=(row_tag,))

            # Сохраняем work_id для возможности редактирования
            self.report_work_ids[parent_id] = work_id

            # Добавляем запчасти как дочерние элементы
            if work_parts:
                for part_name, part_price in work_parts:
                    self.report_tree.insert(parent_id, tk.END, values=(
                        "",
                        "",
                        "",
                        f"  └─ {part_name}",
                        "",
                        "",
                        self.format_currency(part_price),
                        ""
                    ), tags=('part',))

            row_index += 1

        if not works and show_empty_message:
            messagebox.showinfo("Информация", "За выбранный период записей не найдено.")

    # ===== ВКЛАДКА МАРОК И МОДЕЛЕЙ =====

    def setup_cars_tab(self):
        """Настройка вкладки марок и моделей"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.cars_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Импорт из файла
        import_frame = ctk.CTkFrame(center_container)
        import_frame.pack(pady=10)

        ctk.CTkLabel(import_frame, text="Формат JSON: {\"Марка\": [\"Модель1\", \"Модель2\"]}", anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text="Импортировать из файла JSON",
                   command=self.import_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление марки
        brand_frame = ctk.CTkFrame(center_container)
        brand_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(brand_frame, text="Название марки:").pack(side=tk.LEFT, padx=5)
        self.brand_name_entry = ctk.CTkEntry(brand_frame, width=300, fg_color="white", text_color="black")
        self.brand_name_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(brand_frame, text="Добавить марку", command=self.add_brand, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Добавление модели
        model_frame = ctk.CTkFrame(center_container)
        model_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(model_frame, text="Марка:").pack(side=tk.LEFT, padx=5)
        self.brand_combo = ctk.CTkComboBox(model_frame, width=250, fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.brand_combo.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(model_frame, text="Модель:").pack(side=tk.LEFT, padx=5)
        self.model_name_entry = ctk.CTkEntry(model_frame, width=200, fg_color="white", text_color="black")
        self.model_name_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(model_frame, text="Добавить модель", command=self.add_model, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список марок и моделей
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        # Две колонки: марки и модели
        left_frame = ctk.CTkFrame(list_frame)
        left_frame.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(left_frame, text="Марки:", anchor="w").pack(anchor=tk.W)
        self.brands_listbox = tk.Listbox(left_frame, height=15, width=35)
        self.brands_listbox.pack()
        self.brands_listbox.bind('<<ListboxSelect>>', self.on_brand_listbox_select)
        ctk.CTkButton(left_frame, text="Удалить марку", command=self.delete_brand, width=250, fg_color="red", hover_color="darkred").pack(pady=5)

        right_frame = ctk.CTkFrame(list_frame)
        right_frame.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(right_frame, text="Модели выбранной марки:", anchor="w").pack(anchor=tk.W)
        self.models_listbox = tk.Listbox(right_frame, height=15, width=35)
        self.models_listbox.pack()
        ctk.CTkButton(right_frame, text="Удалить модель", command=self.delete_model, width=250, fg_color="red", hover_color="darkred").pack(pady=5)

        # Загружаем данные
        self.refresh_brands_list()

    def refresh_brands_list(self):
        """Обновить список марок"""
        self.brands_listbox.delete(0, tk.END)
        brands = self.db.get_all_car_brands()
        self.brands_data = {brand[1]: brand[0] for brand in brands}

        for brand_name in sorted(self.brands_data.keys()):
            self.brands_listbox.insert(tk.END, brand_name)

        # Обновить комбобокс
        sorted_brands = sorted(self.brands_data.keys())
        self.brand_combo.configure(values=sorted_brands)

        # Установить первую марку по умолчанию
        if sorted_brands:
            self.brand_combo.set(sorted_brands[0])

    def on_brand_listbox_select(self, event):
        """Обработчик выбора марки"""
        selection = self.brands_listbox.curselection()
        if not selection:
            return

        brand_name = self.brands_listbox.get(selection[0])
        brand_id = self.brands_data[brand_name]

        # Загружаем модели
        self.models_listbox.delete(0, tk.END)
        models = self.db.get_car_models_by_brand(brand_id)
        self.models_data = {model[1]: model[0] for model in models}

        for model_name in sorted(self.models_data.keys()):
            self.models_listbox.insert(tk.END, model_name)

    def add_brand(self):
        """Добавить марку"""
        brand_name = self.brand_name_entry.get().strip()
        if not brand_name:
            messagebox.showwarning("Внимание", "Введите название марки!")
            return

        if self.db.add_car_brand(brand_name):
            messagebox.showinfo("Успех", f"Марка '{brand_name}' добавлена!")
            self.brand_name_entry.delete(0, tk.END)
            self.refresh_brands_list()
        else:
            messagebox.showerror("Ошибка", "Такая марка уже существует!")

    def add_model(self):
        """Добавить модель"""
        if not self.brand_combo.get():
            messagebox.showwarning("Внимание", "Выберите марку!")
            return

        model_name = self.model_name_entry.get().strip()
        if not model_name:
            messagebox.showwarning("Внимание", "Введите название модели!")
            return

        brand_id = self.brands_data[self.brand_combo.get()]

        if self.db.add_car_model(brand_id, model_name):
            messagebox.showinfo("Успех", f"Модель '{model_name}' добавлена!")
            self.model_name_entry.delete(0, tk.END)
            # Обновляем список моделей если выбрана эта марка
            selection = self.brands_listbox.curselection()
            if selection and self.brands_listbox.get(selection[0]) == self.brand_combo.get():
                self.on_brand_listbox_select(None)
        else:
            messagebox.showerror("Ошибка", "Такая модель для этой марки уже существует!")

    def delete_brand(self):
        """Удалить марку"""
        selection = self.brands_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите марку для удаления!")
            return

        brand_name = self.brands_listbox.get(selection[0])
        brand_id = self.brands_data[brand_name]

        if messagebox.askyesno("Подтверждение",
                               f"Удалить марку '{brand_name}'?\n\nВсе модели этой марки также будут удалены!"):
            self.db.delete_car_brand(brand_id)
            messagebox.showinfo("Успех", "Марка удалена!")
            self.refresh_brands_list()
            self.models_listbox.delete(0, tk.END)

    def delete_model(self):
        """Удалить модель"""
        selection = self.models_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите модель для удаления!")
            return

        model_name = self.models_listbox.get(selection[0])
        model_id = self.models_data[model_name]

        if messagebox.askyesno("Подтверждение", f"Удалить модель '{model_name}'?"):
            self.db.delete_car_model(model_id)
            messagebox.showinfo("Успех", "Модель удалена!")
            # Обновляем список моделей
            brand_selection = self.brands_listbox.curselection()
            if brand_selection:
                self.on_brand_listbox_select(None)

    def import_from_file(self):
        """Импорт марок и моделей из JSON файла"""
        file_path = filedialog.askopenfilename(
            title="Выберите JSON файл",
            filetypes=[("JSON файлы", "*.json"), ("Все файлы", "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                messagebox.showerror("Ошибка", "Неверный формат файла! Ожидается словарь {\"Марка\": [\"Модель1\", ...]}")
                return

            added_brands, added_models = self.db.import_brands_models_from_dict(data)
            messagebox.showinfo("Успех",
                              f"Импорт завершён!\n\nДобавлено марок: {added_brands}\nДобавлено моделей: {added_models}")
            self.refresh_brands_list()

        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Ошибка чтения JSON файла!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка импорта: {str(e)}")

    # ===== ВКЛАДКА КЛЮЧЕВЫХ СЛОВ =====

    def setup_keywords_tab(self):
        """Настройка вкладки ключевых слов"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.keywords_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Заголовок
        ctk.CTkLabel(center_container, text="Ключевые слова для автодополнения",
                    font=("Segoe UI", 16, "bold")).pack(pady=10)

        # Импорт из файла
        import_frame = ctk.CTkFrame(center_container)
        import_frame.pack(pady=10)

        ctk.CTkLabel(import_frame, text="Формат: текстовый файл (каждое слово на новой строке) или JSON (список слов)", anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text="Импортировать из файла",
                   command=self.import_keywords_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление ключевого слова
        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(add_frame, text="Ключевое слово:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.keyword_entry = ctk.CTkEntry(add_frame, width=350, fg_color="white", text_color="black")
        self.keyword_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(add_frame, text="Добавить", command=self.add_keyword_action,
                     fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список ключевых слов
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        ctk.CTkLabel(list_frame, text="Список ключевых слов:", anchor="w").pack(anchor=tk.W)

        # Treeview для ключевых слов
        columns = ("id", "keyword")
        self.keywords_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.keywords_tree.heading("id", text="ID")
        self.keywords_tree.heading("keyword", text="Ключевое слово")
        self.keywords_tree.column("id", width=50, anchor=tk.CENTER)
        self.keywords_tree.column("keyword", width=450, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.keywords_tree.yview)
        self.keywords_tree.configure(yscrollcommand=scrollbar.set)

        self.keywords_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        ctk.CTkButton(center_container, text="Удалить выбранное ключевое слово",
                     command=self.delete_keyword_action, width=500,
                     fg_color="red", hover_color="darkred").pack(pady=10)

    def refresh_keywords_list(self):
        """Обновить список ключевых слов"""
        for item in self.keywords_tree.get_children():
            self.keywords_tree.delete(item)

        for keyword_id, keyword in self.db.get_all_keywords():
            self.keywords_tree.insert("", tk.END, values=(keyword_id, keyword))

    def add_keyword_action(self):
        """Добавить ключевое слово"""
        keyword = self.keyword_entry.get().strip()
        if not keyword:
            messagebox.showwarning("Внимание", "Введите ключевое слово!")
            return

        if self.db.add_keyword(keyword):
            messagebox.showinfo("Успех", f"Ключевое слово '{keyword}' добавлено!")
            self.keyword_entry.delete(0, tk.END)
            self.refresh_keywords_list()
        else:
            messagebox.showerror("Ошибка", "Такое ключевое слово уже существует!")

    def delete_keyword_action(self):
        """Удалить ключевое слово"""
        selected = self.keywords_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите ключевое слово для удаления!")
            return

        item = self.keywords_tree.item(selected[0])
        keyword_id = item['values'][0]
        keyword = item['values'][1]

        if messagebox.askyesno("Подтверждение", f"Удалить ключевое слово '{keyword}'?"):
            self.db.delete_keyword(keyword_id)
            messagebox.showinfo("Успех", "Ключевое слово удалено!")
            self.refresh_keywords_list()

    def import_keywords_from_file(self):
        """Импорт ключевых слов из файла (TXT или JSON)"""
        file_path = filedialog.askopenfilename(
            title="Выберите файл",
            filetypes=[("Текстовые файлы", "*.txt"), ("JSON файлы", "*.json"), ("Все файлы", "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Определяем формат файла
            keywords = []
            if file_path.lower().endswith('.json'):
                data = json.loads(content)
                if isinstance(data, list):
                    keywords = data
                else:
                    messagebox.showerror("Ошибка", "Неверный формат JSON! Ожидается список слов: ['слово1', 'слово2']")
                    return
            else:
                # Текстовый файл - каждое слово на новой строке
                keywords = content.strip().splitlines()

            if not keywords:
                messagebox.showwarning("Внимание", "Файл пустой или не содержит ключевых слов!")
                return

            added = self.db.import_keywords_from_list(keywords)
            messagebox.showinfo("Успех", f"Импорт завершён! Добавлено ключевых слов: {added}")
            self.refresh_keywords_list()

        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Ошибка чтения JSON файла!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка импорта: {str(e)}")

    # ===== ВКЛАДКА РАСХОДОВ =====

    def setup_expenses_tab(self):
        """Настройка вкладки расходов"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.expenses_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Переключатель Расход/Доход
        switch_row = ctk.CTkFrame(center_container)
        switch_row.pack(fill=tk.X, pady=10)

        self.expense_type_label = ctk.CTkLabel(switch_row, text="Расход", width=80, anchor="e",
                                                font=("Segoe UI", 14, "bold"), text_color="#d32f2f")
        self.expense_type_label.pack(side=tk.LEFT, padx=5)

        self.is_income_var = tk.BooleanVar(value=False)
        self.income_switch = ctk.CTkSwitch(switch_row, text="", variable=self.is_income_var,
                                           command=self.on_income_switch_changed,
                                           width=50, height=26,
                                           progress_color="#4caf50", button_color="white",
                                           fg_color="#d32f2f", button_hover_color="#f0f0f0")
        self.income_switch.pack(side=tk.LEFT, padx=10)

        self.income_type_label = ctk.CTkLabel(switch_row, text="Доход", width=80, anchor="w",
                                               font=("Segoe UI", 14), text_color="gray")
        self.income_type_label.pack(side=tk.LEFT, padx=5)

        # Категория
        row1 = ctk.CTkFrame(center_container)
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text="Категория:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_category_combo = ctk.CTkComboBox(row1, width=350,
                                                    values=["Аренда", "Налоги", "Коммунальные услуги", "Закупка запчастей",
                                                            "Инструменты", "Реклама", "Прочее", "Доход"],
                                                    fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.expense_category_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.expense_category_combo.set("Аренда")

        # Описание
        row2 = ctk.CTkFrame(center_container)
        row2.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row2, text="Описание:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_desc_entry = ctk.CTkEntry(row2, width=400, fg_color="white", text_color="black")
        self.expense_desc_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Сумма
        row3 = ctk.CTkFrame(center_container)
        row3.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row3, text="Сумма (руб.):", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_amount_entry = ctk.CTkEntry(row3, width=200, fg_color="white", text_color="black")
        self.expense_amount_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Дата
        row4 = ctk.CTkFrame(center_container)
        row4.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row4, text="Дата:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_date_entry = DateEntry(row4, width=30, date_pattern='dd.mm.yyyy',
                                             locale='ru_RU')
        self.expense_date_entry.pack(side=tk.LEFT, padx=5)

        # Кнопка добавления
        self.add_expense_btn = ctk.CTkButton(center_container, text='Добавить расход',
                   command=self.add_expense, width=550, height=50, fg_color="#d32f2f", hover_color="#b71c1c")
        self.add_expense_btn.pack(anchor=tk.CENTER, pady=20)

        # История расходов и доходов
        history_frame = ctk.CTkFrame(center_container)
        history_frame.pack(pady=10)

        columns = ("id", "type", "category", "desc", "amount", "date")
        self.expenses_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=12)
        self.expenses_tree.heading("id", text="ID")
        self.expenses_tree.heading("type", text="Тип")
        self.expenses_tree.heading("category", text="Категория")
        self.expenses_tree.heading("desc", text="Описание")
        self.expenses_tree.heading("amount", text="Сумма")
        self.expenses_tree.heading("date", text="Дата")

        self.expenses_tree.column("id", width=50, anchor=tk.CENTER)
        self.expenses_tree.column("type", width=80, anchor=tk.CENTER)
        self.expenses_tree.column("category", width=150, anchor=tk.W)
        self.expenses_tree.column("desc", width=250, anchor=tk.W)
        self.expenses_tree.column("amount", width=100, anchor=tk.CENTER)
        self.expenses_tree.column("date", width=100, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=self.expenses_tree.yview)
        self.expenses_tree.configure(yscrollcommand=scrollbar.set)

        # Настройка цветов для строк
        self.expenses_tree.tag_configure('oddrow', background='#ffffff')
        self.expenses_tree.tag_configure('evenrow', background='#f0f0f0')
        self.expenses_tree.tag_configure('income', background='#e8f5e9')
        self.expenses_tree.tag_configure('expense', background='#ffebee')

        self.expenses_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        self.delete_expense_btn = ctk.CTkButton(center_container, text="Удалить выбранную запись",
                   command=self.delete_expense, width=550, fg_color="red", hover_color="#555555")
        self.delete_expense_btn.pack(anchor=tk.CENTER, pady=10)

    def on_income_switch_changed(self):
        """Обработчик переключения расход/доход"""
        is_income = self.is_income_var.get()
        if is_income:
            self.expense_type_label.configure(text_color="gray", font=("Segoe UI", 14))
            self.income_type_label.configure(text_color="#4caf50", font=("Segoe UI", 14, "bold"))
            self.add_expense_btn.configure(text="Добавить доход", fg_color="#4caf50", hover_color="#388e3c")
        else:
            self.expense_type_label.configure(text_color="#d32f2f", font=("Segoe UI", 14, "bold"))
            self.income_type_label.configure(text_color="gray", font=("Segoe UI", 14))
            self.add_expense_btn.configure(text="Добавить расход", fg_color="#d32f2f", hover_color="#b71c1c")

    def add_expense(self):
        """Добавить расход или доход"""
        category = self.expense_category_combo.get().strip()
        if not category:
            messagebox.showwarning("Внимание", "Выберите категорию!")
            return

        description = self.expense_desc_entry.get().strip()
        is_income = self.is_income_var.get()
        if not description:
            messagebox.showwarning("Внимание", f"Введите описание {'дохода' if is_income else 'расхода'}!")
            return

        try:
            amount = float(self.expense_amount_entry.get().replace(',', '.'))
            if amount <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную сумму!")
            return

        expense_date = self.expense_date_entry.get_date().strftime('%Y-%m-%d')

        self.db.add_expense(description, amount, expense_date, category, is_income)

        messagebox.showinfo("Успех", f"{'Доход' if is_income else 'Расход'} добавлен!")
        self.expense_desc_entry.delete(0, tk.END)
        self.expense_amount_entry.delete(0, tk.END)
        self.refresh_expenses()

    def refresh_expenses(self):
        """Обновить список расходов и доходов"""
        for item in self.expenses_tree.get_children():
            self.expenses_tree.delete(item)

        row_index = 0
        for row in self.db.get_recent_expenses():
            expense_id, desc, amount, expense_date, category, is_income = row
            amount = float(amount)  # MariaDB возвращает Decimal
            # MariaDB возвращает даты как объекты date
            if isinstance(expense_date, str):
                display_date = datetime.strptime(expense_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            else:
                display_date = expense_date.strftime('%d.%m.%Y')

            # Определяем тип записи и тег
            type_text = "Доход" if is_income else "Расход"
            row_tag = 'income' if is_income else 'expense'

            self.expenses_tree.insert("", tk.END, values=(
                expense_id,
                type_text,
                category,
                desc,
                self.format_currency(amount),
                display_date
            ), tags=(row_tag,))

            row_index += 1

    def delete_expense(self):
        """Удалить расход или доход"""
        selected = self.expenses_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите запись для удаления!")
            return

        item = self.expenses_tree.item(selected[0])
        expense_id = item['values'][0]
        type_text = item['values'][1]
        description = item['values'][3]

        if messagebox.askyesno("Подтверждение", f"Удалить {type_text.lower()} '{description}'?"):
            self.db.delete_expense(expense_id)
            messagebox.showinfo("Успех", f"{type_text} удалён!")
            self.refresh_expenses()

    # ===== QR-КОД С ТЕКСТОМ =====

    def generate_work_order_from_report(self):
        """Сформировать лист наряд с QR-кодом"""
        self._generate_work_order(self.report_tree)

    def _generate_work_order(self, tree):
        """Общая функция формирования листа наряда"""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите запись для формирования листа наряда!")
            return

        # Получаем данные из выбранной строки
        item = tree.item(selected[0])

        # Если выбрана запчасть (дочерний элемент), получаем родительскую запись
        parent = tree.parent(selected[0])
        if parent:
            # Это запчасть, берем данные из родительской записи
            item = tree.item(parent)

        values = item['values']
        order_num = values[0]
        worker_name = values[1]
        car_info = values[2]
        description = values[3]
        amount_str = values[4]
        parts_str = values[5]
        parts_price_str = values[6]
        date_str = values[7]

        # Находим работу в базе данных по этим параметрам
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Преобразуем дату обратно в формат БД
        work_date = datetime.strptime(date_str, '%d.%m.%Y').strftime('%Y-%m-%d')

        # Извлекаем сумму из форматированной строки
        amount = float(amount_str.replace(' руб.', '').replace('.', '').replace(',', '.'))

        # Разбираем информацию о машине
        car_parts = car_info.split() if car_info else []
        car_brand = car_parts[0] if len(car_parts) > 0 else ""
        car_model = car_parts[1] if len(car_parts) > 1 else ""
        car_number = car_parts[2] if len(car_parts) > 2 else ""

        cursor.execute('''
            SELECT wk.id
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE w.full_name = %s AND wk.description = %s AND wk.amount = %s AND wk.work_date = %s
            ORDER BY wk.created_at DESC
            LIMIT 1
        ''', (worker_name, description, amount, work_date))

        result = cursor.fetchone()
        conn.close()

        if not result:
            messagebox.showerror("Ошибка", "Не удалось найти работу в базе данных!")
            return

        work_id = result[0]

        # Получаем полную информацию о работе
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT w.full_name, wk.description, wk.amount, wk.work_date, wk.car_brand, wk.car_model, wk.car_number, wk.order_number
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.id = %s
        ''', (work_id,))
        work = cursor.fetchone()
        conn.close()

        if not work:
            messagebox.showerror("Ошибка", "Запись не найдена!")
            return

        worker_name, description, work_amount, work_date, car_brand, car_model, car_number, order_number = work
        work_amount = float(work_amount)  # MariaDB возвращает Decimal
        # MariaDB возвращает даты как объекты date, а не строки
        if isinstance(work_date, str):
            display_date = datetime.strptime(work_date, '%Y-%m-%d').strftime('%d.%m.%Y')
        else:
            display_date = work_date.strftime('%d.%m.%Y')

        # Получаем запчасти
        parts = self.db.get_parts_by_work_id(work_id)

        # Формируем текст листа наряда
        # Загружаем информацию о компании из настроек
        settings = self.load_settings()
        company_info = settings.get('company_info', '')

        order_text = ""
        if company_info:
            order_text += company_info + "\n\n"
        order_text += "=" * 60 + "\n"
        order_num_str = f" № {order_number}" if order_number else ""
        order_text += f"                      ЛИСТ НАРЯД{order_num_str}\n"
        order_text += "=" * 60 + "\n\n"
        order_text += f"Дата: {display_date}\n"
        order_text += f"Автомобиль: {car_brand} {car_model} {car_number}\n"
        order_text += f"Мастер: {worker_name}\n"
        order_text += "\n" + "-" * 60 + "\n"
        order_text += "ЗАПЧАСТИ:\n"
        order_text += "-" * 60 + "\n"

        parts_total = 0
        if parts:
            for part_name, part_price in parts:
                part_price = float(part_price)
                parts_total += part_price
                # Разбиваем длинное название на строки
                if len(part_name) <= 40:
                    order_text += f"  {part_name:<40} {self.format_currency(part_price):>15}\n"
                else:
                    # Разбиваем название на части по 40 символов
                    lines = []
                    remaining = part_name
                    while remaining:
                        lines.append(remaining[:40])
                        remaining = remaining[40:]

                    # Выводим все строки кроме последней без цены
                    for line in lines[:-1]:
                        order_text += f"  {line:<40}\n"

                    # Последняя строка с ценой
                    order_text += f"  {lines[-1]:<40} {self.format_currency(part_price):>15}\n"
        else:
            order_text += "  Нет запчастей\n"

        order_text += "\n" + "-" * 60 + "\n"
        order_text += "РАБОТЫ:\n"
        order_text += "-" * 60 + "\n"
        # Разбиваем длинное название работы на строки
        if len(description) <= 40:
            order_text += f"  {description:<40} {self.format_currency(work_amount):>15}\n"
        else:
            # Разбиваем название на части по 40 символов
            lines = []
            remaining = description
            while remaining:
                lines.append(remaining[:40])
                remaining = remaining[40:]

            # Выводим все строки кроме последней без цены
            for line in lines[:-1]:
                order_text += f"  {line:<40}\n"

            # Последняя строка с ценой
            order_text += f"  {lines[-1]:<40} {self.format_currency(work_amount):>15}\n"

        order_text += "\n" + "=" * 60 + "\n"
        order_text += "ИТОГО:\n"
        order_text += "=" * 60 + "\n"
        order_text += f"  {'Работы:':<33} {self.format_currency(work_amount):>23}\n"
        order_text += f"  {'Запчасти:':<33} {self.format_currency(parts_total):>23}\n"
        order_text += "-" * 60 + "\n"
        order_text += f"  {'ИТОГО:':<33} {self.format_currency(work_amount + parts_total):>23}\n"
        order_text += "=" * 60 + "\n"

        # Создаем QR-код с текстом листа наряда напрямую (минимальный размер)
        # Используем UTF-8 кодировку для правильного отображения кириллицы
        qr = qrcode.QRCode(version=1, box_size=2, border=1)
        qr.add_data(order_text.encode('utf-8'))
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")

        # Показываем QR-код в новом окне
        self.show_qr_window(qr_image, order_text, car_number, order_number)

    def save_work_order_to_pdf(self, qr_image, order_text, car_number="", order_number=""):
        """Сохранить лист наряд в PDF файл"""
        # Формируем имя файла по умолчанию из номера машины
        default_filename = f"{car_number}.pdf" if car_number else "лист_наряд.pdf"

        # Запрашиваем у пользователя где сохранить файл
        file_path = filedialog.asksaveasfilename(
            title="Сохранить лист наряд как PDF",
            initialfile=default_filename,
            defaultextension=".pdf",
            filetypes=[("PDF файлы", "*.pdf"), ("Все файлы", "*.*")]
        )

        if not file_path:
            return

        try:
            # Создаем PDF
            c = canvas.Canvas(file_path, pagesize=A4)
            width, height = A4

            # Регистрируем шрифт с поддержкой кириллицы
            try:
                font_path = "C:\\Windows\\Fonts\\arial.ttf"
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('Arial', font_path))
                    font_name = "Arial"
                else:
                    font_name = "Courier"
            except:
                font_name = "Courier"

            # Сохраняем QR-код во временный файл
            temp_qr_path = tempfile.mktemp(suffix=".png")
            qr_image.save(temp_qr_path)

            # Параметры форматирования
            margin_left = 50
            margin_right = 50
            margin_top = 50
            margin_bottom = 50

            # Загружаем информацию о компании
            settings = self.load_settings()
            company_info = settings.get('company_info', '')

            # Добавляем информацию о компании в начало
            current_y = height - margin_top
            if company_info:
                c.setFont(font_name, 11)
                for line in company_info.split('\n'):
                    c.drawCentredString(width / 2, current_y, line)
                    current_y -= 16
                current_y -= 10  # Отступ после информации о компании

            # Добавляем заголовок
            c.setFont(font_name, 16)
            title_y = current_y
            title_text = f"ЛИСТ НАРЯД № {order_number}" if order_number else "ЛИСТ НАРЯД"
            c.drawCentredString(width / 2, title_y, title_text)

            # Добавляем QR-код
            qr_size = 150
            qr_x = (width - qr_size) / 2
            qr_y = title_y - qr_size - 20
            c.drawImage(temp_qr_path, qr_x, qr_y, qr_size, qr_size)

            # Добавляем текст листа наряда с увеличенным шрифтом
            c.setFont(font_name, 12)
            text_y = qr_y - 30
            line_height = 18
            max_width = width - margin_left - margin_right

            for line in order_text.split('\n'):
                if text_y < margin_bottom:  # Если место заканчивается, создаем новую страницу
                    c.showPage()
                    c.setFont(font_name, 12)
                    text_y = height - margin_top

                # Если строка слишком длинная, разбиваем её
                if c.stringWidth(line, font_name, 12) > max_width:
                    words = line.split()
                    current_line = ""
                    for word in words:
                        test_line = current_line + " " + word if current_line else word
                        if c.stringWidth(test_line, font_name, 12) <= max_width:
                            current_line = test_line
                        else:
                            if current_line:
                                c.drawString(margin_left, text_y, current_line)
                                text_y -= line_height
                                if text_y < margin_bottom:
                                    c.showPage()
                                    c.setFont(font_name, 12)
                                    text_y = height - margin_top
                            current_line = word
                    if current_line:
                        c.drawString(margin_left, text_y, current_line)
                        text_y -= line_height
                else:
                    c.drawString(margin_left, text_y, line)
                    text_y -= line_height

            # Сохраняем PDF
            c.save()

            # Удаляем временный файл QR-кода
            try:
                os.remove(temp_qr_path)
            except:
                pass

            messagebox.showinfo("Успех", f"Лист наряд сохранён в:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать PDF:\n{str(e)}")

    def show_qr_window(self, qr_image, order_text, car_number="", order_number=""):
        """Показать окно с QR-кодом"""
        qr_window = tk.Toplevel(self.root)
        qr_window.title("QR-код листа наряда")
        qr_window.geometry("600x700")

        # Заголовок
        title_label = ctk.CTkLabel(qr_window, text="Лист наряд сформирован!",
                                font=("Arial", 14, "bold"))
        title_label.pack(pady=10)

        # Инструкция
        info_label = ctk.CTkLabel(qr_window,
                               text="Отсканируйте QR-код для просмотра текста листа наряда",
                               justify=tk.CENTER)
        info_label.pack(pady=5)

        # QR-код
        qr_frame = ctk.CTkFrame(qr_window)
        qr_frame.pack(pady=10)

        # Конвертируем QR-код в формат для Tkinter
        qr_photo = ImageTk.PhotoImage(qr_image)
        qr_label = ctk.CTkLabel(qr_frame, image=qr_photo)
        qr_label.image = qr_photo  # Сохраняем ссылку
        qr_label.pack()

        # Предпросмотр текста
        preview_frame = ctk.CTkFrame(qr_window)
        preview_frame.pack(fill=tk.Y, expand=True, padx=10, pady=10)

        # Вычисляем максимальную ширину строки в тексте
        max_line_length = max(len(line) for line in order_text.split('\n'))
        # Добавляем небольшой запас (2 символа)
        text_width = max_line_length + 2

        text_widget = tk.Text(preview_frame, height=15, width=text_width, font=("Courier New", 9), wrap=tk.NONE)
        text_widget.pack(fill=tk.Y, expand=True)
        text_widget.insert(1.0, order_text)
        text_widget.config(state=tk.DISABLED)

        # Кнопки
        buttons_frame = ctk.CTkFrame(qr_window)
        buttons_frame.pack(pady=10)

        ctk.CTkButton(buttons_frame, text="Сохранить PDF",
                   command=lambda: self.save_work_order_to_pdf(qr_image, order_text, car_number, order_number)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(buttons_frame, text="Закрыть", command=qr_window.destroy).pack(side=tk.LEFT, padx=5)



def main():
    root = ctk.CTk()  # Используем CustomTkinter вместо Tkinter
    app = AutoServiceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()