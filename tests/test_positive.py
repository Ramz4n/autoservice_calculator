# -*- coding: utf-8 -*-
"""Позитивные проверки: формы сохраняют то, что нужно, туда, куда нужно.
Каждая функция test_* получает Harness (h). Тестовые госномера Т1xxТТ799 / Т105ТТ77(7), телефоны +7900000010x"""
from datetime import date, timedelta

PLATES = ["Т101ТТ799", "Т102ТТ799", "Т103ТТ799", "Т104ТТ799", "Т105ТТ77", "Т105ТТ777", "Т106ТТ799", "Т107ТТ799"]
PHONES = ["+79000000101", "+79000000103", "+79000000104", "+79000000105", "+79000000106", "+79000000107"]


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
    """«Изменить данные»: госномер (латиницей), модель и имя - та же машина и тот же клиент"""
    h.edit_form(h.state["booking1"], {0: "t102tt799", 2: "Rio X", 6: "Тест Один Изменён"})
    car = h.q("SELECT car_number, car_model FROM client_cars WHERE id = %s", (h.state["car1"],))
    h.check("та же машина: Т102ТТ799, Rio X", car and car[0] == ("Т102ТТ799", "Rio X"), car)
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


TESTS = [test_booking_new_car_latin, test_booking_same_car_same_time, test_booking_region_continues,
         test_booking_pick_car_clears_error, test_warehouse_pick_car, test_work_pick_car,
         test_work_from_booking, test_work_new_car, test_work_opens_active_record, test_plate_hint_all_forms,
         test_warehouse_existing_car, test_warehouse_new_car, test_edit_data, test_delete_booking_with_work,
         test_positions, test_finance_category_follows_switch]
