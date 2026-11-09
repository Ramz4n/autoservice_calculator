# -*- coding: utf-8 -*-
"""
Модуль проверки лицензии.
Логика:
  - Читает ключ из файла license.key рядом с exe
  - Загружает один общий JSON со всеми ключами через LICENSE_URL
  - Кэширует успешную проверку на GRACE_DAYS дней
  - Если сервер явно вернул active=false — блокирует сразу
  - Если сервер недоступен — даёт GRACE_DAYS дней офлайн-работы

Формат JSON на сервере:
{
  "licenses": {
    "ALEXAN-2025-AVTOSRV-001": {"active": true,  "name": "Автосервис Иванова"},
    "ALEXAN-2025-AVTOSRV-002": {"active": false, "name": "Автосервис Петрова"}
  }
}
"""

import os
import sys
import json
import hashlib
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv


def _base_dir() -> str:
    """Папка рядом с exe (или рядом со скриптом при разработке)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


load_dotenv(os.path.join(_base_dir(), "config", ".env"))

# ──────────────────────────────────────────────────
# НАСТРОЙКИ — секреты лежат в config/.env
LICENSE_URL = os.getenv("JSONBIN_URL", "")      # URL приватного bin
API_KEY     = os.getenv("JSONBIN_API_KEY", "")  # секретный ключ jsonbin.io
GRACE_DAYS  = 7  # сколько дней работает без интернета
# ──────────────────────────────────────────────────


def _key_path()   -> str: return os.path.join(_base_dir(), "license.key")
def _cache_path() -> str: return os.path.join(_base_dir(), "license_cache.json")


def _read_key() -> str | None:
    path = _key_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _save_cache(key: str) -> None:
    data = {
        "key_hash": hashlib.sha256(key.encode()).hexdigest(),
        "last_ok":  datetime.now().isoformat()
    }
    with open(_cache_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)


def _check_cache(key: str) -> bool:
    path = _cache_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("key_hash") != hashlib.sha256(key.encode()).hexdigest():
            return False
        last_ok = datetime.fromisoformat(data["last_ok"])
        return datetime.now() - last_ok <= timedelta(days=GRACE_DAYS)
    except Exception:
        return False


def _check_online(key: str) -> bool | None:
    """
    Загружает общий JSON со всеми лицензиями и ищет ключ клиента.
    Возвращает:
      True  — ключ найден и active=true
      False — ключ не найден или active=false
      None  — сервер недоступен или ответил ошибкой (работает офлайн-кэш)
    """
    try:
        r = requests.get(
            LICENSE_URL,
            headers={"X-Access-Key": API_KEY},
            timeout=5,
            proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            return None  # сбой jsonbin (5xx, 429, 401…) — не блокируем, даём GRACE_DAYS
        # jsonbin оборачивает данные в {"record": {...}, "metadata": {...}}
        body = r.json()
        data = body.get("record", body)
        licenses = data.get("licenses", {})
        entry = licenses.get(key)
        if entry is None:
            return False  # ключ вообще не найден
        return bool(entry.get("active", False))
    except Exception:
        return None  # нет связи


def check_license() -> tuple[bool, str]:
    """
    Основная проверка. Возвращает (ok: bool, message: str).
    Вызывай в main() перед запуском окна.
    """
    key = _read_key()

    if not key:
        return False, (
            "Файл лицензии не найден.\n\n"
            "Обратитесь к разработчику для получения ключа.\n"
            f"Ожидаемый путь: {_key_path()}"
        )

    if not (LICENSE_URL and API_KEY):
        # Нет настроек в config/.env — работаем по кэшу, пока не истечёт GRACE_DAYS
        if _check_cache(key):
            return True, ""
        return False, (
            "Не заданы настройки проверки лицензии.\n\n"
            "Добавьте JSONBIN_URL и JSONBIN_API_KEY в config/.env\n"
            "или обратитесь к разработчику."
        )

    online = _check_online(key)

    if online is True:
        _save_cache(key)
        return True, ""

    if online is False:
        return False, (
            "Лицензия заблокирована или не найдена.\n\n"
            "Для возобновления доступа свяжитесь с разработчиком."
        )

    # online is None — сервер недоступен, проверяем кэш
    if _check_cache(key):
        return True, ""

    return False, (
        "Не удалось проверить лицензию (сервер недоступен).\n\n"
        f"Офлайн-период истёк ({GRACE_DAYS} дн.).\n"
        "Подключитесь к интернету или обратитесь к разработчику."
    )
