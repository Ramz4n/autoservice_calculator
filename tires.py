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


# ===== размер шин двумя полями: «ширина/профиль» (205/55) и «радиус» (R16) =====
# В базе - одной строкой, как пишут на боковине: «205/55 R16». В форме - два поля со списками;
# вписать своё тоже можно (31x10.5 R15, 225/45 ZR18, 195/75 R16C)

COMMON_WIDTH_PROFILES = (
    "155/70", "165/65", "165/70", "175/65", "175/70", "185/55", "185/60", "185/65", "185/70", "195/50", "195/55",
    "195/60", "195/65", "195/75", "205/50", "205/55", "205/60", "205/65", "205/70", "215/45", "215/50", "215/55",
    "215/60", "215/65", "215/70", "225/40", "225/45", "225/50", "225/55", "225/60", "225/65", "235/45", "235/50",
    "235/55", "235/60", "235/65", "245/40", "245/45", "245/70", "255/55", "265/65", "265/70", "275/40")
COMMON_RADII = ("R13", "R14", "R15", "R16", "R17", "R18", "R19", "R20", "R21", "R22", "R14C", "R15C", "R16C")

# Буквы, похожие на латинские (вписали в русской раскладке): Р16, 16С, 31х10,5
_LATIN = str.maketrans({"Р": "R", "р": "R", "С": "C", "с": "C", "З": "Z", "з": "Z", "х": "x", "Х": "x", "×": "x",
                        "X": "x"})
_RADIUS = re.compile(r"(Z?R)?(\d{2}(?:[.,]5)?)(C)?", re.IGNORECASE)
_METRIC = re.compile(r"(\d{3})\s*[/\\\-\s.]\s*(\d{2})")
_INCH = re.compile(r"(\d{2})\s*x\s*(\d{1,2}(?:[.,]\d{1,2})?)")
_FULL = re.compile(r"(?P<wp>\d{3}\s*[/\\\-\s.]\s*\d{2}|\d{2}\s*x\s*\d{1,2}(?:[.,]\d{1,2})?)\s*-?\s*"
                   r"(?P<r>(?:Z?R)?\s*\d{2}(?:[.,]5)?\s*C?)", re.IGNORECASE)


def normalize_width_profile(text):
    """«205 55», «205\\55», «205-55» → «205/55»; «31х10,5» → «31x10.5»; другое - как вписали (без лишних пробелов)"""
    original = " ".join(str(text or "").split())
    raw = original.translate(_LATIN)
    match = _METRIC.fullmatch(raw)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    match = _INCH.fullmatch(raw)
    if match:
        return f"{match.group(1)}x{match.group(2).replace(',', '.')}"
    return original   # не размер - как вписали (русские буквы не трогаем)


def normalize_radius(text):
    """«16», «r16», «R 16», «р16» → «R16»; «16c» → «R16C»; «zr18» → «ZR18»; «17,5» → «R17.5».
    Пусто - "". Не радиус - None"""
    raw = "".join(str(text or "").translate(_LATIN).split()).upper()
    if not raw:
        return ""
    match = _RADIUS.fullmatch(raw)
    if not match:
        return None
    prefix, rim, cargo = match.groups()
    return f"{prefix or 'R'}{rim.replace(',', '.')}{cargo or ''}"


def split_size(size):
    """Размер из базы → (ширина/профиль, радиус) для двух полей: «205/55 R16» → («205/55», «R16»),
    «R16» → ("", «R16»). Не разобрать - (весь размер, "")"""
    original = " ".join(str(size or "").split())
    raw = original.translate(_LATIN)
    match = _FULL.fullmatch(raw)
    if match and normalize_radius(match.group("r")):
        return normalize_width_profile(match.group("wp")), normalize_radius(match.group("r"))
    if raw and re.fullmatch(r"(?:Z?R)\s*\d{2}(?:[.,]5)?\s*C?", raw, re.IGNORECASE):
        return "", normalize_radius(raw)
    return original, ""   # не разобрать - как записано (русские буквы не трогаем)


def size_from_fields(width_profile, radius):
    """Размер для базы из двух полей. Весь размер вписали в первое поле («205 55 16», «205/55r16») - он
    разбирается сам (радиус из второго поля тогда не нужен). Возвращает строку («205/55 R16»; "" - пусто)
    или None - во втором поле не радиус"""
    whole_wp, whole_r = split_size(width_profile)
    if whole_r:
        return " ".join(x for x in (whole_wp, whole_r) if x)
    radius = normalize_radius(radius)
    if radius is None:
        return None
    return " ".join(x for x in (normalize_width_profile(width_profile), radius) if x)


def rim_of(size):
    """Посадочный диаметр для фишек: «205/55 R16», «225/45 ZR18», «195/75 R16C» → «R16», «R18», «R16»; нет - None"""
    _, radius = split_size(size)
    match = _RADIUS.fullmatch(radius) if radius else None
    return f"R{match.group(2)}" if match else None


def rim_sort_key(rim):
    """R13 < R16 < R17.5 < R22 - фишки по порядку"""
    try:
        return float(str(rim)[1:])
    except ValueError:
        return 999.0


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
