# -*- coding: utf-8 -*-
"""Общая обвязка автотестов: настоящая программа (AutoServiceApp) на ТЕСТОВОЙ базе, формы заполняются
и кнопки нажимаются как у администратора, результат проверяется запросами к базе.

Защита: тесты пишут в базу, поэтому запускаются, только если в config/.env стоит ALEXAN_TEST_DB=1
(флаг есть только на компьютере разработчика; .env в релиз не попадает).
Перед тестами - резервная копия (папка Backup), после - удаление всего, что тесты создали
(строки с id больше, чем были до запуска), и возврат должностей как были.
Окна-вопросы (messagebox) отвечают сами: askyesno - "Да" или ответ из очереди H.answers."""
import os
import sys
import time
import traceback

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)

import tkinter.messagebox as mb
import customtkinter as ctk
import pymysql

TABLES = ["works", "parts", "bookings", "warehouse_parts", "client_cars", "clients", "workers", "positions",
          "worker_bonuses", "expenses", "worker_absences"]
# Порядок удаления при уборке (сначала зависимые)
CLEANUP_ORDER = ["parts", "works", "worker_bonuses", "worker_absences", "warehouse_parts", "bookings",
                 "expenses", "client_cars", "clients", "workers", "positions"]
WATCH = ["works", "bookings", "warehouse_parts", "client_cars", "clients", "workers", "positions"]


class Harness:
    def __init__(self, log_path):
        self.log_file = open(log_path, "w", encoding="utf-8")
        self.results = []      # [(группа, проверка, прошла)]
        self.dialogs = []      # [(вид, заголовок, текст)]
        self.answers = []      # очередь ответов для askyesno
        self.state = {}        # данные между тестами одного набора
        self.group = ""
        self._patch_dialogs()

        from db_config import DB_CONFIG
        if os.getenv("ALEXAN_TEST_DB") != "1":
            raise SystemExit("ОТКАЗ: в config/.env нет ALEXAN_TEST_DB=1 - это не тестовая база, тесты в неё не пишут.")
        self.db_config = DB_CONFIG

        import autoservice_calculator as m
        self.m = m
        self.root = ctk.CTk()
        self.root.geometry("1400x900+0+0")
        self.app = m.AutoServiceApp(self.root, current_user={"id": 1, "username": "autotest", "full_name": "",
                                                              "role": "admin"})
        self.root.update()
        # Окна, которые ждут ответа сами (не messagebox), в тестах появляться не должны - отмечаем, если появились
        self.app.works_ask_new_owner = lambda *a, **k: self._unexpected("окно «новый владелец?»")
        self.app.show_client_selection_dialog = lambda *a, **k: self._unexpected("окно выбора владельца")
        self._input_answer = [""]
        m.ctk.CTkInputDialog = self._fake_input_dialog()

        import backup as backup_module
        from db_config import get_base_path
        base = get_base_path()
        path = backup_module.create_backup(self.app.db, os.path.join(base, "Backup"),
                                           os.path.join(base, "config", "settings.json"),
                                           os.path.join(base, "config", "spare_parts.txt"))
        self.log(f"Резервная копия перед тестами: {path}")
        self.snapshot = {t: self.q(f"SELECT COALESCE(MAX(id), 0) FROM {t}")[0][0] for t in TABLES}
        self.positions_before = self.q("SELECT id, name, is_master FROM positions ORDER BY id")

    # ---------- служебное ----------
    def _patch_dialogs(self):
        def make(kind):
            def dialog(title=None, message=None, **kw):
                ask = kind.startswith("ask")
                answer = (self.answers.pop(0) if self.answers else True) if ask else "ok"
                self.dialogs.append((kind, str(title), str(message)))
                self.log(f"      окно {kind}: {str(message)[:150]!r} -> {answer}")
                return answer
            return dialog
        for name in ("showinfo", "showwarning", "showerror", "askyesno", "askyesnocancel", "askokcancel"):
            setattr(mb, name, make(name))

    def _fake_input_dialog(self):
        harness = self

        class FakeInputDialog:
            def __init__(self, *a, **k):
                pass

            def get_input(self):
                return harness._input_answer[0]
        return FakeInputDialog

    def set_input_answer(self, text):
        """Что «ввести» в окне ввода (CTkInputDialog), например при переименовании должности"""
        self._input_answer[0] = text

    def _unexpected(self, what):
        self.log(f"      НЕОЖИДАННО: {what}")
        self.dialogs.append(("unexpected", what, what))
        return None

    def log(self, line):
        self.log_file.write(line + "\n")
        self.log_file.flush()

    def q(self, sql, params=()):
        conn = pymysql.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return cur.fetchall()
        finally:
            conn.close()

    def wait(self, ms):
        end = time.time() + ms / 1000
        while time.time() < end:
            self.root.update()

    def check(self, name, cond, detail=""):
        self.results.append((self.group, name, bool(cond)))
        self.log(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
        return bool(cond)

    def counts(self):
        return {t: self.q(f"SELECT COUNT(*) FROM {t}")[0][0] for t in WATCH}

    def expect_rejected(self, name, action, warn_text=None, answers=()):
        """Неверный ввод: должно быть предупреждение (с этим текстом) и ни одной новой / удалённой строки в базе"""
        self.answers[:] = list(answers)
        before_c, before_d = self.counts(), len(self.dialogs)
        try:
            action()
        except Exception:
            self.check(name + " (без исключений)", False, traceback.format_exc()[-600:])
            return
        self.root.update()
        new = self.dialogs[before_d:]
        after_c = self.counts()
        changed = {t: (before_c[t], after_c[t]) for t in WATCH if before_c[t] != after_c[t]}
        warned = any(d[0] in ("showwarning", "showerror", "askyesno")
                     and (warn_text is None or warn_text.lower() in d[2].lower()) for d in new)
        saved = any(d[0] == "showinfo" for d in new)
        self.check(name, warned and not changed and not saved,
                   f"предупреждение={warned} изменения={changed} успех={saved}")

    def dialogs_since(self, index):
        return self.dialogs[index:]

    # ---------- данные ----------
    def car(self, plate):
        """(id, client_id, марка, модель, госномер) или None"""
        r = self.q("SELECT id, client_id, car_brand, car_model, car_number FROM client_cars WHERE car_number = %s",
                   (plate,))
        return r[0] if r else None

    def require_free(self, plates=(), phones=()):
        """Тестовые госномера / телефоны не должны уже быть в базе"""
        busy = [p for p in plates if self.car(p)]
        busy += [p for p in phones if self.q("SELECT id FROM clients WHERE phone = %s", (p,))]
        if busy:
            raise RuntimeError(f"тестовые номера / телефоны уже есть в базе: {busy}")

    # ---------- формы ----------
    @staticmethod
    def find_widgets(parent, kind):
        found = []

        def walk(x):
            for ch in x.winfo_children():
                if isinstance(ch, kind):
                    found.append(ch)
                walk(ch)
        walk(parent)
        return found

    def find_button(self, parent, text):
        return next(b for b in self.find_widgets(parent, ctk.CTkButton) if b.cget("text") == text)

    def booking_form(self, plate, brand=None, model=None, phone10=None, name=None, typed_live_first=None, save=True):
        """«Записать клиента»: госномер (с уходом из поля), марка/модель, телефон, имя, «Завтра», «Записать»"""
        app, root = self.app, self.root
        bw = app._ensure_booking_window()
        bw["open"]()
        self.wait(300)   # окно показывается с задержкой - ждём, как человек
        plate_e, brand_e, model_e, phone_e, name_e = self.find_widgets(bw["window"], ctk.CTkEntry)[:5]
        if typed_live_first:
            plate_e.delete(0, "end"); plate_e.insert(0, typed_live_first)
            plate_e._entry.event_generate("<KeyRelease>")
            root.update()
        plate_e.delete(0, "end"); plate_e.insert(0, plate)
        plate_e._entry.event_generate("<KeyRelease>")
        plate_e._entry.event_generate("<FocusOut>")
        root.update()
        if brand is not None:
            brand_e.delete(0, "end"); brand_e.insert(0, brand)
        if model is not None:
            model_e.delete(0, "end"); model_e.insert(0, model)
        if phone10 is not None:
            app.set_phone_value(phone_e, phone10)
            phone_e._entry.event_generate("<FocusOut>")
        if name is not None:
            name_e.delete(0, "end"); name_e.insert(0, name)
        self.find_button(bw["window"], app.tr("bookings.btn_tomorrow")).invoke()
        root.update()
        if save:
            self.find_button(bw["window"], app.tr("bookings.btn_book")).invoke()
            root.update()
        bw["window"].withdraw(); bw["overlay"].withdraw(); bw["window"].grab_release()

    def works_form(self, plate, brand=None, model=None, phone10=None, name=None, master=True, items=(),
                   live=False, save=True):
        """«Добавить работу»: чистая форма, госномер (поиск как при уходе из поля), данные, мастер, работы, сохранить"""
        app = self.app
        app.switch_tab("works")
        app.clear_work_form()
        self.root.update()
        app.car_number_entry.delete(0, "end"); app.car_number_entry.insert(0, plate)
        app.on_car_number_change(live=live)
        for entry, value in ((app.car_brand_entry, brand), (app.car_model_entry, model),
                             (app.client_name_entry, name)):
            if value is not None:
                entry.delete(0, "end"); entry.insert(0, value)
        if phone10 is not None:
            app.set_phone_value(app.client_phone_entry, phone10)
        app.refresh_workers_combo()
        if master:
            app.worker_combo.set(list(app.workers_data)[0])
        elif master is False:
            app.worker_combo.set("")
        for item, price in items:
            self.add_work_item(item, price)
        if save:
            app.add_work()
            self.root.update()

    def add_work_item(self, name, price):
        app = self.app
        app.work_name_entry.delete(0, "end"); app.work_name_entry.insert(0, name)
        app.work_price_entry.delete(0, "end"); app.work_price_entry.insert(0, str(price))
        app.add_work_to_list()

    def warehouse_form(self, plate, brand=None, model=None, phone10=None, name=None, part="Тест деталь",
                       qty="1", price="500", save=True, close=True):
        """Склад → «Добавить запчасть»: госномер (с уходом из поля), данные новой машины, деталь, «Заказать»"""
        app = self.app
        app.switch_tab("warehouse")
        app.show_add_part_form()
        # Окно показывается с задержкой; в ещё не показанное окно Tk нажатия клавиш не доставляет
        self.wait(300)
        e = app.wh_car_number_entry
        e.delete(0, "end"); e.insert(0, plate); e._entry.event_generate("<FocusOut>")
        self.root.update()
        for entry, value in ((app.wh_new_brand_entry, brand), (app.wh_new_model_entry, model),
                             (app.wh_new_client_name_entry, name), (app.wh_part_name_entry, part),
                             (app.wh_quantity_entry, qty), (app.wh_price_entry, price)):
            if value is not None:
                entry.delete(0, "end"); entry.insert(0, value)
        if phone10 is not None:
            app.set_phone_value(app.wh_phone_entry, phone10)
        if save:
            app.add_warehouse_part()
            self.root.update()
        if close:
            app.hide_add_part_form()

    def edit_form(self, booking_id, changes):
        """«Записи» → ПКМ → «Изменить данные клиента и машины» для записи booking_id.
        changes: {номер поля: значение}; поля: 0 госномер, 1 марка, 2 модель, 3 VIN, 4 пробег, 5 телефон (10 цифр),
        6 имя, 7 Telegram. Нажимает «Сохранить» и закрывает окно, если оно осталось открытым"""
        app = self.app
        app.get_selected_booking_id = lambda: booking_id
        app.edit_client_info()
        self.wait(600)
        win = [x for x in self.root.winfo_children() if isinstance(x, ctk.CTkToplevel) and x.winfo_viewable()][-1]
        entries = self.find_widgets(win, ctk.CTkEntry)
        for index, value in changes.items():
            if index == 5:
                app.set_phone_value(entries[5], value)
            else:
                entries[index].delete(0, "end"); entries[index].insert(0, value)
        self.find_button(win, app.tr("common.save")).invoke()
        self.root.update()
        if win.winfo_exists():
            win.destroy()
        app._edit_data_overlay.withdraw()

    # ---------- уборка и итог ----------
    def cleanup(self):
        self.group = "Уборка"
        self.log("\n== Уборка: удаляю всё, что создали тесты ==")
        conn = pymysql.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute("SET FOREIGN_KEY_CHECKS = 0")
                for t in CLEANUP_ORDER:
                    cur.execute(f"DELETE FROM {t} WHERE id > %s", (self.snapshot[t],))
                    if cur.rowcount:
                        self.log(f"  {t}: удалено {cur.rowcount}")
                for pid, name, is_master in self.positions_before:
                    cur.execute("UPDATE positions SET name = %s, is_master = %s WHERE id = %s", (name, is_master, pid))
                cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            conn.commit()
        finally:
            conn.close()
        left = {t: self.q(f"SELECT COUNT(*) FROM {t} WHERE id > %s", (self.snapshot[t],))[0][0] for t in TABLES}
        self.check("после уборки база как до тестов",
                   not any(left.values())
                   and self.q("SELECT id, name, is_master FROM positions ORDER BY id") == self.positions_before, left)
        unexpected = [d for d in self.dialogs if d[0] == "unexpected"]
        self.check("не было неожиданных окон", not unexpected, unexpected)

    def summary(self):
        failed = [(g, n) for g, n, ok in self.results if not ok]
        self.log(f"\nИТОГО: {len(self.results) - len(failed)} из {len(self.results)} проверок прошли")
        for g, n in failed:
            self.log(f"  FAIL [{g}] {n}")
        self.log_file.close()
        return len(self.results), failed
