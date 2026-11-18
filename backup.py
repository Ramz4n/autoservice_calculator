# -*- coding: utf-8 -*-
"""
Резервное копирование и восстановление данных приложения.

Бэкап -- один .zip с тремя файлами:
  - db.json          -- содержимое всех таблиц БД
  - settings.json     -- настройки приложения (% мастера и т.д.)
  - spare_parts.txt   -- список запчастей для автодополнения

license.key/license_cache.json/config/.env НЕ входят в бэкап -- они
привязаны к конкретному компьютеру/лицензии, восстанавливать их на другой
машине бессмысленно, а в .env к тому же лежат боевые секреты (пароль БД,
токен бота).

Дамп/восстановление -- чистым Python через pymysql (соединение берётся у
уже существующего объекта Database), без внешнего mysqldump.exe -- иначе
пришлось бы либо искать бинарник на диске клиента, либо тащить его отдельно
в PyInstaller-сборку.

Формат восстановления: TRUNCATE + INSERT всех таблиц с отключенными
проверками внешних ключей (FOREIGN_KEY_CHECKS=0) -- порядок таблиц тогда
не важен, а AUTO_INCREMENT сам подстраивается под максимальный вставленный id.
"""

import os
import json
import zipfile
import glob
import hashlib
from datetime import datetime, date
from decimal import Decimal

import pymysql

from db_schema import TABLES

DB_DUMP_NAME = "db.json"
SETTINGS_NAME = "settings.json"
SPARE_PARTS_NAME = "spare_parts.txt"

# Ежедневные копии (и ручные «Сделать копию сейчас») - префикс прежний, старые копии клиента остаются в своём ряду.
# Почасовые и при закрытии программы - отдельный ряд со своим префиксом, чтобы при ротации они не вытесняли
# ежедневные (имя почасовой НЕ начинается с BACKUP_FILE_PREFIX, иначе glob ежедневных цеплял бы и их)
BACKUP_FILE_PREFIX = "autoservice_backup_"
HOURLY_FILE_PREFIX = "autoservice_hourly_"
DAILY_KEEP = 14
HOURLY_KEEP = 48


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Не удалось сериализовать значение типа {type(value)}")


def _dump_database(db) -> dict:
    """Считать все строки всех таблиц, объявленных в db_schema.TABLES."""
    conn = db.get_connection()
    try:
        dump = {}
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            for table_name in TABLES:
                cursor.execute(f"SELECT * FROM `{table_name}`")
                dump[table_name] = cursor.fetchall()
        return dump
    finally:
        conn.close()


def _restore_database(db, dump: dict) -> None:
    """Полностью заменить содержимое всех таблиц данными из dump."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cursor:
            # Колонки, которые реально есть в текущей схеме: в старых бэкапах могут
            # встречаться поля, удалённые из схемы (например keywords.priority)
            existing_columns = {}
            for table_name in TABLES:
                cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
                existing_columns[table_name] = {
                    (row["Field"] if isinstance(row, dict) else row[0])
                    for row in cursor.fetchall()
                }

            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            try:
                for table_name in TABLES:
                    cursor.execute(f"TRUNCATE TABLE `{table_name}`")

                for table_name, rows in dump.items():
                    if table_name not in TABLES or not rows:
                        continue
                    columns = [c for c in rows[0].keys() if c in existing_columns[table_name]]
                    if not columns:
                        continue
                    col_list = ", ".join(f"`{c}`" for c in columns)
                    placeholders = ", ".join(["%s"] * len(columns))
                    sql = f"INSERT INTO `{table_name}` ({col_list}) VALUES ({placeholders})"
                    values = [[row[c] for c in columns] for row in rows]
                    cursor.executemany(sql, values)
            finally:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dump_database_text(db) -> str:
    """Содержимое базы одним текстом (то, что ляжет в db.json)."""
    return json.dumps(_dump_database(db), ensure_ascii=False, default=_json_default)


def dump_hash(dump_text: str) -> str:
    """Отпечаток содержимого базы: одинаковый - данные не менялись, новая почасовая копия не нужна."""
    return hashlib.sha256(dump_text.encode("utf-8")).hexdigest()


def create_backup(db, backup_dir: str, settings_file: str, spare_parts_file: str,
                  prefix: str = BACKUP_FILE_PREFIX, dump_text: str = None) -> str:
    """
    Создать .zip-бэкап в backup_dir. Возвращает путь к созданному файлу.
    dump_text - уже считанная база (dump_database_text), чтобы не читать её второй раз.
    """
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    zip_path = os.path.join(backup_dir, f"{prefix}{timestamp}.zip")

    if dump_text is None:
        dump_text = dump_database_text(db)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(DB_DUMP_NAME, dump_text)

        if os.path.exists(settings_file):
            zf.write(settings_file, SETTINGS_NAME)
        if os.path.exists(spare_parts_file):
            zf.write(spare_parts_file, SPARE_PARTS_NAME)

    return zip_path


def restore_backup(db, zip_path: str, settings_file: str, spare_parts_file: str) -> None:
    """Восстановить БД и локальные файлы настроек из .zip-бэкапа.
    Если восстановление БД упало на середине (битая копия, ошибка вставки) - возвращаем данные, какие были:
    TRUNCATE в MariaDB/MySQL фиксируется сразу, откат транзакции его не отменяет, и без этого база осталась бы
    пустой или неполной. Настройки и запчасти тогда не трогаем"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        dump = json.loads(zf.read(DB_DUMP_NAME).decode("utf-8"))
        current = _dump_database(db)
        try:
            _restore_database(db, dump)
        except Exception:
            _restore_database(db, current)
            raise

        if SETTINGS_NAME in zf.namelist():
            os.makedirs(os.path.dirname(settings_file), exist_ok=True)
            with open(settings_file, "wb") as f:
                f.write(zf.read(SETTINGS_NAME))

        if SPARE_PARTS_NAME in zf.namelist():
            os.makedirs(os.path.dirname(spare_parts_file), exist_ok=True)
            with open(spare_parts_file, "wb") as f:
                f.write(zf.read(SPARE_PARTS_NAME))


def list_backups(backup_dir: str, prefixes=(BACKUP_FILE_PREFIX, HOURLY_FILE_PREFIX)) -> list:
    """Список файлов бэкапа в папке (по умолчанию всех рядов - ежедневные и почасовые), от новых к старым."""
    if not backup_dir or not os.path.isdir(backup_dir):
        return []
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    paths = []
    for prefix in prefixes:
        paths += glob.glob(os.path.join(backup_dir, f"{prefix}*.zip"))
    return sorted(paths, key=os.path.getmtime, reverse=True)


def rotate_backups(backup_dir: str, keep: int = DAILY_KEEP, prefix: str = BACKUP_FILE_PREFIX) -> None:
    """Оставить только keep самых свежих бэкапов ОДНОГО ряда (prefix), остальные удалить.
    Другой ряд не трогается: почасовые не вытесняют ежедневные и наоборот."""
    for old_path in list_backups(backup_dir, prefix)[keep:]:
        try:
            os.remove(old_path)
        except OSError:
            pass
