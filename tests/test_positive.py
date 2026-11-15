# -*- coding: utf-8 -*-
"""Позитивные проверки: формы сохраняют то, что нужно, туда, куда нужно.
Каждая функция test_* получает Harness (h). Тестовые госномера Т1xxТТ799 / Т105ТТ77(7), телефоны +7900000010x"""
from datetime import date, timedelta

PLATES = ["Т101ТТ799", "Т102ТТ799", "Т103ТТ799", "Т104ТТ799", "Т105ТТ77", "Т105ТТ777", "Т106ТТ799", "Т107ТТ799", "Т108ТТ799",
          "Т140ТТ799", "Т141ТТ799", "Т142ТТ799", "Т143ТТ799", "Т144ТТ799", "Т145ТТ799", "Т146ТТ799"]
PHONES = ["+79000000101", "+79000000103", "+79000000104", "+79000000105", "+79000000106", "+79000000107", "+79000000108",
          "+79000000140", "+79000000141", "+79000000142", "+79000000143", "+79000000144", "+79000000145", "+79000000146"]


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
    for name in ("autoservice_calculator.py", "login_window.py"):
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
            tree.selection() == (item,) and label.cget("bg") == "#d6e8fb", tree.selection())
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


TESTS = [test_booking_new_car_latin, test_booking_same_car_same_time, test_booking_region_continues,
         test_booking_pick_car_clears_error, test_warehouse_pick_car, test_work_pick_car,
         test_work_from_booking, test_work_new_car, test_work_brand_from_catalog, test_car_hints_same_everywhere,
         test_work_mileage_digits_only, test_work_mileage_less_than_last,
         test_work_merge_keeps_mileage_vin, test_input_rules_boundaries, test_boundaries_in_forms,
         test_work_opens_active_record, test_plate_hint_all_forms,
         test_warehouse_existing_car, test_warehouse_new_car, test_edit_data, test_delete_booking_with_work,
         test_positions, test_finance_category_follows_switch, test_users_and_roles,
         test_locales, test_login, test_bookings_no_phone_red]
