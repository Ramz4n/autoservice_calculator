# -*- coding: utf-8 -*-
"""
Класс для работы с базой данных MariaDB
"""

import json
import re
import pymysql
from pymysql import Error as MySQLError
from tkinter import messagebox

from db_config import DB_CONFIG
from db_schema import TABLES, INDEXES, MIGRATIONS


def normalize_phone(phone):
    """Привести номер телефона к единому формату +7XXXXXXXXXX"""
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    if len(digits) == 11 and digits.startswith('7'):
        return '+' + digits
    if len(digits) == 10:
        return '+7' + digits
    return '+' + digits if digits else None


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
            conn = pymysql.connect(**self.config)
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
        return pymysql.connect(**self.config)

    def create_tables(self):
        """Создание таблиц в базе данных"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Создаём таблицы из схемы
        for table_name, create_sql in TABLES.items():
            cursor.execute(create_sql)

        # Создаём индексы
        for index_sql in INDEXES:
            try:
                cursor.execute(index_sql)
            except:
                pass

        # Применяем миграции
        for migration_sql in MIGRATIONS:
            try:
                cursor.execute(migration_sql)
            except:
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
        except pymysql.IntegrityError:
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
        except pymysql.IntegrityError:
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
        except pymysql.IntegrityError:
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
        """Поиск марок машин по любой части названия (без учёта регистра)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT brand_name FROM car_brands WHERE LOWER(brand_name) LIKE LOWER(%s) ORDER BY brand_name LIMIT 10",
                      (f"%{search_text}%",))
        brands = [row[0] for row in cursor.fetchall()]
        conn.close()
        return brands

    def search_car_models(self, brand_name, search_text=""):
        """Поиск моделей машин по марке и промежуточным буквам"""
        brand_id = self.get_brand_id_by_name(brand_name)
        if not brand_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()

        if not search_text or search_text == "":
            cursor.execute(
                "SELECT model_name FROM car_models WHERE brand_id = %s ORDER BY model_name",
                (brand_id,)
            )
        else:
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
            except pymysql.IntegrityError:
                cursor.execute("SELECT id FROM car_brands WHERE brand_name = %s", (brand_name,))
                brand_id = cursor.fetchone()[0]

            for model_name in models:
                try:
                    cursor.execute("INSERT INTO car_models (brand_id, model_name) VALUES (%s, %s)",
                                 (brand_id, model_name))
                    added_models += 1
                except pymysql.IntegrityError:
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
            order_number = str(random.randint(10000000, 99999999))
            cursor.execute("SELECT id FROM works WHERE order_number = %s", (order_number,))
            if not cursor.fetchone():
                conn.close()
                return order_number

    def add_work(self, worker_id, description, amount, work_date, mileage="", vin="", booking_id=None, car_id=None, items_json=None):
        """Добавить запись о работе и вернуть ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Преобразуем пробег в число для works.mileage
        mileage_int = None
        if mileage:
            try:
                mileage_int = int(re.sub(r'\D', '', str(mileage)))
            except:
                mileage_int = None

        # Наряд без привязки к записи (клиент "с улицы") добавляется одним действием и
        # никогда не проходит через статус записи "В работе" -> "Выполнено", поэтому для
        # него считаем машину сделанной сразу. Наряд по записи наоборот: его создание
        # переводит запись в статус "В работе" (см. update_booking_status ниже по коду
        # вызывающей стороны) - машина ещё не готова, поэтому completed_at здесь не трогаем
        # и он проставится позже, когда запись отметят "Выполнено" (mark_work_completed).
        completed_at = work_date if not booking_id else None

        # Номер наряда генерируется и проверяется на уникальность отдельным запросом,
        # поэтому при одновременном добавлении с другого ПК возможна гонка - если
        # кто-то успел занять этот номер первым, пробуем ещё раз с новым номером
        for attempt in range(5):
            order_number = self.generate_order_number()
            try:
                cursor.execute(
                    "INSERT INTO works (worker_id, description, amount, work_date, completed_at, order_number, booking_id, car_id, mileage, items_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (worker_id, description, amount, work_date, completed_at, order_number, booking_id, car_id, mileage_int, items_json)
                )
                break
            except pymysql.err.IntegrityError:
                conn.rollback()
                if attempt == 4:
                    conn.close()
                    raise
        work_id = cursor.lastrowid
        if car_id:
            if mileage:
                # Также обновляем последний известный пробег авто
                cursor.execute("UPDATE client_cars SET mileage = %s WHERE id = %s", (mileage, car_id))
            if vin:
                cursor.execute("UPDATE client_cars SET vin = %s WHERE id = %s", (vin, car_id))
        if booking_id and car_id:
            cursor.execute("UPDATE bookings SET car_id = %s WHERE id = %s", (car_id, booking_id))
        conn.commit()
        conn.close()
        return work_id

    def update_work(self, work_id, worker_id, description, amount, work_date, mileage="", vin="", booking_id=None, car_id=None, items_json=None):
        """Обновить запись о работе."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Преобразуем пробег в число для works.mileage
        mileage_int = None
        if mileage:
            try:
                mileage_int = int(re.sub(r'\D', '', str(mileage)))
            except:
                mileage_int = None
        cursor.execute('''
            UPDATE works
            SET worker_id = %s, description = %s, amount = %s, work_date = %s,
                booking_id = %s, car_id = %s, mileage = %s, items_json = %s
            WHERE id = %s
        ''', (worker_id, description, amount, work_date, booking_id, car_id, mileage_int, items_json, work_id))
        if car_id:
            if mileage:
                # Также обновляем последний известный пробег авто
                cursor.execute("UPDATE client_cars SET mileage = %s WHERE id = %s", (mileage, car_id))
            if vin:
                cursor.execute("UPDATE client_cars SET vin = %s WHERE id = %s", (vin, car_id))
        if booking_id and car_id:
            cursor.execute("UPDATE bookings SET car_id = %s WHERE id = %s", (car_id, booking_id))
        conn.commit()
        conn.close()

    def append_to_work(self, work_id, new_description, new_amount, new_items_json=None):
        """Добавить описание и сумму к существующей работе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT description, amount, items_json FROM works WHERE id = %s", (work_id,))
        row = cursor.fetchone()
        if row:
            old_desc = row[0] or ""
            old_amount = float(row[1] or 0)
            combined_desc = old_desc + "\n" + new_description if old_desc else new_description
            combined_amount = old_amount + float(new_amount or 0)
            combined_items_json = self._merge_items_json(row[2], new_items_json)
            cursor.execute('''
                UPDATE works SET description = %s, amount = %s, items_json = %s WHERE id = %s
            ''', (combined_desc, combined_amount, combined_items_json, work_id))
            conn.commit()
        conn.close()
        return work_id

    def _merge_items_json(self, old_items_json, new_items_json):
        """Объединить два JSON-списка позиций работы в один (для append_to_work)"""
        items = []
        for raw in (old_items_json, new_items_json):
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    items.extend(parsed)
            except (TypeError, ValueError):
                continue
        return json.dumps(items, ensure_ascii=False) if items else None

    def get_work_items_json(self, work_id):
        """Получить сырой JSON с позициями работы (название+цена) по ID работы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT items_json FROM works WHERE id = %s", (work_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def get_work_by_id(self, work_id):
        """Получить работу по ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, wk.worker_id, w.full_name, wk.description, wk.amount,
                   wk.work_date,
                   cc.car_brand, cc.car_model, cc.car_number,
                   wk.mileage, cc.vin,
                   wk.booking_id, cl.full_name as client_name, cl.phone as client_phone,
                   wk.car_id, cc.client_id
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wk.id = %s
        ''', (work_id,))
        work = cursor.fetchone()
        conn.close()
        return work

    def get_work_by_booking_id(self, booking_id):
        """Получить работу по ID записи (booking)."""
        if not booking_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, wk.worker_id, w.full_name, wk.description, wk.amount,
                   wk.work_date,
                   cc.car_brand, cc.car_model, cc.car_number,
                   wk.mileage, cc.vin,
                   wk.booking_id, cl.full_name as client_name, cl.phone as client_phone,
                   wk.order_number, wk.car_id
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wk.booking_id = %s
            ORDER BY wk.id DESC
            LIMIT 1
        ''', (booking_id,))
        work = cursor.fetchone()
        conn.close()
        return work

    def get_all_works_by_booking_id(self, booking_id):
        """Получить ВСЕ работы по ID записи (booking)."""
        if not booking_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, wk.worker_id, w.full_name, wk.description, wk.amount,
                   wk.work_date,
                   cc.car_brand, cc.car_model, cc.car_number,
                   wk.mileage, cc.vin,
                   wk.booking_id, cl.full_name as client_name, cl.phone as client_phone,
                   wk.order_number, wk.car_id
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wk.booking_id = %s
            ORDER BY wk.id ASC
        ''', (booking_id,))
        works = cursor.fetchall()
        conn.close()
        return works

    def get_last_work_by_booking_id(self, booking_id):
        """Получить последнюю работу по booking_id (для объединения)"""
        if not booking_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, description, amount FROM works
            WHERE booking_id = %s
            ORDER BY id DESC LIMIT 1
        ''', (booking_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"work_id": row[0], "description": row[1], "amount": row[2]}
        return None

    def get_telegram_user_by_phone(self, phone):
        """Найти telegram user_id и username по телефону"""
        if not phone:
            return None
        import re
        phone_digits = re.sub(r'\D', '', phone)
        phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits

        if not phone_suffix:
            return None

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT telegram_user_id, tg_username, phone FROM clients
            WHERE telegram_user_id IS NOT NULL AND telegram_user_id > 0
            ORDER BY id DESC
        ''')
        all_clients = cursor.fetchall()

        for row in all_clients:
            db_tg_id, db_tg_username, db_phone = row
            if db_phone:
                db_phone_digits = re.sub(r'\D', '', db_phone)
                db_phone_suffix = db_phone_digits[-10:] if len(db_phone_digits) >= 10 else db_phone_digits
                if db_phone_suffix == phone_suffix:
                    conn.close()
                    return {"user_id": db_tg_id, "username": db_tg_username or ""}

        conn.close()
        return None

    def delete_parts_by_work_id(self, work_id):
        """Удалить все запчасти для работы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM parts WHERE work_id = %s", (work_id,))
        conn.commit()
        conn.close()

    def get_works_by_period(self, date_from, date_to):
        """Получить завершённые работы за период (по дате завершения наряда)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.completed_at,
                   cc.car_brand, cc.car_model, cc.car_number,
                   wk.order_number, cl.full_name as client_name, cl.phone as client_phone
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wk.completed_at BETWEEN %s AND %s
            ORDER BY w.full_name, wk.completed_at
        ''', (date_from, date_to))
        works = cursor.fetchall()
        conn.close()
        return works

    def get_works_by_car_number(self, car_number):
        """Получить все работы по госномеру."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.work_date,
                   cc.car_brand, cc.car_model, cc.car_number,
                   wk.order_number, cl.full_name as client_name, cl.phone as client_phone
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.car_number) LIKE %s
            ORDER BY wk.work_date DESC
        ''', (f'%{car_number.upper()}%',))
        works = cursor.fetchall()
        conn.close()
        return works

    def get_summary_by_period(self, date_from, date_to):
        """Получить сводку по работникам за период (только по завершённым нарядам -
        completed_at IS NULL, пока наряд по записи не отмечен "Выполнено")"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT w.id, w.full_name, SUM(wk.amount) as total, COUNT(wk.id) as work_count
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.completed_at BETWEEN %s AND %s
            GROUP BY w.id
            ORDER BY total DESC
        ''', (date_from, date_to))
        summary = cursor.fetchall()
        conn.close()
        return summary

    def get_works_by_worker_and_period(self, worker_id, date_from, date_to):
        """Получить завершённые работы мастера за период (с авто и клиентом) для детального отчёта"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, wk.description, wk.amount, wk.completed_at, wk.items_json,
                   cc.car_brand, cc.car_model, cc.car_number,
                   cl.full_name, cl.phone
            FROM works wk
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wk.worker_id = %s AND wk.completed_at BETWEEN %s AND %s
            ORDER BY wk.completed_at DESC, wk.id DESC
        ''', (worker_id, date_from, date_to))
        works = cursor.fetchall()
        conn.close()
        return works

    def add_worker_bonus(self, worker_id, amount, bonus_date, expense_description, expense_category, comment=None):
        """Начислить премию мастеру. Премия одновременно записывается в expenses как расход
        (одной транзакцией, со ссылкой worker_bonuses.expense_id), чтобы участвовать в
        отчётах и на вкладке "Финансы", и чтобы при удалении этого расхода в "Финансы"
        премия исчезала и из отчётов тоже (см. Database.delete_expense). Возвращает True/False."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO expenses (description, amount, expense_date, category, is_income) VALUES (%s, %s, %s, %s, 0)",
                (expense_description, amount, bonus_date, expense_category)
            )
            expense_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO worker_bonuses (worker_id, amount, bonus_date, comment, expense_id) VALUES (%s, %s, %s, %s, %s)",
                (worker_id, amount, bonus_date, comment, expense_id)
            )
            conn.commit()
            return True
        except MySQLError as e:
            print(f"Ошибка начисления премии: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_bonuses_by_worker_and_period(self, worker_id, date_from, date_to):
        """Получить премии мастера за период (дата, сумма, комментарий)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT bonus_date, amount, comment
            FROM worker_bonuses
            WHERE worker_id = %s AND bonus_date BETWEEN %s AND %s
            ORDER BY bonus_date ASC, id ASC
        ''', (worker_id, date_from, date_to))
        bonuses = cursor.fetchall()
        conn.close()
        return bonuses

    def get_bonuses_sum_by_period(self, date_from, date_to):
        """Получить суммы премий по всем мастерам за период: {worker_id: сумма}"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT worker_id, SUM(amount)
            FROM worker_bonuses
            WHERE bonus_date BETWEEN %s AND %s
            GROUP BY worker_id
        ''', (date_from, date_to))
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: float(row[1]) for row in rows}

    def mark_work_completed(self, booking_id, completed_date=None):
        """Отметить наряды по записи как завершённые, чтобы их сумма попала в зарплатные отчёты"""
        conn = self.get_connection()
        cursor = conn.cursor()
        if completed_date:
            cursor.execute(
                "UPDATE works SET completed_at = %s WHERE booking_id = %s AND completed_at IS NULL",
                (completed_date, booking_id)
            )
        else:
            cursor.execute(
                "UPDATE works SET completed_at = CURDATE() WHERE booking_id = %s AND completed_at IS NULL",
                (booking_id,)
            )
        conn.commit()
        conn.close()

    def get_recent_works(self, limit=50):
        """Получить последние записи о работах."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wk.id, w.full_name, wk.description, wk.amount, wk.work_date,
                   cc.car_brand, cc.car_model, cc.car_number
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
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
        """Удалить расход (и связанную премию мастера, если это была она - см. add_worker_bonus)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM worker_bonuses WHERE expense_id = %s", (expense_id,))
        cursor.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
        conn.commit()
        conn.close()

    def get_total_expenses_by_period(self, date_from, date_to):
        """Получить общую сумму расходов за период"""
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
        """Получить общую сумму доходов за период"""
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
        """Получить детальный список расходов за период"""
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
        """Получить детальный список доходов за период"""
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

    # --- Методы для статистики ---

    def get_car_brand_stats(self, date_from, date_to):
        """Получить статистику визитов и выручки по маркам авто за период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT cc.car_brand,
                   COUNT(wk.id) as visit_count,
                   COUNT(DISTINCT cc.id) as car_count,
                   COALESCE(SUM(wk.amount), 0) as total_amount
            FROM works wk
            JOIN client_cars cc ON wk.car_id = cc.id
            WHERE wk.work_date BETWEEN %s AND %s AND cc.car_brand IS NOT NULL AND cc.car_brand <> ''
            GROUP BY cc.car_brand
            ORDER BY visit_count DESC
        ''', (date_from, date_to))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_top_clients_by_period(self, date_from, date_to):
        """Получить статистику по клиентам (визиты и сумма) за период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT cl.full_name, cl.phone,
                   COUNT(wk.id) as visit_count,
                   COALESCE(SUM(wk.amount), 0) as total_amount
            FROM works wk
            JOIN client_cars cc ON wk.car_id = cc.id
            JOIN clients cl ON cc.client_id = cl.id
            WHERE wk.work_date BETWEEN %s AND %s
            GROUP BY cl.id
            ORDER BY total_amount DESC
        ''', (date_from, date_to))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_works_for_period(self, date_from, date_to):
        """Получить все работы за период (для разбивки на позиции и статистики по видам работ)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, description, amount, items_json
            FROM works
            WHERE work_date BETWEEN %s AND %s
        ''', (date_from, date_to))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_monthly_stats(self, date_from, date_to):
        """Получить динамику визитов и выручки по месяцам за период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DATE_FORMAT(wk.work_date, '%%Y-%%m') as ym,
                   COUNT(wk.id) as visit_count,
                   COALESCE(SUM(wk.amount), 0) as total_amount
            FROM works wk
            WHERE wk.work_date BETWEEN %s AND %s
            GROUP BY ym
            ORDER BY ym
        ''', (date_from, date_to))
        rows = cursor.fetchall()
        conn.close()
        return rows

    # --- Методы для работы с запчастями ---

    def add_parts(self, work_id, parts_list):
        """Добавить запчасти к работе"""
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
        """Поиск ключевых слов по префиксу"""
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
                pass
        conn.commit()
        conn.close()
        return added

    def update_keyword_intervals(self, keyword_id, interval_km_min, interval_km_max):
        """Обновить интервалы ТО для ключевого слова"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE keywords
            SET interval_km_min = %s, interval_km_max = %s
            WHERE id = %s
        """, (interval_km_min, interval_km_max, keyword_id))
        conn.commit()
        conn.close()

    def get_keywords_with_intervals(self):
        """Получить ключевые слова с настроенными интервалами ТО"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, keyword, interval_km_min, interval_km_max
            FROM keywords
            WHERE interval_km_min IS NOT NULL AND interval_km_max IS NOT NULL
            ORDER BY keyword
        """)
        keywords = cursor.fetchall()
        conn.close()
        return keywords

    def get_all_keywords_full(self):
        """Получить все ключевые слова с полными данными"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, keyword, interval_km_min, interval_km_max
            FROM keywords
            ORDER BY keyword
        """)
        keywords = cursor.fetchall()
        conn.close()
        return keywords

    # --- Методы для работы с записями из Telegram ---

    def get_all_bookings(self, status=None):
        """Получить все записи."""
        conn = self.get_connection()
        cursor = conn.cursor()

        query = """SELECT b.id,
                   c.telegram_user_id as user_id,
                   c.tg_username,
                   c.full_name,
                   c.phone,
                   b.booking_date, b.booking_time, b.status,
                   CONCAT(cc.car_brand, ' ', cc.car_model, ' ', cc.car_number) as car_info,
                   b.client_id, b.car_id,
                   w.order_number, b.notes
                   FROM bookings b
                   LEFT JOIN clients c ON b.client_id = c.id
                   LEFT JOIN client_cars cc ON b.car_id = cc.id
                   LEFT JOIN works w ON w.booking_id = b.id
                   WHERE 1=1"""
        params = []

        if status:
            query += " AND b.status = %s"
            params.append(status)

        query += " ORDER BY b.booking_date ASC, b.booking_time ASC"

        cursor.execute(query, params)
        bookings = cursor.fetchall()
        conn.close()
        return bookings

    def get_bookings_by_car_id(self, car_id):
        """Получить записи по ID автомобиля (самые новые сначала)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.booking_date, b.booking_time, b.status
            FROM bookings b
            WHERE b.car_id = %s
            ORDER BY b.booking_date DESC, b.booking_time DESC, b.id DESC
        """, (car_id,))
        bookings = cursor.fetchall()
        conn.close()
        return bookings

    def get_today_bookings(self):
        """Получить записи на сегодня."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id,
                   c.telegram_user_id as user_id,
                   c.tg_username,
                   c.full_name,
                   c.phone,
                   b.booking_date, b.booking_time, b.status,
                   CONCAT(cc.car_brand, ' ', cc.car_model, ' ', cc.car_number) as car_info,
                   b.client_id, b.car_id,
                   w.order_number, b.notes
            FROM bookings b
            LEFT JOIN clients c ON b.client_id = c.id
            LEFT JOIN client_cars cc ON b.car_id = cc.id
            LEFT JOIN works w ON w.booking_id = b.id
            WHERE b.booking_date = CURDATE()
            ORDER BY b.booking_time
        """)
        bookings = cursor.fetchall()
        conn.close()
        return bookings

    def update_booking_status(self, booking_id, status):
        """Обновить статус записи"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE bookings SET status = %s WHERE id = %s",
            (status, booking_id)
        )
        conn.commit()
        conn.close()

    def delete_booking(self, booking_id):
        """Удалить запись"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
        conn.commit()
        conn.close()

    def add_booking(self, booking_date, booking_time, client_id, car_id=None, status="waiting", notes=None):
        """Добавить новую запись клиента. Возвращает ID записи или None при ошибке."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO bookings (client_id, car_id, booking_date, booking_time, status, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (client_id, car_id, booking_date, booking_time, status, notes))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"Ошибка добавления записи: {e}")
            return None
        finally:
            conn.close()

    def is_time_slot_available(self, booking_date, booking_time):
        """Проверить свободен ли слот времени"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM bookings
            WHERE booking_date = %s AND booking_time = %s AND status IN ('waiting', 'in_progress')
        """, (booking_date, booking_time))
        count = cursor.fetchone()[0]
        conn.close()
        return count == 0

    def get_bookings_at_time(self, booking_date, booking_time):
        """Получить список записей на конкретное время с информацией о машинах."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.full_name, car.car_number, car.car_brand, car.car_model
            FROM bookings b
            LEFT JOIN clients c ON b.client_id = c.id
            LEFT JOIN client_cars car ON b.car_id = car.id
            WHERE b.booking_date = %s AND b.booking_time = %s AND b.status IN ('waiting', 'in_progress')
        """, (booking_date, booking_time))
        results = cursor.fetchall()
        conn.close()

        bookings_list = []
        for row in results:
            bookings_list.append({
                'client_name': row[0] or 'Неизвестно',
                'car_number': row[1] or 'Нет номера',
                'brand': row[2] or '',
                'model': row[3] or ''
            })
        return bookings_list

    def get_active_bookings_for_select(self):
        """Получить активные записи для выпадающего списка."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id,
                   c.full_name,
                   c.phone,
                   b.booking_date, b.booking_time, b.car_id
            FROM bookings b
            LEFT JOIN clients c ON b.client_id = c.id
            WHERE b.status IN ('waiting', 'in_progress') AND b.booking_date >= CURDATE()
            ORDER BY b.booking_date ASC, b.booking_time ASC
        """)
        bookings = cursor.fetchall()
        conn.close()
        return bookings

    def get_booking_by_id(self, booking_id):
        """Получить запись по ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id,
                   c.telegram_user_id as user_id,
                   c.tg_username,
                   c.full_name,
                   c.phone,
                   b.booking_date, b.booking_time, b.status, b.created_at,
                   CONCAT(cc.car_brand, ' ', cc.car_model, ' ', cc.car_number) as car_info,
                   b.client_id, b.car_id, b.notes, cc.vin
            FROM bookings b
            LEFT JOIN clients c ON b.client_id = c.id
            LEFT JOIN client_cars cc ON b.car_id = cc.id
            WHERE b.id = %s
        """, (booking_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "id": row[0],
                "user_id": row[1],
                "username": row[2],
                "full_name": row[3],
                "phone": row[4],
                "booking_date": row[5],
                "booking_time": row[6],
                "status": row[7],
                "created_at": row[8],
                "car_info": row[9],
                "client_id": row[10],
                "car_id": row[11],
                "notes": row[12],
                "car_vin": row[13] or ""
            }
        return None

    def get_telegram_user_id_by_phone(self, phone):
        """Найти telegram user_id по номеру телефона из clients"""
        if not phone:
            return None
        import re
        phone_digits = re.sub(r'\D', '', phone)
        phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT telegram_user_id FROM clients
            WHERE telegram_user_id IS NOT NULL AND telegram_user_id > 0
            AND RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
            ORDER BY id DESC LIMIT 1
        """, (phone_suffix,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    # --- Методы для работы с клиентами (таблица clients) ---

    def get_or_create_client(self, telegram_user_id=None, full_name=None, phone=None, tg_username=None, car_number=None):
        """Найти или создать клиента. Возвращает client_id"""
        phone = normalize_phone(phone)
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. Ищем по telegram_user_id
        if telegram_user_id and telegram_user_id > 0:
            cursor.execute("SELECT id FROM clients WHERE telegram_user_id = %s", (telegram_user_id,))
            result = cursor.fetchone()
            if result:
                if full_name or phone or tg_username:
                    cursor.execute("""
                        UPDATE clients SET
                            tg_username = COALESCE(%s, tg_username),
                            full_name = COALESCE(%s, full_name),
                            phone = COALESCE(%s, phone)
                        WHERE id = %s
                    """, (tg_username, full_name, phone, result[0]))
                    conn.commit()
                conn.close()
                return result[0]

        # 2. Ищем по телефону
        if phone:
            phone_digits = re.sub(r'\D', '', phone)
            phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
            cursor.execute("""
                SELECT id FROM clients
                WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
            """, (phone_suffix,))
            result = cursor.fetchone()
            if result:
                if telegram_user_id and telegram_user_id > 0:
                    cursor.execute("""
                        UPDATE clients SET
                            telegram_user_id = %s,
                            tg_username = COALESCE(%s, tg_username),
                            full_name = COALESCE(%s, full_name)
                        WHERE id = %s
                    """, (telegram_user_id, tg_username, full_name, result[0]))
                    conn.commit()
                elif full_name:
                    cursor.execute("""
                        UPDATE clients SET
                            full_name = %s
                        WHERE id = %s
                    """, (full_name, result[0]))
                    conn.commit()
                conn.close()
                return result[0]

        # 3. Ищем по госномеру машины
        if car_number:
            cursor.execute("""
                SELECT client_id FROM client_cars
                WHERE UPPER(car_number) = UPPER(%s) AND client_id IS NOT NULL
            """, (car_number,))
            result = cursor.fetchone()
            if result:
                client_id = result[0]
                # Обновляем данные клиента
                if telegram_user_id and telegram_user_id > 0:
                    cursor.execute("""
                        UPDATE clients SET
                            telegram_user_id = %s,
                            tg_username = COALESCE(%s, tg_username),
                            full_name = COALESCE(%s, full_name),
                            phone = COALESCE(%s, phone)
                        WHERE id = %s
                    """, (telegram_user_id, tg_username, full_name, phone, client_id))
                elif phone or full_name:
                    cursor.execute("""
                        UPDATE clients SET
                            full_name = COALESCE(%s, full_name),
                            phone = COALESCE(%s, phone)
                        WHERE id = %s
                    """, (full_name, phone, client_id))
                conn.commit()
                conn.close()
                return client_id

        # 4. Создаём нового клиента
        cursor.execute("""
            INSERT INTO clients (telegram_user_id, tg_username, full_name, phone)
            VALUES (%s, %s, %s, %s)
        """, (telegram_user_id if telegram_user_id and telegram_user_id > 0 else None, tg_username, full_name, phone))
        conn.commit()
        client_id = cursor.lastrowid
        conn.close()
        return client_id

    def get_client_by_id(self, client_id):
        """Получить клиента по ID"""
        if not client_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, telegram_user_id, full_name, phone, tg_username, created_at
            FROM clients WHERE id = %s
        """, (client_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "id": result[0],
                "telegram_user_id": result[1],
                "full_name": result[2],
                "phone": result[3],
                "tg_username": result[4],
                "created_at": result[5]
            }
        return None

    def update_client(self, client_id, full_name, phone, tg_username=None):
        """Обновить имя, телефон и telegram-username клиента (исправление опечаток оператором).
        telegram_user_id (числовой ID для отправки уведомлений) не редактируется вручную —
        он проставляется автоматически, когда клиент сам пишет боту."""
        tg_username = (tg_username or "").strip().lstrip("@") or None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE clients SET full_name = %s, phone = %s, tg_username = %s WHERE id = %s
        """, (full_name, normalize_phone(phone), tg_username, client_id))
        conn.commit()
        conn.close()

    def get_client_by_phone(self, phone):
        """Получить клиента по телефону"""
        if not phone:
            return None
        import re
        phone_digits = re.sub(r'\D', '', phone)
        phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, telegram_user_id, full_name, phone, created_at
            FROM clients
            WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
            LIMIT 1
        """, (phone_suffix,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "id": result[0],
                "telegram_user_id": result[1],
                "full_name": result[2],
                "phone": result[3],
                "created_at": result[4]
            }
        return None

    def get_or_create_car(self, client_id, car_brand, car_model, car_number):
        """Найти или создать авто клиента. Возвращает car_id"""
        if not car_number:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM client_cars WHERE UPPER(car_number) = UPPER(%s)", (car_number,))
        result = cursor.fetchone()

        if result:
            if client_id:
                cursor.execute("UPDATE client_cars SET client_id = %s WHERE id = %s", (client_id, result[0]))
                conn.commit()
            conn.close()
            return result[0]

        cursor.execute("""
            INSERT INTO client_cars (client_id, car_brand, car_model, car_number)
            VALUES (%s, %s, %s, %s)
        """, (client_id, car_brand, car_model, car_number.upper()))
        conn.commit()
        car_id = cursor.lastrowid
        conn.close()
        return car_id

    def get_client_cars_by_client_id(self, client_id):
        """Получить список машин клиента по client_id"""
        if not client_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, car_brand, car_model, car_number
            FROM client_cars
            WHERE client_id = %s
            ORDER BY car_brand, car_model
        """, (client_id,))
        cars = cursor.fetchall()
        conn.close()
        return cars

    def get_car_by_id(self, car_id):
        """Получить авто по ID"""
        if not car_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_id, car_brand, car_model, car_number
            FROM client_cars WHERE id = %s
        """, (car_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "id": result[0],
                "client_id": result[1],
                "car_brand": result[2],
                "car_model": result[3],
                "car_number": result[4]
            }
        return None

    def get_car_by_number(self, car_number):
        """Получить авто по госномеру"""
        if not car_number:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_id, car_brand, car_model, car_number, vin
            FROM client_cars WHERE UPPER(car_number) = UPPER(%s)
        """, (car_number,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "id": result[0],
                "client_id": result[1],
                "car_brand": result[2],
                "car_model": result[3],
                "car_number": result[4],
                "vin": result[5] or ""
            }
        return None

    def get_client_cars_by_phone(self, phone):
        """Получить список машин клиента по номеру телефона через clients"""
        if not phone:
            return []
        import re
        phone_digits = re.sub(r'\D', '', phone)
        phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT cc.car_brand, cc.car_model, cc.car_number, cc.vin
            FROM client_cars cc
            JOIN clients c ON cc.client_id = c.id
            WHERE RIGHT(REGEXP_REPLACE(c.phone, '[^0-9]', ''), 10) = %s
            AND cc.car_brand IS NOT NULL AND cc.car_brand != ''
            ORDER BY cc.car_brand, cc.car_model
        """, (phone_suffix,))
        cars = cursor.fetchall()
        conn.close()
        return cars

    def add_client_car(self, client_id, car_brand, car_model, car_number):
        """Добавить автомобиль клиента в client_cars. Возвращает car_id или None."""
        if not car_number or not car_brand or not client_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO client_cars (client_id, car_brand, car_model, car_number)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    client_id = VALUES(client_id)
            """, (client_id, car_brand, car_model, car_number.upper()))
            conn.commit()
            cursor.execute("SELECT id FROM client_cars WHERE UPPER(car_number) = UPPER(%s)", (car_number,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Ошибка добавления авто: {e}")
            return None
        finally:
            conn.close()

    def get_client_cars_by_telegram_id(self, telegram_user_id):
        """Получить список машин клиента по telegram_user_id через clients"""
        if not telegram_user_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT cc.car_brand, cc.car_model, cc.car_number, cc.vin
            FROM client_cars cc
            JOIN clients c ON cc.client_id = c.id
            WHERE c.telegram_user_id = %s
            AND cc.car_brand IS NOT NULL AND cc.car_brand != ''
            ORDER BY cc.car_brand, cc.car_model
        """, (telegram_user_id,))
        cars = cursor.fetchall()
        conn.close()
        return cars

    def get_client_name_by_phone(self, phone):
        """Получить имя клиента по номеру телефона из таблицы clients"""
        if not phone:
            return None
        import re
        phone_digits = re.sub(r'\D', '', phone)
        phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT full_name FROM clients
            WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
            AND full_name IS NOT NULL AND full_name != ''
            ORDER BY id DESC LIMIT 1
        """, (phone_suffix,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def get_client_cars_by_name(self, name):
        """Получить список машин клиента по имени через clients"""
        if not name:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT cc.car_brand, cc.car_model, cc.car_number, cc.vin
            FROM client_cars cc
            JOIN clients c ON cc.client_id = c.id
            WHERE c.full_name = %s
            AND cc.car_brand IS NOT NULL AND cc.car_brand != ''
            ORDER BY cc.car_brand, cc.car_model
        """, (name,))
        cars = cursor.fetchall()
        conn.close()
        return cars

    def get_client_history(self, phone=None, name=None, telegram_user_id=None):
        """Получить всю историю работ клиента через clients -> client_cars -> works."""
        if not phone and not name and not telegram_user_id:
            return []
        import re
        conn = self.get_connection()
        cursor = conn.cursor()

        client_id = None

        if telegram_user_id:
            cursor.execute("SELECT id FROM clients WHERE telegram_user_id = %s", (telegram_user_id,))
            result = cursor.fetchone()
            if result:
                client_id = result[0]

        if not client_id and phone:
            phone_digits = re.sub(r'\D', '', phone)
            phone_suffix = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
            cursor.execute("""
                SELECT id FROM clients
                WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
                LIMIT 1
            """, (phone_suffix,))
            result = cursor.fetchone()
            if result:
                client_id = result[0]

        if not client_id and name:
            cursor.execute("SELECT id FROM clients WHERE full_name = %s LIMIT 1", (name,))
            result = cursor.fetchone()
            if result:
                client_id = result[0]

        if not client_id:
            conn.close()
            return []

        cursor.execute("""
            SELECT wk.id, wk.work_date, wk.order_number, w.full_name as worker,
                   cc.car_brand, cc.car_model, cc.car_number, wk.mileage,
                   wk.description, wk.amount, cl.full_name as client_name, cl.phone as client_phone
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            JOIN client_cars cc ON wk.car_id = cc.id
            JOIN clients cl ON cc.client_id = cl.id
            WHERE cc.client_id = %s
            ORDER BY wk.work_date DESC, wk.id DESC
        """, (client_id,))

        works = cursor.fetchall()
        conn.close()
        return works

    def get_client_cars_by_telegram_user_id(self, telegram_user_id):
        """Получить список машин клиента по telegram_user_id через clients -> client_cars"""
        if not telegram_user_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT cc.car_brand, cc.car_model, cc.car_number, cc.vin
            FROM client_cars cc
            JOIN clients c ON cc.client_id = c.id
            WHERE c.telegram_user_id = %s
            AND cc.car_brand IS NOT NULL AND cc.car_brand != ''
            ORDER BY cc.car_brand, cc.car_model
        """, (telegram_user_id,))

        cars = cursor.fetchall()
        conn.close()
        return cars

    def get_car_info_by_number(self, car_number):
        """Получить информацию о машине и владельце по госномеру"""
        if not car_number:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cc.id, cc.car_brand, cc.car_model, cc.car_number, cc.mileage, cc.vin,
                   cl.full_name as client_name, cl.phone as client_phone
            FROM client_cars cc
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.car_number) = UPPER(%s)
            LIMIT 1
        """, (car_number,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "car_id": result[0],
                "car_brand": result[1] or "",
                "car_model": result[2] or "",
                "car_number": result[3] or "",
                "mileage": result[4] or "",
                "vin": result[5] or "",
                "client_name": result[6] or "",
                "client_phone": result[7] or ""
            }
        return None

    def get_all_clients_by_car_number(self, car_number):
        """Получить клиента по госномеру из client_cars"""
        if not car_number:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cl.full_name as client_name, cl.phone as client_phone,
                   cc.car_brand, cc.car_model, cc.vin
            FROM client_cars cc
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.car_number) = UPPER(%s)
        """, (car_number,))
        results = cursor.fetchall()
        conn.close()

        clients = []
        for row in results:
            clients.append({
                "client_name": row[0] or "",
                "client_phone": row[1] or "",
                "car_brand": row[2] or "",
                "car_model": row[3] or "",
                "vin": row[4] or ""
            })
        return clients

    def get_active_work_by_car_number(self, car_number):
        """Найти активную работу (в работе) по госномеру"""
        if not car_number:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.id, w.booking_id, w.description, cl.full_name, cl.phone,
                   b.booking_date, b.booking_time
            FROM works w
            JOIN bookings b ON w.booking_id = b.id
            LEFT JOIN client_cars cc ON w.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.car_number) = UPPER(%s)
              AND b.status = 'in_progress'
            ORDER BY w.id DESC
            LIMIT 1
        """, (car_number,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "work_id": result[0],
                "booking_id": result[1],
                "description": result[2] or "",
                "client_name": result[3] or "",
                "client_phone": result[4] or "",
                "booking_date": result[5],
                "booking_time": result[6]
            }
        return None

    # --- Методы для работы со складом запчастей ---

    def add_warehouse_part(self, car_id, part_name, quantity=1, price=None, order_date=None, notes=None, is_paid=False):
        """Добавить запчасть на склад (заказать)"""
        from datetime import date
        if order_date is None:
            order_date = date.today()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO warehouse_parts (car_id, part_name, quantity, price, order_date, notes, status, is_paid)
            VALUES (%s, %s, %s, %s, %s, %s, 'в пути', %s)
        """, (car_id, part_name, quantity, price, order_date, notes, is_paid))
        conn.commit()
        part_id = cursor.lastrowid
        conn.close()
        return part_id

    def get_all_warehouse_parts(self, status=None):
        """Получить все запчасти со склада с информацией о машине и клиенте"""
        conn = self.get_connection()
        cursor = conn.cursor()
        query = """
            SELECT wp.id, cc.car_number, cc.car_brand, cc.car_model,
                   cl.full_name as client_name, cl.phone as client_phone,
                   wp.part_name, wp.quantity, wp.price, wp.status,
                   wp.order_date, wp.received_date, wp.notes, wp.car_id, wp.is_paid
            FROM warehouse_parts wp
            LEFT JOIN client_cars cc ON wp.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
        """
        if status:
            query += " WHERE wp.status = %s"
            query += " ORDER BY wp.order_date DESC, wp.id DESC"
            cursor.execute(query, (status,))
        else:
            query += " ORDER BY wp.order_date DESC, wp.id DESC"
            cursor.execute(query)
        parts = cursor.fetchall()
        conn.close()
        return parts

    def get_warehouse_parts_by_car_id(self, car_id):
        """Получить запчасти по ID машины"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wp.id, cc.car_number, cc.car_brand, cc.car_model,
                   cl.full_name as client_name, cl.phone as client_phone,
                   wp.part_name, wp.quantity, wp.price, wp.status,
                   wp.order_date, wp.received_date, wp.notes, wp.car_id, wp.is_paid
            FROM warehouse_parts wp
            LEFT JOIN client_cars cc ON wp.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wp.car_id = %s
            ORDER BY wp.order_date DESC, wp.id DESC
        """, (car_id,))
        parts = cursor.fetchall()
        conn.close()
        return parts

    def get_warehouse_parts_by_car_number(self, car_number, status="на складе"):
        """Получить запчасти на складе по госномеру машины"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wp.id, wp.part_name, wp.quantity, wp.price, wp.notes, wp.is_paid
            FROM warehouse_parts wp
            JOIN client_cars cc ON wp.car_id = cc.id
            WHERE UPPER(cc.car_number) = UPPER(%s) AND wp.status = %s
            ORDER BY wp.id DESC
        """, (car_number, status))
        parts = cursor.fetchall()
        conn.close()
        return parts

    def update_warehouse_part_status(self, part_id, status, received_date=None):
        """Обновить статус запчасти"""
        conn = self.get_connection()
        cursor = conn.cursor()
        if received_date:
            cursor.execute("""
                UPDATE warehouse_parts SET status = %s, received_date = %s WHERE id = %s
            """, (status, received_date, part_id))
        else:
            cursor.execute("""
                UPDATE warehouse_parts SET status = %s WHERE id = %s
            """, (status, part_id))
        conn.commit()
        conn.close()

    def update_warehouse_part_paid(self, part_id, is_paid):
        """Быстро отметить/снять отметку "оплачено" у складской позиции"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE warehouse_parts SET is_paid = %s WHERE id = %s", (is_paid, part_id))
        conn.commit()
        conn.close()

    def delete_warehouse_part(self, part_id):
        """Удалить запчасть со склада"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM warehouse_parts WHERE id = %s", (part_id,))
        conn.commit()
        conn.close()

    def update_warehouse_part(self, part_id, part_name, quantity, price, status, notes, is_paid=None):
        """Обновить данные запчасти"""
        conn = self.get_connection()
        cursor = conn.cursor()
        if is_paid is None:
            cursor.execute("""
                UPDATE warehouse_parts
                SET part_name = %s, quantity = %s, price = %s, status = %s, notes = %s
                WHERE id = %s
            """, (part_name, quantity, price, status, notes, part_id))
        else:
            cursor.execute("""
                UPDATE warehouse_parts
                SET part_name = %s, quantity = %s, price = %s, status = %s, notes = %s, is_paid = %s
                WHERE id = %s
            """, (part_name, quantity, price, status, notes, is_paid, part_id))
        conn.commit()
        conn.close()

    def get_warehouse_part_by_id(self, part_id):
        """Получить запчасть по ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wp.id, cc.car_number, cc.car_brand, cc.car_model,
                   cl.full_name as client_name, cl.phone as client_phone,
                   wp.part_name, wp.quantity, wp.price, wp.status,
                   wp.order_date, wp.received_date, wp.notes, wp.car_id, wp.is_paid, wp.work_id
            FROM warehouse_parts wp
            LEFT JOIN client_cars cc ON wp.car_id = cc.id
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE wp.id = %s
        """, (part_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "id": result[0],
                "car_number": result[1],
                "car_brand": result[2],
                "car_model": result[3],
                "client_name": result[4],
                "client_phone": result[5],
                "part_name": result[6],
                "quantity": result[7],
                "price": result[8],
                "status": result[9],
                "order_date": result[10],
                "received_date": result[11],
                "notes": result[12],
                "car_id": result[13],
                "is_paid": bool(result[14]),
                "work_id": result[15]
            }
        return None

    def link_warehouse_part_to_work(self, part_id, work_id):
        """Привязать складскую позицию к наряду (works.id), в который она была установлена"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE warehouse_parts SET work_id = %s WHERE id = %s", (work_id, part_id))
        conn.commit()
        conn.close()

    # ──────────────────────────────────────────────────────
    # --- Методы авторизации и управления пользователями ---
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _hash_password(password: str, salt: str = None):
        """Хэшировать пароль с солью. Возвращает (hash, salt)."""
        import hashlib, os as _os
        if salt is None:
            salt = _os.urandom(32).hex()
        pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return pwd_hash, salt

    def ensure_default_admin(self) -> bool:
        """Создать admin/admin если нет ни одного пользователя. Возвращает True если создал."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        (count,) = cursor.fetchone()
        conn.close()
        if count == 0:
            self.create_user("admin", "admin", "Администратор", "admin")
            return True
        return False

    def verify_user(self, username: str, password: str):
        """Проверить логин/пароль. Возвращает dict с данными пользователя или None."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password_hash, salt, full_name, role "
            "FROM users WHERE username=%s AND is_active=1",
            (username,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        user_id, uname, pwd_hash, salt, full_name, role = row
        expected, _ = self._hash_password(password, salt)
        if expected != pwd_hash:
            return None
        return {"id": user_id, "username": uname, "full_name": full_name, "role": role}

    def create_user(self, username: str, password: str, full_name: str = "", role: str = "user") -> bool:
        """Создать пользователя. Возвращает True при успехе, False если логин занят."""
        pwd_hash, salt = self._hash_password(password)
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password_hash, salt, full_name, role) "
                "VALUES (%s, %s, %s, %s, %s)",
                (username, pwd_hash, salt, full_name, role)
            )
            conn.commit()
            return True
        except pymysql.IntegrityError:
            return False
        finally:
            conn.close()

    def change_password(self, user_id: int, new_password: str) -> bool:
        """Сменить пароль пользователя по ID."""
        pwd_hash, salt = self._hash_password(new_password)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash=%s, salt=%s WHERE id=%s",
            (pwd_hash, salt, user_id)
        )
        conn.commit()
        conn.close()
        return True

    def get_all_users(self):
        """Получить всех пользователей. Возвращает список dict."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, full_name, role, is_active FROM users ORDER BY id")
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "is_active": r[4]}
            for r in rows
        ]

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        """Заблокировать / разблокировать пользователя."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active=%s WHERE id=%s", (1 if is_active else 0, user_id))
        conn.commit()
        conn.close()

    def delete_user(self, user_id: int) -> None:
        """Удалить пользователя."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()
        conn.close()
