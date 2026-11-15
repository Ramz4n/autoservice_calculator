# -*- coding: utf-8 -*-
"""Парное (pairwise) тестирование: набор строк, в котором каждая пара значений любых двух факторов
встречается хотя бы раз. Ошибки чаще всего сидят на стыке двух условий («у записи есть наряд» + «вписан
пробег»), а перебор всех сочетаний слишком велик (7 факторов - сотни строк).

Без внешних библиотек: жадный подбор (каждый раз берём допустимую строку, закрывающую больше всего
ещё не покрытых пар). Детерминированно - при тех же факторах всегда тот же набор."""
from itertools import combinations, product


def pairwise(factors, valid=lambda row: True):
    """factors: {фактор: [значения]}; valid(row) -> False для невозможных сочетаний (ограничения).
    Возвращает список строк {фактор: значение}. Пары, невозможные ни в одной допустимой строке, не требуются"""
    names = list(factors)
    rows = [dict(zip(names, values)) for values in product(*(factors[n] for n in names))]
    rows = [row for row in rows if valid(row)]

    def pairs_of(row):
        return {((a, row[a]), (b, row[b])) for a, b in combinations(names, 2)}

    row_pairs = [pairs_of(row) for row in rows]
    uncovered = set().union(*row_pairs) if row_pairs else set()
    chosen = []
    while uncovered:
        best = max(range(len(rows)), key=lambda i: len(row_pairs[i] & uncovered))
        chosen.append(rows[best])
        uncovered -= row_pairs[best]
    return chosen


def all_pairs_covered(factors, chosen, valid=lambda row: True):
    """Проверка генератора: все допустимые пары есть в наборе. Возвращает непокрытые пары"""
    names = list(factors)
    need = set()
    for values in product(*(factors[n] for n in names)):
        row = dict(zip(names, values))
        if valid(row):
            need |= {((a, row[a]), (b, row[b])) for a, b in combinations(names, 2)}
    have = set()
    for row in chosen:
        have |= {((a, row[a]), (b, row[b])) for a, b in combinations(names, 2)}
    return need - have
