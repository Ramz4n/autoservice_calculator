"""Правила ввода чисел - одни на все формы: деньги (цены, суммы), количество, процент.

Классы эквивалентности и границы описаны в tests/README.md («Классы эквивалентности»):
- деньги: больше 0 и не больше MONEY_MAX; запятая или точка; пробелы между разрядами ("1 500");
  копейки округляются до 2 знаков ("0,001" -> 0 -> неверно); nan / inf / буквы / пусто - неверно;
- количество: целое от 1 до QUANTITY_MAX; пусто - 1 (если разрешено);
- процент: от 0 до 100 включительно;
- время (своё время записи): ЧЧ:ММ, 00:00-23:59; разделитель - двоеточие, точка, тире или пробел;
  «9» и «9:» → 09:00, «930» → 09:30, «1130» → 11:30. Во время ввода - format_time_typing («:» дописывается сама).
"""
import math
import re

MONEY_MAX = 99_999_999.99      # одна цена / сумма - до ~100 млн (в базе DECIMAL(12,2), с запасом на итоги)
QUANTITY_MAX = 9999


def parse_money(text, allow_empty=False):
    """Цена / сумма из поля. Возвращает число (2 знака), None - если поле пустое и allow_empty.
    Неверное значение - ValueError"""
    raw = re.sub(r"\s", "", str(text or "")).replace(",", ".")
    if not raw:
        if allow_empty:
            return None
        raise ValueError("пусто")
    if not re.fullmatch(r"\d+(\.\d*)?|\.\d+", raw):   # без знака, букв, nan, inf, 1e5
        raise ValueError(raw)
    value = round(float(raw), 2)
    if not math.isfinite(value) or value <= 0 or value > MONEY_MAX:
        raise ValueError(raw)
    return value


def parse_quantity(text, allow_empty=True):
    """Количество из поля: целое 1..QUANTITY_MAX; пусто - 1 (allow_empty). Неверное - ValueError"""
    raw = re.sub(r"\s", "", str(text or ""))
    if not raw and allow_empty:
        return 1
    if not raw.isdigit():
        raise ValueError(raw)
    value = int(raw)
    if not 1 <= value <= QUANTITY_MAX:
        raise ValueError(raw)
    return value


DATE_MIN_YEAR, DATE_MAX_YEAR = 2000, 2100


def parse_date(text, allow_empty=False):
    """Дата из поля: дд.мм.гггг (или дд.мм.гг; разделитель - точка, / или -). Возвращает date,
    None - если поле пустое и allow_empty. Неверная дата (31.02, год вне 2000..2100, буквы) - ValueError"""
    from datetime import date
    raw = re.sub(r"\s", "", str(text or ""))
    if not raw:
        if allow_empty:
            return None
        raise ValueError("пусто")
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})", raw)
    if not match:
        raise ValueError(raw)
    day, month, year = (int(x) for x in match.groups())
    if len(match.group(3)) == 2:
        year += 2000
    if not DATE_MIN_YEAR <= year <= DATE_MAX_YEAR:
        raise ValueError(raw)
    return date(year, month, day)   # 31.02 - ValueError


def parse_time(text, allow_empty=True):
    """Время из поля → "ЧЧ:ММ". Пусто - "" (если allow_empty). Не время (25:00, 11:75, буквы) - ValueError"""
    raw = str(text or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise ValueError("пусто")
    match = (re.fullmatch(r"(\d{1,2})\s*[:.,\-\s]\s*(\d{2})", raw) or re.fullmatch(r"(\d{1,2})(\d{2})", raw)
             or re.fullmatch(r"(\d{1,2}):?()", raw))   # «11» и «11:» (двоеточие дописалось само) - 11:00
    if not match:
        raise ValueError(raw)
    hours, minutes = int(match.group(1)), int(match.group(2) or 0)
    if hours > 23 or minutes > 59:
        raise ValueError(raw)
    return f"{hours:02d}:{minutes:02d}"


def format_time_typing(text, grew=True):
    """Поле времени во время ввода: только цифры и одно двоеточие, не длиннее ЧЧ:ММ.
    «:» дописывается само: после двух цифр часа («11» → «11:»), а если час - одна цифра 3…9 - сразу («9» → «9:»);
    только когда текст вырос (стирают - не мешаем). Точка, запятая, тире, пробел - это «:»; второе «:» не ставится.
    «1130» (вставили) → «11:30»"""
    raw = re.sub(r"[.,\-\s]", ":", str(text or ""))
    raw = re.sub(r"[^\d:]", "", raw)
    if ":" in raw:
        hours, minutes = raw.split(":", 1)
        hours, minutes = hours[:2], minutes.replace(":", "")[:2]
        if not hours:
            return minutes[:2]   # «:30» - двоеточие без часа не нужно
        return f"{hours}:{minutes}"
    digits = raw
    if digits and digits[0] in "3456789":                # час из одной цифры: 9 → 9:, 930 → 9:30
        if len(digits) == 1:
            return digits + ":" if grew else digits
        return f"{digits[0]}:{digits[1:3]}"
    if len(digits) >= 3:
        return f"{digits[:2]}:{digits[2:4]}"             # 1130 → 11:30
    if grew and len(digits) == 2:
        return digits + ":"                              # 11 → 11:
    return digits


def parse_percent(text):
    """Процент 0..100 включительно (запятая или точка). Неверное - ValueError"""
    raw = re.sub(r"\s", "", str(text or "")).replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d*)?|\.\d+", raw):
        raise ValueError(raw)
    value = float(raw)
    if not 0 <= value <= 100:
        raise ValueError(raw)
    return value
