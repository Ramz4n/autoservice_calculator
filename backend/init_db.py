"""
Скрипт инициализации БД.
Создаёт все таблицы из db_schema.py (существующие таблицы),
а затем через SQLAlchemy — clients_login и payment_history.

Запуск: python init_db.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymysql
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "autoservice")

# Таблицы из db_schema.py
from db_schema import TABLES, INDEXES, MIGRATIONS  # noqa: E402

def init():
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
    )
    cur = conn.cursor()

    print("Создание основных таблиц из db_schema.py...")
    for name, sql in TABLES.items():
        try:
            cur.execute(sql)
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  SKIP {name}: {e}")

    print("Создание индексов...")
    for sql in INDEXES:
        try:
            cur.execute(sql)
        except Exception:
            pass  # уже существуют

    print("Применение миграций...")
    for sql in MIGRATIONS:
        try:
            cur.execute(sql)
        except Exception:
            pass

    conn.commit()
    cur.close()
    conn.close()

    print("\nСоздание clients_login и payment_history через SQLAlchemy...")
    # Теперь через SQLAlchemy (только новые таблицы)
    from app.database import Base, engine
    from app.models import Client, ClientLogin, Subscription, PaymentHistory  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("  OK: clients_login, payment_history")

    print("\nБД инициализирована успешно.")


if __name__ == "__main__":
    init()
