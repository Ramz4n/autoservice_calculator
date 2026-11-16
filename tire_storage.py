"""«Склад» → «Шины»: шины клиентов на хранении (таблица tire_storage).

Вкладка устроена как «Запчасти»: статусы фишками с количеством, сезон, поиск по мере ввода, колонки на выбор,
меню по правому клику, двойной клик - изменить. Приём шин - то же окно, что «Заказать запчасть»
(клиент и машина ищутся и создаются так же), только вместо раздела «Запчасть» - раздел «Шины».
Шины, записанные раньше запчастями, переносятся сюда через список с отметками (open_tire_transfer).
Подмешивается в AutoServiceApp (TireStorageMixin) - пользуется его формами, переводами и базой.
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date, timedelta

import customtkinter as ctk

from input_rules import parse_money, parse_quantity, parse_date, QUANTITY_MAX
from tires import (SEASONS, STATUS_STORED, STATUS_ISSUED, STATUS_OVERDUE, STATUS_SOON, DEFAULT_QUANTITY,
                   COMMON_WIDTH_PROFILES, COMMON_RADII, default_store_until, display_status, split_size,
                   size_from_fields, rim_of, rim_sort_key)

TIRE_TEXT_LIMITS = {"tire_size": 50, "tire_brand": 100, "location": 50}   # как в базе (VARCHAR)


class SuggestList:
    """Список под полем: вошли в поле - все варианты, вводят - подходящие (без учёта «/», пробелов, R);
    выбрали мышью / Enter - значение в поле, курсор дальше (on_pick). Вписать своё тоже можно"""

    def __init__(self, app, entry, parent, values, on_pick=None):
        self.app, self.entry, self.values, self.on_pick = app, entry, values, on_pick
        self.listbox = app.form_popup_listbox(parent)
        self.listbox.bind("<ButtonRelease-1>", self.pick)
        self.listbox.bind("<Return>", self.pick)
        entry.bind("<KeyRelease>", self.on_key, add="+")
        entry.bind("<FocusIn>", self.on_key, add="+")
        entry.bind("<Down>", self.on_down, add="+")
        entry.bind("<FocusOut>", lambda e: entry.after(200, self._focus_check), add="+")

    @staticmethod
    def key(text):
        return "".join(ch for ch in str(text or "").lower() if ch.isalnum() and ch not in "rzрз")

    def matches(self):
        text = self.key(self.entry.get())
        values = self.values()
        return [v for v in values if text in self.key(v)] if text else list(values)

    def on_key(self, event=None):
        if event is not None and getattr(event, "keysym", None) in ("Down", "Up", "Return", "Escape", "Tab"):
            return
        found = self.matches()
        if not found or (len(found) == 1 and found[0] == self.entry.get().strip()):
            return self.hide()
        self.listbox.delete(0, tk.END)
        for value in found:
            self.listbox.insert(tk.END, value)
        self.app.place_popup(self.listbox, self.entry)

    def on_down(self, event=None):
        if self.listbox.popup_frame.winfo_ismapped():
            self.listbox.focus_set()
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            return "break"

    def pick(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self.listbox.get(selection[0]))
        self.hide()
        if self.on_pick:
            self.on_pick()
        return "break"

    def hide(self):
        self.app.hide_popup(self.listbox)

    def _focus_check(self):
        try:
            if self.app.root.focus_get() is not self.listbox:
                self.hide()
        except (KeyError, tk.TclError):
            self.hide()


class TireStorageMixin:
    TIRE_STATUS_COLORS = {STATUS_STORED: "#22c55e", STATUS_SOON: "#f59e0b", STATUS_OVERDUE: "#e53935",
                          STATUS_ISSUED: "#9e9e9e"}
    # Фон строки - как в «Записях»: светлый оттенок цвета полоски (зелёный, жёлтый, красный, серый);
    # без чередования через строку
    TIRE_ROW_COLORS = {STATUS_STORED: "#edf7f0", STATUS_SOON: "#fdf7e7", STATUS_OVERDUE: "#fcf0f0",
                       STATUS_ISSUED: "#f3f4f6"}
    TIRE_RECENT_DAYS = 92    # «Все» и «Выдано» по умолчанию - за 3 месяца
    TIRE_COLUMNS = ("id", "car_info", "client", "phone", "season", "size", "brand", "quantity", "rims", "location",
                    "received", "until", "price", "paid", "status", "notes")

    # ===== две вкладки склада =====

    def setup_warehouse_pages(self):
        """Переключатель «Запчасти | Шины» сверху склада; возвращает страницу запчастей"""
        switch_row = ctk.CTkFrame(self.warehouse_frame, fg_color="transparent")
        switch_row.pack(fill=tk.X, padx=10, pady=(10, 0))
        self.warehouse_page_labels = {"parts": self.tr("warehouse.tab_parts"), "tires": self.tr("warehouse.tab_tires")}
        self.warehouse_page_switch = ctk.CTkSegmentedButton(
            switch_row, values=list(self.warehouse_page_labels.values()), height=34, font=("Arial", 13, "bold"),
            command=lambda label: self.warehouse_show_page(
                next(k for k, v in self.warehouse_page_labels.items() if v == label)))
        self.warehouse_page_switch.pack(side=tk.LEFT)
        self.warehouse_pages = {"parts": ctk.CTkFrame(self.warehouse_frame, fg_color="transparent"),
                                "tires": ctk.CTkFrame(self.warehouse_frame, fg_color="transparent")}
        self.setup_tires_page(self.warehouse_pages["tires"])
        self.warehouse_page = None
        self.warehouse_show_page("parts", refresh=False)
        return self.warehouse_pages["parts"]

    def warehouse_show_page(self, key, refresh=True):
        """Показать вкладку склада: "parts" - запчасти, "tires" - шины"""
        for name, frame in self.warehouse_pages.items():
            if name != key:
                frame.pack_forget()
        self.warehouse_pages[key].pack(fill=tk.BOTH, expand=True)
        self.warehouse_page_switch.set(self.warehouse_page_labels[key])
        self.warehouse_page = key
        if refresh:
            self.refresh_warehouse_page()

    def refresh_warehouse_page(self):
        """Обновить открытую вкладку склада"""
        if getattr(self, "warehouse_page", "parts") == "tires":
            self.refresh_tires()
        else:
            self.refresh_warehouse()

    # ===== подписи =====

    def tire_season_label(self, season):
        return self.tr(f"tires.season_{season}") if season in SEASONS else "—"

    def tire_status_label(self, status):
        return {STATUS_STORED: self.tr("tires.status_stored"), STATUS_SOON: self.tr("tires.status_soon"),
                STATUS_OVERDUE: self.tr("tires.status_overdue"),
                STATUS_ISSUED: self.tr("tires.status_issued")}.get(status, status)

    def tire_income_texts(self, tire):
        """Доход за хранение в «Финансах»: (категория, описание)"""
        return self.tr("tires.income_category"), self.tr("tires.income_description", tires=self.tire_title(tire))

    def tire_hint_text(self, car_id):
        """Строка для форм, где нашли машину: «🛞 На хранении: Зимние 205/55 R16, 4 шт., ячейка А-12».
        Пусто - у машины нет шин на хранении"""
        sets = self.db.get_stored_tires_by_car(car_id) if car_id else []
        if not sets:
            return ""
        parts = []
        for tire in sets:
            text = ", ".join(x for x in (self.tire_season_label(tire["season"]) if tire["season"] else "",
                                         tire["tire_size"] or "",
                                         self.tr("tires.pieces", count=tire["quantity"] or 0)) if x)
            if tire["location"]:
                text += ", " + self.tr("tires.hint_location", location=tire["location"])
            parts.append(text)
        return self.tr("tires.hint_stored", sets="; ".join(parts))

    # ===== вкладка «Шины» =====

    def setup_tires_page(self, page):
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill=tk.X, padx=10, pady=(8, 6))

        self.tires_status_filter = "all"     # all / stored / overdue / issued
        self.tires_season_filter = None      # None / summer / winter / all
        self.tires_radius_filter = None      # None / "R16" (посадочный диаметр, rim_of)
        self.tires_show_all_time = False
        self.tires_status_bar = ctk.CTkFrame(top, fg_color="transparent")
        self.tires_status_bar.pack(side=tk.LEFT)

        self.tires_columns_btn = ctk.CTkButton(
            top, text="☰", width=34, height=34, corner_radius=8, font=("Arial", 15),
            fg_color="transparent", border_width=1, border_color="#9e9e9e", text_color="#424242", hover_color="#e0e0e0",
            command=lambda: self.show_columns_menu_under("tires_hidden_columns", self.tires_columns_btn))
        self.tires_columns_btn.pack(side=tk.RIGHT)
        self.attach_hover_tip(self.tires_columns_btn, self.tr("bookings.columns_btn"))
        ctk.CTkButton(top, text="+  " + self.tr("tires.accept"), command=lambda: self.show_add_part_form("tires"),
                      height=34, corner_radius=8, font=("Arial", 13, "bold"),
                      fg_color="#1565c0", hover_color="#0d47a1", width=170).pack(side=tk.RIGHT, padx=8)
        search_box = ctk.CTkFrame(top, fg_color="transparent")
        search_box.pack(side=tk.RIGHT, padx=(8, 0))
        self.tires_search_entry = ctk.CTkEntry(search_box, placeholder_text="🔍  " + self.tr("tires.search"),
                                               placeholder_text_color="gray", width=230, height=34, corner_radius=8)
        self.tires_search_entry.pack(side=tk.LEFT)
        self.tires_search_entry.bind("<Return>", lambda e: self.refresh_tires())
        self.tires_search_entry.bind("<KeyRelease>", self._tires_search_keyrelease, add="+")
        ctk.CTkButton(search_box, text="✕", command=self.clear_tires_search, width=30, height=34, corner_radius=8,
                      fg_color="transparent", text_color="gray45", hover_color="#e0e0e0").pack(side=tk.LEFT, padx=(2, 0))

        # Второй ряд: сезон и «перенести из запчастей» (видно, только если в запчастях есть похожие на шины)
        second = ctk.CTkFrame(page, fg_color="transparent")
        second.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.tires_season_bar = ctk.CTkFrame(second, fg_color="transparent")
        self.tires_season_bar.pack(side=tk.LEFT)
        # Радиусы (R15, R16 …) - фишками рядом с сезоном
        self.tires_radius_bar = ctk.CTkFrame(second, fg_color="transparent")
        self.tires_radius_bar.pack(side=tk.LEFT, padx=(12, 0))
        self.tires_transfer_btn = ctk.CTkButton(
            second, text="", command=self.open_tire_transfer, height=30, corner_radius=8, font=("Arial", 12),
            fg_color="#fff3e0", hover_color="#ffe0b2", text_color="#e65100", border_width=1, border_color="#ffb74d")

        bottom = ctk.CTkFrame(page, fg_color="transparent")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 6))
        self.tires_range_btn = ctk.CTkButton(bottom, text="", width=10, height=24, fg_color="transparent",
                                             text_color="#1565c0", hover_color="#e3f2fd",
                                             font=("Arial", 12, "underline"), command=self._tires_toggle_all_time)
        self.tires_count_label = ctk.CTkLabel(bottom, text="", font=("Arial", 12), text_color="gray45", anchor="e")
        self.tires_count_label.pack(side=tk.RIGHT)

        table_frame = ctk.CTkFrame(page, fg_color="white", corner_radius=10, border_width=1,
                                   border_color=self.FORM_CARD_BORDER)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        tree = self.tires_tree = ttk.Treeview(table_frame, columns=self.TIRE_COLUMNS, show="tree headings",
                                              height=15, style="Warehouse.Treeview")
        tree.column("#0", width=12, minwidth=12, stretch=False, anchor="w")   # полоска статуса
        headings = {"id": "ID", "car_info": self.tr("bookings.col_car"),
                    "client": self.tr("bookings.info_label_client"), "phone": self.tr("bookings.col_phone"),
                    "season": self.tr("tires.col_season"),
                    "size": self.tr("tires.col_size"), "brand": self.tr("tires.col_brand"),
                    "quantity": self.tr("warehouse.quantity_short"), "rims": self.tr("tires.col_rims"),
                    "location": self.tr("tires.col_location"), "received": self.tr("tires.col_received"),
                    "until": self.tr("tires.col_until"), "price": self.tr("tires.col_price"),
                    "paid": self.tr("warehouse.col_paid"), "status": self.tr("bookings.col_status"),
                    "notes": self.tr("warehouse.col_notes")}
        widths = {"id": 0, "car_info": 200, "client": 130, "phone": 130, "season": 100, "size": 110, "brand": 120, "quantity": 60,
                  "rims": 70, "location": 80, "received": 95, "until": 95, "price": 100, "paid": 90, "status": 115,
                  "notes": 140}
        for column in self.TIRE_COLUMNS:
            tree.heading(column, text=headings[column])
            anchor = "center" if column in ("quantity", "rims", "paid", "location") else ("e" if column == "price" else "w")
            tree.column(column, width=widths[column], anchor=anchor)
        tree.column("id", width=0, stretch=False, minwidth=0)
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=6)
        tree.pack(fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)
        self.setup_toggleable_columns(tree, "tires_hidden_columns", self.TIRE_COLUMNS[1:])

        self.tires_status_images = {}
        for status, color in self.TIRE_STATUS_COLORS.items():
            image = tk.PhotoImage(master=tree, width=6, height=26)
            image.put(color, to=(0, 0, 6, 26))
            self.tires_status_images[status] = image
        tree.tag_configure(STATUS_ISSUED, foreground="#9e9e9e")
        tree.tag_configure(STATUS_OVERDUE, foreground="#c62828")
        tree.tag_configure(STATUS_SOON, foreground="#b45309")
        for status, background in self.TIRE_ROW_COLORS.items():
            tree.tag_configure(f"bg_{status}", background=background)
        self.make_tree_tooltip(tree, ["brand", "notes", "car_info"])

        menu = self.tires_context_menu = tk.Menu(
            tree, tearoff=0, bg="white", fg="#263238", bd=1, relief="solid",
            activebackground="#e3f2fd", activeforeground="#0d1b2a", font=("Segoe UI", 11), disabledforeground="#b0b7bf")
        menu.add_command(label="  ✎  " + self.tr("bookings.ctx_edit"), command=self.edit_selected_tires)
        menu.add_separator()
        menu.add_command(label="  ✅  " + self.tr("tires.ctx_issue"), command=self.issue_selected_tires)
        menu.add_command(label="  📦  " + self.tr("tires.ctx_return"), command=self.return_selected_tires)
        menu.add_separator()
        menu.add_command(label="  💰  " + self.tr("warehouse.ctx_mark_paid"), command=lambda: self.set_selected_tires_paid(True))
        menu.add_command(label="  ✖  " + self.tr("warehouse.ctx_mark_unpaid"), command=lambda: self.set_selected_tires_paid(False))
        menu.add_separator()
        menu.add_command(label="  🖨  " + self.tr("tires.ctx_receipt"), command=self.save_selected_tire_receipt)
        menu.add_separator()
        menu.add_command(label="  🗑  " + self.tr("bookings.ctx_delete"), command=self.delete_selected_tires,
                         foreground="#c62828", activeforeground="white", activebackground="#c62828")

        def context_menu(event):
            if tree.identify_region(event.x, event.y) == "heading":
                self.show_columns_menu("tires_hidden_columns", event.x_root, event.y_root)
                return
            item = tree.identify_row(event.y)
            if item:
                tree.selection_set(item)
                issued = self.tires_rows.get(item, {}).get("status") == STATUS_ISSUED
                menu.entryconfig(2, state="disabled" if issued else "normal")
                menu.entryconfig(3, state="normal" if issued else "disabled")
                menu.tk_popup(event.x_root, event.y_root)

        def double_click(event):
            if tree.identify_region(event.x, event.y) == "heading":
                return
            item = tree.identify_row(event.y)
            if item:
                tree.selection_set(item)
                self.edit_selected_tires()

        tree.bind("<Button-3>", context_menu)
        tree.bind("<Double-1>", double_click)
        self.tires_rows = {}   # строка таблицы -> комплект (словарь из базы)

    def _tires_search_keyrelease(self, event=None):
        if event is not None and event.keysym in ("Return", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return
        job = getattr(self, "_tires_search_job", None)
        if job:
            self.root.after_cancel(job)
        self._tires_search_job = self.root.after(400, self.refresh_tires)

    def clear_tires_search(self):
        self.tires_search_entry.delete(0, tk.END)
        self.refresh_tires()
        self.restore_placeholder(self.tires_search_entry)

    def _tires_toggle_all_time(self):
        self.tires_show_all_time = not self.tires_show_all_time
        self.refresh_tires()

    def _tires_set_status(self, key):
        self.tires_status_filter = key
        self.refresh_tires()

    def _tires_set_season(self, season):
        self.tires_season_filter = None if self.tires_season_filter == season else season
        self.refresh_tires()

    def _tires_set_radius(self, rim):
        """Фишка радиуса: показать только этот радиус; второй клик - снять"""
        self.tires_radius_filter = None if self.tires_radius_filter == rim else rim
        self.refresh_tires()

    def _tires_chip(self, parent, text, color, selected, command):
        ctk.CTkButton(parent, text=text, width=10, height=28, corner_radius=14,
                      font=("Arial", 12, "bold" if selected else "normal"),
                      fg_color=color if selected else "white", text_color="white" if selected else color,
                      hover_color=color if selected else "#f0f3f6", border_width=1, border_color=color,
                      command=command).pack(side=tk.LEFT, padx=(0, 6))

    def refresh_tires(self):
        """Обновить список шин: статус и сезон - фишками, поиск по госномеру / клиенту / телефону / размеру /
        марке / ячейке. «Все» и «Выдано» - за 3 месяца (если не «за всё время»); поиск - по всему"""
        self._tires_search_job = None
        tree = self.tires_tree
        for item in tree.get_children():
            tree.delete(item)
        self.tires_rows = {}
        today = date.today()
        search = " ".join(self.tires_search_entry.get().split()).lower()
        cutoff = today - timedelta(days=self.TIRE_RECENT_DAYS)
        status_filter, season_filter = self.tires_status_filter, self.tires_season_filter

        sets = self.db.get_all_tire_storage()
        counts = {"all": 0, STATUS_STORED: 0, STATUS_SOON: 0, STATUS_OVERDUE: 0, STATUS_ISSUED: 0}
        season_counts, radius_counts = {}, {}
        radius_filter = getattr(self, "tires_radius_filter", None)
        rows, hidden_by_date = [], 0
        for tire in sets:
            shown_status = display_status(tire["status"], tire["store_until"], today)
            car_info = " ".join(x for x in (tire["car_brand"], tire["car_model"], tire["car_number"]) if x)
            if search:
                digits = "".join(ch for ch in search if ch.isdigit())
                if len(digits) == 11 and digits[0] in "78":   # «8 900 …» и «+7 (900) …» - один и тот же номер
                    digits = digits[1:]
                haystack = " ".join(str(x or "") for x in (
                    car_info, tire["client_name"], tire["tire_size"], tire["tire_brand"], tire["location"],
                    tire["notes"])).lower()
                phone_digits = "".join(ch for ch in str(tire["client_phone"] or "") if ch.isdigit())
                if search not in haystack and not (len(digits) >= 3 and digits in phone_digits):
                    continue
            last = tire["issued_date"] or tire["received_date"]
            if shown_status == STATUS_ISSUED and isinstance(last, date) and last < cutoff:
                hidden_by_date += 1
                if not self.tires_show_all_time and not search:
                    continue
            counts["all"] += 1
            counts[shown_status] += 1
            if shown_status in (STATUS_SOON, STATUS_OVERDUE):
                counts[STATUS_STORED] += 1   # «на хранении» - вместе со «скоро срок» и просроченными
            if status_filter == STATUS_STORED and shown_status not in (STATUS_STORED, STATUS_SOON, STATUS_OVERDUE):
                continue
            if status_filter in (STATUS_SOON, STATUS_OVERDUE, STATUS_ISSUED) and shown_status != status_filter:
                continue
            season_counts[tire["season"]] = season_counts.get(tire["season"], 0) + 1
            if season_filter and tire["season"] != season_filter:
                continue
            rim = rim_of(tire["tire_size"])
            if rim:
                radius_counts[rim] = radius_counts.get(rim, 0) + 1
            if radius_filter and rim != radius_filter:
                continue
            rows.append((tire, shown_status, car_info))

        for index, (tire, shown_status, car_info) in enumerate(rows):
            tags = [shown_status, f"bg_{shown_status}"]
            item = tree.insert("", tk.END, image=self.tires_status_images.get(shown_status), tags=tags, values=(
                tire["id"], car_info, self.display_name(tire["client_name"]),
                self.display_phone(tire["client_phone"]), self.tire_season_label(tire["season"]),
                tire["tire_size"] or "", tire["tire_brand"] or "", tire["quantity"] or "",
                "✓" if tire["with_rims"] else "", tire["location"] or "",
                tire["received_date"].strftime("%d.%m.%Y") if tire["received_date"] else "",
                tire["store_until"].strftime("%d.%m.%Y") if tire["store_until"] else "",
                self.format_currency(float(tire["price"])) if tire["price"] else "",
                "✓" if tire["is_paid"] else "", self.tire_status_label(shown_status),
                " ".join(str(tire["notes"] or "").split())))
            self.tires_rows[item] = tire

        # Фишки статусов (пустые скрыты, кроме выбранной) и сезонов
        for widget in self.tires_status_bar.winfo_children():
            widget.destroy()
        options = [("all", self.tr("bookings.filter_all"), "#455a64")] + \
                  [(st, self.tire_status_label(st), color) for st, color in self.TIRE_STATUS_COLORS.items()]
        for key, label, color in options:
            if key != "all" and not counts.get(key) and status_filter != key:
                continue
            self._tires_chip(self.tires_status_bar, f"●  {label}  {counts.get(key, 0)}", color, status_filter == key,
                             lambda k=key: self._tires_set_status(k))
        for widget in self.tires_season_bar.winfo_children():
            widget.destroy()
        for season in SEASONS:
            count = season_counts.get(season, 0)
            if not count and season_filter != season:
                continue
            self._tires_chip(self.tires_season_bar, f"{self.tire_season_label(season)}  {count}", "#1565c0",
                             season_filter == season, lambda s=season: self._tires_set_season(s))
        # Радиусы - по порядку (R13 … R22); пустые скрыты, кроме выбранного
        for widget in self.tires_radius_bar.winfo_children():
            widget.destroy()
        rims = set(radius_counts) | ({radius_filter} if radius_filter else set())
        for rim in sorted(rims, key=rim_sort_key):
            self._tires_chip(self.tires_radius_bar, f"{rim}  {radius_counts.get(rim, 0)}", "#00838f",
                             radius_filter == rim, lambda r=rim: self._tires_set_radius(r))

        total = len(sets)
        self.tires_count_label.configure(
            text=self.tr("bookings.count_all", shown=len(rows)) if len(rows) == total
            else self.tr("bookings.count_shown", shown=len(rows), total=total))
        if status_filter in ("all", STATUS_ISSUED) and not search and (hidden_by_date or self.tires_show_all_time):
            self.tires_range_btn.configure(text=self.tr("bookings.recent_only") if self.tires_show_all_time
                                           else self.tr("bookings.show_all_time"))
            self.tires_range_btn.pack(side=tk.LEFT)
        else:
            self.tires_range_btn.pack_forget()

        # Шины среди запчастей - предложить перенести
        candidates = len(self.db.get_tire_like_warehouse_parts())
        if candidates:
            self.tires_transfer_btn.configure(text="⇄  " + self.tr("tires.transfer_btn", count=candidates))
            self.tires_transfer_btn.pack(side=tk.RIGHT)
        else:
            self.tires_transfer_btn.pack_forget()

    # ===== действия со строкой =====

    def selected_tire(self):
        """Выбранный комплект (словарь из базы) или None - с предупреждением"""
        selection = self.tires_tree.selection()
        tire = self.tires_rows.get(selection[0]) if selection else None
        if tire is None:
            messagebox.showwarning(self.tr("common.attention"), self.tr("tires.msg_select"))
            return None
        fresh = self.db.get_tire_storage_by_id(tire["id"])
        if fresh is None:
            messagebox.showwarning(self.tr("common.attention"), self.tr("tires.msg_not_found"))
            self.refresh_tires()
        return fresh

    def tire_title(self, tire):
        """«Зимние 205/55 R16, 4 шт. — Kia Rio А123ВС777» для вопросов"""
        car = " ".join(x for x in (tire.get("car_brand"), tire.get("car_model"), tire.get("car_number")) if x)
        what = ", ".join(x for x in (self.tire_season_label(tire.get("season")) if tire.get("season") else "",
                                     tire.get("tire_size") or "",
                                     self.tr("tires.pieces", count=tire.get("quantity") or 0)) if x)
        return f"{what} — {car}" if car else what

    def edit_selected_tires(self):
        tire = self.selected_tire()
        if tire:
            self.show_add_part_form("tires", tire_id=tire["id"])

    def issue_selected_tires(self):
        """Выдать шины клиенту: статус «выдано» с сегодняшней датой. Не оплачено - переспрашиваем"""
        tire = self.selected_tire()
        if not tire:
            return
        if tire["status"] == STATUS_ISSUED:
            messagebox.showinfo(self.tr("common.attention"), self.tr("tires.msg_already_issued"))
            return
        if tire["price"] and not tire["is_paid"]:
            question = self.tr("tires.msg_issue_unpaid", tires=self.tire_title(tire),
                               price=self.format_currency(float(tire["price"])))
        else:
            question = self.tr("tires.msg_confirm_issue", tires=self.tire_title(tire))
        if not messagebox.askyesno(self.tr("common.confirm"), question):
            return
        self.db.set_tire_storage_status(tire["id"], STATUS_ISSUED)
        self.refresh_tires()

    def return_selected_tires(self):
        """Выдали по ошибке - снова «на хранении»"""
        tire = self.selected_tire()
        if not tire or tire["status"] != STATUS_ISSUED:
            return
        if not messagebox.askyesno(self.tr("common.confirm"), self.tr("tires.msg_confirm_return", tires=self.tire_title(tire))):
            return
        # Пока шины были у клиента, в их ячейку могли положить другие - как при приёме, переспрашиваем
        taken = self.db.tire_location_taken(tire["location"], exclude_id=tire["id"])
        if taken and not messagebox.askyesno(
                self.tr("common.attention"),
                self.tr("tires.msg_location_taken", location=tire["location"], tires=self.tire_title(taken)),
                icon="warning"):
            return
        self.db.set_tire_storage_status(tire["id"], STATUS_STORED)
        self.refresh_tires()

    def set_selected_tires_paid(self, is_paid):
        """Отметить оплату (доход в «Финансах» - сегодня) / снять (доход убирается)"""
        tire = self.selected_tire()
        if not tire:
            return
        if is_paid and not tire["price"]:
            messagebox.showwarning(self.tr("common.attention"), self.tr("tires.msg_paid_no_price"))
            return
        self.db.set_tire_storage_paid(tire["id"], is_paid, income=self.tire_income_texts)
        self.refresh_tires()
        self.tires_refresh_money_tabs()

    def tires_refresh_money_tabs(self):
        """Доход за хранение изменился - «Финансы» (история) сразу как в базе"""
        if hasattr(self, "expenses_tree"):
            self.refresh_expenses()

    def delete_selected_tires(self):
        tire = self.selected_tire()
        if tire and messagebox.askyesno(self.tr("common.confirm"),
                                        self.tr("tires.msg_confirm_delete", tires=self.tire_title(tire))):
            self.db.delete_tire_storage(tire["id"])
            self.refresh_tires()
            self.tires_refresh_money_tabs()

    # ===== расписка о приёме шин на хранение (PDF) =====

    def save_selected_tire_receipt(self):
        """Расписка выбранного комплекта; True - сохранена"""
        tire = self.selected_tire()
        return self.save_tire_receipt(tire) if tire else False

    def save_tire_receipt(self, tire):
        """Расписка: кто сдал, какие шины, где лежат, до какого числа, сколько стоит хранение; подписи.
        Файл - куда выберут; True - сохранён"""
        name = f"{self.tr('tires.receipt_file')}_{tire['id']}_{tire.get('car_number') or ''}.pdf"
        name = "".join(c for c in name if c.isalnum() or c in "._- ")
        path = filedialog.asksaveasfilename(title=self.tr("tires.receipt_title", number=tire["id"]), initialfile=name,
                                            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not path:
            return False
        try:
            self.build_tire_receipt(tire, path)
        except Exception as e:
            messagebox.showerror(self.tr("common.error"), self.tr("tires.receipt_failed", error=str(e)))
            return False
        messagebox.showinfo(self.tr("common.success"), self.tr("tires.receipt_saved", path=path))
        return True

    def build_tire_receipt(self, tire, path):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

        font, bold = "Helvetica", "Helvetica-Bold"
        for name, file_name in (("Arial", "arial.ttf"), ("ArialBold", "arialbd.ttf")):
            font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", file_name)
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont(name, font_path))
                    font, bold = ("Arial", bold) if name == "Arial" else (font, "ArialBold")
                except Exception:
                    pass
        settings = self.load_settings()
        style = lambda size, font_name=font, **kw: ParagraphStyle("s", fontName=font_name, fontSize=size,
                                                                  leading=size + 4, **kw)
        esc = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        day = lambda d: d.strftime("%d.%m.%Y") if d else "—"
        elements = []
        company = " · ".join(x for x in (settings.get("company_name"), settings.get("company_address"),
                                        settings.get("company_phone")) if x)
        if company:
            elements.append(Paragraph(esc(company), style(10, textColor=colors.grey, alignment=1)))
            elements.append(Spacer(1, 8))
        elements.append(Paragraph(esc(self.tr("tires.receipt_title", number=tire["id"])), style(17, bold, alignment=1)))
        elements.append(Paragraph(esc(self.tr("tires.receipt_date", date=day(tire["received_date"]))),
                                  style(11, alignment=1)))
        elements.append(Spacer(1, 14))
        car = " ".join(x for x in (tire.get("car_brand"), tire.get("car_model"), tire.get("car_number")) if x)
        rows = [
            (self.tr("bookings.info_label_client"), self.display_name(tire.get("client_name")) or "—"),
            (self.tr("bookings.col_phone"), self.display_phone(tire.get("client_phone")) or "—"),
            (self.tr("bookings.col_car"), car or "—"),
            (self.tr("tires.season"), self.tire_season_label(tire.get("season"))),
            (self.tr("tires.size"), tire.get("tire_size") or "—"),
            (self.tr("tires.brand"), tire.get("tire_brand") or "—"),
            (self.tr("warehouse.quantity_short"), self.tr("tires.pieces", count=tire.get("quantity") or 0)),
            (self.tr("tires.with_rims"), self.tr("common.yes") if tire.get("with_rims") else self.tr("common.no")),
            (self.tr("tires.location"), tire.get("location") or "—"),
            (self.tr("tires.received"), day(tire.get("received_date"))),
            (self.tr("tires.until"), day(tire.get("store_until"))),
            (self.tr("tires.price"), (self.format_currency(float(tire["price"])) if tire.get("price") else "—")
             + (f" ({self.tr('tires.paid')})" if tire.get("is_paid") and tire.get("price") else "")),
            (self.tr("tires.notes"), tire.get("notes") or "—"),
        ]
        table = Table([[Paragraph(esc(k), style(11, bold)), Paragraph(esc(v), style(11))] for k, v in rows],
                      colWidths=[170, 330])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                   ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        elements += [table, Spacer(1, 14), Paragraph(esc(self.tr("tires.receipt_terms")), style(10)), Spacer(1, 36)]
        signs = Table([[self.tr("tires.receipt_handed"), self.tr("tires.receipt_accepted")],
                       ["_________________________", "_________________________"]], colWidths=[250, 250])
        signs.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 11),
                                   ("TOPPADDING", (0, 1), (-1, 1), 22)]))
        elements.append(signs)
        doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=40, bottomMargin=40)
        doc.build(elements)
    # ===== раздел «Шины» в окне склада =====

    def build_tire_form_section(self, content):
        """Раздел «Шины» окна склада (скрыт в режиме запчасти). Возвращает [заголовок, карточка]"""
        _, body = self.form_section(content, self.tr("tires.section"))
        section = content.winfo_children()[-2:]

        self.form_label(body, self.tr("tires.season"), required=True).pack(fill=tk.X)
        self.tire_season_labels = {self.tr(f"tires.season_{s}"): s for s in SEASONS}
        self.tire_season_switch = ctk.CTkSegmentedButton(body, values=list(self.tire_season_labels), height=32,
                                                         font=("Arial", 13))
        self.tire_season_switch.pack(fill=tk.X, pady=(0, 8))

        # Размер - двумя полями со списками: «ширина/профиль» (205/55) и «радиус» (R16); в базе - «205/55 R16»
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill=tk.X)
        self.tire_size_entry = self.works_cell(row, 0, self.tr("tires.width_profile"),
                                               self.form_entry(row, width=110, placeholder_text="205/55"), 110)
        self.tire_radius_entry = self.works_cell(row, 1, self.tr("tires.radius"),
                                                 self.form_entry(row, width=80, placeholder_text="R16"), 80)
        self.tire_brand_entry = self.works_cell(row, 2, self.tr("tires.brand"), self.form_entry(row))
        self.tire_quantity_entry = self.works_cell(row, 3, self.tr("warehouse.quantity_short"),
                                                   self.form_entry(row, width=60), 60)
        self.tire_size_suggest = SuggestList(self, self.tire_size_entry, content, self.tire_width_profile_values,
                                             on_pick=lambda: self.tire_radius_entry.focus_set())
        self.tire_radius_suggest = SuggestList(self, self.tire_radius_entry, content, self.tire_radius_values,
                                               on_pick=lambda: self.tire_brand_entry.focus_set())

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill=tk.X, pady=(8, 0))
        self.tire_location_entry = self.works_cell(row, 0, self.tr("tires.location"),
                                                   self.form_entry(row, width=150, placeholder_text="А-12"), 150)
        rims_holder = ctk.CTkFrame(row, fg_color="transparent")
        self.works_cell(row, 1, " ", rims_holder)
        self.tire_rims_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(rims_holder, text=self.tr("tires.with_rims"), variable=self.tire_rims_var,
                        font=("Arial", 13)).pack(side=tk.LEFT, pady=4)

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill=tk.X, pady=(8, 0))
        self.tire_received_entry = self.works_cell(row, 0, self.tr("tires.received"),
                                                   self.form_entry(row, width=130, placeholder_text=self.tr("tires.date_placeholder")), 130,
                                                   required=True)
        self.tire_until_entry = self.works_cell(row, 1, self.tr("tires.until"),
                                                self.form_entry(row, width=130, placeholder_text=self.tr("tires.date_placeholder")), 130)
        self.tire_price_entry = self.works_cell(row, 2, self.tr("tires.price"), self.form_entry(row, width=120), 120)

        paid_row = ctk.CTkFrame(body, fg_color="transparent")
        paid_row.pack(fill=tk.X, pady=(8, 0))
        self.tire_paid_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(paid_row, text=self.tr("tires.paid"), variable=self.tire_paid_var,
                        font=("Arial", 13)).pack(side=tk.LEFT)

        self.form_label(body, self.tr("tires.notes")).pack(fill=tk.X, pady=(8, 0))
        self.tire_notes_entry = self.form_entry(body, placeholder_text=self.tr("tires.notes_placeholder"))
        self.tire_notes_entry.pack(fill=tk.X)

        self.form_clear_error_on_type((self.tire_size_entry, self.tire_radius_entry, self.tire_brand_entry,
                                       self.tire_quantity_entry,
                                       self.tire_location_entry, self.tire_received_entry, self.tire_until_entry,
                                       self.tire_price_entry))
        return list(section)

    def tire_form_entries(self):
        return (self.tire_size_entry, self.tire_radius_entry, self.tire_brand_entry, self.tire_quantity_entry,
                self.tire_location_entry, self.tire_received_entry, self.tire_until_entry, self.tire_price_entry,
                self.tire_notes_entry)

    def _tire_sizes_in_base(self):
        """Размеры комплектов в базе - разобранные на (ширина/профиль, радиус); один раз на открытие формы"""
        cached = getattr(self, "_tire_sizes_cache", None)
        if cached is None:
            cached = self._tire_sizes_cache = [split_size(t["tire_size"]) for t in self.db.get_all_tire_storage()
                                               if t["tire_size"]]
        return cached

    def tire_width_profile_values(self):
        """Список «ширина/профиль»: сначала те, что уже встречались у вас (частые выше), потом обычные"""
        counts = {}
        for wp, _ in self._tire_sizes_in_base():
            if wp:
                counts[wp] = counts.get(wp, 0) + 1
        used = sorted(counts, key=lambda wp: (-counts[wp], wp))
        return used + [wp for wp in COMMON_WIDTH_PROFILES if wp not in counts]

    def tire_radius_values(self):
        """Список радиусов по порядку (R13 … R22, грузовые R14C …) и ваши необычные (ZR18, R17.5)"""
        values = list(COMMON_RADII)
        for _, radius in self._tire_sizes_in_base():
            if radius and radius not in values:
                values.append(radius)
        return values

    def tire_hide_popups(self):
        for suggest in (getattr(self, "tire_size_suggest", None), getattr(self, "tire_radius_suggest", None)):
            if suggest is not None:
                suggest.hide()

    def reset_tire_form(self, tire_id=None):
        """Чистый раздел «Шины» (4 шт., принято сегодня, хранить полгода) или данные комплекта tire_id"""
        for entry in self.tire_form_entries():
            entry.delete(0, tk.END)
            entry.configure(border_color=self.wh_normal_border)
        self.tire_hide_popups()
        self._tire_sizes_cache = None   # списки размеров - заново из базы
        tire = self.db.get_tire_storage_by_id(tire_id) if tire_id else None
        if tire is None:
            today = date.today()
            self.tire_season_switch.set("")
            self.tire_quantity_entry.insert(0, str(DEFAULT_QUANTITY))
            self.tire_received_entry.insert(0, today.strftime("%d.%m.%Y"))
            self.tire_until_entry.insert(0, default_store_until(today).strftime("%d.%m.%Y"))
            self.tire_rims_var.set(False)
            self.tire_paid_var.set(False)
        else:
            self.tire_season_switch.set(self.tr(f"tires.season_{tire['season']}") if tire["season"] in SEASONS else "")
            width_profile, radius = split_size(tire["tire_size"])
            for entry, value in ((self.tire_size_entry, width_profile), (self.tire_radius_entry, radius),
                                 (self.tire_brand_entry, tire["tire_brand"]),
                                 (self.tire_quantity_entry, tire["quantity"]), (self.tire_location_entry, tire["location"]),
                                 (self.tire_notes_entry, tire["notes"])):
                if value not in (None, ""):
                    entry.insert(0, str(value))
            if tire["received_date"]:
                self.tire_received_entry.insert(0, tire["received_date"].strftime("%d.%m.%Y"))
            if tire["store_until"]:
                self.tire_until_entry.insert(0, tire["store_until"].strftime("%d.%m.%Y"))
            if tire["price"]:
                self.tire_price_entry.insert(0, f"{float(tire['price']):g}")
            self.tire_rims_var.set(tire["with_rims"])
            self.tire_paid_var.set(tire["is_paid"])
            if tire["car_number"]:
                self.fill_wh_car_number(tire["car_number"])
        for entry in self.tire_form_entries():
            if not entry.get():
                self.restore_placeholder(entry)

    def save_tire_storage_form(self):
        """«Принять на хранение» / «Сохранить»: проверка полей, машина (найти или создать), запись в базу"""
        window = self.add_part_form_frame
        season = self.tire_season_labels.get(self.tire_season_switch.get())
        if not season:
            messagebox.showwarning(self.tr("common.attention"), self.tr("tires.msg_choose_season"), parent=window)
            return
        self.tire_hide_popups()
        # Размер из двух полей: «205 55» + «16» → «205/55 R16»; весь размер в первом поле - разбирается сам
        size = size_from_fields(self.tire_size_entry.get(), self.tire_radius_entry.get())
        if size is None:
            self.form_mark_error(self.tire_radius_entry, "tires.msg_bad_radius", window)
            return
        texts = {"tire_size": size,
                 "tire_brand": " ".join(self.tire_brand_entry.get().split()),
                 "location": " ".join(self.tire_location_entry.get().split()).upper()}
        entries = {"tire_size": self.tire_size_entry, "tire_brand": self.tire_brand_entry,   # длинный размер - в 1-м поле
                   "location": self.tire_location_entry}
        for key, limit in TIRE_TEXT_LIMITS.items():
            if len(texts[key]) > limit:
                self.form_mark_error(entries[key], "tires.msg_too_long", window, max=limit)
                return
        try:
            quantity = parse_quantity(self.tire_quantity_entry.get(), allow_empty=False)
        except ValueError:
            self.form_mark_error(self.tire_quantity_entry, "warehouse.msg_quantity_number", window, max=QUANTITY_MAX)
            return
        try:
            received = parse_date(self.tire_received_entry.get())
        except ValueError:
            self.form_mark_error(self.tire_received_entry, "tires.msg_bad_date", window)
            return
        if received > date.today():
            # Принять шины «завтра» нельзя - это опечатка; доход за оплаченное хранение ушёл бы в будущий день
            self.form_mark_error(self.tire_received_entry, "tires.msg_received_future", window)
            return
        try:
            until = parse_date(self.tire_until_entry.get(), allow_empty=True)
        except ValueError:
            self.form_mark_error(self.tire_until_entry, "tires.msg_bad_date", window)
            return
        if until and until < received:
            self.form_mark_error(self.tire_until_entry, "tires.msg_until_before_received", window)
            return
        try:
            price = parse_money(self.tire_price_entry.get(), allow_empty=True)
        except ValueError:
            self.form_mark_error(self.tire_price_entry, "warehouse.msg_price_number", window,
                                 max=self.format_money_limit())
            return
        tire_id = getattr(self, "wh_editing_tire_id", None)
        # Выданные шины ячейку не занимают - правим такой комплект (цену, примечание) без вопроса про ячейку
        editing = self.db.get_tire_storage_by_id(tire_id) if tire_id else None
        taken = None if editing and editing["status"] == STATUS_ISSUED else \
            self.db.tire_location_taken(texts["location"], exclude_id=tire_id)
        if taken and not messagebox.askyesno(
                self.tr("common.attention"),
                self.tr("tires.msg_location_taken", location=texts["location"], tires=self.tire_title(taken)),
                icon="warning", parent=window):
            self.tire_location_entry.configure(border_color=self.FORM_ERROR_BORDER)
            self.tire_location_entry.focus_set()
            return

        car_id = self.wh_form_car_id(require_car=True)
        if car_id is self.WH_CAR_ABORT:
            return
        fields = dict(car_id=car_id, season=season, tire_size=texts["tire_size"] or None,
                      tire_brand=texts["tire_brand"] or None, quantity=quantity, with_rims=self.tire_rims_var.get(),
                      location=texts["location"] or None, received_date=received, store_until=until, price=price,
                      is_paid=self.tire_paid_var.get(), notes=" ".join(self.tire_notes_entry.get().split()) or None)
        if tire_id:
            self.db.update_tire_storage(tire_id, income=self.tire_income_texts, **fields)
            message = self.tr("tires.msg_saved")
        else:
            self.db.add_tire_storage(income=self.tire_income_texts, **fields)
            message = self.tr("tires.msg_accepted")
        self.tires_refresh_money_tabs()
        messagebox.showinfo(self.tr("common.success"), message, parent=window)
        self.hide_add_part_form()
        if getattr(self, "warehouse_page", "parts") != "tires" and getattr(self, "current_tab", "") == "warehouse":
            self.warehouse_show_page("tires")
        else:
            self.refresh_tires()

    # ===== перенос шин из запчастей =====

    def open_tire_transfer(self):
        """Окно: позиции запчастей, похожие на шины, - отметить, какие перенести во вкладку «Шины».
        Явно шины отмечены сразу; «колёса» и заказы «в пути» (купленные шины, а не хранение) - без отметки"""
        candidates = self.db.get_tire_like_warehouse_parts()
        if not candidates:
            messagebox.showinfo(self.tr("common.attention"), self.tr("tires.transfer_none"))
            return
        window = self._tire_transfer_window = ctk.CTkToplevel(self.root)
        window.title(self.tr("tires.transfer_title"))
        window.transient(self.root)
        window.geometry("760x520")
        window.update_idletasks()
        window.geometry(f"+{(window.winfo_screenwidth() - 760) // 2}+{(window.winfo_screenheight() - 520) // 2}")
        ctk.CTkLabel(window, text=self.tr("tires.transfer_hint"), justify=tk.LEFT, anchor="w", wraplength=720,
                     font=("Arial", 13)).pack(fill=tk.X, padx=18, pady=(14, 8))
        listing = ctk.CTkScrollableFrame(window, fg_color="white")
        listing.pack(fill=tk.BOTH, expand=True, padx=18)
        boxes = []
        for part in candidates:
            car = " ".join(x for x in (part["car_brand"], part["car_model"], part["car_number"]) if x) \
                or self.tr("tires.transfer_no_car")
            day = part["received_date"] or part["order_date"]
            text = "  ·  ".join(x for x in (
                self.clean_item_name(part["part_name"]), self.tr("tires.pieces", count=part["quantity"] or 0),
                car + (f" ({self.display_name(part['client_name'])})" if part["client_name"] else ""),
                self.warehouse_status_label(part["status"]), day.strftime("%d.%m.%Y") if day else "") if x)
            var = tk.BooleanVar(value=part["match"] == "strong" and part["status"] != "в пути")
            ctk.CTkCheckBox(listing, text=text, variable=var, font=("Arial", 13)).pack(fill=tk.X, anchor="w", pady=3)
            boxes.append((part, var))

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.pack(fill=tk.X, padx=18, pady=12)

        def set_all(value):
            for _, var in boxes:
                var.set(value)

        def transfer():
            chosen = [part for part, var in boxes if var.get()]
            if not chosen:
                messagebox.showwarning(self.tr("common.attention"), self.tr("tires.transfer_choose"), parent=window)
                return
            if not messagebox.askyesno(self.tr("common.confirm"), self.tr("tires.transfer_confirm", count=len(chosen)),
                                       parent=window):
                return
            moved = sum(1 for part in chosen
                        if self.db.move_warehouse_part_to_tires(part["id"], income=self.tire_income_texts))
            self.tires_refresh_money_tabs()
            close()
            messagebox.showinfo(self.tr("common.success"), self.tr("tires.transfer_done", count=moved))
            self.refresh_warehouse()
            self.refresh_tires()

        def close():
            try:
                window.grab_release()
            except tk.TclError:
                pass
            window.destroy()
            self._tire_transfer_window = None

        ctk.CTkButton(buttons, text=self.tr("tires.transfer_do"), command=transfer, height=38, corner_radius=8,
                      font=("Arial", 14, "bold"), fg_color="#2e7d32", hover_color="#1b5e20").pack(side=tk.LEFT)
        ctk.CTkButton(buttons, text=self.tr("tires.transfer_all"), command=lambda: set_all(True), height=38,
                      fg_color="transparent", border_width=1, border_color="#9e9e9e", text_color="#424242",
                      hover_color="#e0e0e0").pack(side=tk.LEFT, padx=(10, 0))
        ctk.CTkButton(buttons, text=self.tr("tires.transfer_none_btn"), command=lambda: set_all(False), height=38,
                      fg_color="transparent", border_width=1, border_color="#9e9e9e", text_color="#424242",
                      hover_color="#e0e0e0").pack(side=tk.LEFT, padx=(10, 0))
        ctk.CTkButton(buttons, text=self.tr("common.cancel"), command=close, height=38, width=110,
                      fg_color="transparent", border_width=1, border_color="#9e9e9e", text_color="#424242",
                      hover_color="#e0e0e0").pack(side=tk.RIGHT)
        window.protocol("WM_DELETE_WINDOW", close)
        window.bind("<Escape>", lambda e: close())
        window.after(50, lambda: window.winfo_exists() and (window.lift(), window.grab_set()))
