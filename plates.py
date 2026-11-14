# -*- coding: utf-8 -*-
"""Госномера: единое написание в базе и проверка ввода.

Российский номер, набранный латиницей (A123BC77), и тот же номер кириллицей (А123ВС77) - одна машина.
В базу номер пишется заглавными, без пробелов, российский - кириллицей. Номера других стран
(35OL123, 1234AB-7) остаются как написаны: латиницу переводим, только если получился российский номер.
"""

import re

# Латинские буквы, которые выглядят как буквы российского госномера
PLATE_LATIN_TO_CYR = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")
# В российских госномерах только эти 12 букв
PLATE_LETTERS = "АВЕКМНОРСТУХ"
RU_PLATE = re.compile(rf"[{PLATE_LETTERS}]\d{{3}}[{PLATE_LETTERS}]{{2}}\d{{2,3}}")
# Номер без первой буквы: 123ВС77
RU_PLATE_NO_FIRST = re.compile(rf"\d{{3}}[{PLATE_LETTERS}]{{2}}\d{{2,3}}")
PLATE_EXAMPLE = "А123ВС777"


def normalize_plate(plate):
    """Госномер для базы и поиска: заглавными, без пробелов; российский - кириллицей"""
    plate = re.sub(r"\s", "", str(plate or "")).upper()
    ru = plate.translate(PLATE_LATIN_TO_CYR)
    if RU_PLATE.fullmatch(ru) or RU_PLATE_NO_FIRST.fullmatch(ru):
        return ru
    # Номер наполовину латиницей, наполовину кириллицей (А123BC77) - тоже российский
    if re.search("[А-ЯЁ]", plate):
        return ru
    return plate


def plate_may_continue(plate):
    """Российский номер с регионом из двух цифр (Х555ХХ77) - полный, но к нему ещё может дописаться
    цифра региона (Х555ХХ777). Пока номер вводят, такую машину нельзя подставлять сразу"""
    return bool(re.fullmatch(rf"[{PLATE_LETTERS}]\d{{3}}[{PLATE_LETTERS}]{{2}}\d{{2}}", normalize_plate(plate)))


def plate_search_key(text):
    """Часть госномера для поиска "по мере ввода": заглавными, без пробелов, латиница -> кириллица"""
    return re.sub(r"\s", "", str(text or "")).upper().translate(PLATE_LATIN_TO_CYR)


def plate_problem(plate):
    """Что не так с госномером (для предупреждения перед сохранением новой машины):
    None - похоже на российский номер или номер другой страны (только латиница и цифры);
    ("missing_letter", номер) - пропущена первая буква (123ВС77);
    ("bad_letters", "Г, Й") - буквы, которых нет в российских номерах;
    ("format", номер) - кириллица, но не по образцу А123ВС777"""
    plate = normalize_plate(plate)
    if not plate or RU_PLATE.fullmatch(plate):
        return None
    if RU_PLATE_NO_FIRST.fullmatch(plate):
        return "missing_letter", plate
    cyrillic = re.findall("[А-ЯЁ]", plate)
    if not cyrillic:
        return None   # номер другой страны - латиница и цифры, не проверяем
    bad = sorted({ch for ch in cyrillic if ch not in PLATE_LETTERS})
    if bad:
        return "bad_letters", ", ".join(bad)
    return "format", plate
