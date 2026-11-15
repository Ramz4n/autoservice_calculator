# -*- coding: utf-8 -*-
"""Позитивные проверки: формы сохраняют то, что нужно, туда, куда нужно.
Каждая функция test_* получает Harness (h). Тестовые госномера Т1xxТТ799 / Т105ТТ77(7), телефоны +7900000010x"""
from datetime import date, timedelta

PLATES = ["Т101ТТ799", "Т102ТТ799", "Т103ТТ799", "Т104ТТ799", "Т105ТТ77", "Т105ТТ777", "Т106ТТ799", "Т107ТТ799", "Т108ТТ799",
          "Т140ТТ799", "Т141ТТ799", "Т142ТТ799", "Т143ТТ799", "Т144ТТ799", "Т145ТТ799", "Т146ТТ799", "Т147ТТ799",
          "Т148ТТ799", "Т149ТТ799", "Т150ТТ799", "Т151ТТ799", "Т152ТТ799", "Т153ТТ799"]
PHONES = ["+79000000101", "+79000000103", "+79000000104", "+79000000105", "+79000000106", "+79000000107", "+79000000108",
          "+79000000140", "+79000000141", "+79000000142", "+79000000143", "+79000000144", "+79000000145", "+79000000146", "+79000000147",
          "+79000000148", "+79000000149", "+79000000150", "+79000000151", "+79000000152", "+79000000153"]


def prepare(h):
    h.require_free(PLATES, PHONES)


def test_booking_new_car_latin(h):
    """«Записать клиента»: новая машина, госномер латиницей - в базе кириллицей, клиент, запись на завтра"""
    h.booking_form("t101tt799", "Kia", "Rio", "9000000101", "Тест Один")
    car = h.car("Т101ТТ799")
    if not h.check("машина сохранена кириллицей Т101ТТ799", car, car):
        return
    h.check("марка и модель", car[2:4] == ("Kia", "Rio"), car)
    client = h.q("SELECT full_name, phone FROM clients WHERE id = %s", (car[1],))
    h.check("клиент «Тест Один» +79000000101", client and client[0] == ("Тест Один", "+79000000101"), client)
    booking = h.q("SELECT id, booking_date, status FROM bookings WHERE car_id = %s ORDER BY id DESC LIMIT 1", (car[0],))
    h.check("запись на завтра «в ожидании»",
            booking and booking[0][1] == date.today() + timedelta(days=1) and booking[0][2] == "waiting", booking)
    h.state.update(car1=car[0], client1=car[1], booking1=booking[0][0] if booking else None)


def test_booking_same_car_same_time(h):
    """Та же машина на то же время - не записывается повторно, дублей машины и клиента нет"""
    before = len(h.dialogs)
    h.booking_form("Т101ТТ799")
    h.check("предупреждение «уже записан»", any("уже записан" in d[2] for d in h.dialogs_since(before)))
    h.check("машина одна", h.q("SELECT COUNT(*) FROM client_cars WHERE car_number = 'Т101ТТ799'")[0][0] == 1)
    h.check("клиент один", h.q("SELECT COUNT(*) FROM clients WHERE phone = '+79000000101'")[0][0] == 1)
    h.check("запись одна", h.q("SELECT COUNT(*) FROM bookings WHERE car_id = %s", (h.state.get("car1"),))[0][0] == 1)


def test_booking_region_continues(h):
    """Есть Т105ТТ77; вводим Т105ТТ777 - первая машина не подставляется, создаётся отдельная со своим владельцем"""
    h.booking_form("т105тт77", "Lada", "Granta", "9000000105", "Тест Пять")
    first = h.car("Т105ТТ77")
    h.check("Т105ТТ77 сохранена", first, first)
    h.booking_form("т105тт777", "Kia", "Ceed", "9000000106", "Тест Шесть", typed_live_first="т105тт77")
    second = h.car("Т105ТТ777")
    if not h.check("Т105ТТ777 - отдельная машина", second and first and second[0] != first[0], (first, second)):
        return
    h.check("владелец Т105ТТ77 не переписан", h.car("Т105ТТ77")[1] == first[1])
    h.check("Т105ТТ777: Kia Ceed, владелец «Тест Шесть»", second[2:4] == ("Kia", "Ceed") and
            h.q("SELECT full_name FROM clients WHERE id = %s", (second[1],))[0][0] == "Тест Шесть")


def test_work_from_booking(h):
    """«Добавить работу» по записи: работа привязана к записи, машине, клиенту, мастеру; запись «в работе»"""
    app = h.app
    app.switch_tab("works")
    app.clear_work_form()
    app.open_booking_in_add_work(h.state["booking1"])
    h.root.update()
    app.refresh_workers_combo()
    master_name = list(app.workers_data)[0]
    app.worker_combo.set(master_name)
    h.add_work_item("Тест замена масла", 1500)
    app.add_work()
    h.root.update()
    work = h.q("SELECT id, car_id, client_id, amount, worker_id FROM works WHERE booking_id = %s", (h.state["booking1"],))
    if not h.check("работа сохранена по записи", len(work) == 1, work):
        return
    h.check("машина / клиент / сумма / мастер", work[0][1] == h.state["car1"] and work[0][2] == h.state["client1"]
            and float(work[0][3]) == 1500 and work[0][4] == app.workers_data[master_name], work)
    h.check("запись «в работе»",
            h.q("SELECT status FROM bookings WHERE id = %s", (h.state["booking1"],))[0][0] == "in_progress")
    h.state["work1"] = work[0][0]


def test_work_new_car(h):
    """«Добавить работу»: новая машина без записи - машина, клиент и работа"""
    h.works_form("т103тт799", "Hyundai", "Solaris", "9000000103", "Тест Три", items=[("Тест диагностика", 800)])
    car = h.car("Т103ТТ799")
    if not h.check("машина Т103ТТ799 Hyundai Solaris", car and car[2:4] == ("Hyundai", "Solaris"), car):
        return
    work = h.q("SELECT client_id, amount FROM works WHERE car_id = %s", (car[0],))
    h.check("работа 800 у этой машины и её владельца", work and float(work[0][1]) == 800 and work[0][0] == car[1], work)


def test_work_brand_from_catalog(h):
    """«Добавить работу»: марка и модель из справочника - написание как в справочнике («hyundai» → «Hyundai»);
    машина уже в базе с маркой не из справочника (старые данные) - работа сохраняется"""
    h.works_form("т140тт799", "hyundai", "SOLARIS", "9000000140", "Тест Справочник", to_catalog=False,
                 items=[("Тест справочник", 500)])
    car = h.car("Т140ТТ799")
    h.check("марка и модель записаны как в справочнике (Hyundai Solaris)",
            car and car[2:4] == ("Hyundai", "Solaris"), car)

    db = h.app.db
    client = db.get_or_create_client(full_name="Тест Старая Марка", phone="+79000000141")
    db.get_or_create_car(client, "ТестСтараяМарка", "Модель", "Т141ТТ799")
    h.works_form("т141тт799", to_catalog=False, items=[("Тест старая марка", 700)])
    car = h.car("Т141ТТ799")
    work = h.q("SELECT amount FROM works WHERE car_id = %s", (car[0],)) if car else ()
    h.check("машина из базы с маркой не из справочника - работа сохранена",
            work and float(work[0][0]) == 700 and car[2] == "ТестСтараяМарка", (car, work))


def test_car_hints_same_everywhere(h):
    """Подсказки марки и модели - одни на все формы: «Добавить работу» и склад; выбрали марку -
    модель очищена, список её моделей; уже вписана ровно эта марка - список не мешает"""
    app = h.app
    for title, hints in (("«Добавить работу»", app.works_car_hints), ("склад", app.wh_car_hints)):
        hints.brand_entry.delete(0, "end"); hints.brand_entry.insert(0, "ki")
        hints.model_entry.delete(0, "end"); hints.model_entry.insert(0, "старая")
        hints.on_brand_key()
        brands = list(hints.brand_listbox.get(0, "end")) if hints.brand_visible else []
        h.check(f"{title}: на «ki» в подсказке Kia", "Kia" in brands, brands)
        if "Kia" in brands:
            hints.brand_listbox.selection_clear(0, "end")
            hints.brand_listbox.selection_set(brands.index("Kia"))
            hints.on_brand_select()
            models = list(hints.model_listbox.get(0, "end")) if hints.model_visible else []
            h.check(f"{title}: выбрали Kia - модель очищена, в списке модели Kia",
                    hints.brand_entry.get() == "Kia" and not hints.model_entry.get() and "Rio" in models,
                    (hints.brand_entry.get(), hints.model_entry.get(), models[:5]))
        hints.on_brand_key()
        h.check(f"{title}: вписана ровно марка Kia - подсказка спрятана", not hints.brand_visible)
        hints.hide()
        hints.brand_entry.delete(0, "end"); hints.model_entry.delete(0, "end")


def test_work_mileage_digits_only(h):
    """«Добавить работу»: в пробег не набрать буквы (убираются при вводе), цифры сохраняются в наряд и у машины"""
    app = h.app
    h.works_form("т142тт799", "Kia", "Rio", "9000000142", "Тест Пробег", save=False)
    entry = app.mileage_entry
    # Нажатие клавиши (<KeyRelease>) зовёт digits_only_clean; синтетические нажатия Tk доставляет,
    # только когда окно программы на переднем плане - поэтому зовём напрямую
    entry.delete(0, "end"); entry.insert(0, "12а3 45б6")
    entry.digits_only_clean()
    h.check("буквы и пробелы из пробега убраны при вводе", entry.get() == "123456", entry.get())
    h.check("очистка привязана к вводу, вставке и уходу из поля",
            all("digits_only_clean" not in b and b for b in (entry._entry.bind(ev) for ev in
                                                              ("<KeyRelease>", "<<Paste>>", "<FocusOut>"))),
            [entry._entry.bind(ev)[:60] for ev in ("<KeyRelease>", "<<Paste>>", "<FocusOut>")])
    entry.delete(0, "end"); entry.insert(0, "12345678")
    entry.digits_only_clean()
    h.check("пробег не длиннее 7 цифр", entry.get() == "1234567", entry.get())
    h.add_work_item("Тест пробег", 600)
    app.add_work()
    h.root.update()
    car = h.car("Т142ТТ799")
    work = h.q("SELECT mileage FROM works WHERE car_id = %s", (car[0],)) if car else ()
    saved = h.q("SELECT mileage FROM client_cars WHERE id = %s", (car[0],)) if car else ()
    h.check("пробег 1234567 в наряде и у машины", work and work[0][0] == 1234567 and saved
            and str(saved[0][0]) == "1234567", (work, saved))


def test_work_mileage_less_than_last(h):
    """«Добавить работу»: пробег меньше прошлого у этой машины (123 → 12) - вопрос «всё равно записать?»
    с прошлым пробегом; «Да» - работа записана с новым пробегом; пробег больше прошлого - без вопроса"""
    app = h.app

    def finish_open_records():
        # Машину отдали: записи «в работе» → «Выполнено» (иначе госномер снова откроет тот же наряд для правки)
        for (booking_id,) in h.q("SELECT b.id FROM bookings b JOIN client_cars cc ON b.car_id = cc.id "
                                 "WHERE cc.car_number = 'Т143ТТ799' AND b.status = 'in_progress'"):
            app.db.update_booking_status(booking_id, "completed")
            app.db.mark_work_completed(booking_id)

    def save(mileage, item, answers=()):
        finish_open_records()
        h.works_form("т143тт799", "Kia", "Rio", "9000000143", "Тест Пробег Меньше", save=False)
        app.mileage_entry.delete(0, "end"); app.mileage_entry.insert(0, mileage)
        h.add_work_item(item, 500)
        h.answers[:] = list(answers)
        n = len(h.dialogs)
        app.add_work()
        h.root.update()
        h.answers[:] = []
        return [d for d in h.dialogs_since(n) if d[0] == "askyesno" and "пробег" in d[2].lower()]

    h.check("первый наряд с пробегом 123 - без вопроса о пробеге", not save("123", "Тест пробег первый"))
    asked = save("12", "Тест пробег второй", answers=[True])
    h.check("пробег 12 после 123 - вопрос с прошлым пробегом 123 и новым 12",
            len(asked) == 1 and "123 км" in asked[0][2] and "12 км" in asked[0][2], asked)
    car = h.car("Т143ТТ799")
    rows = h.q("SELECT mileage FROM works WHERE car_id = %s ORDER BY id", (car[0],)) if car else ()
    h.check("«Да» - второй наряд записан с пробегом 12", [r[0] for r in rows] == [123, 12], rows)
    h.check("пробег 500 после 12 - без вопроса", not save("500", "Тест пробег третий"))


def test_work_merge_keeps_mileage_vin(h):
    """«Добавить работу»: у записи уже есть наряд - новые работы дописываются в него («объединено»),
    вписанные пробег и VIN сохраняются в наряд и у машины (раньше пропадали)"""
    from datetime import date
    app, db = h.app, h.app.db
    client = db.get_or_create_client(full_name="Тест Объединение", phone="+79000000144")
    car = db.get_or_create_car(client, "Kia", "Rio", "Т144ТТ799")
    booking = db.add_booking(date.today(), "10:00", client, car)
    master = h.q("SELECT id FROM workers LIMIT 1")[0][0]
    work = db.add_work(master, "Тест первая работа", 500, date.today().strftime("%Y-%m-%d"), "1000",
                       booking_id=booking, car_id=car, client_id=client)
    db.update_booking_status(booking, "in_progress")

    h.works_form("т144тт799", "Kia", "Rio", "9000000144", "Тест Объединение", save=False)
    app.editing_work_id = None          # запись выбрана, но наряд не открыт для правки - путь «объединить»
    app.selected_booking_id = booking
    app.works_list.clear()              # в форму встали работы открытого наряда - дописываем только новую
    app.mileage_entry.delete(0, "end"); app.mileage_entry.insert(0, "1500")
    app.vin_entry.delete(0, "end"); app.vin_entry.insert(0, "XTA21100099998888")
    h.add_work_item("Тест вторая работа", 300)
    n = len(h.dialogs)
    app.add_work()
    h.root.update()
    merged = any(d[0] == "showinfo" and d[2] == app.tr("works.msg_work_merged") for d in h.dialogs_since(n))
    rows = h.q("SELECT id, mileage, amount FROM works WHERE car_id = %s", (car,))
    card = h.q("SELECT mileage, vin FROM client_cars WHERE id = %s", (car,))
    h.check("работы объединены в один наряд 800", merged and len(rows) == 1 and rows[0][0] == work
            and float(rows[0][2]) == 800, (merged, rows))
    h.check("пробег 1500 в наряде и у машины, VIN у машины",
            rows and rows[0][1] == 1500 and card and str(card[0][0]) == "1500" and card[0][1] == "XTA21100099998888",
            (rows, card))


def test_input_rules_boundaries(h):
    """Правила чисел (input_rules.py) на границах: допустимые крайние значения проходят, соседние - нет"""
    from input_rules import parse_money, parse_quantity, parse_percent, MONEY_MAX, QUANTITY_MAX

    def value(func, text, **kw):
        try:
            return func(text, **kw)
        except ValueError:
            return "ошибка"

    cases = [  # (функция, ввод, ожидание)
        (parse_money, "0,01", 0.01), (parse_money, "0.005", 0.01), (parse_money, "0,004", "ошибка"),
        (parse_money, "0", "ошибка"), (parse_money, "1", 1.0), (parse_money, "1 500", 1500.0),
        (parse_money, "1500,5", 1500.5), (parse_money, "12.", 12.0), (parse_money, ".5", 0.5),
        (parse_money, "99999999.99", MONEY_MAX), (parse_money, "99 999 999,99", MONEY_MAX),
        (parse_money, "100000000", "ошибка"), (parse_money, "-1", "ошибка"), (parse_money, "+5", "ошибка"),
        (parse_money, "nan", "ошибка"), (parse_money, "inf", "ошибка"), (parse_money, "1e3", "ошибка"),
        (parse_money, "", "ошибка"), (parse_money, "1,2,3", "ошибка"),
        (parse_quantity, "", 1), (parse_quantity, "1", 1), (parse_quantity, "0", "ошибка"),
        (parse_quantity, str(QUANTITY_MAX), QUANTITY_MAX), (parse_quantity, str(QUANTITY_MAX + 1), "ошибка"),
        (parse_quantity, "-1", "ошибка"), (parse_quantity, "1.0", "ошибка"), (parse_quantity, " 3 ", 3),
        (parse_percent, "0", 0.0), (parse_percent, "100", 100.0), (parse_percent, "100,01", "ошибка"),
        (parse_percent, "-0.01", "ошибка"), (parse_percent, "40,5", 40.5), (parse_percent, "nan", "ошибка"),
    ]
    wrong = [(f.__name__, text, expected, value(f, text)) for f, text, expected in cases
             if value(f, text) != expected]
    h.check(f"{len(cases)} граничных значений разобраны верно", not wrong, wrong)
    h.check("пустая цена на складе разрешена (неизвестна)", parse_money("", allow_empty=True) is None)


def test_boundaries_in_forms(h):
    """Границы в формах: цена 0,01 и 99 999 999,99 сохраняются точно; VIN 17 - без вопроса, 18-й символ не
    набрать; склад: количество 9999 и цена 0,01; пробег, равный прошлому, и на 1 больше - без вопроса"""
    app = h.app
    h.works_form("т145тт799", "Kia", "Rio", "9000000145", "Тест Границы", save=False)
    h.add_work_item("Тест граница мин", "0,01")
    h.add_work_item("Тест граница макс", "99 999 999,99")
    app.part_name_entry.insert(0, "Тест недописанная"); app.work_name_entry.insert(0, "Тест недописанная")
    app.clear_work_form()
    h.check("«Очистить форму» стирает и недобавленные работу и запчасть",
            not app.part_name_entry.get() and not app.work_name_entry.get())
    h.works_form("т145тт799", "Kia", "Rio", "9000000145", "Тест Границы", save=False)
    h.add_work_item("Тест граница мин", "0,01")
    h.add_work_item("Тест граница макс", "99 999 999,99")
    h.check("цены 0,01 и 99 999 999,99 в списке работ",
            [p for _, p in app.works_list] == [0.01, 99999999.99], app.works_list)
    app.vin_entry.delete(0, "end"); app.vin_entry.insert(0, "Z9T14500000000145Z")
    h.check("VIN: 18-й символ отрезан", app.vin_entry.get() == "Z9T14500000000145", app.vin_entry.get())
    app.mileage_entry.delete(0, "end"); app.mileage_entry.insert(0, "500")
    n = len(h.dialogs)
    app.add_work()
    h.root.update()
    asked = [d for d in h.dialogs_since(n) if d[0] == "askyesno"]
    h.check("VIN ровно 17 символов - без вопроса «введён не полностью»", not asked, asked)
    car = h.car("Т145ТТ799")
    work = h.q("SELECT amount, mileage FROM works WHERE car_id = %s", (car[0],)) if car else ()
    h.check("сумма наряда 100 000 000,00 (0,01 + 99 999 999,99) записана точно",
            work and float(work[0][0]) == 100000000.0, work)

    for mileage, label in (("500", "равный прошлому (500 → 500)"), ("501", "на 1 больше (500 → 501)")):
        for (booking_id,) in h.q("SELECT b.id FROM bookings b WHERE b.car_id = %s AND b.status = 'in_progress'",
                                 (car[0],)):
            app.db.update_booking_status(booking_id, "completed")
            app.db.mark_work_completed(booking_id)
        h.works_form("т145тт799", "Kia", "Rio", "9000000145", "Тест Границы", save=False,
                     items=[("Тест граница пробег " + mileage, 100)])
        app.mileage_entry.delete(0, "end"); app.mileage_entry.insert(0, mileage)
        n = len(h.dialogs)
        app.add_work()
        h.root.update()
        asked = [d for d in h.dialogs_since(n) if d[0] == "askyesno" and "пробег" in d[2].lower()]
        h.check(f"пробег {label} - без вопроса", not asked, asked)

    h.warehouse_form("т146тт799", "Kia", "Rio", "9000000146", "Тест Склад Границы", part="Тест граница склад",
                     qty="9999", price="0,01")
    part = h.q("SELECT quantity, price FROM warehouse_parts WHERE part_name = 'Тест граница склад'")
    h.check("склад: количество 9999 и цена 0,01 сохранены", part and part[0][0] == 9999 and float(part[0][1]) == 0.01,
            part)


def test_work_opens_active_record(h):
    """«Добавить работу»: ввели госномер (латиницей) машины с записью «в работе» - открывается эта запись"""
    h.works_form("t101tt799", save=False, master=None)
    app = h.app
    h.check("открыта запись «в работе»", getattr(app, "selected_booking_id", None) == h.state.get("booking1"),
            getattr(app, "selected_booking_id", None))
    h.check("в форме её работа", [n for n, _ in app.works_list] == ["Тест замена масла"], app.works_list)
    app.clear_work_form()


def test_plate_hint_all_forms(h):
    """Х555ХХ77 во время ввода только подсказывается во всех формах (не подставляется)"""
    app = h.app
    if not h.car("Т105ТТ77"):   # тест можно запускать и отдельно
        client = app.db.get_or_create_client(full_name="Тест Пять", phone="+79000000105")
        app.db.get_or_create_car(client, "Lada", "Granta", "Т105ТТ77")
    # Добавить работу
    app.switch_tab("works")
    app.clear_work_form()
    app.car_number_entry.insert(0, "т105тт77")
    app.on_car_number_change(live=True)
    h.check("«Добавить работу»: подсказка, ничего не подставлено",
            "Т105ТТ77" in app.works_lookup_text and not app.car_brand_entry.get() and "number" not in app.works_locked,
            app.works_lookup_text)
    app.clear_work_form()
    # Склад
    h.warehouse_form("", save=False, close=False)
    e = app.wh_car_number_entry
    e.delete(0, "end"); e.insert(0, "т105тт77"); e._entry.event_generate("<KeyRelease>")
    h.check("склад: подсказка, телефон не подставлен", "Т105ТТ77" in app.wh_car_info_label.cget("text")
            and not app.wh_selected_car_id,
            f"строка={app.wh_car_info_label.cget('text')!r} car_id={app.wh_selected_car_id} "
            f"искали={getattr(app, 'wh_searched_number', None)!r} поиск={app.find_car_by_plate('т105тт77', True)['status']}")
    app.hide_add_part_form()


def test_warehouse_pick_car(h):
    """Склад → «Добавить запчасть»: телефон клиента с двумя машинами (из теста записи), машину не выбрали -
    запчасть не сохраняется (раньше уходила на склад без машины), красным подсвечен список «Машины клиента»;
    вписали госномер - подсветка снята; выбрали машину - госномер подставлен, запчасть привязана к ней"""
    app, root = h.app, h.root
    car2 = h.car("Т107ТТ799")
    if not h.check("есть клиент с двумя машинами (тест записи)", car2, car2):
        return
    red = app.FORM_ERROR_BORDER
    app.switch_tab("warehouse")
    app.show_add_part_form()
    h.wait(300)
    try:
        app.wh_phone_entry._entry.focus_force()
        root.update()
        app.set_phone_value(app.wh_phone_entry, "9000000107")
        app.wh_phone_entry._entry.event_generate("<KeyRelease>")
        root.update()
        combo = app.wh_phone_cars_combo
        if not h.check("склад: по телефону показан список машин клиента",
                       combo.winfo_manager() and any("Т107ТТ799" in v for v in combo.cget("values"))):
            return
        app.wh_part_name_entry.delete(0, "end"); app.wh_part_name_entry.insert(0, "Тест деталь выбора")
        rows = lambda: h.q("SELECT COUNT(*) FROM warehouse_parts")[0][0]
        before_rows, before = rows(), len(h.dialogs)
        app.add_warehouse_part()
        root.update()
        h.check("склад: машину не выбрали - предупреждение, запчасть не сохранена",
                any(d[0] == "showwarning" and "Выберите машину клиента" in d[2] for d in h.dialogs_since(before))
                and rows() == before_rows)
        h.check("склад: список «Машины клиента» красный, госномер - нет",
                combo.cget("border_color") == red and app.wh_car_number_entry.cget("border_color") != red)

        app.wh_car_number_entry._entry.focus_force()
        root.update()
        app.wh_car_number_entry.insert(0, "Т")
        app.wh_car_number_entry._entry.event_generate("<KeyRelease>")
        root.update()
        h.check("склад: вписали госномер - подсветка списка снята", combo.cget("border_color") != red)
        app.wh_car_number_entry.delete(0, "end")
        app.wh_car_number_entry._entry.event_generate("<KeyRelease>")
        root.update()

        choice = next(v for v in combo.cget("values") if "Т107ТТ799" in v)
        combo.set(choice)
        app.on_wh_phone_car_select(choice)
        root.update()
        h.check("склад: выбрали машину - госномер подставлен, подсветки нет",
                app.wh_car_number_entry.get().upper() == "Т107ТТ799" and combo.cget("border_color") != red,
                app.wh_car_number_entry.get())
        app.add_warehouse_part()
        root.update()
        h.check("склад: запчасть сохранена и привязана к выбранной машине",
                h.q("SELECT car_id FROM warehouse_parts WHERE part_name = 'Тест деталь выбора'") == ((car2[0],),))
    finally:
        app.hide_add_part_form()


def test_work_pick_car(h):
    """«Добавить работу»: телефон клиента с двумя машинами (из теста записи) - кнопки машин красные;
    «Сохранить» без выбора - «Выберите машину клиента» (не «Введите марку»), ничего не сохранено;
    нажали машину - данные подставлены, работа сохранена на эту машину"""
    app, root = h.app, h.root
    car1 = h.car("Т106ТТ799")
    if not h.check("есть клиент с двумя машинами (тест записи)", car1, car1):
        return
    chips = app.client_cars_combo
    app.switch_tab("works")
    app.clear_work_form()
    root.update()
    app.client_phone_entry._entry.focus_force()
    root.update()
    app.set_phone_value(app.client_phone_entry, "9000000107")
    app.client_phone_entry._entry.event_generate("<KeyRelease>")
    root.update()
    h.check("«Добавить работу»: две машины клиента кнопками, ждём выбора (красные)",
            chips.get() == app.tr("works.select_car") and chips._pick
            and sum("ТТ799" in v for v in chips._values) == 2, (chips.get(), chips._values))
    app.worker_combo.set(first_master(app))
    h.add_work_item("Тест работа выбора", 700)
    works_before, before = h.q("SELECT COUNT(*) FROM works")[0][0], len(h.dialogs)
    app.add_work()
    root.update()
    new = h.dialogs_since(before)
    h.check("«Сохранить» без выбора машины - «Выберите машину клиента», не «Введите марку»",
            any(d[0] == "showwarning" and "Выберите машину клиента" in d[2] for d in new)
            and not any("марку" in d[2] for d in new), new)
    h.check("ничего не сохранено, кнопки машин по-прежнему красные",
            h.q("SELECT COUNT(*) FROM works")[0][0] == works_before and chips._pick)

    choice = next(v for v in chips._values if "Т106ТТ799" in v)
    chips._click(choice)
    root.update()
    h.check("нажали машину - госномер, марка, модель подставлены",
            (app.car_number_entry.get().upper(), app.car_brand_entry.get(), app.car_model_entry.get())
            == ("Т106ТТ799", "Kia", "Rio"))
    app.add_work()
    root.update()
    row = h.q("SELECT car_id, booking_id FROM works WHERE description = 'Тест работа выбора'")
    h.check("работа сохранена на выбранную машину", row and row[0][0] == car1[0], row)
    if row:
        h.complete_booking(row[0][1])
    app.clear_work_form()


def first_master(app):
    app.refresh_workers_combo()
    return list(app.workers_data)[0]


def test_warehouse_existing_car(h):
    """Склад: запчасть для найденной машины привязана к ней"""
    h.warehouse_form("т101тт799", part="Тест фильтр масляный")
    r = h.q("SELECT car_id FROM warehouse_parts WHERE part_name = 'Тест фильтр масляный'")
    h.check("запчасть у машины Т101ТТ799", r and r[0][0] == h.state.get("car1"), r)


def test_warehouse_new_car(h):
    """Склад: новая машина (марка, модель, телефон) - машина и запчасть"""
    h.warehouse_form("т104тт799", "Lada", "Vesta", "9000000104", "Тест Четыре", part="Тест колодки")
    car = h.car("Т104ТТ799")
    h.check("машина Т104ТТ799 Lada Vesta", car and car[2:4] == ("Lada", "Vesta"), car)
    r = h.q("SELECT car_id FROM warehouse_parts WHERE part_name = 'Тест колодки'")
    h.check("запчасть у новой машины", car and r and r[0][0] == car[0], r)


def test_edit_data(h):
    """«Изменить данные»: госномер (латиницей), модель (другим регистром - записывается как в справочнике)
    и имя - та же машина и тот же клиент"""
    h.edit_form(h.state["booking1"], {0: "t102tt799", 2: "ceed gt", 6: "Тест Один Изменён"})
    car = h.q("SELECT car_number, car_model FROM client_cars WHERE id = %s", (h.state["car1"],))
    h.check("та же машина: Т102ТТ799, Ceed GT", car and car[0] == ("Т102ТТ799", "Ceed GT"), car)
    name = h.q("SELECT full_name FROM clients WHERE id = %s", (h.state["client1"],))
    h.check("имя клиента изменено", name and name[0][0] == "Тест Один Изменён", name)


def test_delete_booking_with_work(h):
    """«Записи» → Удалить: запись с работой - удаляются запись и работа, запчасть отвязывается, машина остаётся"""
    app = h.app
    if h.state.get("work1"):
        h.q("UPDATE warehouse_parts SET work_id = %s WHERE part_name = 'Тест фильтр масляный'", (h.state["work1"],))
    app.get_selected_booking_id = lambda: h.state["booking1"]
    app.delete_selected_booking()
    h.root.update()
    h.check("запись удалена", not h.q("SELECT id FROM bookings WHERE id = %s", (h.state["booking1"],)))
    h.check("работа удалена", not h.q("SELECT id FROM works WHERE booking_id = %s", (h.state["booking1"],)))
    r = h.q("SELECT work_id FROM warehouse_parts WHERE part_name = 'Тест фильтр масляный'")
    h.check("запчасть на складе, отвязана от наряда", r and r[0][0] is None, r)
    h.check("машина осталась", h.q("SELECT id FROM client_cars WHERE id = %s", (h.state["car1"],)))


def test_positions(h):
    """Должность «с машинами»: сотрудник выбирается в «Добавить работу»; выключили - пропал; удаление"""
    app = h.app
    app.refresh_workers_list()
    app.position_name_entry.delete(0, "end"); app.position_name_entry.insert(0, "Тест-электрик")
    app.position_cars_var.set(True)
    app.add_position()
    pos = h.q("SELECT id, is_master FROM positions WHERE name = 'Тест-электрик'")
    if not h.check("должность создана «с машинами»", pos and pos[0][1] == 1, pos):
        return
    app.worker_name_entry.delete(0, "end"); app.worker_name_entry.insert(0, "Тест Электрик")
    app.worker_position_combo.set("Тест-электрик")
    app.add_worker()
    worker = h.q("SELECT id, position_id FROM workers WHERE full_name = 'Тест Электрик'")
    if not h.check("сотрудник с должностью", worker and worker[0][1] == pos[0][0], worker):
        return
    app.refresh_workers_combo()
    h.check("сотрудник есть в «Добавить работу»", "Тест Электрик" in app.workers_data)
    app.positions_tree.selection_set(str(pos[0][0]))
    app.toggle_position_cars()
    app.refresh_workers_combo()
    h.check("выключили «с машинами» - сотрудника нет в «Добавить работу»", "Тест Электрик" not in app.workers_data)
    app.workers_tree.selection_set(str(worker[0][0]))
    app.delete_worker()
    h.check("сотрудник удалён", not h.q("SELECT id FROM workers WHERE id = %s", (worker[0][0],)))
    app.refresh_positions()
    app.positions_tree.selection_set(str(pos[0][0]))
    app.delete_position()
    h.check("пустая должность удалена", not h.q("SELECT id FROM positions WHERE id = %s", (pos[0][0],)))


def test_finance_category_follows_switch(h):
    """«Финансы»: категория «Доход» и переключатель «Расход / Доход» всегда сходятся"""
    app = h.app
    tr = app.tr
    income, rent, tools = tr("finances.income_label"), tr("finances.category_rent"), tr("finances.category_tools")
    combo = app.expense_category_combo
    app.switch_tab("expenses")
    app.is_income_var.set(False)
    app.on_income_switch_changed()
    combo.set(tools)

    app.is_income_var.set(True)
    app.on_income_switch_changed()
    h.check("переключили на «Доход» - категория «Доход»", combo.get() == income, combo.get())
    app.is_income_var.set(False)
    app.on_income_switch_changed()
    h.check("обратно на «Расход» - категория расходов, не «Доход»", combo.get() == rent, combo.get())

    combo.set(tools)
    app.is_income_var.set(True)
    app.on_income_switch_changed()
    app.is_income_var.set(False)
    app.on_income_switch_changed()
    combo.set(tools)
    app.on_expense_category_selected(tools)
    h.check("«Расход» с другой категорией - категория не меняется", combo.get() == tools and not app.is_income_var.get())

    combo.set(income)
    app.on_expense_category_selected(income)
    h.check("выбрали категорию «Доход» при «Расходе» - переключатель на «Доход»", app.is_income_var.get())
    combo.set(rent)
    app.on_expense_category_selected(rent)
    h.check("выбрали категорию расходов при «Доходе» - переключатель на «Расход»", not app.is_income_var.get())

    # Сохранение: категория «Доход» из списка при «Расходе» - запись сохраняется как доход
    app.is_income_var.set(False)
    app.on_income_switch_changed()
    app.on_expense_category_selected(income)
    combo.set(income)
    entry_id = h.finance_entry(app.is_income_var.get(), income, "Тест доход из списка", 100)
    row = h.q("SELECT is_income, category FROM expenses WHERE id = %s", (entry_id,))
    h.check("категория «Доход» сохранилась как доход", row and row[0] == (1, income), row)
    if entry_id:
        h.delete_expense_in_finances(entry_id)
    app.is_income_var.set(False)
    app.on_income_switch_changed()


def test_booking_pick_car_clears_error(h):
    """«Записать клиента»: телефон клиента с двумя машинами, машину не выбрали - «Записать» не даёт, красным
    подсвечен список «Машины клиента» (не госномер); выбрали машину - госномер подставился, подсветка снята;
    «Записать» - запись на эту машину. Вписали госномер вручную - подсветка списка тоже снимается"""
    import customtkinter as ctk
    app, root = h.app, h.root
    db = app.db
    client = db.get_or_create_client(full_name="Тест Две Машины", phone="+79000000107")
    db.get_or_create_car(client, "Kia", "Rio", "Т106ТТ799")
    car2 = db.get_or_create_car(client, "Lada", "Vesta", "Т107ТТ799")

    bw = app._ensure_booking_window()
    bw["open"]()
    h.wait(300)
    win = bw["window"]
    plate_e, brand_e, model_e, phone_e, name_e = h.find_widgets(win, ctk.CTkEntry)[:5]
    normal = plate_e.cget("border_color")
    red = app.FORM_ERROR_BORDER
    try:
        app.set_phone_value(phone_e, "9000000107")
        phone_e._entry.event_generate("<KeyRelease>")
        phone_e._entry.event_generate("<FocusOut>")
        root.update()
        combo = next((c for c in h.find_widgets(win, ctk.CTkComboBox) if c.winfo_manager()
                      and any("Т107ТТ799" in v for v in c.cget("values"))), None)
        if not h.check("по телефону показан список машин клиента", combo):
            return
        h.check("имя клиента подставлено", name_e.get() == "Тест Две Машины", name_e.get())
        h.find_button(win, app.tr("bookings.btn_tomorrow")).invoke()
        before_rows = h.q("SELECT COUNT(*) FROM bookings")[0][0]
        before = len(h.dialogs)
        h.find_button(win, app.tr("bookings.btn_book")).invoke()
        root.update()
        h.check("машину не выбрали - предупреждение «выберите машину клиента», записи нет",
                any(d[0] == "showwarning" and "Выберите машину клиента" in d[2] for d in h.dialogs_since(before))
                and h.q("SELECT COUNT(*) FROM bookings")[0][0] == before_rows)
        h.check("список «Машины клиента» подсвечен красным, госномер - нет",
                combo.cget("border_color") == red and plate_e.cget("border_color") != red)

        # Вписали госномер сами - подсветка списка снимается (щёлкнули в поле - фокус там, потом ввод)
        plate_e._entry.focus_force()
        root.update()
        plate_e.insert(0, "Т")
        plate_e._entry.event_generate("<KeyRelease>")
        root.update()
        h.check("вписали госномер вручную - подсветка списка снята", combo.cget("border_color") != red)
        plate_e.delete(0, "end")
        plate_e._entry.event_generate("<KeyRelease>")
        h.find_button(win, app.tr("bookings.btn_book")).invoke()
        root.update()
        h.check("снова «Записать» без машины - список опять красный", combo.cget("border_color") == red)

        choice = next(v for v in combo.cget("values") if "Т107ТТ799" in v)
        combo.set(choice)
        combo._command(choice)
        root.update()
        h.check("выбрали машину - госномер подставлен", plate_e.get().upper() == "Т107ТТ799", plate_e.get())
        h.check("выбрали машину - подсветка списка снята, госномер обычной рамкой",
                combo.cget("border_color") != red and plate_e.cget("border_color") == normal,
                (combo.cget("border_color"), plate_e.cget("border_color")))

        h.find_button(win, app.tr("bookings.btn_book")).invoke()
        root.update()
        h.check("«Записать» - запись на выбранную машину и клиента",
                h.q("SELECT client_id FROM bookings WHERE car_id = %s", (car2,)) == ((client,),))
    finally:
        win.withdraw(); bw["overlay"].withdraw(); win.grab_release()


def test_users_and_roles(h):
    """Настройки → Пользователи: добавить (повтор логина - нельзя), вход по паролю, сменить пароль,
    заблокировать (не входит) / разблокировать, удалить; себя не заблокировать и не удалить.
    Роль «пользователь»: в меню нет «Отчётов», «Финансов», «Статистики», в настройках нет «Пользователей»"""
    import customtkinter as ctk
    app, db, root = h.app, h.app.db, h.root
    app.refresh_users_list()

    def add(login, password, role="user"):
        app.new_user_login.delete(0, "end"); app.new_user_login.insert(0, login)
        app.new_user_pass.delete(0, "end"); app.new_user_pass.insert(0, password)
        app.new_user_name.delete(0, "end"); app.new_user_name.insert(0, "Тест " + login)
        app.new_user_role.set(role)
        n = len(h.dialogs)
        app._add_user_from_tab()
        return h.dialogs_since(n)

    def select(login):
        app.refresh_users_list()
        item = next((i for i in app.users_tree.get_children() if app.users_tree.item(i, "values")[0] == login), None)
        if item:
            app.users_tree.selection_set(item)
        return item

    add("autotest_user", "пароль-1")
    uid = h.q("SELECT id, role, is_active FROM users WHERE username = 'autotest_user'")
    if not h.check("пользователь добавлен (роль «пользователь», активен), есть в списке",
                   uid and uid[0][1:] == ("user", 1) and select("autotest_user"), uid):
        return
    uid = uid[0][0]
    h.check("вход: верный пароль - да, неверный - нет",
            db.verify_user("autotest_user", "пароль-1") and not db.verify_user("autotest_user", "чужой"))
    dialogs = add("autotest_user", "другой")
    h.check("тот же логин второй раз - ошибка, второго нет",
            any(d[0] == "showerror" for d in dialogs)
            and h.q("SELECT COUNT(*) FROM users WHERE username = 'autotest_user'")[0][0] == 1)
    before = h.q("SELECT COUNT(*) FROM users")[0][0]
    dialogs = add("autotest_empty", "")
    h.check("без пароля - предупреждение, не добавлен",
            any(d[0] == "showwarning" for d in dialogs) and h.q("SELECT COUNT(*) FROM users")[0][0] == before)

    # Сменить пароль: несовпадение - не меняется, совпадение - вход с новым
    select("autotest_user")
    before_win = set(root.winfo_children())
    app._users_tab_change_password()
    root.update()
    win = next((x for x in root.winfo_children() if x not in before_win and isinstance(x, ctk.CTkToplevel)), None)
    if h.check("окно смены пароля открылось", win):
        win.pwd1.set("пароль-2"); win.pwd2.set("другой")
        win._save()
        h.check("пароли не совпадают - не сменён", db.verify_user("autotest_user", "пароль-1"))
        win.pwd2.set("пароль-2")
        win._save()
        root.update()
        h.check("пароль сменён: новый подходит, старый нет",
                db.verify_user("autotest_user", "пароль-2") and not db.verify_user("autotest_user", "пароль-1"))
        if win.winfo_exists():
            win.destroy()

    select("autotest_user")
    app._users_tab_toggle_active()
    h.check("заблокирован - войти нельзя", not db.verify_user("autotest_user", "пароль-2")
            and h.q("SELECT is_active FROM users WHERE id = %s", (uid,)) == ((0,),))
    select("autotest_user")
    app._users_tab_toggle_active()
    h.check("разблокирован - вход снова работает", db.verify_user("autotest_user", "пароль-2"))

    # Себя - нельзя (текущий пользователь - autotest_admin)
    add("autotest_admin", "пароль-а", "admin")
    admin_id = h.q("SELECT id FROM users WHERE username = 'autotest_admin'")[0][0]
    real_user = app.current_user
    app.current_user = dict(real_user, id=admin_id)
    try:
        for label, action in (("заблокировать", app._users_tab_toggle_active), ("удалить", app._users_tab_delete)):
            select("autotest_admin")
            n = len(h.dialogs)
            h.answers[:] = [True]
            action()
            h.answers[:] = []
            h.check(f"себя {label} нельзя - предупреждение, активен",
                    any(d[0] == "showwarning" for d in h.dialogs_since(n))
                    and h.q("SELECT is_active FROM users WHERE id = %s", (admin_id,)) == ((1,),))
    finally:
        app.current_user = real_user

    select("autotest_user")
    h.answers[:] = [False]
    app._users_tab_delete()
    h.check("удаление, ответ «Нет» - остался", h.q("SELECT id FROM users WHERE id = %s", (uid,)))
    select("autotest_user")
    h.answers[:] = [True]
    app._users_tab_delete()
    h.answers[:] = []
    h.check("удалён - нет в базе и в списке", not h.q("SELECT id FROM users WHERE id = %s", (uid,))
            and not select("autotest_user"))

    # Роли (вторую копию программы в тестах не запустить - CustomTkinter зацикливается на перерисовке,
    # поэтому проверяем само правило, по которому строится меню)
    user_tabs = set(app.menu_tabs_for("user"))
    h.check("роль «пользователь»: нет «Отчётов», «Финансов», «Статистики»; есть работа, записи, склад",
            not user_tabs & {"reports", "expenses", "statistics"} and {"works", "bookings", "warehouse"} <= user_tabs,
            user_tabs)
    h.check("роль «пользователь»: нет вкладки «Пользователи»; админ - есть",
            not app.is_admin_role("user") and app.is_admin_role("admin") and hasattr(app, "users_tab_frame"))
    user_settings = app.settings_tabs_for("user")
    h.check("роль «пользователь»: в «Настройках» нет «Сотрудников» и «Пользователей», восстанавливать из копии нельзя",
            "workers" not in user_settings and "users" not in user_settings and not app.can_restore_backup("user")
            and {"cars", "keywords", "spareparts", "backup"} <= set(user_settings), user_settings)
    h.check("администратору - «Сотрудники», «Пользователи» и восстановление есть",
            {"workers", "users"} <= set(app.settings_tabs_for("admin")) and app.can_restore_backup("admin"))
    names = {app.tr("settings.workers_tab"), app.tr("settings.users_tab")}
    h.check("у администратора в программе вкладки «Сотрудники» и «Пользователи» на месте",
            names <= set(app.add_notebook._tab_dict), list(app.add_notebook._tab_dict))
    real_user = app.current_user
    app.current_user = dict(real_user, role="user")
    try:
        n = len(h.dialogs)
        app._do_restore_backup()
        h.check("пользователю «Восстановить» не срабатывает (нет даже выбора файла)", not h.dialogs_since(n))
    finally:
        app.current_user = real_user
    admin_tabs = [tab for _, tab in app.menu_items]
    h.check("у администратора в меню все вкладки (как правило для «admin»)",
            admin_tabs == app.menu_tabs_for("admin") and {"reports", "expenses", "statistics"} <= set(admin_tabs),
            admin_tabs)


def test_locales(h):
    """Переводы: во всех 5 языках один и тот же набор текстов, подстановки ({name}, {count}...) те же, пустых нет;
    каждый текст, который программа берёт по ключу, есть в русском. Иначе в интерфейсе вместо текста -
    технический ключ вроде works.vin_conflict_title"""
    import json, os, re
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    langs = ["ru", "en", "sr", "hy", "ka"]
    data = {l: json.load(open(os.path.join(base, "config", "locales", f"{l}.json"), encoding="utf-8")) for l in langs}
    ru = set(data["ru"])
    for lang in langs[1:]:
        keys = set(data[lang])
        h.check(f"переводы {lang}: те же тексты, что в русском", keys == ru,
                {"нет": sorted(ru - keys)[:10], "лишние": sorted(keys - ru)[:10]})
    holder = re.compile(r"\{(\w+)\}")
    bad = [(lang, key) for key in ru for lang in langs[1:]
           if key in data[lang] and set(holder.findall(data[lang][key])) != set(holder.findall(data["ru"][key]))]
    h.check("подстановки ({name}, {count}...) во всех языках те же", not bad, bad[:10])
    empty = [(lang, key) for lang in langs for key, value in data[lang].items() if not str(value).strip()]
    h.check("пустых текстов нет", not empty, empty[:10])
    used = set()
    for name in ("autoservice_calculator.py", "login_window.py", "tire_storage.py"):
        text = open(os.path.join(base, name), encoding="utf-8").read()
        used |= {k for k in re.findall(r'\btr\(\s*["\']([a-z_]+\.[A-Za-z0-9_.]+)["\']', text)}
    # Ключ, собранный в коде (f"staff.short_{kind}"), - проверяем все его варианты
    prefixes = {k for k in used if k.endswith("_")}
    used = (used - prefixes) | {p + kind for p in prefixes for kind in ("day_off", "vacation", "sick")}
    missing = sorted(k for k in used if k not in ru)
    h.check("все тексты, которые берёт программа, есть в переводах", not missing, missing)


def test_login(h):
    """Окно входа, кнопка «Войти» (логика без окна - второе главное окно в тестах не запустить):
    верный пароль - вход и запоминается логин; неверный - ошибка, пароль стирается; пустой - ошибка;
    заблокированный - не входит"""
    import login_window
    app, db = h.app, h.app.db
    settings_path = h.m.SETTINGS_FILE
    with open(settings_path, encoding="utf-8") as f:
        settings_before = f.read()

    class Var:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class Label:
        text = ""

        def configure(self, text=""):
            self.text = text

    class Form:
        """Поля окна входа"""
        def __init__(self, login, password):
            self.username_var, self.password_var = Var(login), Var(password)
            self.error_label = Label()
            self.password_entry = type("Entry", (), {"focus": lambda self: None})()
            self.db, self.tr = db, app.tr
            self.logged_user, self.quitted = None, False

        def quit(self):
            self.quitted = True

    def login(name, password):
        form = Form(name, password)
        login_window.LoginWindow._do_login(form)
        return form

    try:
        db.create_user("autotest_login", "пароль-вход", "Тест Вход", "user")
        ok = login("autotest_login", "пароль-вход")
        h.check("верный пароль - вход, пользователь с ролью", ok.quitted and ok.logged_user
                and ok.logged_user["role"] == "user" and not ok.error_label.text, ok.logged_user)
        h.check("логин запомнен для следующего входа", login_window._load_settings().get("last_username") == "autotest_login")
        bad = login("autotest_login", "неверный")
        h.check("неверный пароль - ошибка, не вошёл, пароль стёрт",
                not bad.quitted and bad.error_label.text == app.tr("login.error_invalid") and bad.password_var.get() == "")
        empty = login("", "")
        h.check("пустые логин и пароль - ошибка", not empty.quitted and empty.error_label.text == app.tr("login.error_empty"))
        uid = h.q("SELECT id FROM users WHERE username = 'autotest_login'")[0][0]
        db.set_user_active(uid, False)
        blocked = login("autotest_login", "пароль-вход")
        h.check("заблокированный - не входит", not blocked.quitted and blocked.error_label.text == app.tr("login.error_invalid"))
    finally:
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(settings_before)


def test_bookings_no_phone_red(h):
    """«Записи»: у клиента без телефона «⚠ нет телефона» красным только в ячейке «Телефон» (надпись поверх
    ячейки, ровно по ней); у записей с телефоном надписи нет; клик по надписи выбирает строку; колонку
    «Телефон» скрыли - надпись тоже скрыта"""
    app = h.app
    h.booking_form("т108тт799", "ТестБезТелефона", "Модель", "9000000108", "Тест Без Телефона")
    booking = h.q("SELECT b.id, b.client_id FROM bookings b JOIN client_cars cc ON cc.id = b.car_id "
                  "WHERE cc.car_number = 'Т108ТТ799'")
    if not h.check("запись сохранена", booking):
        return
    booking_id, client_id = booking[0]
    h.q("UPDATE clients SET phone = NULL WHERE id = %s", (client_id,))
    app.switch_tab("bookings")
    app.refresh_bookings()
    tree = app.bookings_tree
    item = next((i for i in tree.get_children() if str(tree.item(i, "values")[0]) == str(booking_id)), None)
    if not h.check("запись в списке", item):
        return
    tree.see(item)
    for _ in range(5):
        h.root.update()
    label = app._bookings_no_phone_marks.get(item)
    h.check("у записи без телефона - надпись «⚠ нет телефона» красным",
            label is not None and label.cget("text") == "⚠ нет телефона"
            and label.cget("fg") == app.BOOKINGS_NO_PHONE_COLOR, label and label.cget("text"))
    if label is None:
        return
    bbox = tree.bbox(item, "phone")
    h.check("надпись ровно поверх ячейки «Телефон»",
            label.winfo_manager() == "place" and bbox
            and (label.winfo_x(), label.winfo_y(), label.winfo_width(), label.winfo_height()) == tuple(bbox),
            (bbox, label.winfo_x(), label.winfo_y(), label.winfo_width()))
    with_phone = [i for i in tree.get_children() if app.bookings_raw[i]["phone"]]
    h.check("у записей с телефоном надписи нет",
            with_phone and not any(i in app._bookings_no_phone_marks for i in with_phone))
    tree.selection_set(())
    label.event_generate("<Button-1>", x=5, y=5)
    for _ in range(3):
        h.root.update()
    h.check("клик по надписи выбирает строку, фон надписи - как у выбранной строки",
            tree.selection() == (item,) and label.cget("bg") == app.BOOKINGS_SELECTED_BG, tree.selection())
    columns = tree["displaycolumns"]
    try:
        tree["displaycolumns"] = [c for c in columns if c != "phone"]
        tree.event_generate("<<ColumnsChanged>>")
        for _ in range(3):
            h.root.update()
        h.check("колонку «Телефон» скрыли - надписи не видно", not label.winfo_manager())
    finally:
        tree["displaycolumns"] = columns
        tree.event_generate("<<ColumnsChanged>>")
        h.root.update()


def test_bookings_row_colors(h):
    """«Записи»: каждая строка во всю ширину залита спокойным цветом своего статуса; у статуса один цвет
    (без чередования через строку); цвета светлые (не «ядерные»); надпись «нет телефона» - того же цвета, что строка"""
    app = h.app
    app.switch_tab("bookings")
    app.bookings_status_var.set(app.tr("bookings.filter_all"))
    app.bookings_show_all_time = True
    try:
        app.refresh_bookings()
        tree = app.bookings_tree
        items = tree.get_children()
        if not h.check("в списке есть записи", items):
            return
        wrong = []
        shown = {}   # статус -> какие цвета фона у его строк на экране
        for index, item in enumerate(items):
            tags = tree.item(item, "tags")
            status = next((t for t in tags if t in app.BOOKING_ROW_COLORS), None)
            bg_tags = [t for t in tags if str(t).startswith("bg_")]
            background = str(tree.tag_configure(f"bg_{status}", "background"))
            if bg_tags != [f"bg_{status}"] or background != app.BOOKING_ROW_COLORS[status]:
                wrong.append((index, tags))
            shown.setdefault(status, set()).add(background)
        h.check("у каждой строки фон своего статуса", not wrong, wrong[:5])
        h.check("у строк одного статуса один цвет (нет чередования через строку)",
                all(len(c) == 1 for c in shown.values()), shown)

        def light(color):
            r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
            return min(r, g, b) >= 0xd8 and max(r, g, b) - min(r, g, b) <= 0x28
        colors = list(app.BOOKING_ROW_COLORS.values())
        h.check("цвета строк спокойные: светлые и неяркие", all(light(c) for c in colors), colors)
        h.check("цвета разных статусов различаются", len(set(colors)) == len(colors))
        h.check("выбранная строка отличается от всех цветов статусов", app.BOOKINGS_SELECTED_BG not in colors)
        for _ in range(3):
            h.root.update()
        marks = [(item, label) for item, label in app._bookings_no_phone_marks.items() if label.winfo_manager()]
        tree.selection_set(())
        app._bookings_place_no_phone_marks()
        h.check("надпись «нет телефона» - цветом своей строки",
                all(label.cget("bg") == app._bookings_row_background(tree.item(item, "tags")) for item, label in marks))
    finally:
        app.bookings_show_all_time = False
        app.refresh_bookings()


def test_bookings_middle_click_scroll(h):
    """«Записи»: нажали колесо мыши - значок ⇕ на месте нажатия; мышь ниже значка - список едет вниз, выше - вверх,
    дальше - быстрее, рядом со значком - стоит; без движения прокрутка остаётся включённой и выключается
    повторным колесом / Esc / щелчком; нажали-повели-отпустили - выключается сразу; работает и над «нет телефона»"""
    import types as _types
    app = h.app
    app.switch_tab("bookings")
    app.bookings_status_var.set(app.tr("bookings.filter_all"))
    app.bookings_show_all_time = True
    tree, auto = app.bookings_tree, app.bookings_autoscroll
    tree.configure(height=3)   # чтобы точно было что прокручивать
    real_pointer, real_shown = auto.pointer, auto.still_shown
    try:
        app.refresh_bookings()
        for _ in range(3):
            h.root.update()
        if not h.check("в списке больше 3 записей - есть что прокручивать",
                       len(tree.get_children()) > 3 and auto.can_scroll(), len(tree.get_children())):
            return
        tree.yview_moveto(0)
        h.root.update()
        x0, y0 = tree.winfo_rootx() + 200, tree.winfo_rooty() + 60
        press = _types.SimpleNamespace(x_root=x0, y_root=y0)
        pointer = [(x0, y0)]
        auto.pointer = lambda: pointer[0]
        auto.still_shown = lambda: tree.winfo_viewable()   # окно тестов может быть не в фокусе

        auto.on_press(press)
        h.root.update()
        h.check("нажали колесо - прокрутка включена, значок на месте нажатия",
                auto.active and auto.marker is not None and auto.marker.winfo_exists()
                and abs(auto.marker.winfo_rootx() + auto.MARKER_SIZE // 2 - x0) <= 2
                and abs(auto.marker.winfo_rooty() + auto.MARKER_SIZE // 2 - y0) <= 2,
                auto.marker and auto.marker.geometry())
        h.check("курсор - стрелки вверх-вниз", str(tree.cget("cursor")) == "sb_v_double_arrow", tree.cget("cursor"))

        pointer[0] = (x0, y0 + auto.DEAD_ZONE - 2)
        auto.tick(dt=1.0)
        h.check("мышь рядом со значком - список стоит", tree.yview()[0] == 0.0, tree.yview())

        pointer[0] = (x0, y0 + 40)
        auto.tick(dt=0.5)
        first_slow = tree.yview()[0]
        h.check("мышь ниже значка - список поехал вниз", first_slow > 0.0, tree.yview())
        h.check("курсор - стрелка вниз", str(tree.cget("cursor")) == "sb_down_arrow")
        h.check("дальше от значка - быстрее", auto.rate(200) > auto.rate(40) > 0 and auto.rate(-200) < 0)

        pointer[0] = (x0, y0 - 40)
        auto.tick(dt=0.5)
        h.check("мышь выше значка - список поехал вверх", tree.yview()[0] < first_slow, (first_slow, tree.yview()))
        h.check("курсор - стрелка вверх", str(tree.cget("cursor")) == "sb_up_arrow")

        # Нажали-повели-отпустили - выключилась, значок убран, курсор прежний
        auto.on_release()
        h.root.update()
        h.check("повели и отпустили колесо - прокрутка выключена, значка нет",
                not auto.active and auto.marker is None)
        h.check("курсор вернулся обычный", str(tree.cget("cursor")) == "", tree.cget("cursor"))

        # Нажали и отпустили, не двигая, - остаётся; сама едет по таймеру
        tree.yview_moveto(0)
        pointer[0] = (x0, y0)
        auto.on_press(press)
        auto.on_release()
        h.check("щёлкнули колесом без движения - прокрутка осталась включённой", auto.active)
        pointer[0] = (x0, y0 + 150)
        h.wait(500)
        h.check("мышь ниже - список едет сам, пока прокрутка включена", tree.yview()[0] > 0.0, tree.yview())
        h.check("шаг прокрутки с перерисовкой быстрый (программа отвечает)", 0 < auto.last_step_ms < 150,
                round(auto.last_step_ms, 1))
        auto.on_press(press)
        h.check("ещё раз колесо - выключена", not auto.active and auto.marker is None)

        auto.on_press(press)
        # Клавиши Tk отдаёт виджету с фокусом - он может быть где угодно в программе (тут - в поле поиска)
        app.bookings_search_entry._entry.focus_force()   # как формы программы: окно тестов могло быть не активно
        h.root.update()
        focus = app.root.focus_get()
        app.bookings_search_entry._entry.event_generate("<KeyPress-Escape>")
        h.root.update()
        h.check("Esc - выключена", not auto.active and auto.marker is None, focus)

        auto.on_press(press)
        app.root.event_generate("<ButtonPress-1>", x=10, y=10)
        h.root.update()
        h.check("щелчок левой кнопкой - выключена", not auto.active)

        auto.on_press(press)
        app.switch_tab("works")
        h.wait(200)
        h.check("ушли на другую вкладку - выключена", not auto.active and auto.marker is None)
        app.switch_tab("bookings")

        # Над надписью «нет телефона» - то же самое
        labels = list(app._bookings_no_phone_marks.values())
        if labels:
            h.check("надпись «нет телефона» тоже включает прокрутку колесом",
                    "on_press" in str(labels[0].bind("<ButtonPress-2>")) or labels[0].bind("<ButtonPress-2>"))
    finally:
        auto.stop()
        auto.pointer, auto.still_shown = real_pointer, real_shown
        tree.configure(height=15)
        app.bookings_show_all_time = False
        app.refresh_bookings()


def test_tables_middle_click_scroll(h):
    """Прокрутка колесом мыши - во всех таблицах программы: нажатие колеса над каждой таблицей и списком
    включает прокрутку (и в окнах, открытых потом); в окне-диалоге щелчки идут значку, а после выключения
    диалог снова модальный; график «Расписание» - вверх-вниз и влево-вправо"""
    import tkinter as tk
    from tkinter import ttk
    from autoscroll import MiddleClickAutoscroll
    app = h.app
    names = ["users_tree", "workers_tree", "positions_tree", "warehouse_tree", "summary_tree", "keywords_tree",
             "spare_parts_tree", "expenses_tree", "brand_stats_tree", "client_stats_tree", "work_stats_tree",
             "monthly_stats_tree", "bookings_tree", "brands_listbox", "models_listbox", "staff_canvas"]
    missing = []
    for name in names:
        widget = getattr(app, name, None)
        if widget is None:
            missing.append(name + " (нет)")
            continue
        if not widget.winfo_ismapped():
            # На скрытой вкладке нажать нельзя (Windows не передаёт щелчки скрытым) - проверяем привязку
            if not (widget.bind("<ButtonPress-2>") or widget.bind_class(widget.winfo_class(), "<ButtonPress-2>")):
                missing.append(name + " (скрыт, привязки нет)")
            continue
        widget.event_generate("<ButtonPress-2>", x=5, y=5, rootx=widget.winfo_rootx() + 5,
                              rooty=widget.winfo_rooty() + 5)
        auto = MiddleClickAutoscroll._instances.get(widget)
        if auto is None:
            missing.append(name)
        else:
            auto.stop()
    h.check("нажатие колеса доходит до всех таблиц и списков", not missing, missing)

    # Окно, открытое потом (как «Подробно»), модальное: таблица в нём тоже прокручивается колесом
    dialog = tk.Toplevel(h.root)
    dialog.geometry("400x200+50+50")
    tree = ttk.Treeview(dialog, columns=("a",), show="headings")
    tree.pack(fill="both", expand=True)
    for i in range(80):
        tree.insert("", "end", values=(f"строка {i}",))
    try:
        dialog.update()
        dialog.grab_set()
        x0, y0 = tree.winfo_rootx() + 100, tree.winfo_rooty() + 80
        tree.event_generate("<ButtonPress-2>", x=100, y=80, rootx=x0, rooty=y0)
        auto = MiddleClickAutoscroll._instances.get(tree)
        if h.check("в новом окне колесо включило прокрутку", auto and auto.active):
            auto.still_shown = lambda: True
            auto.pointer = lambda: (x0, y0 + 120)
            h.root.update()
            h.check("щелчки, пока прокрутка включена, идут значку (не в таблицу)",
                    auto.marker is not None and auto.marker.grab_current() == auto.marker,
                    auto.marker and auto.marker.grab_current())
            auto.tick(dt=0.5)
            h.check("таблица в новом окне прокрутилась вниз", tree.yview()[0] > 0, tree.yview())
            tree.event_generate("<ButtonPress-2>", x=100, y=80, rootx=x0, rooty=y0)
            h.root.update()
            h.check("колесо ещё раз - выключена", not auto.active and auto.marker is None)
            h.check("после выключения окно снова модальное", dialog.grab_current() == dialog, dialog.grab_current())
    finally:
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()

    # «Сотрудники» → расписание: холст меньше графика - прокрутка в обе стороны
    app.switch_tab("staff")
    app.refresh_staff_tab()
    canvas = app.staff_canvas
    auto = MiddleClickAutoscroll._instances.get(canvas)
    h.root.update()
    # График больше окна: рисунок шире и выше, чем видно (так бывает, когда сотрудников много)
    canvas.configure(scrollregion=(0, 0, canvas.winfo_width() * 3, canvas.winfo_height() * 3))
    canvas.xview_moveto(0)
    canvas.yview_moveto(0)
    h.root.update()
    try:
        if not h.check("график шире и выше окна - есть что прокручивать",
                       auto and auto.can_scroll_x() and canvas.yview() != (0.0, 1.0),
                       (canvas.xview(), canvas.yview(), canvas.cget("scrollregion"), canvas.winfo_width(),
                        canvas.winfo_ismapped(), app.staff_content_size)):
            return
        auto.still_shown = lambda: True
        x0, y0 = canvas.winfo_rootx() + 100, canvas.winfo_rooty() + 40
        auto.start(x0, y0)
        h.check("в графике - значок и курсор в четыре стороны", auto.active and str(canvas.cget("cursor")) == "fleur",
                canvas.cget("cursor"))
        auto.pointer = lambda: (x0 + 80, y0 + 80)
        auto.tick(dt=0.5)
        h.check("мышь правее и ниже - график поехал вправо и вниз",
                canvas.xview()[0] > 0 and canvas.yview()[0] > 0, (canvas.xview(), canvas.yview()))
        right, down = canvas.xview()[0], canvas.yview()[0]
        auto.pointer = lambda: (x0 - 80, y0)
        auto.tick(dt=0.2)
        h.check("мышь левее - влево, по высоте стоит", canvas.xview()[0] < right and canvas.yview()[0] == down,
                (canvas.xview(), canvas.yview()))
        h.check("курсор - стрелка влево", str(canvas.cget("cursor")) == "sb_left_arrow")
        auto.stop()
        h.check("выключена - курсор прежний", not auto.active and str(canvas.cget("cursor")) == "",
                canvas.cget("cursor"))
    finally:
        if auto:
            auto.stop()
            auto.__dict__.pop("still_shown", None)
            auto.__dict__.pop("pointer", None)
        app.draw_staff_calendar()
        app.switch_tab("bookings")


def test_tires_rules(h):
    """Шины: как узнать шины среди запчастей (явно / возможно / нет), сезон, размер и «с дисками» по названию;
    дата в поле - дд.мм.гггг / дд.мм.гг / через / и -; срок хранения по умолчанию - полгода; «срок истёк»"""
    from tires import tire_match, guess_season, guess_size, guess_with_rims, default_store_until, display_status
    from input_rules import parse_date
    h.check("явно шины: шины / резина / покрышки / хранение колёс",
            all(tire_match(n) == "strong" for n in ("Шины зимние", "Резина летняя 4 шт", "Покрышки Nokian",
                                                     "Хранение колёс")))
    h.check("возможно шины: «колёса»", tire_match("Колёса R16 зимние") == "weak")
    h.check("не шины: колодки, колёсный цилиндр, шиномонтаж",
            all(tire_match(n) is None for n in ("Колодки передние", "Колёсный цилиндр", "Шиномонтаж", "")))
    h.check("сезон по названию", (guess_season("Шины зимние"), guess_season("Летняя резина"),
                                  guess_season("Всесезонные шины"), guess_season("Шины")) ==
            ("winter", "summer", "all", None))
    h.check("размер по названию", (guess_size("Шины 205/55r16 зимние"), guess_size("шины 195/75 R16C"),
                                   guess_size("Шины")) == ("205/55 R16", "195/75 R16C", None))
    h.check("с дисками по названию", guess_with_rims("Колёса в сборе") and guess_with_rims("Шины на дисках")
            and not guess_with_rims("Шины зимние"))
    h.check("дата: дд.мм.гггг, дд.мм.гг, / и -",
            parse_date("15.10.2026") == parse_date("15.10.26") == parse_date("15/10/2026") == parse_date("15-10-2026")
            == date(2026, 10, 15))
    h.check("пустая дата - можно, если поле необязательное", parse_date("  ", allow_empty=True) is None)
    h.check("хранить до - через полгода", default_store_until(date(2026, 4, 1)) == date(2026, 10, 1))
    h.check("на хранении и срок прошёл - «срок истёк»; выдано - выдано",
            display_status("stored", date(2026, 1, 1), date(2026, 2, 1)) == "overdue"
            and display_status("stored", date(2026, 3, 1), date(2026, 2, 1)) == "stored"
            and display_status("issued", date(2026, 1, 1), date(2026, 2, 1)) == "issued"
            and display_status("stored", None, date(2026, 2, 1)) == "stored")


def test_tires_accept(h):
    """«Склад» → «Шины» → «Принять шины»: новая машина и клиент создаются (как у запчасти), все поля сохраняются,
    комплект в таблице «На хранении»; машина из базы - находится по госномеру; вкладки «Запчасти | Шины»"""
    app = h.app
    app.switch_tab("warehouse")
    h.root.update()
    h.check("на складе две вкладки: «Запчасти» и «Шины», открыты запчасти",
            list(app.warehouse_page_labels) == ["parts", "tires"] and app.warehouse_page == "parts"
            and app.warehouse_pages["parts"].winfo_ismapped() and not app.warehouse_pages["tires"].winfo_ismapped(),
            (app.warehouse_page, app.warehouse_pages["parts"].winfo_ismapped()))
    app.warehouse_show_page("tires")
    h.root.update()
    h.check("переключили на «Шины» - видна таблица шин, запчастей нет",
            app.tires_tree.winfo_ismapped() and not app.warehouse_tree.winfo_ismapped())
    received = date.today() - timedelta(days=3)
    h.tires_form("т150тт799", "Kia", "Rio", "9000000150", "Тест Шины Один", season="winter", size="205/55 R16",
                 tire_brand="Nokian Hakkapeliitta", qty="4", location="а-12", rims=True,
                 received=received.strftime("%d.%m.%Y"), until="", price="3 500", paid=True,
                 notes="Тест шины один")
    tire = h.tire(notes="Тест шины один")
    if not h.check("комплект сохранён", tire):
        return
    h.check("машина и клиент созданы, комплект за ней", tire["car_number"] == "Т150ТТ799"
            and tire["client_phone"] == "+79000000150" and tire["client_name"] == "Тест Шины Один", tire)
    h.check("поля: зимние, размер, марка, 4 шт., с дисками, ячейка большими буквами",
            (tire["season"], tire["tire_size"], tire["tire_brand"], tire["quantity"], tire["with_rims"],
             tire["location"]) == ("winter", "205/55 R16", "Nokian Hakkapeliitta", 4, True, "А-12"), tire)
    h.check("даты, стоимость, оплачено, статус «на хранении»",
            tire["received_date"] == received and tire["store_until"] is None and float(tire["price"]) == 3500
            and tire["is_paid"] and tire["status"] == "stored" and tire["issued_date"] is None, tire)
    h.check("после приёма открыта вкладка «Шины» и комплект в таблице",
            app.warehouse_page == "tires" and any(t["id"] == tire["id"] for t in app.tires_rows.values()))
    h.state["tire1"] = tire["id"]

    # Машина уже в базе - по госномеру находится, новая не создаётся
    cars_before = h.q("SELECT COUNT(*) FROM client_cars")[0][0]
    h.tires_form("Т150ТТ799", season="summer", size="205/55 R16", location="Б-3", notes="Тест шины летние")
    summer = h.tire(notes="Тест шины летние")
    h.check("машина из базы - комплект за ней, новой машины нет",
            summer and summer["car_id"] == tire["car_id"] and h.q("SELECT COUNT(*) FROM client_cars")[0][0] == cars_before)
    h.check("по умолчанию: 4 шт., принято сегодня, хранить полгода, без дисков, не оплачено",
            summer and summer["quantity"] == 4 and summer["received_date"] == date.today()
            and summer["store_until"] == date.today() + timedelta(days=183) and not summer["with_rims"]
            and not summer["is_paid"], summer)


def test_tires_edit_issue(h):
    """Шины: изменить комплект (двойной клик) - форма открывается с его данными, изменения сохраняются;
    «Выдать клиенту» - «выдано» с сегодняшней датой; «Вернуть на хранение»; оплата; удаление"""
    app = h.app
    tire_id = h.state.get("tire1")
    if not h.check("есть комплект из test_tires_accept", tire_id):
        return
    # Форма изменения - с данными комплекта
    app.switch_tab("warehouse")
    app.warehouse_show_page("tires")
    app.show_add_part_form("tires", tire_id=tire_id)
    h.wait(300)
    h.check("форма изменения: данные комплекта и машины",
            app.tire_size_entry.get() == "205/55 R16" and app.tire_location_entry.get() == "А-12"
            and app.tire_season_switch.get() == app.tr("tires.season_winter") and app.tire_rims_var.get()
            and app.wh_car_number_entry.get() == "Т150ТТ799" and app.wh_selected_car_id is not None
            and app.wh_ok_button.cget("text") == app.tr("common.save"),
            (app.tire_size_entry.get(), app.tire_location_entry.get(), app.wh_car_number_entry.get()))
    app.hide_add_part_form()
    h.tires_form(None, season="all", location="В-7", qty="2", tire_id=tire_id)
    tire = app.db.get_tire_storage_by_id(tire_id)
    h.check("изменения сохранены, новой строки нет",
            (tire["season"], tire["location"], tire["quantity"], tire["tire_size"]) == ("all", "В-7", 2, "205/55 R16")
            and h.q("SELECT COUNT(*) FROM tire_storage WHERE notes = 'Тест шины один'")[0][0] == 1, tire)

    if h.tires_select(tire_id):
        app.set_selected_tires_paid(False)
        h.check("снять оплату", not app.db.get_tire_storage_by_id(tire_id)["is_paid"])
        h.tires_select(tire_id)
        app.set_selected_tires_paid(True)
        h.check("отметить оплату", app.db.get_tire_storage_by_id(tire_id)["is_paid"])
        h.tires_select(tire_id)
        app.issue_selected_tires()
        tire = app.db.get_tire_storage_by_id(tire_id)
        h.check("«Выдать клиенту» - выдано сегодня", tire["status"] == "issued" and tire["issued_date"] == date.today(),
                tire)
        h.tires_select(tire_id)
        row = next(i for i, t in app.tires_rows.items() if t["id"] == tire_id)
        h.check("в таблице - «Выдано»", app.tires_tree.set(row, "status") == app.tr("tires.status_issued"))
        app.return_selected_tires()
        tire = app.db.get_tire_storage_by_id(tire_id)
        h.check("«Вернуть на хранение» - снова на хранении, дата выдачи стёрта",
                tire["status"] == "stored" and tire["issued_date"] is None, tire)
    else:
        h.check("комплект виден в таблице", False)

    summer = h.tire(notes="Тест шины летние")
    if summer and h.tires_select(summer["id"]):
        app.delete_selected_tires()
        h.check("удалить - комплекта нет", app.db.get_tire_storage_by_id(summer["id"]) is None)


def test_tires_filters(h):
    """Шины: «Срок истёк» - на хранении и «хранить до» прошло (красным, своя фишка); фильтр по статусу и сезону;
    поиск по размеру, ячейке, госномеру и телефону"""
    app = h.app
    h.tires_form("т151тт799", "Kia", "Rio", "9000000151", "Тест Шины Два", season="summer", size="185/65 R15",
                 location="Г-1", notes="Тест шины просрочены")
    old = h.tire(notes="Тест шины просрочены")
    if not h.check("комплект сохранён", old):
        return
    h.q("UPDATE tire_storage SET received_date = %s, store_until = %s WHERE id = %s",
        (date.today() - timedelta(days=200), date.today() - timedelta(days=10), old["id"]))
    h.tires_select(old["id"])
    row = next(i for i, t in app.tires_rows.items() if t["id"] == old["id"])
    h.check("срок прошёл - «Срок истёк»", app.tires_tree.set(row, "status") == app.tr("tires.status_overdue")
            and "overdue" in app.tires_tree.item(row, "tags"))
    app.tires_status_filter = "overdue"
    app.refresh_tires()
    ids = {t["id"] for t in app.tires_rows.values()}
    h.check("фишка «Срок истёк» - только просроченные", old["id"] in ids
            and all(app.tires_tree.set(i, "status") == app.tr("tires.status_overdue") for i in app.tires_tree.get_children()))
    app.tires_status_filter = "stored"
    app.refresh_tires()
    h.check("«На хранении» - вместе с просроченными", old["id"] in {t["id"] for t in app.tires_rows.values()})
    app.tires_status_filter = "all"
    app.tires_season_filter = "winter"
    app.refresh_tires()
    h.check("сезон «Зимние» - летних нет", old["id"] not in {t["id"] for t in app.tires_rows.values()}
            and all(t["season"] == "winter" for t in app.tires_rows.values()))
    app.tires_season_filter = None
    for text in ("185/65", "г-1", "т151тт", "000000151"):
        app.tires_search_entry.delete(0, "end")
        app.tires_search_entry.insert(0, text)
        app.refresh_tires()
        h.check(f"поиск «{text}» находит комплект", old["id"] in {t["id"] for t in app.tires_rows.values()})
    app.clear_tires_search()


def test_tires_transfer(h):
    """«Перенести из запчастей»: в списке - позиции, похожие на шины (не в наряде); явно шины отмечены сразу,
    «колёса» и заказ «в пути» - нет; перенесённые - во вкладке «Шины» (сезон, размер, диски, оплата, машина,
    название в примечании), из запчастей убраны; неотмеченные остались"""
    app, db = h.app, h.app.db
    h.warehouse_form("т152тт799", "Kia", "Rio", "9000000152", "Тест Перенос", part="Тест шины зимние 205/55 R16 на дисках",
                     qty="4", price="2000", paid=True)
    h.warehouse_form("Т152ТТ799", part="Тест колёса летние", qty="4", price="1000")
    h.warehouse_form("Т152ТТ799", part="Тест резина в заказе", qty="4", price="9000")
    h.warehouse_form("Т152ТТ799", part="Тест колодки шинные нет", qty="1", price="100")
    h.warehouse_form("Т152ТТ799", part="Тест колодки передние", qty="1", price="100")
    strong, weak, ordered = (h.warehouse_part(n) for n in ("Тест шины зимние 205/55 R16 на дисках", "Тест колёса летние",
                                                           "Тест резина в заказе"))
    for part in (strong, weak):
        h.warehouse_set_status(part[0], "на складе")
    h.warehouse_set_status(strong[0], "выдано")
    h.warehouse_set_status(strong[0], "на складе")   # «выдано» → «на складе» (вопрос - «да»)

    app.switch_tab("warehouse")
    app.warehouse_show_page("tires")
    h.check("кнопка «перенести» видна", app.tires_transfer_btn.winfo_manager() == "pack")
    app.open_tire_transfer()
    h.root.update()
    window = app._tire_transfer_window
    boxes = {b.cget("text"): b for b in h.find_widgets(window, h.m.ctk.CTkCheckBox)}
    find = lambda name: next((b for text, b in boxes.items() if text.startswith(name)), None)
    h.check("в списке: шины, колёса, резина в заказе; колодок нет",
            find("Тест шины зимние") and find("Тест колёса летние") and find("Тест резина в заказе")
            and not find("Тест колодки передние"), list(boxes))
    h.check("явно шины - отмечены", find("Тест шины зимние").get() == 1)
    h.check("«колёса» и заказ «в пути» - не отмечены", find("Тест колёса летние").get() == 0
            and find("Тест резина в заказе").get() == 0)
    find("Тест колёса летние").select()
    for box in boxes.values():   # чужие (не тестовые) позиции не трогаем
        if not box.cget("text").startswith("Тест "):
            box.deselect()
    h.find_button(window, app.tr("tires.transfer_do")).invoke()
    h.root.update()

    moved = h.tire(from_part_id=strong[0])
    h.check("шины перенесены: зимние, размер, с дисками, 4 шт., оплачено, машина, название в примечании",
            moved and (moved["season"], moved["tire_size"], moved["with_rims"], moved["quantity"], moved["is_paid"],
                       moved["car_number"], moved["status"]) == ("winter", "205/55 R16", True, 4, True, "Т152ТТ799",
                                                                 "stored")
            and "Тест шины зимние" in moved["notes"] and float(moved["price"]) == 2000, moved)
    wheels = h.tire(from_part_id=weak[0])
    h.check("отмеченные «колёса» - тоже перенесены (летние)", wheels and wheels["season"] == "summer")
    h.check("перенесённые убраны из запчастей", not h.warehouse_part("Тест шины зимние 205/55 R16 на дисках")
            and not h.warehouse_part("Тест колёса летние"))
    h.check("неотмеченные остались в запчастях", h.warehouse_part("Тест резина в заказе")
            and h.warehouse_part("Тест колодки передние"))
    h.check("окно закрыто", not app._tire_transfer_window)


def test_tires_hint_soon_receipt(h):
    """Шины на хранении: при поиске машины по госномеру (одном на все формы) - вторая строка «🛞 На хранении: ...»
    в «Добавить работу» и на складе; выдали - подсказки нет. «Хранить до» через 5 дней - «Скоро срок»
    (своя фишка, входит в «На хранении»); колонка телефона. Расписка - PDF с клиентом, шинами, ячейкой, ценой"""
    import os, tempfile
    from reportlab import platypus
    app, db = h.app, h.app.db
    h.tires_form("т153тт799", "Kia", "Rio", "9000000153", "Тест Шины Подсказка", season="winter", size="225/45 R18",
                 location="Д-4", price="2500", paid=True, notes="Тест шины подсказка",
                 until=(date.today() + timedelta(days=5)).strftime("%d.%m.%Y"))
    tire = h.tire(notes="Тест шины подсказка")
    if not h.check("комплект сохранён", tire):
        return
    hint = app.tr("tires.hint_stored", sets="").strip()
    text = app.find_car_by_plate("Т153ТТ799")["text"]
    h.check("поиск машины: вторая строка - шины на хранении (сезон, размер, ячейка)",
            hint in text and "225/45 R18" in text and "Д-4" in text and text.count("\n") == 1, text)
    shown = lambda: (app.works_tires_label.winfo_ismapped() and hint in app.works_tires_label.cget("text")
                     and "225/45 R18" in app.works_tires_label.cget("text"))
    h.works_form("Т153ТТ799", master=None, save=False)
    h.root.update()
    h.check("«Добавить работу», вписали госномер: строка про шины видна", shown(), app.works_tires_label.cget("text"))
    h.check("и не повторяется в строке «машина найдена»", hint not in (app.works_lookup_text or ""))
    app.clear_work_form()
    h.root.update()
    h.check("очистили форму - строки про шины нет", not app.works_tires_label.winfo_ismapped())

    # Клиент записан - работу начинают из записи: выбор записи в списке и «Записи» → «Редактировать наряд»
    h.booking_form("Т153ТТ799", None, None, None, None, day=date.today() + timedelta(days=1))
    booking = h.q("SELECT b.id FROM bookings b JOIN client_cars cc ON cc.id = b.car_id "
                  "WHERE cc.car_number = 'Т153ТТ799' ORDER BY b.id DESC LIMIT 1")
    if h.check("запись сохранена", booking):
        booking_id = booking[0][0]
        app.switch_tab("works")
        app.clear_work_form()
        app.refresh_bookings_combo()
        choice = next((text for text, info in app.bookings_data.items() if info["id"] == booking_id), None)
        if choice:
            app.booking_combo.set(choice)
            app.on_booking_select(choice)
            h.root.update()
            h.check("«Добавить работу», выбрали запись: строка про шины видна", shown(),
                    app.works_tires_label.cget("text"))
            app.clear_work_form()
        app.switch_tab("bookings")
        app.bookings_show_all_time = True
        app.refresh_bookings()
        item = next((i for i in app.bookings_tree.get_children()
                     if str(app.bookings_tree.item(i, "values")[0]) == str(booking_id)), None)
        if h.check("запись есть в «Записях»", item):
            app.bookings_tree.selection_set(item)
            app.edit_booking_in_add_work()
            h.root.update()
            h.check("«Записи» → «Редактировать наряд»: строка про шины видна", shown(),
                    app.works_tires_label.cget("text"))
            app.clear_work_form()
        app.bookings_show_all_time = False
    app.switch_tab("warehouse")
    app.show_add_part_form()
    h.wait(300)
    app.fill_wh_car_number("Т153ТТ799")
    h.check("склад: подсказка про шины", hint in app.wh_car_info_label.cget("text"), app.wh_car_info_label.cget("text"))
    app.hide_add_part_form()

    # «Скоро срок» и телефон
    h.tires_select(tire["id"])
    row = next(i for i, t in app.tires_rows.items() if t["id"] == tire["id"])
    h.check("срок через 5 дней - «Скоро срок»", app.tires_tree.set(row, "status") == app.tr("tires.status_soon"))
    h.check("колонка телефона", app.tires_tree.set(row, "phone") == app.display_phone("+79000000153"),
            app.tires_tree.set(row, "phone"))
    app.tires_status_filter = "soon"
    app.refresh_tires()
    h.check("фишка «Скоро срок» - комплект в списке", tire["id"] in {t["id"] for t in app.tires_rows.values()})
    app.tires_status_filter = "stored"
    app.refresh_tires()
    h.check("«На хранении» - вместе со «скоро срок»", tire["id"] in {t["id"] for t in app.tires_rows.values()})
    app.tires_status_filter = "all"

    # Расписка
    folder = tempfile.mkdtemp(prefix="alexan_test_receipt_")
    path = os.path.join(folder, "receipt.pdf")
    captured, real_save, real_build = [], h.m.filedialog.asksaveasfilename, platypus.SimpleDocTemplate.build

    def walk(item):
        if isinstance(item, platypus.Paragraph):
            captured.append(item.getPlainText())
        elif isinstance(item, platypus.Table):
            for cells in item._cellvalues:
                for cell in cells:
                    walk(cell) if not isinstance(cell, str) else captured.append(cell)
        elif isinstance(item, (list, tuple)):
            for x in item:
                walk(x)

    def build(doc, flowables, *a, **kw):
        walk(flowables)
        return real_build(doc, flowables, *a, **kw)
    h.m.filedialog.asksaveasfilename = lambda **kw: path
    platypus.SimpleDocTemplate.build = build
    try:
        h.tires_select(tire["id"])
        n = len(h.dialogs)
        app.save_selected_tire_receipt()
    finally:
        h.m.filedialog.asksaveasfilename = real_save
        platypus.SimpleDocTemplate.build = real_build
    ok_file = os.path.exists(path) and open(path, "rb").read(5) == b"%PDF-"
    h.check("расписка: PDF создан, «сохранена» показано",
            ok_file and any(d[0] == "showinfo" and path in d[2] for d in h.dialogs_since(n)), h.dialogs_since(n))
    joined = " | ".join(captured)
    h.check("расписка: номер, клиент, госномер, размер, ячейка, цена, подписи",
            all(x in joined for x in (app.tr("tires.receipt_title", number=tire["id"]), "Тест Шины Подсказка",
                                      "Т153ТТ799", "225/45 R18", "Д-4", app.format_currency(2500),
                                      app.tr("tires.receipt_handed"))), joined[:400])

    # Выдали - подсказки нет
    h.tires_select(tire["id"])
    app.issue_selected_tires()
    h.check("выдали - при поиске машины подсказки про шины нет", hint not in app.find_car_by_plate("Т153ТТ799")["text"])


def test_booking_with_master(h):
    """«Записать клиента»: запись к мастеру - мастер сохраняется; на это время он помечен «занят» и недоступен,
    другой мастер на то же время - можно; мастер виден в «Записях», в подсказке времени и подставляется
    в «Добавить работу»"""
    app, db = h.app, h.app.db
    master_a, master_b = "Тест Мастер Записи А", "Тест Мастер Записи Б"
    for name in (master_a, master_b):
        db.add_worker(name)
    id_a = h.q("SELECT id FROM workers WHERE full_name = %s", (master_a,))[0][0]
    day = date.today() + timedelta(days=1)
    slot = h.m.booking_time_slots()[-1]

    h.booking_form("т148тт799", "Kia", "Rio", "9000000148", "Тест Мастер Один", day=day, time=slot, master=master_a)
    row = h.q("SELECT b.id, b.worker_id FROM bookings b JOIN client_cars cc ON cc.id = b.car_id "
              "WHERE cc.car_number = 'Т148ТТ799'")
    if not h.check("запись сохранена с мастером А", row and row[0][1] == id_a, row):
        return
    booking_id = row[0][0]

    # Снова открыли форму на это время: А - «занят» и недоступен, Б - свободен
    bw = app._ensure_booking_window()
    bw["open"]()
    h.wait(300)
    try:
        from tkcalendar import DateEntry
        calendar = h.find_widgets(bw["window"], DateEntry)[0]
        calendar.set_date(day)
        calendar.event_generate("<<DateEntrySelected>>")
        h.root.update()
        h.find_button(bw["window"], slot).invoke()
        h.root.update()
        btn_a = h.booking_master_button(bw["window"], master_a)
        btn_b = h.booking_master_button(bw["window"], master_b)
        h.check("мастер А на это время - «занят», кнопка недоступна",
                btn_a.cget("text") == app.tr("bookings.master_busy_suffix", name=master_a)
                and str(btn_a.cget("state")) == "disabled", (btn_a.cget("text"), btn_a.cget("state")))
        h.check("мастер Б свободен", btn_b.cget("text") == master_b and str(btn_b.cget("state")) == "normal")
        h.check("кнопка «Любой» есть", any(b.cget("text") == app.tr("bookings.master_any")
                                         for b in h.find_widgets(bw["window"], h.m.ctk.CTkButton)))
    finally:
        bw["window"].withdraw(); bw["overlay"].withdraw(); bw["window"].grab_release()

    by_time = db.get_bookings_by_date(day).get(slot, [])
    h.check("в подсказке времени - мастер записи",
            any(b["worker_id"] == id_a and b["worker_name"] == master_a for b in by_time), by_time)

    # Другая машина на то же время к мастеру Б - записывается
    h.booking_form("т149тт799", "Kia", "Rio", "9000000149", "Тест Мастер Два", day=day, time=slot, master=master_b)
    row_b = h.q("SELECT w.full_name FROM bookings b JOIN client_cars cc ON cc.id = b.car_id "
                "JOIN workers w ON w.id = b.worker_id WHERE cc.car_number = 'Т149ТТ799'")
    h.check("к мастеру Б на то же время - записано", row_b and row_b[0][0] == master_b, row_b)

    # «Записи»: колонка «Мастер»
    app.switch_tab("bookings")
    app.refresh_bookings()
    tree = app.bookings_tree
    item = next((i for i in tree.get_children() if str(tree.item(i, "values")[0]) == str(booking_id)), None)
    h.check("в «Записях» в колонке «Мастер» - мастер А",
            item and tree.set(item, "master") == master_a, item and tree.item(item, "values"))

    # «Начать работу»: мастер записи подставлен в «Добавить работу»
    app.switch_tab("works")
    app.clear_work_form()
    app.refresh_bookings_combo()
    choice = next((text for text, info in app.bookings_data.items() if info["id"] == booking_id), None)
    if h.check("запись есть в списке «Добавить работу»", choice):
        app.booking_combo.set(choice)
        app.on_booking_select(choice)
        h.root.update()
        h.check("мастер записи подставлен в «Добавить работу»", app.workers_data.get(app.worker_combo.get()) == id_a,
                app.worker_combo.get())
        app.clear_work_form()

    # «Записи» → «Редактировать наряд» (наряда ещё нет): мастер записи тоже подставлен
    app.switch_tab("bookings")
    app.refresh_bookings()
    item = next((i for i in tree.get_children() if str(tree.item(i, "values")[0]) == str(booking_id)), None)
    if h.check("запись есть в «Записях»", item):
        tree.selection_set(item)
        app.edit_booking_in_add_work()
        h.root.update()
        h.check("«Редактировать наряд»: мастер записи подставлен в «Добавить работу»",
                app.workers_data.get(app.worker_combo.get()) == id_a, app.worker_combo.get())
        app.clear_work_form()


def test_period_follows_new_day(h):
    """«Отчёты», «Статистика»: программа открыта через полночь - даты «только сегодня» сами переходят
    на новый день, открытая вкладка пересчитывается; период, открытый паролем, не меняется"""
    app = h.app
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    def set_dates(tab, day):
        for entry in app.period_locks[tab]["entries"]:
            state = str(entry.cget("state"))
            entry.configure(state="normal")
            entry.set_date(day)
            entry.configure(state=state)

    def dates(tab):
        return [e.get_date() for e in app.period_locks[tab]["entries"]]

    app.switch_tab("reports")
    h.check("таймер смены дня запущен", getattr(app, "_watched_day", None) == today)
    h.check("в тот же день ничего не меняется", app.on_day_changed(today) is False)
    stats_lock = app.period_locks["statistics"]
    try:
        # «Вчера» программу открыли: на закрытых вкладках вчерашняя дата; в «Статистике» период открыт паролем
        set_dates("reports", yesterday)
        app.report_date_from = None
        stats_lock["unlocked"] = True
        for entry in stats_lock["entries"]:
            entry.configure(state="normal")
        set_dates("statistics", week_ago)
        app._watched_day = yesterday
        changed = app.on_day_changed()
        h.check("новый день замечен", changed is True and app._watched_day == today)
        h.check("«Отчёты»: обе даты - сегодня", dates("reports") == [today, today], dates("reports"))
        h.check("«Отчёты» (открытая вкладка) пересчитаны за сегодня",
                app.report_date_from == today.strftime("%Y-%m-%d"), app.report_date_from)
        h.check("«Отчёты»: даты по-прежнему закрыты паролем",
                all(str(e.cget("state")) == "disabled" for e in app.period_locks["reports"]["entries"]))
        h.check("«Статистика»: период, открытый паролем, не тронут",
                stats_lock["unlocked"] and dates("statistics") == [week_ago, week_ago], dates("statistics"))
        # Та же смена дня, когда «Статистика» закрыта паролем, - её даты тоже на сегодня
        app.lock_period("statistics")
        set_dates("statistics", yesterday)
        app._watched_day = yesterday
        app.on_day_changed()
        h.check("«Статистика» (закрыта паролем): даты - сегодня", dates("statistics") == [today, today],
                dates("statistics"))
    finally:
        app._watched_day = today
        app.lock_period("statistics")
        app.lock_period("reports")


def test_booking_slot_tooltip(h):
    """«Записать клиента»: наведение на время, где есть запись, - подсказка поверх окна записи (раньше
    пряталась под ним): кто записан, машина и что делать (примечание)"""
    import ctypes
    from tkcalendar import DateEntry
    app, db = h.app, h.app.db

    def all_widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from all_widgets(child)

    day = date.today() + timedelta(days=1)
    client = db.get_or_create_client(full_name="Тест Подсказка", phone="+79000000147")
    car = db.get_or_create_car(client, "Kia", "Rio", "Т147ТТ799")
    slot = h.m.booking_time_slots()[-1]
    db.add_booking(day, slot, client, car, notes="Тест замена масла")
    app.show_add_booking_window()
    window = app._booking_window["window"]
    try:
        for _ in range(10):
            h.root.update()
        date_entry = next(w for w in all_widgets(window) if isinstance(w, DateEntry))
        date_entry.set_date(day)
        date_entry.event_generate("<<DateEntrySelected>>")
        h.root.update()
        btn = next(w for w in all_widgets(window)
                   if isinstance(w, h.m.ctk.CTkButton) and w.cget("text") == slot)
        btn._canvas.event_generate("<Enter>", x=5, y=5)
        for _ in range(5):
            h.root.update()
        tips = [w for w in window.winfo_children() if w.winfo_class() == "Toplevel" and w.winfo_ismapped()]
        if not h.check("подсказка появилась", tips, tips):
            return
        tip = tips[-1]
        texts = " | ".join(w.cget("text") for w in all_widgets(tip) if w.winfo_class() == "Label")
        h.check("в подсказке клиент, машина и примечание",
                "Тест Подсказка" in texts and "Т147ТТ799" in texts and "Тест замена масла" in texts, texts)

        class Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        user32 = ctypes.windll.user32
        at_point = user32.GetAncestor(user32.WindowFromPoint(Point(tip.winfo_rootx() + 5, tip.winfo_rooty() + 5)), 2)
        title = ctypes.create_unicode_buffer(200)
        user32.GetWindowTextW(at_point, title, 200)
        h.check("подсказка видна поверх окна записи", at_point == user32.GetAncestor(tip.winfo_id(), 2),
                (tip.winfo_geometry(), "в этой точке окно:", title.value, window.winfo_geometry()))
    finally:
        window.tk.eval(window.protocol("WM_DELETE_WINDOW"))
        h.root.update()


TESTS = [test_booking_new_car_latin, test_booking_same_car_same_time, test_booking_region_continues,
         test_booking_pick_car_clears_error, test_warehouse_pick_car, test_work_pick_car,
         test_work_from_booking, test_work_new_car, test_work_brand_from_catalog, test_car_hints_same_everywhere,
         test_work_mileage_digits_only, test_work_mileage_less_than_last,
         test_work_merge_keeps_mileage_vin, test_input_rules_boundaries, test_boundaries_in_forms,
         test_work_opens_active_record, test_plate_hint_all_forms,
         test_warehouse_existing_car, test_warehouse_new_car, test_edit_data, test_delete_booking_with_work,
         test_positions, test_finance_category_follows_switch, test_users_and_roles,
         test_locales, test_login, test_bookings_no_phone_red, test_bookings_row_colors, test_bookings_middle_click_scroll, test_tables_middle_click_scroll,
         test_tires_rules, test_tires_accept, test_tires_edit_issue, test_tires_filters, test_tires_transfer, test_tires_hint_soon_receipt,
         test_booking_slot_tooltip, test_period_follows_new_day, test_booking_with_master]
