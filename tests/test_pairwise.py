# -*- coding: utf-8 -*-
"""Парное тестирование «Добавить работу» (генератор - pairwise.py).

Факторы и значения (классы эквивалентности - tests/README.md):
  car      new / known      - новая машина или уже в базе (прошлый наряд с пробегом 1000, свой VIN)
  booking  none / booking   - работа без записи или по записи клиента (только у машины из базы)
  phone    own / empty      - телефон клиента вписан / стёрт (вопрос, ответ «Да»)
  mileage  empty / more / less  - пусто, 1100 (больше прошлого), 900 (меньше - вопрос, ответ «Да»)
  vin      empty / 17 / short16 - пусто, новый VIN 17 символов, 16 символов (вопрос, ответ «Да»)
  brand    catalog / lowercase  - «Kia Rio» как в справочнике / «kia rio» (записывается как в справочнике)

Набор 1 - пары верных значений: всё должно сохраниться, а вопросы - появиться ровно там, где нужно.
Набор 2 - неверные значения (нет мастера, 9 цифр телефона, марка не из справочника) на каждом пути
(новая машина / машина из базы / по записи): предупреждение и ни одной записи в базе.
Неверные значения в пары не смешиваем: форма отклоняет строку целиком, и остальные пары этой строки
на самом деле не проверялись бы.
Тестовые госномера Т4xxТТ799, телефоны +790000004xx"""
from datetime import date, timedelta

from pairwise import pairwise, all_pairs_covered

FACTORS = {
    "car": ["new", "known"],
    "booking": ["none", "booking"],
    "phone": ["own", "empty"],
    "mileage": ["empty", "more", "less"],
    "vin": ["empty", "17", "short16"],
    "brand": ["catalog", "lowercase"],
}


def valid(row):
    return not (row["booking"] == "booking" and row["car"] == "new")   # запись всегда на машину из базы


ROWS = pairwise(FACTORS, valid)
INVALID = [("master", "мастер"), ("phone9", "+7"), ("brand_foreign", "нет в списке")]
PATHS = [("new", "none"), ("known", "none"), ("known", "booking")]

PLATES = [f"Т4{i:02d}ТТ799" for i in range(len(ROWS))] + [f"Т4{50 + i:02d}ТТ799" for i in range(len(INVALID) * 3)]
PHONES = ["+7" + f"90000004{i:02d}" for i in range(len(ROWS))] + \
         ["+7" + f"90000004{50 + i:02d}" for i in range(len(INVALID) * 3)]


def prepare(h):
    h.require_free(PLATES, PHONES)


def make_case(h, index, car, booking):
    """Подготовка: машина из базы (прошлый наряд, пробег 1000, свой VIN) и запись, если нужны"""
    db = h.app.db
    plate, phone10 = f"Т4{index:02d}ТТ799", f"90000004{index:02d}"
    name = f"Тест Пара {index}"
    case = {"plate": plate, "phone10": phone10, "name": name, "old_vin": "", "car_id": None, "booking_id": None,
            "new_vin": f"Z9P4{index:02d}00000000000"}
    if car == "known":
        client = db.get_or_create_client(full_name=name, phone="+7" + phone10)
        car_id = db.get_or_create_car(client, "Kia", "Rio", plate)
        case["old_vin"] = f"Z9K4{index:02d}00000000000"
        h.q("UPDATE client_cars SET vin = %s WHERE id = %s", (case["old_vin"], car_id))
        db.add_work(db.get_masters()[0][0], "Тест прошлый наряд", 100, (date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "1000", car_id=car_id, client_id=client)
        case["car_id"] = car_id
        if booking == "booking":
            case["booking_id"] = db.add_booking(date.today(), "11:00", client, car_id)
    return case


def fill_form(h, case, row, invalid=None):
    """Заполнить «Добавить работу» по строке набора; invalid - одно неверное значение"""
    app = h.app
    known = row["car"] == "known"
    lower = row["brand"] == "lowercase"
    if case["booking_id"]:
        app.switch_tab("works")
        app.clear_work_form()
        h.root.update()
        app.open_booking_in_add_work(case["booking_id"])
        h.root.update()
    elif known:
        h.works_form(case["plate"].lower(), master=None, save=False)
    else:
        h.works_form(case["plate"].lower(), "kia" if lower else "Kia", "rio" if lower else "Rio",
                     case["phone10"], case["name"], master=None, save=False, to_catalog=False)

    def set_field(key, entry, value):
        if key in app.works_locked:
            app.works_unlock_field(key)   # как карандаш ✎
        entry.delete(0, "end")
        if value:
            entry.insert(0, value)

    if known and lower:
        set_field("brand", app.car_brand_entry, "kia")
        set_field("model", app.car_model_entry, "rio")
    if invalid == "brand_foreign":
        set_field("brand", app.car_brand_entry, "Несуществующая Марка")
    if row["phone"] == "empty" or invalid == "phone9":
        if "phone" in app.works_locked:
            app.works_unlock_field("phone")
        app.set_phone_value(app.client_phone_entry, case["phone10"][:9] if invalid == "phone9" else "")
    set_field("mileage", app.mileage_entry, {"empty": "", "more": "1100", "less": "900"}[row["mileage"]])
    set_field("vin", app.vin_entry, {"empty": "", "17": case["new_vin"], "short16": case["new_vin"][:16]}[row["vin"]])
    app.refresh_workers_combo()
    app.worker_combo.set("" if invalid == "master" else list(app.workers_data)[0])
    h.add_work_item(f"Тест пара {case['plate']}", 700)


def test_pairwise_work_saved(h):
    """«Добавить работу», пары верных значений: сохранено то, что вписали, вопросы - ровно где нужно"""
    app = h.app
    tr = app.tr
    missing = all_pairs_covered(FACTORS, ROWS, valid)
    h.check(f"набор покрывает все пары факторов ({len(ROWS)} строк вместо 144 сочетаний)", not missing, missing)
    vin_overwrite = []
    original_overwrite = app.ask_vin_overwrite
    app.ask_vin_overwrite = lambda old, new: vin_overwrite.append((old, new)) or "overwrite"
    try:
        for index, row in enumerate(ROWS):
            label = f"пара {index}: " + ", ".join(f"{k}={v}" for k, v in row.items())
            case = make_case(h, index, row["car"], row["booking"])
            known = row["car"] == "known"
            fill_form(h, case, row)
            del vin_overwrite[:]
            n = len(h.dialogs)
            app.add_work()
            h.root.update()
            dialogs = h.dialogs_since(n)
            texts = [d[2] for d in dialogs]
            car = h.car(case["plate"])
            work = h.q("SELECT amount, mileage, booking_id FROM works WHERE car_id = %s AND amount = 700",
                       (car[0],)) if car else ()
            card = h.q("SELECT car_brand, car_model, vin FROM client_cars WHERE id = %s", (car[0],)) if car else ()
            expected_mileage = {"empty": None, "more": 1100, "less": 900}[row["mileage"]]
            expected_vin = {"empty": case["old_vin"], "17": case["new_vin"], "short16": case["new_vin"][:16]}[row["vin"]]
            problems = []
            if not any(d[0] == "showinfo" for d in dialogs):
                problems.append("нет сообщения «сохранено»")
            if len(work) != 1:
                problems.append(f"нарядов на 700: {len(work)}")
            elif work[0][1] != expected_mileage:
                problems.append(f"пробег {work[0][1]} вместо {expected_mileage}")
            if card and (card[0][0], card[0][1]) != ("Kia", "Rio"):
                problems.append(f"марка/модель {card[0][:2]} вместо Kia Rio")
            if card and (card[0][2] or "") != expected_vin:
                problems.append(f"VIN {card[0][2]!r} вместо {expected_vin!r}")
            if case["booking_id"] and work and work[0][2] != case["booking_id"]:
                problems.append("наряд не привязан к записи")
            asked = {
                "пробег меньше прошлого": any(t.startswith(tr("works.ask_mileage_less").split("{")[0]) for t in texts),
                "VIN не полностью": any(t.startswith(tr("works.vin_too_short").split("{")[0]) for t in texts),
                "перезаписать VIN": bool(vin_overwrite),
                "без телефона": tr("works.ask_save_without_phone") in texts,
                "телефон стёрли": any(d[0] == "askyesnocancel" for d in dialogs),
            }
            expected_asked = {
                "пробег меньше прошлого": known and row["mileage"] == "less",
                "VIN не полностью": row["vin"] == "short16",
                "перезаписать VIN": known and row["vin"] != "empty",
                "без телефона": not known and row["phone"] == "empty",
                "телефон стёрли": known and row["phone"] == "empty",
            }
            for question, was in asked.items():
                if was != expected_asked[question]:
                    problems.append(f"вопрос «{question}»: {'был' if was else 'не было'}")
            h.check(label, not problems, problems)
    finally:
        app.ask_vin_overwrite = original_overwrite
        app.clear_work_form()


def test_pairwise_invalid_rejected(h):
    """«Добавить работу»: неверное значение на каждом пути (новая машина / из базы / по записи) -
    предупреждение и ни одной записи в базе"""
    app = h.app
    original_overwrite = app.ask_vin_overwrite
    app.ask_vin_overwrite = lambda old, new: "overwrite"
    try:
        index = 50
        for invalid, warn in INVALID:
            for car, booking in PATHS:
                row = {"car": car, "booking": booking, "phone": "own", "mileage": "more", "vin": "17",
                       "brand": "catalog"}
                case = make_case(h, index, car, booking)
                index += 1

                def action(case=case, row=row, invalid=invalid):
                    fill_form(h, case, row, invalid)
                    app.add_work()

                h.expect_rejected(f"{invalid}: машина {car}, {booking}", action, warn)
    finally:
        app.ask_vin_overwrite = original_overwrite
        app.clear_work_form()


TESTS = [test_pairwise_work_saved, test_pairwise_invalid_rejected]
