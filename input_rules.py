"""Правила ввода чисел - одни на все формы: деньги (цены, суммы), количество, процент.

Классы эквивалентности и границы описаны в tests/README.md («Классы эквивалентности»):
- деньги: больше 0 и не больше MONEY_MAX; запятая или точка; пробелы между разрядами ("1 500");
  копейки округляются до 2 знаков ("0,001" -> 0 -> неверно); nan / inf / буквы / пусто - неверно;
- количество: целое от 1 до QUANTITY_MAX; пусто - 1 (если разрешено);
- процент: от 0 до 100 включительно.
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


def parse_percent(text):
    """Процент 0..100 включительно (запятая или точка). Неверное - ValueError"""
    raw = re.sub(r"\s", "", str(text or "")).replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d*)?|\.\d+", raw):
        raise ValueError(raw)
    value = float(raw)
    if not 0 <= value <= 100:
        raise ValueError(raw)
    return value
