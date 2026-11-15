"""Хранение шин: сезоны, сроки и как узнать шины среди запчастей склада (для переноса во вкладку «Шины»).

Шины клиента на хранении - не запчасть: их не заказывают и не ставят в наряд, а принимают и через сезон
отдают. Раньше их записывали на склад запчастью (часто с «оплачено заранее»); перенести такие позиции
можно только с подтверждения - по названию шины угадываются не всегда.
"""
import re
from datetime import date, timedelta

SEASONS = ("summer", "winter", "all")          # летние / зимние / всесезонные (в базе - так)
STATUS_STORED, STATUS_ISSUED = "stored", "issued"
STATUS_OVERDUE = "overdue"                       # не хранится в базе: «на хранении» и срок прошёл
STATUS_SOON = "soon"                             # не хранится в базе: «на хранении», срок - в ближайшие SOON_DAYS
SOON_DAYS = 14
DEFAULT_QUANTITY = 4
DEFAULT_STORE_DAYS = 183                         # «хранить до» по умолчанию - полгода (до следующего сезона)

# Явно шины - в списке переноса отмечены сразу
_STRONG = re.compile(r"шин|резин|покрышк|хранени\w*\s+(колёс|колес)", re.IGNORECASE)
# Возможно шины («Колёса R16 зимние»), но и «колёсный цилиндр» - показываем без отметки
_WEAK = re.compile(r"колёс|колес", re.IGNORECASE)
# Точно не шины, хотя слово похоже
_NOT_TIRES = re.compile(r"колёсн\w*\s+(цилиндр|подшипник|болт|гайк|шпильк)|колесн\w*\s+(цилиндр|подшипник|болт|гайк|шпильк)"
                        r"|шиномонтаж|шина\s+(тормоз|давлен)", re.IGNORECASE)
_SIZE = re.compile(r"(\d{3})\s*/\s*(\d{2})\s*(Z?R)\s*(\d{2}(?:[.,]\d)?)\s*(C)?", re.IGNORECASE)


def tire_match(name):
    """Похоже ли название запчасти на шины: "strong" - да (отметить сразу), "weak" - возможно, None - нет"""
    text = str(name or "")
    if not text or _NOT_TIRES.search(text):
        return None
    if _STRONG.search(text):
        return "strong"
    if _WEAK.search(text):
        return "weak"
    return None


def guess_season(name):
    """Сезон по названию: "зимн..." - winter, "летн..." - summer, "всесезон..." - all, иначе None"""
    text = str(name or "").lower()
    if "всесезон" in text:
        return "all"
    if "зим" in text or "шипован" in text or "липучк" in text:
        return "winter"
    if "летн" in text or "лето" in text:
        return "summer"
    return None


def guess_size(name):
    """Размер по названию: "205/55 R16" (как пишут на боковине), иначе None"""
    match = _SIZE.search(str(name or ""))
    if not match:
        return None
    width, profile, r, rim, cargo = match.groups()
    return f"{width}/{profile} {r.upper()}{rim.replace(',', '.')}{(cargo or '').upper()}"


def guess_with_rims(name):
    """С дисками: «колёса», «на дисках», «в сборе»"""
    text = str(name or "").lower()
    return bool(re.search(r"диск|колёса|колеса|в сборе", text))


def default_store_until(received):
    return (received or date.today()) + timedelta(days=DEFAULT_STORE_DAYS)


def display_status(status, store_until, today=None):
    """Статус для показа: «на хранении» со сроком в прошлом - «срок истёк», срок в ближайшие 2 недели -
    «скоро срок» (пора звать клиента забирать)"""
    today = today or date.today()
    if status == STATUS_STORED and isinstance(store_until, date):
        if store_until < today:
            return STATUS_OVERDUE
        if (store_until - today).days <= SOON_DAYS:
            return STATUS_SOON
    return status
