# -*- coding: utf-8 -*-
"""Негативные проверки: неверный ввод - предупреждение и НИ ОДНОЙ записи в базу (h.expect_rejected).
Тестовые госномера Т2xxТТ799, телефоны +7900000020x"""

PLATES = ["Т201ТТ799", "Т202ТТ799", "Т203ТТ799", "Т204ТТ799", "Т205ТТ799"]
PHONES = ["+79000000201", "+79000000202", "+79000000203", "+79000000204", "+79000000205"]


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
    h.expect_rejected("неполный телефон", booking(phone10="90000"), "+7")
    h.expect_rejected("без телефона", booking(phone10=""), "+7")
    h.expect_rejected("без имени", booking(name=""), "имя")
    h.expect_rejected("госномер без первой буквы, ответ «Нет»", booking(plate="201тт799"),
                      "пропущена первая буква", answers=[False])
    h.expect_rejected("буква Г в госномере, ответ «Нет»", booking(plate="т201гг799"), "не бывает", answers=[False])
    h.expect_rejected("госномер не по образцу, ответ «Нет»", booking(plate="т2011тт799"), "не похож", answers=[False])


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
    h.expect_rejected("без госномера", works(plate=""), "госномер")
    h.expect_rejected("госномер без первой буквы, ответ «Нет»", works(plate="202тт799"), "пропущена первая буква",
                      answers=[False])

    app = h.app
    app.clear_work_form()
    for price in ("0", "abc", "-5"):
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
    app.clear_work_form()


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
    h.expect_rejected("новая машина без марки", wh(brand=""), "марку")
    h.expect_rejected("новая машина без модели", wh(model=""), "модель")
    h.expect_rejected("новая машина, неполный телефон", wh(phone10="9001"), "телефон")
    h.expect_rejected("госномер без первой буквы, ответ «Нет»", wh(plate="203тт799"), "пропущена первая буква",
                      answers=[False])


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
    existing = h.q("SELECT full_name FROM workers LIMIT 1")
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


TESTS = [test_booking_rejects, test_works_rejects, test_warehouse_rejects, test_edit_rejects, test_positions_rejects]
