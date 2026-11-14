# -*- coding: utf-8 -*-
"""
Класс для работы с базой данных MariaDB
"""

import json
import os
import re
from datetime import timedelta
import pymysql
from pymysql import Error as MySQLError
from tkinter import messagebox

from db_config import DB_CONFIG, get_base_path
from db_schema import TABLES, INDEXES, MIGRATIONS
from plates import normalize_plate, plate_search_key


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


def max_cars_per_slot():
    """Сколько машин можно записать на одно время (config/settings.json, max_cars_per_slot)"""
    try:
        with open(os.path.join(get_base_path(), 'config', 'settings.json'), 'r', encoding='utf-8') as f:
            return max(1, int(json.load(f).get('max_cars_per_slot', 1)))
    except (OSError, ValueError, TypeError):
        return 1


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

        # Первый запуск версии, где у нарядов появился клиент (works.client_id): прежде чем менять
        # структуру уже работающей базы - полная копия в папку Backup (её видно и можно восстановить
        # во вкладке "Резервное копирование"). Сами изменения ничего не удаляют: добавляется пустое поле
        # и заполняется у старых нарядов
        plate_fixes = self._car_numbers_to_normalize(cursor)
        if not self._column_exists(cursor, "works", "client_id") or self._part_names_need_cleanup(cursor)                 or plate_fixes:
            conn.commit()
            self._backup_before_migration()

        # Применяем миграции
        for migration_sql in MIGRATIONS:
            try:
                cursor.execute(migration_sql)
            except:
                pass

        # ADD COLUMN IF NOT EXISTS есть только в MariaDB - на MySQL добавляем поле обычной командой
        if not self._column_exists(cursor, "works", "client_id"):
            try:
                cursor.execute("ALTER TABLE works ADD COLUMN client_id INT DEFAULT NULL")
                cursor.execute("UPDATE works wk JOIN client_cars cc ON wk.car_id = cc.id "
                               "SET wk.client_id = cc.client_id WHERE wk.client_id IS NULL AND cc.client_id IS NOT NULL")
            except MySQLError as e:
                messagebox.showerror(
                    "Обновление базы данных",
                    "Не удалось добавить в базу поле works.client_id (клиент наряда).\n"
                    "Данные не изменены и не удалены, но отчёты и редактирование записей работать не будут.\n\n"
                    f"Ошибка: {e}")

        # Госномера - в одном написании: заглавными, без пробелов, российские - кириллицей
        # (A123BC77 латиницей и "А 123 ВС 77" -> А123ВС77), иначе поиск их не находит
        for car_id, number in plate_fixes:
            try:
                cursor.execute("UPDATE client_cars SET car_number = %s WHERE id = %s", (number, car_id))
            except MySQLError as e:
                print(f"Госномер машины {car_id} не приведён к виду {number}: {e}")

        conn.commit()
        conn.close()

    @staticmethod
    def _car_numbers_to_normalize(cursor):
        """Машины, у которых госномер записан не в едином виде (plates.normalize_plate): [(id, новый номер)].
        Если в базе уже есть машина с таким номером (одна машина заведена дважды: латиницей и кириллицей),
        её не трогаем - иначе две машины с одним номером; такие дубли объединяют вручную"""
        try:
            cursor.execute("SELECT id, car_number FROM client_cars WHERE car_number IS NOT NULL AND car_number <> ''")
            rows = cursor.fetchall()
        except MySQLError:
            return []
        taken = {(number or "").upper() for _, number in rows}
        fixes = []
        for car_id, number in rows:
            fixed = normalize_plate(number)
            if fixed and fixed != number:
                if fixed.upper() in taken and fixed.upper() != number.upper():
                    continue
                taken.add(fixed.upper())
                fixes.append((car_id, fixed))
        return fixes

    @staticmethod
    def _part_names_need_cleanup(cursor):
        """Есть названия запчастей с переносами строк / лишними пробелами (их почистит миграция)"""
        try:
            cursor.execute("""
                SELECT 1 FROM parts
                WHERE part_name <> TRIM(REGEXP_REPLACE(part_name, '[[:space:]]+', ' ')) LIMIT 1
            """)
            return cursor.fetchone() is not None
        except MySQLError:
            return False

    @staticmethod
    def _column_exists(cursor, table, column):
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """, (table, column))
        return cursor.fetchone()[0] > 0

    def _backup_before_migration(self):
        """Полная копия базы перед изменением структуры. Не получилось - спрашиваем, продолжать ли"""
        import backup as backup_module
        base = get_base_path()
        try:
            path = backup_module.create_backup(
                self, os.path.join(base, "Backup"),
                os.path.join(base, "config", "settings.json"),
                os.path.join(base, "config", "spare_parts.txt"))
            print(f"Копия базы перед обновлением структуры: {path}")
        except Exception as e:
            if not messagebox.askyesno(
                    "Обновление базы данных",
                    "Перед обновлением структуры базы не удалось сделать её резервную копию.\n\n"
                    f"Ошибка: {e}\n\n"
                    "Обновление только добавляет новое поле и ничего не удаляет. Продолжить без копии?\n"
                    "(Нет - программа закроется, базу можно сохранить вручную и запустить снова)"):
                raise SystemExit(1)

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

    # --- Расписание сотрудников ---

    def get_worker_absences(self, date_from, date_to, worker_id=None):
        """Отсутствия, пересекающие период [date_from, date_to]"""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = """
            SELECT id, worker_id, date_from, date_to, kind, note FROM worker_absences
            WHERE date_from <= %s AND date_to >= %s
        """
        params = [date_to, date_from]
        if worker_id is not None:
            sql += " AND worker_id = %s"
            params.append(worker_id)
        cursor.execute(sql + " ORDER BY date_from", params)
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "worker_id": r[1], "date_from": r[2], "date_to": r[3], "kind": r[4], "note": r[5] or ""}
                for r in rows]

    def set_worker_day(self, worker_id, day, kind):
        """Отметить один день сотрудника: kind = 'day_off' / 'vacation' / 'sick', None - рабочий день.
        Периоды, которые задевают этот день, разрезаются; соседние дни того же вида склеиваются в один период"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Вырезаем день из всех периодов, которые его содержат
            cursor.execute("""
                SELECT id, date_from, date_to, kind, note FROM worker_absences
                WHERE worker_id = %s AND date_from <= %s AND date_to >= %s
            """, (worker_id, day, day))
            for absence_id, date_from, date_to, old_kind, note in cursor.fetchall():
                cursor.execute("DELETE FROM worker_absences WHERE id = %s", (absence_id,))
                for part_from, part_to in ((date_from, day - timedelta(days=1)), (day + timedelta(days=1), date_to)):
                    if part_from <= part_to:
                        cursor.execute("""
                            INSERT INTO worker_absences (worker_id, date_from, date_to, kind, note)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (worker_id, part_from, part_to, old_kind, note))

            if kind:
                # Соседние дни того же вида - продлеваем их период, а не плодим однодневные
                cursor.execute("""
                    SELECT id, date_from, date_to FROM worker_absences
                    WHERE worker_id = %s AND kind = %s AND (date_to = %s OR date_from = %s)
                """, (worker_id, kind, day - timedelta(days=1), day + timedelta(days=1)))
                left = right = None
                for absence_id, date_from, date_to in cursor.fetchall():
                    if date_to == day - timedelta(days=1):
                        left = (absence_id, date_from)
                    else:
                        right = (absence_id, date_to)
                if left and right:
                    cursor.execute("UPDATE worker_absences SET date_to = %s WHERE id = %s", (right[1], left[0]))
                    cursor.execute("DELETE FROM worker_absences WHERE id = %s", (right[0],))
                elif left:
                    cursor.execute("UPDATE worker_absences SET date_to = %s WHERE id = %s", (day, left[0]))
                elif right:
                    cursor.execute("UPDATE worker_absences SET date_from = %s WHERE id = %s", (day, right[0]))
                else:
                    cursor.execute("""
                        INSERT INTO worker_absences (worker_id, date_from, date_to, kind)
                        VALUES (%s, %s, %s, %s)
                    """, (worker_id, day, day, kind))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_worker_schedule(self, date_from, date_to):
        """Статус каждого сотрудника на каждый день периода: {worker_id: {date: kind}}.
        Дни, когда сотрудник работает, в словарь не попадают. kind: 'day_off', 'vacation', 'sick'"""
        schedule = {}
        for absence in self.get_worker_absences(date_from, date_to):
            day = max(absence["date_from"], date_from)
            last = min(absence["date_to"], date_to)
            while day <= last:
                schedule.setdefault(absence["worker_id"], {})[day] = absence["kind"]
                day += timedelta(days=1)
        return schedule

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

    @staticmethod
    def _like_escape(text):
        """Текст для LIKE: % и _ из ввода - как обычные символы"""
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def _name_search(cls, column, text):
        """Условие и порядок для подсказки по названию (марки, модели).
        Одна буква - только названия, которые с неё начинаются (или их второе слово: "Land Rover" на "R").
        Больше - сначала начинающиеся с введённого, потом совпадение в начале слова, потом где угодно"""
        text = cls._like_escape(text.strip().lower())
        starts, word, anywhere = f"{text}%", f"% {text}%", f"%{text}%"
        if len(text) <= 1:
            where = f"(LOWER({column}) LIKE %s OR LOWER({column}) LIKE %s)"
            params = [starts, word]
        else:
            where = f"LOWER({column}) LIKE %s"
            params = [anywhere]
        order = (f"CASE WHEN LOWER({column}) LIKE %s THEN 0 WHEN LOWER({column}) LIKE %s THEN 1 ELSE 2 END, {column}")
        return where, params, order, [starts, word]

    def search_car_brands(self, search_text):
        """Подсказка марок: на одну букву - начинающиеся с неё; дальше - сначала начинающиеся с введённого"""
        if not (search_text or "").strip():
            return []
        where, params, order, order_params = self._name_search("brand_name", search_text)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT brand_name FROM car_brands WHERE {where} ORDER BY {order} LIMIT 30",
                       params + order_params)
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
            # Сначала начинающиеся с введённого, потом совпадение в начале слова, потом где угодно;
            # если ничего - буквы по порядку с пропусками ("rio" найдёт и "R-io")
            where, params, order, order_params = self._name_search("model_name", search_text)
            cursor.execute(
                f"SELECT model_name FROM car_models WHERE brand_id = %s AND {where} ORDER BY {order} LIMIT 50",
                [brand_id] + params + order_params
            )
            if not cursor.rowcount:
                pattern = "%" + "%".join(self._like_escape(ch) for ch in search_text.lower()) + "%"
                cursor.execute(
                    "SELECT model_name FROM car_models WHERE brand_id = %s AND LOWER(model_name) LIKE %s "
                    "ORDER BY model_name LIMIT 50", (brand_id, pattern))

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

    def add_work(self, worker_id, description, amount, work_date, mileage="", vin="", booking_id=None, car_id=None, items_json=None,
                 client_id=None):
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
                    "INSERT INTO works (worker_id, description, amount, work_date, completed_at, order_number, booking_id, car_id, mileage, items_json, client_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (worker_id, description, amount, work_date, completed_at, order_number, booking_id, car_id, mileage_int, items_json, client_id)
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

    def update_work(self, work_id, worker_id, description, amount, work_date, mileage="", vin="", booking_id=None, car_id=None, items_json=None,
                    client_id=None):
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
                booking_id = %s, car_id = %s, mileage = %s, items_json = %s,
                client_id = COALESCE(%s, client_id)
            WHERE id = %s
        ''', (worker_id, description, amount, work_date, booking_id, car_id, mileage_int, items_json, client_id, work_id))
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
                   wk.car_id, COALESCE(wk.client_id, cc.client_id)
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            LEFT JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
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
            LEFT JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
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
            LEFT JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
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

    def get_parts_totals_by_work_ids(self, work_ids):
        """{work_id: сумма запчастей} для многих нарядов одним запросом (история клиента)"""
        work_ids = [int(w) for w in work_ids if w]
        if not work_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        placeholders = ", ".join(["%s"] * len(work_ids))
        cursor.execute(f"SELECT work_id, COALESCE(SUM(part_price), 0) FROM parts "
                       f"WHERE work_id IN ({placeholders}) GROUP BY work_id", work_ids)
        totals = {row[0]: float(row[1]) for row in cursor.fetchall()}
        conn.close()
        return totals

    def get_warehouse_prices_by_work_ids(self, work_ids):
        """Цены деталей склада, установленных в наряды: {work_id: {название: цена}} (любой статус - и "выдано").
        Нужна, чтобы у запчасти "оплачено ранее" (в наряде она за 0) показать её настоящую цену зачёркнутой"""
        work_ids = [int(w) for w in work_ids if w]
        if not work_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        placeholders = ", ".join(["%s"] * len(work_ids))
        cursor.execute(f"SELECT work_id, part_name, price FROM warehouse_parts "
                       f"WHERE work_id IN ({placeholders}) AND price IS NOT NULL", work_ids)
        prices = {}
        for work_id, part_name, price in cursor.fetchall():
            prices.setdefault(work_id, {})[" ".join(str(part_name or "").split())] = float(price)
        conn.close()
        return prices

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
            LEFT JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
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
            LEFT JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
            WHERE UPPER(REPLACE(cc.car_number, ' ', '')) LIKE %s OR UPPER(REPLACE(cc.car_number, ' ', '')) LIKE %s
            ORDER BY wk.work_date DESC
        ''', ('%' + re.sub(r'\s', '', car_number).upper() + '%', '%' + plate_search_key(car_number) + '%'))
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
            LEFT JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
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
            LEFT JOIN client_cars cc ON wk.car_id = cc.id
            JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
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

    def count_bookings_soon(self, today):
        """Сколько записей (кроме отменённых) на сегодня, завтра и ближайшую неделю - одним запросом"""
        from datetime import timedelta as _td
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(booking_date = %s), 0), COALESCE(SUM(booking_date = %s), 0), COUNT(*)
            FROM bookings
            WHERE booking_date BETWEEN %s AND %s AND status <> 'cancelled'
        """, (today, today + _td(days=1), today, today + _td(days=6)))
        row = cursor.fetchone()
        conn.close()
        return {"today": int(row[0]), "tomorrow": int(row[1]), "week": int(row[2])}

    def count_bookings(self):
        """Сколько всего записей в базе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bookings")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_all_bookings(self, status=None, date_from=None, search=None, date_range=None):
        """Записи для вкладки "Записи".
        date_from - показывать с этой даты, но незавершённые ("ожидает", "в работе") - за любую дату;
        search - поиск по телефону / госномеру / машине по всей базе (период тогда не учитывается)"""
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
                   (SELECT w.order_number FROM works w WHERE w.booking_id = b.id
                    ORDER BY w.id DESC LIMIT 1) AS order_number, b.notes
                   FROM bookings b
                   LEFT JOIN clients c ON b.client_id = c.id
                   LEFT JOIN client_cars cc ON b.car_id = cc.id
                   WHERE 1=1"""
        params = []

        if status:
            query += " AND b.status = %s"
            params.append(status)

        search = (search or "").strip().lower()
        if search:
            like = f"%{search}%"
            conditions = ["LOWER(COALESCE(c.phone, '')) LIKE %s", "LOWER(COALESCE(cc.car_number, '')) LIKE %s",
                          "LOWER(CONCAT_WS(' ', cc.car_brand, cc.car_model, cc.car_number)) LIKE %s",
                          # Госномер набран латиницей (a123bc) или с пробелами - ищем как А123ВС
                          "UPPER(REPLACE(COALESCE(cc.car_number, ''), ' ', '')) LIKE %s"]
            params += [like, like, like, f"%{plate_search_key(search)}%"]
            digits = re.sub(r"\D", "", search)
            if digits:
                conditions.append("REGEXP_REPLACE(COALESCE(c.phone, ''), '[^0-9]', '') LIKE %s")
                params.append(f"%{digits}%")
                if len(digits) > 1 and digits[0] == "8":
                    # Телефоны хранятся как +7..., а набирают часто через 8: 8909... = начало номера 7909...
                    conditions.append("REGEXP_REPLACE(COALESCE(c.phone, ''), '[^0-9]', '') LIKE %s")
                    params.append(f"7{digits[1:]}%")
            query += " AND (" + " OR ".join(conditions) + ")"
        elif date_range:
            # Быстрый фильтр (сегодня / завтра / неделя) - ровно эти даты
            query += " AND b.booking_date BETWEEN %s AND %s"
            params += [date_range[0], date_range[1]]
        elif date_from:
            # Незавершённые - за любую дату; но "в ожидании" с прошедшей датой (просрочена: клиент не приехал,
            # заявка уже не актуальна) - как выполненные и отменённые, за период
            query += (" AND (b.booking_date >= %s OR b.status = 'in_progress'"
                      " OR (b.status = 'waiting' AND b.booking_date >= CURDATE()))")
            params.append(date_from)

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
                   (SELECT w.order_number FROM works w WHERE w.booking_id = b.id
                    ORDER BY w.id DESC LIMIT 1) AS order_number, b.notes
            FROM bookings b
            LEFT JOIN clients c ON b.client_id = c.id
            LEFT JOIN client_cars cc ON b.car_id = cc.id
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
        """Удалить запись вместе с её нарядами (works), иначе работы остаются в зарплате мастера в "Отчётах".
        Запчасти наряда (parts) удаляются каскадом, складские позиции отвязываются от наряда."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM works WHERE booking_id = %s", (booking_id,))
            work_ids = [row[0] for row in cursor.fetchall()]
            if work_ids:
                marks = ", ".join(["%s"] * len(work_ids))
                cursor.execute(f"UPDATE warehouse_parts SET work_id = NULL WHERE work_id IN ({marks})", work_ids)
                cursor.execute(f"DELETE FROM works WHERE id IN ({marks})", work_ids)
            cursor.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
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

    def day_capacity(self, day):
        """Сколько машин можно записать на одно время в этот день: настройка max_cars_per_slot, но не больше
        мастеров, которые в этот день работают (выходной / отпуск / больничный во вкладке "Сотрудники").
        Возвращает dict(capacity, setting, working, total, absent=[(имя, вид)]).
        Мастеров в программе нет - только настройка"""
        setting = max_cars_per_slot()
        workers = self.get_all_workers()
        schedule = self.get_worker_schedule(day, day)
        absent = [(name, schedule[worker_id][day]) for worker_id, name in workers
                  if day in schedule.get(worker_id, {})]
        working = len(workers) - len(absent)
        capacity = min(setting, working) if workers else setting
        return {"capacity": capacity, "setting": setting, "working": working, "total": len(workers),
                "absent": absent}

    def is_time_slot_available(self, booking_date, booking_time):
        """Проверить, есть ли на это время место (вместимость дня - day_capacity)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM bookings
            WHERE booking_date = %s AND booking_time = %s AND status IN ('waiting', 'in_progress')
        """, (booking_date, booking_time))
        count = cursor.fetchone()[0]
        conn.close()
        return count < self.day_capacity(booking_date)["capacity"]

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

    def get_bookings_by_date(self, booking_date):
        """Активные записи на дату, сгруппированные по времени: {"10:00": [{...}, ...]}"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.booking_time, c.full_name, car.car_number, car.car_brand, car.car_model
            FROM bookings b
            LEFT JOIN clients c ON b.client_id = c.id
            LEFT JOIN client_cars car ON b.car_id = car.id
            WHERE b.booking_date = %s AND b.status IN ('waiting', 'in_progress')
            ORDER BY b.booking_time, b.id
        """, (booking_date,))
        results = cursor.fetchall()
        conn.close()

        by_time = {}
        for booking_time, full_name, car_number, brand, model in results:
            by_time.setdefault(str(booking_time).strip(), []).append({
                'client_name': full_name or '',
                'car_number': car_number or '',
                'brand': brand or '',
                'model': model or ''
            })
        return by_time

    def get_active_bookings_for_select(self):
        """Получить активные записи для выпадающего списка."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id,
                   c.full_name,
                   c.phone,
                   b.booking_date, b.booking_time, b.car_id, b.client_id
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
        car_number = normalize_plate(car_number) if car_number else car_number
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

    def get_or_create_car(self, client_id, car_brand, car_model, car_number, update_info=False):
        """Найти или создать авто клиента. Возвращает car_id.
        update_info=True — перезаписать марку/модель найденной машины значениями из формы"""
        car_number = normalize_plate(car_number) if car_number else car_number
        if not car_number:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM client_cars WHERE UPPER(car_number) = UPPER(%s)", (car_number,))
        result = cursor.fetchone()

        if result:
            if client_id:
                cursor.execute("UPDATE client_cars SET client_id = %s WHERE id = %s", (client_id, result[0]))
            if update_info and car_brand and car_model:
                cursor.execute("UPDATE client_cars SET car_brand = %s, car_model = %s WHERE id = %s",
                               (car_brand, car_model, result[0]))
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

    def get_car_owner_by_number(self, car_number):
        """Машина по госномеру с текущим владельцем: dict(id, client_id, car_brand, car_model, car_number, vin,
        owner_name, owner_phone) или None"""
        car_number = normalize_plate(car_number) if car_number else car_number
        if not car_number:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cc.id, cc.client_id, cc.car_brand, cc.car_model, cc.car_number, cc.vin, cl.full_name, cl.phone
            FROM client_cars cc
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.car_number) = UPPER(%s)
            LIMIT 1
        """, (car_number,))
        row = cursor.fetchone()
        conn.close()
        return self._car_owner_row(row)

    def get_car_by_vin(self, vin, exclude_number=None):
        """Машина с таким VIN (кроме машины с госномером exclude_number) - тот же dict, что get_car_owner_by_number"""
        exclude_number = normalize_plate(exclude_number) if exclude_number else exclude_number
        vin = (vin or "").strip().upper()
        if not vin:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cc.id, cc.client_id, cc.car_brand, cc.car_model, cc.car_number, cc.vin, cl.full_name, cl.phone
            FROM client_cars cc
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.vin) = %s AND UPPER(cc.car_number) <> UPPER(%s)
            ORDER BY cc.id DESC
            LIMIT 1
        """, (vin, exclude_number or ""))
        row = cursor.fetchone()
        conn.close()
        return self._car_owner_row(row)

    @staticmethod
    def _car_owner_row(row):
        if not row:
            return None
        return {"id": row[0], "client_id": row[1], "car_brand": row[2] or "", "car_model": row[3] or "",
                "car_number": row[4] or "", "vin": row[5] or "", "owner_name": row[6] or "", "owner_phone": row[7] or ""}

    def transfer_car_history(self, car_id, client_id):
        """Машину продали: все наряды и записи этой машины переходят новому владельцу"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE works SET client_id = %s WHERE car_id = %s", (client_id, car_id))
        cursor.execute("UPDATE bookings SET client_id = %s WHERE car_id = %s", (client_id, car_id))
        conn.commit()
        conn.close()

    def update_car_number(self, car_id, car_number):
        """Сменить госномер машины (перерегистрация) - история машины остаётся с ней"""
        car_number = normalize_plate(car_number) if car_number else car_number
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE client_cars SET car_number = %s WHERE id = %s", (car_number.upper(), car_id))
        conn.commit()
        conn.close()

    def get_car_details(self, car_id):
        """Машина по ID со всеми полями для окна "Изменить данные": dict(id, client_id, car_brand, car_model,
        car_number, vin, mileage) или None"""
        if not car_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_id, car_brand, car_model, car_number, vin, mileage
            FROM client_cars WHERE id = %s
        """, (car_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {"id": row[0], "client_id": row[1], "car_brand": row[2] or "", "car_model": row[3] or "",
                "car_number": row[4] or "", "vin": row[5] or "", "mileage": row[6]}

    def find_other_car(self, car_id, car_number=None, vin=None):
        """Другая машина (не car_id) с таким госномером или VIN - чтобы правкой не получить две машины
        с одним номером. Возвращает ("number" | "vin", dict как get_car_owner_by_number) или None"""
        car_number = normalize_plate(car_number) if car_number else car_number
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            for field, value in (("number", (car_number or "").strip()), ("vin", (vin or "").strip())):
                if not value:
                    continue
                column = "cc.car_number" if field == "number" else "cc.vin"
                cursor.execute(f"""
                    SELECT cc.id, cc.client_id, cc.car_brand, cc.car_model, cc.car_number, cc.vin, cl.full_name, cl.phone
                    FROM client_cars cc
                    LEFT JOIN clients cl ON cc.client_id = cl.id
                    WHERE UPPER({column}) = UPPER(%s) AND cc.id <> %s
                    LIMIT 1
                """, (value, car_id))
                row = cursor.fetchone()
                if row:
                    return field, self._car_owner_row(row)
            return None
        finally:
            conn.close()

    def find_cars_with_first_letter_missing(self, car_number, limit=5):
        """Машины, госномер которых - car_number с ещё одной буквой спереди (ввели 123ВС77, а в базе А123ВС77):
        [dict как get_car_owner_by_number]"""
        car_number = normalize_plate(car_number)
        if not car_number:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cc.id, cc.client_id, cc.car_brand, cc.car_model, cc.car_number, cc.vin, cl.full_name, cl.phone
            FROM client_cars cc
            LEFT JOIN clients cl ON cc.client_id = cl.id
            WHERE UPPER(cc.car_number) LIKE %s
            ORDER BY cc.id DESC
            LIMIT %s
        """, ("_" + car_number.replace("_", "").replace("%", ""), limit))
        rows = cursor.fetchall()
        conn.close()
        return [self._car_owner_row(row) for row in rows]

    def update_car_info(self, car_id, car_brand, car_model, car_number, vin=None, mileage=None):
        """Исправить данные машины (опечатки): та же машина, история нарядов и записей остаётся при ней"""
        car_number = normalize_plate(car_number) if car_number else car_number
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE client_cars SET car_brand = %s, car_model = %s, car_number = %s, vin = %s, mileage = %s
            WHERE id = %s
        """, (car_brand, car_model, car_number.strip().upper(), (vin or "").strip().upper() or None,
              mileage, car_id))
        conn.commit()
        conn.close()

    def find_other_client_by_phone(self, phone, client_id):
        """Другой клиент (не client_id) с таким телефоном: dict(id, full_name, phone) или None"""
        digits = re.sub(r'\D', '', phone or "")[-10:]
        if len(digits) != 10:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, phone FROM clients
            WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s AND id <> %s
            LIMIT 1
        """, (digits, client_id))
        row = cursor.fetchone()
        conn.close()
        return {"id": row[0], "full_name": row[1] or "", "phone": row[2] or ""} if row else None

    def update_client_contact(self, client_id, full_name=None, phone=None):
        """Обновить имя / телефон клиента (пустое - не трогать)"""
        phone = normalize_phone(phone) if phone else None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE clients SET full_name = COALESCE(%s, full_name), phone = COALESCE(%s, phone) WHERE id = %s
        """, (full_name or None, phone or None, client_id))
        conn.commit()
        conn.close()

    def clear_client_phone(self, client_id):
        """Удалить телефон клиента (стёрли в форме и подтвердили удаление)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE clients SET phone = NULL WHERE id = %s", (client_id,))
        conn.commit()
        conn.close()

    def get_car_by_number(self, car_number):
        """Получить авто по госномеру"""
        car_number = normalize_plate(car_number) if car_number else car_number
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

    def get_client_by_phone(self, phone):
        """Клиент с этим телефоном (последние 10 цифр): {"id", "full_name", "phone"} или None"""
        phone_digits = re.sub(r'\D', '', phone or "")[-10:]
        if not phone_digits:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, phone FROM clients
            WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
            ORDER BY id LIMIT 1
        """, (phone_digits,))
        result = cursor.fetchone()
        conn.close()
        return {"id": result[0], "full_name": result[1] or "", "phone": result[2] or ""} if result else None

    def get_client_cars_by_client_id(self, client_id):
        """Машины клиента по его id (надёжнее имени: тёзки - разные клиенты)"""
        if not client_id:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT cc.car_brand, cc.car_model, cc.car_number, cc.vin
            FROM client_cars cc
            WHERE cc.client_id = %s
            AND cc.car_brand IS NOT NULL AND cc.car_brand != ''
            ORDER BY cc.car_brand, cc.car_model
        """, (client_id,))
        cars = cursor.fetchall()
        conn.close()
        return cars

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
            JOIN clients cl ON cl.id = COALESCE(wk.client_id, cc.client_id)
            WHERE COALESCE(wk.client_id, cc.client_id) = %s
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
        car_number = normalize_plate(car_number) if car_number else car_number
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
        car_number = normalize_plate(car_number) if car_number else car_number
        if not car_number:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cl.full_name as client_name, cl.phone as client_phone,
                   cc.car_brand, cc.car_model, cc.vin, cc.client_id
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
                "vin": row[4] or "",
                "client_id": row[5]
            })
        return clients

    def get_active_work_by_car_number(self, car_number):
        """Найти активную работу (в работе) по госномеру"""
        car_number = normalize_plate(car_number) if car_number else car_number
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
            LEFT JOIN clients cl ON cl.id = COALESCE(w.client_id, cc.client_id)
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
        car_number = normalize_plate(car_number) if car_number else car_number
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

    def unlink_warehouse_part_from_work(self, part_id):
        """Отвязать складскую позицию от наряда (деталь убрали из наряда и вернули на склад)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE warehouse_parts SET work_id = NULL WHERE id = %s", (part_id,))
        conn.commit()
        conn.close()

    def get_warehouse_parts_by_work_id(self, work_id):
        """Складские позиции, установленные в наряд: (id, part_name, quantity, price, notes, is_paid)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, part_name, quantity, price, notes, is_paid
            FROM warehouse_parts
            WHERE work_id = %s AND status = 'установлена'
            ORDER BY id
        """, (work_id,))
        parts = cursor.fetchall()
        conn.close()
        return parts

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

    def get_app_setting(self, name):
        """Значение общей настройки из app_settings (None, если не задана)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE name = %s", (name,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def set_app_setting(self, name, value):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO app_settings (name, value) VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE value = VALUES(value)
        """, (name, value))
        conn.commit()
        conn.close()

    def has_reports_password(self) -> bool:
        """Задан ли пароль для просмотра отчётов за другие даты"""
        return bool(self.get_app_setting("reports_password"))

    def set_reports_password(self, password: str):
        pwd_hash, salt = self._hash_password(password)
        self.set_app_setting("reports_password", f"{salt}${pwd_hash}")

    def check_reports_password(self, password: str) -> bool:
        stored = self.get_app_setting("reports_password")
        if not stored or "$" not in stored:
            return False
        salt, pwd_hash = stored.split("$", 1)
        return self._hash_password(password, salt)[0] == pwd_hash

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
