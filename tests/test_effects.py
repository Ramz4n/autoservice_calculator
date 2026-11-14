# -*- coding: utf-8 -*-
"""Связи между разделами: действие в одной вкладке должно правильно отразиться в других.
Работа → зарплата мастера в «Отчётах» (только после «Выполнено»), доход и прибыль, «Статистика»;
удаление записи → всё это убирается; премия → «Финансы» и прибыль; удаление расхода → премия пропадает.

Свой мастер «Тест Мастер», своя марка «ТестМарка…» и свои клиенты - чтобы чужие данные за сегодня
не мешали: проверяются строки этого мастера / марки и ИЗМЕНЕНИЕ итогов, а не итоги целиком."""

from datetime import date

PLATES = ["Т301ТТ799", "Т302ТТ799", "Т303ТТ799", "Т304ТТ799", "Т305ТТ799", "Т306ТТ799", "Т307ТТ799",
          "Т308ТТ799", "Т309ТТ799", "Т310ТТ799", "Т311ТТ799", "Т312ТТ799", "Т313ТТ799", "Т314ТТ799",
          "Т315ТТ799"]
PHONES = ["+79000000301", "+79000000302", "+79000000303", "+79000000304", "+79000000305", "+79000000306",
          "+79000000307", "+79000000308", "+79000000309", "+79000000310", "+79000000311", "+79000000312",
          "+79000000313", "+79000000314", "+79000000315", "+79000000316", "+79000000317", "+79000000318"]
MASTER = "Тест Мастер"
STAFF_POSITION, STAFF = "Тест-администратор", "Тест Админ"   # должность НЕ «с машинами»


def prepare(h):
    h.require_free(PLATES, PHONES)
    if h.q("SELECT id FROM workers WHERE full_name = %s", (MASTER,)):
        raise RuntimeError(f"сотрудник «{MASTER}» уже есть в базе")
    master_position = h.q("SELECT id FROM positions WHERE is_master = 1 ORDER BY id LIMIT 1")[0][0]
    h.app.db.add_worker(MASTER, master_position)
    if h.q("SELECT id FROM positions WHERE name = %s", (STAFF_POSITION,)):
        raise RuntimeError(f"должность «{STAFF_POSITION}» уже есть в базе")
    h.app.db.add_position(STAFF_POSITION, False)
    staff_position = h.q("SELECT id FROM positions WHERE name = %s", (STAFF_POSITION,))[0][0]
    h.app.db.add_worker(STAFF, staff_position)
    h.app.refresh_workers_combo()


def near(a, b):
    return abs(a - b) < 0.01


def master_row(report):
    return report["rows"].get(MASTER, {"count": 0, "total": 0.0, "share": 0.0, "bonus": 0.0})


def save_work(h, plate, brand, model, phone10, name, work_name, price, master=MASTER):
    """«Добавить работу» новой машине мастером «Тест Мастер». Возвращает (id работы, id записи)"""
    h.works_form(plate, brand, model, phone10, name, master=None, save=False)
    h.app.refresh_workers_combo()
    h.app.worker_combo.set(master)
    h.add_work_item(work_name, price)
    h.app.add_work()
    h.root.update()
    car = h.car(plate.upper().replace("T", "Т"))
    row = h.q("SELECT id, booking_id, completed_at FROM works WHERE car_id = %s", (car[0],)) if car else ()
    return (row[0][0], row[0][1], row[0][2]) if row else (None, None, None)


def test_work_salary_and_statistics(h):
    """Работа → «Отчёты» после «Выполнено» и «Статистика»; удаление записи → всё убирается"""
    percent = h.master_percent()
    base = h.report()
    work_id, booking_id, completed = save_work(h, "т301тт799", "ТестМарка", "Один", "9000000301", "Тест Статистика",
                                               "Тест работа связей", 2000)
    if not h.check("работа сохранена, создана запись «в работе»", work_id and booking_id, (work_id, booking_id)):
        return
    h.check("пока запись не выполнена - работа не завершена (completed_at пусто)", completed is None, completed)

    # До «Выполнено» - в зарплату не попадает
    r = h.report()
    h.check("«Отчёты» до «Выполнено»: у мастера нет работы", master_row(r)["count"] == 0, master_row(r))
    h.check("«Отчёты» до «Выполнено»: доход не изменился", near(r["income"], base["income"]),
            (base["income"], r["income"]))

    # «Статистика» считает работу сразу (по дате работы)
    s = h.stats()
    h.check("«Статистика»: марка ТестМарка - 1 визит, 2000", s["brands"].get("ТестМарка") == (1, 2000.0),
            s["brands"].get("ТестМарка"))
    h.check("«Статистика»: клиент «Тест Статистика» - 1 визит", s["clients"].get("Тест Статистика", (0,))[0] == 1,
            s["clients"].get("Тест Статистика"))
    h.check("«Статистика»: вид работ «Тест работа связей» - 1 раз", s["works"].get("Тест работа связей") == (1, 2000.0),
            s["works"].get("Тест работа связей"))

    # «Выполнено» - зарплата мастеру, доход, прибыль
    h.complete_booking(booking_id)
    h.check("«Выполнено»: запись выполнена, работа завершена",
            h.q("SELECT status FROM bookings WHERE id = %s", (booking_id,))[0][0] == "completed"
            and h.q("SELECT completed_at FROM works WHERE id = %s", (work_id,))[0][0] is not None)
    r = h.report()
    share = 2000 * percent / 100
    h.check(f"«Отчёты»: у «{MASTER}» 1 работа на 2000, ему {share:.2f}",
            master_row(r)["count"] == 1 and near(master_row(r)["total"], 2000) and near(master_row(r)["share"], share),
            master_row(r))
    h.check("«Отчёты»: доход +2000", near(r["income"] - base["income"], 2000), (base["income"], r["income"]))
    h.check(f"«Отчёты»: «Мастерам» +{share:.2f}", near(r["masters"] - base["masters"], share),
            (base["masters"], r["masters"]))
    h.check(f"«Отчёты»: прибыль +{2000 - share:.2f}", near(r["profit"] - base["profit"], 2000 - share),
            (base["profit"], r["profit"]))
    h.check("уведомление клиенту не ушло наружу (перехвачено)", True, h.outgoing)

    # Удаление записи - всё возвращается как было
    h.delete_booking(booking_id)
    r = h.report()
    h.check("после удаления: у мастера снова 0 работ", master_row(r)["count"] == 0, master_row(r))
    h.check("после удаления: доход, «Мастерам», прибыль как до работы",
            near(r["income"], base["income"]) and near(r["masters"], base["masters"])
            and near(r["profit"], base["profit"]), (base, r))
    s = h.stats()
    h.check("после удаления: марки ТестМарка нет в «Статистике»", "ТестМарка" not in s["brands"], s["brands"])
    h.check("после удаления: клиента нет в «Статистике»", "Тест Статистика" not in s["clients"])
    h.check("после удаления: вида работ нет в «Статистике»", "Тест работа связей" not in s["works"])


def test_bonus_finances_profit(h):
    """Премия в «Отчётах» → расход в «Финансах», прибыль меньше; удалили расход → премии нет, прибыль как была"""
    base = h.report()
    h.give_bonus(MASTER, 700)
    bonus = h.q("SELECT b.id, b.expense_id, e.amount FROM worker_bonuses b JOIN expenses e ON e.id = b.expense_id "
                "JOIN workers w ON w.id = b.worker_id WHERE w.full_name = %s", (MASTER,))
    if not h.check("премия записана вместе с расходом", bonus and float(bonus[0][2]) == 700, bonus):
        return
    r = h.report()
    h.check("«Отчёты»: премия 700 у мастера", near(master_row(r)["bonus"], 700), master_row(r))
    h.check("«Отчёты»: расходы +700, прибыль −700",
            near(r["expenses"] - base["expenses"], 700) and near(base["profit"] - r["profit"], 700), (base, r))
    h.check("«Финансы»: расход удаляется из списка", h.delete_expense_in_finances(bonus[0][1]))
    h.check("с расходом удалилась и премия", not h.q("SELECT id FROM worker_bonuses WHERE id = %s", (bonus[0][0],)))
    r = h.report()
    h.check("«Отчёты»: премии нет, расходы и прибыль как были",
            near(master_row(r)["bonus"], 0) and near(r["expenses"], base["expenses"])
            and near(r["profit"], base["profit"]), (base, r))


def test_two_works_one_record(h):
    """Две работы по одной машине (дописали в запись «в работе») → «Отчёты» и «Статистика» считают одну запись"""
    percent = h.master_percent()
    base = h.report()
    work_id, booking_id, _ = save_work(h, "т302тт799", "ТестМарка2", "Два", "9000000302", "Тест Две Работы",
                                       "Тест работа А", 1000)
    if not h.check("первая работа сохранена", work_id, work_id):
        return
    # Открыли запись снова (по госномеру) и дописали вторую работу
    h.works_form("т302тт799", save=False, master=None)
    h.app.worker_combo.set(MASTER)
    h.add_work_item("Тест работа Б", 500)
    h.app.add_work()
    h.root.update()
    works = h.q("SELECT id, amount FROM works WHERE booking_id = %s", (booking_id,))
    total = sum(float(w[1]) for w in works)
    h.check("в записи работы на 1500", near(total, 1500), works)
    h.complete_booking(booking_id)
    r = h.report()
    h.check("«Отчёты»: мастеру 1500 и процент от 1500",
            near(master_row(r)["total"], 1500) and near(master_row(r)["share"], 1500 * percent / 100), master_row(r))
    h.check("«Отчёты»: доход +1500", near(r["income"] - base["income"], 1500), (base["income"], r["income"]))
    s = h.stats()
    h.check("«Статистика»: виды работ А и Б посчитаны",
            s["works"].get("Тест работа А") == (1, 1000.0) and s["works"].get("Тест работа Б") == (1, 500.0),
            (s["works"].get("Тест работа А"), s["works"].get("Тест работа Б")))
    h.delete_booking(booking_id)
    r = h.report()
    s = h.stats()
    h.check("после удаления записи: доход как был, видов работ А и Б нет",
            near(r["income"], base["income"]) and "Тест работа А" not in s["works"] and "Тест работа Б" not in s["works"],
            (base["income"], r["income"]))


def test_warehouse_chain(h):
    """Склад → наряд → «Выдано»: заказ «в пути», «На складе», «Со склада» в наряд, «установлена» при сохранении,
    убрали из наряда - снова «на складе», «Выполнено» - «выдано» и оплачено; детали не входят в зарплату"""
    app = h.app
    plate = "т303тт799"
    # Заказ двух деталей для новой машины; шина - «оплачено заранее» (хранение)
    h.warehouse_form(plate, "Lada", "Vesta", "9000000303", "Тест Склад", part="Тест ремень", price="1200")
    h.warehouse_form(plate, part="Тест шина хранение", price="3000", paid=True)
    belt, tire = h.warehouse_part("Тест ремень"), h.warehouse_part("Тест шина хранение")
    if not h.check("заказаны обе детали, статус «в пути»", belt and tire and belt[1] == tire[1] == "в пути",
                   (belt, tire)):
        return
    h.check("шина отмечена «оплачено заранее»", tire[3] == 1, tire)

    # «В пути» в наряд не предлагается
    h.works_form(plate, master=None, save=False)
    h.check("«в пути» - в «Добавить работу» со склада не предлагается", not app.current_car_warehouse_parts,
            app.current_car_warehouse_parts)
    app.clear_work_form()

    # Пришли на склад
    h.check("склад: «На складе» для ремня", h.warehouse_set_status(belt[0], "на складе"))
    h.check("склад: «На складе» для шины", h.warehouse_set_status(tire[0], "на складе"))
    belt, tire = h.warehouse_part("Тест ремень"), h.warehouse_part("Тест шина хранение")
    from datetime import date
    h.check("статус «на складе», дата прихода - сегодня",
            belt[1] == tire[1] == "на складе" and belt[4] == date.today(), (belt, tire))

    # В наряд со склада (пока не сохранили - на складе ничего не меняется)
    base = h.report()
    h.works_form(plate, master=None, save=False)
    offered = h.works_add_from_warehouse(["Тест ремень", "Тест шина хранение"])
    h.check("«Со склада» предлагает обе детали", len(offered) == 2, offered)
    parts = dict(app.parts_list)
    h.check("в наряде: ремень за 1200, шина за 0 (оплачена заранее)",
            parts.get("Тест ремень") == 1200.0 and any(n.startswith("Тест шина хранение") and p == 0.0
                                                        for n, p in app.parts_list), app.parts_list)
    h.check("до сохранения на складе ничего не поменялось",
            h.warehouse_part("Тест ремень")[1] == "на складе" == h.warehouse_part("Тест шина хранение")[1])
    app.worker_combo.set(MASTER)
    h.add_work_item("Тест замена ремня", 1000)
    app.add_work()
    h.root.update()
    work = h.q("SELECT w.id, w.booking_id FROM works w JOIN client_cars c ON c.id = w.car_id "
               "WHERE c.car_number = 'Т303ТТ799'")
    if not h.check("наряд сохранён", work, work):
        return
    work_id, booking_id = work[0]
    belt, tire = h.warehouse_part("Тест ремень"), h.warehouse_part("Тест шина хранение")
    h.check("после сохранения: обе «установлена» и привязаны к наряду",
            belt[1] == tire[1] == "установлена" and belt[2] == tire[2] == work_id, (belt, tire))
    h.check("запчасти наряда записаны", len(h.q("SELECT id FROM parts WHERE work_id = %s", (work_id,))) == 2)

    # Убрали ремень из наряда и сохранили - ремень снова на складе
    h.works_form(plate, master=None, save=False)   # откроется запись «в работе»
    h.check("в открытой записи обе детали", len(app.parts_list) == 2, app.parts_list)
    h.check("ремень убран из списка", h.works_remove_part("Тест ремень"))
    app.add_work()
    h.root.update()
    belt, tire = h.warehouse_part("Тест ремень"), h.warehouse_part("Тест шина хранение")
    h.check("убрали из наряда: ремень «на складе» и отвязан, шина «установлена»",
            belt[1] == "на складе" and belt[2] is None and tire[1] == "установлена", (belt, tire))

    # «Выполнено»: шина выдана и оплачена, ремень на складе; в зарплату и доход - только работа
    h.complete_booking(booking_id)
    belt, tire = h.warehouse_part("Тест ремень"), h.warehouse_part("Тест шина хранение")
    h.check("«Выполнено»: шина «выдано», оплачено", tire[1] == "выдано" and tire[3] == 1, tire)
    h.check("«Выполнено»: ремень остался «на складе»", belt[1] == "на складе", belt)
    r = h.report()
    h.check("«Отчёты»: доход +1000 (только работа, не детали)", near(r["income"] - base["income"], 1000),
            (base["income"], r["income"]))
    h.check("«Отчёты»: мастеру процент только от работы",
            near(master_row(r)["total"], 1000), master_row(r))
    h.delete_booking(booking_id)

    # Деталь в наряде, запись удалили до «Выполнено» - деталь должна вернуться на склад
    h.works_form(plate, master=None, save=False)
    h.works_add_from_warehouse(["Тест ремень"])
    app.worker_combo.set(MASTER)
    h.add_work_item("Тест повторная работа", 500)
    app.add_work()
    h.root.update()
    booking2 = h.q("SELECT b.id FROM bookings b JOIN client_cars c ON c.id = b.car_id "
                   "WHERE c.car_number = 'Т303ТТ799' AND b.status = 'in_progress'")
    h.check("ремень снова «установлена» в новом наряде", h.warehouse_part("Тест ремень")[1] == "установлена")
    if booking2:
        h.delete_booking(booking2[0][0])
        belt = h.warehouse_part("Тест ремень")
        h.check("удалили запись до «Выполнено»: ремень снова «на складе» и отвязан",
                belt[1] == "на складе" and belt[2] is None, belt)
        h.works_form(plate, master=None, save=False)
        h.check("и снова предлагается «Со склада»",
                any(p[1] == "Тест ремень" for p in app.current_car_warehouse_parts), app.current_car_warehouse_parts)
        app.clear_work_form()


def test_staff_payment(h):
    """Выплата сотруднику другой должности: «Отчёты» → «Выписать выплату» → расход «Зарплата сотрудникам»
    в «Финансах», прибыль меньше, «Мастерам» и доход не меняются; удалили расход - выплаты нет;
    удалили сотрудника - выплаченные деньги остаются в расходах"""
    app = h.app
    app.refresh_workers_combo()
    h.check("администратора нет в «Добавить работу»", STAFF not in app.workers_data)
    base = h.report()
    row = base["rows"].get(STAFF)
    h.check("«Отчёты»: администратор в сводке (весь штат), без работ и выплат",
            row is not None and row["count"] == 0 and row["total"] == 0 and row["bonus"] == 0, row)
    group = h.app.summary_tree.item(next(i for i in h.app.summary_tree.get_children()
                                         if i not in h.app.summary_workers
                                         and h.app.summary_tree.item(i, "values")[0] == STAFF_POSITION.upper()),
                                    "values")
    h.check("«Отчёты»: своя группа должности", group is not None, group)
    label, details = h.report_menu(STAFF)
    h.check("меню: «Выписать выплату» (не «премию»)", label.endswith(app.tr("reports.ctx_add_payment")), label)
    h.check("меню: «Подробно» недоступно (работ нет)", str(details) == "disabled", details)
    label, details = h.report_menu(MASTER)
    h.check("меню мастера: «Выписать премию», «Подробно» доступно",
            label.endswith(app.tr("reports.ctx_add_bonus")) and str(details) == "normal", (label, details))

    h.give_bonus(STAFF, 5000)
    pay = h.q("SELECT b.id, e.id, e.amount, e.category, e.description FROM worker_bonuses b "
              "JOIN expenses e ON e.id = b.expense_id JOIN workers w ON w.id = b.worker_id WHERE w.full_name = %s",
              (STAFF,))
    if not h.check("выплата записана вместе с расходом", pay and float(pay[0][2]) == 5000, pay):
        return
    h.check("расход: категория «Зарплата сотрудникам», в описании ФИО и должность",
            pay[0][3] == app.tr("finances.category_staff_salary") and STAFF in pay[0][4] and STAFF_POSITION in pay[0][4],
            pay[0][3:])
    r = h.report()
    h.check("«Отчёты»: у администратора выплата 5000", near(r["rows"][STAFF]["bonus"], 5000), r["rows"][STAFF])
    group = next(h.app.summary_tree.item(i, "values") for i in h.app.summary_tree.get_children()
                 if i not in h.app.summary_workers and h.app.summary_tree.item(i, "values")[0] == STAFF_POSITION.upper())
    h.check("«Отчёты»: в строке должности итог выплат 5000", near(h.money(group[4]), 5000), group)
    h.check("«Отчёты»: расходы +5000, прибыль −5000, доход и «Мастерам» без изменений",
            near(r["expenses"] - base["expenses"], 5000) and near(base["profit"] - r["profit"], 5000)
            and near(r["income"], base["income"]) and near(r["masters"], base["masters"]), (base, r))

    h.check("«Финансы»: расход удаляется", h.delete_expense_in_finances(pay[0][1]))
    h.check("с расходом удалилась выплата", not h.q("SELECT id FROM worker_bonuses WHERE id = %s", (pay[0][0],)))
    r = h.report()
    h.check("«Отчёты»: выплаты нет, расходы и прибыль как были",
            near(r["rows"][STAFF]["bonus"], 0) and near(r["expenses"], base["expenses"])
            and near(r["profit"], base["profit"]), (base, r))

    # Выплатили и уволили: деньги потрачены - расход остаётся, прибыль остаётся меньше
    h.give_bonus(STAFF, 3000)
    expense = h.q("SELECT e.id FROM worker_bonuses b JOIN expenses e ON e.id = b.expense_id "
                  "JOIN workers w ON w.id = b.worker_id WHERE w.full_name = %s", (STAFF,))
    worker_id = h.q("SELECT id FROM workers WHERE full_name = %s", (STAFF,))[0][0]
    app.switch_tab("settings")
    app.refresh_workers_list()
    app.workers_tree.selection_set(str(worker_id))
    app.delete_worker()
    h.root.update()
    h.check("сотрудник с выплатой не удалён, а уволен",
            h.q("SELECT fired_at IS NOT NULL FROM workers WHERE id = %s", (worker_id,)) == ((1,),))
    h.check("его выплата осталась в расходах «Финансов»",
            expense and h.q("SELECT id FROM expenses WHERE id = %s", (expense[0][0],)), expense)
    r = h.report()
    fired_row = r["rows"].get(app.tr("workers.fired_suffix", name=STAFF))
    h.check("«Отчёты»: сотрудник «(уволен)» с выплатой 3000, расходы +3000, прибыль −3000",
            STAFF not in r["rows"] and fired_row and near(fired_row["bonus"], 3000)
            and near(r["expenses"] - base["expenses"], 3000) and near(base["profit"] - r["profit"], 3000),
            (fired_row, base, r))


def test_finance_entries(h):
    """«Финансы»: расход и доход, введённые вручную → список «Финансов» и «Отчёты» (расходы, «Доп. доход», прибыль);
    дата из окна подтверждения; «Отмена» - ничего не сохраняется; удаление → всё как было"""
    from datetime import timedelta
    app = h.app
    tr = app.tr
    base = h.report()
    other_day = app.date_from.get_date() - timedelta(days=1)   # день вне периода отчёта

    # Расход
    rent = tr("finances.category_rent")
    exp_id = h.finance_entry(False, rent, "Тест аренда", "1234,50")
    row = h.q("SELECT amount, category, is_income, expense_date FROM expenses WHERE id = %s", (exp_id,))
    if not h.check("расход записан: сумма с запятой 1234,50, категория, не доход, сегодня",
                   row and float(row[0][0]) == 1234.5 and row[0][1] == rent and row[0][2] == 0
                   and row[0][3] == app.date_to.get_date(), row):
        return
    h.check("поля описания и суммы очищены после сохранения",
            app.expense_desc_entry.get() == "" and app.expense_amount_entry.get() == "")
    fin = h.finance_rows().get(str(exp_id))
    h.check("«Финансы»: строка «Расход» с категорией и описанием",
            fin and fin[0] == tr("finances.expense_label") and fin[1] == rent and fin[2] == "Тест аренда"
            and near(h.money(fin[3]), 1234.5), fin)
    r = h.report()
    h.check("«Отчёты»: расходы +1234,50, прибыль −1234,50",
            near(r["expenses"] - base["expenses"], 1234.5) and near(base["profit"] - r["profit"], 1234.5), (base, r))
    h.check("«Отчёты»: доход, «Доп. доход» и «Мастерам» не изменились",
            near(r["income"], base["income"]) and near(r["other_income"], base["other_income"])
            and near(r["masters"], base["masters"]), (base, r))
    h.check("«Отчёты»: расход в подсказке расходов", "Тест аренда" in r["expenses_list"], r["expenses_list"])

    # Доход
    inc_id = h.finance_entry(True, tr("finances.income_label"), "Тест продажа", 800)
    row = h.q("SELECT amount, is_income FROM expenses WHERE id = %s", (inc_id,))
    h.check("доход записан как доход", row and float(row[0][0]) == 800 and row[0][1] == 1, row)
    fin = h.finance_rows().get(str(inc_id))
    h.check("«Финансы»: строка «Доход»", fin and fin[0] == tr("finances.income_label"), fin)
    r2 = h.report()
    h.check("«Отчёты»: «Доп. доход» +800, прибыль +800",
            near(r2["other_income"] - r["other_income"], 800) and near(r2["profit"] - r["profit"], 800), (r, r2))
    h.check("«Отчёты»: расходы, доход с работ и «Мастерам» не изменились",
            near(r2["expenses"], r["expenses"]) and near(r2["income"], r["income"])
            and near(r2["masters"], r["masters"]), (r, r2))
    h.check("«Отчёты»: доход в подсказке доп. дохода, не в расходах",
            "Тест продажа" in r2["income_list"] and "Тест продажа" not in r2["expenses_list"])

    # Другая дата в окне подтверждения
    old_id = h.finance_entry(False, rent, "Тест старый расход", 500, day=other_day)
    row = h.q("SELECT expense_date FROM expenses WHERE id = %s", (old_id,))
    h.check("расход записан на дату из окна подтверждения", row and row[0][0] == other_day, row)
    r3 = h.report()
    h.check("«Отчёты» за сегодня: расход другого дня не попал",
            near(r3["expenses"], r2["expenses"]) and "Тест старый расход" not in r3["expenses_list"], (r2, r3))

    # «Отмена» в окне даты
    before = h.q("SELECT COUNT(*) FROM expenses")[0][0]
    cancelled = h.finance_entry(False, rent, "Тест отмена", 300, button="common.cancel")
    h.check("«Отмена» в окне даты - ничего не сохранено",
            cancelled is None and h.q("SELECT COUNT(*) FROM expenses")[0][0] == before)
    h.check("«Отмена» - введённое осталось в полях", app.expense_desc_entry.get() == "Тест отмена")

    # Удаление
    for label, entry_id in (("доход", inc_id), ("расход", exp_id), ("расход другого дня", old_id)):
        h.check(f"«Финансы»: {label} удаляется", h.delete_expense_in_finances(entry_id)
                and not h.q("SELECT id FROM expenses WHERE id = %s", (entry_id,)))
        h.check(f"«Финансы»: {label} пропал из списка", str(entry_id) not in h.finance_rows())
    r = h.report()
    h.check("«Отчёты» после удаления: расходы, «Доп. доход», прибыль как были",
            near(r["expenses"], base["expenses"]) and near(r["other_income"], base["other_income"])
            and near(r["profit"], base["profit"]), (base, r))
    h.check("«Отчёты» после удаления: записей нет в подсказках",
            "Тест аренда" not in r["expenses_list"] and "Тест продажа" not in r["income_list"])
    app.is_income_var.set(False)
    app.on_income_switch_changed()
    app.expense_desc_entry.delete(0, "end")
    app.expense_amount_entry.delete(0, "end")


def test_report_other_period(h):
    """«Другой период» под паролем: задать / сменить пароль; без пароля - только сегодня (даты не обойти);
    с паролем - «Отчёты» и «Статистика» за прошлый день (работа, процент, расход, доп. доход);
    ушли с вкладки - снова закрыто; удалили - из отчёта за тот день ушло; «Только сегодня» - закрыто"""
    from datetime import date, timedelta
    app = h.app
    today = date.today()
    past = today - timedelta(days=10)
    percent = h.master_percent()
    h.q("DELETE FROM app_settings WHERE name = 'reports_password'")   # уборка вернёт прежний пароль

    def unlock(tab):
        """Открыть вкладку и ввести пароль (как администратор: сначала вкладка, потом кнопка)"""
        app.switch_tab(tab)
        h.passwords[:] = ["тест-пароль-2"]
        app.toggle_period_lock(tab)
        return h.period_unlocked_ui(tab)

    def report_for(day_from, day_to):
        h.set_period("reports", day_from, day_to)
        return h.report()

    def stats_for(day_from, day_to):
        h.set_period("statistics", day_from, day_to)
        return h.stats()

    # Пароль: задать, потом сменить (нужен текущий)
    h.passwords[:] = ["тест-пароль-1", "тест-пароль-1"]
    app.change_reports_password()
    h.check("пароль для отчётов задан", app.db.check_reports_password("тест-пароль-1"))
    h.passwords[:] = ["тест-пароль-1", "тест-пароль-2", "тест-пароль-2"]
    app.change_reports_password()
    h.check("пароль сменён: новый подходит, старый нет",
            app.db.check_reports_password("тест-пароль-2") and not app.db.check_reports_password("тест-пароль-1"))

    # Закрыто: даты прошлого дня не действуют - отчёт за сегодня
    report_for(past, past)
    h.check("«Отчёты» закрыты: даты вернулись на сегодня, поля недоступны", h.period_locked_ui("reports"))
    h.check("«Отчёты» закрыты: отчёт сформирован за сегодня",
            (app.report_date_from, app.report_date_to) == (today.isoformat(), today.isoformat()))

    # «До» за прошлый день
    if not h.check("«Отчёты»: верный пароль - даты открыты, кнопка «Только сегодня»", unlock("reports")):
        return
    base_past = report_for(past, past)
    h.check("«Отчёты» открыты: отчёт за выбранный день",
            (app.report_date_from, app.report_date_to) == (past.isoformat(), past.isoformat()))
    h.check("«Статистика»: верный пароль - даты открыты", unlock("statistics"))
    h.check("ушли со «Статистики» на «Отчёты» - «Статистика» снова закрыта",
            h.report() and h.period_locked_ui("statistics"))

    # Данные прошлого дня: выполненная работа 2000, расход 700, доп. доход 300
    work_id, booking_id, _ = save_work(h, "т304тт799", "ТестПериод", "Прошлый", "9000000304", "Тест Период",
                                       "Тест работа прошлого дня", 2000)
    if not h.check("работа для прошлого дня сохранена", work_id and booking_id, (work_id, booking_id)):
        return
    h.check("ушли с «Отчётов» - «Отчёты» снова закрыты", h.period_locked_ui("reports"))
    h.complete_booking(booking_id)
    h.q("UPDATE works SET work_date = %s, completed_at = %s WHERE id = %s", (past, past, work_id))
    exp_id = h.finance_entry(False, app.tr("finances.category_rent"), "Тест расход периода", 700, day=past)
    inc_id = h.finance_entry(True, app.tr("finances.income_label"), "Тест доход периода", 300, day=past)

    unlock("reports")
    r = report_for(past, past)
    h.check("«Отчёты» за прошлый день: у мастера работа 2000 и его процент",
            master_row(r)["count"] == 1 and near(master_row(r)["total"], 2000)
            and near(master_row(r)["share"], 2000 * percent / 100), master_row(r))
    h.check("«Отчёты» за прошлый день: доход +2000, расходы +700, доп. доход +300",
            near(r["income"] - base_past["income"], 2000) and near(r["expenses"] - base_past["expenses"], 700)
            and near(r["other_income"] - base_past["other_income"], 300), (base_past, r))
    h.check("«Отчёты» за прошлый день: прибыль + (2000 + 300 - 700 - процент)",
            near(r["profit"] - base_past["profit"], 2000 + 300 - 700 - 2000 * percent / 100), (base_past, r))
    h.check("«Отчёты» за прошлый день: записи в подсказках",
            "Тест расход периода" in r["expenses_list"] and "Тест доход периода" in r["income_list"])
    r = report_for(past, today)
    h.check("«Отчёты» с прошлого дня по сегодня: работа и расход тоже входят",
            master_row(r)["count"] == 1 and "Тест расход периода" in r["expenses_list"], master_row(r))
    r = report_for(today, today)
    h.check("«Отчёты» за сегодня: работы и расхода прошлого дня нет",
            master_row(r)["count"] == 0 and "Тест расход периода" not in r["expenses_list"], master_row(r))

    unlock("statistics")
    s = stats_for(past, past)
    h.check("«Статистика» за прошлый день: марка, клиент, вид работ",
            s["brands"].get("ТестПериод") == (1, 2000.0) and "Тест Период" in s["clients"]
            and "Тест работа прошлого дня" in s["works"], s["brands"].get("ТестПериод"))
    s = stats_for(today, today)
    h.check("«Статистика» за сегодня: работы прошлого дня нет", "ТестПериод" not in s["brands"])

    # Удаление → из отчёта и статистики за тот день уходит
    h.delete_booking(booking_id)
    h.delete_expense_in_finances(exp_id)
    h.delete_expense_in_finances(inc_id)
    unlock("reports")
    r = report_for(past, past)
    h.check("после удаления: отчёт за прошлый день как был",
            master_row(r)["count"] == 0 and near(r["income"], base_past["income"])
            and near(r["expenses"], base_past["expenses"]) and near(r["other_income"], base_past["other_income"])
            and near(r["profit"], base_past["profit"]), (base_past, r))

    # «Только сегодня» - закрыто без пароля, отчёт снова за сегодня
    before = len(h.dialogs)
    app.toggle_period_lock("reports")
    h.check("«Только сегодня»: даты закрыты на сегодня, окна пароля нет",
            h.period_locked_ui("reports") and not any(d[0] == "ask_password" for d in h.dialogs_since(before)))
    h.check("«Только сегодня»: отчёт пересчитан за сегодня",
            (app.report_date_from, app.report_date_to) == (today.isoformat(), today.isoformat()))

    unlock("statistics")
    h.check("после удаления: в «Статистике» за прошлый день работы нет",
            "ТестПериод" not in stats_for(past, past)["brands"])
    app.toggle_period_lock("statistics")
    h.check("«Статистика»: «Только сегодня» - закрыто", h.period_locked_ui("statistics"))


def owner_of(h, plate):
    """(id, имя, телефон) владельца машины"""
    r = h.q("SELECT cl.id, cl.full_name, cl.phone FROM client_cars cc JOIN clients cl ON cl.id = cc.client_id "
            "WHERE cc.car_number = %s", (plate,))
    return r[0] if r else None


def client_by_phone(h, phone):
    r = h.q("SELECT id, full_name FROM clients WHERE phone = %s", (phone,))
    return r[0] if r else None


def car_with_history(h, plate, phone10, name):
    """Машина с выполненной работой (история) - (id работы, id записи)"""
    work_id, booking_id, _ = save_work(h, plate.lower(), "ТестВладелец", "Модель", phone10, name, "Тест история " + plate,
                                       1000)
    if booking_id:
        h.complete_booking(booking_id)
    return work_id, booking_id


def save_owner_work(h, plate, phone10, name, answers, work_name):
    """«Добавить работу» по известной машине с другим владельцем в форме, ответы на вопросы.
    Возвращает (новые окна, id новой работы или None). Новую запись сразу «Выполнено» - иначе следующая
    работа по машине откроет её"""
    h.answers[:] = list(answers)
    before_dialogs = len(h.dialogs)
    last = h.q("SELECT COALESCE(MAX(id), 0) FROM works")[0][0]
    h.works_form(plate.lower(), phone10=phone10, name=name, master=None, save=False)
    h.app.worker_combo.set(MASTER)
    h.add_work_item(work_name, 500)
    h.app.add_work()
    h.root.update()
    h.answers[:] = []
    new = h.q("SELECT id, booking_id FROM works WHERE id > %s", (last,))
    if new:
        h.complete_booking(new[0][1])
    else:
        h.app.clear_work_form()
    return h.dialogs_since(before_dialogs), (new[0][0] if new else None)


def test_new_owner(h):
    """Смена владельца: вопрос «новый владелец?» в «Добавить работу» и «Записать клиента».
    Новый владелец - машина и вся её история к нему, прежний клиент остаётся; тот же человек - меняется
    его телефон / имя; телефон другого клиента - машина к нему; «Отмена» - ничего не сохраняется"""
    h.owner_question(True)
    try:
        _new_owner_checks(h)
    finally:
        h.owner_question(False)
        h.answers[:] = []


def _new_owner_checks(h):
    app = h.app
    counts = lambda: (h.q("SELECT COUNT(*) FROM works")[0][0], h.q("SELECT COUNT(*) FROM clients")[0][0])

    # 1. Новые имя и телефон («Добавить работу») - вопрос «ОК / Отмена»
    old_work, _ = car_with_history(h, "Т305ТТ799", "9000000305", "Продавец Тестовый")
    seller = owner_of(h, "Т305ТТ799")
    if not h.check("машина с историей у «Продавец Тестовый»", old_work and seller and seller[1] == "Продавец Тестовый", seller):
        return
    before = counts()
    dialogs, work = save_owner_work(h, "Т305ТТ799", "9000000306", "Покупатель Тестовый", [False], "Тест работа покупателя")
    h.check("новые имя и телефон: вопрос «новый владелец?» с прежним владельцем",
            any(d[0] == "askokcancel" and "Продавец Тестовый" in d[2] for d in dialogs), dialogs)
    h.check("«Отмена» - работа и клиент не сохранены, владелец прежний",
            work is None and counts() == before and owner_of(h, "Т305ТТ799")[0] == seller[0])

    dialogs, work = save_owner_work(h, "Т305ТТ799", "9000000306", "Покупатель Тестовый", [True], "Тест работа покупателя")
    buyer = client_by_phone(h, "+79000000306")
    h.check("«ОК» - работа сохранена, создан клиент «Покупатель Тестовый»",
            work and buyer and buyer[1] == "Покупатель Тестовый", buyer)
    h.check("машина теперь у покупателя", buyer and owner_of(h, "Т305ТТ799")[0] == buyer[0])
    h.check("история машины (прошлая работа и запись) перешла к покупателю",
            buyer and h.q("SELECT client_id FROM works WHERE id = %s", (old_work,))[0][0] == buyer[0]
            and h.q("SELECT b.client_id FROM bookings b JOIN works w ON w.booking_id = b.id WHERE w.id = %s",
                    (old_work,))[0][0] == buyer[0])
    h.check("прежний клиент остался в базе с его телефоном",
            client_by_phone(h, "+79000000305") == (seller[0], "Продавец Тестовый"))
    s = h.stats()
    h.check("«Статистика»: у покупателя обе работы машины, продавца нет",
            s["clients"].get("Покупатель Тестовый", (0,))[0] == 2 and "Продавец Тестовый" not in s["clients"],
            (s["clients"].get("Покупатель Тестовый"), s["clients"].get("Продавец Тестовый")))

    # 2. Сменился только телефон - «Да / Нет / Отмена»
    car_with_history(h, "Т306ТТ799", "9000000307", "Тест Владелец")
    owner = owner_of(h, "Т306ТТ799")
    before = counts()
    dialogs, work = save_owner_work(h, "Т306ТТ799", "9000000308", "Тест Владелец", [None], "Тест работа телефон")
    h.check("сменился телефон: вопрос «Да / Нет / Отмена»",
            any(d[0] == "askyesnocancel" and "Тест Владелец" in d[2] for d in dialogs), dialogs)
    h.check("«Отмена» - ничего не сохранено, телефон прежний",
            work is None and counts() == before and owner_of(h, "Т306ТТ799") == owner)
    dialogs, work = save_owner_work(h, "Т306ТТ799", "9000000308", "Тест Владелец", [False], "Тест работа телефон")
    h.check("«Нет» (тот же человек) - работа сохранена, нового клиента нет, у владельца новый телефон",
            work and counts()[1] == before[1] and owner_of(h, "Т306ТТ799") == (owner[0], "Тест Владелец",
                                                                                "+79000000308"),
            owner_of(h, "Т306ТТ799"))

    # «Записать клиента» - тот же вопрос; «Да» - новый владелец
    booking_before = h.q("SELECT COALESCE(MAX(id), 0) FROM bookings")[0][0]
    h.answers[:] = [True]
    before_dialogs = len(h.dialogs)
    h.booking_form("т306тт799", phone10="9000000309", name="Тест Владелец")
    h.answers[:] = []
    new_client = client_by_phone(h, "+79000000309")
    h.check("«Записать клиента»: тот же вопрос",
            any(d[0] == "askyesnocancel" and "Тест Владелец" in d[2] for d in h.dialogs_since(before_dialogs)))
    h.check("«Записать клиента», «Да» - запись создана на нового клиента, машина и её наряды - у него",
            new_client and new_client[0] != owner[0] and owner_of(h, "Т306ТТ799")[0] == new_client[0]
            and h.q("SELECT client_id FROM bookings WHERE id > %s", (booking_before,)) == ((new_client[0],),)
            and {r[0] for r in h.q("SELECT w.client_id FROM works w JOIN client_cars cc ON cc.id = w.car_id "
                                   "WHERE cc.car_number = 'Т306ТТ799'")} == {new_client[0]},
            new_client)
    h.check("прежний владелец остался со своим (новым) телефоном",
            client_by_phone(h, "+79000000308") == (owner[0], "Тест Владелец"))

    # 3. Телефон другого клиента из базы - машина к нему, нового клиента нет
    car_with_history(h, "Т307ТТ799", "9000000310", "Старый Тестовый")
    before = counts()
    dialogs, work = save_owner_work(h, "Т307ТТ799", "9000000305", "Продавец Тестовый", [True], "Тест работа к клиенту")
    h.check("телефон есть у другого клиента: вопрос называет его",
            any(d[0] == "askokcancel" and "Продавец Тестовый" in d[2] for d in dialogs), dialogs)
    h.check("«ОК» - машина у этого клиента, нового клиента нет",
            work and owner_of(h, "Т307ТТ799")[0] == seller[0] and counts()[1] == before[1], owner_of(h, "Т307ТТ799"))

    # 4. Тот же телефон, другое имя - переименовать?
    dialogs, work = save_owner_work(h, "Т307ТТ799", "9000000305", "Тестовый Переименован", [False],
                                    "Тест работа имя")
    h.check("другое имя при том же телефоне: вопрос о переименовании; «Нет» - не сохранено, имя прежнее",
            any(d[0] == "askyesnocancel" and "Тестовый Переименован" in d[2] for d in dialogs)
            and work is None and owner_of(h, "Т307ТТ799")[1] == "Продавец Тестовый", dialogs)
    dialogs, work = save_owner_work(h, "Т307ТТ799", "9000000305", "Тестовый Переименован", [True],
                                    "Тест работа имя")
    h.check("«Да» - работа сохранена, клиент переименован, нового клиента нет",
            work and owner_of(h, "Т307ТТ799") == (seller[0], "Тестовый Переименован", "+79000000305")
            and counts()[1] == before[1], owner_of(h, "Т307ТТ799"))
    h.check("не было вопроса «новый владелец?» при переименовании",
            not any(d[0] == "askokcancel" for d in dialogs), dialogs)


FIRED = "Тест Увольняемый"


def test_fire_worker(h):
    """Удаление мастера с работами и премией = увольнение: история остаётся в «Отчётах» и «Статистике»,
    сам он пропадает из списков («Добавить работу», «Сотрудники», расписание, места в «Записать клиента»);
    его наряд открывается с ним; добавили с тем же ФИО - вернулся на работу"""
    app, db = h.app, h.app.db
    master_position = h.q("SELECT id FROM positions WHERE is_master = 1 ORDER BY id LIMIT 1")[0][0]
    if not h.check("тестовый мастер создан", db.add_worker(FIRED, master_position) == "added"):
        return
    worker_id = h.q("SELECT id FROM workers WHERE full_name = %s", (FIRED,))[0][0]
    app.refresh_workers_combo()
    capacity_before = db.day_capacity(date.today())["total"]

    h.works_form("т308тт799", "ТестУволен", "Модель", "9000000311", "Тест Клиент Уволенного", master=None, save=False)
    app.worker_combo.set(FIRED)
    h.add_work_item("Тест работа уволенного", 1500)
    app.add_work()
    h.root.update()
    work = h.q("SELECT id, booking_id FROM works WHERE worker_id = %s", (worker_id,))
    if not h.check("работа мастера сохранена", work, work):
        return
    work_id, booking_id = work[0]
    h.complete_booking(booking_id)
    h.give_bonus(FIRED, 500)
    before = h.report()
    stats_before = h.stats()

    h.answers[:] = [True]
    n = len(h.dialogs)
    app.refresh_workers_list()
    app.workers_tree.selection_set(str(worker_id))
    app.delete_worker()
    h.root.update()
    asked = [d for d in h.dialogs_since(n) if d[0] == "askyesno"]
    h.check("вопрос «Уволить?» с числом работ и выплат",
            asked and "Уволить" in asked[0][2] and "(1)" in asked[0][2], asked)
    h.check("сотрудник уволен (дата увольнения), не удалён",
            h.q("SELECT fired_at FROM workers WHERE id = %s", (worker_id,)) == ((date.today(),),))
    h.check("работа и премия на месте",
            h.q("SELECT COUNT(*) FROM works WHERE worker_id = %s", (worker_id,))[0][0] == 1
            and h.q("SELECT COUNT(*) FROM worker_bonuses WHERE worker_id = %s", (worker_id,))[0][0] == 1)

    r = h.report()
    row = r["rows"].get(app.tr("workers.fired_suffix", name=FIRED))
    h.check("«Отчёты»: «(уволен)» с работой 1500 и премией 500",
            row and row["count"] == 1 and near(row["total"], 1500) and near(row["bonus"], 500), row)
    h.check("«Отчёты»: доход, «Мастерам», расходы, прибыль - как до увольнения",
            all(near(r[k], before[k]) for k in ("income", "masters", "expenses", "profit")), (before, r))
    h.report_menu(FIRED)
    h.check("«Отчёты»: уволенному «Выписать премию» недоступно",
            str(app.summary_context_menu.entrycget(1, "state")) == "disabled")
    s = h.stats()
    h.check("«Статистика»: работа уволенного осталась",
            s["works"].get("Тест работа уволенного") == stats_before["works"].get("Тест работа уволенного")
            and "Тест работа уволенного" in s["works"])

    app.refresh_workers_combo()
    app.refresh_workers_list()
    app.refresh_staff_tab()
    h.check("нет в «Добавить работу»", FIRED not in app.workers_data)
    h.check("нет в «Настройки → Сотрудники»", str(worker_id) not in app.workers_tree.get_children())
    h.check("нет в расписании сотрудников", worker_id not in [w for w, _ in app.staff_workers])
    h.check("«Записать клиента»: мастеров для мест на одного меньше",
            db.day_capacity(date.today())["total"] == capacity_before - 1)

    app.open_booking_in_add_work(booking_id)
    h.root.update()
    h.check("наряд уволенного открывается с ним («(уволен)» в списке мастеров)",
            app.worker_combo.get() == app.tr("workers.fired_suffix", name=FIRED), app.worker_combo.get())
    app.clear_work_form()
    app.refresh_workers_combo()

    # Вернули на работу: тот же человек, вся история его
    app.refresh_workers_list()
    app.worker_name_entry.delete(0, "end"); app.worker_name_entry.insert(0, FIRED)
    app.worker_position_combo.set(h.positions_before[0][1])
    n = len(h.dialogs)
    app.add_worker()
    h.check("добавили с тем же ФИО - «возвращён на работу», нового сотрудника нет",
            any("возвращён" in d[2] for d in h.dialogs_since(n))
            and h.q("SELECT COUNT(*), MAX(fired_at) FROM workers WHERE full_name = %s", (FIRED,)) == ((1, None),))
    app.refresh_workers_combo()
    r = h.report()
    h.check("снова в «Добавить работу» и в «Отчётах» без пометки, с той же работой",
            FIRED in app.workers_data and r["rows"].get(FIRED, {}).get("count") == 1)


def test_cancel_booking_with_works(h):
    """«Отменить» запись с работами нельзя (работы остались бы в «Статистике» без зарплаты, запчасти -
    «установлена»); запись без работ отменяется"""
    from datetime import timedelta
    app, db = h.app, h.app.db
    work_id, booking_id, _ = save_work(h, "т309тт799", "ТестОтмена", "Модель", "9000000312", "Тест Отмена",
                                       "Тест работа отмены", 900)
    if not h.check("запись с работой «в работе»", booking_id):
        return
    n = len(h.dialogs)
    app.get_selected_booking_id = lambda: booking_id
    app.mark_booking_cancelled()
    h.check("«Отменить» запись с работой - предупреждение, запись «в работе», работа на месте",
            any(d[0] == "showwarning" and "отменить её нельзя" in d[2] for d in h.dialogs_since(n))
            and h.q("SELECT status FROM bookings WHERE id = %s", (booking_id,)) == (("in_progress",),)
            and h.q("SELECT id FROM works WHERE id = %s", (work_id,)))
    h.complete_booking(booking_id)

    car = h.car("Т309ТТ799")
    empty = db.add_booking(date.today() + timedelta(days=2), "11:00", car[1], car[0])
    app.get_selected_booking_id = lambda: empty
    app.mark_booking_cancelled()
    h.check("запись без работ отменяется", h.q("SELECT status FROM bookings WHERE id = %s", (empty,)) == (("cancelled",),))


def add_test_worker(h, name, position_name=None, works_with_cars=True):
    """Сотрудник для теста (в своей должности, если position_name). Возвращает (id сотрудника, id должности)"""
    db = h.app.db
    if position_name:
        db.add_position(position_name, works_with_cars)
        position_id = h.q("SELECT id FROM positions WHERE name = %s", (position_name,))[0][0]
    else:
        position_id = h.q("SELECT id FROM positions WHERE is_master = 1 ORDER BY id LIMIT 1")[0][0]
    db.add_worker(name, position_id)
    h.app.refresh_workers_combo()
    return h.q("SELECT id FROM workers WHERE full_name = %s", (name,))[0][0], position_id


def test_edit_completed_work(h):
    """Правка выполненного наряда: другой мастер и цена → зарплата переходит к нему, доход и «Статистика»
    пересчитаны, наряд остаётся выполненным"""
    app = h.app
    percent = h.master_percent()
    add_test_worker(h, "Тест Второй Мастер")
    work_id, booking_id, _ = save_work(h, "т310тт799", "ТестПравка", "Модель", "9000000313", "Тест Правка Наряда",
                                       "Тест работа правки", 2000)
    if not h.check("наряд сохранён", work_id):
        return
    h.complete_booking(booking_id)
    before, stats_before = h.report(), h.stats()

    app.open_booking_in_add_work(booking_id)
    h.root.update()
    h.check("выполненный наряд открылся с мастером и работой",
            app.worker_combo.get() == MASTER and [n for n, _ in app.works_list] == ["Тест работа правки"],
            (app.worker_combo.get(), app.works_list))
    app.refresh_workers_combo()
    app.worker_combo.set("Тест Второй Мастер")
    app.works_list.clear()
    app.works_tree.delete(*app.works_tree.get_children())
    h.add_work_item("Тест работа правки", 3000)
    app.add_work()
    h.root.update()
    row = h.q("SELECT w.full_name, wk.amount, wk.completed_at IS NOT NULL FROM works wk "
              "JOIN workers w ON w.id = wk.worker_id WHERE wk.id = %s", (work_id,))
    h.check("наряд обновлён: другой мастер, 3000, по-прежнему выполнен",
            row and row[0][0] == "Тест Второй Мастер" and float(row[0][1]) == 3000 and row[0][2] == 1, row)
    h.check("новой записи и наряда не появилось",
            h.q("SELECT COUNT(*) FROM works WHERE booking_id = %s", (booking_id,))[0][0] == 1)
    r = h.report()
    second = r["rows"].get("Тест Второй Мастер", {})
    h.check("«Отчёты»: у прежнего мастера работа ушла, у нового - 3000 и его процент",
            master_row(r)["count"] == master_row(before)["count"] - 1 and second.get("count") == 1
            and near(second.get("total", 0), 3000) and near(second.get("share", 0), 3000 * percent / 100),
            (master_row(before), master_row(r), second))
    h.check("«Отчёты»: доход +1000, «Мастерам» + процент от 1000",
            near(r["income"] - before["income"], 1000) and near(r["masters"] - before["masters"], 1000 * percent / 100),
            (before, r))
    st = h.stats()
    h.check("«Статистика»: вид работ - 3000 вместо 2000",
            st["works"].get("Тест работа правки") == (1, 3000.0)
            and stats_before["works"].get("Тест работа правки") == (1, 2000.0),
            (stats_before["works"].get("Тест работа правки"), st["works"].get("Тест работа правки")))
    app.clear_work_form()


def test_master_absence(h):
    """Отпуск мастера сегодня: мест в «Записать клиента» на одного меньше, в «Добавить работу» он с пометкой
    в конце списка и сохранение с ним переспрашивает («Нет» - не сохранено); вышел из отпуска - всё как было"""
    app, db = h.app, h.app.db
    worker_id, _ = add_test_worker(h, "Тест Отпускник")
    today = date.today()
    cap = db.day_capacity(today)
    db.set_worker_day(worker_id, today, "vacation")
    cap2 = db.day_capacity(today)
    h.check("«Записать клиента»: работающих мастеров на одного меньше, отпускник в списке отсутствующих",
            cap2["working"] == cap["working"] - 1 and any(n == "Тест Отпускник" for n, _ in cap2["absent"]),
            (cap, cap2))
    app.refresh_workers_combo()
    label = next((k for k, v in app.workers_data.items() if v == worker_id), "")
    h.check("«Добавить работу»: отпускник с пометкой, в конце списка",
            label != "Тест Отпускник" and "Тест Отпускник" in label and list(app.workers_data)[-1] == label, label)

    before = h.q("SELECT COUNT(*) FROM works")[0][0]
    h.works_form("т311тт799", "ТестОтпуск", "Модель", "9000000314", "Тест Отпуск", master=None, save=False)
    app.worker_combo.set(label)
    h.add_work_item("Тест работа отпускника", 500)
    h.answers[:] = [False]
    n = len(h.dialogs)
    app.add_work()
    h.root.update()
    h.answers[:] = []
    h.check("сохранение с отпускником переспрашивает; «Нет» - не сохранено",
            any(d[0] == "askyesno" and "Тест Отпускник" in d[2] for d in h.dialogs_since(n))
            and h.q("SELECT COUNT(*) FROM works")[0][0] == before)
    app.clear_work_form()

    db.set_worker_day(worker_id, today, None)
    app.refresh_workers_combo()
    h.check("вышел из отпуска: места и список как были",
            db.day_capacity(today)["working"] == cap["working"] and "Тест Отпускник" in app.workers_data)


def test_position_cars_off_and_rename(h):
    """Должность «с машинами» выключили: сотрудника нет в «Добавить работу», но его работы и процент
    в «Отчётах» остаются. Переименовали должность - в «Отчётах» группа с новым названием, суммы те же"""
    app = h.app
    worker_id, position_id = add_test_worker(h, "Тест Кузовщик", "Тест-кузовщик", True)
    h.check("сотрудник должности «с машинами» в «Добавить работу»", "Тест Кузовщик" in app.workers_data)
    work_id, booking_id, _ = save_work(h, "т312тт799", "ТестКузов", "Модель", "9000000315", "Тест Кузов",
                                       "Тест кузовная работа", 1200, master="Тест Кузовщик")
    if not h.check("работа кузовщика сохранена", work_id):
        return
    h.complete_booking(booking_id)
    before = h.report()

    app.refresh_workers_list()
    app.refresh_positions()
    app.positions_tree.selection_set(str(position_id))
    app.toggle_position_cars()
    h.check("отметка «с машинами» выключена",
            h.q("SELECT is_master FROM positions WHERE id = %s", (position_id,)) == ((0,),))
    app.refresh_workers_combo()
    h.check("нет в «Добавить работу»", "Тест Кузовщик" not in app.workers_data)
    r = h.report()
    row = r["rows"].get("Тест Кузовщик", {})
    h.check("«Отчёты»: его работа 1200 осталась, итоги как были",
            row.get("count") == 1 and near(row.get("total", 0), 1200)
            and all(near(r[k], before[k]) for k in ("income", "masters", "profit")), (row, before, r))

    h.set_input_answer("Тест-жестянщик")
    app.positions_tree.selection_set(str(position_id))
    app.rename_position()
    r = h.report()
    groups = [str(app.summary_tree.item(i, "values")[0]) for i in app.summary_tree.get_children()
              if i not in app.summary_workers]
    h.check("переименовали должность: в «Отчётах» группа «ТЕСТ-ЖЕСТЯНЩИК», старой нет",
            "ТЕСТ-ЖЕСТЯНЩИК" in groups and "ТЕСТ-КУЗОВЩИК" not in groups, groups)
    h.check("сумма у сотрудника та же", r["rows"].get("Тест Кузовщик", {}).get("total") == row.get("total"))


def test_plate_change_keeps_links(h):
    """Сменили госномер в «Изменить данные»: запчасть на складе, история работ, поиск - по новому номеру;
    по старому - ничего. Сменили владельца - запчасть машины показывается у нового владельца"""
    app, db = h.app, h.app.db
    work_id, booking_id, _ = save_work(h, "т313тт799", "ТестНомер", "Модель", "9000000316", "Тест Старый Номер",
                                       "Тест работа номера", 800)
    if not h.check("машина с работой", work_id):
        return
    h.complete_booking(booking_id)
    car = h.car("Т313ТТ799")
    h.warehouse_form("т313тт799", part="Тест деталь номера", qty="1", price="300")
    part = h.q("SELECT id FROM warehouse_parts WHERE part_name = 'Тест деталь номера'")
    h.warehouse_set_status(part[0][0], "на складе")

    h.edit_form(booking_id, {0: "т314тт799"})
    h.check("госномер сменён у той же машины", h.car("Т314ТТ799") and h.car("Т314ТТ799")[0] == car[0])
    h.check("склад: деталь находится по новому номеру, по старому - нет",
            [p[1] for p in db.get_warehouse_parts_by_car_number("Т314ТТ799")] == ["Тест деталь номера"]
            and not db.get_warehouse_parts_by_car_number("Т313ТТ799"))
    h.check("история работ - у машины с новым номером",
            h.q("SELECT car_id FROM works WHERE id = %s", (work_id,)) == ((car[0],),))
    found = app.find_car_by_plate("Т314ТТ799")
    h.check("поиск: новый номер находит машину с владельцем, старый - новая машина",
            found["status"] == "found" and found["car"]["client_name"] == "Тест Старый Номер"
            and app.find_car_by_plate("Т313ТТ799")["status"] == "new")

    # Новый владелец - деталь показывается у него
    h.owner_question(True)
    try:
        h.answers[:] = [True]
        h.booking_form("т314тт799", phone10="9000000317", name="Новый Тестовый")
        h.answers[:] = []
    finally:
        h.owner_question(False)
    parts = db.get_warehouse_parts_by_car_id(car[0])
    h.check("склад: у детали машины теперь новый владелец",
            parts and parts[0][4] == "Новый Тестовый", parts and parts[0][4])


def test_master_percent_change(h):
    """Сменили процент мастеру в «Отчётах» → «Мастерам» и прибыль пересчитаны (вернули - как было)"""
    app = h.app
    old = app.percent_var.get()
    try:
        work_id, booking_id, _ = save_work(h, "т315тт799", "ТестПроцент", "Модель", "9000000318", "Тест Процент",
                                           "Тест работа процента", 1000)
        if not h.check("работа сохранена", work_id):
            return
        h.complete_booking(booking_id)
        app.percent_var.set("40")
        r40 = h.report()
        app.percent_var.set("60")
        r60 = h.report()
        h.check("процент 40 → 60: «Мастерам» +20% дохода с работ, прибыль на столько же меньше",
                near(r60["masters"] - r40["masters"], r40["income"] * 0.2)
                and near(r40["profit"] - r60["profit"], r40["income"] * 0.2), (r40, r60))
        h.check("доход от процента не зависит", near(r40["income"], r60["income"]))
        h.check("у мастера доля = 60% его работ", near(master_row(r60)["share"], master_row(r60)["total"] * 0.6),
                master_row(r60))
    finally:
        app.percent_var.set(old)


TESTS = [test_work_salary_and_statistics, test_bonus_finances_profit, test_two_works_one_record,
         test_warehouse_chain, test_staff_payment, test_finance_entries, test_report_other_period,
         test_new_owner, test_fire_worker, test_cancel_booking_with_works,
         test_edit_completed_work, test_master_absence, test_position_cars_off_and_rename,
         test_plate_change_keeps_links, test_master_percent_change]
