# -*- coding: utf-8 -*-
"""Позитивные проверки: формы сохраняют то, что нужно, туда, куда нужно.
Каждая функция test_* получает Harness (h). Тестовые госномера Т1xxТТ799 / Т105ТТ77(7), телефоны +7900000010x"""
from datetime import date, timedelta

PLATES = ["Т101ТТ799", "Т102ТТ799", "Т103ТТ799", "Т104ТТ799", "Т105ТТ77", "Т105ТТ777", "Т106ТТ799", "Т107ТТ799", "Т108ТТ799"]
PHONES = ["+79000000101", "+79000000103", "+79000000104", "+79000000105", "+79000000106", "+79000000107", "+79000000108"]


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
         test_work_from_booking, test_work_new_car, test_work_opens_active_record, test_plate_hint_all_forms,
         test_warehouse_existing_car, test_warehouse_new_car, test_edit_data, test_delete_booking_with_work,
         test_positions, test_finance_category_follows_switch, test_users_and_roles,
         test_locales, test_login, test_bookings_no_phone_red]
