"""Марка и модель машины - одно устройство на все формы
(«Добавить работу», «Записать клиента», склад, «Изменить данные клиента и машины»):
подсказки из справочника «Настройки» → «Марки и модели» и проверка при сохранении."""
import tkinter as tk

SKIP_KEYS = ("Up", "Down", "Return", "Escape", "Tab")


class CarAutocomplete:
    """Подсказки марок и моделей под полями.

    Марка: от первой буквы - список марок. Выбрали марку - модель очищается (если марка другая),
    курсор в модель, список всех её моделей. Модель: при вводе и при входе в поле - модели этой марки.
    Выбрали модель - курсор в next_entry. Ушли из поля - список прячется.
    locked(key) -> True: поле закрыто ("brand" / "model"), подсказки не показываем."""

    def __init__(self, app, brand_entry, model_entry, parent, next_entry=None, locked=None):
        self.app, self.db = app, app.db
        self.brand_entry, self.model_entry = brand_entry, model_entry
        self.next_entry = next_entry
        self.locked = locked or (lambda key: False)
        self.brand_listbox = app.works_popup_listbox(parent)
        self.model_listbox = app.works_popup_listbox(parent)
        self.brand_visible = self.model_visible = False

        brand_entry.bind("<KeyRelease>", self.on_brand_key, add="+")
        brand_entry.bind("<FocusOut>", lambda e: self._hide_later(self.hide_brands), add="+")
        model_entry.bind("<KeyRelease>", self.on_model_key, add="+")
        model_entry.bind("<FocusIn>", self.on_model_key, add="+")
        model_entry.bind("<FocusOut>", lambda e: self._hide_later(self.hide_models), add="+")
        self.brand_listbox.bind("<<ListboxSelect>>", self.on_brand_select)
        self.model_listbox.bind("<<ListboxSelect>>", self.on_model_select)

    # --- показать / спрятать ---
    def _show(self, listbox, entry, values):
        listbox.delete(0, tk.END)
        for value in values:
            listbox.insert(tk.END, value)
        self.app.place_popup(listbox, entry)

    def show_brands(self, brands):
        self._show(self.brand_listbox, self.brand_entry, brands)
        self.brand_visible = True

    def show_models(self, models):
        self._show(self.model_listbox, self.model_entry, models)
        self.model_visible = True

    def hide_brands(self):
        if self.brand_visible:
            self.app.hide_popup(self.brand_listbox)
            self.brand_visible = False

    def hide_models(self):
        if self.model_visible:
            self.app.hide_popup(self.model_listbox)
            self.model_visible = False

    def hide(self):
        self.hide_brands()
        self.hide_models()

    def _hide_later(self, hide):
        """Фокус ушёл из поля (но не в сам список) - спрятать список"""
        widget = self.brand_entry

        def check():
            try:
                if widget.winfo_exists() and widget.focus_get() not in (self.brand_listbox, self.model_listbox):
                    hide()
            except (KeyError, tk.TclError):
                hide()
        widget.after(200, check)

    # --- ввод и выбор ---
    def on_brand_key(self, event=None):
        if event is not None and getattr(event, "keysym", None) in SKIP_KEYS:
            return
        if self.locked("brand"):
            return self.hide_brands()
        text = self.brand_entry.get().strip()
        brands = self.db.search_car_brands(text) if text else []
        if brands and [b.lower() for b in brands] != [text.lower()]:
            self.show_brands(brands)
        else:
            self.hide_brands()   # пусто или уже вписана ровно эта марка

    def on_model_key(self, event=None):
        if event is not None and getattr(event, "keysym", None) in SKIP_KEYS:
            return
        if self.locked("model"):
            return self.hide_models()
        brand = self.brand_entry.get().strip()
        text = self.model_entry.get().strip()
        models = self.db.search_car_models(brand, text) if brand else []
        if models and [m.lower() for m in models] != [text.lower()]:
            self.show_models(models)
        else:
            self.hide_models()

    def on_brand_select(self, event=None):
        selection = self.brand_listbox.curselection()
        if not selection:
            return
        brand = self.brand_listbox.get(selection[0])
        changed = self.brand_entry.get().strip().lower() != brand.lower()
        self.brand_entry.delete(0, tk.END)
        self.brand_entry.insert(0, brand)
        self.hide_brands()
        if changed or not self.model_entry.get().strip():
            self.model_entry.delete(0, tk.END)
        models = self.db.search_car_models(brand, "")
        self.model_entry.focus_set()
        if models and not self.model_entry.get().strip():
            self.show_models(models)

    def on_model_select(self, event=None):
        selection = self.model_listbox.curselection()
        if not selection:
            return
        self.model_entry.delete(0, tk.END)
        self.model_entry.insert(0, self.model_listbox.get(selection[0]))
        self.hide_models()
        if self.next_entry is not None:
            self.next_entry.focus_set()


def catalog_car_names(app, brand_entry, model_entry, window=None, saved=None):
    """Проверка при сохранении: марка и модель - из справочника «Марки и модели».

    saved - (марка, модель) этой машины в базе: если их не меняли - пропускаем
    (старые машины, записанные с маркой не из справочника, сохраняются как раньше).
    Возвращает (марка, модель) с написанием из справочника ("toyota" -> "Toyota", поля тоже поправляются)
    или None - показано предупреждение, поле с красной рамкой и курсором."""
    brand, model = brand_entry.get().strip(), model_entry.get().strip()
    db = app.db
    catalog_brand = db.find_car_brand_name(brand)
    catalog_model = db.find_car_model_name(catalog_brand, model) if catalog_brand else None
    if not catalog_model:
        if saved and brand.lower() == (saved[0] or "").strip().lower() \
                and model.lower() == (saved[1] or "").strip().lower():
            # Не из справочника, но так машина уже записана в базе - оставляем написание из базы
            # (не как вписали: «kia» у записанной «Kia» не должно портить написание)
            catalog_brand, catalog_model = (saved[0] or "").strip(), (saved[1] or "").strip()
        elif not catalog_brand:
            app.form_mark_error(brand_entry, "works.msg_brand_not_in_list", window, brand=brand)
            return None
        else:
            app.form_mark_error(model_entry, "works.msg_model_not_in_list", window, brand=catalog_brand, model=model)
            return None
    for entry, value in ((brand_entry, catalog_brand), (model_entry, catalog_model)):
        if entry.get().strip() != value and entry.cget("state") != "disabled":
            entry.delete(0, tk.END)
            entry.insert(0, value)
    return catalog_brand, catalog_model
