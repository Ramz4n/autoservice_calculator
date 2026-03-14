# Конфигурация бота
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Загружаем настройки из settings.json (общий файл для всего проекта)
_settings_path = Path(__file__).parent.parent / "config" / "settings.json"
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("TOKEN:", os.getenv("BOT_TOKEN"))
# Настройки MariaDB (та же база, что и у основного приложения)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "alexauto")
}

# Настройки автосервиса (из settings.json)
WORKING_HOURS_START = _settings.get("working_hours_start", 10)
WORKING_HOURS_END = _settings.get("working_hours_end", 20)
SLOT_DURATION_MINUTES = _settings.get("slot_duration_minutes", 120)
MAX_BOOKINGS_PER_USER = _settings.get("max_bookings_per_user", 2)

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
