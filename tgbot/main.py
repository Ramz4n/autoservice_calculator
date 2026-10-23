# -*- coding: utf-8 -*-
"""
Telegram бот для автосервиса - единый файл для PyInstaller
"""

import asyncio
import logging
import os
import re
import json
import threading
import sys
import subprocess
import ipaddress
import html
from uuid import uuid4
from datetime import datetime, timedelta, date as dt_date

try:
    from yookassa import Configuration as YKConfiguration, Payment as YKPayment
    YOKASSA_AVAILABLE = True
except ImportError:
    YOKASSA_AVAILABLE = False

import aiohttp
import aiohttp.web
import aiomysql
from aiogram import Bot, Dispatcher, Router, F

# System tray
import pystray
from PIL import Image, ImageDraw
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from pathlib import Path

# ==================== CONFIG ====================

def get_base_path():
    """Получить базовый путь приложения (работает и для PyInstaller)"""
    if getattr(sys, 'frozen', False):
        # Запущено как exe (PyInstaller)
        return Path(sys.executable).parent
    else:
        # Запущено как скрипт
        return Path(__file__).parent.parent

_base_path = get_base_path()

# Загружаем .env из config/
_env_path = _base_path / "config" / ".env"
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "alexauto")
}

# ЮKassa
YOKASSA_SHOP_ID = os.getenv("YOKASSA_SHOP_ID", "")
YOKASSA_SECRET_KEY = os.getenv("YOKASSA_SECRET_KEY", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
ADMIN_TELEGRAM_ID_STR = os.getenv("ADMIN_TELEGRAM_ID", "")
ADMIN_TELEGRAM_ID = int(ADMIN_TELEGRAM_ID_STR) if ADMIN_TELEGRAM_ID_STR.isdigit() else None
YOKASSA_DEV_MODE = os.getenv("YOKASSA_DEV_MODE", "False").lower() in ("true", "1", "yes")

# Настройка ЮKassa SDK
if YOKASSA_AVAILABLE and YOKASSA_SHOP_ID and YOKASSA_SECRET_KEY:
    YKConfiguration.account_id = YOKASSA_SHOP_ID
    YKConfiguration.secret_key = YOKASSA_SECRET_KEY

WORKING_HOURS_START = 10
WORKING_HOURS_END = 20
SLOT_DURATION = 2
TIME_SLOTS = [f"{hour:02d}:00" for hour in range(WORKING_HOURS_START, WORKING_HOURS_END + 1, SLOT_DURATION)]

# Загружаем настройки из settings.json
_settings_path = _base_path / "config" / "settings.json"
try:
    with open(_settings_path, "r", encoding="utf-8") as f:
        _settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    _settings = {}

# Данные компании
COMPANY_NAME = _settings.get("company_name", "Автосервис")
COMPANY_ADDRESS = _settings.get("company_address", "")
COMPANY_PHONE = _settings.get("company_phone", "")
COMPANY_INFO = f"{COMPANY_NAME}\n{COMPANY_ADDRESS}\nТел: {COMPANY_PHONE}"

# Переопределяем из settings.json если есть
WORKING_HOURS_START = _settings.get("working_hours_start", WORKING_HOURS_START)
WORKING_HOURS_END = _settings.get("working_hours_end", WORKING_HOURS_END)
SLOT_DURATION_MINUTES = _settings.get("slot_duration_minutes", 120)
MAX_BOOKINGS_PER_USER = _settings.get("max_bookings_per_user", 2)
# Сколько машин можно записать на одно время (столько постов/подъёмников)
MAX_CARS_PER_SLOT = max(1, int(_settings.get("max_cars_per_slot", 1)))

# Генерация слотов времени (поддержка любого интервала в минутах)
def _generate_time_slots():
    slots = []
    start_minutes = WORKING_HOURS_START * 60
    end_minutes = WORKING_HOURS_END * 60
    current = start_minutes
    while current <= end_minutes:
        hours = current // 60
        minutes = current % 60
        slots.append(f"{hours:02d}:{minutes:02d}")
        current += SLOT_DURATION_MINUTES
    return slots

TIME_SLOTS = _generate_time_slots()

# ==================== SUBSCRIPTION PLANS ====================
SUBSCRIPTION_PLANS = {
    'basic': {
        'name': '🟢 Basic',
        'price': 9900.00,
        'features': [
            '2 замены масла (работа бесплатно)',
            'Диагностика ходовой 2 раза',
            'Проверка АКБ',
            'Проверка тормозов',
            'Проверка жидкостей',
            'Скидка 10% на работу',
        ]
    },
    'premium': {
        'name': '🔵 Premium',
        'price': 23900.00,
        'features': [
            '2 замены масла (всё включено)',
            'Эвакуатор 1 раз',
            'Диагностика 3 раза',
            'Проверка подвески',
            'Проверка тормозов',
            'Проверка АКБ',
            'Проверка кондиционера',
            'Приоритетная запись',
            'Скидка 15% на работу',
        ]
    },
    'vip': {
        'name': '🟡 VIP',
        'price': 39900.00,
        'features': [
            '2 замены масла (всё включено)',
            'Эвакуатор 2 раза',
            'Диагностика без ограничений',
            'Проверка подвески',
            'Проверка тормозов',
            'Проверка АКБ',
            'Проверка кондиционера',
            'Сезонная подготовка авто',
            'Приоритетная запись',
            'Скидка 20% на работу',
        ]
    }
}

# ==================== YOKASSA IP WHITELIST ====================
_YOKASSA_IP_NETWORKS = [
    ipaddress.ip_network('185.71.76.0/27'),
    ipaddress.ip_network('185.71.77.0/27'),
    ipaddress.ip_network('77.75.153.0/25'),
    ipaddress.ip_network('77.75.154.128/25'),
    ipaddress.ip_network('2a02:5180::/32'),
]
_YOKASSA_SINGLE_IPS = {'77.75.156.11', '77.75.156.35'}


def is_yokassa_ip(ip_str: str) -> bool:
    if YOKASSA_DEV_MODE:
        return True
    try:
        if ip_str in _YOKASSA_SINGLE_IPS:
            return True
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in _YOKASSA_IP_NETWORKS)
    except ValueError:
        return False


# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await aiomysql.create_pool(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            db=DB_CONFIG["database"],
            autocommit=True
        )

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def init_tables(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS clients (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        telegram_user_id BIGINT UNIQUE,
                        tg_username VARCHAR(255),
                        full_name VARCHAR(255),
                        phone VARCHAR(50),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_phone (phone)
                    ) ENGINE=InnoDB
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS bookings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        client_id INT,
                        car_id INT,
                        booking_date DATE NOT NULL,
                        booking_time VARCHAR(10) NOT NULL,
                        status VARCHAR(20) DEFAULT 'waiting',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_booking_datetime (booking_date, booking_time)
                    ) ENGINE=InnoDB
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS telegraph_pages (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL UNIQUE,
                        page_path VARCHAR(255),
                        access_token VARCHAR(255),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                """)
                for alter in [
                    "ALTER TABLE bookings ADD COLUMN status VARCHAR(20) DEFAULT 'waiting'",
                    "ALTER TABLE bookings ADD COLUMN client_id INT AFTER id",
                    "ALTER TABLE bookings ADD COLUMN car_id INT AFTER client_id",
                    "ALTER TABLE bookings ADD COLUMN reminder_sent BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE bookings ADD COLUMN reminder_1h_sent BOOLEAN DEFAULT FALSE",
                ]:
                    try:
                        await cur.execute(alter)
                    except:
                        pass
                try:
                    await cur.execute("ALTER TABLE bookings DROP INDEX unique_booking")
                except:
                    pass
                # Telegram-аккаунт подтвердил номер клиента кнопкой «Поделиться номером» (link_verified_phone) -
                # только такому аккаунту бот показывает историю авто, машины и записи
                await cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS tg_verified TINYINT(1) NOT NULL DEFAULT 0")
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS client_cars (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        client_id INT,
                        car_brand VARCHAR(100),
                        car_model VARCHAR(100),
                        car_number VARCHAR(20),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_car_number (car_number)
                    ) ENGINE=InnoDB
                """)
                try:
                    await cur.execute("ALTER TABLE client_cars ADD COLUMN client_id INT AFTER id")
                except:
                    pass
                for idx in [
                    "CREATE INDEX idx_bookings_client_id ON bookings(client_id)",
                    "CREATE INDEX idx_client_cars_client_id ON client_cars(client_id)",
                ]:
                    try:
                        await cur.execute(idx)
                    except:
                        pass

                # Таблица подписок
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id          INT AUTO_INCREMENT PRIMARY KEY,
                        client_id   INT NOT NULL,
                        plan        ENUM('basic','premium','vip') NOT NULL,
                        status      ENUM('active','expired','pending') DEFAULT 'pending',
                        started_at  DATETIME,
                        expires_at  DATETIME,
                        payment_id  VARCHAR(100) UNIQUE,
                        amount      DECIMAL(10,2),
                        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (client_id) REFERENCES clients(id)
                    ) ENGINE=InnoDB
                """)

    def _normalize_phone(self, phone: str) -> str | None:
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

    async def link_verified_phone(self, telegram_user_id: int, phone: str, full_name: str = None, tg_username: str = None) -> int:
        """Привязать Telegram-аккаунт к клиенту по номеру, который подтвердил сам Telegram (кнопка «Поделиться номером»).

        Только так аккаунт получает доступ к истории авто, машинам и записям клиента: номер, набранный текстом,
        или госномер может указать кто угодно - и получить чужую историю.
        Имя и телефон, записанные в программе, не перезаписываются."""
        suffix = phone[-10:]
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, phone FROM clients WHERE telegram_user_id = %s", (telegram_user_id,))
                bound = await cur.fetchone()
                await cur.execute(
                    """SELECT id FROM clients WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
                       ORDER BY telegram_user_id <=> %s DESC, id LIMIT 1""",
                    (suffix, telegram_user_id)
                )
                owner = await cur.fetchone()
                owner_id = owner[0] if owner else None

                if bound and (bound[0] == owner_id or (not bound[1] and not owner_id)):
                    client_id = bound[0]  # уже привязан к этому номеру, или клиент создан ботом без номера
                else:
                    if bound:
                        # Аккаунт был привязан к клиенту с другим номером - такая привязка могла появиться,
                        # когда номер вводили текстом. Снимаем её. Клиент без номера (создан ботом при покупке
                        # подписки) - это тот же человек: его подписки переносим владельцу номера.
                        if not bound[1] and owner_id:
                            await cur.execute("UPDATE subscriptions SET client_id = %s WHERE client_id = %s", (owner_id, bound[0]))
                        await cur.execute("UPDATE clients SET telegram_user_id = NULL, tg_verified = 0 WHERE id = %s", (bound[0],))
                        logger.warning(f"Telegram {telegram_user_id}: снята привязка к клиенту id={bound[0]} "
                                       f"(номер клиента не совпал с подтверждённым)")
                    if owner_id:
                        client_id = owner_id
                    else:
                        await cur.execute("INSERT INTO clients (full_name, phone) VALUES (%s, %s)", (full_name, phone))
                        client_id = cur.lastrowid
                # если номер раньше подтверждал другой Telegram-аккаунт - теперь он принадлежит этому
                await cur.execute("""
                    UPDATE clients SET
                        telegram_user_id = %s,
                        tg_verified = 1,
                        tg_username = COALESCE(%s, tg_username),
                        full_name = COALESCE(NULLIF(full_name, ''), %s),
                        phone = COALESCE(NULLIF(phone, ''), %s)
                    WHERE id = %s
                """, (telegram_user_id, tg_username or None, full_name, phone, client_id))
                return client_id

    async def get_verified_client_id(self, telegram_user_id: int) -> int | None:
        """Клиент, номер которого этот Telegram-аккаунт подтвердил; иначе None"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (telegram_user_id,))
                row = await cur.fetchone()
                return row[0] if row else None

    async def get_client_by_telegram_id(self, telegram_user_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT * FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (telegram_user_id,))
                return await cur.fetchone()

    async def get_or_create_car(self, client_id: int, car_brand: str, car_model: str, car_number: str) -> int | None:
        if not car_number:
            return None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM client_cars WHERE UPPER(car_number) = UPPER(%s)", (car_number,))
                result = await cur.fetchone()
                if result:
                    if client_id:
                        await cur.execute("UPDATE client_cars SET client_id = %s WHERE id = %s", (client_id, result[0]))
                    return result[0]
                await cur.execute("""
                    INSERT INTO client_cars (client_id, car_brand, car_model, car_number)
                    VALUES (%s, %s, %s, %s)
                """, (client_id, car_brand, car_model, car_number.upper()))
                return cur.lastrowid

    async def is_slot_available(self, booking_date: dt_date, booking_time: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM bookings WHERE booking_date = %s AND booking_time = %s AND status IN ('waiting', 'in_progress')",
                    (booking_date, booking_time)
                )
                result = await cur.fetchone()
                return result[0] < MAX_CARS_PER_SLOT

    async def get_booked_slots(self, booking_date: dt_date) -> list:
        """Время, на которое мест уже нет (записано MAX_CARS_PER_SLOT машин)"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT booking_time FROM bookings WHERE booking_date = %s AND status IN ('waiting', 'in_progress')
                       GROUP BY booking_time HAVING COUNT(*) >= %s""",
                    (booking_date, MAX_CARS_PER_SLOT)
                )
                result = await cur.fetchall()
                return [row[0] for row in result]

    async def create_booking(self, booking_date: dt_date, booking_time: str, client_id: int, car_id: int = None) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """INSERT INTO bookings (client_id, car_id, booking_date, booking_time, status) VALUES (%s, %s, %s, %s, 'waiting')""",
                        (client_id, car_id, booking_date, booking_time)
                    )
                    return True
        except Exception as e:
            print(f"Ошибка создания записи: {e}")
            return False

    async def get_user_bookings(self, user_id: int) -> list:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (user_id,))
                client_row = await cur.fetchone()
                if not client_row:
                    return []
                client_id = client_row['id']
                await cur.execute(
                    """SELECT b.id, b.booking_date, b.booking_time, b.status, b.created_at,
                       c.full_name as client_name, c.phone as client_phone,
                       CONCAT(cc.car_brand, ' ', cc.car_model, ' ', cc.car_number) as car_display
                       FROM bookings b
                       JOIN clients c ON b.client_id = c.id
                       LEFT JOIN client_cars cc ON b.car_id = cc.id
                       WHERE b.client_id = %s AND b.booking_date >= CURDATE() AND b.status IN ('waiting', 'in_progress')
                       ORDER BY b.booking_date, b.booking_time""",
                    (client_id,)
                )
                return await cur.fetchall()

    async def cancel_booking(self, booking_id: int, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (user_id,))
                client_row = await cur.fetchone()
                if not client_row:
                    return False
                await cur.execute("UPDATE bookings SET status = 'cancelled' WHERE id = %s AND client_id = %s", (booking_id, client_row[0]))
                return cur.rowcount > 0

    async def count_user_active_bookings(self, user_id: int) -> int:
        """Подсчёт активных записей пользователя"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (user_id,))
                client_row = await cur.fetchone()
                if not client_row:
                    return 0
                await cur.execute(
                    """SELECT COUNT(*) FROM bookings
                       WHERE client_id = %s AND booking_date >= CURDATE() AND status IN ('waiting', 'in_progress')""",
                    (client_row[0],)
                )
                result = await cur.fetchone()
                return result[0] if result else 0

    async def get_user_phone(self, user_id: int) -> str | None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT phone FROM clients WHERE telegram_user_id = %s AND tg_verified = 1 AND phone IS NOT NULL", (user_id,))
                result = await cur.fetchone()
                return result[0] if result and result[0] else None

    async def get_client_cars(self, user_id: int) -> list[tuple]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (user_id,))
                client_row = await cur.fetchone()
                if not client_row:
                    return []
                client_id = client_row[0]
                await cur.execute("""
                    SELECT DISTINCT car_brand, car_model, car_number
                    FROM client_cars WHERE client_id = %s AND car_brand IS NOT NULL AND car_brand != ''
                    ORDER BY car_brand, car_model
                """, (client_id,))
                return list(await cur.fetchall())

    async def get_user_phones(self, user_id: int) -> list[str]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT phone FROM clients WHERE telegram_user_id = %s AND tg_verified = 1 AND phone IS NOT NULL", (user_id,))
                result = await cur.fetchone()
                if result and result[0]:
                    return [result[0]]
                return []

    async def get_car_history_by_user_id(self, telegram_user_id: int) -> list:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (telegram_user_id,))
                client_row = await cur.fetchone()
                if not client_row:
                    return []
                client_id = client_row['id']
                await cur.execute(
                    """SELECT w.id as work_id, w.work_date,
                              cc.car_brand, cc.car_model, cc.car_number,
                              w.description, w.amount, w.order_number, cc.mileage,
                              (SELECT COALESCE(SUM(p.part_price), 0) FROM parts p WHERE p.work_id = w.id) as parts_total
                       FROM works w
                       JOIN client_cars cc ON w.car_id = cc.id
                       WHERE cc.client_id = %s
                       ORDER BY w.work_date DESC, w.id DESC
                       LIMIT 20""",
                    (client_id,)
                )
                return await cur.fetchall()

    async def get_parts_by_work_id(self, work_id: int) -> list:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT part_name, part_price FROM parts WHERE work_id = %s", (work_id,))
                return await cur.fetchall()

    async def get_keywords_with_intervals(self) -> list:
        """Получить ключевые слова с настроенными интервалами ТО"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT id, keyword, interval_km_min, interval_km_max
                    FROM keywords
                    WHERE interval_km_min IS NOT NULL AND interval_km_max IS NOT NULL
                    ORDER BY keyword
                """)
                return await cur.fetchall()

    async def get_car_works_for_analysis(self, car_id: int) -> list:
        """Получить все работы по авто для анализа ТО"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT w.id, w.description, w.work_date, w.mileage as work_mileage
                    FROM works w
                    WHERE w.car_id = %s
                    ORDER BY w.work_date DESC, w.id DESC
                """, (car_id,))
                return await cur.fetchall()

    async def get_car_by_id_full(self, car_id: int) -> dict | None:
        """Получить полную информацию об авто по ID"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT id, client_id, car_brand, car_model, car_number, mileage
                    FROM client_cars WHERE id = %s
                """, (car_id,))
                return await cur.fetchone()

    async def update_car_mileage(self, car_id: int, mileage: int):
        """Обновить пробег авто"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE client_cars SET mileage = %s WHERE id = %s", (str(mileage), car_id))

    async def get_client_cars_with_id(self, user_id: int) -> list:
        """Получить машины клиента с ID"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id FROM clients WHERE telegram_user_id = %s AND tg_verified = 1", (user_id,))
                client_row = await cur.fetchone()
                if not client_row:
                    return []
                client_id = client_row['id']
                await cur.execute("""
                    SELECT id, car_brand, car_model, car_number, mileage
                    FROM client_cars WHERE client_id = %s AND car_brand IS NOT NULL AND car_brand != ''
                    ORDER BY car_brand, car_model
                """, (client_id,))
                return await cur.fetchall()

    async def get_telegraph_pages(self) -> list:
        """Страницы истории, опубликованные раньше на telegra.ph (см. wipe_telegraph_pages)"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id, page_path, access_token FROM telegraph_pages")
                return await cur.fetchall()

    async def delete_telegraph_page(self, page_id: int):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM telegraph_pages WHERE id = %s", (page_id,))

    async def get_tomorrow_bookings_for_reminder(self) -> list:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT b.id, b.booking_date, b.booking_time, c.telegram_user_id, c.full_name
                    FROM bookings b
                    JOIN clients c ON b.client_id = c.id
                    WHERE b.booking_date = DATE_ADD(CURDATE(), INTERVAL 1 DAY)
                      AND b.status = 'waiting'
                      AND (b.reminder_sent IS NULL OR b.reminder_sent = FALSE)
                      AND c.telegram_user_id IS NOT NULL
                """)
                return await cur.fetchall()

    async def mark_reminder_sent(self, booking_id: int):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bookings SET reminder_sent = TRUE WHERE id = %s", (booking_id,))

    async def get_bookings_for_1h_reminder(self) -> list:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT b.id, b.booking_date, b.booking_time, c.telegram_user_id, c.full_name
                    FROM bookings b
                    JOIN clients c ON b.client_id = c.id
                    WHERE b.booking_date = CURDATE()
                      AND b.status = 'waiting'
                      AND (b.reminder_1h_sent IS NULL OR b.reminder_1h_sent = FALSE)
                      AND c.telegram_user_id IS NOT NULL
                      AND TIME(CONCAT(b.booking_time, ':00')) BETWEEN
                          ADDTIME(CURTIME(), '00:30:00') AND ADDTIME(CURTIME(), '01:30:00')
                """)
                return await cur.fetchall()

    async def mark_reminder_1h_sent(self, booking_id: int):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bookings SET reminder_1h_sent = TRUE WHERE id = %s", (booking_id,))

    # --- Методы для подписок ---

    async def get_active_subscription(self, client_id: int) -> dict | None:
        """Получить активную подписку клиента"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT * FROM subscriptions
                    WHERE client_id = %s AND status = 'active' AND expires_at > NOW()
                    ORDER BY expires_at DESC LIMIT 1
                """, (client_id,))
                return await cur.fetchone()

    async def create_pending_subscription(self, client_id: int, plan: str, payment_id: str, amount: float):
        """Создать запись о подписке со статусом pending при инициации оплаты"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO subscriptions (client_id, plan, status, payment_id, amount)
                    VALUES (%s, %s, 'pending', %s, %s)
                """, (client_id, plan, payment_id, amount))

    async def activate_subscription(self, payment_id: str) -> bool:
        """Активировать подписку после успешной оплаты.
        Возвращает True если активирована, False если уже была активная."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Получаем pending-запись
                await cur.execute(
                    "SELECT client_id FROM subscriptions WHERE payment_id = %s AND status = 'pending'",
                    (payment_id,)
                )
                row = await cur.fetchone()
                if not row:
                    return False
                client_id = row[0]
                # Если уже есть активная подписка — не активируем повторно
                await cur.execute(
                    "SELECT id FROM subscriptions WHERE client_id = %s AND status = 'active' AND expires_at > NOW()",
                    (client_id,)
                )
                if await cur.fetchone():
                    await cur.execute(
                        "UPDATE subscriptions SET status = 'expired' WHERE payment_id = %s",
                        (payment_id,)
                    )
                    return False
                # Активируем
                await cur.execute("""
                    UPDATE subscriptions
                    SET status = 'active',
                        started_at = NOW(),
                        expires_at = DATE_ADD(NOW(), INTERVAL 1 YEAR)
                    WHERE payment_id = %s AND status = 'pending'
                """, (payment_id,))
                return cur.rowcount > 0

    async def cancel_pending_subscriptions(self, client_id: int):
        """Отменить все pending-подписки клиента (перед созданием новой)"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE subscriptions SET status = 'expired' WHERE client_id = %s AND status = 'pending'",
                    (client_id,)
                )

    async def get_subscription_by_payment_id(self, payment_id: str) -> dict | None:
        """Получить подписку по ID платежа"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM subscriptions WHERE payment_id = %s",
                    (payment_id,)
                )
                return await cur.fetchone()

    async def get_client_by_id(self, client_id: int) -> dict | None:
        """Получить клиента по внутреннему ID"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
                return await cur.fetchone()


db = Database()

# ==================== TELEGRAPH ====================
# Раньше история авто публиковалась на telegra.ph. Такая страница открывается у любого, у кого есть ссылка,
# а ссылку можно подобрать (она складывается из заголовка и даты). Теперь история показывается прямо в чате,
# а старые страницы затираются при запуске бота (wipe_telegraph_pages) - удалить страницу Telegraph нельзя.
TELEGRAPH_API = "https://api.telegra.ph"

async def telegraph_edit_page(access_token: str, path: str, title: str, content: list) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{TELEGRAPH_API}/editPage", data={
                "access_token": access_token,
                "path": path,
                "title": title,
                "content": json.dumps(content),
                "return_content": "false"
            }) as resp:
                result = await resp.json()
                if result.get("ok"):
                    return result["result"]
    except:
        pass
    return None

# ==================== BOT ====================
router = Router()

class BookingStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_phone = State()
    waiting_for_car = State()


class CarCheckStates(StatesGroup):
    selecting_car = State()
    entering_mileage = State()


class SubscriptionStates(StatesGroup):
    waiting_for_confirm = State()


def get_persistent_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Меню"), KeyboardButton(text="🚗 История авто")]],
        resize_keyboard=True,
        is_persistent=True
    )


def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📝 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton(text="🚗 История авто", callback_data="car_history")],
        [InlineKeyboardButton(text="🔍 Проверить состояние авто", callback_data="check_car")],
        [InlineKeyboardButton(text="⭐ Подписка", callback_data="subscription")],
        [InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking")]
    ])


def get_plans_keyboard():
    """Клавиатура выбора тарифа подписки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Basic — 9 900 ₽/год", callback_data="sub_plan_basic")],
        [InlineKeyboardButton(text="🔵 Premium — 23 900 ₽/год", callback_data="sub_plan_premium")],
        [InlineKeyboardButton(text="🟡 VIP — 39 900 ₽/год", callback_data="sub_plan_vip")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])


def get_book_again_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться снова", callback_data="book")],
        [InlineKeyboardButton(text="📋 Главное меню", callback_data="back_to_menu")]
    ])


def get_contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)], [KeyboardButton(text="📋 Меню")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


CONTACT_PROMPT = ("🔒 История авто и записи видны только владельцу номера.\n\n"
                  "Подтвердите номер телефона — нажмите кнопку «📱 Поделиться номером» внизу экрана. "
                  "Telegram передаст номер, к которому привязан ваш аккаунт.")


async def ask_contact(message: Message, text: str = CONTACT_PROMPT):
    await message.answer(text, reply_markup=get_contact_keyboard())


async def require_verified(event: Message | CallbackQuery) -> int | None:
    """id клиента, если этот Telegram-аккаунт подтвердил номер; иначе просит подтвердить и возвращает None.
    На callback не отвечает - это делает обработчик."""
    client_id = await db.get_verified_client_id(event.from_user.id)
    if not client_id:
        await ask_contact(event.message if isinstance(event, CallbackQuery) else event)
    return client_id


async def verified_contact_phone(message: Message) -> str | None:
    """Номер из кнопки «Поделиться номером». Принимается только свой контакт: карточку чужого контакта
    (или набранную вручную) Telegram не подтверждает."""
    contact = message.contact
    if not contact or contact.user_id != message.from_user.id:
        await message.answer("❌ Нужен ваш собственный номер — нажмите кнопку «📱 Поделиться номером» внизу экрана.",
                             reply_markup=get_contact_keyboard())
        return None
    phone = validate_phone(contact.phone_number)
    if not phone:
        await message.answer(f"❌ Через бота можно записаться только с российским номером (+7).\n\n{COMPANY_INFO}",
                             reply_markup=get_persistent_menu())
        return None
    return phone


def get_date_keyboard():
    buttons = []
    today = datetime.now().date()
    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][date.weekday()]
        buttons.append([InlineKeyboardButton(text=f"{day_name} {date_str}", callback_data=f"date_{date.isoformat()}")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_time_keyboard(booking_date: str):
    date_obj = dt_date.fromisoformat(booking_date)
    booked_slots = await db.get_booked_slots(date_obj)

    # Проверяем, является ли дата сегодняшней
    now = datetime.now()
    is_today = date_obj == now.date()
    current_time = now.hour * 60 + now.minute  # текущее время в минутах

    buttons = []
    row = []
    for time_slot in TIME_SLOTS:
        # Если сегодня - пропускаем прошедшие слоты
        if is_today:
            slot_hour, slot_min = map(int, time_slot.split(':'))
            slot_time = slot_hour * 60 + slot_min
            if slot_time <= current_time:
                continue  # пропускаем прошедший слот

        if time_slot in booked_slots:
            row.append(InlineKeyboardButton(text=f"{time_slot} (занято)", callback_data="slot_busy"))
        else:
            row.append(InlineKeyboardButton(text=f"{time_slot}", callback_data=f"time_{booking_date}_{time_slot}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="book")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def validate_phone(phone: str) -> str | None:
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    if len(digits) == 11 and digits.startswith('7'):
        return '+' + digits
    return None


async def show_car_selection_or_create_booking(message_or_callback, state: FSMContext, user_id: int, username: str,
                                                full_name: str, phone: str, booking_date, booking_time: str,
                                                is_callback: bool = False):
    client_id = await db.get_verified_client_id(user_id)  # номер подтверждён до этого шага
    cars = await db.get_client_cars(user_id)

    if len(cars) >= 1:
        await state.update_data(
            phone=phone,
            booking_date=booking_date.isoformat() if hasattr(booking_date, 'isoformat') else booking_date,
            booking_time=booking_time,
            client_id=client_id
        )
        await state.set_state(BookingStates.waiting_for_car)
        buttons = []
        for i, (brand, model, number) in enumerate(cars):
            car_display = f"{brand} {model} {number}".strip()
            buttons.append([InlineKeyboardButton(text=f"🚗 {car_display}", callback_data=f"selectcar_{i}")])
        buttons.append([InlineKeyboardButton(text="➕ Другое авто", callback_data="selectcar_skip")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        cars_list = [f"{b} {m} {n}".strip() for b, m, n in cars]
        await state.update_data(cars_list=cars_list)
        date_display = booking_date.strftime("%d.%m.%Y") if hasattr(booking_date, 'strftime') else booking_date
        text = f"📅 Дата: {date_display}\n🕐 Время: {booking_time}\n📱 Телефон: {phone}\n\n🚗 Выберите автомобиль:"
        if is_callback:
            await message_or_callback.message.edit_text(text, reply_markup=keyboard)
        else:
            await message_or_callback.answer(text, reply_markup=keyboard)
        return

    car_id = None
    success = await db.create_booking(booking_date=booking_date, booking_time=booking_time, client_id=client_id, car_id=car_id)
    await state.clear()
    date_display = booking_date.strftime("%d.%m.%Y") if hasattr(booking_date, 'strftime') else booking_date

    if success:
        text = f"✅ <b>Вы успешно записаны!</b>\n\n📅 Дата: {date_display}\n🕐 Время: {booking_time}\n📱 Телефон: {phone}"
        text += f"\n\n{COMPANY_INFO}\n\nЖдём вас!"
        if is_callback:
            await message_or_callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="HTML")
        else:
            await message_or_callback.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")
    else:
        if is_callback:
            await message_or_callback.message.edit_text("❌ Произошла ошибка при записи.\nПопробуйте ещё раз.", reply_markup=get_main_menu())
        else:
            await message_or_callback.answer("❌ Произошла ошибка при записи.\nПопробуйте ещё раз.", reply_markup=get_main_menu())


async def history_messages(history: list) -> list[str]:
    """История обслуживания для чата (HTML), разбитая на сообщения не длиннее лимита Telegram"""
    e = html.escape
    car_title = lambda w: f"{w['car_brand'] or ''} {w['car_model'] or ''} {w['car_number'] or ''}".strip() or "Автомобиль не указан"
    cars = {}
    for work in history:
        cars.setdefault(car_title(work), []).append(work)

    blocks = ["🚗 <b>История обслуживания</b>"]
    for car, works in cars.items():
        blocks.append(f"🚙 <b>{e(car)}</b>")
        for work in works:
            work_amount = float(work['amount'] or 0)
            parts_total = float(work['parts_total'] or 0)
            header = f"📅 {work['work_date'].strftime('%d.%m.%Y') if work['work_date'] else '—'}"
            if work['order_number']:
                header += f" • №{e(str(work['order_number']))}"
            lines = [f"<b>{header}</b>"]
            if work['mileage']:
                lines.append(f"🔢 Пробег: {e(str(work['mileage']))} км")
            if work['description']:
                lines.append(f"📝 Работы: {work_amount:,.0f} ₽".replace(',', ' '))
                lines += [f"  • {e(item.strip())}" for item in work['description'].split(',') if item.strip()]
            parts = await db.get_parts_by_work_id(work['work_id']) if work.get('work_id') else []
            if parts:
                lines.append(f"🔧 Запчасти: {parts_total:,.0f} ₽".replace(',', ' '))
                lines += [f"  • {e(str(name))} — {float(price or 0):,.0f} ₽".replace(',', ' ') for name, price in parts]
            lines.append(f"💰 Итого: {work_amount + parts_total:,.0f} ₽".replace(',', ' '))
            blocks.append("\n".join(lines))

    messages, current = [], ""
    for block in blocks:
        if current and len(current) + len(block) > 3500:
            messages.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    messages.append(current)
    return messages


async def send_car_history(message: Message, telegram_user_id: int):
    history = await db.get_car_history_by_user_id(telegram_user_id)
    if not history:
        await message.answer("🔍 История не найдена.\n\nИстория появится после того, как вы пройдёте обслуживание.", reply_markup=get_main_menu())
        return
    texts = await history_messages(history)
    refresh = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data="car_history")]])
    for i, text in enumerate(texts):
        await message.answer(text, parse_mode="HTML", reply_markup=refresh if i == len(texts) - 1 else None)


async def wipe_telegraph_pages():
    """Стереть страницы истории, опубликованные раньше на telegra.ph (см. TELEGRAPH выше)"""
    try:
        for page in await db.get_telegraph_pages():
            if await telegraph_edit_page(page['access_token'], page['page_path'], "Страница удалена",
                                         [{"tag": "p", "children": ["Страница удалена."]}]):
                await db.delete_telegraph_page(page['id'])
                logger.info(f"Стёрта страница Telegraph: {page['page_path']}")
            else:
                logger.warning(f"Не удалось стереть страницу Telegraph {page['page_path']}, попробую при следующем запуске")
    except Exception as ex:
        logger.error(f"Ошибка при стирании страниц Telegraph: {ex}")


async def analyze_car_maintenance(car_id: int, current_mileage: int) -> list:
    """Анализ состояния авто на основе пробега и истории работ"""
    keywords = await db.get_keywords_with_intervals()
    if not keywords:
        return []

    works = await db.get_car_works_for_analysis(car_id)
    results = []

    # Находим ПЕРВОЕ посещение (минимальный пробег) — для тех работ что никогда не делались
    first_visit_mileage = None
    first_visit_date = None
    for work in works:
        mileage = work.get('work_mileage')
        if mileage is not None:
            try:
                m = int(mileage)
                if first_visit_mileage is None or m < first_visit_mileage:
                    first_visit_mileage = m
                    first_visit_date = work.get('work_date')
            except:
                pass

    for kw in keywords:
        keyword = kw['keyword'].lower()
        interval_min = kw['interval_km_min']
        interval_max = kw['interval_km_max']

        # Ищем последнюю работу с этим ключевым словом
        last_work = None
        last_mileage = None
        never_done = False  # Флаг: никогда не делалось

        for work in works:
            description = (work['description'] or '').lower()
            if keyword in description:
                last_work = work
                mileage = work.get('work_mileage')
                if mileage is not None:
                    try:
                        last_mileage = int(mileage)
                    except:
                        last_mileage = None
                break

        # Если НЕТ записи с этим keyword — считаем от первого посещения
        if last_mileage is None and first_visit_mileage is not None:
            last_mileage = first_visit_mileage
            last_work = {'work_date': first_visit_date}
            never_done = True  # Помечаем что никогда не делалось

        if last_mileage is not None:
            km_since = current_mileage - last_mileage
            km_until_max = interval_max - km_since
            overdue_km = km_since - interval_max if km_since > interval_max else 0

            if km_since < interval_min:
                status = 'ok'
            elif km_since <= interval_max:
                status = 'soon'
            else:
                status = 'overdue'

            results.append({
                'name': kw['keyword'],
                'status': status,
                'last_mileage': last_mileage,
                'last_date': last_work.get('work_date') if last_work else None,
                'km_since': km_since,
                'km_until': km_until_max,
                'overdue_km': overdue_km,
                'interval_min': interval_min,
                'interval_max': interval_max,
                'never_done': never_done  # Никогда не менялось
            })

    # Сортируем: сначала overdue, потом soon, потом ok
    # Внутри категории: сначала never_done, потом по величине просрочки
    def sort_key(x):
        status_order = {'overdue': 0, 'soon': 1, 'ok': 2}
        never = 0 if x.get('never_done') else 1
        overdue = -(x.get('overdue_km') or 0)
        return (status_order.get(x['status'], 3), never, overdue)

    results.sort(key=sort_key)

    return results


def format_maintenance_report(car_info: dict, current_mileage: int, results: list) -> str:
    """Форматирование отчёта о состоянии авто"""
    car_display = f"{car_info.get('car_brand', '')} {car_info.get('car_model', '')} ({car_info.get('car_number', '')})".strip()

    text = f"🚗 <b>СОСТОЯНИЕ АВТО</b>\n"
    text += f"{car_display}\n"
    text += f"Текущий пробег: {current_mileage:,} км\n".replace(',', ' ')
    text += "\n━━━━━━━━━━━━━━━━━━━━\n"

    # Группируем по статусу
    # "Обратить внимание" - ВСЕ что никогда не менялось (независимо от пробега)
    attention = [r for r in results if r.get('never_done')]
    # Остальные категории - только реально замененные
    overdue = [r for r in results if r['status'] == 'overdue' and not r.get('never_done')]
    soon = [r for r in results if r['status'] == 'soon' and not r.get('never_done')]
    ok = [r for r in results if r['status'] == 'ok' and not r.get('never_done')]

    if overdue:
        text += "\n🔴 <b>КРИТИЧНО - ЗАМЕНА ПРОСРОЧЕНА:</b>\n\n"
        for item in overdue:
            interval_min = item.get('interval_min', 0)
            interval_max = item.get('interval_max', 0)
            text += f"⛔ {item['name']}\n"
            text += f"   Последняя замена: {item['last_mileage']:,} км".replace(',', ' ')
            if item['last_date']:
                text += f" ({item['last_date'].strftime('%d.%m.%Y')})"
            text += "\n"
            text += f"   Рекомендуемый интервал замены: {interval_min:,} - {interval_max:,} км\n".replace(',', ' ')
            text += f"   Пройдено: {item['km_since']:,} км\n".replace(',', ' ')
            text += f"   ❗ Просрочено на {item['overdue_km']:,} км!\n\n".replace(',', ' ')

    if soon:
        text += "\n🟡 <b>ПОРА МЕНЯТЬ:</b>\n\n"
        for item in soon:
            interval_min = item.get('interval_min', 0)
            interval_max = item.get('interval_max', 0)
            text += f"⚠️ {item['name']}\n"
            text += f"   Последняя замена: {item['last_mileage']:,} км\n".replace(',', ' ')
            text += f"   Рекомендуемый интервал замены: {interval_min:,} - {interval_max:,} км\n".replace(',', ' ')
            text += f"   Пройдено: {item['km_since']:,} км\n".replace(',', ' ')
            if item['km_until'] > 0:
                text += f"   До критичного: ~{item['km_until']:,} км\n\n".replace(',', ' ')
            else:
                text += "\n"

    if attention:
        text += "\n🟠 <b>ОБРАТИТЬ ВНИМАНИЕ:</b>\n\n"
        for item in attention:
            km_ago = item['km_since'] if item['km_since'] else 0
            interval_min = item.get('interval_min', 0)
            interval_max = item.get('interval_max', 0)
            text += f"❓ {item['name']}\n"
            text += f"   Нет данных о замене\n"
            text += f"   С первого посещения вы проехали: {km_ago:,} км\n".replace(',', ' ')
            text += f"   Рекомендуемый интервал замены: {interval_min:,} - {interval_max:,} км\n\n".replace(',', ' ')

    if ok:
        text += "\n🟢 <b>В НОРМЕ:</b>\n\n"
        for item in ok:
            km_ago = item['km_since'] if item['km_since'] else 0
            text += f"✅ {item['name']} ({km_ago:,} км назад)\n".replace(',', ' ')

    if not results:
        text += "\n⚠️ Нет данных для анализа.\n"
        text += "Добавьте интервалы ТО в настройках.\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━\n"

    return text


# ==================== HANDLERS ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"🚗 Добро пожаловать в автосервис!\n\n⏰ Режим работы: 10:00 - 20:00\n📅 Запись каждые 2 часа.\n\nИспользуйте кнопки внизу экрана для навигации.",
        reply_markup=get_persistent_menu()
    )
    await message.answer("Выберите действие:", reply_markup=get_main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Выберите действие:", reply_markup=get_main_menu())


@router.message(F.text == "📋 Меню")
async def btn_menu(message: Message):
    await message.answer("Выберите действие:", reply_markup=get_main_menu())


@router.message(F.text == "📝 Мои записи")
async def btn_my_bookings(message: Message):
    if not await require_verified(message):
        return
    bookings = await db.get_user_bookings(message.from_user.id)
    if not bookings:
        await message.answer("У вас нет активных записей.", reply_markup=get_main_menu())
    else:
        text = "📝 Ваши записи:\n\n"
        for b in bookings:
            date_display = b["booking_date"].strftime("%d.%m.%Y")
            text += f"• {date_display} в {b['booking_time']}\n"
        await message.answer(text, reply_markup=get_main_menu())


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выберите действие:", reply_markup=get_main_menu())
    await callback.answer()


@router.callback_query(F.data == "book")
async def start_booking(callback: CallbackQuery, state: FSMContext):
    # Проверяем лимит активных записей
    active_count = await db.count_user_active_bookings(callback.from_user.id)
    if active_count >= MAX_BOOKINGS_PER_USER:
        try:
            await callback.message.edit_text(
                f"⚠️ У вас уже есть {MAX_BOOKINGS_PER_USER} активных записей.\n\nДождитесь выполнения или отмените одну из них.",
                reply_markup=get_main_menu()
            )
        except TelegramBadRequest:
            pass
        await callback.answer("У вас максимум записей", show_alert=True)
        return

    await state.set_state(BookingStates.waiting_for_date)
    await callback.message.edit_text("Выберите дату записи:", reply_markup=get_date_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("date_"))
async def select_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.replace("date_", "")
    await state.update_data(booking_date=date_str)
    await state.set_state(BookingStates.waiting_for_time)
    keyboard = await get_time_keyboard(date_str)
    date_display = datetime.fromisoformat(date_str).strftime("%d.%m.%Y")
    await callback.message.edit_text(f"Дата: {date_display}\n\nВыберите время:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "slot_busy")
async def slot_busy(callback: CallbackQuery):
    await callback.answer("Это время уже занято!", show_alert=True)


async def ask_contact_for_booking(callback: CallbackQuery, state: FSMContext, date_str: str, time_str: str):
    await state.update_data(booking_date=date_str, booking_time=time_str, bot_message_id=callback.message.message_id)
    await state.set_state(BookingStates.waiting_for_phone)
    date_display = datetime.fromisoformat(date_str).strftime("%d.%m.%Y")
    await callback.message.edit_text(f"📅 Дата: {date_display}\n🕐 Время: {time_str}")
    await ask_contact(callback.message, "📱 Для записи подтвердите номер телефона — нажмите кнопку «📱 Поделиться номером» внизу экрана.")


@router.callback_query(F.data.startswith("usephone_"))
async def use_saved_phone(callback: CallbackQuery, state: FSMContext):
    # usephone_<дата>_<время>; в старых кнопках ещё и номер: usephone_<номер>_<дата>_<время> - номер из кнопки
    # не берём (данные кнопки можно подделать), только подтверждённый номер из базы
    parts = callback.data.split("_")
    date_str, time_str = parts[-2], parts[-1]
    phone = await db.get_user_phone(callback.from_user.id)
    if not phone:
        await ask_contact_for_booking(callback, state, date_str, time_str)
        await callback.answer()
        return
    booking_date = dt_date.fromisoformat(date_str)
    booking_time = time_str
    if not await db.is_slot_available(booking_date, booking_time):
        await callback.message.edit_text("К сожалению, это время уже занято.\nПожалуйста, выберите другое время.", reply_markup=get_main_menu())
        await callback.answer()
        return
    await show_car_selection_or_create_booking(callback, state, user_id=callback.from_user.id, username=callback.from_user.username or "",
                                                full_name=callback.from_user.full_name, phone=phone, booking_date=booking_date,
                                                booking_time=booking_time, is_callback=True)
    await callback.answer()


@router.callback_query(F.data.startswith("enter_new_phone_"))
async def enter_new_phone(callback: CallbackQuery, state: FSMContext):
    """Кнопка «Ввести другой номер» из старых сообщений: номер теперь только подтверждённый"""
    parts = callback.data.split("_")
    await ask_contact_for_booking(callback, state, parts[3], parts[4])
    await callback.answer()


@router.callback_query(F.data.startswith("time_"))
async def select_time(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    date_str = parts[1]
    time_str = parts[2]
    await state.update_data(booking_time=time_str)
    date_display = datetime.fromisoformat(date_str).strftime("%d.%m.%Y")
    phone = await db.get_user_phone(callback.from_user.id)
    if phone:
        formatted = f"+7 ({phone[2:5]}) {phone[5:8]}-{phone[8:10]}-{phone[10:12]}" if re.fullmatch(r'\+7\d{10}', phone) else phone
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📱 {formatted}", callback_data=f"usephone_{date_str}_{time_str}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"date_{date_str}")]
        ])
        await callback.message.edit_text(f"📅 Дата: {date_display}\n🕐 Время: {time_str}\n\n📱 Записать на этот номер?", reply_markup=keyboard)
    else:
        await ask_contact_for_booking(callback, state, date_str, time_str)
    await callback.answer()


@router.message(BookingStates.waiting_for_phone, F.contact)
async def process_phone(message: Message, state: FSMContext):
    phone = await verified_contact_phone(message)
    if not phone:
        return
    await db.link_verified_phone(message.from_user.id, phone, message.from_user.full_name, message.from_user.username)
    data = await state.get_data()
    booking_date = dt_date.fromisoformat(data["booking_date"])
    booking_time = data["booking_time"]
    bot_message_id = data.get("bot_message_id")
    try:
        if bot_message_id:
            await message.bot.delete_message(message.chat.id, bot_message_id)
    except:
        pass
    await message.answer("✅ Номер подтверждён", reply_markup=get_persistent_menu())
    if not await db.is_slot_available(booking_date, booking_time):
        await message.answer("❌ К сожалению, это время уже занято.\nПожалуйста, выберите другое время.", reply_markup=get_main_menu())
        await state.clear()
        return
    await show_car_selection_or_create_booking(message, state, user_id=message.from_user.id, username=message.from_user.username or "",
                                                full_name=message.from_user.full_name, phone=phone, booking_date=booking_date,
                                                booking_time=booking_time, is_callback=False)


@router.message(BookingStates.waiting_for_phone)
async def process_phone_text(message: Message):
    await message.answer("Номер не нужно вводить — нажмите кнопку «📱 Поделиться номером» внизу экрана.", reply_markup=get_contact_keyboard())


@router.message(F.contact)
async def process_contact(message: Message):
    """Номер подтверждают не только при записи - например, перед просмотром истории авто"""
    phone = await verified_contact_phone(message)
    if not phone:
        return
    await db.link_verified_phone(message.from_user.id, phone, message.from_user.full_name, message.from_user.username)
    await message.answer("✅ Номер подтверждён. Теперь вам доступны история авто и ваши записи.", reply_markup=get_persistent_menu())
    await message.answer("Выберите действие:", reply_markup=get_main_menu())


@router.callback_query(F.data == "my_bookings")
async def show_my_bookings(callback: CallbackQuery):
    if not await require_verified(callback):
        return await callback.answer()
    bookings = await db.get_user_bookings(callback.from_user.id)
    if not bookings:
        await callback.message.edit_text("У вас нет активных записей.", reply_markup=get_main_menu())
    else:
        text = "Ваши записи:\n\n"
        for b in bookings:
            date_display = b["booking_date"].strftime("%d.%m.%Y")
            text += f"- {date_display} в {b['booking_time']}\n"
        await callback.message.edit_text(text, reply_markup=get_main_menu())
    await callback.answer()


@router.callback_query(F.data == "cancel_booking")
async def show_cancel_options(callback: CallbackQuery):
    if not await require_verified(callback):
        return await callback.answer()
    bookings = await db.get_user_bookings(callback.from_user.id)
    if not bookings:
        await callback.message.edit_text("У вас нет записей для отмены.", reply_markup=get_main_menu())
    else:
        buttons = []
        for b in bookings:
            date_display = b["booking_date"].strftime("%d.%m.%Y")
            buttons.append([InlineKeyboardButton(text=f"{date_display} в {b['booking_time']}", callback_data=f"cancel_{b['id']}")])
        buttons.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите запись для отмены:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_"))
async def cancel_selected_booking(callback: CallbackQuery):
    booking_id = int(callback.data.replace("cancel_", ""))
    success = await db.cancel_booking(booking_id, callback.from_user.id)
    if success:
        await callback.message.edit_text("Запись успешно отменена!", reply_markup=get_main_menu())
    else:
        await callback.message.edit_text("Не удалось отменить запись.", reply_markup=get_main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("selectcar_"))
async def select_car(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    phone = data.get("phone")
    booking_date_str = data.get("booking_date")
    booking_time = data.get("booking_time")
    cars_list = data.get("cars_list", [])
    client_id = data.get("client_id") or await db.get_verified_client_id(callback.from_user.id)
    if not client_id or not booking_date_str:
        await state.clear()
        await callback.message.edit_text("Запись прервалась — начните, пожалуйста, заново.", reply_markup=get_main_menu())
        await callback.answer()
        return
    booking_date = dt_date.fromisoformat(booking_date_str)
    car_info = None
    car_id = None
    choice = callback.data.replace("selectcar_", "")
    if choice != "skip" and choice.isdigit():
        idx = int(choice)
        if 0 <= idx < len(cars_list):
            car_info = cars_list[idx]
            parts = car_info.strip().split()
            if len(parts) >= 3:
                car_number = parts[-1]
                car_model = parts[-2]
                car_brand = ' '.join(parts[:-2])
                car_id = await db.get_or_create_car(client_id, car_brand, car_model, car_number)
    if not await db.is_slot_available(booking_date, booking_time):
        await callback.message.edit_text("❌ К сожалению, это время уже занято.\nПожалуйста, выберите другое время.", reply_markup=get_main_menu())
        await state.clear()
        await callback.answer()
        return
    success = await db.create_booking(booking_date=booking_date, booking_time=booking_time, client_id=client_id, car_id=car_id)
    await state.clear()
    if success:
        date_display = booking_date.strftime("%d.%m.%Y")
        text = f"✅ <b>Вы успешно записаны!</b>\n\n📅 Дата: {date_display}\n🕐 Время: {booking_time}\n📱 Телефон: {phone}"
        if car_info:
            text += f"\n🚗 Авто: {car_info}"
        text += f"\n\n{COMPANY_INFO}\n\nЖдём вас!"
        await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="HTML")
    else:
        await callback.message.edit_text("❌ Произошла ошибка при записи.\nПопробуйте ещё раз.", reply_markup=get_main_menu())
    await callback.answer()


@router.callback_query(F.data == "car_history")
async def show_car_history(callback: CallbackQuery):
    await callback.answer()
    if await require_verified(callback):
        await send_car_history(callback.message, callback.from_user.id)


@router.message(F.text == "🚗 История авто")
async def btn_car_history(message: Message):
    if await require_verified(message):
        await send_car_history(message, message.from_user.id)


# ==================== ПРОВЕРКА СОСТОЯНИЯ АВТО ====================

@router.callback_query(F.data == "check_car")
async def start_car_check(callback: CallbackQuery, state: FSMContext):
    """Начало проверки состояния авто"""
    if not await require_verified(callback):
        return await callback.answer()
    cars = await db.get_client_cars_with_id(callback.from_user.id)

    if not cars:
        await callback.message.edit_text(
            "🔍 У вас нет зарегистрированных автомобилей.\n\n"
            "Автомобили появятся после того, как вы пройдёте обслуживание.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return

    if len(cars) == 1:
        # Одна машина - сразу запрашиваем пробег
        car = cars[0]
        await state.update_data(car_id=car['id'])
        await state.set_state(CarCheckStates.entering_mileage)

        car_display = f"{car['car_brand']} {car['car_model']} ({car['car_number']})"
        current_mileage = car.get('mileage') or 'не указан'

        await callback.message.edit_text(
            f"🚗 <b>{car_display}</b>\n\n"
            f"Последний известный пробег: {current_mileage}\n\n"
            f"📝 Введите текущий пробег (только число в км):",
            parse_mode="HTML"
        )
    else:
        # Несколько машин - показываем выбор
        await state.set_state(CarCheckStates.selecting_car)
        buttons = []
        for car in cars:
            car_display = f"{car['car_brand']} {car['car_model']} ({car['car_number']})"
            buttons.append([InlineKeyboardButton(text=f"🚗 {car_display}", callback_data=f"checkcar_{car['id']}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text("🔍 Выберите автомобиль для проверки:", reply_markup=keyboard)

    await callback.answer()


@router.callback_query(F.data.startswith("checkcar_"), CarCheckStates.selecting_car)
async def select_car_for_check(callback: CallbackQuery, state: FSMContext):
    """Выбор авто для проверки"""
    car_id = int(callback.data.replace("checkcar_", ""))
    car = await db.get_car_by_id_full(car_id)
    client_id = await db.get_verified_client_id(callback.from_user.id)

    # номер машины приходит из данных кнопки, а их можно подделать - проверяем, что машина этого клиента
    if not car or not client_id or car['client_id'] != client_id:
        await callback.message.edit_text("❌ Автомобиль не найден.", reply_markup=get_main_menu())
        await state.clear()
        await callback.answer()
        return

    await state.update_data(car_id=car_id)
    await state.set_state(CarCheckStates.entering_mileage)

    car_display = f"{car['car_brand']} {car['car_model']} ({car['car_number']})"
    current_mileage = car.get('mileage') or 'не указан'

    await callback.message.edit_text(
        f"🚗 <b>{car_display}</b>\n\n"
        f"Последний известный пробег: {current_mileage}\n\n"
        f"📝 Введите текущий пробег (только число в км):",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(CarCheckStates.entering_mileage)
async def process_mileage_input(message: Message, state: FSMContext):
    """Обработка ввода пробега"""
    # Извлекаем число из текста
    mileage_text = re.sub(r'\D', '', message.text)

    if not mileage_text:
        await message.answer("❌ Введите число!\n\nПример: 57000")
        return

    mileage = int(mileage_text)

    if mileage < 0 or mileage > 999999:
        await message.answer("❌ Некорректный пробег!\n\nВведите число от 0 до 999 999 км.")
        return

    data = await state.get_data()
    car_id = data.get('car_id')

    if not car_id:
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=get_main_menu())
        await state.clear()
        return

    # Обновляем пробег в БД
    await db.update_car_mileage(car_id, mileage)

    # Получаем информацию об авто
    car = await db.get_car_by_id_full(car_id)

    # Анализируем состояние
    loading_msg = await message.answer("⏳ Анализирую состояние авто...")

    results = await analyze_car_maintenance(car_id, mileage)

    await loading_msg.delete()

    if not results:
        await message.answer(
            "⚠️ <b>Нет данных для анализа</b>\n\n"
            "Для работы этой функции нужно:\n"
            "1. Добавить интервалы ТО в настройках\n"
            "2. Иметь историю обслуживания с указанием пробега\n\n"
            "Обратитесь к администратору для настройки.",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )
        await state.clear()
        return

    # Формируем отчёт
    report = format_maintenance_report(car, mileage, results)

    # Кнопки под отчётом
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться на ТО", callback_data="book")],
        [InlineKeyboardButton(text="🔄 Проверить снова", callback_data="check_car")],
        [InlineKeyboardButton(text="📋 Главное меню", callback_data="back_to_menu")]
    ])

    await message.answer(report, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()


# ==================== ПОДПИСКА ====================

@router.callback_query(F.data == "subscription")
async def show_subscription(callback: CallbackQuery):
    """Показать статус подписки или список тарифов"""
    client = await db.get_client_by_telegram_id(callback.from_user.id)
    if client:
        sub = await db.get_active_subscription(client['id'])
    else:
        sub = None

    if sub:
        plan_info = SUBSCRIPTION_PLANS.get(sub['plan'], {})
        plan_name = plan_info.get('name', sub['plan'])
        started = sub['started_at'].strftime('%d.%m.%Y') if sub.get('started_at') else '—'
        expires = sub['expires_at'].strftime('%d.%m.%Y') if sub.get('expires_at') else '—'
        features_text = '\n'.join(f'• {f}' for f in plan_info.get('features', []))
        text = (
            f"⭐ <b>Ваша подписка: {plan_name}</b>\n\n"
            f"📅 Действует с: {started}\n"
            f"📅 Действует до: {expires}\n\n"
            f"<b>Что входит:</b>\n{features_text}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        text = (
            "⭐ <b>Подписка</b>\n\n"
            "У вас нет активной подписки.\n\n"
            "Подписка действует <b>1 год</b> с момента оплаты.\n"
            "Выберите тариф:"
        )
        await callback.message.edit_text(text, reply_markup=get_plans_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub_plan_"))
async def show_plan_details(callback: CallbackQuery):
    """Показать детали выбранного тарифа"""
    plan_key = callback.data.replace("sub_plan_", "")
    plan = SUBSCRIPTION_PLANS.get(plan_key)
    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    price_str = f"{int(plan['price']):,}".replace(',', ' ')
    features_text = '\n'.join(f'✅ {f}' for f in plan['features'])
    text = (
        f"{plan['name']} — <b>{price_str} ₽/год</b>\n\n"
        f"{features_text}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить подписку", callback_data=f"sub_buy_{plan_key}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub_buy_"))
async def buy_subscription(callback: CallbackQuery):
    """Создать платёж в ЮKassa и отправить ссылку"""
    if not YOKASSA_AVAILABLE:
        await callback.answer("Оплата временно недоступна. Обратитесь в сервис.", show_alert=True)
        return
    if not YOKASSA_SHOP_ID or not YOKASSA_SECRET_KEY:
        await callback.answer("Оплата не настроена. Обратитесь в сервис.", show_alert=True)
        return

    plan_key = callback.data.replace("sub_buy_", "")
    plan = SUBSCRIPTION_PLANS.get(plan_key)
    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    client_id = await require_verified(callback)
    if not client_id:
        await callback.answer()
        return

    # Проверяем: нет ли уже активной подписки
    sub = await db.get_active_subscription(client_id)
    if sub:
        await callback.answer("У вас уже есть активная подписка!", show_alert=True)
        return

    # Отменяем старые незавершённые попытки оплаты
    await db.cancel_pending_subscriptions(client_id)

    idempotency_key = str(uuid4())
    price = plan['price']
    plan_name = plan['name']
    return_url = WEBHOOK_BASE_URL.rstrip('/') + "/payment-success" if WEBHOOK_BASE_URL else "https://t.me/"

    try:
        payment = await asyncio.to_thread(
            lambda: YKPayment.create({
                "amount": {"value": f"{price:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": return_url},
                "capture": True,
                "description": f"Подписка {plan_name} на 1 год — {COMPANY_NAME}",
                "metadata": {
                    "telegram_user_id": str(callback.from_user.id),
                    "plan": plan_key
                }
            }, idempotency_key)
        )

        payment_id = payment.id
        confirmation_url = payment.confirmation.confirmation_url

        await db.create_pending_subscription(client_id, plan_key, payment_id, price)

        price_str = f"{int(price):,}".replace(',', ' ')
        await callback.message.edit_text(
            f"💳 <b>{plan_name} — {price_str} ₽/год</b>\n\n"
            f"Нажмите кнопку ниже — откроется страница оплаты.\n"
            f"Подписка активируется автоматически после оплаты.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=confirmation_url)],
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка создания платежа ЮKassa: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при создании платежа.\nПожалуйста, попробуйте позже.",
            reply_markup=get_main_menu()
        )


# ==================== WEBHOOK ЮKASSA ====================

_webhook_runner = None


async def handle_yokassa_webhook(request):
    """Обработчик webhook от ЮKassa"""
    # Проверяем IP
    client_ip = request.headers.get('X-Forwarded-For', request.remote or '').split(',')[0].strip()
    if not is_yokassa_ip(client_ip):
        logger.warning(f"Webhook отклонён — неизвестный IP: {client_ip}")
        return aiohttp.web.Response(status=403)

    try:
        data = await request.json()
    except Exception:
        return aiohttp.web.Response(status=400)

    event = data.get('event', '')
    obj = data.get('object', {})
    payment_id = obj.get('id', '')

    logger.info(f"Webhook ЮKassa: event={event}, payment_id={payment_id}")

    if event == 'payment.succeeded' and payment_id:
        sub = await db.get_subscription_by_payment_id(payment_id)
        if sub and sub['status'] == 'pending':
            activated = await db.activate_subscription(payment_id)
            if not activated:
                logger.info(f"Подписка уже активна или дубль, payment_id={payment_id}")
                return aiohttp.web.Response(status=200)
            sub = await db.get_subscription_by_payment_id(payment_id)

            if sub and bot_instance:
                client = await db.get_client_by_id(sub['client_id'])
                plan_info = SUBSCRIPTION_PLANS.get(sub['plan'], {})
                plan_name = plan_info.get('name', sub['plan'])
                expires = sub['expires_at'].strftime('%d.%m.%Y') if sub.get('expires_at') else '—'

                # Уведомление клиенту
                if client and client.get('telegram_user_id'):
                    try:
                        await bot_instance.send_message(
                            chat_id=client['telegram_user_id'],
                            text=(
                                f"✅ <b>Подписка активирована!</b>\n\n"
                                f"Тариф: {plan_name}\n"
                                f"Действует до: {expires}\n\n"
                                f"Спасибо за доверие к нашему автосервису! 🚗"
                            ),
                            parse_mode="HTML"
                        )
                        logger.info(f"Уведомление об активации подписки отправлено клиенту {client['telegram_user_id']}")
                    except Exception as e:
                        logger.error(f"Ошибка уведомления клиента: {e}")

                # Уведомление администратору
                if ADMIN_TELEGRAM_ID and client:
                    client_name = client.get('full_name') or client.get('tg_username') or f"ID {client.get('telegram_user_id', '?')}"
                    client_phone = client.get('phone') or '—'
                    amount = float(sub.get('amount') or 0)
                    amount_str = f"{amount:,.0f}".replace(',', ' ')
                    try:
                        await bot_instance.send_message(
                            chat_id=ADMIN_TELEGRAM_ID,
                            text=(
                                f"💳 <b>Новая подписка!</b>\n\n"
                                f"Клиент: {client_name}\n"
                                f"Телефон: {client_phone}\n"
                                f"Тариф: {plan_name}\n"
                                f"Сумма: {amount_str} ₽\n"
                                f"Действует до: {expires}\n"
                                f"ID платежа: {payment_id}"
                            ),
                            parse_mode="HTML"
                        )
                        logger.info(f"Уведомление об оплате отправлено администратору")
                    except Exception as e:
                        logger.error(f"Ошибка уведомления администратора: {e}")

    return aiohttp.web.Response(status=200)


async def start_webhook_server():
    """Запустить aiohttp сервер для приёма webhook от ЮKassa"""
    global _webhook_runner
    app = aiohttp.web.Application()
    app.router.add_post('/yokassa/webhook', handle_yokassa_webhook)
    _webhook_runner = aiohttp.web.AppRunner(app)
    await _webhook_runner.setup()
    site = aiohttp.web.TCPSite(_webhook_runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    logger.info(f"Webhook сервер запущен на порту {WEBHOOK_PORT}")


# ==================== LOGGING ====================
# Путь к файлу логов
LOG_FILE = os.path.join(_base_path, 'logs', 'bot.log')

# Создаём папку logs если не существует
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Настройка логирования в файл и консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== SCHEDULER ====================

bot_instance: Bot = None
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def send_evening_reminders():
    try:
        bookings = await db.get_tomorrow_bookings_for_reminder()
        for booking in bookings:
            try:
                telegram_user_id = booking.get('telegram_user_id')
                if not telegram_user_id:
                    continue
                booking_date = booking.get('booking_date')
                booking_time = booking.get('booking_time')
                if hasattr(booking_date, 'strftime'):
                    date_str = booking_date.strftime('%d.%m')
                else:
                    date_str = str(booking_date)
                message = (f"🔔 <b>Напоминание о записи!</b>\n\n📅 Завтра, <b>{date_str}</b> в <b>{booking_time}</b>\n"
                           f"вы записаны в автосервис.\n\nЖдём вас!\n\n{COMPANY_INFO}")
                await bot_instance.send_message(chat_id=telegram_user_id, text=message, parse_mode="HTML")
                await db.mark_reminder_sent(booking['id'])
                logger.info(f"Вечернее напоминание отправлено: user_id={telegram_user_id}, booking_id={booking['id']}")
            except Exception as e:
                logger.error(f"Ошибка отправки вечернего напоминания booking_id={booking.get('id')}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в send_evening_reminders: {e}")


async def send_1h_reminders():
    try:
        bookings = await db.get_bookings_for_1h_reminder()
        for booking in bookings:
            try:
                telegram_user_id = booking.get('telegram_user_id')
                if not telegram_user_id:
                    continue
                booking_time = booking.get('booking_time')
                message = (f"⏰ <b>Напоминание!</b>\n\nВ <b>{booking_time}</b> вы записаны в автосервис.\n\n"
                           f"Ждём вас!\n\n{COMPANY_INFO}")
                await bot_instance.send_message(chat_id=telegram_user_id, text=message, parse_mode="HTML")
                await db.mark_reminder_1h_sent(booking['id'])
                logger.info(f"Напоминание за 1 час отправлено: user_id={telegram_user_id}, booking_id={booking['id']}")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания за 1 час booking_id={booking.get('id')}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в send_1h_reminders: {e}")


async def on_startup():
    await db.connect()
    await db.init_tables()
    logger.info("База данных подключена и таблицы созданы")
    asyncio.create_task(wipe_telegraph_pages())
    scheduler.add_job(send_evening_reminders, 'cron', hour=20, minute=0)
    scheduler.add_job(send_1h_reminders, 'cron', hour='9-20', minute='0,30')
    scheduler.start()
    logger.info("Планировщик напоминаний запущен")


async def on_shutdown():
    global _webhook_runner
    scheduler.shutdown()
    await db.close()
    if _webhook_runner:
        await _webhook_runner.cleanup()
    logger.info("Планировщик остановлен, соединение с БД закрыто")


# ==================== SYSTEM TRAY ====================
tray_icon = None
bot_loop = None
stop_event = threading.Event()


def create_tray_icon():
    """Создание иконки для системного трея"""
    # Создаём простую иконку 64x64 с изображением автомобиля
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Фон - круг
    draw.ellipse([2, 2, size-2, size-2], fill=(52, 152, 219))

    # Корпус автомобиля (упрощённый)
    draw.rectangle([12, 28, 52, 42], fill='white')  # основа
    draw.polygon([(18, 28), (26, 18), (42, 18), (48, 28)], fill='white')  # крыша

    # Колёса
    draw.ellipse([14, 38, 24, 48], fill=(44, 62, 80))
    draw.ellipse([40, 38, 50, 48], fill=(44, 62, 80))

    return image


def on_tray_logs(icon, item):
    """Открыть окно с логами в live режиме"""
    try:
        # Открываем PowerShell с Get-Content -Wait для live просмотра
        cmd = f'powershell -Command "Get-Content -Path \'{LOG_FILE}\' -Wait -Tail 100"'
        subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        logger.info("Открыто окно логов")
    except Exception as e:
        logger.error(f"Ошибка открытия логов: {e}")


def on_tray_exit(icon, item):
    """Обработчик выхода из трея"""
    global bot_loop, tray_icon
    logger.info("Завершение работы через системный трей...")
    stop_event.set()

    # Останавливаем бот
    if bot_loop and bot_loop.is_running():
        bot_loop.call_soon_threadsafe(bot_loop.stop)

    # Останавливаем иконку трея
    if icon:
        icon.stop()


def setup_tray():
    """Настройка системного трея"""
    global tray_icon

    icon_image = create_tray_icon()

    menu = pystray.Menu(
        pystray.MenuItem("Автосервис Бот", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Логи", on_tray_logs),
        pystray.MenuItem("Выход", on_tray_exit)
    )

    tray_icon = pystray.Icon(
        name="autoservice_bot",
        icon=icon_image,
        title="Автосервис - Telegram бот",
        menu=menu
    )

    return tray_icon


async def main():
    global bot_instance, bot_loop

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден! Проверьте файл .env")
        input("Нажмите Enter для выхода...")
        return

    bot_loop = asyncio.get_event_loop()
    bot_instance = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    logger.info("Бот запускается...")

    # Запускаем webhook сервер если настроены ЮKassa ключи
    if YOKASSA_SHOP_ID and YOKASSA_SECRET_KEY:
        try:
            await start_webhook_server()
        except Exception as e:
            logger.error(f"Не удалось запустить webhook сервер: {e}")
    else:
        logger.info("ЮKassa не настроена, webhook сервер не запущен")

    try:
        await dp.start_polling(bot_instance)
    except asyncio.CancelledError:
        logger.info("Polling отменён")
    finally:
        await on_shutdown()


def run_bot():
    """Запуск бота в отдельном потоке"""
    asyncio.run(main())


if __name__ == "__main__":
    try:
        # Создаём и запускаем системный трей
        icon = setup_tray()

        # Запускаем бота в отдельном потоке
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()

        logger.info("Приложение запущено в системном трее")

        # Запускаем трей (блокирующий вызов)
        icon.run()

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        input("Нажмите Enter для выхода...")