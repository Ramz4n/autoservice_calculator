# -*- coding: utf-8 -*-
"""Негативные проверки: неверный ввод - предупреждение и НИ ОДНОЙ записи в базу (h.expect_rejected).
Тестовые госномера Т2xxТТ799, телефоны +7900000020x"""

from datetime import date, timedelta

PLATES = ["Т201ТТ799", "Т202ТТ799", "Т203ТТ799", "Т204ТТ799", "Т205ТТ799", "Т206ТТ799", "Т207ТТ799", "Т208ТТ799", "Т209ТТ799", "Т210ТТ799", "Т211ТТ799",
          "Т212ТТ799", "Т213ТТ799", "Т214ТТ799", "Т215ТТ799", "Т216ТТ799", "Т217ТТ799", "Т218ТТ799", "Т219ТТ799"]
PHONES = ["+79000000201", "+79000000202", "+79000000203", "+79000000204", "+79000000205", "+79000000206", "+79000000207",
          "+79000000208", "+79000000209", "+79000000210", "+79000000211",
          "+79000000213", "+79000000214", "+79000000215", "+79000000216", "+79000000217", "+79000000218", "+79000000219"]


def prepare(h):
    h.require_free(PLATES, PHONES)


def test_booking_rejects(h):
    """«Записать клиента»"""
    def booking(**changes):
        data = dict(plate="Т201ТТ799", brand="Kia", model="Rio", phone10="9000000201", name="Тест Негатив")
        data.update(changes)
        return lambda: h.booking_form(**data)

    h.expect_rejected("пустой госномер", booking(plate=""), "госномер")
    h.expect_rejected("новая машина без марки", booking(brand=""), "марку")
    h.expect_rejected("новая машина без модели", booking(model=""), "модель")
    h.expect_rejected("марка не из справочника", booking(brand="Несуществующая Марка", to_catalog=False),
                      "нет в списке")
    h.expect_rejected("модель не из справочника", booking(model="Несуществующая", to_catalog=False), "нет модели")
    h.expect_rejected("неполный телефон", booking(phone10="90000"), "+7")
    h.expect_rejected("без телефона", booking(phone10=""), "+7")
    h.expect_rejected("без имени", booking(name=""), "имя")
    h.expect_rejected("госномер без первой буквы, ответ «Нет»", booking(plate="201тт799"),
                      "пропущена первая буква", answers=[False])
    h.expect_rejected("буква Г в госномере, ответ «Нет»", booking(plate="т201гг799"), "не бывает", answers=[False])
    h.expect_rejected("госномер не по образцу, ответ «Нет»", booking(plate="т2011тт799"), "не похож", answers=[False])
    h.expect_rejected("своё время «25:00»", booking(custom_time="25:00"), "ЧЧ:ММ")
    h.expect_rejected("своё время «11:75»", booking(custom_time="11:75"), "ЧЧ:ММ")
    h.expect_rejected("своё время не дописано «11:3»", booking(custom_time="113"), "ЧЧ:ММ")
    h.expect_rejected("своё время сегодня уже прошло", booking(custom_time="00:00", day=date.today()), "уже прошло")
    h.expect_rejected("VIN короче 17, ответ «Нет»", booking(vin="TESTVIN0201"), "не полностью", answers=[False])
    # VIN уже у другой машины - не записываем (иначе две машины с одним VIN)
    other_id = h.app.db.get_or_create_car(None, "Kia", "Rio", "Т212ТТ799")
    h.app.db.set_car_vin(other_id, "TESTVIN0000000212")
    h.expect_rejected("VIN уже у другой машины", booking(vin="testvin0000000212"), "уже есть в базе")
    h.check("у другой машины VIN не тронут, Т201 не создана",
            h.q("SELECT vin FROM client_cars WHERE id = %s", (other_id,))[0][0] == "TESTVIN0000000212"
            and not h.car("Т201ТТ799"))


def test_works_rejects(h):
    """«Добавить работу»"""
    def works(**changes):
        data = dict(plate="т202тт799", brand="Hyundai", model="Solaris", phone10="9000000202", name="Тест Работа",
                    items=[("Тест работа", 1000)])
        data.update(changes)
        return lambda: h.works_form(**data)

    h.expect_rejected("без мастера", works(master=False), "мастер")
    h.expect_rejected("без работ", works(items=()), "работ")
    h.expect_rejected("без марки", works(brand=""), "марку")
    h.expect_rejected("без модели", works(model=""), "модель")
    h.expect_rejected("марка не из справочника", works(brand="Несуществующая Марка", to_catalog=False),
                      "нет в списке")
    h.expect_rejected("модель не из справочника", works(model="Несуществующая", to_catalog=False), "нет модели")

    def works_with_mileage(value):
        def action():
            # Мимо клавиатуры (вставка программой / старые данные) - фильтр поля не срабатывает, ловит проверка
            data = dict(plate="т202тт799", brand="Hyundai", model="Solaris", phone10="9000000202", name="Тест Работа",
                        items=[("Тест работа", 1000)], save=False)
            h.works_form(**data)
            h.app.mileage_entry.delete(0, "end"); h.app.mileage_entry.insert(0, value)
            h.app.add_work()
        return action

    h.expect_rejected("пробег буквами", works_with_mileage("абв"), "только цифры")
    h.expect_rejected("пробег с буквами", works_with_mileage("12тыс"), "только цифры")
    h.expect_rejected("пробег длиннее 7 цифр", works_with_mileage("123456789"), "только цифры")

    # Пробег меньше прошлого, ответ «Нет» - ни работы, ни нового пробега у машины
    db = h.app.db
    client = db.get_or_create_client(full_name="Тест Пробег Нет", phone="+79000000206")
    car = db.get_or_create_car(client, "Kia", "Rio", "Т206ТТ799")
    master = h.q("SELECT id FROM workers LIMIT 1")[0][0]
    db.add_work(master, "Тест пробег прошлый", 500, date.today().strftime("%Y-%m-%d"), "123", car_id=car,
                client_id=client)

    def less_mileage():
        h.works_form("т206тт799", "Kia", "Rio", "9000000206", "Тест Пробег Нет", items=[("Тест пробег меньше", 500)],
                     save=False)
        h.app.mileage_entry.delete(0, "end"); h.app.mileage_entry.insert(0, "12")
        h.app.add_work()

    h.expect_rejected("пробег меньше прошлого (123 → 12), ответ «Нет»", less_mileage, "последний пробег",
                      answers=[False])

    def mileage_122():
        h.works_form("т206тт799", "Kia", "Rio", "9000000206", "Тест Пробег Нет", items=[("Тест пробег меньше", 500)],
                     save=False)
        h.app.mileage_entry.delete(0, "end"); h.app.mileage_entry.insert(0, "122")
        h.app.add_work()

    h.expect_rejected("пробег на 1 меньше прошлого (123 → 122), ответ «Нет»", mileage_122, "последний пробег",
                      answers=[False])
    h.check("пробег у машины остался 123",
            str(h.q("SELECT mileage FROM client_cars WHERE id = %s", (car,))[0][0]) == "123")
    h.expect_rejected("без госномера", works(plate=""), "госномер")
    h.expect_rejected("госномер без первой буквы, ответ «Нет»", works(plate="202тт799"), "пропущена первая буква",
                      answers=[False])

    app = h.app
    app.clear_work_form()
    # Классы: ноль, минус, буквы, nan/inf, экспонента; границы: 0,001 (округляется до 0), 100 000 000 (> MONEY_MAX)
    for price in ("0", "abc", "-5", "0,001", "0.004", "nan", "inf", "1e5", "100000000", "99999999.996"):
        before = len(h.dialogs)
        h.add_work_item("Тест цена " + price, price)
        h.check(f"работа с ценой «{price}» не добавляется", not app.works_list and
                any(d[0] == "showwarning" for d in h.dialogs_since(before)), app.works_list)
    h.add_work_item("Тест дубль", 100)
    before = len(h.dialogs)
    h.add_work_item("тест  ДУБЛЬ", 200)
    h.check("одна работа дважды не добавляется (регистр, пробелы)", len(app.works_list) == 1 and
            any(d[0] == "showwarning" for d in h.dialogs_since(before)), app.works_list)
    before = len(h.dialogs)
    h.add_work_item("", 100)
    h.check("работа без названия не добавляется", len(app.works_list) == 1 and
            any(d[0] == "showwarning" for d in h.dialogs_since(before)))
    # Поле запчасти в «Добавить работу» - те же правила, что у работы
    for price in ("0", "0,001", "nan", "100000000"):
        app.part_name_entry.delete(0, "end"); app.part_name_entry.insert(0, "Тест деталь " + price)
        app.part_price_entry.delete(0, "end"); app.part_price_entry.insert(0, price)
        n = len(app.parts_list)
        before = len(h.dialogs)
        app.add_part_to_list()
        h.check(f"запчасть с ценой «{price}» не добавляется", len(app.parts_list) == n and
                any(d[0] == "showwarning" for d in h.dialogs_since(before)), app.parts_list)
    app.clear_work_form()

    # Границы телефона и VIN, пробег на 1 меньше прошлого
    h.expect_rejected("телефон 9 цифр (граница 10)", works(phone10="900000020"), "+7")
    h.expect_rejected("пустой телефон, ответ «Нет» на «Сохранить без телефона?»", works(phone10=""), "телефон",
                      answers=[False])

    def works_with_vin(vin):
        def action():
            h.works_form(**dict(plate="т202тт799", brand="Hyundai", model="Solaris", phone10="9000000202",
                                name="Тест Работа", items=[("Тест работа", 1000)], save=False))
            h.app.vin_entry.delete(0, "end"); h.app.vin_entry.insert(0, vin)
            h.app.add_work()
        return action

    h.expect_rejected("VIN 16 символов (граница 17), ответ «Нет»", works_with_vin("XTA2110009999888"), "17",
                      answers=[False])


def test_warehouse_rejects(h):
    """Склад → «Добавить запчасть»"""
    def wh(**changes):
        data = dict(plate="т203тт799", brand="Lada", model="Vesta", phone10="9000000203", part="Тест деталь",
                    qty="1", price="500")
        data.update(changes)
        return lambda: h.warehouse_form(**data)

    h.expect_rejected("без названия детали", wh(part=""), "запчаст")
    h.expect_rejected("количество буквами", wh(qty="abc"), "количество")
    h.expect_rejected("цена буквами", wh(price="abc"), "цена")
    # Границы количества (1..9999) и цены (> 0, до 99 999 999,99)
    for qty in ("0", "-1", "10000", "1.5"):
        h.expect_rejected(f"количество «{qty}»", wh(qty=qty), "количество")
    for price in ("0", "-5", "0,001", "nan", "100000000"):
        h.expect_rejected(f"цена «{price}»", wh(price=price), "цена")
    h.expect_rejected("новая машина без марки", wh(brand=""), "марку")
    h.expect_rejected("новая машина без модели", wh(model=""), "модель")
    h.expect_rejected("марка не из справочника", wh(brand="Несуществующая Марка", model="Vesta", to_catalog=False),
                      "нет в списке")
    h.expect_rejected("модель не из справочника", wh(brand="Kia", model="Несуществующая", to_catalog=False),
                      "нет модели")
    h.expect_rejected("новая машина, неполный телефон", wh(phone10="9001"), "телефон")
    h.expect_rejected("госномер без первой буквы, ответ «Нет»", wh(plate="203тт799"), "пропущена первая буква",
                      answers=[False])


def test_warehouse_edit_rejects(h):
    """Склад → «Изменить»: неверное - предупреждение, деталь в базе не изменилась; ничего не выбрано -
    «Выберите запчасть», ничего не меняется и окно не открывается"""
    app = h.app
    h.warehouse_form("т211тт799", "Lada", "Vesta", "9000000211", "Тест Склад Отказ", part="Тест деталь отказа",
                     price="700")
    part = h.warehouse_part("Тест деталь отказа")
    if not h.check("деталь для проверок заказана", part, part):
        return
    part_id = part[0]

    def row():
        return h.q("SELECT part_name, quantity, price, status, notes, is_paid, received_date FROM warehouse_parts "
                   "WHERE id = %s", (part_id,))

    def rejected(label, text, **fields):
        before, n = row(), len(h.dialogs)
        opened = h.warehouse_edit(part_id, **fields)
        new = h.dialogs_since(n)
        h.check("«Изменить», " + label,
                opened and any(d[0] in ("showwarning", "askyesno") and text in d[2].lower() for d in new)
                and not any(d[0] == "showinfo" for d in new) and row() == before, (new, row()))

    rejected("пустое название - не сохранено", "запчаст", name="   ")
    for qty in ("0", "-1", "10000", "1.5", "abc"):
        rejected(f"количество «{qty}» - не сохранено", "количество", qty=qty)
    for price in ("abc", "0", "-5", "nan", "100000000"):
        rejected(f"цена «{price}» - не сохранено", "цена", price=price)
    rejected("статус вписан руками («абв») - не сохранено", "статус", status_text="абв")
    h.warehouse_set_status(part_id, "выдано")
    rejected("«выдано» → «на складе», ответ «Нет» - не сохранено", "вернуть", status="на складе", answers=[False])

    app.switch_tab("warehouse")
    app.refresh_warehouse()
    for label, action in (("«Изменить»", app.edit_warehouse_part), ("«Удалить»", app.delete_warehouse_part),
                          ("«На складе»", lambda: app.update_part_status("на складе")),
                          ("«Выдано»", lambda: app.update_part_status("выдано")),
                          ("«Оплачено»", lambda: app.set_warehouse_part_paid(True)),
                          ("«Перейти к записи»", app.goto_booking_from_warehouse)):
        app.warehouse_tree.selection_remove(app.warehouse_tree.selection())
        before = h.q("SELECT id, status, is_paid FROM warehouse_parts ORDER BY id")
        n = len(h.dialogs)
        opened = h.new_windows(action)
        h.check(f"ничего не выбрано, {label} - «Выберите запчасть», ничего не изменилось",
                not opened and app.current_tab == "warehouse"
                and any(d[0] == "showwarning" and "выберите запчасть" in d[2].lower() for d in h.dialogs_since(n))
                and h.q("SELECT id, status, is_paid FROM warehouse_parts ORDER BY id") == before,
                (h.dialogs_since(n), app.current_tab))


def test_edit_rejects(h):
    """«Изменить данные клиента и машины»: неверное - не сохраняется, машина и клиент как были"""
    db = h.app.db
    c1 = db.get_or_create_client(full_name="Тест Правка", phone="+79000000204")
    c2 = db.get_or_create_client(full_name="Тест Чужой", phone="+79000000205")
    car1 = db.get_or_create_car(c1, "Kia", "Rio", "Т204ТТ799")
    car2 = db.get_or_create_car(c2, "Lada", "Granta", "Т205ТТ799")
    h.q("UPDATE client_cars SET vin = 'XTA21100012345678' WHERE id = %s", (car2,))
    from datetime import date
    booking_id = db.add_booking(date.today(), "10:00", c1, car1)

    def snapshot():
        return (h.q("SELECT car_number, car_brand, car_model, vin FROM client_cars WHERE id = %s", (car1,)),
                h.q("SELECT full_name, phone FROM clients WHERE id = %s", (c1,)))

    before = snapshot()
    for label, changes, text, answers in (
            ("пустой госномер", {0: ""}, "госномер", ()),
            ("пустая марка", {1: ""}, "марку", ()),
            ("пустая модель", {2: ""}, "модель", ()),
            ("марка не из справочника", {1: "Несуществующая Марка"}, "нет в списке", ()),
            ("модель не из справочника", {2: "Rio X"}, "нет модели", ()),
            ("неполный телефон", {5: "90012"}, "+7", ()),
            ("чужой госномер латиницей", {0: "t205tt799"}, "уже есть", ()),
            ("чужой VIN", {3: "XTA21100012345678"}, "уже есть", ()),
            ("госномер без первой буквы, ответ «Нет»", {0: "204тт799"}, "пропущена первая буква", (False,)),
            ("телефон другого клиента, ответ «Нет»", {5: "9000000205"}, "уже есть у клиента", (False,))):
        h.expect_rejected(label, lambda c=changes: h.edit_form(booking_id, c), text, answers)
        h.check(label + ": машина и клиент не изменились", snapshot() == before)


def test_positions_rejects(h):
    """Настройки → Сотрудники"""
    app = h.app
    app.refresh_workers_list()
    first_position = h.positions_before[0][1]

    def add_position(name):
        def action():
            app.position_name_entry.delete(0, "end"); app.position_name_entry.insert(0, name)
            app.add_position()
        return action

    def add_worker(name):
        def action():
            app.worker_name_entry.delete(0, "end"); app.worker_name_entry.insert(0, name)
            app.worker_position_combo.set(first_position)
            app.add_worker()
        return action

    h.expect_rejected("пустое название должности", add_position("   "), "название")
    h.expect_rejected("должность с существующим названием", add_position(first_position), "уже есть")
    h.expect_rejected("сотрудник без ФИО", add_worker(""), "ФИО")
    existing = h.q("SELECT full_name FROM workers WHERE fired_at IS NULL LIMIT 1")
    if existing:
        h.expect_rejected("сотрудник с существующим ФИО", add_worker(existing[0][0]), "уже есть")

    plain = [p for p in h.positions_before if not p[2]]
    if plain:
        h.set_input_answer(first_position)
        app.refresh_positions()
        app.positions_tree.selection_set(str(plain[0][0]))
        h.expect_rejected("переименовать должность в существующее название", app.rename_position, "уже есть")

    # Последняя должность «с машинами»: временно оставляем отметку только у одной (уборка вернёт как было)
    car_positions = [p for p in h.positions_before if p[2]]
    for p in car_positions[1:]:
        h.q("UPDATE positions SET is_master = 0 WHERE id = %s", (p[0],))
    app.refresh_positions()
    app.positions_tree.selection_set(str(car_positions[0][0]))
    h.expect_rejected("последнюю должность «с машинами» не выключить", app.toggle_position_cars, "Хотя бы одна",
                      answers=[True])
    h.check("отметка осталась",
            h.q("SELECT is_master FROM positions WHERE id = %s", (car_positions[0][0],))[0][0] == 1)
    # и не удалить - пустая временная должность «с машинами», у остальных отметки нет
    app.db.add_position("Тест-последняя", True)
    temp_id = h.q("SELECT id FROM positions WHERE name = 'Тест-последняя'")[0][0]
    h.q("UPDATE positions SET is_master = 0 WHERE id <> %s", (temp_id,))
    app.refresh_positions()
    app.positions_tree.selection_set(str(temp_id))
    h.expect_rejected("последнюю (пустую) должность «с машинами» не удалить", app.delete_position, "Хотя бы одна")
    h.check("должность осталась", h.q("SELECT id FROM positions WHERE id = %s", (temp_id,)))
    for pid, _, is_master in h.positions_before:
        h.q("UPDATE positions SET is_master = %s WHERE id = %s", (is_master, pid))


def test_payment_rejects(h):
    """«Отчёты» → «Выписать премию / выплату»: неверная сумма"""
    worker = h.q("SELECT w.full_name FROM workers w JOIN positions p ON p.id = w.position_id ORDER BY w.id LIMIT 1")
    if not h.check("есть сотрудник для проверки", worker):
        return
    name = worker[0][0]
    for amount in ("0", "-100", "abc", "", "0,001", "nan", "100000000"):
        before = h.q("SELECT COUNT(*) FROM expenses")[0][0], h.q("SELECT COUNT(*) FROM worker_bonuses")[0][0]
        h.expect_rejected(f"сумма «{amount}»", lambda a=amount: h.give_bonus(name, a), "сумму")
        after = h.q("SELECT COUNT(*) FROM expenses")[0][0], h.q("SELECT COUNT(*) FROM worker_bonuses")[0][0]
        h.check(f"сумма «{amount}»: ни расхода, ни выплаты", before == after, (before, after))


def test_finance_rejects(h):
    """«Финансы»: неверный ввод - предупреждение, окна даты нет, ни одной записи; удаление без выбора и с ответом «Нет»"""
    app = h.app
    tr = app.tr
    rent = tr("finances.category_rent")

    def count():
        return h.q("SELECT COUNT(*) FROM expenses")[0][0]

    for label, income, category, desc, amount, text in (
            ("расход без описания", False, rent, "", 100, "описание"),
            ("доход без описания", True, tr("finances.income_label"), "", 100, "описание"),
            ("без категории", False, "", "Тест", 100, "категори"),
            ("сумма 0", False, rent, "Тест", "0", "сумму"),
            ("сумма с минусом", False, rent, "Тест", "-50", "сумму"),
            ("сумма буквами", False, rent, "Тест", "abc", "сумму"),
            ("пустая сумма", False, rent, "Тест", "", "сумму"),
            ("сумма 0,001 (округляется до 0)", False, rent, "Тест", "0,001", "сумму"),
            ("сумма nan", False, rent, "Тест", "nan", "сумму"),
            ("сумма 100 000 000 (больше предела)", False, rent, "Тест", "100000000", "сумму")):
        before = count()
        h.expect_rejected(f"«Финансы»: {label}",
                          lambda a=(income, category, desc, amount): h.finance_entry(*a), text)
        h.check(f"«Финансы»: {label} - ни одной записи", count() == before)

    app.switch_tab("expenses")
    app.refresh_expenses()
    app.expenses_tree.selection_set(())
    before = count()
    h.expect_rejected("«Финансы»: удалить без выбора строки", app.delete_expense, "Выберите запись")
    h.check("«Финансы»: без выбора ничего не удалено", count() == before)

    entry_id = h.finance_entry(False, rent, "Тест не удалять", 100)
    if h.check("запись для проверки удаления создана", entry_id):
        h.answers[:] = [False]
        h.delete_expense_in_finances(entry_id)
        h.check("«Финансы»: ответ «Нет» - запись осталась", h.q("SELECT id FROM expenses WHERE id = %s", (entry_id,)))
        h.answers[:] = []
        h.delete_expense_in_finances(entry_id)
    app.is_income_var.set(False)
    app.on_income_switch_changed()
    app.expense_desc_entry.delete(0, "end")
    app.expense_amount_entry.delete(0, "end")


def test_period_rejects(h):
    """«Другой период»: без пароля, неверный пароль, «Отмена» - даты остаются закрыты на сегодня;
    смена пароля с ошибкой - пароль не меняется; дата «С» позже «По» - отчёт не формируется"""
    from datetime import date, timedelta
    app = h.app
    today = date.today()

    def setting():
        return h.q("SELECT value FROM app_settings WHERE name = 'reports_password'")

    h.q("DELETE FROM app_settings WHERE name = 'reports_password'")   # уборка вернёт прежний пароль
    for tab in ("reports", "statistics"):
        before = len(h.dialogs)
        app.toggle_period_lock(tab)
        new = h.dialogs_since(before)
        h.check(f"{tab}: пароль не задан - сообщение «не задан», окна пароля нет, закрыто",
                any("не задан" in d[2] for d in new) and not any(d[0] == "ask_password" for d in new)
                and h.period_locked_ui(tab), new)

    app.db.set_reports_password("тест-верный")
    for tab in ("reports", "statistics"):
        before = len(h.dialogs)
        h.passwords[:] = ["тест-неверный"]
        app.toggle_period_lock(tab)
        h.check(f"{tab}: неверный пароль - ошибка, закрыто",
                any(d[0] == "showerror" and "Неверный" in d[2] for d in h.dialogs_since(before))
                and h.period_locked_ui(tab))
        before = len(h.dialogs)
        h.passwords[:] = [None]
        app.toggle_period_lock(tab)
        h.check(f"{tab}: «Отмена» в окне пароля - без сообщений, закрыто",
                not any(d[0].startswith("show") for d in h.dialogs_since(before)) and h.period_locked_ui(tab))

    stored = setting()
    for label, answers, text in (
            ("неверный текущий пароль", ["тест-неверный"], "Неверный"),
            ("новый и повтор не совпадают", ["тест-верный", "тест-новый", "тест-другой"], "не совпадают"),
            ("пустой новый пароль", ["тест-верный", ""], None),
            ("«Отмена» на повторе", ["тест-верный", "тест-новый", None], None)):
        before = len(h.dialogs)
        h.passwords[:] = answers
        app.change_reports_password()
        new = h.dialogs_since(before)
        warned = text is None or any(d[0] == "showerror" and text in d[2] for d in new)
        h.check(f"смена пароля: {label} - пароль не изменился", warned and setting() == stored
                and not any(d[0] == "showinfo" for d in new), new)

    h.passwords[:] = ["тест-верный"]
    app.toggle_period_lock("reports")
    h.report()
    reported = (app.report_date_from, app.report_date_to)
    h.set_period("reports", today, today - timedelta(days=3))
    before = len(h.dialogs)
    app.generate_report(show_empty_message=False)
    h.check("дата «С» позже «По» - предупреждение, отчёт не пересчитан",
            any(d[0] == "showwarning" and "больше" in d[2] for d in h.dialogs_since(before))
            and (app.report_date_from, app.report_date_to) == reported)
    app.toggle_period_lock("reports")
    h.check("«Отчёты» снова закрыты", h.period_locked_ui("reports"))


def test_bookings_middle_click_nothing_to_scroll(h):
    """«Записи»: всё помещается (прокручивать нечего) - нажатие колеса ничего не включает, значка нет"""
    import types as _types
    app = h.app
    app.switch_tab("bookings")
    tree, auto = app.bookings_tree, app.bookings_autoscroll
    app.bookings_search_entry.delete(0, "end")
    app.bookings_search_entry.insert(0, "нет-такой-записи-zzz")
    try:
        app.refresh_bookings()
        for _ in range(3):
            h.root.update()
        h.check("по поиску ни одной записи", not tree.get_children(), len(tree.get_children()))
        result = auto.start(tree.winfo_rootx() + 100, tree.winfo_rooty() + 60)
        auto.on_press(_types.SimpleNamespace(x_root=tree.winfo_rootx() + 100, y_root=tree.winfo_rooty() + 60))
        h.root.update()
        h.check("прокручивать нечего - прокрутка не включилась, значка нет",
                result is False and not auto.active and auto.marker is None)
        h.check("курсор обычный", str(tree.cget("cursor")) == "", tree.cget("cursor"))
    finally:
        auto.stop()
        app.clear_bookings_search()
        app.refresh_bookings()


def test_tables_middle_click_nothing_to_scroll(h):
    """Таблица или список, где всё помещается, - колесо ничего не включает, значка нет, модальное окно остаётся
    модальным; график расписания, который помещается целиком, - тоже"""
    import tkinter as tk
    from tkinter import ttk
    from autoscroll import MiddleClickAutoscroll
    dialog = tk.Toplevel(h.root)
    dialog.geometry("400x300+50+50")
    tree = ttk.Treeview(dialog, columns=("a",), show="headings", height=5)
    tree.pack()
    tree.insert("", "end", values=("одна строка",))
    listbox = tk.Listbox(dialog, height=5)
    listbox.pack()
    listbox.insert("end", "один пункт")
    try:
        dialog.update()
        dialog.grab_set()
        for widget, name in ((tree, "таблица"), (listbox, "список")):
            widget.event_generate("<ButtonPress-2>", x=10, y=10, rootx=widget.winfo_rootx() + 10,
                                  rooty=widget.winfo_rooty() + 10)
            auto = MiddleClickAutoscroll._instances.get(widget)
            h.check(f"{name}: всё помещается - прокрутка не включилась, значка нет",
                    auto is not None and not auto.active and auto.marker is None)
        h.check("окно осталось модальным", dialog.grab_current() == dialog, dialog.grab_current())
    finally:
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()

    app = h.app
    app.switch_tab("staff")
    app.refresh_staff_tab()
    canvas = app.staff_canvas
    auto = MiddleClickAutoscroll._instances.get(canvas)
    h.root.update()
    canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), canvas.winfo_height()))   # рисунок = окно
    try:
        started = auto.start(canvas.winfo_rootx() + 10, canvas.winfo_rooty() + 10)
        h.check("график помещается целиком - прокрутка не включилась",
                started is False and not auto.active and auto.marker is None, (canvas.xview(), canvas.yview()))
    finally:
        auto.stop()
        app.draw_staff_calendar()
        app.switch_tab("bookings")


def test_tires_rejects(h):
    """«Принять шины»: нет сезона / госномера / марки новой машины, количество 0 и буквы, дата 31.02 и не по образцу,
    «хранить до» раньше приёма, цена 0, слишком длинный размер - предупреждение и ни одной записи (машина тоже
    не создаётся); ячейка занята, ответ «нет» - не сохраняется; выдать неоплаченные, «нет» - не выдано;
    перенос: ничего не отмечено - ничего не перенесено; деталь в наряде - не переносится"""
    app, db = h.app, h.app.db
    good = dict(brand="Kia", model="Rio", phone10="9000000209", name="Тест Шины Отказ", season="winter",
                size="205/55 R16", tire_brand="Nokian", qty="4", received=date.today().strftime("%d.%m.%Y"),
                until="", price="1000")
    cases = [
        ("нет сезона", dict(season=None), "сезон"),
        ("нет госномера", dict(plate=""), None),
        ("новая машина без марки", dict(brand=""), None),
        ("количество 0", dict(qty="0"), None),
        ("количество буквами", dict(qty="четыре"), None),
        ("количество пусто", dict(qty=""), None),
        ("дата 31.02", dict(received="31.02.2026"), "дд.мм"),
        ("дата не по образцу", dict(received="вчера"), "дд.мм"),
        ("дата пустая", dict(received=""), "дд.мм"),
        ("год 1999", dict(received="01.01.1999"), "дд.мм"),
        ("«хранить до» раньше приёма", dict(until=(date.today() - timedelta(days=1)).strftime("%d.%m.%Y")), None),
        ("стоимость 0", dict(price="0"), None),
        ("стоимость буквами", dict(price="много"), None),
        ("размер длиннее 50", dict(size="2" * 51), "50"),
        ("дата приёма завтра", dict(received=(date.today() + timedelta(days=1)).strftime("%d.%m.%Y")), "не позже"),
        ("количество 10000", dict(qty="10000"), "количество"),
        ("количество минус", dict(qty="-1"), "количество"),
        ("количество дробное", dict(qty="1.5"), "количество"),
        ("стоимость минус", dict(price="-5"), "цена"),
        ("стоимость nan", dict(price="nan"), "цена"),
        ("стоимость больше максимума", dict(price="100000000"), "цена"),
        ("марка шин длиннее 100", dict(tire_brand="Б" * 101), "100"),
        ("ячейка длиннее 50", dict(location="Я" * 51), "50"),
        ("радиус «abc»", dict(size="205/55", radius="abc"), "радиус"),
        ("радиус «16.7»", dict(size="205/55", radius="16.7"), "радиус"),
    ]
    for name, change, text in cases:
        fields = dict(good, plate="Т209ТТ799")
        fields.update(change)
        plate = fields.pop("plate")
        h.expect_rejected(f"шины: {name} - отказ, ничего не сохранено",
                          lambda p=plate, f=fields: h.tires_form(p, **f), text)
    h.check("машина Т209ТТ799 не создана (отказ до сохранения)", not h.car("Т209ТТ799"))

    # Нет сезона - кнопки сезона в красной рамке; выбрали сезон - рамка обычная
    h.tires_form("Т209ТТ799", **dict(good, season=None), close=False)
    chips = app.tire_season_switch
    h.check("нет сезона - кнопки сезона в красной рамке",
            all(b.cget("border_color") == chips.ERROR_BORDER for b in chips.buttons.values()))
    chips.set(app.tr("tires.season_summer"))
    h.check("выбрали сезон - красной рамки нет",
            not any(b.cget("border_color") == chips.ERROR_BORDER for b in chips.buttons.values()))
    app.hide_add_part_form()

    # Ширина/профиль, радиус, марка шин - обязательные: нет - предупреждение со списком, ничего не сохранено
    missing_text = app.tr("tires.msg_missing_fields", fields="").split(":")[0]
    for name, change, fields_named in (
            ("нет размера и марки", dict(size="", tire_brand=""), ("width_profile", "radius", "brand")),
            ("нет радиуса", dict(size="205/55", radius=""), ("radius",)),
            ("нет ширины/профиля", dict(size="", radius="R16"), ("width_profile",)),
            ("нет марки шин", dict(tire_brand=""), ("brand",)),
            ("марка шин - одни пробелы", dict(tire_brand="   "), ("brand",))):
        before = len(h.dialogs)
        h.expect_rejected(f"шины: {name} - отказ, ничего не сохранено",
                          lambda f=dict(good, **change): h.tires_form("Т209ТТ799", **f), missing_text)
        warned = next((d[2] for d in h.dialogs[before:] if d[0] == "showwarning"), "")
        listed = warned.split("\n")[0]   # «Не заполнено: «Радиус», «Марка шин».»
        quoted = {k: "«" + app.tr("tires." + k) + "»" for k in ("width_profile", "radius", "brand")}
        h.check(f"{name}: в предупреждении названы именно пустые поля",
                all((quoted[k] in listed) == (k in fields_named) for k in quoted), warned)
    h.check("машина Т209ТТ799 не создана (размер, марка)", not h.car("Т209ТТ799"))

    # Ячейка пустая - вопрос «оставить без ячейки?», «нет» - ничего не сохранено, рамка у поля ячейки
    no_cell = app.tr("tires.msg_no_location").split("—")[0].strip()
    h.expect_rejected("шины: нет ячейки, «нет» - ничего не сохранено",
                      lambda: h.tires_form("Т209ТТ799", **dict(good, location=""), close=False), no_cell,
                      answers=[False])
    h.check("нет ячейки, «нет» - поле ячейки в красной рамке",
            app.tire_location_entry.cget("border_color") == app.FORM_ERROR_BORDER)
    app.hide_add_part_form()
    h.check("машина Т209ТТ799 не создана (ячейка)", not h.car("Т209ТТ799"))

    # Стоимость пустая - вопрос «хранить бесплатно?», «нет» - ничего не сохранено, рамка у стоимости
    no_price = app.tr("tires.msg_no_price").split("—")[0].strip()
    h.expect_rejected("шины: нет стоимости, «нет» - ничего не сохранено",
                      lambda: h.tires_form("Т209ТТ799", **dict(good, location="Ж-9", price=""), close=False),
                      no_price, answers=[False])
    h.check("нет стоимости, «нет» - поле стоимости в красной рамке",
            app.tire_price_entry.cget("border_color") == app.FORM_ERROR_BORDER)
    app.hide_add_part_form()

    # Машина в базе, у владельца нет телефона: «оставить без телефона?» «нет» - ничего; неполный номер - отказ
    h.tires_form("т218тт799", "Kia", "Rio", "9000000218", "Тест Шины Телефон", season="winter",
                 location="Ж-10", price="1000", notes="Тест шины телефон отказ 1")
    car = h.car("Т218ТТ799")
    if h.check("машина Т218ТТ799 создана", car):
        app.db.clear_client_phone(car[1])
        no_phone = app.tr("tires.msg_no_phone").split("—")[0].strip()
        h.expect_rejected("шины: владелец без телефона, поле пустое, «нет» - ничего не сохранено",
                          lambda: h.tires_form("Т218ТТ799", location="Ж-11", price="1000",
                                               notes="Тест шины телефон отказ 2", close=False),
                          no_phone, answers=[False])
        h.check("«нет» - поле телефона в красной рамке",
                app.wh_phone_entry.cget("border_color") == app.FORM_ERROR_BORDER)
        app.hide_add_part_form()
        h.expect_rejected("шины: владелец без телефона, номер неполный - отказ",
                          lambda: h.tires_form("Т218ТТ799", phone10="90000", location="Ж-11", price="1000",
                                               notes="Тест шины телефон отказ 3"), None)
        h.check("телефон владельцу не записан", h.q("SELECT phone FROM clients WHERE id = %s", (car[1],))[0][0]
                is None)

    # Ячейка занята: «нет» - не сохраняется, «да» - сохраняется
    h.tires_form("Т209ТТ799", location="Ж-1", notes="Тест шины ячейка 1", **{k: v for k, v in good.items()})
    first = h.tire(notes="Тест шины ячейка 1")
    if h.check("первый комплект в ячейке Ж-1 сохранён", first and first["location"] == "Ж-1"):
        h.expect_rejected("ячейка Ж-1 занята, ответ «нет» - не сохранено",
                          lambda: h.tires_form("Т209ТТ799", season="summer", location="ж-1", size="205/55 R16",
                                               tire_brand="Nokian", price="1000", notes="Тест шины ячейка 2"), "Ж-1",
                          answers=[False])
        # Неоплаченные - выдать, «нет»: статус не меняется
        db.set_tire_storage_paid(first["id"], False)
        h.tires_select(first["id"])
        h.answers[:] = [False]
        app.issue_selected_tires()
        h.check("выдать неоплаченные, «нет» - не выдано", db.get_tire_storage_by_id(first["id"])["status"] == "stored")
        h.check("был вопрос про неоплаченное хранение", any("не оплачено" in d[2] for d in h.dialogs[-1:]),
                h.dialogs[-1:])
        h.tires_select(first["id"])
        app.issue_selected_tires()   # «да»
        h.tires_select(first["id"])
        before = len(h.dialogs)
        app.issue_selected_tires()   # уже выдано
        h.check("уже выдано - второй раз не выдаётся (сообщение)", db.get_tire_storage_by_id(first["id"])["status"]
                == "issued" and any(app.tr("tires.msg_already_issued") in d[2] for d in h.dialogs[before:]))
        h.answers[:] = [False]
        h.tires_select(first["id"])
        app.delete_selected_tires()
        h.check("удалить, «нет» - комплект остался", db.get_tire_storage_by_id(first["id"]) is not None)

    # Ничего не выбрано в таблице - предупреждение
    app.tires_tree.selection_set(())
    h.expect_rejected("ничего не выбрано - «Выдать» не работает", app.issue_selected_tires, app.tr("tires.msg_select"))
    for label, action in (("«Изменить»", app.edit_selected_tires),
                          ("«Отметить оплату»", lambda: app.set_selected_tires_paid(True)),
                          ("«Снять оплату»", lambda: app.set_selected_tires_paid(False)),
                          ("«Удалить»", app.delete_selected_tires),
                          ("«Расписка»", app.save_selected_tire_receipt)):
        app.tires_tree.selection_set(())
        opened = []
        h.expect_rejected(f"ничего не выбрано - {label} не работает",
                          lambda a=action: opened.extend(h.new_windows(a)), app.tr("tires.msg_select"))
        h.check(f"ничего не выбрано - {label}: окно не открылось", not opened and not app.add_part_form_visible)

    # Перенос: ничего не отмечено - ничего не переносится
    h.warehouse_form("т210тт799", "Kia", "Rio", "9000000210", "Тест Перенос Отказ", part="Тест шины отказ переноса")
    part = h.warehouse_part("Тест шины отказ переноса")
    app.switch_tab("warehouse")
    app.warehouse_show_page("tires")
    app.open_tire_transfer()
    h.root.update()
    window = app._tire_transfer_window
    for box in h.find_widgets(window, h.m.ctk.CTkCheckBox):
        box.deselect()
    h.expect_rejected("перенос: ничего не отмечено - предупреждение, ничего не перенесено",
                      lambda: h.find_button(window, app.tr("tires.transfer_do")).invoke(), app.tr("tires.transfer_choose"))
    for box in h.find_widgets(window, h.m.ctk.CTkCheckBox):
        if box.cget("text").startswith("Тест шины отказ переноса"):
            box.select()
    h.expect_rejected("перенос: «нет» на вопросе - ничего не перенесено",
                      lambda: h.find_button(window, app.tr("tires.transfer_do")).invoke(), None, answers=[False])
    h.find_button(window, app.tr("common.cancel")).invoke()
    h.check("отмена - окно закрыто, деталь в запчастях", not app._tire_transfer_window
            and h.warehouse_part("Тест шины отказ переноса"))
    # Деталь в наряде («установлена») - не переносится и в списке её нет
    h.q("UPDATE warehouse_parts SET status = 'установлена' WHERE id = %s", (part[0],))
    h.check("деталь в наряде - в списке переноса её нет",
            all(p["id"] != part[0] for p in db.get_tire_like_warehouse_parts()))
    h.check("деталь в наряде - перенос отказан, в запчастях осталась",
            db.move_warehouse_part_to_tires(part[0]) is None and h.warehouse_part("Тест шины отказ переноса"))

    # Оплата без цены: в форме - сохраняется, но дохода нет; «Отметить оплату» - предупреждение, дохода нет
    incomes = lambda: h.q("SELECT COUNT(*) FROM expenses WHERE is_income = 1")[0][0]
    before = incomes()
    h.tires_form("Т209ТТ799", season="summer", price="", paid=True, notes="Тест шины без цены")
    no_price = h.tire(notes="Тест шины без цены")
    h.check("оплачено без цены - сохранено, дохода нет", no_price and no_price["income_id"] is None
            and incomes() == before)
    db.set_tire_storage_paid(no_price["id"], False)
    h.tires_select(no_price["id"])
    h.expect_rejected("«Отметить оплату» без цены - предупреждение", lambda: app.set_selected_tires_paid(True),
                      app.tr("tires.msg_paid_no_price"))
    h.check("и дохода нет, комплект не оплачен", incomes() == before
            and not db.get_tire_storage_by_id(no_price["id"])["is_paid"])

    # Расписка: в окне сохранения нажали «Отмена» - ни файла, ни сообщений
    real_save = h.m.filedialog.asksaveasfilename
    h.m.filedialog.asksaveasfilename = lambda **kw: ""
    try:
        n = len(h.dialogs)
        h.tires_select(no_price["id"])
        saved = app.save_selected_tire_receipt()
    finally:
        h.m.filedialog.asksaveasfilename = real_save
    h.check("расписка: отмена - ничего не сохранено, сообщений нет", saved is False and not h.dialogs_since(n))


def test_booking_master_rejects(h):
    """«Записать клиента»: мастер уже записан на это время - отказ, ни одной записи; база тоже не даёт
    записать его второй раз; мастер на выходном в этот день - кнопка недоступна, с пометкой"""
    from datetime import timedelta
    app, db = h.app, h.app.db
    master = "Тест Мастер Занятый"
    db.add_worker(master)
    master_id = h.q("SELECT id FROM workers WHERE full_name = %s", (master,))[0][0]
    day = date.today() + timedelta(days=1)
    slot = h.m.booking_time_slots()[-1]
    client = db.get_or_create_client(full_name="Тест Занятый Мастер", phone="+79000000208")
    car = db.get_or_create_car(client, "Kia", "Rio", "Т208ТТ799")
    db.add_booking(day, slot, client, car, worker_id=master_id)

    h.expect_rejected("мастер уже записан на это время", lambda: h.booking_form(
        "т207тт799", "Kia", "Rio", "9000000207", "Тест Негатив Мастер", day=day, time=slot, master=master),
        "уже записан")
    before = h.q("SELECT COUNT(*) FROM bookings")[0][0]
    again = db.add_booking(day, slot, client, car, worker_id=master_id)
    h.check("база: второй раз к тому же мастеру на то же время - не записывается",
            again is None and h.q("SELECT COUNT(*) FROM bookings")[0][0] == before, again)

    # Выходной в этот день - мастера выбрать нельзя
    day_off = day + timedelta(days=1)
    db.set_worker_day(master_id, day_off, "day_off")
    try:
        bw = app._ensure_booking_window()
        bw["open"]()
        h.wait(300)
        from tkcalendar import DateEntry
        calendar = h.find_widgets(bw["window"], DateEntry)[0]
        calendar.set_date(day_off)
        calendar.event_generate("<<DateEntrySelected>>")
        h.root.update()
        btn = h.booking_master_button(bw["window"], master)
        h.check("мастер на выходном - кнопка недоступна, с пометкой «выходной»",
                str(btn.cget("state")) == "disabled" and btn.cget("text") != master, btn.cget("text"))
    finally:
        bw["window"].withdraw(); bw["overlay"].withdraw(); bw["window"].grab_release()
        db.set_worker_day(master_id, day_off, None)

def test_booking_vin_time_rejects(h):
    """«Записать клиента», VIN и своё время: запись не прошла - VIN машины не меняется; VIN другой машины у
    найденной машины - отказ; своё время ровно «сейчас» - отказ (граница); на своё время мест нет - «Нет» -
    ни одной записи; мастер уже записан на это своё время - отказ"""
    from datetime import datetime, timedelta
    app, db = h.app, h.app.db
    client = db.get_or_create_client(full_name="Тест Вин Отказ", phone="+79000000213")
    car = db.get_or_create_car(client, "Kia", "Rio", "Т213ТТ799")
    db.set_car_vin(car, "TESTVIN0000000213")

    def vin_of(car_id):
        return h.q("SELECT vin FROM client_cars WHERE id = %s", (car_id,))[0][0]

    h.expect_rejected("найденная машина, новый VIN, но время неверное - отказ", lambda: h.booking_form(
        "Т213ТТ799", vin="TESTVIN0000000999", custom_time="25:00"), "ЧЧ:ММ")
    h.check("запись не прошла - VIN машины прежний", vin_of(car) == "TESTVIN0000000213", vin_of(car))
    other = db.get_or_create_car(None, "Kia", "Rio", "Т214ТТ799")
    db.set_car_vin(other, "TESTVIN0000000214")
    h.expect_rejected("найденной машине вписали VIN другой машины - отказ", lambda: h.booking_form(
        "Т213ТТ799", vin="TESTVIN0000000214"), "уже есть в базе")
    h.check("VIN обеих машин не тронут", (vin_of(car), vin_of(other)) == ("TESTVIN0000000213", "TESTVIN0000000214"))

    # Граница «сейчас»: ровно текущая минута - уже прошла
    now = datetime.now().strftime("%H:%M")
    h.expect_rejected(f"своё время ровно сейчас ({now}) - уже прошло", lambda: h.booking_form(
        "Т213ТТ799", custom_time=now, day=date.today()), "уже прошло")

    # Своё время, на которое мест нет: «Нет» - ничего не записано
    day = date.today() + timedelta(days=83)
    cap = db.day_capacity(day)["capacity"]
    if h.check(f"мест на время в {day}: {cap} (1…3)", 1 <= cap <= 3, cap):
        for i, plate in enumerate(("Т215ТТ799", "Т216ТТ799", "Т217ТТ799")[:cap]):
            c = db.get_or_create_client(full_name=f"Тест Место Своё {i}", phone=f"+7900000021{5 + i}")
            db.add_booking(day, "07:05", c, db.get_or_create_car(c, "Kia", "Rio", plate))
        h.expect_rejected("на своё время 07:05 мест нет, «Нет» - не записан", lambda: h.booking_form(
            "Т213ТТ799", custom_time="0705", day=day), "записано машин", answers=[False])

    # Мастер уже записан на это своё время
    master = "Тест Мастер Своё Время"
    db.add_worker(master)
    master_id = h.q("SELECT id FROM workers WHERE full_name = %s", (master,))[0][0]
    busy_day = date.today() + timedelta(days=84)
    db.add_booking(busy_day, "13:15", client, other, worker_id=master_id)
    h.expect_rejected("мастер уже записан на своё время 13:15 - отказ", lambda: h.booking_form(
        "Т213ТТ799", custom_time="1315", day=busy_day, master=master), "уже записан")



def test_work_without_mileage_no(h):
    """«Добавить работу»: пробег не вписали, на вопрос «сохранить без пробега?» - «Нет»: ничего не записано
    (ни наряда, ни машины, ни клиента), курсор в поле пробега, работы в форме остались"""
    app = h.app
    h.mileage_question = True
    focused = []
    real_focus = app.mileage_entry.focus_set
    app.mileage_entry.focus_set = lambda *a: (focused.append(True), real_focus(*a))
    try:
        h.expect_rejected("пробег пустой, «Нет» - ничего не сохранено",
                          lambda: h.works_form("т219тт799", "Kia", "Rio", "9000000219", "Тест Без Пробега Нет",
                                               items=[("Тест работа без пробега нет", 700)]),
                          app.tr("works.ask_save_without_mileage"), answers=[False])
        h.check("машина Т219ТТ799 не создана", not h.car("Т219ТТ799"))
        h.check("курсор поставлен в поле пробега", focused)
        h.check("работы в форме остались", len(app.works_list) == 1, app.works_list)
    finally:
        h.mileage_question = False
        app.mileage_entry.focus_set = real_focus
        app.clear_work_form()


TESTS = [test_booking_rejects, test_works_rejects, test_warehouse_rejects, test_warehouse_edit_rejects,
         test_edit_rejects, test_positions_rejects,
         test_payment_rejects, test_finance_rejects, test_period_rejects, test_booking_master_rejects,
         test_bookings_middle_click_nothing_to_scroll, test_tables_middle_click_nothing_to_scroll, test_tires_rejects,
         test_booking_vin_time_rejects,
         test_work_without_mileage_no]
