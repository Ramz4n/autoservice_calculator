# -*- coding: utf-8 -*-
"""
Калькулятор для автосервиса
Приложение для учёта работ сотрудников
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date, timedelta
from tkcalendar import DateEntry
import json
import calendar as pycalendar
from PIL import Image, ImageTk
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import subprocess
import tempfile
import threading
import re
import requests
import webbrowser
from urllib.parse import quote
import customtkinter as ctk
from dotenv import load_dotenv

# Импорт класса для работы с базой данных
from database import Database
import web_sync
from i18n import I18n, SUPPORTED_LANGUAGES
from sms_notifications import send_sms_notification
import backup as backup_module

# Стандартная длина VIN
VIN_LENGTH = 17


def get_base_path():
    """Получить базовый путь приложения (работает и для PyInstaller)"""
    if getattr(sys, 'frozen', False):
        # Запущено как exe (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Запущено как скрипт
        return os.path.dirname(__file__)


# Загрузка переменных окружения из config/.env
load_dotenv(os.path.join(get_base_path(), 'config', '.env'))

# Токен Telegram бота для уведомлений
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')


# Базовый путь приложения
BASE_PATH = get_base_path()

# Путь к файлу настроек приложения
SETTINGS_FILE = os.path.join(BASE_PATH, 'config', 'settings.json')

# Путь к файлу со списком запчастей для автодополнения
SPARE_PARTS_FILE = os.path.join(BASE_PATH, 'config', 'spare_parts.txt')

# Имена (страны СНГ) для подсказки в поле "Имя" окна "Записать клиента"
FIRST_NAMES_FILE = os.path.join(BASE_PATH, 'config', 'first_names.txt')

# Папка с переводами интерфейса
LOCALES_DIR = os.path.join(BASE_PATH, 'config', 'locales')

# Папка для автоматических локальных бэкапов -- рядом с программой, всегда
# работает без какой-либо настройки (в отличие от опциональной облачной
# папки, которую пользователь указывает сам в настройках).
LOCAL_BACKUP_DIR = os.path.join(BASE_PATH, 'Backup')

# Настройка темы CustomTkinter
ctk.set_appearance_mode("light")  # "dark" или "light"
ctk.set_default_color_theme("blue")  # "blue", "green", "dark-blue"


def load_app_settings():
    """Загрузить настройки приложения из JSON файла"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'master_percent': 50}


def booking_time_slots():
    """Время записи: от начала до конца рабочего дня включительно, каждые slot_duration_minutes
    (те же настройки использует Telegram-бот и сайт онлайн-записи)"""
    s = load_app_settings()
    start, end = int(s.get('working_hours_start', 10)) * 60, int(s.get('working_hours_end', 20)) * 60
    step = max(15, int(s.get('slot_duration_minutes', 120)))
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(start, end + 1, step)]


# Маска телефона: скобки и тире стоят всегда, "_" - позиции цифр
PHONE_MASK = "+7(___)-___-__-__"
PHONE_SLOTS = [i for i, c in enumerate(PHONE_MASK) if c == "_"]


def phone_mask_digits(text):
    """Цифры номера после +7 (до 10). Понимает и маску +7(909)-58_-__-__, и обычный ввод 89095813910"""
    if len(text) == len(PHONE_MASK) and text.startswith("+7("):
        return "".join(text[pos] for pos in PHONE_SLOTS if text[pos].isdigit())
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    return digits[-10:]


def format_phone_ru(digits):
    """Подставить до 10 цифр после +7 в маску: "909581" -> +7(909)-581-__-__"""
    chars = list(PHONE_MASK)
    for pos, d in zip(PHONE_SLOTS, digits[:10]):
        chars[pos] = d
    return "".join(chars)


def save_app_settings(settings):
    """Сохранить настройки приложения в JSON файл"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")


def send_telegram_notification(user_id, message, with_menu=False):
    """Отправить уведомление клиенту в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": user_id,
            "text": message,
            "parse_mode": "HTML"
        }

        # Добавляем кнопки если нужно
        if with_menu:
            import json
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📅 Записаться снова", "callback_data": "book"}],
                    [{"text": "📋 Главное меню", "callback_data": "back_to_menu"}]
                ]
            }
            data["reply_markup"] = json.dumps(keyboard)

        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Ошибка отправки уведомления в Telegram: {e}")
        return False


class TreeviewTooltip:
    """Всплывающая подсказка для Treeview при наведении на ячейку"""

    def __init__(self, treeview, columns=None, text_provider=None):
        self.treeview = treeview
        self.columns = columns  # Список колонок для которых показывать tooltip (None = все)
        self.text_provider = text_provider  # callable(item_id, col_name) -> str | None, если задан - переопределяет текст ячейки
        self.tooltip = None
        self.current_item = None
        self.current_column = None

        # Привязываем события
        self.treeview.bind('<Motion>', self.on_motion)
        self.treeview.bind('<Leave>', self.hide_tooltip)

    def on_motion(self, event):
        """Обработка движения мыши"""
        # Определяем элемент и колонку под курсором
        item = self.treeview.identify_row(event.y)
        column = self.treeview.identify_column(event.x)

        if not item or not column:
            self.hide_tooltip()
            return

        # Преобразуем #1, #2 в имя колонки. Номер считается по видимым колонкам (displaycolumns),
        # а индекс значения в values - по полному списку columns
        display_index = int(column.replace('#', '')) - 1
        columns = list(self.treeview['columns'])
        display_columns = list(self.treeview['displaycolumns'])
        if display_columns == ['#all']:
            display_columns = columns

        if display_index < 0 or display_index >= len(display_columns):
            self.hide_tooltip()
            return

        col_name = display_columns[display_index]
        col_index = columns.index(col_name)

        # Проверяем, нужно ли показывать tooltip для этой колонки
        if self.columns and col_name not in self.columns:
            self.hide_tooltip()
            return

        # Если это тот же элемент и колонка - не обновляем
        if item == self.current_item and column == self.current_column:
            return

        self.current_item = item
        self.current_column = column

        if self.text_provider:
            # Кастомный текст (может отличаться от того, что показано в ячейке)
            text = self.text_provider(item, col_name)
            if text:
                self.show_tooltip(event.x_root, event.y_root, text)
            else:
                self.hide_tooltip()
            return

        # Получаем текст ячейки
        values = self.treeview.item(item, 'values')
        if not values or col_index >= len(values):
            self.hide_tooltip()
            return

        text = str(values[col_index])

        # Показываем tooltip только если текст достаточно длинный
        if len(text) > 20:
            self.show_tooltip(event.x_root, event.y_root, text)
        else:
            self.hide_tooltip()

    def show_tooltip(self, x, y, text):
        """Показать tooltip"""
        self.hide_tooltip()

        self.tooltip = tk.Toplevel(self.treeview)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x + 15}+{y + 10}")

        # Создаём рамку и текст
        frame = tk.Frame(self.tooltip, bg='#ffffe0', relief='solid', borderwidth=1)
        frame.pack()

        # Разбиваем длинный текст на строки, сохраняя явные переносы строк (\n)
        max_width = 60
        lines = []
        for paragraph in text.split('\n'):
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current_line = ""
            for word in words:
                if len(current_line + " " + word) <= max_width:
                    current_line = (current_line + " " + word).strip()
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)

        wrapped_text = '\n'.join(lines) if lines else text

        label = tk.Label(frame, text=wrapped_text, bg='#ffffe0', fg='black',
                        font=('Segoe UI', 11), justify=tk.LEFT, padx=8, pady=5)
        label.pack()

        # Не даём подсказке выйти за границы экрана
        self.tooltip.update_idletasks()
        tip_width = self.tooltip.winfo_width()
        tip_height = self.tooltip.winfo_height()
        screen_width = self.tooltip.winfo_screenwidth()
        screen_height = self.tooltip.winfo_screenheight()

        pos_x = x + 15
        pos_y = y + 10
        if pos_x + tip_width > screen_width:
            pos_x = x - tip_width - 15
            if pos_x < 0:
                pos_x = max(0, screen_width - tip_width)
        if pos_y + tip_height > screen_height:
            pos_y = y - tip_height - 10
            if pos_y < 0:
                pos_y = max(0, screen_height - tip_height)

        self.tooltip.wm_geometry(f"+{pos_x}+{pos_y}")

    def hide_tooltip(self, event=None):
        """Скрыть tooltip"""
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None
        self.current_item = None
        self.current_column = None


class LabelTooltip:
    """Всплывающая подсказка для CTkLabel с детальной информацией"""

    def __init__(self, label, format_currency_func, is_expense=True):
        self.label = label
        self.format_currency = format_currency_func
        self.is_expense = is_expense  # True для расходов, False для доходов
        self.tooltip = None
        self.data = []  # Список кортежей (category, description, amount, date)

        # Привязываем события
        self.label.bind('<Enter>', self.show_tooltip)
        self.label.bind('<Leave>', self.hide_tooltip)

    def set_data(self, data):
        """Установить данные для tooltip"""
        self.data = data

    def show_tooltip(self, event):
        """Показать tooltip"""
        if not self.data:
            return

        self.hide_tooltip()

        # Получаем позицию label на экране
        x = self.label.winfo_rootx()
        y = self.label.winfo_rooty() + self.label.winfo_height() + 5

        self.tooltip = tk.Toplevel(self.label)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")

        # Цвета в зависимости от типа
        if self.is_expense:
            amount_color = '#c62828'  # Красный для расходов
            sign = "-"
        else:
            amount_color = '#2e7d32'  # Зелёный для доходов
            sign = "+"

        # Создаём рамку
        frame = tk.Frame(self.tooltip, bg='#fffde7', relief='solid', borderwidth=1)
        frame.pack()

        # Заголовок
        header = tk.Label(frame, text="Категория | Описание | Сумма | Дата",
                         bg='#fffde7', fg='#333', font=('Segoe UI', 10, 'bold'),
                         padx=10, pady=5)
        header.pack(anchor=tk.W)

        # Разделитель
        tk.Frame(frame, bg='#ccc', height=1).pack(fill=tk.X, padx=5)

        # Данные (максимум 15 записей)
        for i, (category, desc, amount, expense_date) in enumerate(self.data[:15]):
            amount = float(amount)
            # Форматируем дату
            if isinstance(expense_date, str):
                display_date = datetime.strptime(expense_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            else:
                display_date = expense_date.strftime('%d.%m.%Y')

            # Обрезаем длинное описание
            short_desc = desc[:25] + '...' if len(desc) > 25 else desc
            short_cat = category[:15] + '...' if len(category) > 15 else category

            # Строка с данными (сумму выводим отдельно с цветом)
            row_frame = tk.Frame(frame, bg='#fffde7')
            row_frame.pack(anchor=tk.W, fill=tk.X, padx=10)

            text_part = f"{short_cat} | {short_desc} | "
            tk.Label(row_frame, text=text_part, bg='#fffde7', fg='#333',
                    font=('Segoe UI', 9), pady=2, anchor=tk.W).pack(side=tk.LEFT)

            # Сумма с цветом и знаком
            amount_text = f"{sign}{self.format_currency(amount)}"
            tk.Label(row_frame, text=amount_text, bg='#fffde7', fg=amount_color,
                    font=('Segoe UI', 9, 'bold'), pady=2, anchor=tk.W).pack(side=tk.LEFT)

            tk.Label(row_frame, text=f" | {display_date}", bg='#fffde7', fg='#333',
                    font=('Segoe UI', 9), pady=2, anchor=tk.W).pack(side=tk.LEFT)

        # Если записей больше 15
        if len(self.data) > 15:
            more_label = tk.Label(frame, text=f"... и ещё {len(self.data) - 15} записей",
                                 bg='#fffde7', fg='#666', font=('Segoe UI', 9, 'italic'),
                                 padx=10, pady=5)
            more_label.pack(anchor=tk.W)

    def hide_tooltip(self, event=None):
        """Скрыть tooltip"""
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class AutoHideLabel(ctk.CTkLabel):
    """Надпись, которая занимает место только когда в ней есть текст.
    auto_pack - параметры pack(), с которыми её показывать"""

    def __init__(self, master, auto_pack=None, **kwargs):
        super().__init__(master, **kwargs)
        self.auto_pack = auto_pack or {}

    def configure(self, require_redraw=False, **kwargs):
        super().configure(require_redraw, **kwargs)
        if "text" in kwargs:
            if kwargs["text"]:
                self.pack(**self.auto_pack)
            else:
                self.pack_forget()


class WorkItemsList(ctk.CTkFrame):
    """Список позиций вкладки "Добавить работу" (работы / запчасти): строки "название ... цена ✕".
    Повторяет нужные методы ttk.Treeview (insert / delete / get_children / index),
    поэтому остальной код работает с ним как с прежней таблицей.
    on_remove(item_id) - нажали ✕; on_change() - список изменился; tag_text - метка у позиций с tags=("warehouse",)"""

    def __init__(self, master, empty_text, on_remove, on_change=None, tag_text=""):
        super().__init__(master, fg_color="transparent")
        self.empty_text = empty_text
        self.on_remove = on_remove
        self.on_change = on_change
        self.tag_text = tag_text
        self._items = []   # [(item_id, values, tags)]
        self._counter = 0
        self._redraw()

    def insert(self, parent, index, values=(), tags=()):
        self._counter += 1
        item_id = f"I{self._counter:04d}"
        self._items.append((item_id, tuple(values), tuple(tags)))
        self._redraw()
        return item_id

    def delete(self, *item_ids):
        self._items = [item for item in self._items if item[0] not in item_ids]
        self._redraw()

    def get_children(self, item=""):
        return tuple(item[0] for item in self._items)

    def update_item(self, item_id, values):
        """Поменять название / цену строки (метки остаются)"""
        self._items = [(iid, tuple(values) if iid == item_id else vals, tags) for iid, vals, tags in self._items]
        self._redraw()

    def index(self, item_id):
        return self.get_children().index(item_id)

    def _redraw(self):
        for widget in self.winfo_children():
            widget.destroy()
        if not self._items:
            ctk.CTkLabel(self, text=self.empty_text, text_color="gray", font=("Arial", 12),
                         anchor="w").pack(fill=tk.X, pady=4)
        for i, (item_id, values, tags) in enumerate(self._items):
            name, price, struck = (list(values) + ["", "", ""])[:3]
            row = ctk.CTkFrame(self, fg_color="#f7f9fa" if i % 2 == 0 else "white", corner_radius=6)
            row.pack(fill=tk.X, pady=1)
            ctk.CTkButton(row, text="✕", width=28, height=26, corner_radius=6, fg_color="transparent",
                          text_color="#c62828", hover_color="#ffebee", font=("Arial", 13, "bold"),
                          command=lambda item_id=item_id: self.on_remove(item_id)).pack(side=tk.RIGHT, padx=(4, 6))
            prepaid = bool(struck) or (price and not any(ch.isdigit() for ch in str(price)))  # "оплачено ранее"
            ctk.CTkLabel(row, text=price, font=("Arial", 14, "italic") if prepaid else ("Arial", 14),
                         text_color="#2e7d32" if prepaid else None, anchor="e").pack(side=tk.RIGHT)
            if struck:
                # Оплачено ранее: настоящая цена - зачёркнутой
                ctk.CTkLabel(row, text=struck, text_color="gray50", anchor="e",
                             font=ctk.CTkFont(family="Arial", size=14, overstrike=True)).pack(side=tk.RIGHT, padx=(0, 6))
            ctk.CTkLabel(row, text=name, font=("Arial", 14), anchor="w", justify="left",
                         wraplength=420).pack(side=tk.LEFT, padx=10, pady=4)
            if "warehouse" in tags and self.tag_text:
                ctk.CTkLabel(row, text=self.tag_text, font=("Arial", 11, "bold"), text_color="white",
                             fg_color="#1565c0", corner_radius=6, height=20).pack(side=tk.LEFT, padx=(0, 6))
        if self.on_change:
            self.on_change()


class ClientCarChips:
    """Машины клиента кнопками в строку (вместо выпадающего списка). Повторяет нужное от CTkComboBox:
    configure(values=..., text_color=...), set(), get() - остальной код работает с ним как с прежним списком.
    Выбранная машина синяя; красный text_color - ждём выбора (рамки красные).
    Строка видна, только когда у клиента есть хотя бы одна машина"""
    PER_LINE = 3      # кнопок с машинами в одной строке, дальше - перенос
    PICK_COLOR = "#c62828"

    def __init__(self, master, label, new_car_value, select_car_value, new_car_text, command, pack_kwargs,
                 before_select=None):
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        self.before_select = before_select   # before_select(value) -> False - выбор отменён
        self.label = label
        self.new_car_value = new_car_value
        self.select_car_value = select_car_value
        self.new_car_text = new_car_text
        self.command = command
        self.pack_kwargs = pack_kwargs
        self._values = []
        self._value = ""
        self._pick = False

    def configure(self, values=None, text_color=None, **kwargs):
        if values is not None:
            self._values = list(values)
        if text_color is not None:
            self._pick = text_color == self.PICK_COLOR
        self._redraw()

    def set(self, value):
        self._value = value or ""
        self._redraw()

    def get(self):
        return self._value

    def _click(self, value):
        if value == self._value:
            return
        if self.before_select and not self.before_select(value):
            return
        self.set(value)
        if self.command:
            self.command(value)

    def _redraw(self):
        for widget in self.frame.winfo_children():
            widget.destroy()
        cars = [v for v in self._values if v not in (self.new_car_value, self.select_car_value, "")]
        if not cars:
            self.frame.pack_forget()
            return
        pick = self._pick or self._value == self.select_car_value
        ctk.CTkLabel(self.frame, text=self.label, font=("Arial", 12), text_color="#37474f").grid(
            row=0, column=0, sticky="nw", padx=(0, 8), pady=(4, 0))
        lines = ctk.CTkFrame(self.frame, fg_color="transparent")
        lines.grid(row=0, column=1, sticky="w")
        chips = cars + [self.new_car_value]
        for i, value in enumerate(chips):
            if i % self.PER_LINE == 0:
                line = ctk.CTkFrame(lines, fg_color="transparent")
                line.pack(anchor="w", pady=(0, 4))
            is_car = value != self.new_car_value
            selected = value == self._value and value != self.select_car_value
            red = pick and is_car
            ctk.CTkButton(line, text=value if is_car else self.new_car_text, width=10, height=28, corner_radius=14,
                          font=("Arial", 13, "bold" if selected else "normal"),
                          fg_color="#1565c0" if selected else "transparent",
                          hover_color="#0d47a1" if selected else "#e3f2fd",
                          text_color="white" if selected else (self.PICK_COLOR if red else "#0d47a1"),
                          border_width=0 if selected else 1,
                          border_color=self.PICK_COLOR if red else "#90caf9",
                          command=lambda v=value: self._click(v)).pack(side=tk.LEFT, padx=(0, 6))
        self.frame.pack(**self.pack_kwargs)


class AutoServiceApp:
    """Главный класс приложения"""

    def __init__(self, root, current_user=None):
        self.root = root
        self.current_user = current_user or {"id": 0, "username": "?", "full_name": "", "role": "user"}
        self.logged_out = False

        # Язык интерфейса (переключение — в настройках, применяется после перезапуска)
        self.i18n = I18n(LOCALES_DIR, self.load_settings().get('language', 'ru'))
        self.tr = self.i18n.t

        self.root.protocol("WM_DELETE_WINDOW", self._confirm_close)
        self.root.title(self.tr("app.window_title"))
        self.root.minsize(800, 600)

        self.db = Database()
        self.spare_parts_list = self.load_spare_parts()

        # Настройка стилей
        self.setup_styles()

        # Основной контейнер
        self.main_container = ctk.CTkFrame(root, fg_color="transparent")
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Боковое меню слева
        self.sidebar = ctk.CTkFrame(self.main_container, width=180, corner_radius=10)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        self.sidebar.pack_propagate(False)  # Фиксированная ширина

        # Заголовок меню
        self.sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text=self.tr("menu.title"),
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.sidebar_title.pack(pady=(20, 2))

        # Версия приложения — под заголовком меню
        try:
            from updater import APP_VERSION as _app_version
        except Exception:
            _app_version = "?"
        ctk.CTkLabel(
            self.sidebar,
            text=f"v{_app_version}",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(pady=(0, 18))

        # Пункты меню
        _is_admin = self.current_user.get("role") == "admin"
        self.menu_items = [
            (self.tr("menu.add_work"), "works"),
            (self.tr("menu.bookings"), "bookings"),
            (self.tr("menu.warehouse"), "warehouse"),
            (self.tr("menu.staff"), "staff"),
            *([(self.tr("menu.reports"), "reports"), (self.tr("menu.expenses"), "expenses"), (self.tr("menu.statistics"), "statistics")] if _is_admin else []),
            #("Поиск деталей", "parts_search"),
            (self.tr("menu.settings"), "settings")
        ]

        self.menu_buttons = {}
        self.current_tab = "works"

        for text, name in self.menu_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=text,
                command=lambda n=name: self.switch_tab(n),
                height=40,
                corner_radius=8,
                fg_color="#1565c0" if name == "works" else "transparent",
                text_color="white" if name == "works" else ("gray10", "gray90"),
                hover_color=("#1976d2", "#1976d2"),
                anchor="w",
                font=ctk.CTkFont(size=14)
            )
            btn.pack(fill=tk.X, pady=3, padx=10)
            self.menu_buttons[name] = btn

        # Имя пользователя + кнопка выхода внизу сайдбара
        sidebar_bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        sidebar_bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        ctk.CTkLabel(
            sidebar_bottom,
            text="👤 " + (self.current_user.get("full_name") or self.current_user.get("username", "?")),
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
            wraplength=140
        ).pack(fill=tk.X, pady=(0, 6))
        ctk.CTkButton(
            sidebar_bottom,
            text="🔄 " + self.tr("menu.check_update"),
            command=self._check_update_manual,
            height=44,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color="gray",
            text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray25"),
            font=ctk.CTkFont(size=11),
            anchor="center"
        ).pack(fill=tk.X, pady=(0, 6))
        ctk.CTkButton(
            sidebar_bottom,
            text="🚪 " + self.tr("menu.logout"),
            command=self._logout,
            height=34,
            corner_radius=8,
            fg_color="#c62828",
            hover_color="#b71c1c",
            font=ctk.CTkFont(size=13)
        ).pack(fill=tk.X)

        # Контейнер для контента справа
        self.content_container = ctk.CTkFrame(self.main_container, corner_radius=10)
        self.content_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Словарь для хранения фреймов контента
        self.content_frames = {}

        # Вкладка добавления работ
        self.works_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["works"] = self.works_frame
        self.setup_works_tab()

        # Вкладка записей из Telegram
        self.bookings_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["bookings"] = self.bookings_frame
        self.setup_bookings_tab()

        # Вкладка склада запчастей
        self.warehouse_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["warehouse"] = self.warehouse_frame
        self.setup_warehouse_tab()

        # Вкладка сотрудников: расписание выходных, отпусков, больничных
        self.staff_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["staff"] = self.staff_frame
        self.setup_staff_tab()

        # Вкладка отчётов
        self.reports_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["reports"] = self.reports_frame
        self.setup_reports_tab()

        # Вкладка расходов и доходов
        self.expenses_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["expenses"] = self.expenses_frame
        self.setup_expenses_tab()

        # Вкладка статистики
        self.statistics_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["statistics"] = self.statistics_frame
        self.setup_statistics_tab()

        # Вкладка поиска деталей
        self.parts_search_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["parts_search"] = self.parts_search_frame
        self.parts_search_history = []
        self.setup_parts_search_tab()

        # Вкладка настроек с подвкладками
        self.add_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["settings"] = self.add_frame

        # Создаём вложенный Tabview для подвкладок настроек
        self.add_notebook = ctk.CTkTabview(self.add_frame)
        self.add_notebook.pack(fill=tk.BOTH, expand=True)

        # Показываем первую вкладку по умолчанию
        self.works_frame.pack(fill=tk.BOTH, expand=True)

        # Подвкладка работников
        self.add_notebook.add(self.tr("settings.workers_tab"))
        self.workers_frame = self.add_notebook.tab(self.tr("settings.workers_tab"))
        self.setup_workers_tab()

        # Подвкладка марок и моделей
        self.add_notebook.add(self.tr("settings.cars_tab"))
        self.cars_frame = self.add_notebook.tab(self.tr("settings.cars_tab"))
        self.setup_cars_tab()

        # Подвкладка ключевых слов
        self.add_notebook.add(self.tr("settings.keywords_tab"))
        self.keywords_frame = self.add_notebook.tab(self.tr("settings.keywords_tab"))
        self.setup_keywords_tab()

        # Подвкладка запчастей
        self.add_notebook.add(self.tr("settings.spareparts_tab"))
        self.spare_parts_frame = self.add_notebook.tab(self.tr("settings.spareparts_tab"))
        self.setup_spare_parts_tab()

        # Подвкладка языка интерфейса
        self.add_notebook.add(self.tr("settings.language_tab"))
        self.language_frame = self.add_notebook.tab(self.tr("settings.language_tab"))
        self.setup_language_tab()

        # Подвкладка пользователей (только для admin)
        if self.current_user.get("role") == "admin":
            self.add_notebook.add(self.tr("settings.users_tab"))
            self.users_tab_frame = self.add_notebook.tab(self.tr("settings.users_tab"))
            self.setup_users_tab()

        # Подвкладка резервного копирования
        self.add_notebook.add(self.tr("settings.backup_tab"))
        self.backup_frame = self.add_notebook.tab(self.tr("settings.backup_tab"))
        self.setup_backup_tab()

        # Подвкладка "О программе" (всегда последняя)
        self.add_notebook.add(self.tr("settings.about_tab"))
        self.about_frame = self.add_notebook.tab(self.tr("settings.about_tab"))
        self.setup_about_tab()

        # Окно "Записать клиента" строим заранее, когда программа уже открылась - потом оно открывается сразу
        self.root.after(2500, self._prebuild_booking_window)
        self.root.after(3500, self._prebuild_part_window)

        # Загрузка данных
        self.refresh_workers_list()
        self.refresh_workers_combo()
        self.refresh_bookings_combo()
        self.refresh_expenses()
        self.refresh_keywords_list()
        self.refresh_spare_parts_list()
        self.refresh_bookings()

    def switch_tab(self, tab_name):
        """Переключение между вкладками бокового меню"""
        # Скрываем все фреймы
        for frame in self.content_frames.values():
            frame.pack_forget()

        # Показываем выбранный фрейм
        self.content_frames[tab_name].pack(fill=tk.BOTH, expand=True)

        # Обновляем стили кнопок меню
        for name, btn in self.menu_buttons.items():
            if name == tab_name:
                btn.configure(fg_color="#1565c0", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=("gray10", "gray90"))

        self.current_tab = tab_name

        # Вызываем обработчик смены вкладки
        self.on_tab_changed()

    def on_tab_changed(self):
        """Обработчик переключения вкладок"""
        current_tab = self.current_tab
        # Ушли с вкладки - выбор периода снова закрыт паролем
        for tab, lock in getattr(self, "period_locks", {}).items():
            if current_tab != tab and lock["unlocked"]:
                self.lock_period(tab)
        if current_tab == "reports":
            # Автоматически обновляем отчёт при переключении на вкладку
            self.generate_report(show_empty_message=False)
        elif current_tab == "bookings":
            # Автоматически обновляем записи при переключении на вкладку
            self.refresh_bookings()
        elif current_tab == "works":
            # Автоматически обновляем список записей для выбора клиента
            self.refresh_bookings_combo()
            # Запчасти со склада - как сейчас на складе (оплату / цену могли поменять)
            self.works_sync_warehouse_parts()
            # и список мастеров - кто сегодня по расписанию отсутствует
            self.refresh_workers_combo()
        elif current_tab == "staff":
            self.refresh_staff_tab()
        elif current_tab == "warehouse":
            # Автоматически обновляем список запчастей на складе
            self.refresh_warehouse()
        elif current_tab == "statistics":
            # Автоматически обновляем статистику при переключении на вкладку
            self.generate_statistics(show_empty_message=False)

    def format_currency(self, amount):
        """Форматирование суммы в формат: 1.000.000 руб."""
        # Определяем знак
        sign = "-" if amount < 0 else ""
        amount = abs(amount)

        # Форматируем число с двумя знаками после запятой
        formatted = f"{amount:.2f}"
        # Разделяем на целую и дробную части
        parts = formatted.split('.')
        integer_part = parts[0]
        decimal_part = parts[1]

        # Добавляем точки как разделители тысяч
        integer_with_separators = ""
        for i, digit in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                integer_with_separators = "." + integer_with_separators
            integer_with_separators = digit + integer_with_separators

        # Возвращаем отформатированную строку
        return f"{sign}{integer_with_separators},{decimal_part} руб."

    def get_work_line_items(self, work_id, description, amount, items_json=None):
        """Разбить работу на отдельные позиции (название, цена).
        Использует сохранённый items_json для точных цен; если его нет (старые записи) —
        делит сумму поровну между строками описания."""
        if items_json is None:
            items_json = self.db.get_work_items_json(work_id)
        if items_json:
            try:
                parsed = json.loads(items_json)
                if isinstance(parsed, list) and parsed:
                    return [(it["name"], float(it["price"])) for it in parsed]
            except (TypeError, ValueError, KeyError):
                pass

        amount = float(amount or 0)
        lines = [l.strip() for l in (description or "").split("\n") if l.strip()]
        if not lines:
            return []
        if len(lines) == 1:
            return [(lines[0], amount)]
        price_each = amount / len(lines)
        return [(line, price_each) for line in lines]

    def load_settings(self):
        """Загрузить настройки из JSON файла"""
        return load_app_settings()

    def load_spare_parts(self):
        """Загрузить список запчастей из текстового файла (по одной на строку)"""
        try:
            with open(SPARE_PARTS_FILE, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def load_first_names(self):
        """Загрузить список имён для подсказки (по одному на строку, # - комментарий)"""
        if not hasattr(self, "_first_names"):
            names = []
            try:
                with open(FIRST_NAMES_FILE, 'r', encoding='utf-8') as f:
                    names = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            except FileNotFoundError:
                pass
            # Порядок как в файле - вверху самые частые (русские), повторы убираем
            self._first_names = list(dict.fromkeys(names))
        return self._first_names

    def attach_phone_mask(self, entry):
        """Поле телефона с маской +7(___)-___-__-__ (номер читать через phone_mask_digits,
        подставлять через set_phone_value)"""
        entry.delete(0, tk.END)
        entry.insert(0, PHONE_MASK)

        # Ввод номера по маске +7(___)-___-__-__: цифры стоят на своих позициях,
        # удалённая цифра заменяется на "_", остальные не сдвигаются
        def set_phone_text(text):
            entry.delete(0, tk.END)
            entry.insert(0, text)

        def phone_slots_in(start, end):
            """Номера позиций цифр (0..9), попадающих в диапазон символов [start, end)"""
            return [i for i, pos in enumerate(PHONE_SLOTS) if start <= pos < end]

        def put_phone_digits(slot, digits):
            """Записать цифры подряд начиная с позиции slot, курсор - за последней"""
            chars = list(entry.get())
            for d in digits:
                if slot >= len(PHONE_SLOTS):
                    break
                chars[PHONE_SLOTS[slot]] = d
                slot += 1
            set_phone_text("".join(chars))
            entry.icursor(PHONE_SLOTS[slot] if slot < len(PHONE_SLOTS) else len(PHONE_MASK))

        def clear_phone_selection():
            """Стереть выделенные цифры, вернуть позицию начала выделения (или None)"""
            if not entry.select_present():
                return None
            start, end = entry.index("sel.first"), entry.index("sel.last")
            chars = list(entry.get())
            for i in phone_slots_in(start, end):
                chars[PHONE_SLOTS[i]] = "_"
            set_phone_text("".join(chars))
            entry.icursor(start)
            return start

        def on_phone_key(event):
            if event.state & 0x4:  # Ctrl+C / Ctrl+V / Ctrl+A - стандартное поведение
                return None
            cursor = entry.index(tk.INSERT)
            if event.keysym == "BackSpace":
                if clear_phone_selection() is None:
                    before = phone_slots_in(0, cursor)
                    if before:
                        slot = before[-1]
                        chars = list(entry.get())
                        chars[PHONE_SLOTS[slot]] = "_"
                        set_phone_text("".join(chars))
                        entry.icursor(PHONE_SLOTS[slot])
                return "break"
            if event.keysym == "Delete":
                if clear_phone_selection() is None:
                    after = phone_slots_in(cursor, len(PHONE_MASK))
                    if after:
                        chars = list(entry.get())
                        chars[PHONE_SLOTS[after[0]]] = "_"
                        set_phone_text("".join(chars))
                        entry.icursor(PHONE_SLOTS[after[0]])
                return "break"
            if event.char.isdigit():
                start = clear_phone_selection()
                if start is not None:
                    cursor = start
                after = phone_slots_in(cursor, len(PHONE_MASK))
                if after:
                    put_phone_digits(after[0], event.char)
                return "break"
            # Буквы и прочие символы не пропускаем; стрелки, Tab, Enter и т.п. (без символа) - как обычно
            return "break" if event.char.isprintable() and event.char else None

        def on_phone_paste(event):
            try:
                digits = ''.join(c for c in entry.clipboard_get() if c.isdigit())
            except tk.TclError:
                return "break"
            if not digits:
                return "break"
            if len(digits) >= 10:
                # Номер целиком: 89095813910 / 79095813910 / 9095813910
                if len(digits) == 11 and digits[0] in "78":
                    digits = digits[1:]
                set_phone_text(PHONE_MASK)
                put_phone_digits(0, digits[:10])
            else:
                start = clear_phone_selection()
                cursor = start if start is not None else entry.index(tk.INSERT)
                after = phone_slots_in(cursor, len(PHONE_MASK))
                if after:
                    put_phone_digits(after[0], digits)
            return "break"

        def on_phone_click(event):
            # В пустое поле курсор ставим на первую цифру, а не туда, куда попал клик
            if not any(c.isdigit() for c in entry.get()[2:]):
                entry.after_idle(lambda: entry.icursor(PHONE_SLOTS[0]))

        entry.bind("<KeyPress>", on_phone_key)
        entry.bind("<<Paste>>", on_phone_paste)
        entry.bind("<<Cut>>", lambda e: "break")
        entry.bind("<ButtonRelease-1>", on_phone_click)
        entry.bind("<FocusIn>", on_phone_click)

    def snapshot_fields(self, fields):
        """Текущие значения полей {ключ: поле} - чтобы потом понять, что подставил поиск"""
        return {key: field.get() for key, field in fields.items()}

    def autofilled_diff(self, fields, before):
        """Какие поля изменились после поиска (их подставила программа): {ключ: значение}"""
        after = self.snapshot_fields(fields)
        return {key: value for key, value in after.items() if value != before[key]}

    def undo_autofill(self, fields, filled):
        """Стереть подставленное поиском по прошлому номеру. Поле, которое уже поправили руками, не трогаем"""
        for key, value in filled.items():
            field = fields[key]
            if field.get() != value:
                continue
            if value.startswith("+7("):
                self.set_phone_value(field, "")
            else:
                field.delete(0, tk.END)

    def set_phone_value(self, entry, phone):
        """Подставить номер в поле с маской (+79095813910 / 89095813910 / пусто)"""
        entry.delete(0, tk.END)
        entry.insert(0, format_phone_ru(phone_mask_digits(phone or "")))

    # ===== Оформление окон-форм ("Записать клиента", "Добавить запчасть"): блоки-карточки, поля во всю ширину =====
    FORM_CARD_BORDER = "#dfe3e8"
    FORM_STATE_BORDERS = {"found": "#66bb6a", "new": "#ffa726"}  # машина найдена / новая машина
    FORM_STATE_COLORS = {"found": "#2e7d32", "new": "#ef6c00", "warn": "#ef6c00"}
    FORM_ERROR_BORDER = "#e53935"

    def form_content(self, window, width=470):
        """Область формы в окне; width - ширина формы"""
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(fill=tk.BOTH, expand=True, padx=18, pady=(12, 0))
        tk.Frame(content, width=width, height=0).pack()
        return content

    def form_section(self, content, title):
        """Блок формы: заголовок и белая карточка; возвращает (карточка, область для полей)"""
        ctk.CTkLabel(content, text=title.rstrip(':').upper(), font=("Arial", 12, "bold"),
                     text_color="#607d8b", anchor="w").pack(fill=tk.X, padx=4, pady=(4, 2))
        card = ctk.CTkFrame(content, fg_color="white", corner_radius=10, border_width=1,
                            border_color=self.FORM_CARD_BORDER)
        card.pack(fill=tk.X, pady=(0, 8))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill=tk.X, padx=14, pady=10)
        return card, body

    def form_label(self, parent, text, required=False):
        """Подпись над полем; required - звёздочка у обязательного поля"""
        return ctk.CTkLabel(parent, text=text.rstrip(":") + (" *" if required else ""), font=("Arial", 12),
                            text_color="#37474f", anchor="w")

    def form_entry(self, parent, **kwargs):
        return ctk.CTkEntry(parent, height=34, font=("Arial", 14), corner_radius=8, **kwargs)

    def form_popup_listbox(self, parent, **kwargs):
        """Список подсказок (марки, модели...) - поверх формы через place_popup, прячется hide_popup.
        С полосой прокрутки и "▼ ещё N" - видно, что список можно листать (как во вкладке "Добавить работу")"""
        return self.works_popup_listbox(parent)

    POPUP_MAX_ROWS = 8   # строк в списке подсказок с прокруткой (works_popup_listbox)

    def place_popup(self, listbox, entry, above=False):
        """Показать список подсказок под полем (или над ним), по ширине поля и по числу строк"""
        frame = getattr(listbox, "popup_frame", None)
        if frame is None:
            listbox.configure(height=min(5, max(1, listbox.size())))
            target = listbox
        else:
            # Список с прокруткой: полоса и "▼ ещё N" - только когда строк больше, чем помещается
            size = listbox.size()
            listbox.configure(height=min(self.POPUP_MAX_ROWS, max(1, size)))
            listbox.yview_moveto(0)
            if size > self.POPUP_MAX_ROWS:
                listbox.popup_more.pack(side=tk.BOTTOM, fill=tk.X, before=listbox)
                listbox.popup_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, before=listbox)
            else:
                listbox.popup_more.pack_forget()
                listbox.popup_scrollbar.pack_forget()
            target = frame
        if above:
            target.place(in_=entry, relx=0.0, rely=0.0, y=-2, anchor="sw", relwidth=1.0)
        else:
            target.place(in_=entry, relx=0.0, rely=1.0, y=2, relwidth=1.0)
        target.lift()

    def hide_popup(self, listbox):
        getattr(listbox, "popup_frame", listbox).place_forget()

    def works_popup_listbox(self, parent):
        """Список подсказок с полосой прокрутки и подписью "▼ ещё N" - видно, что список можно листать.
        Показывается через place_popup, прячется через hide_popup"""
        frame = tk.Frame(parent, bd=1, relief="solid", bg="white")
        listbox = tk.Listbox(frame, height=5, font=("Arial", 12), bd=0, highlightthickness=0,
                             activestyle="none", takefocus=False)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=listbox.yview)
        more = tk.Label(frame, text="", font=("Arial", 9), fg="#555", bg="#f0f0f0", anchor="w", padx=4)

        def on_scroll(first, last):
            scrollbar.set(first, last)
            below = listbox.size() - round(float(last) * listbox.size())
            more.configure(text=f"▼ {self.tr('common.more_items', count=below)}" if below > 0 else "▲")

        listbox.configure(yscrollcommand=on_scroll)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        listbox.popup_frame = frame
        listbox.popup_scrollbar = scrollbar
        listbox.popup_more = more
        return listbox

    def form_set_card_state(self, card, state):
        """Рамка карточки: зелёная - машина найдена, оранжевая - новая машина, иначе обычная"""
        card.configure(border_color=self.FORM_STATE_BORDERS.get(state, self.FORM_CARD_BORDER),
                       border_width=2 if state in self.FORM_STATE_BORDERS else 1)

    def fit_form_window(self, window):
        """Размер окна - по содержимому (блоки появляются и пропадают); при первом вызове - по центру экрана"""
        window.update_idletasks()
        w, h = window.winfo_reqwidth(), window.winfo_reqheight()
        if getattr(window, "_form_pos", None) is None:
            window._form_pos = ((window.winfo_screenwidth() - w) // 2,
                                max(0, (window.winfo_screenheight() - h) // 2 - 20))
        x, y = window._form_pos
        tk.Wm.wm_geometry(window, f"{w}x{h}+{x}+{y}")

    def make_dim_overlay(self):
        """Затемнение главного окна под окном-формой (создаётся скрытым).
        Не "поверх всех окон": затемнение принадлежит главному окну (transient), а форма - затемнению.
        Windows держит их в порядке главное окно -> затемнение -> форма, но другие программы
        (WhatsApp, браузер) при переключении спокойно встают сверху"""
        overlay = tk.Toplevel(self.root)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.configure(bg="black")
        overlay.attributes("-alpha", 0.5)
        overlay.transient(self.root)

        def follow_root(event):
            # Главное окно передвинули / изменили размер - затемнение следом
            if event.widget is self.root and overlay.winfo_exists() and overlay.winfo_ismapped():
                self._place_dim_overlay(overlay)

        self.root.bind("<Configure>", follow_root, add="+")
        return overlay

    @staticmethod
    def set_window_owner(window, owner):
        """Windows: сделать owner владельцем окна window - окно всегда над владельцем, сворачивается с ним,
        но не висит над другими программами. Tk для окна без рамки (затемнение) этого сам не делает"""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            ga_root = 2
            window.update_idletasks()
            hwnd = user32.GetAncestor(window.winfo_id(), ga_root) or window.winfo_id()
            owner_hwnd = user32.GetAncestor(owner.winfo_id(), ga_root) or owner.winfo_id()
            gwl_hwndparent = -8
            setter = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            setter(hwnd, gwl_hwndparent, owner_hwnd)
        except Exception as e:
            print(f"Не удалось назначить владельца окна: {e}")

    def _place_dim_overlay(self, overlay):
        overlay.geometry(f"{self.root.winfo_width()}x{self.root.winfo_height()}+{self.root.winfo_rootx()}+{self.root.winfo_rooty()}")

    def show_dim_overlay(self, overlay):
        """Показать затемнение точно поверх главного окна (по его текущему положению и размеру)"""
        self.root.update_idletasks()
        self._place_dim_overlay(overlay)
        overlay.deiconify()
        self.set_window_owner(overlay, self.root)
        overlay.lift()

    def show_form_window_when_ready(self, window, focus_widget=None, delay=40):
        """Показать окно-форму один раз, уже собранным и нужного размера.
        Окно строится скрытым (withdraw сразу после создания): CustomTkinter на Windows после resizable()
        прячет и снова показывает окно, чтобы перекрасить заголовок, - если окно уже видно, оно мигает.
        Даём библиотеке закончить это, пока окно скрыто, и только потом показываем"""
        window.update()

        def show():
            if not window.winfo_exists():
                return
            self.fit_form_window(window)
            window.deiconify()
            owner = getattr(window, "dim_overlay", None)
            if owner is not None and owner.winfo_exists():
                self.set_window_owner(window, owner)
            window.lift()
            window.grab_set()
            window.focus_force()
            if focus_widget is not None:
                focus_widget.focus_set()
                # Окно получает фокус не сразу после показа - ставим курсор в поле ещё раз, когда оно уже активно
                window.after(30, lambda: focus_widget.winfo_exists() and focus_widget.focus_set())

        window.after(delay, show)

    def form_buttons(self, window, ok_text, ok_command, cancel_command):
        """Широкая основная кнопка и второстепенная "Отмена" внизу окна"""
        btn_frame = ctk.CTkFrame(window, fg_color="transparent")
        btn_frame.pack(fill=tk.X, padx=18, pady=(4, 16))
        ctk.CTkButton(btn_frame, text=self.tr("common.cancel"), command=cancel_command, width=120, height=40,
                      corner_radius=8, font=("Arial", 14), fg_color="transparent", border_width=1,
                      border_color="#9e9e9e", text_color="#424242", hover_color="#e0e0e0").pack(side=tk.RIGHT)
        ctk.CTkButton(btn_frame, text=ok_text, command=ok_command, height=40,
                      corner_radius=8, font=("Arial", 15, "bold"), fg_color="#2e7d32",
                      hover_color="#1b5e20").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

    def form_bind_keys(self, window, content, on_ok, on_cancel, hide_popups):
        """Enter - основная кнопка, Esc - отмена. Если открыт список подсказок - Enter/Esc сначала для него"""
        def popup_open():
            def listboxes(widget):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Listbox):
                        yield child
                    yield from listboxes(child)
            return any(lb.winfo_ismapped() for lb in listboxes(content))

        def on_enter(event):
            if isinstance(event.widget, tk.Listbox) or popup_open():
                return
            on_ok()

        def on_escape(event):
            if popup_open():
                hide_popups()
                return
            on_cancel()

        window.bind("<Return>", on_enter)
        window.bind("<Escape>", on_escape)

    def form_mark_error(self, entry, message_key, window):
        """Незаполненное/неверное поле - красная рамка, курсор в поле и сообщение"""
        entry.configure(border_color=self.FORM_ERROR_BORDER)
        entry.focus_set()
        messagebox.showwarning(self.tr("common.attention"), self.tr(message_key), parent=window)

    def form_clear_error_on_type(self, entries):
        """Красная рамка снимается, как только поле начали править"""
        for entry in entries:
            default = entry.cget("border_color")
            entry.bind("<KeyRelease>", lambda e, en=entry, d=default: en.configure(border_color=d), add="+")

    def attach_name_autocomplete(self, entry, listbox_parent, position="right"):
        """Подсказка имён из config/first_names.txt для поля ввода имени.
        listbox_parent - контейнер, в котором лежит поле (список рисуется поверх соседних полей),
        position - "right" (справа от поля) или "below" (под полем)"""
        first_names = self.load_first_names()
        window = entry.winfo_toplevel()
        # Список с полосой прокрутки - чтобы было видно, что имён больше, чем помещается
        popup = tk.Frame(listbox_parent, bd=1, relief="solid")
        listbox = tk.Listbox(popup, height=6, width=18, font=("Arial", 12), activestyle="none",
                             bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(popup, orient=tk.VERTICAL, command=listbox.yview)
        # Подпись внизу "▼ ещё N" - сколько имён ниже видимой части
        more_label = tk.Label(popup, text="", font=("Arial", 9), fg="#555", bg="#f0f0f0", anchor="w", padx=4)
        visible = [False]
        max_rows = 6

        def on_list_scroll(first, last):
            scrollbar.set(first, last)
            below = listbox.size() - round(float(last) * listbox.size())
            more_label.configure(text=f"▼ {self.tr('common.more_items', count=below)}" if below > 0 else "▲")

        listbox.configure(yscrollcommand=on_list_scroll)
        more_label.pack(side=tk.BOTTOM, fill=tk.X)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH)

        def hide_list(event=None):
            if visible[0]:
                popup.place_forget()
                visible[0] = False

        def on_wheel(event):
            # Колесо прокручивает список, даже если курсор в поле ввода
            if visible[0]:
                listbox.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return "break"

        def on_key(event):
            if event.keysym in ("Down", "Escape", "Return", "Tab"):
                return
            # Подсказываем по слову, которое сейчас вводится (имя может идти после фамилии)
            word = entry.get().split(" ")[-1].strip().lower()
            matches = [n for n in first_names if n.lower().startswith(word)][:50] if word else []
            # Имя уже введено полностью - список не нужен
            if not matches or (len(matches) == 1 and matches[0].lower() == word):
                hide_list()
                return
            listbox.delete(0, tk.END)
            for n in matches:
                listbox.insert(tk.END, n)
            listbox.configure(height=min(max_rows, len(matches)))
            listbox.yview_moveto(0)
            if len(matches) > max_rows:
                more_label.pack(side=tk.BOTTOM, fill=tk.X, before=listbox)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y, before=listbox)
            else:
                more_label.pack_forget()
                scrollbar.pack_forget()
            if not visible[0]:
                if position == "below":
                    popup.place(in_=entry, relx=0.0, rely=1.0, y=2)
                else:
                    popup.place(in_=entry, relx=1.0, x=10, rely=0.0)
                popup.lift()
                visible[0] = True

        def on_select(event=None):
            sel = listbox.curselection()
            if not sel:
                return
            parts = entry.get().split(" ")
            parts[-1] = listbox.get(sel[0])
            entry.delete(0, tk.END)
            entry.insert(0, " ".join(parts))
            hide_list()
            entry.focus_set()
            entry.icursor(tk.END)

        def on_down(event):
            # Стрелка вниз - переход в список подсказок
            if visible[0]:
                listbox.focus_set()
                listbox.selection_clear(0, tk.END)
                listbox.selection_set(0)
                listbox.activate(0)
                return "break"

        def on_focus_out(event):
            def check_and_hide():
                try:
                    if window.focus_get() != listbox:
                        hide_list()
                except (KeyError, tk.TclError):
                    hide_list()
            window.after(200, check_and_hide)

        entry.bind("<KeyRelease>", on_key)
        entry.bind("<Down>", on_down)
        def on_escape(event):
            if visible[0]:
                hide_list()
                return "break"

        entry.bind("<Escape>", on_escape)
        entry.bind("<FocusOut>", on_focus_out)
        listbox.bind("<Button-1>", lambda e: listbox.focus_set())
        listbox.bind("<ButtonRelease-1>", on_select)
        listbox.bind("<Return>", lambda e: (on_select(), "break")[1])
        listbox.bind("<Escape>", lambda e: (hide_list(), entry.focus_set(), "break")[2])
        listbox.bind("<FocusOut>", on_focus_out)
        entry.bind("<MouseWheel>", on_wheel)
        listbox.bind("<MouseWheel>", on_wheel)
        scrollbar.bind("<MouseWheel>", on_wheel)
        more_label.bind("<MouseWheel>", on_wheel)

    def save_settings(self, settings):
        """Сохранить настройки в JSON файл"""
        save_app_settings(settings)

    def on_percent_changed(self, *args):
        """Обработчик изменения процента мастеру"""
        try:
            percent_str = self.percent_var.get().replace(',', '.')
            if percent_str:
                percent = float(percent_str)
                settings = self.load_settings()
                settings['master_percent'] = percent
                self.save_settings(settings)
        except ValueError:
            pass

    def setup_entry_context_menu(self, entry_widget):
        """Добавляет контекстное меню с функциями копирования/вставки для поля ввода"""
        # Создаем контекстное меню
        context_menu = tk.Menu(entry_widget, tearoff=0)

        def cut_text():
            try:
                if entry_widget.select_present():
                    entry_widget.clipboard_clear()
                    entry_widget.clipboard_append(entry_widget.selection_get())
                    entry_widget.delete("sel.first", "sel.last")
            except:
                pass

        def copy_text():
            try:
                if entry_widget.select_present():
                    entry_widget.clipboard_clear()
                    entry_widget.clipboard_append(entry_widget.selection_get())
            except:
                pass

        def paste_text():
            try:
                text = entry_widget.clipboard_get()
                try:
                    # Для CTkEntry используем insert в позицию курсора
                    entry_widget.insert(tk.INSERT, text)
                except:
                    # Если не работает, вставляем в конец
                    current = entry_widget.get()
                    entry_widget.delete(0, tk.END)
                    entry_widget.insert(0, current + text)
            except:
                pass

        def select_all():
            try:
                entry_widget.select_range(0, tk.END)
                entry_widget.icursor(tk.END)
            except:
                pass

        context_menu.add_command(label=self.tr("ctx.cut"), command=cut_text)
        context_menu.add_command(label=self.tr("ctx.copy"), command=copy_text)
        context_menu.add_command(label=self.tr("ctx.paste"), command=paste_text)
        context_menu.add_separator()
        context_menu.add_command(label=self.tr("ctx.select_all"), command=select_all)

        def show_context_menu(event):
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()

        # Привязываем контекстное меню к правой кнопке мыши
        entry_widget.bind("<Button-3>", show_context_menu)

        # Привязываем горячие клавиши (return "break" чтобы остановить стандартную обработку)
        def paste_wrapper(e):
            paste_text()
            return "break"

        def copy_wrapper(e):
            copy_text()
            return "break"

        def cut_wrapper(e):
            cut_text()
            return "break"

        def select_all_wrapper(e):
            select_all()
            return "break"

        entry_widget.bind("<Control-v>", paste_wrapper)
        entry_widget.bind("<Control-V>", paste_wrapper)
        entry_widget.bind("<Control-m>", paste_wrapper)  # Ctrl+M (только на английской раскладке)
        entry_widget.bind("<Control-M>", paste_wrapper)
        entry_widget.bind("<Control-c>", copy_wrapper)
        entry_widget.bind("<Control-C>", copy_wrapper)
        entry_widget.bind("<Control-x>", cut_wrapper)
        entry_widget.bind("<Control-X>", cut_wrapper)
        entry_widget.bind("<Control-a>", select_all_wrapper)
        entry_widget.bind("<Control-A>", select_all_wrapper)

    def _confirm_close(self):
        """Подтверждение закрытия приложения."""
        if messagebox.askyesno(
            "Выход",
            "Закрыть приложение?",
            parent=self.root
        ):
            self.root.destroy()

    def _logout(self):
        """Выйти из аккаунта и вернуться на экран авторизации."""
        if messagebox.askyesno(
            "Выход из аккаунта",
            "Выйти из аккаунта и вернуться к экрану входа?",
            parent=self.root
        ):
            self.logged_out = True
            self.root.destroy()

    def _check_update_manual(self):
        """Ручная проверка обновлений по кнопке в меню — в отличие от фоновой
        проверки, всегда показывает результат пользователю (в том числе
        когда обновлений нет или сервер недоступен), чтобы можно было
        разобраться, почему автообновление не сработало."""
        try:
            from updater import APP_VERSION, check_for_update, show_update_dialog, apply_update, _log_error
        except Exception as e:
            messagebox.showerror(
                self.tr("common.error"),
                f"Модуль обновлений недоступен:\n{e}",
                parent=self.root
            )
            return

        try:
            upd = check_for_update(silent=False)
        except Exception as e:
            _log_error("_check_update_manual", e)
            messagebox.showerror(
                self.tr("common.error"),
                f"Не удалось проверить обновления:\n{e}",
                parent=self.root
            )
            return

        if upd:
            if show_update_dialog(upd, parent=self.root):
                apply_update(upd["download_url"], parent_widget=self.root, forced=upd.get("forced", False))
        else:
            messagebox.showinfo(
                self.tr("common.info"),
                f"У вас установлена последняя версия ({APP_VERSION}).",
                parent=self.root
            )

    def _open_user_management(self):
        """Открыть диалог управления пользователями (только admin)."""
        from login_window import UserManagementDialog
        UserManagementDialog(self.root, self.db, self.current_user)

    def setup_styles(self):
        """Настройка стилей"""
        style = ttk.Style()

        # Используем тему clam для отображения вертикальных разделителей
        style.theme_use('clam')

        style.configure("Title.TLabel", font=("Arial", 14, "bold"))
        style.configure("Header.TLabel", font=("Arial", 11, "bold"))

        # Настройка Treeview для отображения сетки с разделителями
        style.configure("Treeview",
                       rowheight=32,
                       borderwidth=1,
                       relief="solid",
                       background="white",
                       fieldbackground="white",
                       font=("Segoe UI", 12))
        style.configure("Treeview.Heading",
                       borderwidth=1,
                       relief="solid",
                       background="#e0e0e0",
                       font=("Segoe UI", 11, "bold"))

        # Настройка цветов для чередующихся строк и выделения
        style.map('Treeview',
                 background=[('selected', '#0078d7')],
                 foreground=[('selected', 'white')])

        # Теги для чередующихся строк (zebra stripes)
        self.row_tags = ('oddrow', 'evenrow')

    # ===== ВКЛАДКА РАБОТНИКОВ =====

    def setup_users_tab(self):
        main_frame = ctk.CTkFrame(self.users_tab_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=20)
        ctk.CTkLabel(add_frame, text="Логин:").pack(side=tk.LEFT, padx=5, pady=5)
        self.new_user_login = ctk.CTkEntry(add_frame, width=120, fg_color="white", text_color="black", placeholder_text="логин")
        self.new_user_login.pack(side=tk.LEFT, padx=5, pady=5)
        ctk.CTkLabel(add_frame, text="Пароль:").pack(side=tk.LEFT, padx=5, pady=5)
        self.new_user_pass = ctk.CTkEntry(add_frame, width=120, show="•", fg_color="white", text_color="black", placeholder_text="пароль")
        self.new_user_pass.pack(side=tk.LEFT, padx=5, pady=5)
        ctk.CTkLabel(add_frame, text="Имя:").pack(side=tk.LEFT, padx=5, pady=5)
        self.new_user_name = ctk.CTkEntry(add_frame, width=150, fg_color="white", text_color="black", placeholder_text="отображаемое имя")
        self.new_user_name.pack(side=tk.LEFT, padx=5, pady=5)
        self.new_user_role = tk.StringVar(value="user")
        ctk.CTkRadioButton(add_frame, text="Польз.", variable=self.new_user_role, value="user").pack(side=tk.LEFT, padx=4)
        ctk.CTkRadioButton(add_frame, text="Админ",  variable=self.new_user_role, value="admin").pack(side=tk.LEFT, padx=4)
        ctk.CTkButton(add_frame, text="Добавить", command=self._add_user_from_tab,
                      fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=10, pady=5)

        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(fill=tk.X, pady=10)
        cols = ("username", "full_name", "role", "status")
        self.users_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=15)
        self.users_tree.heading("username",  text="Логин")
        self.users_tree.heading("full_name", text="Имя")
        self.users_tree.heading("role",      text="Роль")
        self.users_tree.heading("status",    text="Статус")
        self.users_tree.column("username",  width=140, anchor=tk.W)
        self.users_tree.column("full_name", width=210, anchor=tk.W)
        self.users_tree.column("role",      width=130, anchor=tk.CENTER)
        self.users_tree.column("status",    width=110, anchor=tk.CENTER)
        self.users_tree.tag_configure("oddrow",  background="#ffffff")
        self.users_tree.tag_configure("evenrow", background="#f0f0f0")
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.users_tree.yview)
        self.users_tree.configure(yscrollcommand=sb.set)
        self.users_tree.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)

        btn_frame = ctk.CTkFrame(center_container, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Сменить пароль", width=180,
                      command=self._users_tab_change_password).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_frame, text="Блок / Разблок", width=160,
                      fg_color="orange", hover_color="#e65100",
                      command=self._users_tab_toggle_active).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_frame, text="Удалить", width=120,
                      fg_color="red", hover_color="darkred",
                      command=self._users_tab_delete).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_frame, text=self.tr("reports.set_password_btn"), width=180,
                      fg_color="#6a1b9a", hover_color="#4a148c",
                      command=self.change_reports_password).pack(side=tk.LEFT, padx=5)
        self.refresh_users_list()

    def _add_user_from_tab(self):
        username  = self.new_user_login.get().strip()
        password  = self.new_user_pass.get()
        full_name = self.new_user_name.get().strip()
        role      = self.new_user_role.get()
        if not username or not password:
            messagebox.showwarning("Внимание", "Введите логин и пароль!", parent=self.root)
            return
        if self.db.create_user(username, password, full_name, role):
            messagebox.showinfo("Успех", f"Пользователь '{username}' добавлен!", parent=self.root)
            self.new_user_login.delete(0, tk.END)
            self.new_user_pass.delete(0, tk.END)
            self.new_user_name.delete(0, tk.END)
            self.refresh_users_list()
        else:
            messagebox.showerror("Ошибка", "Пользователь с таким логином уже существует!", parent=self.root)

    def _users_tab_selected_id(self):
        sel = self.users_tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Выберите пользователя!", parent=self.root)
            return None
        return int(self.users_tree.item(sel[0])["tags"][0])

    def _users_tab_change_password(self):
        uid = self._users_tab_selected_id()
        if uid is None:
            return
        from login_window import ChangePasswordDialog
        ChangePasswordDialog(self.root, self.db, uid, on_saved=self.refresh_users_list)

    def _users_tab_toggle_active(self):
        uid = self._users_tab_selected_id()
        if uid is None:
            return
        if uid == self.current_user["id"]:
            messagebox.showwarning("Ошибка", "Нельзя заблокировать себя!", parent=self.root)
            return
        users = {u["id"]: u for u in self.db.get_all_users()}
        u = users.get(uid)
        if u:
            self.db.set_user_active(uid, not u["is_active"])
            self.refresh_users_list()

    def _users_tab_delete(self):
        uid = self._users_tab_selected_id()
        if uid is None:
            return
        if uid == self.current_user["id"]:
            messagebox.showwarning("Ошибка", "Нельзя удалить себя!", parent=self.root)
            return
        uname = self.users_tree.item(self.users_tree.selection()[0])["values"][0]
        if messagebox.askyesno("Подтверждение", f"Удалить пользователя '{uname}'?", parent=self.root):
            self.db.delete_user(uid)
            self.refresh_users_list()

    def refresh_users_list(self):
        if not hasattr(self, "users_tree"):
            return
        for item in self.users_tree.get_children():
            self.users_tree.delete(item)
        for i, u in enumerate(self.db.get_all_users()):
            role_label   = "Администратор" if u["role"] == "admin" else "Пользователь"
            status_label = "Активен" if u["is_active"] else "Заблокирован"
            tag = "oddrow" if i % 2 == 0 else "evenrow"
            self.users_tree.insert("", tk.END,
                values=(u["username"], u["full_name"] or "", role_label, status_label),
                tags=(str(u["id"]), tag))

    def setup_workers_tab(self):
        """Настройка вкладки работников"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.workers_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Верхняя панель - добавление работника
        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=20)

        ctk.CTkLabel(add_frame, text=self.tr("workers.full_name_label")).pack(side=tk.LEFT, padx=5, pady=5)
        self.worker_name_entry = ctk.CTkEntry(add_frame, width=400, fg_color="white", text_color="black")
        self.worker_name_entry.pack(side=tk.LEFT, padx=5, pady=5)

        ctk.CTkButton(add_frame, text=self.tr("common.add"), command=self.add_worker, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5, pady=5)

        # Список работников
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(fill=tk.X, pady=10)

        # Таблица работников (без колонки ID) - ширина по родительскому контейнеру
        columns = ("name",)
        self.workers_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.workers_tree.heading("name", text=self.tr("reports.col_master_name"))
        self.workers_tree.column("name", width=500, stretch=True, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.workers_tree.yview)
        self.workers_tree.configure(yscrollcommand=scrollbar.set)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.workers_tree.tag_configure('oddrow', background='#ffffff')
        self.workers_tree.tag_configure('evenrow', background='#f0f0f0')

        self.workers_tree.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)

        # Кнопка удаления
        ctk.CTkButton(center_container, text=self.tr("workers.delete_selected"),
                   command=self.delete_worker, width=550, fg_color="red", hover_color="darkred").pack(anchor=tk.CENTER, pady=10)

    def add_worker(self):
        """Добавить работника"""
        name = self.worker_name_entry.get().strip()
        if not name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("workers.msg_enter_name"))
            return

        if self.db.add_worker(name):
            messagebox.showinfo(self.tr("common.success"), self.tr("workers.msg_added", name=name))
            self.worker_name_entry.delete(0, tk.END)
            self.refresh_workers_list()
            self.refresh_workers_combo()
        else:
            messagebox.showerror(self.tr("common.error"), self.tr("workers.msg_already_exists"))

    def delete_worker(self):
        """Удалить работника"""
        selected = self.workers_tree.selection()
        if not selected:
            messagebox.showwarning(self.tr("common.attention"), self.tr("workers.msg_select_to_delete"))
            return

        item = self.workers_tree.item(selected[0])
        worker_id = item['tags'][0]  # ID хранится в тегах
        worker_name = item['values'][0]  # Имя в первой колонке

        if messagebox.askyesno(self.tr("common.confirm"),
                               self.tr("workers.msg_confirm_delete", name=worker_name)):
            self.db.delete_worker(worker_id)
            messagebox.showinfo(self.tr("common.success"), self.tr("workers.msg_deleted"))
            self.refresh_workers_list()
            self.refresh_workers_combo()

    def refresh_workers_list(self):
        """Обновить список работников"""
        for item in self.workers_tree.get_children():
            self.workers_tree.delete(item)

        row_index = 0
        for worker in self.db.get_all_workers():
            worker_id, worker_name = worker

            # Определяем тег для чередующихся строк
            row_tag = 'oddrow' if row_index % 2 == 0 else 'evenrow'

            # Вставляем только имя в таблицу, ID сохраняем в тегах вместе с цветом
            self.workers_tree.insert("", tk.END, values=(worker_name,), tags=(worker_id, row_tag))

            row_index += 1

    # ===== ВКЛАДКА "СОТРУДНИКИ" (РАСПИСАНИЕ) =====

    # Виды отсутствия: цвет клетки в календаре
    STAFF_KIND_COLORS = {
        "day_off": "#ffcc80",   # выходной
        "vacation": "#a5d6a7",  # отпуск
        "sick": "#ef9a9a",      # больничный
    }
    STAFF_PERIOD_KINDS = ("day_off", "vacation", "sick")

    def staff_kind_label(self, kind):
        return self.tr(f"staff.kind_{kind}")

    def setup_staff_tab(self):
        """Вкладка "Сотрудники": календарь на месяц (сотрудники x дни)"""
        parent = self.staff_frame
        today = date.today()
        self.staff_month = date(today.year, today.month, 1)
        self.staff_workers = []
        self.staff_content_size = (0, 0)

        # Всё по центру: заголовок, переключение месяца, сводка на сегодня, легенда, таблица
        ctk.CTkLabel(parent, text=self.tr("staff.title"),
                     font=ctk.CTkFont(size=18, weight="bold")).pack(padx=10, pady=(10, 4))
        nav = ctk.CTkFrame(parent, fg_color="transparent")
        nav.pack(padx=10)
        ctk.CTkButton(nav, text="◀", width=36, command=lambda: self.staff_change_month(-1)).pack(side=tk.LEFT)
        self.staff_month_label = ctk.CTkLabel(nav, text="", width=150, font=ctk.CTkFont(size=15, weight="bold"))
        self.staff_month_label.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(nav, text="▶", width=36, command=lambda: self.staff_change_month(1)).pack(side=tk.LEFT)
        ctk.CTkButton(nav, text=self.tr("staff.today_btn"), width=80,
                      command=lambda: self.staff_change_month(0)).pack(side=tk.LEFT, padx=(10, 0))

        self.staff_summary_label = ctk.CTkLabel(parent, text="", justify=tk.CENTER, wraplength=900)
        self.staff_summary_label.pack(padx=12, pady=(6, 0))

        # Легенда - она же выбор того, что ставится в график по клику на клетку
        legend = ctk.CTkFrame(parent, fg_color="transparent")
        legend.pack(padx=10, pady=(4, 6))
        self.staff_brush = "day_off"
        self.staff_brush_buttons = {}
        for kind in self.STAFF_PERIOD_KINDS:
            button = tk.Label(legend, text=f"  {self.tr('staff.short_' + kind)}  {self.staff_kind_label(kind)}  ",
                              bg=self.STAFF_KIND_COLORS[kind], font=("Arial", 10), cursor="hand2", pady=3)
            button.pack(side=tk.LEFT, padx=4)
            button.bind("<Button-1>", lambda e, k=kind: self.set_staff_brush(k))
            self.staff_brush_buttons[kind] = button
        self.set_staff_brush(self.staff_brush)
        ctk.CTkLabel(legend, text=self.tr("staff.hint"), text_color="gray").pack(side=tk.LEFT, padx=10)

        # Календарь: холст по размеру таблицы, прокрутка - только если окно меньше таблицы
        self.staff_body = ctk.CTkFrame(parent, fg_color="transparent")
        self.staff_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        cal_frame = tk.Frame(self.staff_body, bg="white", highlightthickness=1, highlightbackground="#bdbdbd")
        cal_frame.pack(side=tk.TOP, anchor="n")
        self.staff_canvas = tk.Canvas(cal_frame, bg="white", highlightthickness=0, width=1, height=1)
        self.staff_x_scroll = tk.Scrollbar(cal_frame, orient=tk.HORIZONTAL, command=self.staff_canvas.xview)
        self.staff_y_scroll = tk.Scrollbar(cal_frame, orient=tk.VERTICAL, command=self.staff_canvas.yview)
        self.staff_canvas.configure(xscrollcommand=self.staff_x_scroll.set, yscrollcommand=self.staff_y_scroll.set)
        self.staff_canvas.grid(row=0, column=0)
        self.staff_x_scroll.grid(row=1, column=0, sticky="ew")
        self.staff_y_scroll.grid(row=0, column=1, sticky="ns")
        self.staff_canvas.bind("<Button-1>", self.on_staff_canvas_click)
        self.staff_canvas.bind("<MouseWheel>",
                               lambda e: self.staff_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.staff_body.bind("<Configure>", self.fit_staff_canvas, add=True)

        self.refresh_staff_tab()

    def fit_staff_canvas(self, event=None):
        """Размер таблицы = размер содержимого; если не влезает в окно - урезаем и показываем прокрутку"""
        avail_w, avail_h = self.staff_body.winfo_width() - 2, self.staff_body.winfo_height() - 2
        if avail_w <= 1 or avail_h <= 1:
            return
        need_w, need_h = self.staff_content_size
        bar = self.staff_y_scroll.winfo_reqwidth()
        show_x = need_w > avail_w
        show_y = need_h > avail_h - (bar if show_x else 0)
        if show_y and not show_x:
            show_x = need_w > avail_w - bar
        self.staff_canvas.configure(width=min(need_w, avail_w - (bar if show_y else 0)),
                                    height=min(need_h, avail_h - (bar if show_x else 0)))
        self.staff_x_scroll.grid() if show_x else self.staff_x_scroll.grid_remove()
        self.staff_y_scroll.grid() if show_y else self.staff_y_scroll.grid_remove()

    def staff_change_month(self, step):
        """step = -1 / 1 - листаем месяц, 0 - к текущему месяцу"""
        if step == 0:
            today = date.today()
            self.staff_month = date(today.year, today.month, 1)
        else:
            month = self.staff_month.month - 1 + step
            self.staff_month = date(self.staff_month.year + month // 12, month % 12 + 1, 1)
        self.draw_staff_calendar()

    def refresh_staff_tab(self):
        """Перечитать сотрудников и расписание"""
        self.staff_workers = self.db.get_all_workers()
        self.update_staff_summary()
        self.draw_staff_calendar()

    def update_staff_summary(self):
        """Сводка на сегодня: сколько работает, кто отсутствует"""
        if not self.staff_workers:
            self.staff_summary_label.configure(text=self.tr("staff.no_workers"))
            return
        today = date.today()
        schedule = self.db.get_worker_schedule(today, today)
        absent = [f"{name} ({self.staff_kind_label(schedule[wid][today])})"
                  for wid, name in self.staff_workers if today in schedule.get(wid, {})]
        text = self.tr("staff.today_summary", working=len(self.staff_workers) - len(absent), total=len(self.staff_workers))
        if absent:
            text += "   " + self.tr("staff.today_absent", list=", ".join(absent))
        self.staff_summary_label.configure(text=text)

    STAFF_NAME_W = 170
    STAFF_CELL = 28
    STAFF_HEAD = 40

    def draw_staff_calendar(self):
        """Нарисовать календарь месяца: строки - сотрудники, столбцы - дни"""
        canvas = self.staff_canvas
        canvas.delete("all")
        first = self.staff_month
        days_in_month = pycalendar.monthrange(first.year, first.month)[1]
        last = first.replace(day=days_in_month)
        self.staff_month_label.configure(text=f"{self.tr(f'staff.month_{first.month}')} {first.year}")
        schedule = self.db.get_worker_schedule(first, last) if self.staff_workers else {}
        today = date.today()
        name_w, cell, head = self.STAFF_NAME_W, self.STAFF_CELL, self.STAFF_HEAD
        width = name_w + days_in_month * cell
        height = head + len(self.staff_workers) * cell

        # Шапка: число и день недели, выходные дни недели подкрашены
        for d in range(1, days_in_month + 1):
            day = first.replace(day=d)
            x = name_w + (d - 1) * cell
            weekend = day.weekday() >= 5
            canvas.create_rectangle(x, 0, x + cell, head, fill="#eceff1" if weekend else "#fafafa", outline="#cfd8dc")
            canvas.create_text(x + cell / 2, 13, text=str(d), font=("Arial", 10, "bold"),
                               fill="#c62828" if weekend else "#212121")
            canvas.create_text(x + cell / 2, 29, text=self.tr(f"staff.weekday_{day.weekday()}"), font=("Arial", 8),
                               fill="#c62828" if weekend else "#757575")
        canvas.create_rectangle(0, 0, name_w, head, fill="#fafafa", outline="#cfd8dc")

        # Строки сотрудников
        for row, (worker_id, name) in enumerate(self.staff_workers):
            y = head + row * cell
            canvas.create_rectangle(0, y, name_w, y + cell, fill="white", outline="#cfd8dc")
            canvas.create_text(8, y + cell / 2, text=name, anchor="w", font=("Arial", 10), width=name_w - 12)
            worker_days = schedule.get(worker_id, {})
            for d in range(1, days_in_month + 1):
                day = first.replace(day=d)
                x = name_w + (d - 1) * cell
                kind = worker_days.get(day)
                canvas.create_rectangle(x, y, x + cell, y + cell,
                                        fill=self.STAFF_KIND_COLORS.get(kind, "white"), outline="#cfd8dc")
                if kind:
                    canvas.create_text(x + cell / 2, y + cell / 2, text=self.tr(f"staff.short_{kind}"),
                                       font=("Arial", 9, "bold"), fill="#37474f")

        # Сегодняшний день - синяя рамка по всему столбцу
        if first.year == today.year and first.month == today.month:
            x = name_w + (today.day - 1) * cell
            canvas.create_rectangle(x, 0, x + cell, max(height, head), outline="#1565c0", width=2)

        canvas.configure(scrollregion=(0, 0, width + 1, height + 1))
        self.staff_content_size = (width + 1, height + 1)
        self.fit_staff_canvas()

    def on_staff_canvas_click(self, event):
        """Клик по клетке календаря - поставить выбранное в легенде (или снять)"""
        x = self.staff_canvas.canvasx(event.x)
        y = self.staff_canvas.canvasy(event.y)
        row = int((y - self.STAFF_HEAD) // self.STAFF_CELL)
        if y < self.STAFF_HEAD or row >= len(self.staff_workers):
            return
        worker_id = self.staff_workers[row][0]

        col = int((x - self.STAFF_NAME_W) // self.STAFF_CELL)
        days_in_month = pycalendar.monthrange(self.staff_month.year, self.staff_month.month)[1]
        if x < self.STAFF_NAME_W or col >= days_in_month:
            return
        day = self.staff_month.replace(day=col + 1)
        kind = self.db.get_worker_schedule(day, day).get(worker_id, {}).get(day)
        # Там уже стоит выбранное - снимаем (рабочий день), иначе ставим выбранное
        self.db.set_worker_day(worker_id, day, None if kind == self.staff_brush else self.staff_brush)
        self.after_staff_change()

    def set_staff_brush(self, kind):
        """Выбор в легенде: что ставить в график по клику на клетку"""
        self.staff_brush = kind
        for k, button in self.staff_brush_buttons.items():
            selected = k == kind
            button.configure(relief="solid" if selected else "flat", borderwidth=2 if selected else 0,
                             font=("Arial", 10, "bold" if selected else "normal"))

    def after_staff_change(self):
        """Расписание изменилось - перерисовать вкладку и обновить список мастеров в "Добавить работу" """
        self.update_staff_summary()
        self.draw_staff_calendar()
        self.refresh_workers_combo()

    # ===== ВКЛАДКА ПОИСКА ДЕТАЛЕЙ =====

    def setup_parts_search_tab(self):
        """Настройка вкладки поиска деталей"""
        parent = self.parts_search_frame

        # Заголовок
        ctk.CTkLabel(
            parent,
            text="🔍 Поиск деталей",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=(24, 4))

        ctk.CTkLabel(
            parent,
            text="Введите название детали или артикул — откроется браузер с результатами",
            font=ctk.CTkFont(size=13),
            text_color="gray"
        ).pack(pady=(0, 20))

        # Поле поиска
        search_frame = ctk.CTkFrame(parent, fg_color="transparent")
        search_frame.pack(padx=40, fill=tk.X)

        self.parts_search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Например: фильтр масляный Toyota Camry или артикул 90915-YZZD2",
            height=42,
            font=ctk.CTkFont(size=14)
        )
        self.parts_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.parts_search_entry.bind("<Return>", lambda e: self._parts_open_all())

        ctk.CTkButton(
            search_frame,
            text="Искать везде",
            command=self._parts_open_all,
            height=42,
            width=140,
            font=ctk.CTkFont(size=14),
            fg_color="#1565c0",
            hover_color="#1976d2"
        ).pack(side=tk.LEFT)

        # Кнопки сайтов
        ctk.CTkLabel(
            parent,
            text="Открыть на конкретном сайте:",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(pady=(28, 8))

        sites_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sites_frame.pack()

        self._parts_sites = [
            ("exist.ru",    "https://exist.ru/Price/?pnam={q}",                          "#1565c0"),
            ("autodoc.ru",  "https://autodoc.ru/search/{q}",                             "#2e7d32"),
            ("emex.ru",     "https://emex.ru/goods?goodsNumber={q}",                     "#6a1b9a"),
            ("avito.ru",    "https://www.avito.ru/rossiya/zapchasti_i_aksessuary?q={q}", "#e65100"),
            ("drom.ru",     "https://baza.drom.ru/?action=search&query={q}",             "#37474f"),
        ]

        for i, (label, url_tpl, color) in enumerate(self._parts_sites):
            ctk.CTkButton(
                sites_frame,
                text=label,
                command=lambda t=url_tpl: self._parts_open_site(t),
                height=38,
                width=130,
                font=ctk.CTkFont(size=13),
                fg_color=color,
                hover_color=color
            ).grid(row=0, column=i, padx=6)

        # История поиска
        ctk.CTkLabel(
            parent,
            text="Последние запросы:",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(pady=(30, 6))

        self.parts_history_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.parts_history_frame.pack()

        ctk.CTkLabel(
            self.parts_history_frame,
            text="История пуста",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack()

    def _parts_get_query(self) -> str:
        return self.parts_search_entry.get().strip()

    def _parts_open_site(self, url_tpl: str):
        query = self._parts_get_query()
        if not query:
            return
        self._parts_add_history(query)
        webbrowser.open(url_tpl.replace("{q}", quote(query)))

    def _parts_open_all(self):
        query = self._parts_get_query()
        if not query:
            return
        self._parts_add_history(query)
        for _, url_tpl, _ in self._parts_sites:
            webbrowser.open(url_tpl.replace("{q}", quote(query)))

    def _parts_add_history(self, query: str):
        if query in self.parts_search_history:
            self.parts_search_history.remove(query)
        self.parts_search_history.insert(0, query)
        self.parts_search_history = self.parts_search_history[:8]
        self._parts_refresh_history()

    def _parts_refresh_history(self):
        for w in self.parts_history_frame.winfo_children():
            w.destroy()
        if not self.parts_search_history:
            ctk.CTkLabel(
                self.parts_history_frame,
                text="История пуста",
                font=ctk.CTkFont(size=12),
                text_color="gray"
            ).pack()
            return
        for item in self.parts_search_history:
            row = ctk.CTkFrame(self.parts_history_frame, fg_color="transparent")
            row.pack(fill=tk.X, pady=1)
            ctk.CTkButton(
                row,
                text=f"🕐  {item}",
                command=lambda q=item: self._parts_use_history(q),
                height=30,
                fg_color="transparent",
                text_color=("#1565c0", "#90caf9"),
                hover_color=("#e3f2fd", "#1e3a5f"),
                anchor="w",
                font=ctk.CTkFont(size=13)
            ).pack(side=tk.LEFT)

    def _parts_use_history(self, query: str):
        self.parts_search_entry.delete(0, tk.END)
        self.parts_search_entry.insert(0, query)
        self._parts_open_all()

    # ===== ВКЛАДКА ДОБАВЛЕНИЯ РАБОТ =====

    WORKS_MAX_WIDTH = 700          # ширина колонки вкладки на широком экране
    WORKS_AUTOFILL_BG = "#e8f5e9"  # фон поля, которое подставила программа (по госномеру / телефону)

    def works_cell(self, row, column, label, widget, width=None, required=False):
        """Ячейка строки формы: подпись сверху, под ней поле. width=None - ячейка тянется на остаток строки"""
        padx = (0 if column == 0 else 10, 0)
        row.grid_columnconfigure(column, weight=0 if width else 1)
        self.form_label(row, label, required=required).grid(row=0, column=column, sticky="w", padx=padx)
        widget.grid(row=1, column=column, sticky="w" if width else "ew", padx=padx)
        return widget

    def works_entry(self, parent, width, big=False, **kwargs):
        entry = self.form_entry(parent, width=width, **kwargs)
        if big:
            entry.configure(height=40, font=("Arial", 17, "bold"))
        return entry

    def works_combo(self, parent, width=140, command=None):
        return ctk.CTkComboBox(parent, values=[""], width=width, height=34, font=("Arial", 14), corner_radius=8,
                               state="readonly", command=command)

    def setup_works_tab(self):
        """Вкладка "Добавить работу": одна колонка по центру.
        Админ вводит госномер или телефон - данные клиента и машины подставляются сами (подсвечены зелёным)"""
        # Нижняя строка "Итого | Добавить запись | Сбросить" - закреплена снизу, вне прокрутки, по ширине колонки
        self.works_bottom_bar = ctk.CTkFrame(self.works_frame, fg_color="white", corner_radius=10, border_width=1,
                                             border_color=self.FORM_CARD_BORDER)
        self.works_bottom_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(6, 10))
        self.works_total_label = ctk.CTkLabel(self.works_bottom_bar, text="", font=("Arial", 18, "bold"),
                                              text_color="#263238")
        self.works_total_label.pack(side=tk.LEFT, padx=18, pady=12)
        ctk.CTkButton(self.works_bottom_bar, text=self.tr("works.reset"), command=self.clear_work_form,
                      width=110, height=44, corner_radius=8, font=("Arial", 14), fg_color="transparent",
                      border_width=1, border_color="#9e9e9e", text_color="#424242",
                      hover_color="#e0e0e0").pack(side=tk.RIGHT, padx=(0, 14))
        ctk.CTkButton(self.works_bottom_bar, text=self.tr("works.save"), command=self.add_work,
                      width=220, height=44, corner_radius=8, font=("Arial", 16, "bold"),
                      fg_color="#2e7d32", hover_color="#1b5e20").pack(side=tk.RIGHT, padx=10)

        # Прокручиваемая область с колонкой формы
        self.works_scroll = ctk.CTkScrollableFrame(self.works_frame, fg_color="transparent")
        self.works_scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        col = ctk.CTkFrame(self.works_scroll, fg_color="transparent")
        col.pack(fill=tk.X, padx=8)
        self.works_column = col
        # Строка заголовка постоянной высоты: при редактировании сохранённой записи заголовок становится
        # "✎ Редактирование записи: ..." (оранжевый) и справа кнопка "Выйти из редактирования" - форма не сдвигается
        title_row = ctk.CTkFrame(col, fg_color="transparent", height=40)
        self.works_title_row = title_row
        title_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        title_row.pack_propagate(False)
        self.works_edit_banner_label = ctk.CTkLabel(title_row, text=self.tr("works.title"),
                                                    font=("Segoe UI", 20, "bold"), anchor="w")
        self.works_edit_banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.works_title_color = self.works_edit_banner_label.cget("text_color")
        self.works_edit_banner = ctk.CTkButton(
            title_row, text=self.tr("works.edit_banner_exit"), width=10, height=30, corner_radius=8,
            font=("Arial", 13), fg_color="transparent", border_width=1, border_color="#ffb74d",
            text_color="#e65100", hover_color="#ffe0b2", command=self.clear_work_form)
        # Всплывающее сообщение ("Открыта новая запись ...") - поверх формы, форму не сдвигает
        self.works_info_banner = ctk.CTkLabel(self.works_frame, text="", font=("Arial", 14, "bold"),
                                              text_color="white", fg_color="#2e7d32", bg_color="transparent",
                                              corner_radius=10, height=40)
        self.works_editing_title = ""

        # ===== Запись и мастер - одна строка =====
        _, body = self.form_section(col, self.tr("works.section_booking_master"))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill=tk.X, pady=(0, 6))
        booking_box = ctk.CTkFrame(row, fg_color="transparent")
        self.booking_combo = self.works_combo(booking_box, command=self.on_booking_select)
        self.booking_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.booking_combo.set("")
        self.bookings_data = {}  # Словарь для хранения booking_id по тексту
        ctk.CTkButton(booking_box, text="⟳", width=36, height=34, corner_radius=8, font=("Arial", 16),
                      command=self.refresh_bookings_combo).pack(side=tk.LEFT, padx=(6, 0))
        self.works_cell(row, 0, self.tr("works.booking"), booking_box)
        self.worker_combo = self.works_combo(row, width=220)
        self.works_cell(row, 1, self.tr("works.master"), self.worker_combo, width=220, required=True)

        # ===== Клиент и автомобиль =====
        self.works_owner_card, body = self.form_section(col, self.tr("works.section_client_car"))
        self.works_lookup_hint = ctk.CTkLabel(body, text=self.tr("works.lookup_hint"), font=("Arial", 12),
                                              text_color="gray45", anchor="w")
        self.works_lookup_hint.pack(fill=tk.X, pady=(0, 4))

        # Госномер | Телефон | Имя - по госномеру или телефону подставляется всё остальное
        self.works_search_row = row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill=tk.X, pady=(0, 6))
        self.car_number_entry = self.works_cell(row, 0, self.tr("works.car_number"),
                                                self.works_entry(row, 150, big=True), 150, required=True)
        self.client_phone_entry = self.works_cell(row, 1, self.tr("works.client_phone"),
                                                  self.works_entry(row, 200, big=True), 200)
        self.client_name_entry = self.works_cell(row, 2, self.tr("works.client_name"), self.works_entry(row, 140))
        self.client_name_entry.configure(height=40, font=("Arial", 16))

        # Строка результата поиска ("✓ Машина есть в базе — ...") - видна, когда есть текст
        self.works_lookup_status = ctk.CTkLabel(body, text="", font=("Arial", 13, "bold"), anchor="w")

        # Марка | Модель | VIN | Пробег
        car_row = ctk.CTkFrame(body, fg_color="transparent")
        car_row.pack(fill=tk.X, pady=(0, 6))
        self.car_brand_entry = self.works_cell(car_row, 0, self.tr("works.car_brand"),
                                               self.works_entry(car_row, 120), 120, required=True)
        self.car_model_entry = self.works_cell(car_row, 1, self.tr("works.car_model"),
                                               self.works_entry(car_row, 120), 120, required=True)
        vin_box = ctk.CTkFrame(car_row, fg_color="transparent")
        self.vin_var = tk.StringVar()
        self.vin_entry = self.form_entry(vin_box, width=190, textvariable=self.vin_var)
        self.vin_entry.configure(font=("Consolas", 14))
        self.vin_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # Счётчик символов VIN (стандарт - 17)
        self.vin_counter_label = ctk.CTkLabel(vin_box, text=f"0/{VIN_LENGTH}", font=("Arial", 11), width=36)
        self.vin_counter_label.pack(side=tk.LEFT, padx=(4, 0))
        self.vin_var.trace_add("write", self.on_vin_change)
        self.works_cell(car_row, 2, self.tr("works.vin"), vin_box)
        self.mileage_entry = self.works_cell(car_row, 3, self.tr("works.mileage"),
                                             self.works_entry(car_row, 95,
                                                              placeholder_text=self.tr("works.mileage_placeholder")), 95)

        # Машины клиента - кнопками над строкой машины
        self.client_cars_combo = ClientCarChips(
            body, self.tr("works.cars_label"), self.tr("works.new_car"), self.tr("works.select_car"),
            self.tr("works.new_car_chip"), command=self.on_client_car_select,
            pack_kwargs=dict(fill=tk.X, pady=(0, 6), before=car_row),
            before_select=self.works_confirm_car_switch)
        self.client_cars_combo.configure(values=[self.tr("works.new_car")])
        self.client_cars_data = {}  # Словарь для хранения данных машин

        # Поиск: госномер - сразу, как только номер введён целиком (и при уходе из поля / Enter)
        self.car_number_entry.bind("<KeyRelease>", self.on_car_number_keyrelease)
        self.car_number_entry.bind("<FocusOut>", self.on_car_number_change)
        self.car_number_entry.bind("<Return>", self.on_car_number_change)
        self.attach_phone_mask(self.client_phone_entry)
        self.client_phone_entry.bind("<KeyRelease>", self.on_client_phone_keyrelease)
        # Подсказка имён - список под полем, поверх строк ниже
        self.attach_name_autocomplete(self.client_name_entry, col, position="below")

        # Подсказки марок и моделей - поверх формы, под полем
        self.car_brand_entry.bind('<KeyRelease>', self.on_brand_keyrelease)
        self.car_brand_entry.bind('<FocusOut>', self.on_brand_focus_out)
        self.brand_listbox = self.works_popup_listbox(col)
        self.brand_listbox_visible = False
        self.brand_listbox.bind('<<ListboxSelect>>', self.on_brand_select)
        self.car_model_entry.bind('<KeyRelease>', self.on_model_keyrelease)
        self.car_model_entry.bind('<FocusOut>', self.on_model_focus_out)
        self.model_listbox = self.works_popup_listbox(col)
        self.model_listbox_visible = False
        self.model_listbox.bind('<<ListboxSelect>>', self.on_model_select)

        # Контекстное меню для VIN (правая кнопка - вставить)
        self.vin_context_menu = tk.Menu(self.root, tearoff=0)
        self.vin_context_menu.add_command(label=self.tr("works.context_paste"), command=self.paste_to_vin)
        self.vin_entry.bind("<Button-3>", self.show_vin_context_menu)

        # Данные встали (нашли по госномеру / телефону, открыли запись) - поля закрыты от случайной правки.
        # Поправить конкретное поле - карандаш ✎ справа в поле
        self.works_setup_field_locks()

        # Подсветка подставленных полей: поправили руками - подсветка снимается
        self.works_autofilled = {}
        self.works_entry_bg = self.car_brand_entry.cget("fg_color")
        for field in self.works_lookup_fields().values():
            field.bind("<KeyRelease>", self.works_unmark_edited, add="+")

        # Храним выбранный booking_id
        self.selected_booking_id = None
        self.works_number_fill = None
        self.works_phone_fill = None

        # ===== Работы =====
        self.works_list = []
        self.works_tree, self.works_sum_label, self.work_name_entry, self.work_price_entry, _ = \
            self.works_items_section(col, self.tr("works.section_works"), self.add_work_to_list,
                                     self.remove_work_from_list)
        self.work_name_entry.bind('<KeyRelease>', self.on_work_name_keyrelease)
        self.work_name_entry.bind('<FocusOut>', self.on_work_name_focus_out)
        self.work_keyword_listbox = self.works_popup_listbox(col)
        self.work_keyword_listbox_visible = False
        self.work_keyword_listbox.bind('<Double-Button-1>', self.on_work_keyword_select)
        self.work_keyword_listbox.bind('<ButtonRelease-1>', self.on_work_keyword_select)
        self.work_keyword_listbox.bind('<Return>', self.on_work_keyword_select)

        # ===== Запчасти =====
        self.parts_list = []
        self.warehouse_part_ids = {}       # item_id в списке → warehouse_part_id
        self.current_car_warehouse_parts = []
        self.parts_tree, self.parts_sum_label, self.part_name_entry, self.part_price_entry, parts_entry_row = \
            self.works_items_section(col, self.tr("works.section_parts"), self.add_part_to_list,
                                     self.remove_part_from_list)
        self.warehouse_notice_label = AutoHideLabel(
            self.part_name_entry.master.master, text="", text_color="#ef6c00", font=("Arial", 12, "bold"),
            anchor="w", auto_pack=dict(fill=tk.X, pady=(0, 4), before=parts_entry_row))
        # Кнопка "Со склада" - в строке ввода, видна, когда на складе есть детали для этой машины
        self.add_from_warehouse_btn = ctk.CTkButton(
            parts_entry_row, text=self.tr("works.from_warehouse_short"), command=self.add_part_from_warehouse,
            width=10, height=34, corner_radius=8, font=("Arial", 13),
            fg_color="#e3f2fd", text_color="#0d47a1", hover_color="#bbdefb")
        self.part_name_entry.bind('<KeyRelease>', self.on_part_name_keyrelease)
        self.part_name_entry.bind('<FocusOut>', self.on_part_name_focus_out)
        self.part_keyword_listbox = self.works_popup_listbox(col)
        self.part_keyword_listbox_visible = False
        self.part_keyword_listbox.bind('<Double-Button-1>', self.on_part_keyword_select)
        self.part_keyword_listbox.bind('<ButtonRelease-1>', self.on_part_keyword_select)
        self.part_keyword_listbox.bind('<Return>', self.on_part_keyword_select)
        # Добавляем контекстное меню для вставки
        self.setup_entry_context_menu(self.part_name_entry)

        self.works_set_lookup_state(None)
        self.update_total_cost()

        # Колонка по центру и не шире WORKS_MAX_WIDTH; нижняя строка - той же ширины
        self.works_scroll.bind("<Configure>", self.works_relayout, add="+")
        self.works_column.bind("<Configure>", lambda e: self.root.after_idle(self._works_align_bottom), add="+")
        self.works_frame.bind("<Configure>", lambda e: self.root.after_idle(self._works_align_bottom), add="+")

    def works_items_section(self, parent, title, on_add, on_remove):
        """Карточка "Работы" / "Запчасти": строка ввода "название | цена | +" над списком, сумма под списком.
        Возвращает (список, надпись суммы, поле названия, поле цены, строка ввода)"""
        _, body = self.form_section(parent, title)
        entry_row = ctk.CTkFrame(body, fg_color="transparent")
        entry_row.pack(fill=tk.X)
        name_entry = self.form_entry(entry_row, placeholder_text=self.tr("works.name_placeholder"))
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        price_entry = self.form_entry(entry_row, width=100, placeholder_text=self.tr("works.price_placeholder"))
        price_entry.pack(side=tk.LEFT, padx=(8, 0))
        ctk.CTkButton(entry_row, text="+", width=40, height=34, corner_radius=8, font=("Arial", 18, "bold"),
                      fg_color="#1565c0", hover_color="#0d47a1", command=on_add).pack(side=tk.LEFT, padx=(8, 0))

        def on_name_enter(event):
            # Enter в названии: цена ещё не введена - переходим в цену, иначе добавляем
            if not price_entry.get().strip():
                price_entry.focus_set()
            else:
                on_add()
            return "break"

        name_entry.bind("<Return>", on_name_enter)
        price_entry.bind("<Return>", lambda e: (on_add(), "break")[1])

        items = WorkItemsList(body, self.tr("works.list_empty"), on_remove=on_remove,
                              on_change=self.update_total_cost, tag_text=self.tr("works.warehouse_tag"))
        items.pack(fill=tk.X, pady=(8, 0))
        sum_label = ctk.CTkLabel(body, text="", font=("Arial", 14, "bold"), text_color="#37474f", anchor="e")
        sum_label.pack(fill=tk.X, pady=(6, 0))
        return items, sum_label, name_entry, price_entry, entry_row

    def restore_placeholder(self, entry):
        """CTkEntry показывает подсказку-заполнитель только после ухода фокуса - вернуть её у очищенного поля"""
        try:
            if not entry.get() and self.root.focus_get() is not entry._entry:
                entry._activate_placeholder()
        except (AttributeError, KeyError, tk.TclError):
            pass

    def works_car_title(self):
        """Машина в форме одной строкой: "Kia Rio А123БВ777" """
        parts = [self.car_brand_entry.get().strip(), self.car_model_entry.get().strip(),
                 self.car_number_entry.get().strip().upper()]
        return " ".join(p for p in parts if p)

    def works_update_edit_banner(self):
        """Заголовок вкладки: обычный или "✎ Редактирование записи: ..." с кнопкой выхода (высота строки та же)"""
        if getattr(self, "editing_work_id", None):
            self.works_edit_banner_label.configure(
                text=self.tr("works.edit_banner", car=self.works_editing_title or "—"),
                font=("Segoe UI", 18, "bold"), text_color="#e65100")
            self.works_edit_banner.pack(side=tk.RIGHT)
        else:
            self.works_edit_banner_label.configure(text=self.tr("works.title"), font=("Segoe UI", 20, "bold"),
                                                   text_color=self.works_title_color)
            self.works_edit_banner.pack_forget()

    def works_form_snapshot(self):
        """Состояние формы - чтобы понять, есть ли несохранённые правки в редактируемой записи"""
        fields = self.snapshot_fields(self.works_lookup_fields())
        fields["mileage"] = self.mileage_entry.get()
        fields["master"] = self.worker_combo.get()
        return fields, tuple(self.works_list), tuple(self.parts_list)

    def works_has_unsaved_edits(self):
        snapshot = getattr(self, "works_edit_snapshot", None)
        return snapshot is None or snapshot != self.works_form_snapshot()

    def works_find_car_booking(self, car_number):
        """Запись, которую надо открыть при выборе этой машины: та, из которой только что ушли
        (переключившись на другую машину), или запись "в работе". None - записи нет"""
        left = getattr(self, "works_left_booking", None)
        if left and left["number"].upper() == car_number.upper():
            return left["booking_id"]
        active = self.db.get_active_work_by_car_number(car_number)
        return active["booking_id"] if active else None

    def works_leave_current_record(self):
        """Уходим из текущей записи (переключили машину). Есть несохранённые правки - спрашиваем, сохранить ли.
        Возвращает False - остаёмся в текущей записи"""
        editing = getattr(self, "editing_work_id", None)
        if editing:
            unsaved = self.works_has_unsaved_edits()
            title = self.works_editing_title
        else:
            # Новая, ещё не сохранённая запись - "правки" есть, если уже добавили работы или запчасти
            unsaved = bool(self.works_list or self.parts_list)
            title = self.works_car_title()
        if editing and self.selected_booking_id:
            # Запомним, откуда ушли: нажмут эту машину снова - откроем эту же запись
            self.works_left_booking = {"number": self.car_number_entry.get().strip(),
                                       "booking_id": self.selected_booking_id}

        if unsaved:
            answer = messagebox.askyesnocancel(
                self.tr("works.dialog_unsaved_title"),
                self.tr("works.dialog_unsaved_body", car=title or "—"))
            if answer is None:
                return False
            if answer:
                self.add_work()
                if getattr(self, "editing_work_id", None) or self.works_list:
                    return False  # не сохранилось (не прошла проверка или отменили) - остаёмся в записи
                return True
        self.clear_work_form()
        return True

    def works_confirm_car_switch(self, value):
        """Нажали другую машину клиента или "+ новая".
        - У выбранной машины есть запись (в работе или та, из которой только что ушли) - открываем её
          со всеми работами, как "Редактировать".
        - Редактируем сохранённую запись - новая машина не должна записаться поверх неё: открываем новую
          запись для того же клиента, а редактируемая остаётся в базе.
        Несохранённые правки - спрашиваем, сохранить ли. Возвращает False - выбор кнопки уже обработан
        или отменён"""
        car_info = self.client_cars_data.get(value)
        booking_id = self.works_find_car_booking(car_info["number"]) if car_info else None
        if booking_id and booking_id == self.selected_booking_id and getattr(self, "editing_work_id", None):
            booking_id = None  # это и есть открытая запись
        if booking_id:
            if not self.works_leave_current_record():
                return False
            self.open_booking_in_add_work(booking_id)
            self.works_show_info_banner(self.tr("works.record_reopened", car=self.works_car_title() or value))
            return False  # форму уже заполнили целиком

        if not getattr(self, "editing_work_id", None):
            return True
        name = self.client_name_entry.get().strip()
        phone_digits = phone_mask_digits(self.client_phone_entry.get())
        if not self.works_leave_current_record():
            return False

        # Новая запись для того же клиента
        self.client_name_entry.insert(0, name)
        self.set_phone_value(self.client_phone_entry, phone_digits)
        self.load_client_cars("+7" + phone_digits if phone_digits else "", name, auto_select=False)
        # Телефон уже "найден" - повторно по нему не ищем
        self.works_phone_fill = {"digits": phone_digits, "filled": {}}
        self.works_lock_filled()
        car = value if value in self.client_cars_data else self.tr("works.new_record_new_car")
        self.works_show_info_banner(self.tr("works.new_record_opened", car=car))
        return True

    def works_show_info_banner(self, text, ms=3500):
        """Зелёное сообщение на несколько секунд - всплывает поверх верха формы (по ширине колонки),
        ничего не сдвигая; клик по нему - скрыть сразу"""
        banner = self.works_info_banner
        banner.configure(text=text)
        self.root.update_idletasks()
        col = self.works_column
        x = col.winfo_rootx() - self.works_frame.winfo_rootx()
        width = col.winfo_width() if col.winfo_width() > 1 else self.WORKS_MAX_WIDTH
        # Ровно поверх строки заголовка (с небольшим запасом), чтобы из-под него ничего не выглядывало
        row = self.works_title_row
        y = row.winfo_rooty() - self.works_frame.winfo_rooty() - 4
        banner.configure(width=width, height=row.winfo_height() + 8)
        banner.place(x=x, y=max(4, y))
        banner.lift()
        banner.bind("<Button-1>", lambda e: banner.place_forget())
        job = getattr(self, "_works_info_banner_job", None)
        if job:
            self.root.after_cancel(job)
        self._works_info_banner_job = self.root.after(ms, banner.place_forget)

    def works_relayout(self, event=None):
        """Колонка вкладки - по центру и не шире WORKS_MAX_WIDTH; нижняя строка - по ширине колонки"""
        pad = max(8, (self.works_scroll.winfo_width() - self.WORKS_MAX_WIDTH) // 2)
        if getattr(self, "_works_pad", None) != pad:
            self._works_pad = pad
            self.works_column.pack_configure(padx=pad)
        self.root.after_idle(self._works_align_bottom)

    def _works_align_bottom(self):
        col = self.works_column
        if not col.winfo_ismapped() or col.winfo_width() <= 1:
            return
        left = col.winfo_rootx() - self.works_frame.winfo_rootx()
        right = self.works_frame.winfo_width() - left - col.winfo_width()
        self.works_bottom_bar.pack_configure(padx=(max(10, left), max(10, right)))

    WORKS_LOCK_TAG = "WorksFieldLock"
    WORKS_LOCK_ALLOWED_KEYS = {"Tab", "ISO_Left_Tab", "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
                               "Escape", "Return", "KP_Enter", "Shift_L", "Shift_R", "Control_L", "Control_R",
                               "Alt_L", "Alt_R"}

    def works_setup_field_locks(self):
        """Замок на полях клиента и машины: набор с клавиатуры, вставка и вырезание не проходят, пока поле закрыто
        (программа при этом может менять поле как угодно). Карандаш ✎ открывает поле для правки"""
        self.works_locked = set()
        self.works_lock_widgets = {}   # внутреннее поле tk.Entry -> ключ
        self.works_lock_pencils = {}
        fields = self.works_lookup_fields()
        self.works_text_color = self.car_brand_entry.cget("text_color")
        for key, entry in fields.items():
            inner = entry._entry
            inner.bindtags((self.WORKS_LOCK_TAG,) + inner.bindtags())
            self.works_lock_widgets[str(inner)] = key
            pencil = ctk.CTkButton(entry.master, text="✎", width=26, height=24, corner_radius=6,
                                   font=("Arial", 14), fg_color="transparent", hover_color="#e3f2fd",
                                   text_color="#1565c0", cursor="hand2",
                                   command=lambda key=key: self.works_unlock_field(key, focus=True))
            self.works_lock_pencils[key] = pencil
        self.root.bind_class(self.WORKS_LOCK_TAG, "<Key>", self._works_lock_key)
        for event in ("<<Paste>>", "<<Cut>>", "<<Clear>>", "<<PasteSelection>>"):
            self.root.bind_class(self.WORKS_LOCK_TAG, event, self._works_lock_block)

    def _works_lock_is_locked(self, widget):
        return self.works_lock_widgets.get(str(widget)) in self.works_locked

    def _works_lock_key(self, event):
        if not self._works_lock_is_locked(event.widget):
            return None
        if event.keysym in self.WORKS_LOCK_ALLOWED_KEYS:
            return None
        if event.state & 0x4 and event.keysym.lower() in ("c", "a", "insert", "cyrillic_es", "cyrillic_ef"):
            return None   # Ctrl+C / Ctrl+A - копировать можно
        return "break"

    def _works_lock_block(self, event):
        return "break" if self._works_lock_is_locked(event.widget) else None

    def works_lock_field(self, key):
        """Закрыть поле, если в нём что-то есть"""
        entry = self.works_lookup_fields()[key]
        value = entry.get()
        if not value.strip() or (key == "phone" and not phone_mask_digits(value)):
            return
        self.works_locked.add(key)
        entry.configure(text_color="#455a64")
        pencil = self.works_lock_pencils[key]
        if key == "vin":
            # У VIN справа счётчик 17/17 - карандаш встаёт на его место
            pencil.place(in_=self.vin_counter_label, relx=0.5, rely=0.5, anchor="center")
        else:
            pencil.place(in_=entry, relx=1.0, x=-4, rely=0.5, anchor="e")
        pencil.lift()

    def works_unlock_field(self, key, focus=False):
        """Открыть поле для правки (карандаш)"""
        self.works_locked.discard(key)
        entry = self.works_lookup_fields()[key]
        entry.configure(text_color=self.works_text_color)
        self.works_lock_pencils[key].place_forget()
        if focus:
            entry.focus_set()
            entry.icursor(tk.END)
            if key != "phone":
                entry.select_range(0, tk.END)

    def works_lock_filled(self):
        """Закрыть все заполненные поля клиента и машины (данные встали)"""
        for key in self.works_lookup_fields():
            self.works_lock_field(key)

    def works_unlock_empty(self):
        """Пустое поле закрытым не держим - его надо заполнить"""
        fields = self.works_lookup_fields()
        for key in list(self.works_locked):
            value = fields[key].get()
            if not value.strip() or (key == "phone" and not phone_mask_digits(value)):
                self.works_unlock_field(key)

    def works_unlock_all(self):
        for key in list(getattr(self, "works_locked", ())):
            self.works_unlock_field(key)

    def works_lookup_fields(self):
        """Поля, которые подставляет поиск по госномеру / телефону / записи"""
        return {"name": self.client_name_entry, "phone": self.client_phone_entry, "number": self.car_number_entry,
                "brand": self.car_brand_entry, "model": self.car_model_entry, "vin": self.vin_entry}

    def works_mark_autofilled(self, before):
        """Подсветить поля, которые изменил поиск (before - значения до поиска)"""
        fields = self.works_lookup_fields()
        for key, value in self.snapshot_fields(fields).items():
            if value == before.get(key):
                continue
            empty = not value.strip() or (key == "phone" and not phone_mask_digits(value))
            if empty:
                self.works_autofilled.pop(key, None)
                fields[key].configure(fg_color=self.works_entry_bg)
            else:
                self.works_autofilled[key] = value
                fields[key].configure(fg_color=self.WORKS_AUTOFILL_BG)

    def works_unmark_edited(self, event=None):
        """Снять подсветку с полей, которые с тех пор поменялись (поправили руками или стёрли)"""
        fields = self.works_lookup_fields()
        for key in list(self.works_autofilled):
            if fields[key].get() != self.works_autofilled[key]:
                self.works_autofilled.pop(key)
                fields[key].configure(fg_color=self.works_entry_bg)

    def works_clear_marks(self):
        fields = self.works_lookup_fields()
        for key in list(self.works_autofilled):
            fields[key].configure(fg_color=self.works_entry_bg)
        self.works_autofilled = {}

    def works_set_lookup_state(self, state, text=""):
        """Результат поиска: строка под госномером и рамка карточки.
        state: "found" - зелёная, "new" - оранжевая, "pick" - красный текст (выбрать машину), None - обычная"""
        colors = {"found": self.FORM_STATE_COLORS["found"], "new": self.FORM_STATE_COLORS["new"], "pick": "#c62828"}
        if state and text:
            self.works_lookup_status.configure(text=text, text_color=colors[state])
            self.works_lookup_status.pack(fill=tk.X, pady=(0, 6), after=self.works_search_row)
            self.works_lookup_hint.pack_forget()
        else:
            self.works_lookup_status.configure(text="")
            self.works_lookup_status.pack_forget()
            self.works_lookup_hint.pack(fill=tk.X, pady=(0, 4), before=self.works_search_row)
        self.form_set_card_state(self.works_owner_card, state if state in ("found", "new") else None)

    # Обработчики автокомплита для марки
    def on_brand_keyrelease(self, event):
        """Обработчик ввода текста для марки"""
        if "brand" in getattr(self, "works_locked", ()):
            return  # поле закрыто - подсказки не нужны
        search_text = self.car_brand_entry.get().strip()
        if len(search_text) < 1:
            self.hide_brand_listbox()
            return

        brands = self.db.search_car_brands(search_text)
        if brands:
            self.show_brand_listbox(brands)
        else:
            self.hide_brand_listbox()

    def show_brand_listbox(self, brands):
        """Показать список марок"""
        self.brand_listbox.delete(0, tk.END)
        for brand in brands:
            self.brand_listbox.insert(tk.END, brand)
        # Список - поверх формы, под полем
        self.place_popup(self.brand_listbox, self.car_brand_entry)
        self.brand_listbox_visible = True

    def hide_brand_listbox(self):
        """Скрыть список марок"""
        if self.brand_listbox_visible:
            self.hide_popup(self.brand_listbox)
            self.brand_listbox_visible = False

    def on_vin_change(self, *args):
        """Ограничить VIN 17 символами (без пробелов, заглавными) и обновить счётчик"""
        value = self.vin_var.get()
        cleaned = re.sub(r"\s", "", value).upper()[:VIN_LENGTH]
        if cleaned != value:
            # Внутри trace-обработчика Tcl не вызывает его повторно, поэтому счётчик обновляем здесь же
            self.vin_var.set(cleaned)

        length = len(cleaned)
        if length == 0:
            color = ("gray40", "gray60")
        elif length < VIN_LENGTH:
            color = "#ef4444"
        else:
            color = "#22c55e"
        self.vin_counter_label.configure(text=f"{length}/{VIN_LENGTH}", text_color=color)

    def ask_vin_overwrite(self, old_vin, new_vin):
        """Спросить, перезаписать ли VIN машины. Отличающиеся символы подсвечиваются.
        Возвращает "overwrite", "keep" или None (отмена сохранения)."""
        import difflib

        result = {"choice": None}

        dialog = ctk.CTkToplevel(self.root)
        dialog.title(self.tr("works.vin_conflict_title"))
        dialog.geometry("520x300")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(
            dialog,
            text=self.tr("works.vin_conflict_body"),
            font=("Arial", 14),
            wraplength=470,
            justify="left"
        ).pack(padx=25, pady=(20, 15), anchor="w")

        # Разметка различий. При одинаковой длине сравниваем строго по позициям;
        # при разной (пропущен/лишний символ) ищем сдвиг, но совпадением считаем
        # только участки от 3 символов подряд, чтобы случайные одиночные совпадения не "гасили" ошибку
        if len(old_vin) == len(new_vin):
            old_diff = {i for i, (a, b) in enumerate(zip(old_vin, new_vin)) if a != b}
            new_diff = set(old_diff)
        else:
            old_diff, new_diff = set(range(len(old_vin))), set(range(len(new_vin)))
            matcher = difflib.SequenceMatcher(None, old_vin, new_vin, autojunk=False)
            for i, j, size in matcher.get_matching_blocks():
                if size >= 3:
                    old_diff.difference_update(range(i, i + size))
                    new_diff.difference_update(range(j, j + size))

        is_dark = ctk.get_appearance_mode() == "Dark"
        bg = "#2b2b2b" if is_dark else "#ffffff"
        fg = "#ffffff" if is_dark else "#000000"

        def vin_row(label, value, diff, highlight_bg):
            row = ctk.CTkFrame(dialog, fg_color="transparent")
            row.pack(fill="x", padx=25, pady=4)
            ctk.CTkLabel(row, text=label, width=110, anchor="w", font=("Arial", 14)).pack(side="left")
            text = tk.Text(row, height=1, width=len(value) + 1, font=("Consolas", 16, "bold"),
                           bg=bg, fg=fg, relief="flat", borderwidth=0, highlightthickness=0)
            text.tag_configure("diff", background=highlight_bg, foreground="#000000")
            for idx, ch in enumerate(value):
                text.insert(tk.END, ch, ("diff",) if idx in diff else ())
            text.configure(state="disabled")
            text.pack(side="left")

        vin_row(self.tr("works.vin_old_label"), old_vin, old_diff, "#fca5a5")
        vin_row(self.tr("works.vin_new_label"), new_vin, new_diff, "#86efac")

        ctk.CTkLabel(
            dialog,
            text=self.tr("works.vin_length_info", old=len(old_vin), new=len(new_vin)),
            font=("Arial", 12),
            text_color=("gray40", "gray60")
        ).pack(padx=25, pady=(6, 0), anchor="w")

        def choose(value):
            result["choice"] = value
            dialog.destroy()

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(pady=20)
        ctk.CTkButton(btn_row, text=self.tr("works.vin_overwrite_btn"), command=lambda: choose("overwrite"),
                      fg_color="#4caf50", hover_color="#388e3c", width=140).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_row, text=self.tr("works.vin_keep_btn"), command=lambda: choose("keep"),
                      width=140).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_row, text=self.tr("common.cancel"), command=dialog.destroy,
                      fg_color="gray", width=110).pack(side=tk.LEFT, padx=5)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self.root.wait_window(dialog)
        return result["choice"]

    def show_vin_context_menu(self, event):
        """Показать контекстное меню для поля VIN"""
        if "vin" in getattr(self, "works_locked", ()):
            return
        self.vin_context_menu.tk_popup(event.x_root, event.y_root)

    def paste_to_vin(self):
        """Вставить текст из буфера обмена в поле VIN"""
        try:
            clipboard_text = self.root.clipboard_get()
            self.vin_entry.insert(tk.END, clipboard_text)
        except tk.TclError:
            pass  # Буфер обмена пуст

    def add_copy_button(self, parent, text):
        """Кнопка-значок рядом с текстом: по клику копирует text в буфер обмена"""
        btn = ctk.CTkButton(
            parent,
            text="📋",
            width=26,
            height=24,
            font=("Arial", 14),
            fg_color="transparent",
            hover_color=("gray80", "gray30"),
            text_color=("gray30", "gray70"),
            cursor="hand2",
        )

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()  # чтобы текст остался в буфере и после закрытия окна
            btn.configure(text="✓", text_color=("green", "#4ade80"))
            btn.after(1200, lambda: btn.winfo_exists() and btn.configure(
                text="📋", text_color=("gray30", "gray70")))

        btn.configure(command=copy)
        return btn

    def on_brand_select(self, event):
        """Обработчик выбора марки из списка"""
        selection = self.brand_listbox.curselection()
        if selection:
            brand = self.brand_listbox.get(selection[0])
            self.car_brand_entry.delete(0, tk.END)
            self.car_brand_entry.insert(0, brand)
            self.hide_brand_listbox()

            # Автоматически показываем все модели выбранной марки
            models = self.db.search_car_models(brand, "")
            if models:
                self.car_model_entry.delete(0, tk.END)
                self.show_model_listbox(models)
                self.car_model_entry.focus_set()

    def on_brand_focus_out(self, event):
        """Скрыть список при потере фокуса"""
        self.root.after(200, self.hide_brand_listbox)

    # Обработчики для выбора записи клиента
    def refresh_bookings_combo(self):
        """Обновить список записей в комбобоксе"""
        bookings = self.db.get_active_bookings_for_select()
        self.bookings_data = {}
        values = [""]  # Пустой вариант для ручного ввода

        for booking in bookings:
            booking_id, full_name, phone, booking_date, booking_time, car_id = booking
            # Форматируем дату
            if hasattr(booking_date, 'strftime'):
                date_str = booking_date.strftime('%d.%m')
            else:
                date_str = str(booking_date)

            display_text = f"{date_str} {booking_time} - {full_name or self.tr('common.no_name')} ({phone or self.tr('common.no_phone')})"
            values.append(display_text)
            self.bookings_data[display_text] = {
                'id': booking_id,
                'name': full_name or '',
                'phone': phone or '',
                'car_id': car_id
            }

        self.booking_combo.configure(values=values)

    def on_booking_select(self, choice):
        """Обработчик выбора записи из списка"""
        # По записи уже есть наряд (запись "в работе") - открываем его целиком, как "Редактировать":
        # видно, что уже сделано, новые работы дописываются в этот же наряд
        if choice and choice in self.bookings_data:
            booking_id = self.bookings_data[choice]['id']
            already_open = booking_id == self.selected_booking_id and getattr(self, "editing_work_id", None)
            if not already_open and self.db.get_work_by_booking_id(booking_id):
                previous = getattr(self, "_works_booking_choice", "")
                if not self.works_leave_current_record():
                    self.booking_combo.set(previous)   # остались в текущей записи
                    return
                self.open_booking_in_add_work(booking_id)
                self._works_booking_choice = self.booking_combo.get()
                self.works_show_info_banner(self.tr("works.record_reopened", car=self.works_car_title() or choice))
                return
        self._works_booking_choice = choice or ""

        self.works_phone_fill = None
        self.works_number_fill = None
        if choice and choice in self.bookings_data:
            booking_info = self.bookings_data[choice]
            self.selected_booking_id = booking_info['id']
            before = self.snapshot_fields(self.works_lookup_fields())
            # Автозаполнение полей клиента
            self.client_name_entry.delete(0, tk.END)
            self.client_name_entry.insert(0, booking_info['name'])
            self.set_phone_value(self.client_phone_entry, booking_info['phone'])
            # Загружаем машины этого клиента (передаём car_id из записи)
            self.load_client_cars(booking_info['phone'], booking_info['name'], booking_info.get('car_id'))
            self.works_mark_autofilled(before)
            if booking_info['name']:
                self.works_set_lookup_state("found", self.tr("works.lookup_booking", name=booking_info['name']))
            self.works_lock_filled()
            self.works_record_number = self.car_number_entry.get().strip()

            # Если по записи уже есть наряд - подставляем мастера, который его ведёт
            existing_work = self.db.get_work_by_booking_id(booking_info['id'])
            if existing_work:
                worker_id = existing_work[1]
                for name, wid in self.workers_data.items():
                    if wid == worker_id:
                        self.worker_combo.set(name)
                        break
        else:
            self.selected_booking_id = None
            self.client_cars_combo.configure(values=[self.tr("works.new_car")])
            self.client_cars_combo.set("")
            self.client_cars_data = {}
            self.works_set_lookup_state(None)

    def load_client_cars(self, phone, name, booking_car_id=None, auto_select=True):
        """Загрузить машины клиента по телефону или имени.
        booking_car_id - ID машины из записи (None = "Другое авто" в боте)
        auto_select - автоматически выбирать машину при поиске по телефону
        """
        cars = []
        # Сначала ищем по телефону
        if phone:
            cars = self.db.get_client_cars_by_phone(phone)
        # Если не нашли по телефону, ищем по имени
        if not cars and name:
            cars = self.db.get_client_cars_by_name(name)

        self.client_cars_data = {}
        values = [self.tr("works.new_car")]
        selected_car_display = None

        for car in cars:
            car_brand, car_model, car_number, car_vin = car
            display_text = f"{car_brand or ''} {car_model or ''} {car_number or ''}".strip()
            if display_text:
                values.append(display_text)
                self.client_cars_data[display_text] = {
                    'brand': car_brand or '',
                    'model': car_model or '',
                    'number': car_number or '',
                    'vin': car_vin or ''
                }
                # Если есть car_id из записи - ищем соответствующую машину
                if booking_car_id:
                    car_data = self.db.get_car_by_number(car_number)
                    if car_data and car_data.get('id') == booking_car_id:
                        selected_car_display = display_text

        self.client_cars_combo.configure(values=values)

        # Сбрасываем цвет на стандартный
        self.client_cars_combo.configure(text_color="black")

        # Количество машин клиента (без "Новая машина")
        num_cars = len(values) - 1

        # Если auto_select=True и нет booking_car_id - логика для ввода телефона
        if auto_select and booking_car_id is None:
            if num_cars == 1:
                # Одна машина - автоматически выбираем и заполняем поля
                self.client_cars_combo.set(values[1])
                self.on_client_car_select(values[1])
            elif num_cars > 1:
                # Несколько машин - показываем "Выберите авто" красным
                values_with_select = [self.tr("works.select_car")] + values[1:]  # убираем "Новая машина" из начала
                values_with_select.append(self.tr("works.new_car"))  # добавляем в конец
                self.client_cars_combo.configure(values=values_with_select)
                self.client_cars_combo.set(self.tr("works.select_car"))
                self.client_cars_combo.configure(text_color="#c62828")
                # Очищаем поля машины
                self.car_brand_entry.delete(0, tk.END)
                self.car_model_entry.delete(0, tk.END)
                self.car_number_entry.delete(0, tk.END)
                self.vin_var.set("")
            else:
                # Нет машин
                self.client_cars_combo.set(self.tr("works.new_car"))
        # Если booking_car_id передан - старая логика для редактирования записи
        elif booking_car_id is not None:
            if selected_car_display:
                self.client_cars_combo.set(selected_car_display)
                self.on_client_car_select(selected_car_display)
            elif num_cars > 0:
                self.client_cars_combo.set(values[1])
                self.on_client_car_select(values[1])
            else:
                self.client_cars_combo.set(self.tr("works.new_car"))
        else:
            self.client_cars_combo.set(self.tr("works.new_car"))

    def on_client_phone_keyrelease(self, event):
        """При вводе телефона - искать данные клиента и его машины"""
        if "phone" in getattr(self, "works_locked", ()):
            return  # поле закрыто (данные встали) - заново не ищем
        # Ищем только когда номер введён полностью (в маске +7 всегда есть - считаем только цифры после него)
        phone_digits = phone_mask_digits(self.client_phone_entry.get())
        phone_raw = "+7" + phone_digits
        fields = self.works_phone_fill_fields()

        # Номер изменили - убираем всё, что подставили по прошлому номеру
        fill = getattr(self, "works_phone_fill", None)
        if fill and fill["digits"] != phone_digits:
            self.works_phone_fill = None
            undo = fill["filled"]
            if "number" in getattr(self, "works_locked", ()):
                # Машина уже определена (закрыта) - телефон это только контакт: убираем лишь имя,
                # подставленное по прошлому номеру, машину не трогаем
                undo = {k: v for k, v in undo.items() if k == "name"}
            self.undo_autofill(fields, undo)
            self.works_unmark_edited()
            self.works_unlock_empty()
            if not self.works_number_fill:
                self.works_set_lookup_state(None)
        elif fill:
            return  # тот же номер уже обработан

        if len(phone_digits) == 10 and self.works_owner_change_lookup(phone_digits, fields):
            return
        if len(phone_digits) == 10:
            before = self.snapshot_fields(fields)
            # Нормализуем до последних 10 цифр
            last_10 = phone_digits[-10:]

            # Пробуем разные форматы телефона
            phone_variants = [
                f"+7{last_10}",
                f"7{last_10}",
                f"8{last_10}",
                last_10,
            ]

            # Ищем имя клиента
            client_name = None
            for phone_variant in phone_variants:
                client_name = self.db.get_client_name_by_phone(phone_variant)
                if client_name:
                    break

            # Автозаполнение имени - всегда обновляем при найденном клиенте
            if client_name:
                self.client_name_entry.delete(0, tk.END)
                self.client_name_entry.insert(0, client_name)

            # Загружаем машины клиента
            self.load_client_cars(phone_raw, client_name or "")
            self.works_phone_fill = {"digits": phone_digits, "filled": self.autofilled_diff(fields, before)}
            self.works_mark_autofilled(before)

            # Что нашли: одна машина - подставлена, несколько - выбрать, никого - новый клиент
            cars_count = len(self.client_cars_data)
            if cars_count > 1 and self.client_cars_combo.get() == self.tr("works.select_car"):
                self.works_set_lookup_state("pick", self.tr("works.lookup_pick_car", count=cars_count))
                self.works_lock_filled()
            elif client_name or cars_count:
                self.works_set_lookup_state("found", self.tr("works.lookup_client_found",
                                                             name=client_name or self.client_name_entry.get().strip()))
                self.works_lock_filled()
            else:
                self.works_set_lookup_state("new", self.tr("works.lookup_new_client"))
        else:
            # Если цифр меньше 10 - очищаем список машин
            self.client_cars_combo.configure(values=[self.tr("works.new_car")])
            self.client_cars_combo.set(self.tr("works.new_car"))
            self.client_cars_data = {}

    def works_owner_change_lookup(self, phone_digits, fields):
        """Машина уже определена (госномер закрыт), а телефон поменяли (через ✎) - возможно, сменился владелец.
        Машину не трогаем (не подставляем машины этого человека), подставляем только его имя, если он есть
        в базе, и предупреждаем: при сохранении спросим, новый ли это владелец. True - обработали"""
        if "number" not in getattr(self, "works_locked", ()):
            return False
        car = self.db.get_car_owner_by_number(self.car_number_entry.get().strip())
        if not car or not car["client_id"]:
            return False
        before = self.snapshot_fields(fields)
        same = self.works_same_person(phone_digits, "", car["owner_phone"], car["owner_name"])
        name = car["owner_name"] if same else self.db.get_client_name_by_phone("+7" + phone_digits)
        self.client_name_entry.delete(0, tk.END)
        if name:
            self.client_name_entry.insert(0, name)
        else:
            # Человека нет в базе - имя прежнего владельца убираем, поле открыто: вписать нового
            self.works_unlock_field("name")
        self.works_phone_fill = {"digits": phone_digits, "filled": self.autofilled_diff(fields, before)}
        self.works_mark_autofilled(before)
        if not name:
            self.client_name_entry.focus_set()
        if same:
            self.works_set_lookup_state("found", self.tr("works.lookup_car_found",
                                                         name=car["owner_name"] or self.tr("common.no_name")))
        else:
            self.works_set_lookup_state("new", self.tr("works.lookup_owner_change",
                                                       owner=car["owner_name"] or self.tr("common.no_name")))
        return True

    def works_phone_fill_fields(self):
        """Поля вкладки "Добавить работу", которые заполняет поиск по телефону / госномеру"""
        return {"name": self.client_name_entry, "phone": self.client_phone_entry, "brand": self.car_brand_entry,
                "model": self.car_model_entry, "number": self.car_number_entry, "vin": self.vin_entry}

    CAR_NUMBER_LIVE_MIN = 8   # с какой длины госномера искать прямо при вводе (номер введён целиком)

    def works_check_record_plate_change(self, car_number, record_number):
        """В открытой записи госномер сменили. Это госномер другой машины из базы - иначе работа молча
        переедет на чужую машину: спрашиваем, открыть ли запись для той машины, или вернуть госномер.
        Госномера в базе нет - считаем, что исправили опечатку"""
        clients = self.db.get_all_clients_by_car_number(car_number)
        if not clients:
            return
        other = clients[0]
        car = " ".join(x for x in (other.get("car_brand"), other.get("car_model")) if x) or car_number.upper()
        owner = other.get("client_name") or self.tr("common.no_name")
        open_other = messagebox.askyesno(
            self.tr("works.dialog_plate_other_car_title"),
            self.tr("works.dialog_plate_other_car_body", number=car_number.upper(), car=car, owner=owner,
                    current=self.works_editing_title or record_number, old=record_number))
        # Госномер записи возвращаем в любом случае: с ним запись и сохраняется, если её сохранят
        self.car_number_entry.delete(0, tk.END)
        self.car_number_entry.insert(0, record_number)
        self.works_lock_field("number")
        if not open_other or not self.works_leave_current_record():
            return

        booking_id = self.works_find_car_booking(car_number)
        if booking_id:
            self.open_booking_in_add_work(booking_id)
            self.works_show_info_banner(self.tr("works.record_reopened", car=self.works_car_title()))
        else:
            # Новая запись: ищем по госномеру как обычно - подставятся владелец и машина
            self.car_number_entry.insert(0, car_number)
            self.on_car_number_change()
            self.works_show_info_banner(self.tr("works.new_record_opened", car=self.works_car_title()))

    def on_car_number_keyrelease(self, event=None):
        """Ввод госномера: ищем через паузу после последней нажатой клавиши, чтобы не дёргать базу на каждую букву"""
        if "number" in getattr(self, "works_locked", ()):
            return
        pending = getattr(self, "_car_number_search_job", None)
        if pending:
            self.root.after_cancel(pending)
        self._car_number_search_job = self.root.after(400, lambda: self.on_car_number_change(live=True))

    def on_car_number_change(self, event=None, live=False):
        """Автозаполнение по госномеру. live - поиск прямо во время ввода (иначе - уход из поля / Enter)"""
        self._car_number_search_job = None
        car_number = self.car_number_entry.get().strip()

        # Открыта запись (редактирование или выбрана из списка) и госномер в ней поменяли
        record_number = getattr(self, "works_record_number", None)
        in_record = getattr(self, "editing_work_id", None) or getattr(self, "selected_booking_id", None)
        if in_record and record_number:
            if live or car_number.upper() == record_number.upper():
                return
            if car_number and len(car_number) >= 3:
                self.works_check_record_plate_change(car_number, record_number)
            return

        # Номер изменили - убираем всё, что подставили по прошлому номеру (поправленное руками не трогаем)
        fill = getattr(self, "works_number_fill", None)
        if fill and fill["number"].upper() != car_number.upper():
            self.works_number_fill = None
            self.works_phone_fill = None
            self.undo_autofill(self.works_phone_fill_fields(), fill["filled"])
            self.works_unmark_edited()
            self.works_unlock_empty()
            self.client_cars_combo.configure(values=[self.tr("works.new_car")])
            self.client_cars_combo.set("")
            self.client_cars_data = {}
            self.check_warehouse_for_car("")
            self.works_set_lookup_state(None)
        elif fill:
            return  # этот номер уже найден и подставлен
        if car_number.upper() != getattr(self, "_works_looked_up_number", None):
            self._works_looked_up_number = None
        elif self._works_looked_up_number:
            return  # этот номер уже искали (например, открыто окно выбора владельца)

        if not car_number or len(car_number) < 3 or (live and len(car_number) < self.CAR_NUMBER_LIVE_MIN):
            return

        # Проверяем, не заполнены ли уже другие поля машины
        if self.car_brand_entry.get().strip() or self.car_model_entry.get().strip():
            return  # Поля уже заполнены, не перезаписываем

        # Ищем всех клиентов по госномеру
        clients = self.db.get_all_clients_by_car_number(car_number)

        if not clients:
            if not live:
                self.works_set_lookup_state("new", self.tr("works.lookup_new_car"))
            return

        self._works_looked_up_number = car_number.upper()
        if len(clients) == 1:
            # Только один клиент - заполняем сразу
            self.fill_car_and_client_info(clients[0])
        else:
            # Несколько клиентов - показываем окно выбора
            self.show_client_selection_dialog(clients, car_number)

    def fill_car_and_client_info(self, client_info):
        """Заполнить поля машины и клиента"""
        fields = self.works_phone_fill_fields()
        before = self.snapshot_fields(fields)
        car_brand = client_info.get("car_brand", "")
        car_model = client_info.get("car_model", "")

        # Заполняем данные о машине
        self.car_brand_entry.delete(0, tk.END)
        self.car_brand_entry.insert(0, car_brand)

        self.car_model_entry.delete(0, tk.END)
        self.car_model_entry.insert(0, car_model)

        # VIN заполняем если есть
        if client_info.get("vin"):
            self.vin_entry.delete(0, tk.END)
            self.vin_entry.insert(0, client_info["vin"])

        # Заполняем данные клиента
        if client_info.get("client_name"):
            self.client_name_entry.delete(0, tk.END)
            self.client_name_entry.insert(0, client_info["client_name"])

        if client_info.get("client_phone"):
            self.set_phone_value(self.client_phone_entry, client_info["client_phone"])

        # Загружаем список машин клиента
        self.load_client_cars_without_autofill(client_info.get("client_phone", ""), client_info.get("client_name", ""))

        # Выбираем текущую машину в списке
        car_number = self.car_number_entry.get().strip().upper()
        if car_number:
            # Ищем машину в списке по госномеру или по марке+модели
            for display_text, car_data in self.client_cars_data.items():
                if car_data.get('number', '').upper() == car_number:
                    self.client_cars_combo.set(display_text)
                    break
            else:
                # Если не нашли по номеру - ищем по марке и модели
                for display_text, car_data in self.client_cars_data.items():
                    if car_data.get('brand') == car_brand and car_data.get('model') == car_model:
                        self.client_cars_combo.set(display_text)
                        break

        # Проверяем склад на наличие запчастей для этого авто
        self.check_warehouse_for_car(self.car_number_entry.get().strip())

        # Запоминаем подставленное: сменят госномер - уберём. Телефон уже подставлен - по нему повторно не ищем
        self.works_number_fill = {"number": self.car_number_entry.get().strip(),
                                  "filled": self.autofilled_diff(fields, before)}
        self.works_phone_fill = {"digits": phone_mask_digits(self.client_phone_entry.get()), "filled": {}}
        self.works_mark_autofilled(before)
        name = client_info.get("client_name") or self.tr("common.no_name")
        self.works_set_lookup_state("found", self.tr("works.lookup_car_found", name=name))
        self.works_lock_filled()
        # Всё подставили - курсор сразу в "Пробег"
        self.mileage_entry.focus_set()

    def show_client_selection_dialog(self, clients, car_number):
        """Показать диалог выбора клиента для госномера"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(self.tr("works.dialog_select_client_title", car_number=car_number))
        dialog.geometry("450x300")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=self.tr("works.dialog_select_client_label", car_number=car_number),
                    font=("Arial", 13)).pack(pady=(15, 10), padx=15, anchor="w")

        # Фрейм для списка клиентов
        list_frame = ctk.CTkScrollableFrame(dialog, height=180)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        selected_client = [None]  # Используем список для хранения выбора

        def select_client(client):
            selected_client[0] = client
            dialog.destroy()
            self.fill_car_and_client_info(client)

        for client in clients:
            name = client.get("client_name") or self.tr("common.no_name")
            phone = client.get("client_phone") or self.tr("common.no_phone")
            btn_text = f"{name}  |  {phone}"

            btn = ctk.CTkButton(list_frame, text=btn_text, anchor="w",
                               command=lambda c=client: select_client(c),
                               fg_color="#2b2b2b", hover_color="#3b3b3b",
                               height=40, font=("Arial", 12))
            btn.pack(fill=tk.X, pady=3)

        # Кнопка отмены
        ctk.CTkButton(dialog, text=self.tr("common.cancel"), command=dialog.destroy,
                     fg_color="#757575", hover_color="#616161", width=100).pack(pady=15)

    def load_client_cars_without_autofill(self, phone, name):
        """Загрузить машины клиента без автозаполнения полей"""
        cars = []
        if phone:
            cars = self.db.get_client_cars_by_phone(phone)
        if not cars and name:
            cars = self.db.get_client_cars_by_name(name)

        self.client_cars_data = {}
        values = [self.tr("works.new_car")]

        for car in cars:
            car_brand, car_model, car_number, car_vin = car
            display_text = f"{car_brand or ''} {car_model or ''} {car_number or ''}".strip()
            if display_text:
                values.append(display_text)
                self.client_cars_data[display_text] = {
                    'brand': car_brand or '',
                    'model': car_model or '',
                    'number': car_number or '',
                    'vin': car_vin or ''
                }

        self.client_cars_combo.configure(values=values)
        self.client_cars_combo.set("")  # Не выбираем ничего

    def on_client_car_select(self, choice):
        """Обработчик выбора машины клиента"""
        fields = self.works_phone_fill_fields()
        before = self.snapshot_fields(fields)
        self._fill_client_car(choice)
        fill = getattr(self, "works_phone_fill", None)
        if fill:
            # Машину выбрали из списка по телефону - при смене номера её тоже уберём
            fill["filled"].update(self.autofilled_diff(fields, before))
        number_fill = getattr(self, "works_number_fill", None)
        if number_fill:
            if choice in self.client_cars_data:
                # Другая машина того же клиента - теперь "найденный" госномер этот
                number_fill["number"] = self.car_number_entry.get().strip()
                number_fill["filled"].update(self.autofilled_diff(fields, before))
            else:
                # Новая машина: владельца оставляем, новый госномер ищем заново
                self.works_number_fill = None
        self._works_looked_up_number = None
        self.works_mark_autofilled(before)

        if choice in self.client_cars_data:
            name = self.client_name_entry.get().strip() or self.tr("common.no_name")
            self.works_set_lookup_state("found", self.tr("works.lookup_client_found", name=name))
            self.check_warehouse_for_car(self.car_number_entry.get().strip())
            self.works_lock_filled()
            self.mileage_entry.focus_set()
        elif choice == self.tr("works.new_car"):
            self.works_unlock_empty()
            self.works_set_lookup_state("new", self.tr("works.lookup_new_car"))
            self.check_warehouse_for_car("")
            self.car_number_entry.focus_set()

    def _fill_client_car(self, choice):
        # Сбрасываем красный цвет при любом выборе
        self.client_cars_combo.configure(text_color="black")

        if choice and choice in self.client_cars_data:
            car_info = self.client_cars_data[choice]
            # Заполняем поля машины
            self.car_brand_entry.delete(0, tk.END)
            self.car_brand_entry.insert(0, car_info['brand'])
            self.car_model_entry.delete(0, tk.END)
            self.car_model_entry.insert(0, car_info['model'])
            self.car_number_entry.delete(0, tk.END)
            self.car_number_entry.insert(0, car_info['number'])
            self.vin_var.set(car_info.get('vin', ''))
        elif choice == self.tr("works.new_car"):
            # Очищаем поля машины для новой
            self.car_brand_entry.delete(0, tk.END)
            self.car_model_entry.delete(0, tk.END)
            self.car_number_entry.delete(0, tk.END)
            self.vin_var.set("")
        elif choice == self.tr("works.select_car"):
            # Не делаем ничего, ждём выбора
            self.client_cars_combo.configure(text_color="#c62828")

    # Обработчики автокомплита для модели
    def on_model_keyrelease(self, event):
        """Обработчик ввода текста для модели"""
        if "model" in getattr(self, "works_locked", ()):
            return  # поле закрыто - подсказки не нужны
        brand = self.car_brand_entry.get().strip()
        if not brand:
            self.hide_model_listbox()
            return

        search_text = self.car_model_entry.get().strip()
        models = self.db.search_car_models(brand, search_text)
        if models:
            self.show_model_listbox(models)
        else:
            self.hide_model_listbox()

    def show_model_listbox(self, models):
        """Показать список моделей"""
        self.model_listbox.delete(0, tk.END)
        for model in models:
            self.model_listbox.insert(tk.END, model)
        # Список - поверх формы, под полем
        self.place_popup(self.model_listbox, self.car_model_entry)
        self.model_listbox_visible = True

    def hide_model_listbox(self):
        """Скрыть список моделей"""
        if self.model_listbox_visible:
            self.hide_popup(self.model_listbox)
            self.model_listbox_visible = False

    def on_model_select(self, event):
        """Обработчик выбора модели из списка"""
        selection = self.model_listbox.curselection()
        if selection:
            model = self.model_listbox.get(selection[0])
            self.car_model_entry.delete(0, tk.END)
            self.car_model_entry.insert(0, model)
            self.hide_model_listbox()

    def on_model_focus_out(self, event):
        """Скрыть список при потере фокуса"""
        self.root.after(200, self.hide_model_listbox)


    def refresh_workers_combo(self):
        """Обновить выпадающий список работников. Кто сегодня по расписанию отсутствует -
        в конце списка с пометкой ("Иванов — отпуск"). Выбранный мастер сохраняется"""
        workers = self.db.get_all_workers()
        today = date.today()
        try:
            schedule = self.db.get_worker_schedule(today, today)
        except Exception as e:
            print(f"Не удалось загрузить расписание сотрудников: {e}")
            schedule = {}
        previous_id = getattr(self, "workers_data", {}).get(self.worker_combo.get())

        working, absent = [], []
        for worker_id, name in workers:
            kind = schedule.get(worker_id, {}).get(today)
            if kind:
                absent.append((self.tr("works.worker_absent_suffix", name=name, kind=self.staff_kind_label(kind)), worker_id))
            else:
                working.append((name, worker_id))
        self.workers_data = dict(working + absent)
        self.worker_names_by_id = {worker_id: name for worker_id, name in workers}

        worker_names = [self.tr("works.select_master")] + list(self.workers_data.keys())
        self.worker_combo.configure(values=worker_names)
        selected = next((name for name, wid in self.workers_data.items() if wid == previous_id), None)
        self.worker_combo.set(selected or self.tr("works.select_master"))

    def works_available_warehouse_parts(self, car_number):
        """Детали со склада, которые можно добавить в наряд: "на складе" для этой машины
        плюс детали редактируемого наряда, которые из него убрали (на складе они ещё "установлена" -
        вернутся "на склад" только при сохранении), минус уже добавленные в список"""
        in_form = set(self.warehouse_part_ids.values())
        parts = [p for p in self.db.get_warehouse_parts_by_car_number(car_number) if p[0] not in in_form]
        known = {p[0] for p in parts}
        for part in getattr(self, "works_linked_wh_parts", {}).values():
            if part[0] not in in_form and part[0] not in known:
                parts.append(part)
        return parts

    def check_warehouse_for_car(self, car_number, left=False):
        """Проверить склад на наличие запчастей для данного автомобиля.
        left - часть деталей уже добавили в наряд ("на складе ещё ...")"""
        if not car_number:
            self.warehouse_notice_label.configure(text="")
            self.add_from_warehouse_btn.pack_forget()
            self.current_car_warehouse_parts = []
            return
        parts = self.works_available_warehouse_parts(car_number)
        self.current_car_warehouse_parts = parts
        if parts:
            count = len(parts)
            if left:
                text = self.tr("works.warehouse_notice_left_many", count=count) if count > 1 else self.tr("works.warehouse_notice_left_one")
            else:
                text = self.tr("works.warehouse_notice_many", count=count) if count > 1 else self.tr("works.warehouse_notice_one")
            self.warehouse_notice_label.configure(text=text)
            self.add_from_warehouse_btn.pack(side=tk.LEFT, padx=(8, 0))
        else:
            self.warehouse_notice_label.configure(text="")
            self.add_from_warehouse_btn.pack_forget()

    def add_part_from_warehouse(self):
        """Добавить запчасть со склада в список"""
        # Берём со склада заново: пока открыта вкладка, на складе могли поменять оплату или цену
        car_number = self.car_number_entry.get().strip()
        if car_number:
            self.current_car_warehouse_parts = self.works_available_warehouse_parts(car_number)
        parts = self.current_car_warehouse_parts
        if not parts:
            self.check_warehouse_for_car(car_number)
            return
        self._show_warehouse_part_selection(parts)

    def warehouse_part_list_entry(self, part_name, price, is_paid):
        """Как складская запчасть выглядит в списке наряда: оплаченная заранее - с пометкой и за 0"""
        if is_paid:
            return f"{part_name} ({self.tr('warehouse.already_paid_marker')})", 0.0
        return part_name, float(price) if price else 0.0

    def works_sync_warehouse_parts(self):
        """Сверить со складом запчасти, добавленные в наряд со склада: на складе могли поменять
        "оплачено ранее" или цену - в наряде должно быть так же. И обновить надпись "на складе есть ..." """
        if not hasattr(self, "parts_tree"):
            return
        children = self.parts_tree.get_children()
        for item_id, wh_part_id in list(self.warehouse_part_ids.items()):
            if item_id not in children:
                continue
            part = self.db.get_warehouse_part_by_id(wh_part_id)
            if not part:
                continue
            name, price = self.warehouse_part_list_entry(part["part_name"], part["price"], part.get("is_paid"))
            index = children.index(item_id)
            if self.parts_list[index] != (name, price):
                self.parts_list[index] = (name, price)
                self.parts_tree.update_item(item_id, self.part_row_values(name, price, part["price"]))
        car_number = self.car_number_entry.get().strip()
        if car_number:
            self.check_warehouse_for_car(car_number)
        self.update_total_cost()

    def _add_warehouse_part_to_list(self, part):
        """Добавить одну складскую запчасть в таблицу"""
        part_id, part_name, quantity, price, notes, is_paid = part
        price = float(price) if price else 0.0

        # Уже оплаченные позиции (например, платное хранение шин) не добавляем
        # повторно в счёт -- клиент уже заплатил при сдаче на склад
        original = price
        name, price = self.warehouse_part_list_entry(part_name, price, is_paid)
        self.parts_list.append((name, price))
        item_id = self.parts_tree.insert("", tk.END, values=self.part_row_values(name, price, original),
                                         tags=("warehouse",))
        self.warehouse_part_ids[item_id] = part_id
        # На складе деталь станет "установлена" только при сохранении наряда (save_warehouse_parts_for_work):
        # не сохранили (закрыли программу, сбросили форму) - на складе ничего не меняется

        # Обновляем уведомление "на складе ещё ..."
        self.check_warehouse_for_car(self.car_number_entry.get().strip(), left=True)
        self.update_total_cost()

    def _show_warehouse_part_selection(self, parts):
        """Диалог выбора запчастей со склада (с чекбоксами)"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(self.tr("works.dialog_select_from_warehouse_title"))
        dialog.geometry("480x" + str(min(120 + len(parts) * 48, 480)))
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(dialog, text=self.tr("works.dialog_select_from_warehouse_label"),
                     font=("Segoe UI", 13, "bold")).pack(pady=(14, 6), padx=15, anchor="w")

        # Кнопки — пакуем ПЕРВЫМИ с side=BOTTOM, чтобы всегда были видны
        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill=tk.X, padx=15, pady=(6, 14), side=tk.BOTTOM)

        # Список с чекбоксами — пакуем ПОСЛЕ кнопок, заполняет оставшееся место
        scroll_frame = ctk.CTkScrollableFrame(dialog)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=4)

        check_vars = []
        for part in parts:
            part_id, part_name, quantity, price, notes, is_paid = part
            if is_paid:
                price_str = self.tr("warehouse.already_paid_marker")
            else:
                price_str = self.format_currency(float(price)) if price else "—"
            label = f"{part_name}  |  {price_str}"
            if notes:
                label += f"  |  📝 {notes}"
            var = tk.BooleanVar(value=False)
            check_vars.append(var)
            row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            row.pack(fill=tk.X, pady=3)
            ctk.CTkCheckBox(row, text=label,
                            variable=var, font=("Segoe UI", 12)).pack(side=tk.LEFT, padx=5)

        def select_all():
            all_checked = all(v.get() for v in check_vars)
            for v in check_vars:
                v.set(not all_checked)
            select_all_btn.configure(text=self.tr("common.deselect_all") if not all_checked else self.tr("common.select_all"))

        select_all_btn = ctk.CTkButton(btn_row, text=self.tr("common.select_all"), width=140,
                                       fg_color="transparent", border_width=1,
                                       text_color=("gray10", "gray90"),
                                       command=select_all)
        select_all_btn.pack(side=tk.LEFT, padx=(0, 8))

        def on_add():
            selected = [parts[i] for i, v in enumerate(check_vars) if v.get()]
            if not selected:
                messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_select_one_part"), parent=dialog)
                return
            dialog.destroy()
            for part in selected:
                self._add_warehouse_part_to_list(part)

        ctk.CTkButton(btn_row, text=self.tr("common.add"), width=140,
                      fg_color="#1565c0", hover_color="#0d47a1",
                      command=on_add).pack(side=tk.RIGHT)

    def add_part_to_list(self):
        """Добавить запчасть в список"""
        part_name = " ".join(self.part_name_entry.get().split())
        if not part_name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_part_name"))
            return

        try:
            part_price = float(self.part_price_entry.get().replace(',', '.'))
            if part_price <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_valid_part_price"))
            return

        # Добавляем в список
        self.parts_list.append((part_name, part_price))

        # Обновляем таблицу
        self.parts_tree.insert("", tk.END, values=self.part_row_values(part_name, part_price))

        # Очищаем поля ввода
        self.part_name_entry.delete(0, tk.END)
        self.part_price_entry.delete(0, tk.END)
        self.restore_placeholder(self.part_price_entry)
        self.hide_part_keyword_listbox()
        self.part_name_entry.focus_set()

        # Обновляем общую стоимость
        self.update_total_cost()

    def remove_part_from_list(self, item_id):
        """Удалить запчасть из списка (✕ в строке)"""
        name, price = self.parts_list[self.parts_tree.index(item_id)]
        if not self.works_confirm_remove("part", name, price):
            return

        # Деталь со склада снова доступна для "Со склада"; на склад в базе вернётся при сохранении наряда
        if item_id in self.warehouse_part_ids:
            self.warehouse_part_ids.pop(item_id)
            self.check_warehouse_for_car(self.car_number_entry.get().strip())

        # Получаем индекс выбранного элемента
        item_index = self.parts_tree.index(item_id)

        # Удаляем из списка
        del self.parts_list[item_index]

        # Удаляем из таблицы
        self.parts_tree.delete(item_id)

        # Обновляем общую стоимость
        self.update_total_cost()

    def add_work_to_list(self):
        """Добавить работу в список"""
        work_name = " ".join(self.work_name_entry.get().split())
        if not work_name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_work_name"))
            return
        try:
            work_price = float(self.work_price_entry.get().replace(',', '.'))
            if work_price <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_valid_work_price"))
            return

        if any(" ".join(name.split()).lower() == work_name.lower() for name, _ in self.works_list):
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_work_duplicate", name=work_name))
            self.work_name_entry.focus_set()
            return

        self.works_list.append((work_name, work_price))
        self.works_tree.insert("", tk.END, values=(work_name, self.format_currency(work_price)))
        self.work_name_entry.delete(0, tk.END)
        self.work_price_entry.delete(0, tk.END)
        self.restore_placeholder(self.work_price_entry)
        self.hide_work_keyword_listbox()
        self.work_name_entry.focus_set()

    def works_confirm_remove(self, kind, name, price):
        """✕ в строке работы / запчасти - переспрашиваем, чтобы не удалить случайным кликом"""
        shown_name, price_text, _ = self.part_row_values(name, price)
        return messagebox.askyesno(
            self.tr("works.confirm_remove_title"),
            self.tr(f"works.confirm_remove_{kind}", name=shown_name, price=price_text))

    def remove_work_from_list(self, item_id):
        """Удалить работу из списка (✕ в строке)"""
        item_index = self.works_tree.index(item_id)
        name, price = self.works_list[item_index]
        if not self.works_confirm_remove("work", name, price):
            return
        del self.works_list[item_index]
        self.works_tree.delete(item_id)

    def on_work_name_keyrelease(self, event):
        text = self.work_name_entry.get().strip()
        if len(text) < 1:
            self.hide_work_keyword_listbox()
            return
        keywords = self.db.search_keywords(text)
        if keywords:
            self.show_work_keyword_listbox(keywords)
        else:
            self.hide_work_keyword_listbox()

    def show_work_keyword_listbox(self, keywords):
        self.work_keyword_listbox.delete(0, tk.END)
        for kw in keywords:
            self.work_keyword_listbox.insert(tk.END, kw)
        # Список - поверх формы, под полем
        self.place_popup(self.work_keyword_listbox, self.work_name_entry)
        self.work_keyword_listbox_visible = True

    def hide_work_keyword_listbox(self):
        if self.work_keyword_listbox_visible:
            self.hide_popup(self.work_keyword_listbox)
            self.work_keyword_listbox_visible = False

    def on_work_keyword_select(self, event):
        selection = self.work_keyword_listbox.curselection()
        if selection:
            keyword = self.work_keyword_listbox.get(selection[0])
            self.work_name_entry.delete(0, tk.END)
            self.work_name_entry.insert(0, keyword)
            self.hide_work_keyword_listbox()
            self.work_name_entry.focus_set()

    def on_work_name_focus_out(self, event):
        def check_and_hide():
            try:
                focused = self.root.focus_get()
                if focused != self.work_keyword_listbox:
                    self.hide_work_keyword_listbox()
            except:
                self.hide_work_keyword_listbox()
        self.root.after(200, check_and_hide)

    def on_part_name_keyrelease(self, event):
        text = self.part_name_entry.get().strip().lower()
        if len(text) < 1:
            self.hide_part_keyword_listbox()
            return
        matches = [p for p in self.spare_parts_list if text in p.lower()][:10]
        if matches:
            self.show_part_keyword_listbox(matches)
        else:
            self.hide_part_keyword_listbox()

    def show_part_keyword_listbox(self, parts):
        self.part_keyword_listbox.delete(0, tk.END)
        for p in parts:
            self.part_keyword_listbox.insert(tk.END, p)
        # Список - поверх формы, под полем
        self.place_popup(self.part_keyword_listbox, self.part_name_entry)
        self.part_keyword_listbox_visible = True

    def hide_part_keyword_listbox(self):
        if self.part_keyword_listbox_visible:
            self.hide_popup(self.part_keyword_listbox)
            self.part_keyword_listbox_visible = False

    def on_part_keyword_select(self, event):
        selection = self.part_keyword_listbox.curselection()
        if selection:
            part_name = self.part_keyword_listbox.get(selection[0])
            self.part_name_entry.delete(0, tk.END)
            self.part_name_entry.insert(0, part_name)
            self.hide_part_keyword_listbox()
            self.part_name_entry.focus_set()

    def on_part_name_focus_out(self, event):
        def check_and_hide():
            try:
                focused = self.root.focus_get()
                if focused != self.part_keyword_listbox:
                    self.hide_part_keyword_listbox()
            except:
                self.hide_part_keyword_listbox()
        self.root.after(200, check_and_hide)

    def update_total_cost(self):
        """Суммы под списками работ и запчастей и "Итого" внизу вкладки"""
        if not hasattr(self, "parts_sum_label"):
            return  # вкладка ещё строится
        works_sum = sum(price for _, price in getattr(self, "works_list", []))
        parts_sum = sum(price for _, price in getattr(self, "parts_list", []))
        self.works_sum_label.configure(text=self.tr("works.sum_works", amount=self.format_currency(works_sum)))
        self.parts_sum_label.configure(text=self.tr("works.sum_parts", amount=self.format_currency(parts_sum)))
        self.works_total_label.configure(text=self.tr("works.total", amount=self.format_currency(works_sum + parts_sum)))

    @staticmethod
    def works_same_person(phone_digits, name, other_phone, other_name):
        """Тот же ли человек: по телефону (последние 10 цифр), а если телефона нет - по имени"""
        other_digits = re.sub(r"\D", "", other_phone or "")[-10:]
        if phone_digits and other_digits:
            return phone_digits[-10:] == other_digits
        if not name or not other_name:
            return True   # сравнить не с чем - считаем, что тот же
        return " ".join(name.split()).lower() == " ".join(other_name.split()).lower()

    @staticmethod
    def works_name_changed(name, other_name):
        """Имя сменилось по сути (другое первое слово): "Равшан" -> "Роман". Дописали фамилию - не считается"""
        a, b = (name or "").split(), (other_name or "").split()
        return bool(a and b) and a[0].lower().replace("ё", "е") != b[0].lower().replace("ё", "е")

    def works_confirm_rename(self, phone_digits, client_name, old_name, old_phone, phone_entry, parent=None):
        """Телефон тот же, а имя другое - это переименование клиента или другой человек?
        True - продолжаем (имя клиента обновится), False - сохранение остановлено"""
        if not phone_digits or not self.works_same_person(phone_digits, "", old_phone, "") \
                or not self.works_name_changed(client_name, old_name):
            return True
        kwargs = {"parent": parent} if parent else {}
        answer = messagebox.askyesnocancel(
            self.tr("works.dialog_rename_title"),
            self.tr("works.dialog_rename_body", phone="+7" + phone_digits[-10:], old=old_name, new=client_name),
            **kwargs)
        if answer:
            return True
        if answer is False:
            # Другой человек - у него свой телефон: открываем поле телефона
            if phone_entry is getattr(self, "client_phone_entry", None) and "phone" in getattr(self, "works_locked", ()):
                self.works_unlock_field("phone", focus=True)
            else:
                phone_entry.focus_set()
        return False

    def works_resolve_owner(self, car_number, vin, client_name, phone_digits):
        """Перед сохранением: та ли машина и тот ли владелец. Возвращает решение для works_owner_ids
        или None - сохранение отменили.
        - Госномера в базе нет, а такой VIN есть у машины с другим госномером - спрашиваем, та ли это машина
          (перерегистрация: госномер у машины меняется, история остаётся с ней).
        - У машины другой владелец, чем в форме - спрашиваем, новый ли это владелец (машину продали):
          да - машина и вся история её работ переходят к нему; нет - у владельца обновятся имя / телефон."""
        owner = {"car": self.db.get_car_owner_by_number(car_number), "plate_from": None,
                 "client_id": None, "reassign": True, "lookup_by_car": True, "update_contact": False,
                 "new_owner": False}
        car = owner["car"]
        vin = (vin or "").strip().upper()
        if not car and len(vin) == VIN_LENGTH:
            same_vin = self.db.get_car_by_vin(vin, exclude_number=car_number)
            if same_vin and same_vin["client_id"] and not self.works_same_person(
                    phone_digits, client_name, same_vin["owner_phone"], same_vin["owner_name"]):
                # Тот же VIN, новый госномер и другой человек - обычно машину продали и перерегистрировали.
                # Спрашиваем сразу про всё в одном окне
                title = " ".join(x for x in (same_vin["car_brand"], same_vin["car_model"], same_vin["car_number"]) if x)
                old_name = same_vin["owner_name"] or self.tr("common.no_name")
                old_person = f"{old_name} ({same_vin['owner_phone']})" if same_vin["owner_phone"] else old_name
                new_name = client_name or self.tr("common.no_name")
                new_person = f"{new_name} (+7{phone_digits})" if phone_digits else new_name
                answer = messagebox.askyesnocancel(
                    self.tr("works.dialog_same_vin_title"),
                    self.tr("works.dialog_same_vin_owner_body", vin=vin, car=title, old=old_person,
                            number=car_number, new=new_person, new_name=new_name, old_name=old_name))
                if answer is None:
                    self.vin_entry.focus_set()
                    return None
                owner.update(car=same_vin, plate_from=same_vin["car_number"], lookup_by_car=False)
                if answer:
                    owner.update(new_owner=True)          # новый владелец: машина и история - к нему
                else:
                    owner.update(client_id=same_vin["client_id"], update_contact=True)   # тот же человек
                return owner
            if same_vin:
                title = " ".join(x for x in (same_vin["car_brand"], same_vin["car_model"], same_vin["car_number"]) if x)
                if not messagebox.askyesno(
                        self.tr("works.dialog_same_vin_title"),
                        self.tr("works.dialog_same_vin_body", vin=vin, car=title,
                                owner=same_vin["owner_name"] or self.tr("common.no_name"), number=car_number)):
                    self.vin_entry.focus_set()
                    return None
                owner["car"] = car = same_vin
                owner["plate_from"] = same_vin["car_number"]

        if not car or not car["client_id"]:
            return owner

        # Редактируем наряд и в форме - клиент этого наряда (машину могли уже продать) - владельца не трогаем
        editing = getattr(self, "editing_work_id", None)
        if editing:
            work = self.db.get_work_by_id(editing)
            if work and work[-1] and not self.works_confirm_rename(phone_digits, client_name, work[12] or "", work[13] or "",
                                                                   self.client_phone_entry):
                return None
            if work and work[-1] and self.works_same_person(phone_digits, client_name, work[13], work[12]):
                owner.update(client_id=work[-1], reassign=work[-1] == car["client_id"], lookup_by_car=False,
                             update_contact=True)
                return owner

        if not self.works_confirm_rename(phone_digits, client_name, car["owner_name"], car["owner_phone"],
                                         self.client_phone_entry):
            return None
        if self.works_same_person(phone_digits, client_name, car["owner_phone"], car["owner_name"]):
            return owner

        new_person = client_name or (("+7" + phone_digits) if phone_digits else self.tr("common.no_name"))
        if phone_digits and client_name:
            new_person = f"{client_name} (+7{phone_digits})"
        old_person = car["owner_name"] or self.tr("common.no_name")
        if car["owner_phone"]:
            old_person = f"{old_person} ({car['owner_phone']})"
        answer = messagebox.askyesnocancel(
            self.tr("works.dialog_new_owner_title"),
            self.tr("works.dialog_new_owner_body", number=car["car_number"] or car_number, old=old_person,
                    new=new_person, old_name=car["owner_name"] or self.tr("common.no_name")))
        if answer is None:
            return None
        if answer:
            # Новый владелец: клиента ищем / создаём по его телефону, не по госномеру (там прежний владелец).
            # Вся история машины переходит к нему (works_owner_ids)
            owner.update(lookup_by_car=False, new_owner=True)
        else:
            # Тот же человек - обновим ему имя / телефон
            owner.update(client_id=car["client_id"], lookup_by_car=False, update_contact=True)
        return owner

    def works_owner_ids(self, owner, telegram_user_id, client_name, client_phone, car_brand, car_model, car_number):
        """Клиент и машина для сохранения по решению works_resolve_owner. Считается один раз (кэш в owner)"""
        if "ids" in owner:
            return owner["ids"]
        car = owner["car"]
        if owner["plate_from"] and car:
            # Та же машина (по VIN) с новым госномером
            self.db.update_car_number(car["id"], car_number)
        client_id = owner["client_id"]
        if not client_id:
            client_id = self.db.get_or_create_client(
                telegram_user_id=telegram_user_id,
                full_name=client_name,
                phone=client_phone,
                car_number=car_number if owner["lookup_by_car"] else None
            )
        elif owner["update_contact"]:
            self.db.update_client_contact(client_id, client_name, client_phone)
        if owner["reassign"]:
            car_id = self.db.get_or_create_car(client_id, car_brand, car_model, car_number, update_info=True) if client_id else None
        else:
            # Машина уже у другого владельца - наряд прежнего клиента её не забирает
            car_id = self.db.get_or_create_car(None, car_brand, car_model, car_number, update_info=True)
        if owner["new_owner"] and client_id and car_id:
            # Машину продали: все прошлые наряды и записи этой машины - теперь у нового владельца
            self.db.transfer_car_history(car_id, client_id)
        owner["ids"] = (client_id, car_id)
        return owner["ids"]

    def _link_warehouse_parts_to_work(self, work_id):
        """Наряд сохранили - отметить склад: детали из списка - "установлена" и привязаны к наряду,
        детали этого наряда, которые из списка убрали, - обратно "на складе" """
        in_form = set(self.warehouse_part_ids.values())
        for part_id in in_form:
            self.db.update_warehouse_part_status(part_id, "установлена")
            self.db.link_warehouse_part_to_work(part_id, work_id)
        for part_id in getattr(self, "works_linked_wh_parts", {}):
            if part_id not in in_form:
                self.db.update_warehouse_part_status(part_id, "на складе")
                self.db.unlink_warehouse_part_from_work(part_id)
        if in_form or getattr(self, "works_linked_wh_parts", None):
            self.refresh_warehouse()

    def add_work(self):
        """Добавить или обновить запись о работе"""
        selected_worker = self.worker_combo.get()
        if not selected_worker or selected_worker == self.tr("works.select_master"):
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_select_master"))
            return

        if not self.works_list:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_add_one_work"))
            return

        description = "\n".join(name for name, _ in self.works_list)
        amount = sum(price for _, price in self.works_list)
        # Сохраняем точные цены по каждой позиции отдельно, чтобы не терять их при редактировании
        items_json = json.dumps(
            [{"name": name, "price": price} for name, price in self.works_list],
            ensure_ascii=False
        )

        worker_id = self.workers_data[selected_worker]

        # Мастер по расписанию отсутствует в день работы - переспрашиваем (бывает, что выходит в свой выходной)
        check_date = date.today()
        if getattr(self, 'editing_work_id', None):
            original_work = self.db.get_work_by_id(self.editing_work_id)
            if original_work and original_work[5]:
                work_day = original_work[5]
                if isinstance(work_day, datetime):
                    work_day = work_day.date()
                elif not isinstance(work_day, date):
                    work_day = datetime.strptime(str(work_day)[:10], '%Y-%m-%d').date()
                check_date = work_day
        absence_kind = self.db.get_worker_schedule(check_date, check_date).get(worker_id, {}).get(check_date)
        if absence_kind and not messagebox.askyesno(
                self.tr("common.attention"),
                self.tr("works.msg_worker_absent",
                        name=getattr(self, "worker_names_by_id", {}).get(worker_id, selected_worker),
                        date=check_date.strftime('%d.%m.%Y'), kind=self.staff_kind_label(absence_kind))):
            return
        car_brand = self.car_brand_entry.get().strip()
        car_model = self.car_model_entry.get().strip()
        car_number = self.car_number_entry.get().strip().upper()
        mileage = self.mileage_entry.get().strip()
        vin = self.vin_entry.get().strip().upper()

        # Валидация обязательных полей авто
        if not car_brand:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_brand"))
            return
        if not car_model:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_model"))
            return
        if not car_number:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_car_number"))
            return

        # VIN короче стандартных 17 символов - предупреждаем
        if vin and len(vin) < VIN_LENGTH:
            if not messagebox.askyesno(self.tr("common.attention"),
                                       self.tr("works.vin_too_short", count=len(vin), required=VIN_LENGTH)):
                self.vin_entry.focus_set()
                return

        # Если у машины уже записан другой VIN - спрашиваем, перезаписывать ли
        if vin:
            existing_car = self.db.get_car_by_number(car_number)
            old_vin = (existing_car or {}).get("vin", "").strip().upper()
            if old_vin and old_vin != vin:
                choice = self.ask_vin_overwrite(old_vin, vin)
                if choice is None:
                    return
                if choice == "keep":
                    vin = old_vin

        # Данные клиента
        booking_id = getattr(self, 'selected_booking_id', None)
        client_name = self.client_name_entry.get().strip()
        # Телефон из маски -> +7XXXXXXXXXX; неполный номер не сохраняем
        phone_digits = phone_mask_digits(self.client_phone_entry.get())
        if phone_digits and len(phone_digits) != 10:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_enter_phone_after_plus7"))
            self.client_phone_entry.focus_set()
            return
        client_phone = "+7" + phone_digits if phone_digits else ""

        # Получаем telegram_user_id из записи если есть
        telegram_user_id = None
        if booking_id:
            booking = self.db.get_booking_by_id(booking_id)
            if booking:
                telegram_user_id = booking.get("user_id")

        # Если нет booking_id, но есть телефон - ищем user_id по телефону
        if not telegram_user_id and client_phone:
            telegram_user_id = self.db.get_telegram_user_id_by_phone(client_phone)

        # Та ли это машина и тот ли владелец: машину могли продать (другой человек на том же госномере)
        # или перерегистрировать (тот же VIN, новый госномер) - спрашиваем, пока ничего не записано
        owner = self.works_resolve_owner(car_number, vin, client_name, phone_digits)
        if owner is None:
            return

        def client_and_car(tg_user_id=telegram_user_id):
            return self.works_owner_ids(owner, tg_user_id, client_name, client_phone, car_brand, car_model, car_number)

        # Проверяем, редактируем ли существующую запись
        if hasattr(self, 'editing_work_id') and self.editing_work_id:
            # Получаем оригинальную дату записи
            original_work = self.db.get_work_by_id(self.editing_work_id)
            if original_work:
                work_date = original_work[5]  # work_date из оригинальной записи
                if hasattr(work_date, 'strftime'):
                    work_date = work_date.strftime('%Y-%m-%d')
            else:
                work_date = datetime.now().strftime('%Y-%m-%d')

            # Создаём/находим клиента и машину
            client_id, car_id = client_and_car()

            # Обновляем запись
            self.db.update_work(self.editing_work_id, worker_id, description, amount, work_date, mileage, vin, booking_id, car_id, items_json,
                                client_id=client_id)

            # Удаляем старые запчасти и добавляем новые
            self.db.delete_parts_by_work_id(self.editing_work_id)
            if self.parts_list:
                self.db.add_parts(self.editing_work_id, self.parts_list)

            self._link_warehouse_parts_to_work(self.editing_work_id)

            messagebox.showinfo(self.tr("common.success"), self.tr("works.msg_record_updated"))

            # Сбрасываем режим редактирования
            self.editing_work_id = None
        else:
            # Автоматически используем текущую дату для новой записи
            work_date = datetime.now().strftime('%Y-%m-%d')
            now = datetime.now()

            # Если есть booking_id - проверяем, есть ли уже работы у этой записи
            if booking_id:
                existing_work = self.db.get_last_work_by_booking_id(booking_id)
                if existing_work:
                    # У записи уже есть работа - всегда объединяем в один наряд, без вопроса.
                    # Сменился владелец / контакты / госномер (ответы на вопросы выше) - применяем и здесь
                    if owner["new_owner"] or owner["update_contact"] or owner["plate_from"]:
                        client_and_car()
                    self.db.append_to_work(existing_work["work_id"], description, amount, items_json)

                    # Добавляем запчасти к существующей работе
                    if self.parts_list:
                        self.db.add_parts(existing_work["work_id"], self.parts_list)

                    self._link_warehouse_parts_to_work(existing_work["work_id"])

                    messagebox.showinfo(self.tr("common.success"), self.tr("works.msg_work_merged"))

                    # Очищаем форму и выходим
                    self.clear_work_form(restore_warehouse=False)
                    return

            # Если нет booking_id - проверяем, есть ли уже активная работа для этой машины
            elif not booking_id:
                active_work = self.db.get_active_work_by_car_number(car_number)
                if active_work:
                    # Машина уже в работе - спрашиваем пользователя
                    booking_date = active_work["booking_date"]
                    if hasattr(booking_date, 'strftime'):
                        date_str = booking_date.strftime('%d.%m.%Y')
                    else:
                        date_str = str(booking_date)

                    desc_preview = active_work['description'][:100] + "..." if len(active_work['description']) > 100 else active_work['description']
                    msg = self.tr(
                        "works.dialog_car_busy_body",
                        car_number=car_number,
                        client_name=active_work['client_name'],
                        client_phone=active_work['client_phone'],
                        date=date_str,
                        time=active_work['booking_time'],
                        preview=desc_preview,
                    )

                    if messagebox.askyesno(self.tr("works.dialog_car_busy_title"), msg):
                        # Объединяем с существующей работой (смену владельца / контактов - применяем)
                        existing_work_id = active_work["work_id"]
                        if owner["new_owner"] or owner["update_contact"] or owner["plate_from"]:
                            client_and_car()
                        self.db.append_to_work(existing_work_id, description, amount, items_json)

                        # Добавляем запчасти к существующей работе
                        if self.parts_list:
                            self.db.add_parts(existing_work_id, self.parts_list)

                        self._link_warehouse_parts_to_work(existing_work_id)

                        messagebox.showinfo(self.tr("common.success"), self.tr("works.msg_work_merged_booking"))

                        # Очищаем форму и выходим
                        self.clear_work_form(restore_warehouse=False)
                        return
                    else:
                        # Пользователь отказался - отменяем добавление
                        return

                else:
                    # Машина не в работе - создаём новую запись
                    current_hour = now.hour
                    TIME_SLOTS = booking_time_slots()
                    booking_time = None

                    # Ищем ближайший слот к текущему времени
                    for slot in TIME_SLOTS:
                        slot_hour = int(slot.split(":")[0])
                        if slot_hour >= current_hour:
                            booking_time = slot
                            break

                    # Если не нашли подходящий слот сегодня - берём первый
                    if not booking_time:
                        booking_time = TIME_SLOTS[0]

                    # Ищем telegram данные по телефону
                    tg_user_id = telegram_user_id or 0
                    tg_username = ""
                    if client_phone:
                        tg_data = self.db.get_telegram_user_by_phone(client_phone)
                        if tg_data:
                            tg_user_id = tg_data["user_id"] or tg_user_id
                            tg_username = tg_data["username"] or ""

                    # Создаём/находим клиента и машину для booking
                    new_client_id, new_car_id = client_and_car(tg_user_id if tg_user_id else None)

                    # Создаём запись со статусом "В работе"
                    booking_id = self.db.add_booking(
                        booking_date=now.date(),
                        booking_time=booking_time,
                        client_id=new_client_id,
                        car_id=new_car_id,
                        status="in_progress"
                    )

            # Создаём/находим клиента и машину для работы
            client_id, car_id = client_and_car()

            # Добавляем работу и получаем ID
            work_id = self.db.add_work(worker_id, description, amount, work_date, mileage, vin, booking_id, car_id, items_json,
                                       client_id=client_id)

            # Если есть запчасти - сохраняем их
            if self.parts_list:
                self.db.add_parts(work_id, self.parts_list)

            self._link_warehouse_parts_to_work(work_id)

            # Меняем статус записи на "В работе"
            if booking_id:
                self.db.update_booking_status(booking_id, "in_progress")

            messagebox.showinfo(self.tr("common.success"), self.tr("works.msg_record_added"))

        # Очищаем форму (детали со склада остаются как "установлена")
        self.clear_work_form(restore_warehouse=False)

    def clear_work_form(self, restore_warehouse=True):
        """Очистить форму добавления работы"""
        self.editing_work_id = None
        self.works_phone_fill = None
        self.works_number_fill = None
        self._works_looked_up_number = None
        self.works_clear_marks()
        self.works_unlock_all()
        self.works_record_number = None
        self.works_set_lookup_state(None)
        self.works_editing_title = ""
        self.works_edit_snapshot = None
        self.works_update_edit_banner()
        self.worker_combo.set(self.tr("works.select_master"))
        self.works_list = []
        for item in self.works_tree.get_children():
            self.works_tree.delete(item)
        self.car_brand_entry.delete(0, tk.END)
        self.car_model_entry.delete(0, tk.END)
        self.car_number_entry.delete(0, tk.END)
        self.mileage_entry.delete(0, tk.END)
        self.vin_entry.delete(0, tk.END)
        self.client_name_entry.delete(0, tk.END)
        self.set_phone_value(self.client_phone_entry, "")
        self.booking_combo.set("")
        self.selected_booking_id = None
        self.client_cars_combo.configure(values=[self.tr("works.new_car")])
        self.client_cars_combo.set("")
        self.client_cars_data = {}

        # Склад до сохранения наряда не меняется - возвращать на склад нечего
        # (restore_warehouse оставлен для совместимости вызовов)
        self.warehouse_part_ids = {}
        self.works_linked_wh_parts = {}
        self.current_car_warehouse_parts = []
        self.warehouse_notice_label.configure(text="")
        self.add_from_warehouse_btn.pack_forget()

        # Очищаем список запчастей
        self.parts_list = []
        for item in self.parts_tree.get_children():
            self.parts_tree.delete(item)

        # Обновляем общую стоимость
        self.update_total_cost()

    # ===== ВКЛАДКА СКЛАДА =====

    def setup_warehouse_tab(self):
        """Настройка вкладки склада запчастей"""
        # Верхняя панель с кнопками
        top_frame = ctk.CTkFrame(self.warehouse_frame)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        # Заголовок
        ctk.CTkLabel(top_frame, text=self.tr("warehouse.title"), font=ctk.CTkFont(size=20, weight="bold")).pack(side=tk.LEFT, padx=10)

        # Кнопка заказать запчасть
        ctk.CTkButton(top_frame, text=self.tr("warehouse.order_part"), command=self.show_add_part_form,
                     fg_color="#1565c0", hover_color="#0d47a1", width=160).pack(side=tk.RIGHT, padx=10)

        # Кнопка обновить
        ctk.CTkButton(top_frame, text=self.tr("works.refresh"), command=self.refresh_warehouse,
                     width=100).pack(side=tk.RIGHT, padx=5)

        # Кнопка выбора колонок
        self.warehouse_columns_btn = ctk.CTkButton(top_frame, text="☰ " + self.tr("bookings.columns_btn"),
                                                   command=lambda: self.show_columns_menu_under("warehouse_hidden_columns", self.warehouse_columns_btn),
                                                   width=110)
        self.warehouse_columns_btn.pack(side=tk.RIGHT, padx=5)

        # Фильтр по статусу
        filter_frame = ctk.CTkFrame(self.warehouse_frame)
        filter_frame.pack(fill=tk.X, padx=10, pady=5)

        ctk.CTkLabel(filter_frame, text=self.tr("bookings.status_label")).pack(side=tk.LEFT, padx=5)
        self.warehouse_status_var = tk.StringVar(value=self.tr("bookings.filter_all"))
        status_combo = ctk.CTkComboBox(filter_frame, variable=self.warehouse_status_var,
                                        values=[self.tr("bookings.filter_all"), self.tr("warehouse.status_in_transit"),
                                                self.tr("warehouse.status_in_stock"), self.tr("warehouse.status_issued")],
                                        width=140, command=lambda x: self.refresh_warehouse())
        status_combo.pack(side=tk.LEFT, padx=5)

        # Поиск по госномеру
        ctk.CTkLabel(filter_frame, text=self.tr("works.car_number")).pack(side=tk.LEFT, padx=(20, 5))
        self.warehouse_search_entry = ctk.CTkEntry(filter_frame, width=150, placeholder_text=self.tr("warehouse.search_placeholder"))
        self.warehouse_search_entry.pack(side=tk.LEFT, padx=5)
        self.warehouse_search_entry.bind("<Return>", lambda e: self.refresh_warehouse())
        ctk.CTkButton(filter_frame, text="✕", command=self.clear_warehouse_search,
                     width=30, fg_color="#c62828", hover_color="#b71c1c").pack(side=tk.LEFT, padx=2)

        # Таблица запчастей
        table_frame = ctk.CTkFrame(self.warehouse_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("id", "car_info", "client", "part_name", "quantity", "price", "paid", "status", "order_date", "received_date", "notes")
        self.warehouse_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        self.warehouse_tree.heading("id", text="ID")
        self.warehouse_tree.heading("car_info", text=self.tr("bookings.col_car"))
        self.warehouse_tree.heading("client", text=self.tr("bookings.info_label_client"))
        self.warehouse_tree.heading("part_name", text=self.tr("warehouse.col_part_name"))
        self.warehouse_tree.heading("quantity", text=self.tr("warehouse.col_quantity"))
        self.warehouse_tree.heading("price", text=self.tr("works.col_price"))
        self.warehouse_tree.heading("paid", text=self.tr("warehouse.col_paid"))
        self.warehouse_tree.heading("status", text=self.tr("bookings.col_status"))
        self.warehouse_tree.heading("order_date", text=self.tr("warehouse.col_order_date"))
        self.warehouse_tree.heading("received_date", text=self.tr("warehouse.col_received_date"))
        self.warehouse_tree.heading("notes", text=self.tr("warehouse.col_notes"))

        self.warehouse_tree.column("id", width=0, stretch=False, minwidth=0)
        self.warehouse_tree.column("car_info", width=180)
        self.warehouse_tree.column("client", width=130)
        self.warehouse_tree.column("part_name", width=200)
        self.warehouse_tree.column("quantity", width=50)
        self.warehouse_tree.column("price", width=90)
        self.warehouse_tree.column("paid", width=80)
        self.warehouse_tree.column("status", width=90)
        self.warehouse_tree.column("order_date", width=90)
        self.warehouse_tree.column("received_date", width=90)
        self.warehouse_tree.column("notes", width=120)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.warehouse_tree.yview)
        self.warehouse_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.warehouse_tree.pack(fill=tk.BOTH, expand=True)

        # Видимость колонок (сохраняется в settings.json); id скрыт всегда
        self.setup_toggleable_columns(self.warehouse_tree, "warehouse_hidden_columns", columns[1:])

        # Настройка цветов для статусов
        self.warehouse_tree.tag_configure("в пути", background="#e3f2fd", foreground="#1565c0")
        self.warehouse_tree.tag_configure("на складе", background="#e8f5e9", foreground="#2e7d32")
        self.warehouse_tree.tag_configure("выдано", background="#f3e5f5", foreground="#7b1fa2")

        # Добавляем tooltip для запчастей
        TreeviewTooltip(self.warehouse_tree, columns=["part_name", "notes"])

        # Контекстное меню для редактирования
        self.warehouse_context_menu = tk.Menu(
            self.warehouse_tree, tearoff=0,
            bg="#1e1e1e", fg="white", bd=0,
            activebackground="#2d2d2d", activeforeground="white",
            font=("Segoe UI", 11)
        )
        self.warehouse_context_menu.add_command(
            label="  ✏  " + self.tr("bookings.ctx_edit"), command=self.edit_warehouse_part,
            foreground="#64b5f6", activeforeground="#90caf9",
            background="#1e1e1e", activebackground="#1976d2"
        )
        self.warehouse_context_menu.add_separator()
        self.warehouse_context_menu.add_command(
            label="  📦  " + self.tr("warehouse.status_in_stock"), command=lambda: self.update_part_status("на складе"),
            foreground="#81c784", activeforeground="#a5d6a7",
            background="#1e1e1e", activebackground="#2e7d32"
        )
        self.warehouse_context_menu.add_command(
            label="  ✅  " + self.tr("warehouse.status_issued"), command=lambda: self.update_part_status("выдано"),
            foreground="#ffb74d", activeforeground="#ffcc80",
            background="#1e1e1e", activebackground="#e65100"
        )
        self.warehouse_context_menu.add_separator()
        self.warehouse_context_menu.add_command(
            label="  💰  " + self.tr("warehouse.ctx_mark_paid"), command=lambda: self.set_warehouse_part_paid(True),
            foreground="#81c784", activeforeground="#a5d6a7",
            background="#1e1e1e", activebackground="#2e7d32"
        )
        self.warehouse_context_menu.add_command(
            label="  🚫  " + self.tr("warehouse.ctx_mark_unpaid"), command=lambda: self.set_warehouse_part_paid(False),
            foreground="#e0e0e0", activeforeground="#ffffff",
            background="#1e1e1e", activebackground="#616161"
        )
        self.warehouse_context_menu.add_separator()
        self.warehouse_context_menu.add_command(
            label="  🔗  " + self.tr("warehouse.ctx_goto_booking"), command=self.goto_booking_from_warehouse,
            foreground="#64b5f6", activeforeground="#90caf9",
            background="#1e1e1e", activebackground="#1976d2"
        )
        self.warehouse_context_menu.add_separator()
        self.warehouse_context_menu.add_command(
            label="  🗑  " + self.tr("bookings.ctx_delete"), command=self.delete_warehouse_part,
            foreground="#ef5350", activeforeground="#ef9a9a",
            background="#1e1e1e", activebackground="#c62828"
        )

        def show_warehouse_context_menu(event):
            # ПКМ по заголовку - меню колонок
            if self.warehouse_tree.identify_region(event.x, event.y) == "heading":
                self.show_columns_menu("warehouse_hidden_columns", event.x_root, event.y_root)
                return
            # Выбираем строку под курсором
            item = self.warehouse_tree.identify_row(event.y)
            if item:
                self.warehouse_tree.selection_set(item)
                self.warehouse_context_menu.tk_popup(event.x_root, event.y_root)

        self.warehouse_tree.bind("<Button-3>", show_warehouse_context_menu)

        # Форма добавления запчасти (скрыта по умолчанию)
        self.add_part_form_frame = ctk.CTkFrame(self.warehouse_frame)
        self.add_part_form_visible = False

    def show_add_part_form(self):
        """Показать форму добавления запчасти"""
        # Окно уже открыто - просто поднимаем его. Раньше кнопка работала как переключатель,
        # и после закрытия окна крестиком (флаг не сбрасывался) открывалась только со второго нажатия
        if self.add_part_form_visible and self.add_part_form_frame.winfo_exists():
            self.add_part_form_frame.lift()
            self.add_part_form_frame.focus_force()
            return

        # Окно строится один раз (заранее, вскоре после запуска) - дальше только сброс формы и показ
        window = self._ensure_part_window()
        self.reset_add_part_form()
        self.show_dim_overlay(self.wh_part_overlay)
        delay = 40 if self._part_window_fresh else 1   # сразу после построения CustomTkinter ещё перекрашивает заголовок
        self._part_window_fresh = False
        self.add_part_form_visible = True
        self.show_form_window_when_ready(window, self.wh_car_number_entry, delay=delay)

    def _ensure_part_window(self):
        """Готовое окно "Добавить запчасть": построить, если ещё нет"""
        window = getattr(self, "_part_window", None)
        try:
            if window is not None and window.winfo_exists():
                return window
        except tk.TclError:
            pass
        self._part_window = self._build_add_part_window()
        return self._part_window

    def _prebuild_part_window(self):
        """Построить окно "Добавить запчасть" заранее, пока программа простаивает"""
        try:
            self._ensure_part_window()
        except Exception as e:
            print(f"Окно склада заранее не построено (построится при первом открытии): {e}")

    def reset_add_part_form(self):
        """Каждое открытие - чистая форма: поля, найденная машина, форма новой машины, телефон, галочка, ошибки"""
        for entry in (self.wh_car_number_entry, self.wh_new_brand_entry, self.wh_new_model_entry,
                      self.wh_new_client_name_entry, self.wh_part_name_entry, self.wh_quantity_entry,
                      self.wh_price_entry, self.wh_notes_entry):
            entry.delete(0, tk.END)
            entry.configure(border_color=self.wh_normal_border)
        self.set_phone_value(self.wh_phone_entry, "")
        self.wh_phone_entry.configure(border_color=self.wh_normal_border, fg_color=self.wh_entry_bg)
        self.hide_popup(self.wh_part_listbox)
        self.wh_quantity_entry.insert(0, "1")
        self.restore_placeholder(self.wh_car_number_entry)
        self.wh_paid_var.set(False)
        self.wh_selected_car_id = None
        self.wh_phone_fill = None
        self.wh_plate_phone = None
        self.wh_searched_number = None
        self.wh_phone_cars_numbers = {}
        self.hide_wh_brand_listbox()
        self.hide_wh_model_listbox()
        if self.wh_phone_cars_combo.winfo_manager():
            self.wh_phone_cars_combo.pack_forget()
        self.hide_new_car_form()
        self.set_wh_car_status("")
        self.fit_form_window(self.add_part_form_frame)

    def _build_add_part_window(self):
        """Построить окно "Добавить запчасть" (скрытым)"""
        self.wh_part_overlay = self.make_dim_overlay()
        window = self.add_part_form_frame = ctk.CTkToplevel(self.root)
        window.withdraw()  # строим скрытым - показывает show_add_part_form
        self._part_window_fresh = True
        window.after(300, lambda: setattr(self, "_part_window_fresh", False))
        window.title(self.tr("warehouse.order_part"))
        window.transient(self.root)
        window.dim_overlay = self.wh_part_overlay   # форма принадлежит затемнению - всегда над ним, но не над другими программами
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.hide_add_part_form)
        content = self.wh_form_content = self.form_content(window, width=560)

        # === КЛИЕНТ И АВТОМОБИЛЬ: госномер и телефон в одну строку (как во вкладке "Добавить работу") ===
        self.wh_car_card, car_body = self.form_section(content, self.tr("works.section_client_car"))
        row = ctk.CTkFrame(car_body, fg_color="transparent")
        row.pack(fill=tk.X)
        self.wh_car_number_entry = self.works_cell(row, 0, self.tr("works.car_number"),
                                                   self.form_entry(row, width=160, placeholder_text="А123БВ777"), 160)
        self.wh_phone_entry = self.works_cell(row, 1, self.tr("bookings.add_window_phone"), self.form_entry(row, width=200))
        # Машина ищется сама по мере ввода (как в "Записать клиента"), кнопка "Найти" не нужна
        self.wh_car_number_entry.bind('<KeyRelease>', lambda e: self.search_car_for_warehouse())
        self.wh_car_number_entry.bind('<FocusOut>', lambda e: self.search_car_for_warehouse())
        # Enter в госномере - поиск машины, а не "Заказать"
        self.wh_car_number_entry.bind('<Return>', lambda e: (self.search_car_for_warehouse(), "break")[1])
        self.attach_phone_mask(self.wh_phone_entry)
        self.wh_phone_entry.bind("<KeyRelease>", self.on_wh_phone_keyrelease)
        self.wh_entry_bg = self.wh_phone_entry.cget("fg_color")

        # Информация о найденной машине (строка показывается, только когда есть что сказать)
        status_holder = tk.Frame(car_body, bg="white")
        status_holder.pack(fill=tk.X)
        self.wh_car_info_label = ctk.CTkLabel(status_holder, text="", font=("Arial", 13, "bold"), anchor="w",
                                              justify=tk.LEFT, wraplength=520)
        self.wh_selected_car_id = None  # Сохраняем car_id

        # Машины клиента, найденного по телефону (если их несколько)
        cars_holder = tk.Frame(car_body, bg="white")
        cars_holder.pack(fill=tk.X)
        self.wh_phone_cars_combo = ctk.CTkComboBox(cars_holder, height=34, font=("Arial", 13), values=[],
                                                   state="readonly", corner_radius=8,
                                                   command=self.on_wh_phone_car_select)
        self.wh_phone_cars_numbers = {}
        self.wh_phone_fill = None  # что подставил поиск по телефону

        # Новая машина (скрыто по умолчанию): марка | модель | имя клиента - в одну строку
        new_car_holder = tk.Frame(car_body, bg="white")
        new_car_holder.pack(fill=tk.X)
        self.wh_new_car_frame = ctk.CTkFrame(new_car_holder, fg_color="transparent")
        self.wh_new_car_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="car")
        self.wh_new_car_visible = False
        frame = self.wh_new_car_frame
        self.form_label(frame, self.tr("bookings.add_window_brand"), required=True).grid(row=0, column=0, sticky="w")
        self.form_label(frame, self.tr("bookings.add_window_model")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.form_label(frame, self.tr("works.client_name")).grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.wh_new_brand_entry = self.form_entry(frame)
        self.wh_new_brand_entry.grid(row=1, column=0, sticky="ew")
        self.wh_new_brand_entry.bind('<KeyRelease>', self.on_wh_brand_keyrelease)
        self.wh_new_brand_entry.bind('<FocusOut>', self.on_wh_brand_focus_out)
        self.wh_new_model_entry = self.form_entry(frame)
        self.wh_new_model_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        self.wh_new_model_entry.bind('<KeyRelease>', self.on_wh_model_keyrelease)
        self.wh_new_model_entry.bind('<FocusOut>', self.on_wh_model_focus_out)
        self.wh_new_client_name_entry = self.form_entry(frame)
        self.wh_new_client_name_entry.grid(row=1, column=2, sticky="ew", padx=(10, 0))
        # Подсказка имён - список под полем
        self.attach_name_autocomplete(self.wh_new_client_name_entry, content, position="below")

        # Списки подсказок марки и модели - поверх формы под полями
        self.wh_brand_listbox = self.form_popup_listbox(content, takefocus=False)
        self.wh_brand_listbox_visible = False
        self.wh_brand_listbox.bind('<<ListboxSelect>>', self.on_wh_brand_select)
        self.wh_model_listbox = self.form_popup_listbox(content, takefocus=False)
        self.wh_model_listbox_visible = False
        self.wh_model_listbox.bind('<<ListboxSelect>>', self.on_wh_model_select)

        # === ЗАПЧАСТЬ: название | кол-во | цена - в одну строку ===
        _, part_body = self.form_section(content, self.tr("warehouse.part_label"))
        row = ctk.CTkFrame(part_body, fg_color="transparent")
        row.pack(fill=tk.X)
        self.wh_part_name_entry = self.works_cell(row, 0, self.tr("warehouse.part_name_label"), self.form_entry(row),
                                                  required=True)
        self.wh_quantity_entry = self.works_cell(row, 1, self.tr("warehouse.quantity_short"),
                                                 self.form_entry(row, width=60), 60)
        self.wh_quantity_entry.insert(0, "1")
        self.wh_price_entry = self.works_cell(row, 2, self.tr("works.price_label"), self.form_entry(row, width=100), 100)

        # Подсказки названий запчастей (из списка запчастей) - под полем, с прокруткой
        self.wh_part_listbox = self.form_popup_listbox(content)
        self.wh_part_listbox.bind("<ButtonRelease-1>", self.on_wh_part_select)
        self.wh_part_listbox.bind("<Return>", self.on_wh_part_select)
        self.wh_part_name_entry.bind("<KeyRelease>", self.on_wh_part_name_keyrelease)
        self.wh_part_name_entry.bind("<Down>", self.on_wh_part_name_down)
        self.wh_part_name_entry.bind("<FocusOut>", lambda e: self.root.after(200, self._wh_part_list_focus_check))

        # Уже оплачено (например, хранение шин - клиент заплатил при сдаче, и при выдаче со склада
        # эта сумма не должна повторно попасть в счёт). Коротко в строку, подробно - подсказкой при наведении
        paid_row = ctk.CTkFrame(part_body, fg_color="transparent")
        paid_row.pack(fill=tk.X, pady=(8, 0))
        self.wh_paid_var = tk.BooleanVar(value=False)
        paid_box = ctk.CTkCheckBox(paid_row, text="", width=24, variable=self.wh_paid_var)
        paid_box.pack(side=tk.LEFT)
        paid_label = ctk.CTkLabel(paid_row, text=self.tr("warehouse.paid_short"), font=("Arial", 12),
                                  anchor="w", cursor="hand2")
        paid_label.pack(side=tk.LEFT, padx=(4, 0))
        paid_label.bind("<Button-1>", lambda e: self.wh_paid_var.set(not self.wh_paid_var.get()))
        for widget in (paid_box, paid_label):
            self.attach_hover_tip(widget, self.tr("warehouse.paid_checkbox_label"))

        self.form_label(part_body, self.tr("warehouse.notes_label")).pack(fill=tk.X, pady=(8, 0))
        self.wh_notes_entry = self.form_entry(part_body)
        self.wh_notes_entry.pack(fill=tk.X)

        # Кнопки: широкая "Заказать" и "Отмена"; Enter - заказать, Esc - отмена
        self.form_buttons(window, self.tr("warehouse.order_btn"), self.add_warehouse_part, self.hide_add_part_form)
        self.form_bind_keys(window, content, self.add_warehouse_part, self.hide_add_part_form,
                            lambda: (self.hide_wh_brand_listbox(), self.hide_wh_model_listbox(),
                                     self.hide_popup(self.wh_part_listbox)))
        self.form_clear_error_on_type((self.wh_car_number_entry, self.wh_new_brand_entry, self.wh_phone_entry,
                                       self.wh_part_name_entry, self.wh_quantity_entry, self.wh_price_entry))

        self.wh_normal_border = self.wh_car_number_entry.cget("border_color")
        window.update_idletasks()
        return window

    def on_wh_part_name_keyrelease(self, event=None):
        """Подсказки названий запчастей: из списка запчастей (как во вкладке "Добавить работу")"""
        if event is not None and event.keysym in ("Down", "Up", "Return", "Escape", "Tab"):
            return
        text = self.wh_part_name_entry.get().strip().lower()
        parts = getattr(self, "spare_parts_list", []) or []
        matches = [p for p in parts if text in p.lower()][:50] if text else []
        # Название уже введено полностью - список не нужен
        if not matches or (len(matches) == 1 and matches[0].lower() == text):
            self.hide_popup(self.wh_part_listbox)
            return
        self.wh_part_listbox.delete(0, tk.END)
        for name in matches:
            self.wh_part_listbox.insert(tk.END, name)
        self.place_popup(self.wh_part_listbox, self.wh_part_name_entry)

    def on_wh_part_name_down(self, event=None):
        """Стрелка вниз - перейти в список подсказок"""
        if self.wh_part_listbox.popup_frame.winfo_ismapped():
            self.wh_part_listbox.focus_set()
            self.wh_part_listbox.selection_clear(0, tk.END)
            self.wh_part_listbox.selection_set(0)
            self.wh_part_listbox.activate(0)
            return "break"

    def on_wh_part_select(self, event=None):
        selection = self.wh_part_listbox.curselection()
        if selection:
            self.wh_part_name_entry.delete(0, tk.END)
            self.wh_part_name_entry.insert(0, self.wh_part_listbox.get(selection[0]))
        self.hide_popup(self.wh_part_listbox)
        self.wh_quantity_entry.focus_set()
        return "break"

    def _wh_part_list_focus_check(self):
        try:
            if self.root.focus_get() is not self.wh_part_listbox:
                self.hide_popup(self.wh_part_listbox)
        except (KeyError, tk.TclError):
            self.hide_popup(self.wh_part_listbox)

    def attach_hover_tip(self, widget, text):
        """Подсказка при наведении мыши (жёлтая, как у таблиц)"""
        tip = [None]

        def show(event):
            hide()
            win = tk.Toplevel(widget)
            win.wm_overrideredirect(True)
            win.transient(widget.winfo_toplevel())
            win.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 16}")
            tk.Label(win, text=text, bg="#ffffe0", relief="solid", borderwidth=1, font=("Segoe UI", 10),
                     justify=tk.LEFT, wraplength=360, padx=8, pady=4).pack()
            tip[0] = win

        def hide(event=None):
            if tip[0] is not None:
                tip[0].destroy()
                tip[0] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")
        widget.bind("<Button-1>", hide, add="+")

    def set_wh_car_status(self, text, state=None):
        """Строка о машине в форме склада и цвет рамки карточки.
        state: "found" - найдена, "new" - новая машина (нужны данные), "warn" - подсказка, None - пусто"""
        self.wh_car_info_label.configure(text=text, text_color=self.FORM_STATE_COLORS.get(state, "gray"))
        if text:
            self.wh_car_info_label.pack(fill=tk.X, pady=(6, 0))
        else:
            self.wh_car_info_label.pack_forget()
            self.wh_car_info_label.master.configure(height=1)  # пустой контейнер Tk сам не сжимает
        self.form_set_card_state(self.wh_car_card, state if text else None)
        self.fit_form_window(self.add_part_form_frame)

    def wh_hide_phone_cars(self):
        if self.wh_phone_cars_combo.winfo_manager():
            self.wh_phone_cars_combo.pack_forget()
            self.fit_form_window(self.add_part_form_frame)

    def search_car_for_warehouse(self):
        """Поиск машины по госномеру для склада - по мере ввода (с 6 символов), как в "Записать клиента" """
        car_number = self.wh_car_number_entry.get().strip()
        self._wh_phone_unmark_if_changed()
        if car_number and car_number.upper() == getattr(self, "wh_searched_number", None):
            return  # этот госномер уже искали - не дёргаем базу на каждое нажатие (Tab, стрелки)
        self.wh_searched_number = car_number.upper() if len(car_number) >= 6 else None
        if len(car_number) < 6:
            self.wh_selected_car_id = None
            # Госномер стёрли - телефон, подставленный по нему (если не правили), тоже убираем
            plate_phone = getattr(self, "wh_plate_phone", None)
            if plate_phone and self.wh_phone_entry.get() == plate_phone:
                self.set_phone_value(self.wh_phone_entry, "")
                self.wh_phone_fill = None
            self.wh_plate_phone = None
            if getattr(self, "wh_form_by_phone", False):
                # Форму новой машины открыл поиск по телефону - не закрываем, ждём госномер
                return
            # Госномер ещё вводят (или стёрли) - ни "найдено", ни "новая машина" пока не показываем
            self.set_wh_car_status("")
            self.hide_new_car_form()
            return

        car_info = self.db.get_car_info_by_number(car_number)
        # Телефон, подставленный по прошлому госномеру (если его не правили руками) - убираем
        plate_phone = getattr(self, "wh_plate_phone", None)
        if plate_phone and self.wh_phone_entry.get() == plate_phone:
            self.set_phone_value(self.wh_phone_entry, "")
        self.wh_plate_phone = None
        if car_info:
            self.wh_selected_car_id = car_info.get("car_id")
            # Телефон - в поле рядом, здесь только машина и владелец (как во вкладке "Добавить работу")
            car_title = " ".join(x for x in (car_info.get('car_brand'), car_info.get('car_model')) if x)
            info_text = f"✓ {car_title} — {car_info.get('client_name') or self.tr('common.no_name')}"
            self.set_wh_car_status(info_text, "found")
            self.hide_new_car_form()
            # Телефон владельца - в поле телефона (если там ещё ничего не набрано)
            owner_phone = car_info.get("client_phone") or ""
            if owner_phone and not phone_mask_digits(self.wh_phone_entry.get()):
                self.set_phone_value(self.wh_phone_entry, owner_phone)
                self.wh_plate_phone = self.wh_phone_entry.get()
                self.wh_phone_entry.configure(fg_color=self.WORKS_AUTOFILL_BG)   # подставила программа
                # Номер уже "найден" - повторный поиск по нему ничего не подставит
                self.wh_phone_fill = {"digits": phone_mask_digits(self.wh_plate_phone), "filled": {}}
        else:
            self.wh_selected_car_id = None
            self.set_wh_car_status(self.tr("warehouse.car_not_found"), "new")
            self.show_new_car_form()

    def show_new_car_form(self):
        """Показать форму для новой машины"""
        if not self.wh_new_car_visible:
            self.wh_new_car_frame.pack(fill=tk.X, pady=(6, 0))
            self.wh_new_car_visible = True
            # Телефон уже введён и клиент известен - подставляем его имя
            phone_digits = phone_mask_digits(self.wh_phone_entry.get())
            if len(phone_digits) == 10 and not self.wh_new_client_name_entry.get().strip():
                fields = self.wh_phone_fill_fields()
                before = self.snapshot_fields(fields)
                client_name = self.db.get_client_name_by_phone(phone_digits)
                if client_name:
                    self.wh_new_client_name_entry.insert(0, client_name)
                if self.wh_phone_fill and self.wh_phone_fill["digits"] == phone_digits:
                    self.wh_phone_fill["filled"].update(self.autofilled_diff(fields, before))
            self.fit_form_window(self.add_part_form_frame)

    def hide_new_car_form(self):
        """Скрыть форму для новой машины"""
        self.wh_form_by_phone = False
        if self.wh_new_car_visible:
            self.hide_wh_brand_listbox()
            self.hide_wh_model_listbox()
            self.wh_new_car_frame.pack_forget()
            self.wh_new_car_frame.master.configure(height=1)  # пустой контейнер Tk сам не сжимает
            self.wh_new_car_visible = False
            self.fit_form_window(self.add_part_form_frame)

    def _wh_phone_unmark_if_changed(self):
        """Телефон уже не тот, что подставил госномер (правили руками или убрали) - снять зелёную подсветку"""
        if self.wh_phone_entry.get() != getattr(self, "wh_plate_phone", None):
            self.wh_phone_entry.configure(fg_color=self.wh_entry_bg)

    def on_wh_phone_keyrelease(self, event=None):
        """Поиск клиента по телефону (склад): одна машина - подставляем госномер, несколько - список"""
        self._wh_phone_unmark_if_changed()
        digits = phone_mask_digits(self.wh_phone_entry.get())
        fields = self.wh_phone_fill_fields()

        # Номер изменили - убираем всё, что подставили по прошлому номеру
        if self.wh_phone_fill and self.wh_phone_fill["digits"] != digits:
            filled = self.wh_phone_fill["filled"]
            self.wh_phone_fill = None
            self.wh_hide_phone_cars()
            self.undo_autofill(fields, filled)
            if not self.wh_car_number_entry.get().strip():
                # Госномер был подставлен и стёрт (или форму новой машины открыл поиск по телефону) - сбрасываем
                self.wh_selected_car_id = None
                self.set_wh_car_status("")
                self.hide_new_car_form()
            elif self.wh_car_info_label.cget("text") == getattr(self, "wh_phone_msg", None):
                self.set_wh_car_status("")
        if len(digits) != 10:
            self.wh_hide_phone_cars()
            return
        if self.wh_phone_fill:
            return

        before = self.snapshot_fields(fields)
        self.wh_phone_fill = {"digits": digits, "filled": {}}
        self.fill_wh_by_phone(digits)
        self.wh_phone_fill["filled"] = self.autofilled_diff(fields, before)

    def wh_phone_fill_fields(self):
        """Поля формы склада, которые заполняет поиск по телефону"""
        return {"car_number": self.wh_car_number_entry, "new_name": self.wh_new_client_name_entry}

    def fill_wh_by_phone(self, digits):
        # Госномер уже введён вручную - его не трогаем (это может быть новая машина известного клиента),
        # только подставляем имя клиента в открытую форму новой машины
        if self.wh_car_number_entry.get().strip():
            self.wh_hide_phone_cars()
            if self.wh_new_car_visible and not self.wh_new_client_name_entry.get().strip():
                client_name = self.db.get_client_name_by_phone(digits)
                if client_name:
                    self.wh_new_client_name_entry.insert(0, client_name)
            return

        self.wh_phone_cars_numbers = {}
        for car_brand, car_model, car_number, _vin in self.db.get_client_cars_by_phone(digits):
            if car_number:
                display = f"{car_brand or ''} {car_model or ''} {car_number}".strip()
                self.wh_phone_cars_numbers[display] = car_number

        if not self.wh_phone_cars_numbers:
            self.wh_hide_phone_cars()
            client_name = self.db.get_client_name_by_phone(digits)
            text = (self.tr("warehouse.phone_client_no_cars", name=client_name) if client_name
                    else self.tr("warehouse.phone_client_not_found"))
            # Клиента или его машин нет в базе - сразу открываем форму новой машины,
            # как при ненайденном госномере
            self.wh_phone_msg = text
            self.wh_selected_car_id = None
            self.show_new_car_form()
            self.wh_form_by_phone = True
            self.set_wh_car_status(text, "new")
            return

        if len(self.wh_phone_cars_numbers) == 1:
            self.wh_hide_phone_cars()
            self.fill_wh_car_number(next(iter(self.wh_phone_cars_numbers.values())))
        else:
            self.wh_phone_cars_combo.configure(values=list(self.wh_phone_cars_numbers))
            self.wh_phone_cars_combo.set(self.tr("bookings.add_window_client_cars"))
            if not self.wh_phone_cars_combo.winfo_manager():
                self.wh_phone_cars_combo.pack(fill=tk.X, pady=(8, 0))
                self.fit_form_window(self.add_part_form_frame)

    def on_wh_phone_car_select(self, choice):
        """Выбрана машина клиента из списка (склад)"""
        number = self.wh_phone_cars_numbers.get(choice)
        if number:
            fields = self.wh_phone_fill_fields()
            before = self.snapshot_fields(fields)
            self.fill_wh_car_number(number)
            # Машину выбрали из списка по телефону - при смене номера её тоже уберём
            if self.wh_phone_fill:
                self.wh_phone_fill["filled"].update(self.autofilled_diff(fields, before))

    def fill_wh_car_number(self, number):
        """Подставить госномер в форму склада и найти машину"""
        self.wh_car_number_entry.delete(0, tk.END)
        self.wh_car_number_entry.insert(0, number)
        self.search_car_for_warehouse()

    # === Автокомплит для марки (форма склада) ===
    def on_wh_brand_keyrelease(self, event):
        """Обработчик ввода текста для марки (склад)"""
        if event.keysym in ('Up', 'Down', 'Return', 'Escape'):
            return

        search_text = self.wh_new_brand_entry.get().strip()
        if len(search_text) < 1:
            self.hide_wh_brand_listbox()
            return

        brands = self.db.search_car_brands(search_text)
        if brands:
            self.show_wh_brand_listbox(brands)
        else:
            self.hide_wh_brand_listbox()

    def show_wh_brand_listbox(self, brands):
        """Показать список марок (склад)"""
        self.wh_brand_listbox.delete(0, tk.END)
        for brand in brands:
            self.wh_brand_listbox.insert(tk.END, brand)
        self.place_popup(self.wh_brand_listbox, self.wh_new_brand_entry)
        self.wh_brand_listbox_visible = True

    def hide_wh_brand_listbox(self):
        """Скрыть список марок (склад)"""
        if self.wh_brand_listbox_visible:
            self.hide_popup(self.wh_brand_listbox)
            self.wh_brand_listbox_visible = False

    def on_wh_brand_select(self, event):
        """Обработчик выбора марки из списка (склад)"""
        selection = self.wh_brand_listbox.curselection()
        if selection:
            brand = self.wh_brand_listbox.get(selection[0])
            self.wh_new_brand_entry.delete(0, tk.END)
            self.wh_new_brand_entry.insert(0, brand)
            self.hide_wh_brand_listbox()

            # Автоматически показываем все модели выбранной марки
            models = self.db.search_car_models(brand, "")
            if models:
                self.wh_new_model_entry.delete(0, tk.END)
                self.show_wh_model_listbox(models)
                self.wh_new_model_entry.focus_set()

    def on_wh_brand_focus_out(self, event):
        """Скрыть список при потере фокуса (склад)"""
        self.root.after(200, self.hide_wh_brand_listbox)

    # === Автокомплит для модели (форма склада) ===
    def on_wh_model_keyrelease(self, event):
        """Обработчик ввода текста для модели (склад)"""
        if event.keysym in ('Up', 'Down', 'Return', 'Escape'):
            return

        brand = self.wh_new_brand_entry.get().strip()
        if not brand:
            self.hide_wh_model_listbox()
            return

        search_text = self.wh_new_model_entry.get().strip()
        models = self.db.search_car_models(brand, search_text)
        if models:
            self.show_wh_model_listbox(models)
        else:
            self.hide_wh_model_listbox()

    def show_wh_model_listbox(self, models):
        """Показать список моделей (склад)"""
        self.wh_model_listbox.delete(0, tk.END)
        for model in models:
            self.wh_model_listbox.insert(tk.END, model)
        self.place_popup(self.wh_model_listbox, self.wh_new_model_entry)
        self.wh_model_listbox_visible = True

    def hide_wh_model_listbox(self):
        """Скрыть список моделей (склад)"""
        if self.wh_model_listbox_visible:
            self.hide_popup(self.wh_model_listbox)
            self.wh_model_listbox_visible = False

    def on_wh_model_select(self, event):
        """Обработчик выбора модели из списка (склад)"""
        selection = self.wh_model_listbox.curselection()
        if selection:
            model = self.wh_model_listbox.get(selection[0])
            self.wh_new_model_entry.delete(0, tk.END)
            self.wh_new_model_entry.insert(0, model)
            self.hide_wh_model_listbox()

    def on_wh_model_focus_out(self, event):
        """Скрыть список при потере фокуса (склад)"""
        self.root.after(200, self.hide_wh_model_listbox)

    def hide_add_part_form(self):
        """Скрыть форму добавления запчасти"""
        # Скрываем списки автокомплита
        if hasattr(self, 'wh_brand_listbox_visible'):
            self.hide_wh_brand_listbox()
        if hasattr(self, 'wh_model_listbox_visible'):
            self.hide_wh_model_listbox()

        # Окно не уничтожаем - прячем вместе с затемнением; при следующем открытии форма сбросится
        window = getattr(self, "_part_window", None)
        if window is not None and window.winfo_exists():
            window.grab_release()
            window.withdraw()
        overlay = getattr(self, "wh_part_overlay", None)
        if overlay is not None and overlay.winfo_exists():
            overlay.withdraw()
        self.add_part_form_visible = False

    def add_warehouse_part(self):
        """Добавить запчасть на склад"""
        car_number = self.wh_car_number_entry.get().strip().upper()
        part_name = " ".join(self.wh_part_name_entry.get().split())
        quantity_str = self.wh_quantity_entry.get().strip()
        price_str = self.wh_price_entry.get().strip()
        notes = self.wh_notes_entry.get().strip()

        if not part_name:
            self.form_mark_error(self.wh_part_name_entry, "works.msg_enter_part_name", self.add_part_form_frame)
            return

        try:
            quantity = int(quantity_str) if quantity_str else 1
        except ValueError:
            self.form_mark_error(self.wh_quantity_entry, "warehouse.msg_quantity_number", self.add_part_form_frame)
            return

        try:
            price = float(price_str.replace(",", ".")) if price_str else None
        except ValueError:
            self.form_mark_error(self.wh_price_entry, "warehouse.msg_price_number", self.add_part_form_frame)
            return

        # Используем car_id если машина найдена
        car_id = self.wh_selected_car_id if hasattr(self, 'wh_selected_car_id') else None

        # Если госномер введён, но машина не найдена — пробуем найти автоматически
        if car_number and car_id is None:
            car_info = self.db.get_car_info_by_number(car_number)
            if car_info:
                car_id = car_info.get("car_id")
                self.wh_selected_car_id = car_id

        # Форма новой машины открыта (например, поиском по телефону), а госномер не введён
        if car_id is None and self.wh_new_car_visible and not car_number:
            self.form_mark_error(self.wh_car_number_entry, "works.msg_enter_car_number", self.add_part_form_frame)
            return

        # Если машина не найдена и форма новой машины видна — создаём клиента и машину
        if car_id is None and self.wh_new_car_visible and car_number:
            brand = self.wh_new_brand_entry.get().strip()
            model = self.wh_new_model_entry.get().strip()
            client_name = self.wh_new_client_name_entry.get().strip()
            phone_digits = phone_mask_digits(self.wh_phone_entry.get())

            if not brand:
                self.form_mark_error(self.wh_new_brand_entry, "warehouse.msg_enter_car_brand", self.add_part_form_frame)
                return

            # Проверка телефона: должен быть +7 и 10 цифр
            if len(phone_digits) != 10:
                self.form_mark_error(self.wh_phone_entry, "warehouse.msg_enter_full_phone", self.add_part_form_frame)
                return
            phone = "+7" + phone_digits

            # Создаём или находим клиента
            client_id = self.db.get_or_create_client(
                full_name=client_name if client_name else None,
                phone=phone if phone else None,
                car_number=car_number
            )

            # Создаём машину
            car_id = self.db.get_or_create_car(
                client_id=client_id,
                car_brand=brand,
                car_model=model if model else "",
                car_number=car_number
            )

        # Предупреждение: госномер введён, но машина не привязана
        if car_number and car_id is None:
            result = messagebox.askyesno(
                self.tr("common.attention"),
                self.tr("warehouse.msg_car_not_found_confirm", car_number=car_number),
                parent=self.add_part_form_frame   # поверх окна формы, а не под затемнением
            )
            if not result:
                return

        self.db.add_warehouse_part(
            car_id=car_id,
            part_name=part_name,
            quantity=quantity,
            price=price,
            notes=notes if notes else None,
            is_paid=self.wh_paid_var.get()
        )

        messagebox.showinfo(self.tr("common.success"), self.tr("warehouse.msg_part_added"),
                            parent=self.add_part_form_frame)
        self.hide_add_part_form()
        self.refresh_warehouse()

    def refresh_warehouse(self):
        """Обновить список запчастей на складе"""
        # Очистка таблицы
        for item in self.warehouse_tree.get_children():
            self.warehouse_tree.delete(item)

        # Получение фильтра по статусу
        status_filter = self.warehouse_status_var.get() if hasattr(self, 'warehouse_status_var') else self.tr("bookings.filter_all")
        status_map = {
            self.tr("bookings.filter_all"): None,
            self.tr("warehouse.status_in_transit"): "в пути",
            self.tr("warehouse.status_in_stock"): "на складе",
            self.tr("warehouse.status_issued"): "выдано",
        }
        status = status_map.get(status_filter, None)

        # Поиск по госномеру
        search_query = self.warehouse_search_entry.get().strip().upper() if hasattr(self, 'warehouse_search_entry') else ""

        # Получение данных (новая структура с JOIN)
        parts = self.db.get_all_warehouse_parts(status=status)

        for part in parts:
            # Новая структура: id, car_number, car_brand, car_model, client_name, client_phone,
            #                  part_name, quantity, price, status, order_date, received_date, notes, car_id, is_paid
            part_id, car_number, car_brand, car_model, client_name, client_phone, \
                part_name, quantity, price, part_status, order_date, received_date, notes, car_id, is_paid = part

            # Фильтрация по госномеру
            if search_query and (not car_number or search_query not in car_number.upper()):
                continue

            # Форматирование информации о машине
            car_info = f"{car_number or ''} {car_brand or ''} {car_model or ''}".strip() or "-"

            # Форматирование информации о клиенте
            client_info = client_name or "-"

            # Форматирование дат
            order_date_str = order_date.strftime("%d.%m.%Y") if order_date else "-"
            received_date_str = received_date.strftime("%d.%m.%Y") if received_date else "-"

            # Форматирование цены
            price_str = self.format_currency(float(price)) if price else "-"

            # Статус для отображения (в БД статус всегда хранится по-русски)
            status_display = {
                "в пути": self.tr("warehouse.status_in_transit"),
                "на складе": self.tr("warehouse.status_in_stock"),
                "выдано": self.tr("warehouse.status_issued"),
            }.get(part_status, part_status)

            paid_str = self.tr("common.yes") if is_paid else self.tr("common.no")

            self.warehouse_tree.insert("", tk.END, values=(
                part_id,
                car_info,
                client_info,
                part_name,
                quantity,
                price_str,
                paid_str,
                status_display,
                order_date_str,
                received_date_str,
                notes or "-"
            ), tags=(part_status,))

    def clear_warehouse_search(self):
        """Очистить поиск по складу"""
        self.warehouse_search_entry.delete(0, tk.END)
        self.refresh_warehouse()

    def update_part_status(self, new_status):
        """Обновить статус выбранной запчасти"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_select_part"))
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])
        current_status = values[7]  # колонка статуса (уже переведённая для отображения)

        # Защита от смены статуса "выдано"
        if current_status == self.tr("warehouse.status_issued"):
            if not messagebox.askyesno(self.tr("common.confirm"), self.tr("warehouse.msg_confirm_return_to_stock")):
                return

        # Если статус "на складе", устанавливаем дату прихода
        received_date = None
        if new_status == "на складе":
            from datetime import date
            received_date = date.today()

        self.db.update_warehouse_part_status(part_id, new_status, received_date)
        self.refresh_warehouse()

    def set_warehouse_part_paid(self, is_paid: bool):
        """Быстро отметить выбранную складскую позицию как оплаченную/неоплаченную"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_select_part"))
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])

        self.db.update_warehouse_part_paid(part_id, is_paid)
        self.refresh_warehouse()

    def goto_booking_from_warehouse(self):
        """Перейти во вкладку 'Записи' к записи, связанной с автомобилем выбранной запчасти"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_select_part"))
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])

        part = self.db.get_warehouse_part_by_id(part_id)
        if not part:
            messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_part_not_found"))
            return

        booking_id = None

        # Сначала пытаемся найти именно тот наряд, в который была установлена деталь
        work_id = part.get("work_id")
        if work_id:
            work = self.db.get_work_by_id(work_id)
            if work:
                booking_id = work[11]  # booking_id из наряда

        # Запасной вариант (старые детали без привязки к наряду) - последняя запись по машине
        if not booking_id:
            car_id = part.get("car_id")
            if not car_id:
                messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_no_car_linked"))
                return

            bookings = self.db.get_bookings_by_car_id(car_id)
            if not bookings:
                messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_no_related_booking"))
                return

            booking_id = bookings[0][0]  # самая свежая запись для этого авто

        # Переключаемся на вкладку записей и сбрасываем фильтры, чтобы запись точно была видна
        self.switch_tab("bookings")
        if hasattr(self, "bookings_status_var"):
            self.bookings_status_var.set(self.tr("bookings.filter_all"))
        if hasattr(self, "bookings_period_var"):
            self.bookings_period_var.set(self.tr("bookings.period_all"))
        if hasattr(self, "bookings_search_entry"):
            self.bookings_search_entry.delete(0, tk.END)
        self.refresh_bookings()

        for item in self.bookings_tree.get_children():
            if self.bookings_tree.item(item, "values")[0] == str(booking_id):
                self.bookings_tree.selection_set(item)
                self.bookings_tree.focus(item)
                self.bookings_tree.see(item)
                break

    def edit_warehouse_part(self):
        """Редактировать выбранную запчасть"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_select_part"))
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])

        # Получаем данные запчасти из БД
        part_data = self.db.get_warehouse_part_by_id(part_id)
        if not part_data:
            messagebox.showerror(self.tr("common.error"), self.tr("warehouse.msg_part_not_found"))
            return

        # Создаём окно редактирования
        edit_window = ctk.CTkToplevel(self.root)
        edit_window.title(self.tr("warehouse.edit_part_title"))
        edit_window.geometry("450x400")
        edit_window.transient(self.root)
        edit_window.grab_set()

        # Центрируем окно
        x = (edit_window.winfo_screenwidth() - 450) // 2
        y = (edit_window.winfo_screenheight() - 400) // 2
        edit_window.geometry(f"+{x}+{y}")

        # Форма
        form_frame = ctk.CTkFrame(edit_window)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ctk.CTkLabel(form_frame, text=self.tr("warehouse.edit_part_header"),
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(0, 15))

        # Информация о машине (только для чтения)
        car_info = f"{part_data.get('car_number', '')} {part_data.get('car_brand', '')} {part_data.get('car_model', '')}".strip()
        if car_info:
            ctk.CTkLabel(form_frame, text=self.tr("warehouse.car_info_label", car_info=car_info), text_color="gray").pack(anchor="w", pady=(0, 10))

        # Название запчасти
        row1 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text=self.tr("warehouse.part_label"), width=100, anchor="w").pack(side=tk.LEFT)
        part_name_entry = ctk.CTkEntry(row1, width=280, fg_color="white", text_color="black")
        part_name_entry.pack(side=tk.LEFT)
        part_name_entry.insert(0, part_data.get('part_name', ''))

        # Количество
        row2 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row2.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row2, text=self.tr("warehouse.quantity_label"), width=100, anchor="w").pack(side=tk.LEFT)
        quantity_entry = ctk.CTkEntry(row2, width=100, fg_color="white", text_color="black")
        quantity_entry.pack(side=tk.LEFT)
        quantity_entry.insert(0, str(part_data.get('quantity', 1)))

        # Цена
        row3 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row3.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row3, text=self.tr("works.price_label"), width=100, anchor="w").pack(side=tk.LEFT)
        price_entry = ctk.CTkEntry(row3, width=150, fg_color="white", text_color="black")
        price_entry.pack(side=tk.LEFT)
        if part_data.get('price'):
            price_entry.insert(0, str(part_data.get('price')))

        # Уже оплачено
        row_paid = ctk.CTkFrame(form_frame, fg_color="transparent")
        row_paid.pack(fill=tk.X, pady=5)
        paid_var = tk.BooleanVar(value=bool(part_data.get('is_paid')))
        ctk.CTkCheckBox(row_paid, text=self.tr("warehouse.paid_checkbox_label"),
                        variable=paid_var).pack(side=tk.LEFT)

        # Статус (в БД хранится по-русски, в интерфейсе показываем перевод)
        row4 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row4.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row4, text=self.tr("bookings.status_label"), width=100, anchor="w").pack(side=tk.LEFT)
        status_display_to_raw = {
            self.tr("warehouse.status_in_transit"): "в пути",
            self.tr("warehouse.status_in_stock"): "на складе",
            self.tr("warehouse.status_issued"): "выдано",
        }
        status_raw_to_display = {v: k for k, v in status_display_to_raw.items()}
        status_var = tk.StringVar(value=status_raw_to_display.get(part_data.get('status', 'в пути'), self.tr("warehouse.status_in_transit")))
        status_combo = ctk.CTkComboBox(row4, variable=status_var,
                                        values=list(status_display_to_raw.keys()), width=150)
        status_combo.pack(side=tk.LEFT)

        # Примечания
        row5 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row5.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row5, text=self.tr("warehouse.notes_label"), width=100, anchor="w").pack(side=tk.LEFT)
        notes_entry = ctk.CTkEntry(row5, width=280, fg_color="white", text_color="black")
        notes_entry.pack(side=tk.LEFT)
        if part_data.get('notes'):
            notes_entry.insert(0, part_data.get('notes'))

        def save_changes():
            new_part_name = " ".join(part_name_entry.get().split())
            if not new_part_name:
                messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_part_name"))
                return

            try:
                new_quantity = int(quantity_entry.get().strip()) if quantity_entry.get().strip() else 1
            except ValueError:
                messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_quantity_number"))
                return

            try:
                price_str = price_entry.get().strip().replace(",", ".")
                new_price = float(price_str) if price_str else None
            except ValueError:
                messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_price_number"))
                return

            new_status = status_display_to_raw.get(status_var.get(), status_var.get())
            new_notes = notes_entry.get().strip() or None

            # Защита от смены статуса "выдано"
            if part_data.get('status') == 'выдано' and new_status != 'выдано':
                if not messagebox.askyesno(self.tr("common.confirm"), self.tr("warehouse.msg_confirm_return_to_stock"),
                        parent=edit_window):
                    return

            self.db.update_warehouse_part(part_id, new_part_name, new_quantity, new_price, new_status, new_notes, paid_var.get())
            edit_window.destroy()
            self.refresh_warehouse()
            messagebox.showinfo(self.tr("common.success"), self.tr("warehouse.msg_part_updated"))

        # Кнопки
        buttons_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        buttons_frame.pack(pady=20)

        ctk.CTkButton(buttons_frame, text=self.tr("common.save"), command=save_changes,
                     fg_color="#2e7d32", hover_color="#1b5e20", width=120).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(buttons_frame, text=self.tr("common.cancel"), command=edit_window.destroy,
                     fg_color="#757575", hover_color="#616161", width=120).pack(side=tk.LEFT, padx=10)

    def delete_warehouse_part(self):
        """Удалить выбранную запчасть"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("warehouse.msg_select_part"))
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])
        part_name = values[3]

        if messagebox.askyesno(self.tr("common.confirm"), self.tr("warehouse.msg_confirm_delete_part", part_name=part_name)):
            self.db.delete_warehouse_part(part_id)
            self.refresh_warehouse()

    # ===== ВКЛАДКА ОТЧЁТОВ =====

    def setup_reports_tab(self):
        """Настройка вкладки отчётов"""
        # Выбор периода
        period_frame = ctk.CTkFrame(self.reports_frame)
        period_frame.pack(fill=tk.X, padx=10, pady=10)
        title = ctk.CTkLabel(
            period_frame,
            text=self.tr("reports.title_period"),
            font=("Segoe UI", 20, "bold"),
            anchor="center"
        )

        title.pack(fill=tk.X, pady=(0, 10))

        dates_frame = ctk.CTkFrame(period_frame)
        dates_frame.pack()

        ctk.CTkLabel(dates_frame, text=self.tr("reports.date_from_label")).pack(side=tk.LEFT, padx=5)
        self.date_from = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy',
                                    locale='ru_RU')
        self.date_from.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(dates_frame, text=self.tr("reports.date_to_label")).pack(side=tk.LEFT, padx=15)
        self.date_to = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy',
                                  locale='ru_RU')
        self.date_to.pack(side=tk.LEFT, padx=5)

        # Без пароля отчёт только за сегодня; другие даты открываются паролем для отчётов
        self.add_period_lock("reports", dates_frame, (self.date_from, self.date_to),
                             lambda: self.generate_report(show_empty_message=False))

        ctk.CTkLabel(dates_frame, text=self.tr("reports.master_percent_label")).pack(side=tk.LEFT, padx=(20, 5))
        settings = self.load_settings()
        self.percent_var = tk.StringVar(value=str(settings.get('master_percent', 50)))
        self.percent_var.trace_add('write', self.on_percent_changed)
        self.percent_entry = ctk.CTkEntry(dates_frame, width=80,
                                          textvariable=self.percent_var, fg_color="white", text_color="black")
        self.percent_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkLabel(dates_frame, text="%").pack(side=tk.LEFT)

        ctk.CTkButton(dates_frame, text=self.tr("reports.generate_btn"),
                   command=self.generate_report).pack(side=tk.LEFT, padx=20)

        # Сводка по работникам
        summary_frame = ctk.CTkFrame(self.reports_frame)
        summary_frame.pack(fill=tk.X, padx=10, pady=10)
        title_masters = ctk.CTkLabel(
            summary_frame,
            text=self.tr("reports.summary_title"),
            font=("Segoe UI", 20, "bold"),
            anchor="center")
        title_masters.pack(fill=tk.X, pady=(0, 10))

        summary_table_frame = ctk.CTkFrame(summary_frame, fg_color="transparent")
        summary_table_frame.pack(fill=tk.X, padx=5)

        columns = ("name", "count", "total", "percent", "bonus")
        self.summary_tree = ttk.Treeview(summary_table_frame, columns=columns, show="headings", height=8)
        self.summary_tree.heading("name", text=self.tr("reports.col_master_name"))
        self.summary_tree.heading("count", text=self.tr("reports.col_work_count"))
        self.summary_tree.heading("total", text=self.tr("reports.col_total_earned"))
        self.summary_tree.heading("percent", text=self.tr("reports.col_master_percent"))
        self.summary_tree.heading("bonus", text=self.tr("reports.col_bonus"))

        self.summary_tree.column("name", width=200)
        self.summary_tree.column("count", width=200, anchor=tk.CENTER)
        self.summary_tree.column("total", width=230, anchor=tk.CENTER)
        self.summary_tree.column("percent", width=210, anchor=tk.CENTER)
        self.summary_tree.column("bonus", width=170, anchor=tk.CENTER)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.summary_tree.tag_configure('oddrow', background='#ffffff')
        self.summary_tree.tag_configure('evenrow', background='#f0f0f0')

        summary_scrollbar = ttk.Scrollbar(summary_table_frame, orient=tk.VERTICAL, command=self.summary_tree.yview)
        self.summary_tree.configure(yscrollcommand=summary_scrollbar.set)
        summary_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.summary_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Данные о премиях по строкам (worker_id -> список (дата, сумма, комментарий)) для tooltip колонки "Премии"
        self.summary_bonus_data = {}

        def bonus_tooltip_text(item_id, col_name):
            if col_name != "bonus":
                return None
            tags = self.summary_tree.item(item_id, "tags")
            if not tags:
                return None
            worker_id = tags[0]
            bonuses = self.summary_bonus_data.get(worker_id)
            if not bonuses:
                return None
            lines = [self.tr("reports.bonus_tooltip_title")]
            for bonus_date, amount, comment in bonuses:
                if hasattr(bonus_date, 'strftime'):
                    date_str = bonus_date.strftime('%d.%m.%Y')
                else:
                    date_str = str(bonus_date)
                line = f"{date_str} — {self.format_currency(float(amount))}"
                if comment:
                    line += f" ({comment})"
                lines.append(line)
            return '\n'.join(lines)

        TreeviewTooltip(self.summary_tree, columns=["bonus"], text_provider=bonus_tooltip_text)

        # Контекстное меню для сводки по мастерам
        self.summary_context_menu = tk.Menu(
            self.summary_tree, tearoff=0,
            bg="#1e1e1e", fg="white", bd=0,
            activebackground="#2d2d2d", activeforeground="white",
            font=("Segoe UI", 11)
        )
        self.summary_context_menu.add_command(
            label="  📋  " + self.tr("reports.ctx_details"), command=self.show_master_report_details,
            foreground="#64b5f6", activeforeground="#90caf9",
            background="#1e1e1e", activebackground="#1976d2"
        )
        self.summary_context_menu.add_command(
            label="  💰  " + self.tr("reports.ctx_add_bonus"), command=self.show_add_bonus_window,
            foreground="#81c784", activeforeground="#a5d6a7",
            background="#1e1e1e", activebackground="#2e7d32"
        )
        self.summary_tree.bind("<Button-3>", self.show_summary_context_menu)

        # Общая сумма - фрейм с разноцветными label-ами
        self.total_frame = ctk.CTkFrame(summary_frame)
        self.total_frame.pack(pady=10)

        # Зелёный цвет для доходов/прибыли, красный для расходов
        green_color = "#2e7d32"
        red_color = "#c62828"

        # Загружаем процент из настроек для начального отображения
        settings = self.load_settings()
        initial_percent = settings.get('master_percent', 50)

        self.income_label = ctk.CTkLabel(self.total_frame, text=self.tr("reports.income_label", amount="0,00 руб."),
                                        font=("Arial", 12, "bold"), text_color=green_color)
        self.income_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.other_income_label = ctk.CTkLabel(self.total_frame, text=self.tr("reports.other_income_label", amount="0,00 руб."),
                                              font=("Arial", 12, "bold"), text_color=green_color)
        self.other_income_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.expenses_label = ctk.CTkLabel(self.total_frame, text=self.tr("reports.expenses_label", amount="0,00 руб."),
                                          font=("Arial", 12, "bold"), text_color=red_color)
        self.expenses_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.masters_label = ctk.CTkLabel(self.total_frame, text=self.tr("reports.masters_label", percent=f"{initial_percent:.0f}", amount="0,00 руб."),
                                         font=("Arial", 12, "bold"), text_color=red_color)
        self.masters_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.profit_label = ctk.CTkLabel(self.total_frame, text=self.tr("reports.profit_label", amount="0,00 руб."),
                                        font=("Arial", 12, "bold"), text_color=green_color)
        self.profit_label.pack(side=tk.LEFT, padx=5)

        # Tooltip для "Прочий доход" и "РАСХОДЫ"
        self.other_income_tooltip = LabelTooltip(self.other_income_label, self.format_currency, is_expense=False)
        self.expenses_tooltip = LabelTooltip(self.expenses_label, self.format_currency, is_expense=True)

    # Выбор периода под паролем для отчётов ("Отчёты", "Статистика"): без пароля - только сегодня.
    # self.period_locks[вкладка] = {"entries": (дата с, дата по), "button": кнопка, "refresh": пересчёт, "unlocked": bool}

    def add_period_lock(self, tab, parent, entries, refresh):
        """Кнопка "Другой период" рядом с датами; даты сразу закрываются на сегодня"""
        if not hasattr(self, "period_locks"):
            self.period_locks = {}
        button = ctk.CTkButton(parent, text="", width=150, command=lambda: self.toggle_period_lock(tab))
        button.pack(side=tk.LEFT, padx=(10, 0))
        self.period_locks[tab] = {"entries": entries, "button": button, "refresh": refresh, "unlocked": False}
        self.lock_period(tab)

    def is_period_unlocked(self, tab):
        return self.period_locks[tab]["unlocked"]

    def lock_period(self, tab):
        """Закрыть выбор периода: только сегодня"""
        lock = self.period_locks[tab]
        lock["unlocked"] = False
        for entry in lock["entries"]:
            entry.configure(state="normal")
            entry.set_date(date.today())
            entry.configure(state="disabled")
        lock["button"].configure(text=self.tr("reports.period_locked_btn"))

    def toggle_period_lock(self, tab):
        """Кнопка у дат: ввести пароль и открыть выбор периода / снова закрыть"""
        lock = self.period_locks[tab]
        if lock["unlocked"]:
            self.lock_period(tab)
            lock["refresh"]()
            return
        if not self.db.has_reports_password():
            messagebox.showinfo(self.tr("reports.password_title"), self.tr("reports.msg_no_password"))
            return
        password = self.ask_password(self.tr("reports.password_title"), self.tr("reports.password_prompt"))
        if password is None:
            return
        if not self.db.check_reports_password(password):
            messagebox.showerror(self.tr("reports.password_title"), self.tr("reports.msg_wrong_password"))
            return
        lock["unlocked"] = True
        for entry in lock["entries"]:
            entry.configure(state="normal")
        lock["button"].configure(text=self.tr("reports.period_unlocked_btn"))

    def ask_password(self, title, prompt):
        """Окно ввода пароля (символы скрыты). Возвращает введённое или None, если отменили"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(title)
        dialog.geometry("360x170")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        result = [None]

        ctk.CTkLabel(dialog, text=prompt, wraplength=320, justify=tk.LEFT).pack(padx=20, pady=(18, 8), anchor="w")
        entry = ctk.CTkEntry(dialog, width=320, show="•", fg_color="white", text_color="black")
        entry.pack(padx=20)

        def ok(event=None):
            result[0] = entry.get()
            dialog.destroy()

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(pady=15)
        ctk.CTkButton(buttons, text="OK", width=120, command=ok).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(buttons, text=self.tr("common.cancel"), width=120, fg_color="#757575", hover_color="#616161",
                      command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        entry.bind("<Return>", ok)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.after(100, entry.focus_force)
        self.root.wait_window(dialog)
        return result[0]

    def change_reports_password(self):
        """Настройки -> Пользователи: задать или сменить пароль для отчётов"""
        title = self.tr("reports.password_title")
        if self.db.has_reports_password():
            current = self.ask_password(title, self.tr("reports.password_current_prompt"))
            if current is None:
                return
            if not self.db.check_reports_password(current):
                messagebox.showerror(title, self.tr("reports.msg_wrong_password"), parent=self.root)
                return
        new = self.ask_password(title, self.tr("reports.password_new_prompt"))
        if not new:
            return
        repeat = self.ask_password(title, self.tr("reports.password_repeat_prompt"))
        if repeat is None:
            return
        if new != repeat:
            messagebox.showerror(title, self.tr("reports.msg_password_mismatch"), parent=self.root)
            return
        self.db.set_reports_password(new)
        messagebox.showinfo(title, self.tr("reports.msg_password_saved"), parent=self.root)

    def generate_report(self, show_empty_message=True):
        """Сформировать отчёт за период"""
        if not self.is_period_unlocked("reports"):
            # Без пароля - только сегодня (заодно сменится дата, если программа открыта с прошлого дня)
            self.lock_period("reports")
        date_from = self.date_from.get_date().strftime('%Y-%m-%d')
        date_to = self.date_to.get_date().strftime('%Y-%m-%d')

        if date_from > date_to:
            messagebox.showwarning(self.tr("common.attention"), self.tr("reports.msg_date_range_invalid"))
            return

        # Запоминаем период сформированного отчёта (для окна "Подробно" по мастеру)
        self.report_date_from = date_from
        self.report_date_to = date_to

        # Получаем процент
        try:
            percent = float(self.percent_var.get().replace(',', '.'))
            if percent < 0 or percent > 100:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(self.tr("common.attention"), self.tr("reports.msg_invalid_percent"))
            return

        # Очистка таблицы
        for item in self.summary_tree.get_children():
            self.summary_tree.delete(item)

        # Сводка
        summary = self.db.get_summary_by_period(date_from, date_to)
        bonus_sums = self.db.get_bonuses_sum_by_period(date_from, date_to)
        self.summary_bonus_data = {}
        grand_total = 0
        total_percent_sum = 0
        summary_row_index = 0
        for row in summary:
            worker_id, name, total, count = row
            total = float(total)  # MariaDB возвращает Decimal
            grand_total += total
            worker_share = total * percent / 100
            total_percent_sum += worker_share

            # Определяем тег для чередующихся строк
            row_tag = 'oddrow' if summary_row_index % 2 == 0 else 'evenrow'

            # Премии мастера за выбранный период (сумма в колонке, разбивка по датам - во всплывающей подсказке)
            bonus_total = bonus_sums.get(worker_id, 0)
            if bonus_total:
                self.summary_bonus_data[str(worker_id)] = self.db.get_bonuses_by_worker_and_period(worker_id, date_from, date_to)
                bonus_text = self.format_currency(bonus_total)
            else:
                bonus_text = "-"

            # ID мастера сохраняем в тегах вместе с цветом (для контекстного меню "Подробно"/"Выписать премию")
            self.summary_tree.insert("", tk.END, values=(
                name,
                count,
                self.format_currency(total),
                self.format_currency(worker_share),
                bonus_text
            ), tags=(str(worker_id), row_tag))

            summary_row_index += 1

        # Получаем расходы и доходы за период
        total_expenses = float(self.db.get_total_expenses_by_period(date_from, date_to))
        other_income = float(self.db.get_total_income_by_period(date_from, date_to))
        total_income = grand_total + other_income
        net_profit = total_income - total_expenses - total_percent_sum

        # Получаем детальные данные для tooltip
        detailed_expenses = self.db.get_detailed_expenses_by_period(date_from, date_to)
        detailed_income = self.db.get_detailed_income_by_period(date_from, date_to)

        # Обновляем данные для tooltip
        self.expenses_tooltip.set_data(detailed_expenses)
        self.other_income_tooltip.set_data(detailed_income)

        # Обновляем каждый label отдельно
        self.income_label.configure(text=self.tr("reports.income_label", amount=self.format_currency(grand_total)))
        self.other_income_label.configure(text=self.tr("reports.other_income_label", amount=self.format_currency(other_income)))
        self.expenses_label.configure(text=self.tr("reports.expenses_label", amount=self.format_currency(total_expenses)))
        self.masters_label.configure(text=self.tr("reports.masters_label", percent=f"{percent:.0f}", amount=self.format_currency(total_percent_sum)))

        # Цвет прибыли зависит от значения
        profit_color = "#2e7d32" if net_profit >= 0 else "#c62828"  # Зелёный если >= 0, красный если < 0
        self.profit_label.configure(text=self.tr("reports.profit_label", amount=self.format_currency(net_profit)), text_color=profit_color)

    def show_summary_context_menu(self, event):
        """Показать контекстное меню для строки сводки по мастеру"""
        item = self.summary_tree.identify_row(event.y)
        if item:
            self.summary_tree.selection_set(item)
            self.summary_context_menu.post(event.x_root, event.y_root)

    def show_add_bonus_window(self):
        """Показать окно начисления премии выбранному мастеру"""
        selection = self.summary_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_select_master"))
            return

        item = self.summary_tree.item(selection[0])
        worker_id = item['tags'][0]
        worker_name = item['values'][0]

        bonus_window = ctk.CTkToplevel(self.root)
        bonus_window.title(self.tr("reports.bonus_window_title", name=worker_name))
        bonus_window.geometry("380x260")
        bonus_window.transient(self.root)
        bonus_window.attributes("-topmost", True)
        bonus_window.grab_set()
        bonus_window.focus_force()

        main_frame = ctk.CTkFrame(bonus_window, fg_color="transparent")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ctk.CTkLabel(main_frame, text=f"👤  {worker_name}", font=("Arial", 16, "bold")).pack(anchor="w", pady=(0, 15))

        ctk.CTkLabel(main_frame, text=self.tr("reports.bonus_amount_label"), font=("Arial", 14)).pack(anchor="w", pady=(0, 5))
        amount_entry = ctk.CTkEntry(main_frame, width=200, font=("Arial", 14))
        amount_entry.pack(anchor="w", pady=(0, 10))
        amount_entry.focus_set()

        ctk.CTkLabel(main_frame, text=self.tr("reports.bonus_date_label"), font=("Arial", 14)).pack(anchor="w", pady=(0, 5))
        bonus_date_entry = DateEntry(main_frame, width=15, date_pattern='dd.mm.yyyy', locale='ru_RU')
        bonus_date_entry.pack(anchor="w", pady=(0, 15))

        def save_bonus():
            try:
                amount = float(amount_entry.get().strip().replace(',', '.'))
                if amount <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showwarning(self.tr("common.attention"), self.tr("reports.msg_invalid_bonus_amount"), parent=bonus_window)
                return

            bonus_date = bonus_date_entry.get_date()

            # Премия начисляется вместе со связанным расходом в "Финансы" одной транзакцией
            # (см. Database.add_worker_bonus) - поэтому удаление расхода на вкладке "Финансы"
            # удалит и премию из отчётов
            added = self.db.add_worker_bonus(
                int(worker_id), amount, bonus_date,
                self.tr("finances.bonus_description", name=worker_name),
                self.tr("finances.category_bonus")
            )
            if added:
                if hasattr(self, 'expenses_tree'):
                    self.refresh_expenses()

                messagebox.showinfo(self.tr("common.success"), self.tr("reports.msg_bonus_added", name=worker_name, amount=self.format_currency(amount)), parent=bonus_window)
                bonus_window.destroy()
                self.generate_report(show_empty_message=False)
            else:
                messagebox.showerror(self.tr("common.error"), self.tr("reports.msg_bonus_failed"), parent=bonus_window)

        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        ctk.CTkButton(btn_frame, text=self.tr("reports.bonus_save_btn"), command=save_bonus,
                     fg_color="#2e7d32", hover_color="#1b5e20", width=130, height=36, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_frame, text=self.tr("common.cancel"), command=bonus_window.destroy,
                     fg_color="#757575", hover_color="#616161", width=130, height=36, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)

    def show_master_report_details(self):
        """Показать окно с детализацией работ мастера за сформированный период"""
        selection = self.summary_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_select_master"))
            return

        item = self.summary_tree.item(selection[0])
        worker_id = item['tags'][0]
        worker_name = item['values'][0]

        date_from = getattr(self, 'report_date_from', None)
        date_to = getattr(self, 'report_date_to', None)
        if not date_from or not date_to:
            messagebox.showwarning(self.tr("common.attention"), self.tr("reports.msg_generate_first"))
            return

        works = self.db.get_works_by_worker_and_period(int(worker_id), date_from, date_to)

        # Создаём окно детализации
        details_window = ctk.CTkToplevel(self.root)
        details_window.title(self.tr("reports.details_window_title", name=worker_name))
        details_window.geometry("900x600")
        details_window.transient(self.root)
        details_window.grab_set()

        period_str = f"{datetime.strptime(date_from, '%Y-%m-%d').strftime('%d.%m.%Y')} — {datetime.strptime(date_to, '%Y-%m-%d').strftime('%d.%m.%Y')}"

        header_frame = ctk.CTkFrame(details_window, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(
            header_frame,
            text=f"👤  {worker_name}",
            font=("Arial", 18, "bold")
        ).pack(side="left")
        ctk.CTkLabel(
            header_frame,
            text=self.tr("reports.period_label", period=period_str),
            font=("Arial", 13),
            text_color=("gray30", "gray70")
        ).pack(side="right")

        table_frame = ctk.CTkFrame(details_window, fg_color="transparent")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        columns = ("date", "client", "work", "price")
        details_tree = ttk.Treeview(table_frame, columns=columns, show="tree headings")
        details_tree.heading("#0", text=self.tr("bookings.col_car"))
        details_tree.heading("date", text=self.tr("bookings.col_date"))
        details_tree.heading("client", text=self.tr("bookings.info_label_client"))
        details_tree.heading("work", text=self.tr("reports.col_work"))
        details_tree.heading("price", text=self.tr("works.col_price"))
        details_tree.column("#0", width=220)
        details_tree.column("date", width=90, anchor=tk.CENTER)
        details_tree.column("client", width=150)
        details_tree.column("work", width=250)
        details_tree.column("price", width=120, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=details_tree.yview)
        details_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        details_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        details_tree.tag_configure('carrow', background='#dbe9fb', font=("Segoe UI", 10, "bold"))
        details_tree.tag_configure('oddrow', background='#ffffff')
        details_tree.tag_configure('evenrow', background='#f0f0f0')

        # Группируем работы по автомобилю, сохраняя порядок первого появления (сначала недавние - works уже отсортирован по дате)
        cars = {}
        for work in works:
            work_id, description, amount, work_date, items_json, car_brand, car_model, car_number, client_name, client_phone = work
            amount = float(amount or 0)

            if hasattr(work_date, 'strftime'):
                date_str = work_date.strftime('%d.%m.%Y')
            else:
                date_str = str(work_date) if work_date else "-"

            car_info = " ".join(filter(None, [car_brand, car_model, car_number])).strip() or self.tr("reports.no_car")
            car_key = car_number or car_info
            client_display = client_name or "-"

            car_group = cars.setdefault(car_key, {
                "car_info": car_info, "client": client_display, "items": [], "total": 0.0
            })

            for work_name, price in self.get_work_line_items(work_id, description, amount, items_json):
                car_group["items"].append((date_str, work_name, price))
                car_group["total"] += price

        grand_total = 0.0
        for car_key, car_group in cars.items():
            grand_total += car_group["total"]
            work_count = len(car_group["items"])
            work_count_text = self.tr("reports.car_works_one") if work_count == 1 else self.tr("reports.car_works_many", count=work_count)
            car_node = details_tree.insert(
                "", tk.END,
                text=f"🚗 {car_group['car_info']}  ({work_count_text})",
                values=("", car_group["client"], "", self.format_currency(car_group["total"])),
                tags=('carrow',), open=True
            )
            for i, (date_str, work_name, price) in enumerate(car_group["items"]):
                row_tag = 'oddrow' if i % 2 == 0 else 'evenrow'
                details_tree.insert(
                    car_node, tk.END,
                    text="",
                    values=(date_str, "", work_name, self.format_currency(price)),
                    tags=(row_tag,)
                )

        # Итоговая строка
        footer_frame = ctk.CTkFrame(details_window, fg_color="transparent")
        footer_frame.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkLabel(
            footer_frame,
            text=self.tr("reports.footer_summary", cars=len(cars), works=len(works)),
            font=("Arial", 13),
            text_color=("gray30", "gray70")
        ).pack(side="left")
        ctk.CTkLabel(
            footer_frame,
            text=self.tr("reports.grand_total_label", amount=self.format_currency(grand_total)),
            font=("Arial", 15, "bold"),
            text_color="#2e7d32"
        ).pack(side="right")

        if not works:
            messagebox.showinfo(self.tr("common.info"), self.tr("reports.msg_no_works_for_master", name=worker_name), parent=details_window)

    # ===== ВКЛАДКА МАРОК И МОДЕЛЕЙ =====

    def setup_cars_tab(self):
        """Настройка вкладки марок и моделей"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.cars_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Импорт из файла
        import_frame = ctk.CTkFrame(center_container)
        import_frame.pack(pady=10)

        ctk.CTkLabel(import_frame, text=self.tr("cars.import_format_label"), anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text=self.tr("cars.import_btn"),
                   command=self.import_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление марки
        brand_frame = ctk.CTkFrame(center_container)
        brand_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(brand_frame, text=self.tr("cars.brand_name_label")).pack(side=tk.LEFT, padx=5)
        self.brand_name_entry = ctk.CTkEntry(brand_frame, width=300, fg_color="white", text_color="black")
        self.brand_name_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(brand_frame, text=self.tr("cars.add_brand_btn"), command=self.add_brand, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Добавление модели
        model_frame = ctk.CTkFrame(center_container)
        model_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(model_frame, text=self.tr("bookings.add_window_brand")).pack(side=tk.LEFT, padx=5)
        self.brand_combo = ctk.CTkComboBox(model_frame, width=250, fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.brand_combo.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(model_frame, text=self.tr("bookings.add_window_model")).pack(side=tk.LEFT, padx=5)
        self.model_name_entry = ctk.CTkEntry(model_frame, width=200, fg_color="white", text_color="black")
        self.model_name_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(model_frame, text=self.tr("cars.add_model_btn"), command=self.add_model, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список марок и моделей
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        # Две колонки: марки и модели
        left_frame = ctk.CTkFrame(list_frame)
        left_frame.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(left_frame, text=self.tr("cars.brands_label"), anchor="w").pack(anchor=tk.W)
        self.brands_listbox = tk.Listbox(left_frame, height=15, width=35)
        self.brands_listbox.pack()
        self.brands_listbox.bind('<<ListboxSelect>>', self.on_brand_listbox_select)
        ctk.CTkButton(left_frame, text=self.tr("cars.delete_brand_btn"), command=self.delete_brand, width=250, fg_color="red", hover_color="darkred").pack(pady=5)

        right_frame = ctk.CTkFrame(list_frame)
        right_frame.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(right_frame, text=self.tr("cars.models_of_brand_label"), anchor="w").pack(anchor=tk.W)
        self.models_listbox = tk.Listbox(right_frame, height=15, width=35)
        self.models_listbox.pack()
        ctk.CTkButton(right_frame, text=self.tr("cars.delete_model_btn"), command=self.delete_model, width=250, fg_color="red", hover_color="darkred").pack(pady=5)

        # Загружаем данные
        self.refresh_brands_list()

    def refresh_brands_list(self):
        """Обновить список марок"""
        self.brands_listbox.delete(0, tk.END)
        brands = self.db.get_all_car_brands()
        self.brands_data = {brand[1]: brand[0] for brand in brands}

        for brand_name in sorted(self.brands_data.keys()):
            self.brands_listbox.insert(tk.END, brand_name)

        # Обновить комбобокс
        sorted_brands = sorted(self.brands_data.keys())
        self.brand_combo.configure(values=sorted_brands)

        # Установить первую марку по умолчанию
        if sorted_brands:
            self.brand_combo.set(sorted_brands[0])

    def on_brand_listbox_select(self, event):
        """Обработчик выбора марки"""
        selection = self.brands_listbox.curselection()
        if not selection:
            return

        brand_name = self.brands_listbox.get(selection[0])
        brand_id = self.brands_data[brand_name]

        # Загружаем модели
        self.models_listbox.delete(0, tk.END)
        models = self.db.get_car_models_by_brand(brand_id)
        self.models_data = {model[1]: model[0] for model in models}

        for model_name in sorted(self.models_data.keys()):
            self.models_listbox.insert(tk.END, model_name)

    def add_brand(self):
        """Добавить марку"""
        brand_name = self.brand_name_entry.get().strip()
        if not brand_name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("cars.msg_enter_brand_name"))
            return

        if self.db.add_car_brand(brand_name):
            messagebox.showinfo(self.tr("common.success"), self.tr("cars.msg_brand_added", name=brand_name))
            self.brand_name_entry.delete(0, tk.END)
            self.refresh_brands_list()
        else:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_brand_exists"))

    def add_model(self):
        """Добавить модель"""
        if not self.brand_combo.get():
            messagebox.showwarning(self.tr("common.attention"), self.tr("cars.msg_select_brand"))
            return

        model_name = self.model_name_entry.get().strip()
        if not model_name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("cars.msg_enter_model_name"))
            return

        brand_id = self.brands_data[self.brand_combo.get()]

        if self.db.add_car_model(brand_id, model_name):
            messagebox.showinfo(self.tr("common.success"), self.tr("cars.msg_model_added", name=model_name))
            self.model_name_entry.delete(0, tk.END)
            # Обновляем список моделей если выбрана эта марка
            selection = self.brands_listbox.curselection()
            if selection and self.brands_listbox.get(selection[0]) == self.brand_combo.get():
                self.on_brand_listbox_select(None)
        else:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_model_exists_for_brand"))

    def delete_brand(self):
        """Удалить марку"""
        selection = self.brands_listbox.curselection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("cars.msg_select_brand_to_delete"))
            return

        brand_name = self.brands_listbox.get(selection[0])
        brand_id = self.brands_data[brand_name]

        if messagebox.askyesno(self.tr("common.confirm"),
                               self.tr("cars.msg_confirm_delete_brand", name=brand_name)):
            self.db.delete_car_brand(brand_id)
            messagebox.showinfo(self.tr("common.success"), self.tr("cars.msg_brand_deleted"))
            self.refresh_brands_list()
            self.models_listbox.delete(0, tk.END)

    def delete_model(self):
        """Удалить модель"""
        selection = self.models_listbox.curselection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("cars.msg_select_model_to_delete"))
            return

        model_name = self.models_listbox.get(selection[0])
        model_id = self.models_data[model_name]

        if messagebox.askyesno(self.tr("common.confirm"), self.tr("cars.msg_confirm_delete_model", name=model_name)):
            self.db.delete_car_model(model_id)
            messagebox.showinfo(self.tr("common.success"), self.tr("cars.msg_model_deleted"))
            # Обновляем список моделей
            brand_selection = self.brands_listbox.curselection()
            if brand_selection:
                self.on_brand_listbox_select(None)

    def import_from_file(self):
        """Импорт марок и моделей из JSON файла"""
        file_path = filedialog.askopenfilename(
            title=self.tr("cars.select_json_title"),
            filetypes=[(self.tr("cars.json_files_label"), "*.json"), (self.tr("cars.all_files_label"), "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_invalid_json_format"))
                return

            added_brands, added_models = self.db.import_brands_models_from_dict(data)
            messagebox.showinfo(self.tr("common.success"),
                              self.tr("cars.msg_import_done", brands=added_brands, models=added_models))
            self.refresh_brands_list()

        except json.JSONDecodeError:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_json_read_error"))
        except Exception as e:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_import_error", error=str(e)))

    # ===== ВКЛАДКА КЛЮЧЕВЫХ СЛОВ =====

    def setup_keywords_tab(self):
        """Настройка вкладки ключевых слов"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.keywords_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Заголовок
        ctk.CTkLabel(center_container, text=self.tr("keywords.title"),
                    font=("Segoe UI", 16, "bold")).pack(pady=10)

        # Импорт из файла
        import_frame = ctk.CTkFrame(center_container)
        import_frame.pack(pady=10)

        ctk.CTkLabel(import_frame, text=self.tr("keywords.import_format_label"), anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text=self.tr("keywords.import_btn"),
                   command=self.import_keywords_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление ключевого слова
        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(add_frame, text=self.tr("keywords.add_label"), width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.keyword_entry = ctk.CTkEntry(add_frame, width=350, fg_color="white", text_color="black")
        self.keyword_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(add_frame, text=self.tr("common.add"), command=self.add_keyword_action,
                     fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список ключевых слов
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        ctk.CTkLabel(list_frame, text=self.tr("keywords.list_label"), anchor="w").pack(anchor=tk.W)

        # Treeview для ключевых слов
        columns = ("id", "keyword")
        self.keywords_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.keywords_tree.heading("id", text="ID")
        self.keywords_tree.heading("keyword", text=self.tr("keywords.col_keyword"))
        self.keywords_tree.column("id", width=50, anchor=tk.CENTER)
        self.keywords_tree.column("keyword", width=450, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.keywords_tree.yview)
        self.keywords_tree.configure(yscrollcommand=scrollbar.set)

        self.keywords_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        ctk.CTkButton(center_container, text=self.tr("keywords.delete_selected_btn"),
                     command=self.delete_keyword_action, width=500,
                     fg_color="red", hover_color="darkred").pack(pady=10)

    def refresh_keywords_list(self):
        """Обновить список ключевых слов"""
        for item in self.keywords_tree.get_children():
            self.keywords_tree.delete(item)

        for keyword_id, keyword in self.db.get_all_keywords():
            self.keywords_tree.insert("", tk.END, values=(keyword_id, keyword))

    def add_keyword_action(self):
        """Добавить ключевое слово"""
        keyword = self.keyword_entry.get().strip()
        if not keyword:
            messagebox.showwarning(self.tr("common.attention"), self.tr("keywords.msg_enter_keyword"))
            return

        if self.db.add_keyword(keyword):
            messagebox.showinfo(self.tr("common.success"), self.tr("keywords.msg_added", name=keyword))
            self.keyword_entry.delete(0, tk.END)
            self.refresh_keywords_list()
        else:
            messagebox.showerror(self.tr("common.error"), self.tr("keywords.msg_already_exists"))

    def delete_keyword_action(self):
        """Удалить ключевое слово"""
        selected = self.keywords_tree.selection()
        if not selected:
            messagebox.showwarning(self.tr("common.attention"), self.tr("keywords.msg_select_to_delete"))
            return

        item = self.keywords_tree.item(selected[0])
        keyword_id = item['values'][0]
        keyword = item['values'][1]

        if messagebox.askyesno(self.tr("common.confirm"), self.tr("keywords.msg_confirm_delete", name=keyword)):
            self.db.delete_keyword(keyword_id)
            messagebox.showinfo(self.tr("common.success"), self.tr("keywords.msg_deleted"))
            self.refresh_keywords_list()

    def import_keywords_from_file(self):
        """Импорт ключевых слов из файла (TXT или JSON)"""
        file_path = filedialog.askopenfilename(
            title=self.tr("keywords.select_file_title"),
            filetypes=[(self.tr("keywords.text_files_label"), "*.txt"), (self.tr("cars.json_files_label"), "*.json"), (self.tr("cars.all_files_label"), "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Определяем формат файла
            keywords = []
            if file_path.lower().endswith('.json'):
                data = json.loads(content)
                if isinstance(data, list):
                    keywords = data
                else:
                    messagebox.showerror(self.tr("common.error"), self.tr("keywords.msg_invalid_json_format"))
                    return
            else:
                # Текстовый файл - каждое слово на новой строке
                keywords = content.strip().splitlines()

            if not keywords:
                messagebox.showwarning(self.tr("common.attention"), self.tr("keywords.msg_empty_file"))
                return

            added = self.db.import_keywords_from_list(keywords)
            messagebox.showinfo(self.tr("common.success"), self.tr("keywords.msg_import_done", count=added))
            self.refresh_keywords_list()

        except json.JSONDecodeError:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_json_read_error"))
        except Exception as e:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_import_error", error=str(e)))

    # ===== ВКЛАДКА ЗАПЧАСТЕЙ =====

    def setup_spare_parts_tab(self):
        """Настройка вкладки запчастей"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.spare_parts_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Заголовок
        ctk.CTkLabel(center_container, text=self.tr("spareparts.title"),
                    font=("Segoe UI", 16, "bold")).pack(pady=10)

        # Импорт из файла
        import_frame = ctk.CTkFrame(center_container)
        import_frame.pack(pady=10)

        ctk.CTkLabel(import_frame, text=self.tr("spareparts.import_format_label"), anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text=self.tr("keywords.import_btn"),
                   command=self.import_spare_parts_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление запчасти
        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(add_frame, text=self.tr("works.name_label"), width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.spare_part_entry = ctk.CTkEntry(add_frame, width=350, fg_color="white", text_color="black")
        self.spare_part_entry.pack(side=tk.LEFT, padx=5)
        self.spare_part_entry.bind('<Return>', lambda e: self.add_spare_part_action())
        ctk.CTkButton(add_frame, text=self.tr("common.add"), command=self.add_spare_part_action,
                     fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список запчастей
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        ctk.CTkLabel(list_frame, text=self.tr("spareparts.list_label"), anchor="w").pack(anchor=tk.W)

        # Treeview для запчастей
        columns = ("part_name",)
        self.spare_parts_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.spare_parts_tree.heading("part_name", text=self.tr("spareparts.col_part_name"))
        self.spare_parts_tree.column("part_name", width=500, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.spare_parts_tree.yview)
        self.spare_parts_tree.configure(yscrollcommand=scrollbar.set)

        self.spare_parts_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        ctk.CTkButton(center_container, text=self.tr("spareparts.delete_selected_btn"),
                     command=self.delete_spare_part_action, width=500,
                     fg_color="red", hover_color="darkred").pack(pady=10)

    def refresh_spare_parts_list(self):
        """Обновить список запчастей"""
        for item in self.spare_parts_tree.get_children():
            self.spare_parts_tree.delete(item)

        for part_name in self.spare_parts_list:
            self.spare_parts_tree.insert("", tk.END, values=(part_name,))

    def save_spare_parts_file(self):
        """Сохранить список запчастей в текстовый файл"""
        try:
            os.makedirs(os.path.dirname(SPARE_PARTS_FILE), exist_ok=True)
            with open(SPARE_PARTS_FILE, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self.spare_parts_list))
        except Exception as e:
            messagebox.showerror(self.tr("common.error"), self.tr("spareparts.msg_save_error", error=str(e)))

    def add_spare_part_action(self):
        """Добавить запчасть"""
        part_name = self.spare_part_entry.get().strip()
        if not part_name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("works.msg_enter_part_name"))
            return

        if any(p.lower() == part_name.lower() for p in self.spare_parts_list):
            messagebox.showerror(self.tr("common.error"), self.tr("spareparts.msg_already_exists"))
            return

        self.spare_parts_list.append(part_name)
        self.save_spare_parts_file()
        messagebox.showinfo(self.tr("common.success"), self.tr("spareparts.msg_added", name=part_name))
        self.spare_part_entry.delete(0, tk.END)
        self.refresh_spare_parts_list()

    def delete_spare_part_action(self):
        """Удалить запчасть"""
        selected = self.spare_parts_tree.selection()
        if not selected:
            messagebox.showwarning(self.tr("common.attention"), self.tr("spareparts.msg_select_to_delete"))
            return

        item = self.spare_parts_tree.item(selected[0])
        part_name = item['values'][0]

        if messagebox.askyesno(self.tr("common.confirm"), self.tr("spareparts.msg_confirm_delete", name=part_name)):
            self.spare_parts_list = [p for p in self.spare_parts_list if p != part_name]
            self.save_spare_parts_file()
            messagebox.showinfo(self.tr("common.success"), self.tr("spareparts.msg_deleted"))
            self.refresh_spare_parts_list()

    def import_spare_parts_from_file(self):
        """Импорт запчастей из файла (TXT или JSON)"""
        file_path = filedialog.askopenfilename(
            title=self.tr("keywords.select_file_title"),
            filetypes=[(self.tr("keywords.text_files_label"), "*.txt"), (self.tr("cars.json_files_label"), "*.json"), (self.tr("cars.all_files_label"), "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Определяем формат файла
            parts = []
            if file_path.lower().endswith('.json'):
                data = json.loads(content)
                if isinstance(data, list):
                    parts = data
                else:
                    messagebox.showerror(self.tr("common.error"), self.tr("spareparts.msg_invalid_json_format"))
                    return
            else:
                # Текстовый файл - каждая запчасть на новой строке
                parts = content.strip().splitlines()

            parts = [p.strip() for p in parts if p and p.strip()]
            if not parts:
                messagebox.showwarning(self.tr("common.attention"), self.tr("spareparts.msg_empty_file"))
                return

            existing_lower = {p.lower() for p in self.spare_parts_list}
            added = 0
            for part_name in parts:
                if part_name.lower() not in existing_lower:
                    self.spare_parts_list.append(part_name)
                    existing_lower.add(part_name.lower())
                    added += 1

            self.save_spare_parts_file()
            messagebox.showinfo(self.tr("common.success"), self.tr("spareparts.msg_import_done", count=added))
            self.refresh_spare_parts_list()

        except json.JSONDecodeError:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_json_read_error"))
        except Exception as e:
            messagebox.showerror(self.tr("common.error"), self.tr("cars.msg_import_error", error=str(e)))

    # ===== ВКЛАДКА ЯЗЫКА =====

    def setup_language_tab(self):
        """Настройка вкладки выбора языка интерфейса"""
        main_frame = ctk.CTkFrame(self.language_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        ctk.CTkLabel(center_container, text=self.tr("settings.language_title"),
                    font=("Segoe UI", 16, "bold")).pack(pady=10)

        row = ctk.CTkFrame(center_container)
        row.pack(fill=tk.X, pady=10)
        ctk.CTkLabel(row, text=self.tr("settings.language_label"), width=120, anchor="w").pack(side=tk.LEFT, padx=5)

        self._language_codes_by_name = {name: code for code, name in SUPPORTED_LANGUAGES.items()}
        self.language_combo = ctk.CTkComboBox(row, width=250, fg_color="white", text_color="black",
                                               button_color="#0078d7", button_hover_color="#005a9e",
                                               values=list(SUPPORTED_LANGUAGES.values()), state="readonly")
        self.language_combo.pack(side=tk.LEFT, padx=5)
        self.language_combo.set(SUPPORTED_LANGUAGES.get(self.i18n.lang, SUPPORTED_LANGUAGES["ru"]))

        ctk.CTkButton(center_container, text=self.tr("settings.language_save"),
                     command=self.save_language_action, fg_color="green", hover_color="darkgreen").pack(pady=10)

        ctk.CTkLabel(center_container, text=self.tr("settings.language_restart_notice"),
                    text_color="#FF9800").pack(pady=(0, 10))

    def save_language_action(self):
        """Сохранить выбранный язык интерфейса и перезапустить приложение"""
        selected_name = self.language_combo.get()
        lang_code = self._language_codes_by_name.get(selected_name, "ru")

        settings = self.load_settings()
        settings['language'] = lang_code
        self.save_settings(settings)

        messagebox.showinfo(self.tr("common.success"), self.tr("settings.language_saved"))
        self.restart_application()

    def restart_application(self):
        """Перезапустить приложение текущим интерпретатором/exe"""
        self.root.destroy()
        if getattr(sys, 'frozen', False):
            # os.execv на Windows для onefile-сборки PyInstaller приводит к гонке
            # с очисткой временной папки _MEI бывшего процесса и падению с
            # "Can't find a usable init.tcl". Поэтому запускаем новый процесс
            # отдельно и завершаем текущий, не дожидаясь его.
            subprocess.Popen([sys.executable] + sys.argv[1:])
            os._exit(0)
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # ===== ВКЛАДКА РЕЗЕРВНОГО КОПИРОВАНИЯ =====

    def setup_backup_tab(self):
        """Настройка вкладки резервного копирования"""
        main_frame = ctk.CTkFrame(self.backup_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=20, padx=20, fill=tk.X)

        ctk.CTkLabel(center_container, text=self.tr("backup.title"),
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(10, 4), anchor="w")

        ctk.CTkLabel(center_container, text=self.tr("backup.description"),
                    font=ctk.CTkFont(size=12), text_color="gray", justify="left",
                    wraplength=460).pack(pady=(0, 16), anchor="w")

        settings = self.load_settings()

        # Папка для бэкапов
        folder_row = ctk.CTkFrame(center_container, fg_color="transparent")
        folder_row.pack(fill=tk.X, pady=6)
        ctk.CTkLabel(folder_row, text=self.tr("backup.folder_label"), width=150, anchor="w").pack(side=tk.LEFT)
        self.backup_folder_var = tk.StringVar(value=settings.get('backup_folder', ''))
        ctk.CTkEntry(folder_row, textvariable=self.backup_folder_var, width=260,
                    state="readonly").pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(folder_row, text=self.tr("backup.browse"), width=100,
                     command=self._browse_backup_folder).pack(side=tk.LEFT, padx=5)

        # Автоматический бэкап
        auto_row = ctk.CTkFrame(center_container, fg_color="transparent")
        auto_row.pack(fill=tk.X, pady=6)
        self.backup_auto_var = tk.BooleanVar(value=settings.get('backup_auto', True))
        ctk.CTkCheckBox(auto_row, text=self.tr("backup.auto_label"),
                        variable=self.backup_auto_var,
                        command=self._on_backup_auto_changed).pack(side=tk.LEFT)

        # Статус последнего бэкапа
        self._backup_status_label = ctk.CTkLabel(center_container, text="",
                                                  font=ctk.CTkFont(size=12), text_color="gray", anchor="w")
        self._backup_status_label.pack(fill=tk.X, pady=(10, 16), anchor="w")
        self._refresh_backup_status_label()

        # Кнопки
        btn_row = ctk.CTkFrame(center_container, fg_color="transparent")
        btn_row.pack(fill=tk.X, pady=(0, 10))
        ctk.CTkButton(btn_row, text=self.tr("backup.now"), fg_color="green", hover_color="darkgreen",
                     command=lambda: self._do_backup_now(silent=False)).pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(btn_row, text=self.tr("backup.restore"), fg_color="#c62828", hover_color="#b71c1c",
                     command=self._do_restore_backup).pack(side=tk.LEFT)

    def _browse_backup_folder(self):
        """Выбрать папку для бэкапов (обычно -- синхронизируемая папка Google
        Диска / Яндекс.Диска, чтобы копия автоматически оказалась в облаке)."""
        folder = filedialog.askdirectory(parent=self.root, title=self.tr("backup.folder_label"))
        if not folder:
            return
        self.backup_folder_var.set(folder)
        settings = self.load_settings()
        settings['backup_folder'] = folder
        self.save_settings(settings)
        self._refresh_backup_status_label()

    def _on_backup_auto_changed(self):
        settings = self.load_settings()
        settings['backup_auto'] = self.backup_auto_var.get()
        self.save_settings(settings)

    def _refresh_backup_status_label(self):
        if not hasattr(self, "_backup_status_label"):
            return
        settings = self.load_settings()
        last = settings.get('backup_last')
        count = len(backup_module.list_backups(LOCAL_BACKUP_DIR))

        if last:
            try:
                last_str = datetime.fromisoformat(last).strftime('%d.%m.%Y %H:%M')
            except Exception:
                last_str = last
        else:
            last_str = self.tr("backup.last_never")

        self._backup_status_label.configure(text=self.tr("backup.status", last=last_str, count=count))

    def _do_backup_now(self, silent: bool = False, include_cloud: bool = True) -> bool:
        """
        Создать бэкап немедленно.
        Всегда пишет копию в LOCAL_BACKUP_DIR (папка "Backup" рядом с
        программой) -- это работает без какой-либо настройки со стороны
        пользователя и не зависит от галочки "автобэкап". Дополнительно,
        если в настройках указана облачная папка (Google Диск/Яндекс.Диск)
        и include_cloud=True, пишет копию и туда.

        silent=True -- для фоновой автоматической проверки, без всплывающих
        окон при успехе/ошибке. include_cloud=False -- используется фоновой
        проверкой, когда галочка "копировать в облако" выключена (локальный
        бэкап при этом всё равно продолжает делаться).
        """
        settings = self.load_settings()
        cloud_folder = settings.get('backup_folder', '').strip()

        targets = [LOCAL_BACKUP_DIR]
        if include_cloud and cloud_folder and cloud_folder != LOCAL_BACKUP_DIR:
            targets.append(cloud_folder)

        made_any = False
        local_ok = False
        errors = []
        for folder in targets:
            try:
                backup_module.create_backup(self.db, folder, SETTINGS_FILE, SPARE_PARTS_FILE)
                backup_module.rotate_backups(folder)
                made_any = True
                if folder == LOCAL_BACKUP_DIR:
                    local_ok = True
            except Exception as e:
                errors.append(f"{folder}: {e}")

        if made_any:
            settings = self.load_settings()
            settings['backup_last'] = datetime.now().isoformat()
            self.save_settings(settings)
        self._refresh_backup_status_label()

        if not silent:
            if errors and not local_ok:
                messagebox.showerror(self.tr("common.error"),
                                    self.tr("backup.now_error", error="\n".join(errors)), parent=self.root)
            elif errors:
                # Локальный бэкап (папка "Backup" рядом с программой) удался,
                # упала только облачная папка -- это не критично, показываем
                # предупреждение, а не ошибку, чтобы не пугать пользователя
                # ложным "не удалось" при фактически сделанной копии.
                messagebox.showwarning(self.tr("common.attention"),
                                      self.tr("backup.now_partial", error="\n".join(errors)), parent=self.root)
            elif made_any:
                messagebox.showinfo(self.tr("common.success"), self.tr("backup.now_success"), parent=self.root)

        return made_any

    def _do_restore_backup(self):
        """Восстановить БД и настройки из выбранного .zip-бэкапа."""
        settings = self.load_settings()
        folder = settings.get('backup_folder') or LOCAL_BACKUP_DIR

        path = filedialog.askopenfilename(
            parent=self.root,
            title=self.tr("backup.restore"),
            initialdir=folder,
            filetypes=[("ZIP", "*.zip")]
        )
        if not path:
            return

        if not messagebox.askyesno(self.tr("common.attention"), self.tr("backup.restore_confirm_body"), parent=self.root):
            return

        try:
            backup_module.restore_backup(self.db, path, SETTINGS_FILE, SPARE_PARTS_FILE)
        except Exception as e:
            messagebox.showerror(self.tr("common.error"), self.tr("backup.restore_error", error=str(e)), parent=self.root)
            return

        messagebox.showinfo(self.tr("common.success"), self.tr("backup.restore_success"), parent=self.root)
        self.restart_application()

    def setup_about_tab(self):
        """Настройка вкладки "О программе" """
        main_frame = ctk.CTkFrame(self.about_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=20, padx=20)

        try:
            from updater import APP_VERSION as _app_version
        except Exception:
            _app_version = "?"

        ctk.CTkLabel(center_container, text=self.tr("about.title"),
                    font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(10, 4))

        ctk.CTkLabel(center_container, text=self.tr("about.version", version=_app_version),
                    font=ctk.CTkFont(size=13), text_color="gray").pack(pady=(0, 16))

        ctk.CTkLabel(center_container, text=self.tr("about.description"),
                    font=ctk.CTkFont(size=13), justify="left", wraplength=420).pack(pady=(0, 20))

        ctk.CTkLabel(center_container, text=self.tr("about.contacts_title"),
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 8))

        # Клик по Telegram - открыть чат
        telegram_label = ctk.CTkLabel(center_container, text=self.tr("about.telegram"),
                                      font=ctk.CTkFont(size=13, underline=True), text_color="#1e88e5", cursor="hand2")
        telegram_label.pack(pady=(0, 2))
        telegram_label.bind("<Button-1>", lambda e: webbrowser.open("https://t.me/R_AM_Z"))

        ctk.CTkLabel(center_container, text=self.tr("about.email"),
                    font=ctk.CTkFont(size=13)).pack(pady=(0, 10))

    # ===== ВКЛАДКА РАСХОДОВ =====

    def setup_expenses_tab(self):
        """Настройка вкладки расходов"""
        # Используем прокручиваемый фрейм для поддержки маленьких экранов
        # (без этого на ноутбуках с низким разрешением кнопка "Удалить
        # выбранную запись" внизу уходит за пределы экрана)
        main_frame = ctk.CTkScrollableFrame(self.expenses_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Форма ввода - все строки выровнены по сетке (одинаковая ширина колонки label
        # и одинаковый маленький размер полей), чтобы визуально быть на одном уровне
        form_frame = ctk.CTkFrame(center_container, fg_color="transparent")
        form_frame.pack(pady=10)

        FIELD_WIDTH = 250

        # Переключатель Расход/Доход
        ctk.CTkLabel(form_frame, text=self.tr("finances.type_label"), width=150, anchor="e").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        switch_row = ctk.CTkFrame(form_frame, fg_color="transparent")
        switch_row.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        self.expense_type_label = ctk.CTkLabel(switch_row, text=self.tr("finances.expense_label"), width=60, anchor="e",
                                                font=("Segoe UI", 14, "bold"), text_color="#d32f2f")
        self.expense_type_label.pack(side=tk.LEFT, padx=5)

        self.is_income_var = tk.BooleanVar(value=False)
        self.income_switch = ctk.CTkSwitch(switch_row, text="", variable=self.is_income_var,
                                           command=self.on_income_switch_changed,
                                           width=50, height=26,
                                           progress_color="#4caf50", button_color="white",
                                           fg_color="#d32f2f", button_hover_color="#f0f0f0")
        self.income_switch.pack(side=tk.LEFT, padx=10)

        self.income_type_label = ctk.CTkLabel(switch_row, text=self.tr("finances.income_label"), width=60, anchor="w",
                                               font=("Segoe UI", 14), text_color="gray")
        self.income_type_label.pack(side=tk.LEFT, padx=5)

        # Категория
        ctk.CTkLabel(form_frame, text=self.tr("finances.category_label"), width=150, anchor="e").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.expense_category_combo = ctk.CTkComboBox(form_frame, width=FIELD_WIDTH,
                                                    values=[self.tr("finances.category_rent"), self.tr("finances.category_taxes"),
                                                            self.tr("finances.category_utilities"), self.tr("finances.category_parts_purchase"),
                                                            self.tr("finances.category_tools"), self.tr("finances.category_ads"),
                                                            self.tr("finances.category_other"), self.tr("finances.income_label")],
                                                    fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.expense_category_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        self.expense_category_combo.set(self.tr("finances.category_rent"))

        # Описание
        ctk.CTkLabel(form_frame, text=self.tr("finances.description_label"), width=150, anchor="e").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.expense_desc_entry = ctk.CTkEntry(form_frame, width=FIELD_WIDTH, fg_color="white", text_color="black")
        self.expense_desc_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        # Сумма
        ctk.CTkLabel(form_frame, text=self.tr("finances.amount_label"), width=150, anchor="e").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        self.expense_amount_entry = ctk.CTkEntry(form_frame, width=FIELD_WIDTH, fg_color="white", text_color="black")
        self.expense_amount_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")

        # Кнопка добавления
        self.add_expense_btn = ctk.CTkButton(center_container, text=self.tr("finances.add_expense_btn"),
                   command=self.add_expense, width=400, height=50, fg_color="#d32f2f", hover_color="#b71c1c")
        self.add_expense_btn.pack(anchor=tk.CENTER, pady=20)

        # История расходов и доходов
        history_frame = ctk.CTkFrame(center_container)
        history_frame.pack(pady=10)

        columns = ("id", "type", "category", "desc", "amount", "date")
        self.expenses_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=12)
        self.expenses_tree.heading("id", text="ID")
        self.expenses_tree.heading("type", text=self.tr("finances.col_type"))
        self.expenses_tree.heading("category", text=self.tr("finances.col_category"))
        self.expenses_tree.heading("desc", text=self.tr("finances.col_description"))
        self.expenses_tree.heading("amount", text=self.tr("finances.col_amount"))
        self.expenses_tree.heading("date", text=self.tr("bookings.col_date"))

        self.expenses_tree.column("id", width=50, anchor=tk.CENTER)
        self.expenses_tree.column("type", width=90, anchor=tk.CENTER)
        self.expenses_tree.column("category", width=200, anchor=tk.W)
        self.expenses_tree.column("desc", width=380, anchor=tk.W)
        self.expenses_tree.column("amount", width=130, anchor=tk.CENTER)
        self.expenses_tree.column("date", width=110, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=self.expenses_tree.yview)
        self.expenses_tree.configure(yscrollcommand=scrollbar.set)

        # Tooltip с полным текстом при наведении, если описание/категория обрезаны
        TreeviewTooltip(self.expenses_tree, columns=["desc", "category"])

        # Настройка цветов для строк
        self.expenses_tree.tag_configure('oddrow', background='#ffffff')
        self.expenses_tree.tag_configure('evenrow', background='#f0f0f0')
        self.expenses_tree.tag_configure('income', background='#e8f5e9')
        self.expenses_tree.tag_configure('expense', background='#ffebee')

        self.expenses_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        self.delete_expense_btn = ctk.CTkButton(center_container, text=self.tr("finances.delete_selected_btn"),
                   command=self.delete_expense, width=400, fg_color="red", hover_color="#555555")
        self.delete_expense_btn.pack(anchor=tk.CENTER, pady=10)

    def on_income_switch_changed(self):
        """Обработчик переключения расход/доход"""
        is_income = self.is_income_var.get()
        if is_income:
            self.expense_type_label.configure(text_color="gray", font=("Segoe UI", 14))
            self.income_type_label.configure(text_color="#4caf50", font=("Segoe UI", 14, "bold"))
            self.add_expense_btn.configure(text=self.tr("finances.add_income_btn"), fg_color="#4caf50", hover_color="#388e3c")
        else:
            self.expense_type_label.configure(text_color="#d32f2f", font=("Segoe UI", 14, "bold"))
            self.income_type_label.configure(text_color="gray", font=("Segoe UI", 14))
            self.add_expense_btn.configure(text=self.tr("finances.add_expense_btn"), fg_color="#d32f2f", hover_color="#b71c1c")

    def add_expense(self):
        """Добавить расход или доход"""
        category = self.expense_category_combo.get().strip()
        if not category:
            messagebox.showwarning(self.tr("common.attention"), self.tr("finances.msg_select_category"))
            return

        description = self.expense_desc_entry.get().strip()
        is_income = self.is_income_var.get()
        if not description:
            messagebox.showwarning(self.tr("common.attention"),
                                    self.tr("finances.msg_enter_income_desc") if is_income else self.tr("finances.msg_enter_expense_desc"))
            return

        try:
            amount = float(self.expense_amount_entry.get().replace(',', '.'))
            if amount <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(self.tr("common.attention"), self.tr("finances.msg_invalid_amount"))
            return

        self._confirm_expense_date_and_save(category, description, amount, is_income)

    def _confirm_expense_date_and_save(self, category, description, amount, is_income):
        """Показывает диалог подтверждения даты перед сохранением записи.
        Поле в календаре может «зависнуть» на старой дате, если программа
        работает без перезапуска не первый день, поэтому по умолчанию
        предлагаем реальную сегодняшнюю дату, а не значение из формы."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(self.tr("finances.confirm_date_title"))
        dialog.geometry("360x180")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(dialog, text=self.tr("finances.confirm_date_label"),
                     font=("Segoe UI", 13), wraplength=320).pack(pady=(20, 10))

        confirm_date_entry = DateEntry(dialog, width=20, date_pattern='dd.mm.yyyy', locale='ru_RU')
        confirm_date_entry.set_date(datetime.now().date())
        confirm_date_entry.pack(pady=5)

        def on_confirm():
            expense_date = confirm_date_entry.get_date().strftime('%Y-%m-%d')
            self.db.add_expense(description, amount, expense_date, category, is_income)
            dialog.destroy()

            messagebox.showinfo(self.tr("common.success"),
                                 self.tr("finances.msg_income_added") if is_income else self.tr("finances.msg_expense_added"))
            self.expense_desc_entry.delete(0, tk.END)
            self.expense_amount_entry.delete(0, tk.END)
            self.refresh_expenses()

        def on_cancel():
            dialog.destroy()

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(pady=15)
        ctk.CTkButton(btn_row, text=self.tr("finances.confirm_date_btn"), command=on_confirm,
                      fg_color="#4caf50", hover_color="#388e3c", width=130).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_row, text=self.tr("common.cancel"), command=on_cancel,
                      fg_color="gray", width=130).pack(side=tk.LEFT, padx=10)

    def refresh_expenses(self):
        """Обновить список расходов и доходов"""
        for item in self.expenses_tree.get_children():
            self.expenses_tree.delete(item)

        row_index = 0
        for row in self.db.get_recent_expenses():
            expense_id, desc, amount, expense_date, category, is_income = row
            amount = float(amount)  # MariaDB возвращает Decimal
            # MariaDB возвращает даты как объекты date
            if isinstance(expense_date, str):
                display_date = datetime.strptime(expense_date, '%Y-%m-%d').strftime('%d.%m.%Y')
            else:
                display_date = expense_date.strftime('%d.%m.%Y')

            # Определяем тип записи и тег
            type_text = self.tr("finances.income_label") if is_income else self.tr("finances.expense_label")
            row_tag = 'income' if is_income else 'expense'

            self.expenses_tree.insert("", tk.END, values=(
                expense_id,
                type_text,
                category,
                desc,
                self.format_currency(amount),
                display_date
            ), tags=(row_tag,))

            row_index += 1

    def delete_expense(self):
        """Удалить расход или доход"""
        selected = self.expenses_tree.selection()
        if not selected:
            messagebox.showwarning(self.tr("common.attention"), self.tr("finances.msg_select_to_delete"))
            return

        item = self.expenses_tree.item(selected[0])
        expense_id = item['values'][0]
        type_text = item['values'][1]
        description = item['values'][3]

        if messagebox.askyesno(self.tr("common.confirm"), self.tr("finances.msg_confirm_delete", type=type_text.lower(), name=description)):
            self.db.delete_expense(expense_id)
            messagebox.showinfo(self.tr("common.success"), self.tr("finances.msg_deleted", type=type_text))
            self.refresh_expenses()

    # ===== ВКЛАДКА СТАТИСТИКИ =====

    def _setup_tree_sorting(self, tree, rows_attr, key_funcs, redraw_func):
        """Делает заголовки Treeview кликабельными для сортировки (по возрастанию/убыванию).
        rows_attr — имя атрибута self со списком строк-кортежей (сырые данные).
        key_funcs — {имя_колонки: функция ключа сортировки}.
        redraw_func — функция(rows), которая очищает и заново рисует дерево."""
        state = {"col": None, "reverse": False}

        def handler(col):
            rows = getattr(self, rows_attr)
            reverse = state["col"] == col and not state["reverse"]
            rows.sort(key=key_funcs[col], reverse=reverse)
            state["col"], state["reverse"] = col, reverse
            redraw_func(rows)

        for col, key_func in key_funcs.items():
            tree.heading(col, command=lambda c=col: handler(c))

    def setup_statistics_tab(self):
        """Настройка вкладки статистики: марки авто, топ клиентов, популярные работы, динамика по месяцам"""
        main_frame = ctk.CTkScrollableFrame(self.statistics_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Выбор периода
        period_frame = ctk.CTkFrame(main_frame)
        period_frame.pack(fill=tk.X, padx=10, pady=10)
        ctk.CTkLabel(
            period_frame,
            text=self.tr("statistics.title_period"),
            font=("Segoe UI", 20, "bold"),
            anchor="center"
        ).pack(fill=tk.X, pady=(0, 10))

        dates_frame = ctk.CTkFrame(period_frame)
        dates_frame.pack()

        ctk.CTkLabel(dates_frame, text=self.tr("statistics.date_from_label")).pack(side=tk.LEFT, padx=5)
        self.stats_date_from = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy', locale='ru_RU')
        self.stats_date_from.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(dates_frame, text=self.tr("statistics.date_to_label")).pack(side=tk.LEFT, padx=15)
        self.stats_date_to = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy', locale='ru_RU')
        self.stats_date_to.pack(side=tk.LEFT, padx=5)

        # Без пароля статистика только за сегодня; другие даты открываются паролем для отчётов
        self.add_period_lock("statistics", dates_frame, (self.stats_date_from, self.stats_date_to),
                             lambda: self.generate_statistics(show_empty_message=False))

        ctk.CTkButton(dates_frame, text=self.tr("statistics.generate_btn"),
                      command=self.generate_statistics).pack(side=tk.LEFT, padx=20)

        self.stats_summary_label = ctk.CTkLabel(period_frame, text="", font=("Segoe UI", 12, "bold"),
                                                  text_color=("gray20", "gray80"))
        self.stats_summary_label.pack(fill=tk.X, pady=(12, 0))

        # --- Секция: марки авто ---
        brands_frame = ctk.CTkFrame(main_frame)
        brands_frame.pack(fill=tk.X, padx=10, pady=10)
        ctk.CTkLabel(brands_frame, text="🚗  " + self.tr("statistics.brands_title"),
                     font=("Segoe UI", 16, "bold")).pack(fill=tk.X, padx=10, pady=(10, 8))

        brand_table = ctk.CTkFrame(brands_frame, fg_color="transparent")
        brand_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        brand_columns = ("brand", "visits", "cars", "total", "avg")
        self.brand_stats_tree = ttk.Treeview(brand_table, columns=brand_columns, show="headings", height=10)
        self.brand_stats_tree.heading("brand", text=self.tr("statistics.col_brand"))
        self.brand_stats_tree.heading("visits", text=self.tr("statistics.col_visit_count"))
        self.brand_stats_tree.heading("cars", text=self.tr("statistics.col_car_count"))
        self.brand_stats_tree.heading("total", text=self.tr("statistics.col_total_amount"))
        self.brand_stats_tree.heading("avg", text=self.tr("statistics.col_avg_check"))
        self.brand_stats_tree.column("brand", width=220, anchor=tk.W)
        self.brand_stats_tree.column("visits", width=100, anchor=tk.CENTER)
        self.brand_stats_tree.column("cars", width=100, anchor=tk.CENTER)
        self.brand_stats_tree.column("total", width=150, anchor=tk.CENTER)
        self.brand_stats_tree.column("avg", width=150, anchor=tk.CENTER)
        brand_scroll = ttk.Scrollbar(brand_table, orient=tk.VERTICAL, command=self.brand_stats_tree.yview)
        self.brand_stats_tree.configure(yscrollcommand=brand_scroll.set)
        self.brand_stats_tree.tag_configure('oddrow', background='#ffffff')
        self.brand_stats_tree.tag_configure('evenrow', background='#f0f0f0')
        self.brand_stats_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        brand_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._stats_brand_rows = []

        def redraw_brands(rows):
            for item in self.brand_stats_tree.get_children():
                self.brand_stats_tree.delete(item)
            for i, (brand, visits, cars, total) in enumerate(rows):
                avg = total / visits if visits else 0
                tag = 'oddrow' if i % 2 == 0 else 'evenrow'
                self.brand_stats_tree.insert("", tk.END, values=(
                    brand, visits, cars, self.format_currency(total), self.format_currency(avg)
                ), tags=(tag,))

        self._redraw_stats_brands = redraw_brands
        self._setup_tree_sorting(self.brand_stats_tree, "_stats_brand_rows", {
            "brand": lambda r: r[0].lower(),
            "visits": lambda r: r[1],
            "cars": lambda r: r[2],
            "total": lambda r: r[3],
            "avg": lambda r: (r[3] / r[1] if r[1] else 0),
        }, redraw_brands)

        # --- Секция: топ клиентов ---
        clients_frame = ctk.CTkFrame(main_frame)
        clients_frame.pack(fill=tk.X, padx=10, pady=10)
        ctk.CTkLabel(clients_frame, text="👤  " + self.tr("statistics.clients_title"),
                     font=("Segoe UI", 16, "bold")).pack(fill=tk.X, padx=10, pady=(10, 8))

        clients_table = ctk.CTkFrame(clients_frame, fg_color="transparent")
        clients_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        client_columns = ("client", "phone", "visits", "total", "avg")
        self.client_stats_tree = ttk.Treeview(clients_table, columns=client_columns, show="headings", height=10)
        self.client_stats_tree.heading("client", text=self.tr("statistics.col_client"))
        self.client_stats_tree.heading("phone", text=self.tr("statistics.col_phone"))
        self.client_stats_tree.heading("visits", text=self.tr("statistics.col_visit_count"))
        self.client_stats_tree.heading("total", text=self.tr("statistics.col_total_amount"))
        self.client_stats_tree.heading("avg", text=self.tr("statistics.col_avg_check"))
        self.client_stats_tree.column("client", width=200, anchor=tk.W)
        self.client_stats_tree.column("phone", width=140, anchor=tk.CENTER)
        self.client_stats_tree.column("visits", width=100, anchor=tk.CENTER)
        self.client_stats_tree.column("total", width=150, anchor=tk.CENTER)
        self.client_stats_tree.column("avg", width=150, anchor=tk.CENTER)
        client_scroll = ttk.Scrollbar(clients_table, orient=tk.VERTICAL, command=self.client_stats_tree.yview)
        self.client_stats_tree.configure(yscrollcommand=client_scroll.set)
        self.client_stats_tree.tag_configure('oddrow', background='#ffffff')
        self.client_stats_tree.tag_configure('evenrow', background='#f0f0f0')
        self.client_stats_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        client_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._stats_client_rows = []

        def redraw_clients(rows):
            for item in self.client_stats_tree.get_children():
                self.client_stats_tree.delete(item)
            for i, (name, phone, visits, total) in enumerate(rows):
                avg = total / visits if visits else 0
                tag = 'oddrow' if i % 2 == 0 else 'evenrow'
                self.client_stats_tree.insert("", tk.END, values=(
                    name or "-", phone or "-", visits, self.format_currency(total), self.format_currency(avg)
                ), tags=(tag,))

        self._redraw_stats_clients = redraw_clients
        self._setup_tree_sorting(self.client_stats_tree, "_stats_client_rows", {
            "client": lambda r: (r[0] or "").lower(),
            "phone": lambda r: (r[1] or ""),
            "visits": lambda r: r[2],
            "total": lambda r: r[3],
            "avg": lambda r: (r[3] / r[2] if r[2] else 0),
        }, redraw_clients)

        # --- Секция: популярные виды работ ---
        works_frame = ctk.CTkFrame(main_frame)
        works_frame.pack(fill=tk.X, padx=10, pady=10)
        ctk.CTkLabel(works_frame, text="📋  " + self.tr("statistics.works_title"),
                     font=("Segoe UI", 16, "bold")).pack(fill=tk.X, padx=10, pady=(10, 8))

        works_table = ctk.CTkFrame(works_frame, fg_color="transparent")
        works_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        work_columns = ("work", "count", "total", "avg")
        self.work_stats_tree = ttk.Treeview(works_table, columns=work_columns, show="headings", height=10)
        self.work_stats_tree.heading("work", text=self.tr("statistics.col_work_name"))
        self.work_stats_tree.heading("count", text=self.tr("statistics.col_count"))
        self.work_stats_tree.heading("total", text=self.tr("statistics.col_total_amount"))
        self.work_stats_tree.heading("avg", text=self.tr("statistics.col_avg_check"))
        self.work_stats_tree.column("work", width=300, anchor=tk.W)
        self.work_stats_tree.column("count", width=120, anchor=tk.CENTER)
        self.work_stats_tree.column("total", width=150, anchor=tk.CENTER)
        self.work_stats_tree.column("avg", width=150, anchor=tk.CENTER)
        work_scroll = ttk.Scrollbar(works_table, orient=tk.VERTICAL, command=self.work_stats_tree.yview)
        self.work_stats_tree.configure(yscrollcommand=work_scroll.set)
        self.work_stats_tree.tag_configure('oddrow', background='#ffffff')
        self.work_stats_tree.tag_configure('evenrow', background='#f0f0f0')
        self.work_stats_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        work_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._stats_work_rows = []

        def redraw_works(rows):
            for item in self.work_stats_tree.get_children():
                self.work_stats_tree.delete(item)
            for i, (name, count, total) in enumerate(rows):
                avg = total / count if count else 0
                tag = 'oddrow' if i % 2 == 0 else 'evenrow'
                self.work_stats_tree.insert("", tk.END, values=(
                    name, count, self.format_currency(total), self.format_currency(avg)
                ), tags=(tag,))

        self._redraw_stats_works = redraw_works
        self._setup_tree_sorting(self.work_stats_tree, "_stats_work_rows", {
            "work": lambda r: r[0].lower(),
            "count": lambda r: r[1],
            "total": lambda r: r[2],
            "avg": lambda r: (r[2] / r[1] if r[1] else 0),
        }, redraw_works)

        # --- Секция: динамика по месяцам ---
        monthly_frame = ctk.CTkFrame(main_frame)
        monthly_frame.pack(fill=tk.X, padx=10, pady=10)
        ctk.CTkLabel(monthly_frame, text="📈  " + self.tr("statistics.monthly_title"),
                     font=("Segoe UI", 16, "bold")).pack(fill=tk.X, padx=10, pady=(10, 8))

        monthly_table = ctk.CTkFrame(monthly_frame, fg_color="transparent")
        monthly_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        monthly_columns = ("month", "visits", "total", "avg")
        self.monthly_stats_tree = ttk.Treeview(monthly_table, columns=monthly_columns, show="headings", height=8)
        self.monthly_stats_tree.heading("month", text=self.tr("statistics.col_month"))
        self.monthly_stats_tree.heading("visits", text=self.tr("statistics.col_visit_count"))
        self.monthly_stats_tree.heading("total", text=self.tr("statistics.col_total_amount"))
        self.monthly_stats_tree.heading("avg", text=self.tr("statistics.col_avg_check"))
        self.monthly_stats_tree.column("month", width=150, anchor=tk.CENTER)
        self.monthly_stats_tree.column("visits", width=120, anchor=tk.CENTER)
        self.monthly_stats_tree.column("total", width=150, anchor=tk.CENTER)
        self.monthly_stats_tree.column("avg", width=150, anchor=tk.CENTER)
        monthly_scroll = ttk.Scrollbar(monthly_table, orient=tk.VERTICAL, command=self.monthly_stats_tree.yview)
        self.monthly_stats_tree.configure(yscrollcommand=monthly_scroll.set)
        self.monthly_stats_tree.tag_configure('oddrow', background='#ffffff')
        self.monthly_stats_tree.tag_configure('evenrow', background='#f0f0f0')
        self.monthly_stats_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        monthly_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._stats_monthly_rows = []

        def redraw_monthly(rows):
            for item in self.monthly_stats_tree.get_children():
                self.monthly_stats_tree.delete(item)
            for i, (ym, visits, total) in enumerate(rows):
                avg = total / visits if visits else 0
                try:
                    month_label = datetime.strptime(ym, '%Y-%m').strftime('%m.%Y')
                except (TypeError, ValueError):
                    month_label = ym
                tag = 'oddrow' if i % 2 == 0 else 'evenrow'
                self.monthly_stats_tree.insert("", tk.END, values=(
                    month_label, visits, self.format_currency(total), self.format_currency(avg)
                ), tags=(tag,))

        self._redraw_stats_monthly = redraw_monthly
        self._setup_tree_sorting(self.monthly_stats_tree, "_stats_monthly_rows", {
            "month": lambda r: r[0],
            "visits": lambda r: r[1],
            "total": lambda r: r[2],
            "avg": lambda r: (r[2] / r[1] if r[1] else 0),
        }, redraw_monthly)

    def generate_statistics(self, show_empty_message=True):
        """Сформировать статистику за выбранный период"""
        if not self.is_period_unlocked("statistics"):
            # Без пароля - только сегодня
            self.lock_period("statistics")
        date_from = self.stats_date_from.get_date().strftime('%Y-%m-%d')
        date_to = self.stats_date_to.get_date().strftime('%Y-%m-%d')

        if date_from > date_to:
            messagebox.showwarning(self.tr("common.attention"), self.tr("statistics.msg_date_range_invalid"))
            return

        # Марки авто
        brand_rows = self.db.get_car_brand_stats(date_from, date_to)
        self._stats_brand_rows = [(brand, int(visits), int(cars), float(total))
                                   for brand, visits, cars, total in brand_rows]
        self._redraw_stats_brands(self._stats_brand_rows)

        # Топ клиентов
        client_rows = self.db.get_top_clients_by_period(date_from, date_to)
        self._stats_client_rows = [(name, phone, int(visits), float(total))
                                    for name, phone, visits, total in client_rows]
        self._redraw_stats_clients(self._stats_client_rows)

        # Популярные виды работ (разбиваем каждую работу на отдельные позиции)
        work_stats = {}
        for work_id, description, amount, items_json in self.db.get_works_for_period(date_from, date_to):
            for name, price in self.get_work_line_items(work_id, description, amount, items_json):
                key = name.strip()
                if not key:
                    continue
                entry = work_stats.setdefault(key, {"count": 0, "total": 0.0})
                entry["count"] += 1
                entry["total"] += price
        self._stats_work_rows = sorted(
            [(name, data["count"], data["total"]) for name, data in work_stats.items()],
            key=lambda r: r[1], reverse=True
        )
        self._redraw_stats_works(self._stats_work_rows)

        # Динамика по месяцам
        monthly_rows = self.db.get_monthly_stats(date_from, date_to)
        self._stats_monthly_rows = [(ym, int(visits), float(total)) for ym, visits, total in monthly_rows]
        self._redraw_stats_monthly(self._stats_monthly_rows)

        # Сводка
        total_visits = sum(r[1] for r in self._stats_brand_rows)
        total_clients = len(self._stats_client_rows)
        total_brands = len(self._stats_brand_rows)
        self.stats_summary_label.configure(text=self.tr(
            "statistics.summary_label", visits=total_visits, brands=total_brands, clients=total_clients
        ))

        if show_empty_message and total_visits == 0:
            messagebox.showinfo(self.tr("common.info"), self.tr("statistics.msg_no_data"))

    def save_booking_to_pdf(self, booking, works):
        """Сохранить все работы записи в PDF файл (формат А4)"""
        if not works:
            messagebox.showwarning("Внимание", "Нет выполненных работ для сохранения!")
            return

        # Загружаем настройки компании
        settings = self.load_settings()
        company_name = settings.get('company_name', 'Автосервис')
        company_address = settings.get('company_address', '')
        company_phone = settings.get('company_phone', '')

        # Собираем информацию о клиенте из записи
        client_name = booking.get('full_name') or ''
        client_phone = booking.get('phone') or ''
        car_info = booking.get('car_info') or ''

        # Формируем имя файла
        booking_date = booking.get('booking_date')
        if hasattr(booking_date, 'strftime'):
            date_str = booking_date.strftime('%Y%m%d')
            display_date = booking_date.strftime('%d.%m.%Y')
        else:
            date_str = str(booking_date).replace('-', '')
            display_date = str(booking_date)

        default_filename = f"наряд_{date_str}_{client_name or 'клиент'}.pdf"
        default_filename = "".join(c for c in default_filename if c.isalnum() or c in "._- ")

        file_path = filedialog.asksaveasfilename(
            title="Сохранить лист наряд как PDF",
            initialfile=default_filename,
            defaultextension=".pdf",
            filetypes=[("PDF файлы", "*.pdf"), ("Все файлы", "*.*")]
        )

        if not file_path:
            return

        try:
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

            # Регистрируем шрифт Arial
            font_name = "Helvetica"
            font_name_bold = "Helvetica-Bold"
            try:
                font_path = "C:\\Windows\\Fonts\\arial.ttf"
                font_path_bold = "C:\\Windows\\Fonts\\arialbd.ttf"
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('Arial', font_path))
                    font_name = "Arial"
                if os.path.exists(font_path_bold):
                    pdfmetrics.registerFont(TTFont('ArialBold', font_path_bold))
                    font_name_bold = "ArialBold"
                else:
                    font_name_bold = font_name
            except:
                pass

            # Создаём документ A4
            doc = SimpleDocTemplate(
                file_path,
                pagesize=A4,
                leftMargin=40,
                rightMargin=40,
                topMargin=40,
                bottomMargin=40
            )

            width, height = A4
            content_width = width - 80  # 40 + 40 margins

            # Стили
            styles = getSampleStyleSheet()
            style_header = ParagraphStyle(
                'Header',
                parent=styles['Normal'],
                fontName=font_name_bold,
                fontSize=18,
                leading=22,
                alignment=TA_CENTER,
                spaceAfter=8
            )
            style_company = ParagraphStyle(
                'Company',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=10,
                alignment=TA_CENTER,
                textColor=colors.grey
            )
            style_normal = ParagraphStyle(
                'NormalText',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=10,
                leading=14
            )
            style_bold = ParagraphStyle(
                'BoldText',
                parent=styles['Normal'],
                fontName=font_name_bold,
                fontSize=10,
                leading=14
            )
            style_section = ParagraphStyle(
                'Section',
                parent=styles['Normal'],
                fontName=font_name_bold,
                fontSize=11,
                spaceBefore=10,
                spaceAfter=5
            )
            style_total = ParagraphStyle(
                'Total',
                parent=styles['Normal'],
                fontName=font_name_bold,
                fontSize=12,
                alignment=TA_RIGHT
            )

            elements = []

            # ═══════════════════════════════════════════════════════
            # ШАПКА: Название компании
            # ═══════════════════════════════════════════════════════
            elements.append(Paragraph(company_name, style_header))
            if company_address:
                elements.append(Paragraph(company_address, style_company))
            if company_phone:
                elements.append(Paragraph(f"Тел: {company_phone}", style_company))
            elements.append(Spacer(1, 15))

            # Линия
            line_table = Table([['']], colWidths=[content_width])
            line_table.setStyle(TableStyle([
                ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
            ]))
            elements.append(line_table)
            elements.append(Spacer(1, 10))

            # ═══════════════════════════════════════════════════════
            # ЗАГОЛОВОК: ЛИСТ НАРЯД
            # ═══════════════════════════════════════════════════════
            title_style = ParagraphStyle(
                'Title',
                parent=styles['Normal'],
                fontName=font_name_bold,
                fontSize=16,
                leading=20,
                alignment=TA_CENTER,
                spaceAfter=15
            )
            order_numbers = ", ".join(dict.fromkeys(str(w[14]) for w in works if w[14]))
            title_text = f"ЛИСТ НАРЯД № {order_numbers}" if order_numbers else "ЛИСТ НАРЯД"
            elements.append(Paragraph(title_text, title_style))

            # ═══════════════════════════════════════════════════════
            # ИНФОРМАЦИЯ О КЛИЕНТЕ И АВТОМОБИЛЕ
            # Одна колонка "label - значение" построчно — читается легче,
            # чем два поля в одной строке. Дата и мастер указаны здесь один
            # раз на весь документ, повторно в заголовках работ не дублируются.
            # ═══════════════════════════════════════════════════════
            master_names = ", ".join(dict.fromkeys(w[2] for w in works if w[2])) or "-"

            info_data = [
                [Paragraph("<b>Дата:</b>", style_normal), Paragraph(display_date, style_normal)],
                [Paragraph("<b>Клиент:</b>", style_normal), Paragraph(client_name or "-", style_normal)],
                [Paragraph("<b>Телефон:</b>", style_normal), Paragraph(client_phone or "-", style_normal)],
                [Paragraph("<b>Автомобиль:</b>", style_normal), Paragraph(car_info or "-", style_normal)],
                [Paragraph("<b>Мастер:</b>", style_normal), Paragraph(master_names, style_normal)],
            ]

            col_widths = [content_width * 0.2, content_width * 0.8]
            info_table = Table(info_data, colWidths=col_widths)
            info_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(info_table)

            # ═══════════════════════════════════════════════════════
            # РАБОТЫ
            # ═══════════════════════════════════════════════════════
            grand_total_works = 0
            grand_total_parts = 0

            # Цвета фона для наглядного разделения таблицы работ и таблицы
            # запчастей — у каждой свой оттенок (шапка + строка суммы).
            works_header_bg = colors.Color(0.80, 0.88, 0.98)
            works_subtotal_bg = colors.Color(0.91, 0.95, 0.99)
            parts_header_bg = colors.Color(0.99, 0.90, 0.78)
            parts_subtotal_bg = colors.Color(0.99, 0.95, 0.89)

            for work in works:
                work_id, _, _, description, amount, _, _, _, _, mileage, _, _, _, _, _, _ = work

                work_amount = float(amount or 0)
                grand_total_works += work_amount

                # Номер наряда и мастер уже указаны один раз в шапке документа
                # и в информационном блоке — здесь для каждой работы оставляем
                # только пробег, если он есть.
                if mileage:
                    mileage_table = Table(
                        [[Paragraph("<b>Пробег:</b>", style_normal), Paragraph(f"{mileage} км", style_normal)]],
                        colWidths=col_widths
                    )
                    mileage_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ]))
                    elements.append(mileage_table)
                    elements.append(Spacer(1, 6))

                # Таблица работ
                works_table_data = [[
                    Paragraph("<b>Наименование работ</b>", style_bold),
                    Paragraph("<b>Цена</b>", style_bold)
                ]]

                # Описание работ - каждая позиция отдельной строкой со своей ценой
                work_items = self.get_work_line_items(work_id, description, work_amount) if description else []
                if work_items:
                    for item_name, item_price in work_items:
                        works_table_data.append([
                            Paragraph(f"• {item_name}", style_normal),
                            Paragraph(self.format_currency(item_price), style_normal)
                        ])
                else:
                    works_table_data.append([
                        Paragraph("Работы не указаны", style_normal),
                        Paragraph("", style_normal)
                    ])

                # Строка "Сумма работ" — последняя строка той же таблицы, чтобы
                # рамка охватывала список работ и итог по ним как единый блок.
                works_table_data.append([
                    Paragraph("Сумма работ:", style_bold),
                    Paragraph(self.format_currency(work_amount), style_bold)
                ])

                works_table = Table(works_table_data, colWidths=[content_width * 0.75, content_width * 0.25])
                works_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('BACKGROUND', (0, 0), (-1, 0), works_header_bg),
                    ('BACKGROUND', (0, -1), (-1, -1), works_subtotal_bg),
                    ('LINEBELOW', (0, 0), (-1, 0), 0.75, colors.black),
                    ('LINEABOVE', (0, -1), (-1, -1), 0.75, colors.black),
                    ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
                ]))
                elements.append(works_table)
                elements.append(Spacer(1, 10))

                # Запчасти
                parts = self.db.get_parts_by_work_id(work_id)
                wh_prices = self.db.get_warehouse_prices_by_work_ids([work_id]) if parts else {}
                parts_total = 0

                if parts:
                    parts_table_data = [[
                        Paragraph("<b>Запчасти</b>", style_bold),
                        Paragraph("<b>Цена</b>", style_bold)
                    ]]

                    for part_name, part_price in parts:
                        part_price = float(part_price)
                        parts_total += part_price
                        # Оплаченная заранее: без пометки в названии, вместо "0 руб." - "оплачено ранее",
                        # настоящая цена (со склада) - зачёркнутой
                        original = self.prepaid_original_price(wh_prices, work_id, part_name)
                        shown_name, price_text, struck = self.part_row_values(part_name, part_price, original)
                        if struck:
                            price_text = f"<strike>{struck}</strike> {price_text}"
                        parts_table_data.append([
                            Paragraph(f"• {shown_name}", style_normal),
                            Paragraph(price_text, style_normal)
                        ])

                    # Строка "Сумма запчастей" — последняя строка той же таблицы,
                    # тем же приёмом, что и в таблице работ выше.
                    parts_table_data.append([
                        Paragraph("Сумма запчастей:", style_bold),
                        Paragraph(self.format_currency(parts_total), style_bold)
                    ])

                    parts_table = Table(parts_table_data, colWidths=[content_width * 0.75, content_width * 0.25])
                    parts_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ('BACKGROUND', (0, 0), (-1, 0), parts_header_bg),
                        ('BACKGROUND', (0, -1), (-1, -1), parts_subtotal_bg),
                        ('LINEBELOW', (0, 0), (-1, 0), 0.75, colors.black),
                        ('LINEABOVE', (0, -1), (-1, -1), 0.75, colors.black),
                        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
                    ]))
                    elements.append(parts_table)
                    elements.append(Spacer(1, 10))

                grand_total_parts += parts_total

            # ═══════════════════════════════════════════════════════
            # ИТОГО
            # Разбивка "Сумма работ" / "Сумма запчастей" уже показана прямо
            # под соответствующими таблицами выше, поэтому здесь остаётся
            # только общий итог к оплате.
            # ═══════════════════════════════════════════════════════
            grand_total = grand_total_works + grand_total_parts

            totals_data = [
                [Paragraph("<b>ИТОГО К ОПЛАТЕ:</b>", style_bold), Paragraph(f"<b>{self.format_currency(grand_total)}</b>", style_bold)]
            ]

            totals_table = Table(totals_data, colWidths=[content_width * 0.75, content_width * 0.25])
            totals_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LINEABOVE', (0, -1), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (0, -1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
            ]))
            elements.append(totals_table)

            # ═══════════════════════════════════════════════════════
            # ПОДПИСИ
            # ═══════════════════════════════════════════════════════
            elements.append(Spacer(1, 40))

            signatures_data = [[
                Paragraph("Исполнитель: _____________________", style_normal),
                Paragraph("Заказчик: _____________________", style_normal)
            ]]
            signatures_table = Table(signatures_data, colWidths=[content_width * 0.5, content_width * 0.5])
            signatures_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ]))
            elements.append(signatures_table)

            # Собираем документ
            doc.build(elements)

            messagebox.showinfo("Успех", f"Лист наряд сохранён в:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать PDF:\n{str(e)}")

    # --- Методы для вкладки Записи ---

    def setup_bookings_tab(self):
        """Настройка вкладки записей из Telegram"""
        # Верхняя панель с фильтрами
        filter_frame = ctk.CTkFrame(self.bookings_frame)
        filter_frame.pack(fill=tk.X, padx=10, pady=10)

        # Фильтр по статусу
        ctk.CTkLabel(filter_frame, text=self.tr("bookings.status_label")).pack(side=tk.LEFT, padx=5)
        self.bookings_status_var = tk.StringVar(value=self.tr("bookings.filter_all"))
        status_combo = ctk.CTkComboBox(filter_frame, variable=self.bookings_status_var,
                                        values=[self.tr("bookings.filter_all"), self.tr("bookings.filter_waiting"),
                                                self.tr("bookings.filter_in_progress"), self.tr("bookings.filter_completed"),
                                                self.tr("bookings.filter_cancelled")],
                                        command=lambda _: self.refresh_bookings(),  # фильтр применяется сразу при выборе
                                        width=140)
        status_combo.pack(side=tk.LEFT, padx=5)

        # Период: по умолчанию последний месяц (+ будущие и незавершённые за любую дату). Выбор запоминается
        self.bookings_periods = {self.tr("bookings.period_month"): 31, self.tr("bookings.period_3months"): 92,
                                 self.tr("bookings.period_year"): 366, self.tr("bookings.period_all"): None}
        saved_days = self.load_settings().get("bookings_period_days", 31)
        saved_label = next((k for k, v in self.bookings_periods.items() if v == saved_days),
                           self.tr("bookings.period_month"))
        self.bookings_period_var = tk.StringVar(value=saved_label)
        ctk.CTkComboBox(filter_frame, variable=self.bookings_period_var, values=list(self.bookings_periods),
                        command=self.on_bookings_period_change, width=120, state="readonly").pack(side=tk.LEFT, padx=5)

        # Кнопки
        ctk.CTkButton(filter_frame, text=self.tr("works.refresh"), command=self.refresh_bookings,
                     width=100).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(filter_frame, text=self.tr("bookings.today_only"), command=self.show_today_bookings,
                     width=120).pack(side=tk.LEFT, padx=5)

        # Поле поиска
        ctk.CTkLabel(filter_frame, text=self.tr("bookings.search_label")).pack(side=tk.LEFT, padx=(20, 0))
        self.bookings_search_entry = ctk.CTkEntry(filter_frame,
                                                   placeholder_text=self.tr("bookings.search_placeholder"),
                                                   placeholder_text_color="gray", width=180)
        self.bookings_search_entry.pack(side=tk.LEFT, padx=5)
        self.bookings_search_entry.bind("<Return>", lambda e: self.refresh_bookings())
        ctk.CTkButton(filter_frame, text="✕", command=self.clear_bookings_search,
                     width=30, fg_color="#c62828", hover_color="#b71c1c").pack(side=tk.LEFT, padx=2)
        ctk.CTkButton(filter_frame, text=self.tr("bookings.add_client"), command=self.show_add_booking_window,
                     fg_color="#1565c0", hover_color="#0d47a1", width=140).pack(side=tk.LEFT, padx=(15, 5))
        self.bookings_columns_btn = ctk.CTkButton(filter_frame, text="☰ " + self.tr("bookings.columns_btn"),
                                                  command=lambda: self.show_columns_menu_under("bookings_hidden_columns", self.bookings_columns_btn), width=110)
        self.bookings_columns_btn.pack(side=tk.LEFT, padx=5)

        # "Показано N из M" - под таблицей (часть записей может скрывать период)
        self.bookings_count_label = ctk.CTkLabel(self.bookings_frame, text="", font=("Arial", 12),
                                                 text_color="gray45", anchor="e")
        self.bookings_count_label.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 6))

        # Таблица записей
        table_frame = ctk.CTkFrame(self.bookings_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("id", "order_number", "date", "time", "name", "phone", "username", "car", "notes", "status")
        self.bookings_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        # Настройка колонок
        self.bookings_tree.heading("id", text="ID")
        self.bookings_tree.heading("order_number", text=self.tr("bookings.col_order_number"))
        self.bookings_tree.heading("date", text=self.tr("bookings.col_date") + " ▼",
                                   command=self.toggle_bookings_date_sort)
        self.bookings_sort_desc = True  # по умолчанию новые даты сверху
        self.bookings_tree.heading("time", text=self.tr("bookings.col_time"))
        self.bookings_tree.heading("name", text=self.tr("bookings.col_name"))
        self.bookings_tree.heading("phone", text=self.tr("bookings.col_phone"))
        self.bookings_tree.heading("username", text="Telegram")
        self.bookings_tree.heading("car", text=self.tr("bookings.col_car"))
        self.bookings_tree.heading("notes", text=self.tr("bookings.col_notes"))
        self.bookings_tree.heading("status", text=self.tr("bookings.col_status"))

        self.bookings_tree.column("id", width=0, stretch=False, minwidth=0)
        self.bookings_tree.column("order_number", width=80)
        self.bookings_tree.column("date", width=100)
        self.bookings_tree.column("time", width=70)
        self.bookings_tree.column("name", width=150)
        self.bookings_tree.column("phone", width=120)
        self.bookings_tree.column("username", width=120)
        self.bookings_tree.column("car", width=180)
        self.bookings_tree.column("notes", width=150)
        self.bookings_tree.column("status", width=100)

        # Видимость колонок (сохраняется в settings.json); id скрыт всегда
        self.setup_toggleable_columns(self.bookings_tree, "bookings_hidden_columns", columns[1:])

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.bookings_tree.yview)
        self.bookings_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.bookings_tree.pack(fill=tk.BOTH, expand=True)

        # Tooltip с полным текстом примечания при наведении (если текст обрезан)
        TreeviewTooltip(self.bookings_tree, columns=["notes"])

        # Настройка цветов для статусов
        self.bookings_tree.tag_configure("waiting", background="#fff3e0", foreground="#e65100")      # Оранжевый - В ожидании
        self.bookings_tree.tag_configure("in_progress", background="#e3f2fd", foreground="#1565c0")  # Синий - В работе
        self.bookings_tree.tag_configure("completed", background="#e8f5e9", foreground="#2e7d32")    # Зелёный - Выполнена
        self.bookings_tree.tag_configure("cancelled", background="#ffebee", foreground="#c62828")   # Красный - Отменена

        # Контекстное меню для записей
        self.bookings_context_menu = tk.Menu(
            self.bookings_tree, tearoff=0,
            bg="#1e1e1e", fg="white", bd=0,
            activebackground="#2d2d2d", activeforeground="white",
            font=("Segoe UI", 11)
        )
        self.bookings_context_menu.add_command(
            label="  🔧  " + self.tr("bookings.ctx_start_work"), command=self.start_work_from_booking,
            foreground="#81c784", activeforeground="#a5d6a7",
            background="#1e1e1e", activebackground="#2e7d32"
        )
        self.bookings_context_menu.add_command(
            label="  ✏  " + self.tr("bookings.ctx_edit"), command=self.edit_booking_in_add_work,
            foreground="#64b5f6", activeforeground="#90caf9",
            background="#1e1e1e", activebackground="#1976d2"
        )
        self.bookings_context_menu.add_separator()
        self.bookings_context_menu.add_command(
            label="  📋  " + self.tr("bookings.ctx_info"), command=self.show_booking_info,
            foreground="#ce93d8", activeforeground="#e1bee7",
            background="#1e1e1e", activebackground="#6a1b9a"
        )
        self.bookings_context_menu.add_command(
            label="  👤  " + self.tr("bookings.ctx_client_info"), command=self.show_client_info,
            foreground="#80deea", activeforeground="#b2ebf2",
            background="#1e1e1e", activebackground="#00838f"
        )
        self.bookings_context_menu.add_command(
            label="  ✏  " + self.tr("bookings.ctx_edit_client"), command=self.edit_client_info,
            foreground="#fff59d", activeforeground="#fffde7",
            background="#1e1e1e", activebackground="#f9a825"
        )
        self.bookings_context_menu.add_separator()
        self.bookings_context_menu.add_command(
            label="  ✅  " + self.tr("bookings.ctx_completed"), command=self.mark_booking_completed,
            foreground="#81c784", activeforeground="#a5d6a7",
            background="#1e1e1e", activebackground="#2e7d32"
        )
        self.bookings_context_menu.add_command(
            label="  ❌  " + self.tr("bookings.ctx_cancelled"), command=self.mark_booking_cancelled,
            foreground="#ffb74d", activeforeground="#ffe0b2",
            background="#1e1e1e", activebackground="#e65100"
        )
        self.bookings_context_menu.add_command(
            label="  🗑  " + self.tr("bookings.ctx_delete"), command=self.delete_selected_booking,
            foreground="#ef9a9a", activeforeground="#ffcdd2",
            background="#1e1e1e", activebackground="#c62828"
        )
        self.bookings_tree.bind("<Button-3>", self.show_bookings_context_menu)



    def toggle_bookings_date_sort(self):
        """Клик по заголовку "Дата" - сменить направление сортировки"""
        self.bookings_sort_desc = not self.bookings_sort_desc
        self.sort_bookings_tree()

    def sort_bookings_tree(self):
        """Отсортировать записи по дате и времени (по умолчанию - новые сверху)"""
        def sort_key(item):
            values = self.bookings_tree.item(item, "values")
            try:
                booking_date = datetime.strptime(values[2], "%d.%m.%Y")
            except (ValueError, IndexError):
                booking_date = datetime.min
            # Время "9:00" и "10:00" сравниваем как числа, а не как строки
            time_parts = re.findall(r"\d+", str(values[3]) if len(values) > 3 else "")
            booking_time = tuple(int(x) for x in time_parts[:2])
            return booking_date, booking_time, int(values[0] or 0)

        items = sorted(self.bookings_tree.get_children(), key=sort_key, reverse=self.bookings_sort_desc)
        for index, item in enumerate(items):
            self.bookings_tree.move(item, "", index)

        arrow = " ▼" if self.bookings_sort_desc else " ▲"
        self.bookings_tree.heading("date", text=self.tr("bookings.col_date") + arrow)

    def clear_bookings_search(self):
        """Очистить поле поиска и обновить список"""
        self.bookings_search_entry.delete(0, tk.END)
        self.refresh_bookings()

    def refresh_bookings(self):
        """Обновить список записей (от сегодня и далее)"""
        # Очистка таблицы
        for item in self.bookings_tree.get_children():
            self.bookings_tree.delete(item)

        # Получение фильтра по статусу
        status_filter = self.bookings_status_var.get() if hasattr(self, 'bookings_status_var') else None
        # Преобразование русского названия в код статуса
        status_map = {
            self.tr("bookings.filter_all"): None,
            self.tr("bookings.filter_waiting"): "waiting",
            self.tr("bookings.filter_in_progress"): "in_progress",
            self.tr("bookings.filter_completed"): "completed",
            self.tr("bookings.filter_cancelled"): "cancelled",
        }
        status = status_map.get(status_filter, None)

        # Получение поискового запроса
        search_query = self.bookings_search_entry.get().strip().lower() if hasattr(self, 'bookings_search_entry') else ""

        # Период (поиск ищет по всей базе - период тогда не учитывается)
        days = getattr(self, "bookings_periods", {}).get(self.bookings_period_var.get()) \
            if hasattr(self, "bookings_period_var") else None
        date_from = date.today() - timedelta(days=days) if days else None

        # Отбор делает база: дата / статус / поиск по телефону и госномеру
        bookings = self.db.get_all_bookings(status=status, date_from=date_from, search=search_query)

        # Заполнение таблицы
        for booking in bookings:
            booking_id, user_id, username, full_name, phone, booking_date, booking_time, status, car_info, client_id, car_id, order_number, notes = booking

            # Форматирование даты
            if isinstance(booking_date, date):
                date_str = booking_date.strftime("%d.%m.%Y")
            else:
                date_str = str(booking_date)

            # Статус на русском
            status_ru = {
                "waiting": self.tr("bookings.filter_waiting"),
                "in_progress": self.tr("bookings.filter_in_progress"),
                "completed": self.tr("bookings.status_completed"),
                "cancelled": self.tr("bookings.status_cancelled"),
            }.get(status, status)

            # Вставка с тегом для цвета
            self.bookings_tree.insert("", tk.END, values=(
                booking_id, order_number or "-", date_str, booking_time, full_name or "-",
                phone or "-", f"@{username}" if username else "-",
                car_info or "-", notes or "-", status_ru
            ), tags=(status,))

        self.sort_bookings_tree()
        self.update_bookings_count()

    def update_bookings_count(self):
        """Подпись "Показано N из M" под таблицей записей"""
        if not hasattr(self, "bookings_count_label"):
            return
        try:
            total = self.db.count_bookings()
        except Exception:
            total = None
        shown = len(self.bookings_tree.get_children())
        if total is None or shown == total:
            text = self.tr("bookings.count_all", shown=shown)
        else:
            text = self.tr("bookings.count_shown", shown=shown, total=total)
        self.bookings_count_label.configure(text=text)

    def on_bookings_period_change(self, choice=None):
        """Сменили период - запоминаем и обновляем список"""
        settings = self.load_settings()
        settings["bookings_period_days"] = self.bookings_periods.get(self.bookings_period_var.get())
        self.save_settings(settings)
        self.refresh_bookings()

    def show_today_bookings(self):
        """Показать записи на сегодня"""
        # Очистка таблицы
        for item in self.bookings_tree.get_children():
            self.bookings_tree.delete(item)

        bookings = self.db.get_today_bookings()
        self.root.after_idle(self.update_bookings_count)

        for booking in bookings:
            booking_id, user_id, username, full_name, phone, booking_date, booking_time, status, car_info, client_id, car_id, order_number, notes = booking

            if isinstance(booking_date, date):
                date_str = booking_date.strftime("%d.%m.%Y")
            else:
                date_str = str(booking_date)

            status_ru = {
                "waiting": self.tr("bookings.filter_waiting"),
                "in_progress": self.tr("bookings.filter_in_progress"),
                "completed": self.tr("bookings.status_completed"),
                "cancelled": self.tr("bookings.status_cancelled"),
            }.get(status, status)

            # Вставка с тегом для цвета
            self.bookings_tree.insert("", tk.END, values=(
                booking_id, order_number or "-", date_str, booking_time, full_name or "-",
                phone or "-", f"@{username}" if username else "-",
                car_info or "-", notes or "-", status_ru
            ), tags=(status,))

        self.sort_bookings_tree()

    def get_selected_booking_id(self):
        """Получить ID выбранной записи"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_select_from_list"))
            return None
        values = self.bookings_tree.item(selection[0], "values")
        return int(values[0])

    def mark_booking_completed(self):
        """Отметить запись как выполненную"""
        booking_id = self.get_selected_booking_id()
        if booking_id:
            # Нельзя завершить запись, по которой ещё не добавлено ни одной работы
            work = self.db.get_work_by_booking_id(booking_id)
            if not work:
                messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_completed_requires_work"))
                return

            # Получаем данные записи для уведомления
            booking = self.db.get_booking_by_id(booking_id)

            self.db.update_booking_status(booking_id, "completed")
            self.db.mark_work_completed(booking_id)
            self.refresh_bookings()

            # Помечаем использованные складские запчасти как "выдано"
            if work:
                car_number = work[8]
                if car_number:
                    wh_parts = self.db.get_warehouse_parts_by_car_number(car_number, status="установлена")
                    for wh_part in wh_parts:
                        self.db.update_warehouse_part_status(wh_part[0], "выдано")
                        self.db.update_warehouse_part_paid(wh_part[0], True)
                    if wh_parts:
                        self.refresh_warehouse()

            # Отправляем уведомление клиенту (Telegram и/или SMS)
            if booking:
                # Получаем данные работы по этой записи
                work = self.db.get_work_by_booking_id(booking_id)

                car_display = ""
                order_number = ""
                total = None

                # Формируем сообщение
                message = "🚗 <b>Ваша машина готова, ждём вас!</b>\n\n"

                # Добавляем наряд если есть связанная работа
                if work:
                    # work: (id, worker_id, full_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, booking_id, client_name, client_phone, order_number, car_id)
                    work_id = work[0]
                    description = work[3]
                    work_amount = work[4]  # Стоимость работ
                    car_brand = work[6] or ""
                    car_model = work[7] or ""
                    car_number = work[8] or ""
                    order_number = work[14] if len(work) > 14 else ""

                    message += "📋 <b>ЗАКАЗ-НАРЯД</b>\n"
                    message += "━━━━━━━━━━━━━━━━━━━━\n"

                    if order_number:
                        message += f"№ {order_number}\n"

                    # Информация об автомобиле
                    car_info = " ".join(filter(None, [car_brand, car_model]))
                    car_display = car_info
                    if car_number:
                        car_display = f"{car_display} ({car_number})".strip()
                    if car_info or car_number:
                        message += f"🚙 Авто: {car_info}"
                        if car_number:
                            message += f" ({car_number})"
                        message += "\n"

                    # Выполненные работы со стоимостью каждой позиции
                    if description:
                        message += f"\n📝 <b>Работы:</b>\n"
                        work_items = self.get_work_line_items(work_id, description, work_amount)
                        for work_item, item_price in work_items:
                            message += f"  • {work_item} — {item_price:,.0f} ₽\n"
                        message += f"  <i>Стоимость работ: {work_amount:,.0f} ₽</i>\n"

                    # Запчасти
                    parts = self.db.get_parts_by_work_id(work_id)
                    parts_total = 0
                    if parts:
                        message += f"\n🔧 <b>Запчасти:</b>\n"
                        for part_name, part_price in parts:
                            message += f"  • {part_name} — {part_price:,.0f} ₽\n"
                            parts_total += part_price
                        message += f"  <i>Итого запчасти: {parts_total:,.0f} ₽</i>\n"

                    # Итоговая сумма (работы + запчасти)
                    total = work_amount + parts_total
                    message += f"\n━━━━━━━━━━━━━━━━━━━━\n"
                    message += f"💰 <b>ИТОГО: {total:,.0f} ₽</b>\n"

                message += "\n✨ Спасибо, что выбрали наш автосервис!\n━━━━━━━━━━━━━━━━━━━━\nг.Щёлково, ул.Беляева, д.6Б\n+7-960-546-62-81 AlexAuto"

                notified_channels = []

                if booking.get("user_id"):
                    if send_telegram_notification(booking["user_id"], message, with_menu=True):
                        notified_channels.append("Telegram")

                phone = booking.get("phone")
                if phone:
                    sms_lines = ["Ваш автомобиль" + (f" {car_display}" if car_display else "") + " готов, ждём вас!"]
                    if order_number:
                        sms_lines.append(f"Заказ-наряд № {order_number}.")
                    if total is not None:
                        sms_lines.append(f"Итого: {total:,.0f} ₽.")
                    sms_lines.append("AlexAuto, г.Щёлково, ул.Беляева, д.6Б, +7-960-546-62-81")
                    sms_text = " ".join(sms_lines)
                    if send_sms_notification(phone, sms_text):
                        notified_channels.append("SMS")

                if notified_channels:
                    messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_completed_notified"))
                else:
                    messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_completed_notify_failed"))
            else:
                messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_completed"))

    def mark_booking_cancelled(self):
        """Отметить запись как отменённую"""
        booking_id = self.get_selected_booking_id()
        if booking_id:
            self.db.update_booking_status(booking_id, "cancelled")
            self.refresh_bookings()
            messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_cancelled"))

    def delete_selected_booking(self):
        """Удалить выбранную запись"""
        booking_id = self.get_selected_booking_id()
        if booking_id:
            if messagebox.askyesno(self.tr("common.confirm"), self.tr("bookings.msg_confirm_delete")):
                self.db.delete_booking(booking_id)
                self.refresh_bookings()
                messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_deleted"))

    # ===== Синхронизация с сайтом онлайн-записи (web_sync.py) =====
    # Обмен идёт в фоновом потоке, окна Tk трогаем только из главного потока (результат забираем опросом)

    WEB_SYNC_INTERVAL_MS = 60 * 1000

    def start_web_sync(self):
        """Запустить периодическую синхронизацию, если сайт настроен в config/.env"""
        if web_sync.enabled():
            self.root.after(3000, self._web_sync_tick)

    def _web_sync_tick(self):
        self.web_sync_now()
        self.root.after(self.WEB_SYNC_INTERVAL_MS, self._web_sync_tick)

    def web_sync_now(self):
        """Один обмен с сайтом сейчас (не ждёт - результат появится сам)"""
        if not web_sync.enabled() or getattr(self, "_web_sync_running", False):
            return
        self._web_sync_running = True
        result = {}

        def _worker():
            try:
                result.update(web_sync.sync_once(self.db))
            except Exception as e:
                result["error"] = e

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        def _wait_result():
            if thread.is_alive():
                self.root.after(300, _wait_result)
                return
            self._web_sync_running = False
            error = result.get("error")
            # в журнал пишем только смену состояния, а не каждую минуту без интернета
            if str(error or "") != getattr(self, "_web_sync_last_error", ""):
                self._web_sync_last_error = str(error or "")
                self._log_web_sync(f"ошибка: {error}" if error else "связь с сайтом есть")
            # новые записи с сайта/из панели или отмена с телефона - обновляем список
            if result.get("new") or result.get("cancelled"):
                try:
                    self.refresh_bookings()
                except Exception:
                    pass
            if result.get("new"):
                self.show_web_bookings_notice(result["new"])

        _wait_result()

    def _log_web_sync(self, text):
        try:
            log_dir = os.path.join(BASE_PATH, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "web_sync.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
        except Exception:
            pass

    def show_web_bookings_notice(self, bookings):
        """Окошко в правом нижнем углу: новые записи с сайта (новые добавляются в уже открытое)"""
        lines = [self.tr("web_sync.line", date=datetime.strptime(b["date"], "%Y-%m-%d").strftime("%d.%m.%Y"),
                         time=b["time"], name=b["name"], phone=b["phone"], car=b["car"], service=b["service"])
                 for b in bookings]
        win = getattr(self, "_web_notice", None)
        if win is not None and win.winfo_exists():
            win._lines.extend(lines)
        else:
            win = ctk.CTkToplevel(self.root)
            win.title(self.tr("web_sync.title"))
            win.attributes("-topmost", True)
            win.resizable(False, False)
            win._lines = list(lines)
            win._label = ctk.CTkLabel(win, text="", font=("Arial", 14), justify="left", anchor="w", wraplength=420)
            win._label.pack(padx=18, pady=(16, 10), fill=tk.X)
            buttons = ctk.CTkFrame(win, fg_color="transparent")
            buttons.pack(pady=(0, 14))

            def _open_bookings():
                win.destroy()
                self.switch_tab("bookings")

            ctk.CTkButton(buttons, text=self.tr("web_sync.open"), command=_open_bookings,
                          fg_color="#2e7d32", hover_color="#1b5e20", width=150).pack(side=tk.LEFT, padx=5)
            ctk.CTkButton(buttons, text="OK", command=win.destroy,
                          fg_color="#757575", hover_color="#616161", width=90).pack(side=tk.LEFT, padx=5)
            self._web_notice = win
        win._label.configure(text=self.tr("web_sync.header", count=len(win._lines)) + "\n\n" + "\n\n".join(win._lines[-8:]))
        win.update_idletasks()
        x = win.winfo_screenwidth() - win.winfo_reqwidth() - 30
        y = win.winfo_screenheight() - win.winfo_reqheight() - 80
        win.geometry(f"+{x}+{y}")
        win.lift()
        win.bell()

    def show_add_booking_window(self):
        """Показать окно для записи клиента. Окно строится один раз (заранее, вскоре после запуска)
        и дальше только показывается/прячется - поэтому открывается сразу"""
        # Подтягиваем свежие записи с сайта, чтобы проверка занятости учла и их
        self.web_sync_now()
        self._ensure_booking_window()["open"]()

    def _ensure_booking_window(self):
        """Готовое окно "Записать клиента": построить, если ещё нет (или поменялась сетка времени в настройках)"""
        cached = getattr(self, "_booking_window", None)
        if cached:
            try:
                alive = cached["window"].winfo_exists()
            except tk.TclError:
                alive = False
            if alive and cached["slots"] == booking_time_slots():
                return cached
            for widget in (cached["window"], cached["overlay"]):
                try:
                    widget.destroy()
                except tk.TclError:
                    pass
        self._booking_window = self._build_add_booking_window()
        return self._booking_window

    def _prebuild_booking_window(self):
        """Построить окно "Записать клиента" заранее, пока программа простаивает"""
        try:
            self._ensure_booking_window()
        except Exception as e:
            print(f"Окно записи заранее не построено (построится при первом открытии): {e}")

    def _build_add_booking_window(self):
        """Построить окно "Записать клиента" (скрытым). Возвращает {"window", "overlay", "slots", "open"}"""
        # Слоты времени из настроек (по умолчанию каждые 2 часа с 10:00 до 20:00)
        TIME_SLOTS = booking_time_slots()

        # Затемняющий оверлей поверх главного окна - показывается вместе с окном записи
        overlay = self.make_dim_overlay()

        add_window = ctk.CTkToplevel(self.root)
        add_window.withdraw()  # строим скрытым - покажем один раз, когда всё готово (show_form_window_when_ready)
        add_window.title(self.tr("bookings.add_client"))
        add_window.transient(self.root)
        add_window.dim_overlay = overlay   # форма принадлежит затемнению - всегда над ним, но не над другими программами
        add_window.resizable(False, False)

        def on_close():
            # Окно не уничтожаем - спрячем, при следующем открытии форма сбросится (reset_and_show)
            try:
                hide_slot_tooltip()
                hide_brand_list()
                hide_model_list()
                hide_notes_keyword_list()
            except NameError:
                pass
            add_window.grab_release()
            add_window.withdraw()
            overlay.withdraw()

        add_window.protocol("WM_DELETE_WINDOW", on_close)

        # Оформление формы - общие функции form_* (как в "Добавить запчасть")
        time_cols = 6  # время - сетка кнопок по 6 в ряд
        content = self.form_content(add_window)

        def section(title):
            return self.form_section(content, title)

        field_label = self.form_label
        make_entry = self.form_entry
        popup_below = self.place_popup

        def fit_window():
            self.fit_form_window(add_window)

        # Флаг: авто найдено по госномеру
        car_found_by_number = [False]
        found_car_id = [None]

        # === АВТОМОБИЛЬ ===
        car_card, car_body = section(self.tr("bookings.section_car"))
        field_label(car_body, self.tr("works.car_number"), required=True).pack(fill=tk.X)
        car_number_entry = make_entry(car_body, placeholder_text="А123БВ777")
        car_number_entry.pack(fill=tk.X)
        car_status_label = ctk.CTkLabel(car_body, text="", font=("Arial", 13, "bold"), anchor="w")

        # Марка/модель - только для нового авто (показывается динамически)
        car_details_frame = ctk.CTkFrame(car_body, fg_color="transparent")
        car_details_frame.grid_columnconfigure((0, 1), weight=1, uniform="car")
        car_details_visible = [False]

        field_label(car_details_frame, self.tr("bookings.add_window_brand"), required=True).grid(row=0, column=0, sticky="w")
        field_label(car_details_frame, self.tr("bookings.add_window_model"), required=True).grid(row=0, column=1, sticky="w", padx=(10, 0))
        brand_entry = make_entry(car_details_frame)
        brand_entry.grid(row=1, column=0, sticky="ew")
        model_entry = make_entry(car_details_frame)
        model_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        # Флаги видимости listbox
        brand_listbox_visible = [False]
        model_listbox_visible = [False]
        brand_listbox = self.form_popup_listbox(content)
        model_listbox = self.form_popup_listbox(content)

        def set_car_state(state, text=""):
            """state: None - пусто, "found" - авто найдено, "new" - новое авто (нужны марка и модель)"""
            self.form_set_card_state(car_card, state)
            if text:
                car_status_label.configure(text=text, text_color=self.FORM_STATE_COLORS.get(state, "#ef6c00"))
                car_status_label.pack(fill=tk.X, pady=(6, 0), after=car_number_entry)
            else:
                car_status_label.pack_forget()
            if state == "new":
                if not car_details_visible[0]:
                    car_details_frame.pack(fill=tk.X, pady=(6, 0), after=car_status_label)
                    car_details_visible[0] = True
            elif car_details_visible[0]:
                hide_brand_list()
                hide_model_list()
                car_details_frame.pack_forget()
                car_details_visible[0] = False
            fit_window()

        def show_brand_list(brands_list):
            brand_listbox.delete(0, tk.END)
            for b in brands_list:
                brand_listbox.insert(tk.END, b)
            popup_below(brand_listbox, brand_entry)
            brand_listbox_visible[0] = True

        def hide_brand_list():
            if brand_listbox_visible[0]:
                self.hide_popup(brand_listbox)
                brand_listbox_visible[0] = False

        def on_brand_key(event):
            text = brand_entry.get().strip()
            if len(text) >= 1:
                results = self.db.search_car_brands(text)
                if results:
                    show_brand_list(results)
                else:
                    hide_brand_list()
            else:
                hide_brand_list()

        def on_brand_select(event):
            sel = brand_listbox.curselection()
            if sel:
                brand_entry.delete(0, tk.END)
                brand_entry.insert(0, brand_listbox.get(sel[0]))
                hide_brand_list()
                model_entry.focus_set()

        brand_entry.bind('<KeyRelease>', on_brand_key)
        brand_listbox.bind('<<ListboxSelect>>', on_brand_select)

        def show_model_list(models_list):
            model_listbox.delete(0, tk.END)
            for m in models_list:
                model_listbox.insert(tk.END, m)
            popup_below(model_listbox, model_entry)
            model_listbox_visible[0] = True

        def hide_model_list():
            if model_listbox_visible[0]:
                self.hide_popup(model_listbox)
                model_listbox_visible[0] = False

        def on_model_key(event):
            brand_name = brand_entry.get().strip()
            text = model_entry.get().strip()
            if brand_name:
                results = self.db.search_car_models(brand_name, text)
                if results:
                    show_model_list(results)
                else:
                    hide_model_list()
            else:
                hide_model_list()

        def on_model_select(event):
            sel = model_listbox.curselection()
            if sel:
                model_entry.delete(0, tk.END)
                model_entry.insert(0, model_listbox.get(sel[0]))
                hide_model_list()
                phone_entry.focus_set()

        def hide_list_later(hide):
            # Список марок/моделей прячем, когда фокус ушёл из поля (но не в сам список)
            def check():
                try:
                    if add_window.focus_get() not in (brand_listbox, model_listbox):
                        hide()
                except (KeyError, tk.TclError):
                    hide()
            add_window.after(200, check)

        model_entry.bind('<KeyRelease>', on_model_key)
        model_entry.bind('<FocusIn>', on_model_key)
        model_listbox.bind('<<ListboxSelect>>', on_model_select)
        brand_entry.bind('<FocusOut>', lambda e: hide_list_later(hide_brand_list), add="+")
        model_entry.bind('<FocusOut>', lambda e: hide_list_later(hide_model_list), add="+")

        # === КЛИЕНТ: телефон и имя рядом ===
        _, client_body = section(self.tr("bookings.section_client"))
        client_grid = ctk.CTkFrame(client_body, fg_color="transparent")
        client_grid.pack(fill=tk.X)
        client_grid.grid_columnconfigure((0, 1), weight=1, uniform="client")
        field_label(client_grid, self.tr("bookings.add_window_phone"), required=True).grid(row=0, column=0, sticky="w")
        field_label(client_grid, self.tr("works.client_name"), required=True).grid(row=0, column=1, sticky="w", padx=(10, 0))
        phone_entry = make_entry(client_grid)
        phone_entry.grid(row=1, column=0, sticky="ew")
        self.attach_phone_mask(phone_entry)
        name_entry = make_entry(client_grid)
        name_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        # Подсказка имён из config/first_names.txt - список под полем
        self.attach_name_autocomplete(name_entry, content, position="below")

        # Выбор машины клиента, найденного по телефону (показывается, если машин несколько)
        phone_cars_combo = ctk.CTkComboBox(client_body, height=34, font=("Arial", 13), values=[], state="readonly",
                                           corner_radius=8)
        phone_cars_visible = [False]
        phone_cars_numbers = {}
        # Что подставил поиск по телефону: {"digits": номер, "filled": {поле: значение}}
        phone_fill = [None]

        # Что подставил поиск по госномеру: {"number": госномер, "filled": {поле: значение}} -
        # госномер поправили - это убираем (если руками не меняли)
        plate_fill = [None]
        plate_fill_fields = {"name": name_entry, "phone": phone_entry}

        def check_car_number(*args):
            """Проверка госномера - ищем существующее авто и владельца"""
            car_num = car_number_entry.get().strip().upper()
            if plate_fill[0] and plate_fill[0]["number"] == car_num:
                return  # этот госномер уже найден и подставлен
            if plate_fill[0]:
                # Госномер поправили - имя и телефон прежнего владельца убираем
                filled = plate_fill[0]["filled"]
                plate_fill[0] = None
                self.undo_autofill(plate_fill_fields, filled)
                if "phone" in filled:
                    phone_fill[0] = None
            if len(car_num) >= 6:
                car_info = self.db.get_car_info_by_number(car_num)
                if car_info:
                    before = self.snapshot_fields(plate_fill_fields)
                    car_found_by_number[0] = True
                    found_car_id[0] = car_info.get('car_id')
                    owner_name = car_info.get('client_name', '')
                    owner_phone = car_info.get('client_phone', '')
                    car_brand = car_info.get('car_brand', '')
                    car_model = car_info.get('car_model', '')

                    # Показываем информацию, поля марки/модели скрываем
                    info_text = self.tr("bookings.add_window_car_found", brand=car_brand, model=car_model)
                    if owner_name:
                        info_text += f" — {owner_name}"
                    set_car_state("found", info_text)

                    # Заполняем марку/модель (скрытые, но для сохранения)
                    brand_entry.delete(0, tk.END)
                    brand_entry.insert(0, car_brand)
                    model_entry.delete(0, tk.END)
                    model_entry.insert(0, car_model)

                    # Автозаполнение телефона и имени (всегда обновляем при нахождении)
                    if owner_name:
                        name_entry.delete(0, tk.END)
                        name_entry.insert(0, owner_name)
                    if owner_phone:
                        phone_digits = ''.join(c for c in owner_phone if c.isdigit())
                        if len(phone_digits) >= 10:
                            self.set_phone_value(phone_entry, phone_digits[-10:])
                    plate_fill[0] = {"number": car_num, "filled": self.autofilled_diff(plate_fill_fields, before)}
                else:
                    # Авто не найдено - показываем поля марки/модели, сбрасываем данные
                    car_found_by_number[0] = False
                    found_car_id[0] = None
                    if not car_details_visible[0]:
                        brand_entry.delete(0, tk.END)
                        model_entry.delete(0, tk.END)
                    set_car_state("new", self.tr("bookings.add_window_new_car").rstrip(":"))
            else:
                car_found_by_number[0] = False
                found_car_id[0] = None
                if car_status_label.winfo_ismapped() or car_details_visible[0]:
                    set_car_state(None)
                # Сбрасываем поля марки/модели
                brand_entry.delete(0, tk.END)
                model_entry.delete(0, tk.END)

        car_number_entry.bind("<KeyRelease>", check_car_number)
        car_number_entry.bind("<FocusOut>", check_car_number)

        def hide_phone_cars():
            if phone_cars_visible[0]:
                phone_cars_combo.pack_forget()
                phone_cars_visible[0] = False
                fit_window()

        def fill_car_number(number):
            car_number_entry.delete(0, tk.END)
            car_number_entry.insert(0, number)
            check_car_number()

        def on_phone_car_select(choice):
            number = phone_cars_numbers.get(choice)
            if number:
                before = self.snapshot_fields(phone_fill_fields)
                fill_car_number(number)
                # Машину выбрали из списка по телефону - при смене номера её тоже уберём
                if phone_fill[0]:
                    phone_fill[0]["filled"].update(self.autofilled_diff(phone_fill_fields, before))

        phone_cars_combo.configure(command=on_phone_car_select)

        phone_fill_fields = {"name": name_entry, "car_number": car_number_entry}

        def check_phone(*args):
            """Проверка телефона - подставляем имя клиента и его машины"""
            phone_digits = ''.join(c for c in phone_entry.get() if c.isdigit())
            # Номер изменили - убираем всё, что подставили по прошлому номеру
            if phone_fill[0] and phone_fill[0]["digits"] != phone_digits:
                filled = phone_fill[0]["filled"]
                phone_fill[0] = None
                hide_phone_cars()
                self.undo_autofill(phone_fill_fields, filled)
                if "car_number" in filled:
                    check_car_number()  # сбросит найденную марку/модель
            if len(phone_digits) != 11:
                hide_phone_cars()
                return
            if phone_fill[0]:
                return
            before = self.snapshot_fields(phone_fill_fields)
            phone_fill[0] = {"digits": phone_digits, "filled": {}}
            fill_by_phone(phone_digits)
            phone_fill[0]["filled"] = self.autofilled_diff(phone_fill_fields, before)

        def fill_by_phone(phone_digits):
            client_name = self.db.get_client_name_by_phone(phone_digits)
            if client_name and not name_entry.get().strip():
                name_entry.insert(0, client_name)

            cars = self.db.get_client_cars_by_phone(phone_digits)
            phone_cars_numbers.clear()
            for car_brand, car_model, car_number, _vin in cars:
                if car_number:
                    display = f"{car_brand or ''} {car_model or ''} {car_number}".strip()
                    phone_cars_numbers[display] = car_number

            if not phone_cars_numbers:
                hide_phone_cars()
                return

            # Госномер уже введён вручную - не перезаписываем
            if car_number_entry.get().strip():
                return

            if len(phone_cars_numbers) == 1:
                hide_phone_cars()
                fill_car_number(next(iter(phone_cars_numbers.values())))
            else:
                phone_cars_combo.configure(values=list(phone_cars_numbers))
                phone_cars_combo.set(self.tr("bookings.add_window_client_cars"))
                if not phone_cars_visible[0]:
                    phone_cars_combo.pack(fill=tk.X, pady=(8, 0))
                    phone_cars_visible[0] = True
                    fit_window()

        phone_entry.bind("<KeyRelease>", check_phone, add="+")
        phone_entry.bind("<FocusOut>", check_phone)

        # === ДАТА И ВРЕМЯ ===
        _, when_body = section(self.tr("bookings.section_datetime"))
        date_row = ctk.CTkFrame(when_body, fg_color="transparent")
        date_row.pack(fill=tk.X, pady=(0, 8))

        # Календарь для выбора даты
        date_entry = DateEntry(
            date_row,
            width=12,
            background='#1f538d',
            foreground='white',
            borderwidth=2,
            date_pattern='dd.mm.yyyy',
            locale='ru_RU',
            mindate=datetime.now().date(),
            font=("Arial", 13)
        )
        date_entry.pack(side=tk.LEFT, ipady=3)

        # Быстрый выбор: сегодня / завтра
        quick_dates = {}
        for label_key, days in (("bookings.btn_today", 0), ("bookings.btn_tomorrow", 1)):
            quick_btn = ctk.CTkButton(date_row, text=self.tr(label_key), width=90, height=30, corner_radius=8,
                                      font=("Arial", 13), border_width=1, border_color="#c5cdd6",
                                      command=lambda d=days: set_booking_date(date.today() + timedelta(days=d)))
            quick_btn.pack(side=tk.LEFT, padx=(8, 0))
            quick_dates[days] = quick_btn

        def set_booking_date(day):
            date_entry.set_date(day)
            update_available_times()

        # Время - сетка кнопок во всю ширину карточки
        time_grid = ctk.CTkFrame(when_body, fg_color="transparent")
        time_grid.pack(fill=tk.X)
        time_grid.grid_columnconfigure(tuple(range(time_cols)), weight=1, uniform="time")
        selected_time = [None]
        time_buttons = {}
        time_badges = {}
        past_slots = set()  # на сегодня - время, которое уже прошло
        slot_bookings = {}  # время -> список записей на выбранную дату
        slot_tooltip = [None]

        button_look = {}  # время -> как кнопка нарисована сейчас (перерисовываем только изменившиеся)

        def select_time(slot):
            if slot in past_slots:
                return
            selected_time[0] = slot
            for s, btn in time_buttons.items():
                look = "past" if s in past_slots else ("selected" if s == slot else "free")
                if button_look.get(s) == look:
                    continue
                button_look[s] = look
                if look == "past":
                    btn.configure(state="disabled", fg_color="#f1f3f5", text_color_disabled="#b0b7bf",
                                  border_color="#e3e7eb")
                elif look == "selected":
                    btn.configure(state="normal", fg_color="#1f538d", text_color="white", hover_color="#1f538d",
                                  border_color="#1f538d")
                else:
                    btn.configure(state="normal", fg_color="white", text_color="black", hover_color="#dbe6f3",
                                  border_color="#c5cdd6")

        def hide_slot_tooltip(event=None):
            if slot_tooltip[0]:
                slot_tooltip[0].destroy()
                slot_tooltip[0] = None

        def show_slot_tooltip(slot):
            hide_slot_tooltip()
            bookings = slot_bookings.get(slot)
            if not bookings:
                return
            btn = time_buttons[slot]
            tip = tk.Toplevel(add_window)
            tip.wm_overrideredirect(True)
            tip.transient(add_window)  # подсказка принадлежит окну записи - над ним, но не над другими программами
            tip.wm_geometry(f"+{btn.winfo_rootx()}+{btn.winfo_rooty() + btn.winfo_height() + 4}")
            frame = tk.Frame(tip, bg='#ffffe0', relief='solid', borderwidth=1)
            frame.pack()
            tk.Label(frame, text=self.tr("bookings.add_window_slot_bookings", time=slot), bg='#ffffe0',
                     font=('Segoe UI', 10, 'bold'), padx=8, pady=4).pack(anchor=tk.W)
            for b in bookings:
                car = " ".join(x for x in (b['brand'], b['model'], b['car_number']) if x)
                line = f"• {b['client_name'] or '—'}" + (f" — {car}" if car else "")
                tk.Label(frame, text=line, bg='#ffffe0', font=('Segoe UI', 10),
                         padx=8, pady=1, justify=tk.LEFT).pack(anchor=tk.W)
            tk.Frame(frame, bg='#ffffe0', height=4).pack()
            slot_tooltip[0] = tip

        for i, slot in enumerate(TIME_SLOTS):
            # Ячейка с отступом сверху/справа - в угол ложится красный кружок с числом записей
            cell = ctk.CTkFrame(time_grid, fg_color="transparent")
            cell.grid(row=i // time_cols, column=i % time_cols, sticky="ew", padx=1, pady=1)
            btn = ctk.CTkButton(cell, text=slot, width=50, height=30, font=("Arial", 13),
                                corner_radius=8, border_width=1, border_color="#c5cdd6",
                                command=lambda s=slot: select_time(s))
            btn.pack(fill=tk.X, padx=(0, 7), pady=(7, 0))
            badge = ctk.CTkLabel(cell, text="", width=16, height=16, corner_radius=8,
                                 fg_color="#e53935", text_color="white", font=("Arial", 10, "bold"))
            badge.bind("<Button-1>", lambda e, s=slot: select_time(s))
            for w in (btn, badge):
                w.bind("<Enter>", lambda e, s=slot: show_slot_tooltip(s), add="+")
                w.bind("<Leave>", hide_slot_tooltip, add="+")
            time_buttons[slot] = btn
            time_badges[slot] = badge

        def refresh_slot_counts():
            """Подсчитать записи на выбранную дату и обновить кружки"""
            slot_bookings.clear()
            try:
                slot_bookings.update(self.db.get_bookings_by_date(date_entry.get_date()))
            except Exception as e:
                print(f"Не удалось загрузить записи на дату: {e}")
            for slot, badge in time_badges.items():
                count = len(slot_bookings.get(slot, []))
                if count:
                    badge.configure(text=str(count) if count < 10 else "9+")
                    badge.place(relx=1.0, rely=0.0, anchor="ne")
                    badge.lift()
                else:
                    badge.place_forget()

        add_window.bind("<Destroy>", lambda e: hide_slot_tooltip() if e.widget is add_window else None, add="+")

        # Статус (показывается, если на сегодня свободного времени не осталось)
        slot_status_label = ctk.CTkLabel(when_body, text="", font=("Arial", 13), text_color="#ef6c00", anchor="w")

        def update_available_times(*args):
            """Обновить слоты времени: прошедшие на сегодня - серые, занятость - кружками"""
            try:
                booking_date = date_entry.get_date()
            except Exception:
                booking_date = date.today()
            now = datetime.now()
            past_slots.clear()
            if booking_date == now.date():
                past_slots.update(s for s in TIME_SLOTS if s <= now.strftime("%H:%M"))
            free = [s for s in TIME_SLOTS if s not in past_slots]
            # Выбранное время оставляем, если оно ещё доступно, иначе - первое свободное
            slot = selected_time[0] if selected_time[0] in free else (free[0] if free else None)
            selected_time[0] = None
            select_time(slot)
            refresh_slot_counts()

            if free:
                slot_status_label.pack_forget()
            else:
                slot_status_label.configure(text=self.tr("bookings.msg_no_slots_today"))
                slot_status_label.pack(fill=tk.X, pady=(6, 0))
            # Подсвечиваем кнопку "Сегодня"/"Завтра", если выбрана эта дата
            for days, quick_btn in quick_dates.items():
                active = booking_date == date.today() + timedelta(days=days)
                quick_btn.configure(fg_color="#1f538d" if active else "white",
                                    text_color="white" if active else "black",
                                    hover_color="#1f538d" if active else "#dbe6f3")
            fit_window()

        date_entry.bind("<<DateEntrySelected>>", update_available_times)

        # === ПРИМЕЧАНИЕ (со списком ключевых слов, как в "Проделанные работы") ===
        _, notes_body = section(self.tr("bookings.section_notes"))
        notes_entry = make_entry(notes_body)
        notes_entry.pack(fill=tk.X)
        # Список над полем - под ним кнопки и край окна
        notes_keyword_listbox = self.form_popup_listbox(content)
        notes_keyword_listbox_visible = [False]

        def show_notes_keyword_list(keywords):
            notes_keyword_listbox.delete(0, tk.END)
            for kw in keywords:
                notes_keyword_listbox.insert(tk.END, kw)
            popup_below(notes_keyword_listbox, notes_entry, above=True)
            notes_keyword_listbox_visible[0] = True

        def hide_notes_keyword_list():
            if notes_keyword_listbox_visible[0]:
                self.hide_popup(notes_keyword_listbox)
                notes_keyword_listbox_visible[0] = False

        def on_notes_key(event):
            if event.keysym in ("Return", "Escape"):
                return
            text = notes_entry.get().strip()
            if len(text) >= 1:
                results = self.db.search_keywords(text)
                if results:
                    show_notes_keyword_list(results)
                else:
                    hide_notes_keyword_list()
            else:
                hide_notes_keyword_list()

        def on_notes_select(event):
            sel = notes_keyword_listbox.curselection()
            if sel:
                notes_entry.delete(0, tk.END)
                notes_entry.insert(0, notes_keyword_listbox.get(sel[0]))
                hide_notes_keyword_list()
                notes_entry.focus_set()
            return "break"

        def on_notes_focus_out(event):
            def check_and_hide():
                try:
                    focused = add_window.focus_get()
                    if focused != notes_keyword_listbox:
                        hide_notes_keyword_list()
                except:
                    hide_notes_keyword_list()
            add_window.after(200, check_and_hide)

        notes_entry.bind('<KeyRelease>', on_notes_key)
        notes_entry.bind('<FocusOut>', on_notes_focus_out)
        notes_keyword_listbox.bind('<Double-Button-1>', on_notes_select)
        notes_keyword_listbox.bind('<Return>', on_notes_select)

        # Незаполненное обязательное поле - красная рамка (снимается, как только поле начали править)
        def mark_error(entry, message_key):
            self.form_mark_error(entry, message_key, add_window)

        self.form_clear_error_on_type((car_number_entry, brand_entry, model_entry, phone_entry, name_entry))

        def save_booking():
            """Сохранить запись"""
            name = name_entry.get().strip()
            phone_raw = phone_entry.get().strip()
            date_str = date_entry.get_date().strftime("%d.%m.%Y")
            time_str = selected_time[0]

            # Получаем информацию об авто
            number = car_number_entry.get().strip().upper()
            brand = brand_entry.get().strip()
            model = model_entry.get().strip()
            existing_car_id = found_car_id[0]  # ID найденного авто или None

            # Валидация госномера - обязательно
            if not number:
                mark_error(car_number_entry, "works.msg_enter_car_number")
                return

            # Если авто не найдено - нужны марка и модель
            if not car_found_by_number[0]:
                if not brand:
                    mark_error(brand_entry, "works.msg_enter_brand")
                    return
                if not model:
                    mark_error(model_entry, "works.msg_enter_model")
                    return

            # Валидация телефона - должен быть +7 и 10 цифр после
            phone_digits = ''.join(c for c in phone_raw if c.isdigit())
            if len(phone_digits) != 11 or not phone_digits.startswith('7'):
                mark_error(phone_entry, "bookings.msg_enter_phone_after_plus7")
                return

            if not name:
                mark_error(name_entry, "bookings.msg_enter_client_name")
                return

            if not time_str:
                messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_no_slots_today"), parent=add_window)
                return

            # В базу - без форматирования, +7XXXXXXXXXX
            phone = "+" + phone_digits

            # Парсим дату
            try:
                from datetime import datetime
                booking_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            except:
                messagebox.showerror(self.tr("common.error"), self.tr("bookings.msg_invalid_date"), parent=add_window)
                return

            # Эта же машина уже записана на это время - второй раз не записываем
            for booking in self.db.get_bookings_at_time(booking_date, time_str):
                if booking['car_number'].strip().upper() == number:
                    messagebox.showwarning(
                        self.tr("common.attention"),
                        self.tr("bookings.msg_car_already_booked", car_number=number,
                                date=date_str, time=time_str, client_name=booking['client_name']),
                        parent=add_window)
                    return

            # Проверяем доступность
            if not self.db.is_time_slot_available(booking_date, time_str):
                # Получаем список машин на это время
                existing_bookings = self.db.get_bookings_at_time(booking_date, time_str)
                num_cars = len(existing_bookings)

                # Формируем сообщение
                message = self.tr("bookings.msg_slot_busy_header", num_cars=num_cars)
                for booking in existing_bookings:
                    car_info = f"{booking['brand']} {booking['model']}" if booking['brand'] else ""
                    message += f"• {booking['car_number']}"
                    if car_info:
                        message += f" ({car_info})"
                    message += f" - {booking['client_name']}\n"

                message += self.tr("bookings.msg_slot_busy_footer")

                # Спрашиваем пользователя
                result = messagebox.askyesno(self.tr("bookings.dialog_slot_busy_title"), message, parent=add_window)
                if not result:
                    return

            # Ищем Telegram данные по телефону
            tg_user_id = 0
            tg_username = ""
            if phone:
                tg_data = self.db.get_telegram_user_by_phone(phone)
                if tg_data:
                    tg_user_id = tg_data.get("user_id") or 0
                    tg_username = tg_data.get("username") or ""

            # Машина уже есть в базе на другом человеке - спрашиваем, новый ли это владелец (машину продали).
            # Иначе прежний владелец молча переименуется в нового (поиск клиента по госномеру)
            car = self.db.get_car_owner_by_number(number)
            new_owner = False
            client_id = None
            if car and car["client_id"] and not self.works_confirm_rename(
                    phone_digits[-10:], name, car["owner_name"], car["owner_phone"], phone_entry, parent=add_window):
                return
            if car and car["client_id"] and not self.works_same_person(
                    phone_digits[-10:], name, car["owner_phone"], car["owner_name"]):
                old_person = car["owner_name"] or self.tr("common.no_name")
                if car["owner_phone"]:
                    old_person = f"{old_person} ({car['owner_phone']})"
                answer = messagebox.askyesnocancel(
                    self.tr("works.dialog_new_owner_title"),
                    self.tr("works.dialog_new_owner_body", number=car["car_number"] or number, old=old_person,
                            new=f"{name} ({phone})", old_name=car["owner_name"] or self.tr("common.no_name")),
                    parent=add_window)
                if answer is None:
                    return
                if answer:
                    new_owner = True
                else:
                    # Тот же человек - обновим ему имя / телефон
                    client_id = car["client_id"]
                    self.db.update_client_contact(client_id, name, phone)

            # Создаём/находим клиента (новый владелец - по его телефону, не по госномеру: там прежний)
            if client_id is None:
                client_id = self.db.get_or_create_client(
                    telegram_user_id=tg_user_id if tg_user_id else None,
                    full_name=name,
                    phone=phone,
                    car_number=None if new_owner else number
                )

            # Создаём/находим машину
            car_id = existing_car_id  # Используем ID существующей машины если выбрана
            if new_owner and client_id:
                # Машину продали: она и вся история её работ и записей - у нового владельца
                car_id = self.db.get_or_create_car(client_id, brand, model, number)
                self.db.transfer_car_history(car_id, client_id)
            elif not car_id and client_id and brand and number:
                # Создаём новую машину только если не выбрана существующая
                car_id = self.db.get_or_create_car(client_id, brand, model, number)

            # Сохраняем запись
            notes = notes_entry.get().strip()
            booking_id = self.db.add_booking(
                booking_date=booking_date,
                booking_time=time_str,
                client_id=client_id,
                car_id=car_id,
                notes=notes if notes else None
            )
            if booking_id:
                messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_client_booked", date=date_str, time=time_str), parent=add_window)
                on_close()
                self.refresh_bookings()
            else:
                messagebox.showerror(self.tr("common.error"), self.tr("bookings.msg_booking_failed"), parent=add_window)

        # Кнопки: широкая основная "Записать" и второстепенная "Отмена"; Enter - записать, Esc - отмена
        self.form_buttons(add_window, self.tr("bookings.btn_book"), save_booking, on_close)
        self.form_bind_keys(add_window, content, save_booking, on_close,
                            lambda: (hide_brand_list(), hide_model_list(), hide_notes_keyword_list()))

        form_entries = (car_number_entry, brand_entry, model_entry, phone_entry, name_entry, notes_entry)
        just_built = [True]
        normal_border = car_number_entry.cget("border_color")

        def reset_and_show():
            """Каждое открытие - чистая форма: поля, найденная машина, подсказки, ошибки, дата и время"""
            for entry in form_entries:
                if entry is phone_entry:
                    self.set_phone_value(phone_entry, "")
                else:
                    entry.delete(0, tk.END)
                entry.configure(border_color=normal_border)
            self.restore_placeholder(car_number_entry)
            car_found_by_number[0] = False
            found_car_id[0] = None
            phone_fill[0] = None
            plate_fill[0] = None
            phone_cars_numbers.clear()
            hide_phone_cars()
            hide_brand_list()
            hide_model_list()
            hide_notes_keyword_list()
            hide_slot_tooltip()
            set_car_state(None)

            # Дата - сегодня (окно могло быть построено вчера), а если на сегодня время кончилось - завтра
            now = datetime.now()
            date_entry.configure(mindate=now.date())
            day = now.date()
            if all(slot <= now.strftime("%H:%M") for slot in TIME_SLOTS):
                day += timedelta(days=1)
            date_entry.set_date(day)
            selected_time[0] = None
            update_available_times()  # занятость слотов - свежая из базы; заодно подгоняет высоту окна

            # Затемнение - по текущему положению главного окна, потом само окно записи
            self.show_dim_overlay(overlay)
            # Сразу после построения CustomTkinter ещё перекрашивает заголовок (прячет/показывает окно) - ждём;
            # при повторных открытиях это уже сделано - показываем сразу
            delay = 40 if just_built[0] else 1
            just_built[0] = False
            self.show_form_window_when_ready(add_window, car_number_entry, delay=delay)

        # Окно построено скрытым; CustomTkinter перекрасит заголовок, пока его не видно
        # (построено заранее - к первому открытию это уже сделано)
        add_window.update_idletasks()
        add_window.after(300, lambda: just_built.__setitem__(0, False))
        return {"window": add_window, "overlay": overlay, "slots": TIME_SLOTS, "open": reset_and_show}

    # ===== Скрытие/показ колонок таблиц (общее для "Записей" и "Склада") =====
    # Настройки хранятся в settings.json под ключом settings_key: список скрытых колонок

    def setup_toggleable_columns(self, tree, settings_key, columns):
        """Подключить к таблице скрытие колонок и растягивание видимых на всю ширину"""
        if not hasattr(self, "_column_toggles"):
            self._column_toggles = {}
        self._column_toggles[settings_key] = {
            "tree": tree,
            "columns": tuple(columns),
            # Исходные ширины - по ним видимые колонки делят ширину таблицы пропорционально
            "base_widths": {c: tree.column(c, "width") for c in columns},
        }
        self.apply_columns_visibility(settings_key)
        tree.bind("<Configure>", lambda e: self.fit_columns(settings_key), add="+")

    def apply_columns_visibility(self, settings_key):
        """Показать только колонки, не отмеченные как скрытые в настройках"""
        cfg = self._column_toggles[settings_key]
        hidden = set(self.load_settings().get(settings_key, []))
        visible = [c for c in cfg["columns"] if c not in hidden] or list(cfg["columns"])
        cfg["tree"]["displaycolumns"] = visible
        self.fit_columns(settings_key)

    def fit_columns(self, settings_key):
        """Растянуть видимые колонки на всю ширину таблицы (пропорционально исходным ширинам)"""
        cfg = self._column_toggles[settings_key]
        tree, base_widths = cfg["tree"], cfg["base_widths"]
        tree_width = tree.winfo_width()
        if tree_width <= 1:  # таблица ещё не отрисована - пересчитаем по <Configure>
            return
        visible = [c for c in tree["displaycolumns"] if c in base_widths]
        base_total = sum(base_widths[c] for c in visible)
        if not base_total:
            return
        used = 0
        for i, column in enumerate(visible):
            if i == len(visible) - 1:
                width = tree_width - used  # последней колонке - остаток, чтобы не было зазора от округления
            else:
                width = int(tree_width * base_widths[column] / base_total)
            used += width
            tree.column(column, width=max(width, 40))

    def toggle_column(self, settings_key, column):
        """Скрыть/показать колонку и сохранить выбор"""
        columns = self._column_toggles[settings_key]["columns"]
        settings = self.load_settings()
        hidden = set(settings.get(settings_key, []))
        if column in hidden:
            hidden.discard(column)
        else:
            # Нельзя скрыть последнюю видимую колонку
            if len([c for c in columns if c not in hidden]) <= 1:
                messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.columns_last_visible"))
                return
            hidden.add(column)
        settings[settings_key] = [c for c in columns if c in hidden]
        self.save_settings(settings)
        self.apply_columns_visibility(settings_key)

    def show_columns_menu(self, settings_key, x_root, y_root):
        """Меню с галочками: какие колонки показывать"""
        cfg = self._column_toggles[settings_key]
        hidden = set(self.load_settings().get(settings_key, []))
        menu = tk.Menu(cfg["tree"], tearoff=0, font=("Segoe UI", 11))
        menu.add_command(label=self.tr("bookings.columns_menu_title"), state="disabled")
        menu.add_separator()
        menu._vars = []  # держим ссылки, чтобы переменные галочек не удалил сборщик мусора
        for column in cfg["columns"]:
            var = tk.BooleanVar(master=menu, value=column not in hidden)
            menu._vars.append(var)
            menu.add_checkbutton(
                label=cfg["tree"].heading(column, "text").rstrip(" ▲▼"),
                variable=var,
                command=lambda c=column: self.toggle_column(settings_key, c)
            )
        menu.tk_popup(x_root, y_root)

    def show_columns_menu_under(self, settings_key, button):
        """Открыть меню колонок под кнопкой"""
        self.show_columns_menu(settings_key, button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    def show_bookings_context_menu(self, event):
        """Показать контекстное меню для записи"""
        if self.bookings_tree.identify_region(event.x, event.y) == "heading":
            self.show_columns_menu("bookings_hidden_columns", event.x_root, event.y_root)
            return
        item = self.bookings_tree.identify_row(event.y)
        if item:
            self.bookings_tree.selection_set(item)
            # Получаем данные записи для проверки статуса
            values = self.bookings_tree.item(item, "values")
            booking_id = values[0] if values else None
            # Проверяем статус - "Начать работу" только для "В ожидании"
            if booking_id:
                booking = self.db.get_booking_by_id(int(booking_id))
                if booking and booking.get("status") == "waiting":
                    self.bookings_context_menu.entryconfig(0, state="normal")
                else:
                    self.bookings_context_menu.entryconfig(0, state="disabled")

                # "Выполнено" доступно только если по записи уже есть хотя бы одна работа
                has_work = bool(self.db.get_work_by_booking_id(int(booking_id)))
                self.bookings_context_menu.entryconfig(7, state="normal" if has_work else "disabled")
            self.bookings_context_menu.post(event.x_root, event.y_root)

    def start_work_from_booking(self):
        """Начать работу по выбранной записи - переход на вкладку добавления работы"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_select_booking"))
            return

        values = self.bookings_tree.item(selection[0], "values")
        if not values:
            return

        booking_id = values[0]
        if not booking_id:
            return

        # Получаем данные записи
        booking = self.db.get_booking_by_id(int(booking_id))
        if not booking:
            messagebox.showerror(self.tr("common.error"), self.tr("bookings.msg_booking_not_found"))
            return

        # Проверяем статус
        if booking.get("status") != "waiting":
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_start_work_only_waiting"))
            return

        # Переключаемся на вкладку "Добавить работу"
        self.switch_tab("works")

        # Обновляем список записей в комбобоксе
        self.refresh_bookings_combo()

        # Форматируем строку для поиска в комбобоксе
        booking_date = booking.get("booking_date")
        if hasattr(booking_date, 'strftime'):
            date_str = booking_date.strftime('%d.%m')
        else:
            date_str = str(booking_date)

        full_name = booking.get("full_name") or self.tr("common.no_name")
        phone = booking.get("phone") or self.tr("common.no_phone")
        search_text = f"{date_str} {booking.get('booking_time')} - {full_name} ({phone})"

        # Ищем и выбираем запись в комбобоксе
        for display_text in self.bookings_data.keys():
            if search_text in display_text or display_text in search_text:
                self.booking_combo.set(display_text)
                self.on_booking_select(display_text)
                break

    def edit_booking_in_add_work(self):
        """Редактировать запись - переход на вкладку добавления работы (без проверки статуса)"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_select_booking"))
            return

        values = self.bookings_tree.item(selection[0], "values")
        if not values:
            return

        booking_id = values[0]
        if not booking_id:
            return
        self.open_booking_in_add_work(int(booking_id))

    def open_booking_in_add_work(self, booking_id):
        """Открыть запись на вкладке "Добавить работу": клиент, машина, работы, запчасти, мастер.
        Если по записи уже есть наряд - форма в режиме редактирования этого наряда"""
        self.works_phone_fill = None
        self.works_number_fill = None
        self.works_clear_marks()
        self.works_unlock_all()
        self.works_record_number = None
        self.works_set_lookup_state(None)
        self.works_editing_title = ""
        self.works_edit_snapshot = None
        self.works_update_edit_banner()

        # Получаем данные записи
        booking = self.db.get_booking_by_id(int(booking_id))
        if not booking:
            messagebox.showerror(self.tr("common.error"), self.tr("bookings.msg_booking_not_found"))
            return

        # Переключаемся на вкладку "Добавить работу"
        self.switch_tab("works")

        # Сохраняем booking_id
        self.selected_booking_id = int(booking_id)

        # Заполняем данные клиента напрямую
        full_name = booking.get("full_name") or ""
        phone = booking.get("phone") or ""
        car_id = booking.get("car_id")

        self.client_name_entry.delete(0, tk.END)
        self.client_name_entry.insert(0, full_name)
        self.set_phone_value(self.client_phone_entry, phone)

        # Загружаем машины клиента
        self.load_client_cars(phone, full_name, car_id)

        # Если есть связанная работа - загружаем её данные
        work = self.db.get_work_by_booking_id(int(booking_id))
        self.editing_work_id = None
        if work:
            # work: (id, worker_id, full_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, booking_id, client_name, client_phone, order_number, car_id)
            work_id = work[0]
            self.editing_work_id = work_id  # без этого add_work() дублирует работу через append_to_work
            worker_id = work[1]
            description = work[3] or ""
            amount = work[4] or 0
            car_brand = work[6] or ""
            car_model = work[7] or ""
            car_number = work[8] or ""
            mileage = work[9] or ""
            order_number = work[14] if len(work) > 14 else ""

            # Заполняем поля машины
            self.car_brand_entry.delete(0, tk.END)
            self.car_brand_entry.insert(0, car_brand)
            self.car_model_entry.delete(0, tk.END)
            self.car_model_entry.insert(0, car_model)
            self.car_number_entry.delete(0, tk.END)
            self.car_number_entry.insert(0, car_number)

            # Заполняем пробег
            self.mileage_entry.delete(0, tk.END)
            self.mileage_entry.insert(0, str(mileage) if mileage else "")

            # Заполняем таблицу работ
            self.works_list = []
            for item in self.works_tree.get_children():
                self.works_tree.delete(item)

            # Пытаемся восстановить точные цены по каждой позиции из items_json
            items_from_json = None
            items_json = self.db.get_work_items_json(work_id)
            if items_json:
                try:
                    parsed = json.loads(items_json)
                    if isinstance(parsed, list) and parsed:
                        items_from_json = [(item["name"], float(item["price"])) for item in parsed]
                except (TypeError, ValueError, KeyError):
                    items_from_json = None

            if items_from_json:
                for name, price in items_from_json:
                    self.works_list.append((name, price))
                    self.works_tree.insert("", tk.END, values=(name, self.format_currency(price)))
            elif description:
                # Записи без items_json (созданные до этого исправления) — цена делится поровну между строками
                lines = [l.strip() for l in description.split("\n") if l.strip()]
                if len(lines) > 1:
                    price_each = float(amount or 0) / len(lines)
                    for line in lines:
                        self.works_list.append((line, price_each))
                        self.works_tree.insert("", tk.END, values=(line, self.format_currency(price_each)))
                else:
                    self.works_list.append((description, float(amount or 0)))
                    self.works_tree.insert("", tk.END, values=(description, self.format_currency(float(amount or 0))))

            # Выбираем мастера
            if worker_id:
                for name, wid in self.workers_data.items():
                    if wid == worker_id:
                        self.worker_combo.set(name)
                        break

            # Загружаем запчасти
            self.parts_list = []
            self.warehouse_part_ids = {}
            self.works_linked_wh_parts = {}
            # Очищаем таблицу запчастей
            for item in self.parts_tree.get_children():
                self.parts_tree.delete(item)

            # Детали склада, установленные в этот наряд: строку наряда узнаём по названию
            # (у оплаченных заранее - с пометкой). Убрали такую строку и сохранили - деталь вернётся на склад
            linked = list(self.db.get_warehouse_parts_by_work_id(work_id))
            parts = self.db.get_parts_by_work_id(work_id)
            if parts:
                for part_name, part_price in parts:
                    match = None
                    for wh_part in linked:
                        wh_id, wh_name, _, _, _, wh_paid = wh_part
                        names = {wh_name, self.warehouse_part_list_entry(wh_name, 0, True)[0]}
                        if part_name in names:
                            match = wh_part
                            break
                    self.parts_list.append((part_name, float(part_price)))
                    item_id = self.parts_tree.insert("", tk.END,
                                                     values=self.part_row_values(part_name, part_price,
                                                                                 match[3] if match else None),
                                                     tags=("warehouse",) if match else ())
                    if match:
                        linked.remove(match)
                        self.warehouse_part_ids[item_id] = match[0]
                        self.works_linked_wh_parts[match[0]] = match

            self.update_total_cost()

        # Заполняем VIN: из машины наряда, а если наряда ещё нет - из машины записи
        vin = (work[10] if work else None) or booking.get("car_vin") or ""
        self.vin_var.set(vin)

        # Проверяем склад на наличие новых запчастей для этого авто
        self.check_warehouse_for_car(self.car_number_entry.get().strip())

        # Полоска "Редактирование записи ..." (машина - как в сохранённом наряде)
        self.works_editing_title = self.works_car_title()
        self.works_update_edit_banner()

        # Обновляем комбобокс записей
        self.refresh_bookings_combo()

        # Устанавливаем текст в комбобоксе
        booking_date = booking.get("booking_date")
        if hasattr(booking_date, 'strftime'):
            date_str = booking_date.strftime('%d.%m')
        else:
            date_str = str(booking_date)
        display_text = f"{date_str} {booking.get('booking_time')} - {full_name} ({phone})"
        self.booking_combo.set(display_text)

        # Как форма выглядит сразу после открытия - чтобы потом понять, есть ли несохранённые правки
        self.works_edit_snapshot = self.works_form_snapshot()
        # Данные записи встали - поля закрыты; госномер записи запоминаем (сменят на чужой - спросим)
        self.works_lock_filled()
        self.works_record_number = self.car_number_entry.get().strip()

    # ===== Окна "Информация" (наряд) и "О клиенте" =====

    _prepaid_markers = None

    def split_prepaid(self, name):
        """Запчасть, оплаченная заранее, хранится в наряде за 0 с пометкой в названии: "Амортизатор (оплачено ранее)".
        Возвращает (название без пометки, оплачено_ли). Пометку узнаём на любом языке интерфейса"""
        if AutoServiceApp._prepaid_markers is None:
            markers = {self.tr("warehouse.already_paid_marker")}
            locales_dir = os.path.join(BASE_PATH, "config", "locales")
            try:
                for file_name in os.listdir(locales_dir):
                    if file_name.endswith(".json"):
                        with open(os.path.join(locales_dir, file_name), encoding="utf-8") as f:
                            marker = json.load(f).get("warehouse.already_paid_marker")
                        if marker:
                            markers.add(marker)
            except OSError:
                pass
            AutoServiceApp._prepaid_markers = markers
        text = self.clean_item_name(name)
        for marker in AutoServiceApp._prepaid_markers:
            suffix = f"({marker})"
            if text.endswith(suffix):
                return text[:-len(suffix)].rstrip(), True
        return text, False

    def part_row_values(self, name, price, original_price=None):
        """Как запчасть показывать: (название, цена, зачёркнутая цена).
        Оплаченная заранее - без пометки в названии, вместо "0 руб." - "оплачено ранее",
        а её настоящая цена (со склада, если известна) - зачёркнутой"""
        clean, prepaid = self.split_prepaid(name)
        if prepaid:
            struck = self.format_currency(float(original_price)) if original_price else ""
            return clean, self.tr("warehouse.already_paid_marker"), struck
        return clean, self.format_currency(float(price or 0)), ""

    def prepaid_original_price(self, prices_by_work, work_id, name):
        """Настоящая цена запчасти "оплачено ранее" по данным склада (или None)"""
        clean, prepaid = self.split_prepaid(name)
        if not prepaid:
            return None
        return (prices_by_work or {}).get(work_id, {}).get(clean)

    @staticmethod
    def clean_item_name(name):
        """Название работы / запчасти в одну строку (из сайтов поставщиков копируют с переносами)"""
        return " ".join(str(name or "").split())

    def info_item_rows(self, parent, items, wrap=400):
        """Строки "название ... цена" (полосками, как в "Добавить работу"); items: [(название, цена)]"""
        for i, item in enumerate(items):
            name, price = item[0], item[1]
            original = item[2] if len(item) > 2 else None
            row = ctk.CTkFrame(parent, fg_color="#f7f9fa" if i % 2 == 0 else "white", corner_radius=6)
            row.pack(fill=tk.X, pady=1)
            shown_name, price_text, struck = self.part_row_values(name, price, original)
            prepaid = price_text == self.tr("warehouse.already_paid_marker")
            ctk.CTkLabel(row, text=price_text, font=("Arial", 13, "italic") if prepaid else ("Arial", 13),
                         text_color="#2e7d32" if prepaid else None, anchor="e").pack(side=tk.RIGHT, padx=(6, 10), pady=4)
            if struck:
                ctk.CTkLabel(row, text=struck, text_color="gray50", anchor="e",
                             font=ctk.CTkFont(family="Arial", size=13, overstrike=True)).pack(side=tk.RIGHT, pady=4)
            ctk.CTkLabel(row, text=shown_name, font=("Arial", 13), anchor="w", justify="left",
                         wraplength=wrap).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0), pady=4)

    def info_summary_tiles(self, parent, tiles):
        """Плитки сводки в строку: [(подпись, значение, выделить)]"""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill=tk.X, pady=(0, 8))
        for i, (label, value, accent) in enumerate(tiles):
            bar.grid_columnconfigure(i, weight=1, uniform="tile")
            tile = ctk.CTkFrame(bar, corner_radius=10, border_width=1,
                                fg_color="#e8f5e9" if accent else "white",
                                border_color="#a5d6a7" if accent else self.FORM_CARD_BORDER)
            tile.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            ctk.CTkLabel(tile, text=label, font=("Arial", 12), text_color="#607d8b", anchor="w").pack(
                fill=tk.X, padx=12, pady=(8, 0))
            ctk.CTkLabel(tile, text=value, font=("Arial", 17, "bold"), anchor="w",
                         text_color="#2e7d32" if accent else "#263238").pack(fill=tk.X, padx=12, pady=(0, 8))

    def info_window(self, title, width):
        """Окно-карточка (наряд / клиент): светлый фон, прокрутка, кнопки снизу"""
        window = ctk.CTkToplevel(self.root)
        window.withdraw()
        window.title(title)
        window.transient(self.root)
        window.configure(fg_color="#eef1f4")
        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.pack(side=tk.BOTTOM, fill=tk.X, padx=18, pady=(6, 14))
        body = ctk.CTkScrollableFrame(window, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        width_guard = tk.Frame(body, width=width - 60, height=0)
        width_guard.pack()
        return window, body, buttons

    def info_window_show(self, window, width, body):
        """Высота окна - по содержимому, но не выше 85% экрана; по центру экрана"""
        window.update_idletasks()
        inner_h = max(body.winfo_reqheight(), 200)
        buttons_h = max((w.winfo_reqheight() for w in window.winfo_children() if w is not body.master), default=60)
        height = min(inner_h + buttons_h + 70, int(window.winfo_screenheight() * 0.85))
        x = (window.winfo_screenwidth() - width) // 2
        y = max(0, (window.winfo_screenheight() - height) // 2 - 20)
        tk.Wm.wm_geometry(window, f"{width}x{height}+{x}+{y}")
        window.deiconify()
        window.lift()
        window.focus_force()
        window.grab_set()
        window.bind("<Escape>", lambda e: window.destroy())

    def show_booking_info(self):
        """Показать окно с информацией о записи и работе"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_select_booking"))
            return
        values = self.bookings_tree.item(selection[0], "values")
        if values and values[0]:
            self.show_booking_info_window(int(values[0]))

    def show_booking_info_window(self, booking_id, parent_window=None):
        """Наряд: шапка (дата, мастер, клиент, машина), сводка сумм, работы и запчасти списком"""
        booking = self.db.get_booking_by_id(int(booking_id))
        if not booking:
            messagebox.showerror(self.tr("common.error"), self.tr("bookings.msg_booking_not_found"))
            return
        works = self.db.get_all_works_by_booking_id(int(booking_id))

        primary = works[0] if works else None
        worker_name = primary[2] if primary else None
        mileage = primary[9] if primary else None
        order_number = primary[14] if primary else None
        vin = (primary[10] if primary else None) or booking.get("car_vin")
        title = self.tr("bookings.order_number_label", order_number=order_number) if order_number \
            else self.tr("bookings.info_window_title")

        width = 640
        window, body, buttons = self.info_window(title, width)
        if parent_window is not None:
            window.transient(parent_window)

        # --- шапка: номер, статус, когда и кто ---
        status = booking.get("status", "waiting")
        status_style = {"waiting": ("#f59e0b", "⏳ " + self.tr("bookings.filter_waiting")),
                        "in_progress": ("#3b82f6", "🔧 " + self.tr("bookings.filter_in_progress")),
                        "completed": ("#22c55e", "✅ " + self.tr("bookings.info_status_completed")),
                        "cancelled": ("#ef4444", "❌ " + self.tr("bookings.status_cancelled"))}
        badge_color, badge_text = status_style.get(status, ("#6b7280", status))
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill=tk.X, padx=4, pady=(4, 0))
        ctk.CTkLabel(head, text=title, font=("Segoe UI", 20, "bold"), anchor="w").pack(side=tk.LEFT)
        ctk.CTkLabel(head, text=f"  {badge_text}  ", font=("Arial", 13, "bold"), fg_color=badge_color,
                     text_color="white", corner_radius=8).pack(side=tk.RIGHT)

        booking_date = booking.get("booking_date")
        date_str = booking_date.strftime('%d.%m.%Y') if hasattr(booking_date, "strftime") else str(booking_date or "")
        when = f"{date_str}, {booking.get('booking_time') or ''}".strip(", ")
        if worker_name:
            when += " · " + self.tr("bookings.info_master", name=worker_name)
        ctk.CTkLabel(body, text=when, font=("Arial", 13), text_color="#607d8b", anchor="w").pack(
            fill=tk.X, padx=4, pady=(0, 8))

        # --- клиент и машина ---
        _, card = self.form_section(body, self.tr("works.section_client_car"))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill=tk.X)
        ctk.CTkLabel(row, text=booking.get("full_name") or self.tr("bookings.name_not_specified"),
                     font=("Arial", 15, "bold"), anchor="w").pack(side=tk.LEFT)
        phone = booking.get("phone")
        if phone:
            self.add_copy_button(row, phone).pack(side=tk.RIGHT)
            ctk.CTkLabel(row, text=format_phone_ru(phone_mask_digits(phone)) if len(phone_mask_digits(phone)) == 10
                         else phone, font=("Arial", 14), anchor="e").pack(side=tk.RIGHT, padx=(0, 4))
        car_line = booking.get("car_info") or ""
        if mileage:
            car_line += ("  ·  " if car_line else "") + self.tr("bookings.info_mileage", mileage=mileage)
        if car_line:
            ctk.CTkLabel(card, text=car_line, font=("Arial", 14), anchor="w").pack(fill=tk.X, pady=(4, 0))
        if vin:
            vin_row = ctk.CTkFrame(card, fg_color="transparent")
            vin_row.pack(fill=tk.X, pady=(2, 0))
            ctk.CTkLabel(vin_row, text=f"VIN {vin}", font=("Consolas", 13), text_color="#455a64").pack(side=tk.LEFT)
            self.add_copy_button(vin_row, vin).pack(side=tk.LEFT, padx=(6, 0))
        if booking.get("username"):
            ctk.CTkLabel(card, text=f"Telegram: @{booking['username']}", font=("Arial", 12),
                         text_color="#607d8b", anchor="w").pack(fill=tk.X, pady=(2, 0))
        if booking.get("notes"):
            ctk.CTkLabel(card, text="📝 " + booking["notes"], font=("Arial", 13), anchor="w", justify="left",
                         wraplength=width - 100).pack(fill=tk.X, pady=(4, 0))

        # --- работы и запчасти ---
        work_items, part_items = [], []
        multiple = len(works) > 1
        wh_prices = self.db.get_warehouse_prices_by_work_ids([w[0] for w in works])
        for work in works:
            work_id, description, amount = work[0], work[3], float(work[4] or 0)
            items = self.get_work_line_items(work_id, description, amount)
            parts = self.db.get_parts_by_work_id(work_id) or []
            if multiple:
                label = self.tr("bookings.order_number_label", order_number=work[14]) if work[14] else ""
                work_items.append((label, None))
                if parts:
                    part_items.append((label, None))
            work_items += [(n, p) for n, p in items]
            part_items += [(n, float(p), self.prepaid_original_price(wh_prices, work_id, n)) for n, p in parts]
        works_sum = sum(item[1] for item in work_items if item[1] is not None)
        parts_sum = sum(item[1] for item in part_items if item[1] is not None)

        if not works:
            _, card = self.form_section(body, self.tr("works.section_works"))
            ctk.CTkLabel(card, text=self.tr("bookings.no_works_yet"), text_color="gray45",
                         font=("Arial", 13), anchor="w").pack(fill=tk.X)
        else:
            self.info_summary_tiles(body, [(self.tr("works.section_works"), self.format_currency(works_sum), False),
                                           (self.tr("works.section_parts"), self.format_currency(parts_sum), False),
                                           (self.tr("bookings.sum_total"), self.format_currency(works_sum + parts_sum), True)])
            for title_key, items in (("works.section_works", work_items), ("works.section_parts", part_items)):
                if not items:
                    continue
                _, card = self.form_section(body, self.tr(title_key))
                for chunk_title, chunk in self._split_by_headers(items):
                    if chunk_title:
                        ctk.CTkLabel(card, text=chunk_title, font=("Arial", 12, "bold"), text_color="#607d8b",
                                     anchor="w").pack(fill=tk.X, pady=(4, 2))
                    self.info_item_rows(card, chunk, wrap=width - 230)

        # --- кнопки ---
        def edit():
            window.destroy()
            if parent_window is not None and parent_window.winfo_exists():
                parent_window.destroy()
            self.open_booking_in_add_work(int(booking_id))

        ctk.CTkButton(buttons, text="✎  " + self.tr("bookings.ctx_edit"), command=edit, height=40, width=170,
                      corner_radius=8, font=("Arial", 14, "bold"), fg_color="#1565c0",
                      hover_color="#0d47a1").pack(side=tk.LEFT)
        if works:
            ctk.CTkButton(buttons, text="📄  PDF", command=lambda: self.save_booking_to_pdf(booking, works),
                          height=40, width=110, corner_radius=8, font=("Arial", 14),
                          fg_color="#e3f2fd", text_color="#0d47a1", hover_color="#bbdefb").pack(side=tk.LEFT, padx=8)
        ctk.CTkButton(buttons, text=self.tr("common.close"), command=window.destroy, height=40, width=120,
                      corner_radius=8, font=("Arial", 14), fg_color="transparent", border_width=1,
                      border_color="#9e9e9e", text_color="#424242", hover_color="#e0e0e0").pack(side=tk.RIGHT)
        self.info_window_show(window, width, body)

    @staticmethod
    def _split_by_headers(items):
        """[(заголовок, None), (название, цена)...] -> [(заголовок, [(название, цена)...])]"""
        chunks = [("", [])]
        for item in items:
            if item[1] is None:
                chunks.append((item[0], []))
            else:
                chunks[-1][1].append(item)
        return [(t, c) for t, c in chunks if c]

    def show_client_info(self):
        """Показать окно с информацией о клиенте: машины и история"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_select_booking"))
            return
        values = self.bookings_tree.item(selection[0], "values")
        if not values:
            return

        # values: (id, order_number, date, time, name, phone, username, car_info, notes, status)
        booking_id = values[0] if len(values) > 0 else None
        client_name = values[4] if len(values) > 4 and values[4] != "-" else None
        client_phone = values[5] if len(values) > 5 and values[5] != "-" else None
        client_telegram = values[6] if len(values) > 6 and values[6] != "-" else None

        telegram_user_id = None
        if booking_id:
            booking = self.db.get_booking_by_id(int(booking_id))
            if booking:
                telegram_user_id = booking.get("user_id")
        if not telegram_user_id and not client_phone and not client_name:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_no_client_data"))
            return

        cars, history = [], []
        if telegram_user_id:
            cars = self.db.get_client_cars_by_telegram_user_id(telegram_user_id)
            history = self.db.get_client_history(telegram_user_id=telegram_user_id)
        if not cars and client_phone:
            cars = self.db.get_client_cars_by_phone(client_phone)
        if not cars and client_name:
            cars = self.db.get_client_cars_by_name(client_name)
        if not history:
            history = self.db.get_client_history(phone=client_phone, name=client_name)

        # Суммы запчастей по всем визитам - одним запросом
        parts_totals = self.db.get_parts_totals_by_work_ids([w[0] for w in history])
        visits = []
        for work in history:
            work_id, work_date, order_number, worker, brand, model, number, mileage, description, amount = work[:10]
            total = float(amount or 0) + parts_totals.get(work_id, 0.0)
            visits.append({"id": work_id, "date": work_date, "order": order_number, "worker": worker,
                           "car": " ".join(x for x in (brand, model) if x), "number": number or "",
                           "mileage": mileage, "description": description, "amount": float(amount or 0), "total": total})

        width = 700
        window, body, buttons = self.info_window(
            self.tr("bookings.client_window_title", name=client_name or client_phone), width)

        # --- шапка: имя, телефон ---
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill=tk.X, padx=4, pady=(4, 2))
        ctk.CTkLabel(head, text=client_name or self.tr("bookings.name_not_specified"),
                     font=("Segoe UI", 20, "bold"), anchor="w").pack(side=tk.LEFT)
        if client_phone:
            self.add_copy_button(head, client_phone).pack(side=tk.RIGHT)
            digits = phone_mask_digits(client_phone)
            ctk.CTkLabel(head, text=format_phone_ru(digits) if len(digits) == 10 else client_phone,
                         font=("Arial", 15), anchor="e").pack(side=tk.RIGHT, padx=(0, 4))
        if client_telegram:
            ctk.CTkLabel(body, text=f"Telegram: {client_telegram}", font=("Arial", 12), text_color="#607d8b",
                         anchor="w").pack(fill=tk.X, padx=4)

        # --- сводка ---
        def fmt_date(d):
            return d.strftime('%d.%m.%Y') if hasattr(d, "strftime") else (str(d) if d else "—")

        last_visit = max((v["date"] for v in visits if v["date"]), default=None)
        ctk.CTkFrame(body, fg_color="transparent", height=6).pack()
        self.info_summary_tiles(body, [(self.tr("bookings.client_visits"), str(len(visits)), False),
                                       (self.tr("bookings.client_total"),
                                        self.format_currency(sum(v["total"] for v in visits)), True),
                                       (self.tr("bookings.client_last_visit"), fmt_date(last_visit), False)])

        # --- машины: плашки, клик - фильтр истории ---
        car_filter = [None]
        chips_row = None
        if cars:
            _, card = self.form_section(body, self.tr("bookings.client_cars_section"))
            chips_row = ctk.CTkFrame(card, fg_color="transparent")
            chips_row.pack(fill=tk.X)
            vins = [(f"{(b or '')} {(m or '')}".strip(), n, v) for b, m, n, v in cars]
            for title, number, vin in vins:
                if vin:
                    vin_row = ctk.CTkFrame(card, fg_color="transparent")
                    vin_row.pack(fill=tk.X, pady=(4, 0))
                    ctk.CTkLabel(vin_row, text=f"{title} {number or ''} — VIN {vin}", font=("Consolas", 12),
                                 text_color="#455a64").pack(side=tk.LEFT)
                    self.add_copy_button(vin_row, vin).pack(side=tk.LEFT, padx=(6, 0))

        # --- история: строка на визит, клик - раскрыть, двойной клик - открыть наряд ---
        _, history_card = self.form_section(body, self.tr("bookings.client_history_section"))
        if visits:
            ctk.CTkLabel(history_card, text=self.tr("bookings.client_history_hint"), font=("Arial", 11),
                         text_color="gray50", anchor="w").pack(fill=tk.X, pady=(0, 4))
        history_list = ctk.CTkFrame(history_card, fg_color="transparent")
        history_list.pack(fill=tk.X)

        def open_visit(visit):
            work = self.db.get_work_by_id(visit["id"])
            if work and work[11]:
                self.show_booking_info_window(int(work[11]), parent_window=window)

        def draw_history():
            for w in history_list.winfo_children():
                w.destroy()
            shown = [v for v in visits if car_filter[0] is None or v["number"] == car_filter[0]]
            if not shown:
                ctk.CTkLabel(history_list, text=self.tr("bookings.history_empty"), text_color="gray45",
                             font=("Arial", 13), anchor="w").pack(fill=tk.X)
            for i, visit in enumerate(shown):
                item = ctk.CTkFrame(history_list, fg_color="#f7f9fa" if i % 2 == 0 else "white", corner_radius=6)
                item.pack(fill=tk.X, pady=1)
                line = ctk.CTkFrame(item, fg_color="transparent", cursor="hand2")
                line.pack(fill=tk.X)
                arrow = ctk.CTkLabel(line, text="▸", width=16, font=("Arial", 13), cursor="hand2")
                arrow.pack(side=tk.LEFT, padx=(8, 2), pady=5)
                parts_txt = [fmt_date(visit["date"]), f"{visit['car']} {visit['number']}".strip()]
                if visit["worker"]:
                    parts_txt.append(visit["worker"])
                text = ctk.CTkLabel(line, text="   ".join(parts_txt), font=("Arial", 13), anchor="w", cursor="hand2")
                text.pack(side=tk.LEFT, fill=tk.X, expand=True)
                total = ctk.CTkLabel(line, text=self.format_currency(visit["total"]), font=("Arial", 13, "bold"),
                                     cursor="hand2")
                total.pack(side=tk.RIGHT, padx=10)
                details = ctk.CTkFrame(item, fg_color="transparent")
                opened = [False]

                def toggle(event=None, visit=visit, details=details, arrow=arrow, opened=opened):
                    if opened[0]:
                        details.pack_forget()
                        arrow.configure(text="▸")
                    else:
                        if not details.winfo_children():
                            items = self.get_work_line_items(visit["id"], visit["description"], visit["amount"])
                            parts = self.db.get_parts_by_work_id(visit["id"]) or []
                            wh_prices = self.db.get_warehouse_prices_by_work_ids([visit["id"]]) if parts else {}
                            if visit["order"]:
                                ctk.CTkLabel(details, text=self.tr("bookings.order_number_label", order_number=visit["order"])
                                             + (f"  ·  {self.tr('bookings.info_mileage', mileage=visit['mileage'])}"
                                                if visit["mileage"] else ""),
                                             font=("Arial", 11), text_color="#607d8b", anchor="w").pack(fill=tk.X, padx=26)
                            self.info_item_rows(details, items + [
                                (n, float(p), self.prepaid_original_price(wh_prices, visit["id"], n)) for n, p in parts],
                                wrap=width - 260)
                        details.pack(fill=tk.X, padx=(20, 8), pady=(0, 6))
                        arrow.configure(text="▾")
                    opened[0] = not opened[0]

                for w in (line, arrow, text, total):
                    w.bind("<Button-1>", toggle)
                    w.bind("<Double-Button-1>", lambda e, v=visit: open_visit(v))

        def set_filter(number):
            car_filter[0] = number
            draw_chips()
            draw_history()

        def draw_chips():
            if chips_row is None:
                return
            for w in chips_row.winfo_children():
                w.destroy()
            options = [(self.tr("bookings.client_all_cars"), None)] + \
                      [(f"{(b or '')} {(m or '')}  {n or ''}".strip(), n) for b, m, n, _ in cars]
            if len(cars) < 2:
                options = options[1:]   # одна машина - фильтр не нужен
            for label, number in options:
                selected = number == car_filter[0] and len(cars) > 1
                ctk.CTkButton(chips_row, text=label, width=10, height=28, corner_radius=14,
                              font=("Arial", 13, "bold" if selected else "normal"),
                              fg_color="#1565c0" if selected else "transparent",
                              hover_color="#0d47a1" if selected else "#e3f2fd",
                              text_color="white" if selected else "#0d47a1", border_width=0 if selected else 1,
                              border_color="#90caf9",
                              command=(lambda n=number: set_filter(n)) if len(cars) > 1 else None).pack(
                    side=tk.LEFT, padx=(0, 6), pady=2)

        draw_chips()
        draw_history()

        ctk.CTkButton(buttons, text=self.tr("common.close"), command=window.destroy, height=40, width=120,
                      corner_radius=8, font=("Arial", 14), fg_color="transparent", border_width=1,
                      border_color="#9e9e9e", text_color="#424242", hover_color="#e0e0e0").pack(side=tk.RIGHT)
        self.info_window_show(window, width, body)

    def edit_client_info(self):
        """Открыть окно редактирования имени/телефона клиента — исправление
        опечаток оператором (например, неверно введённый номер телефона)."""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_select_booking"))
            return

        values = self.bookings_tree.item(selection[0], "values")
        if not values:
            return

        booking_id = values[0] if len(values) > 0 else None
        booking = self.db.get_booking_by_id(int(booking_id)) if booking_id else None
        client_id = booking.get("client_id") if booking else None

        if not client_id:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_no_client_data"))
            return

        client = self.db.get_client_by_id(client_id)
        if not client:
            messagebox.showwarning(self.tr("common.attention"), self.tr("bookings.msg_no_client_data"))
            return

        dialog = ctk.CTkToplevel(self.root)
        dialog.title(self.tr("bookings.edit_client_title"))
        dialog.geometry("360x330")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(padx=25, pady=20, fill="x")

        ctk.CTkLabel(form, text=self.tr("bookings.client_name_label"), anchor="w").pack(fill="x", pady=(0, 2))
        name_var = tk.StringVar(value=client.get("full_name") or "")
        ctk.CTkEntry(form, textvariable=name_var, height=36).pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(form, text=self.tr("bookings.col_phone"), anchor="w").pack(fill="x", pady=(0, 2))
        phone_var = tk.StringVar(value=client.get("phone") or "")
        ctk.CTkEntry(form, textvariable=phone_var, height=36).pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(form, text=self.tr("bookings.client_telegram_label"), anchor="w").pack(fill="x", pady=(0, 2))
        telegram_var = tk.StringVar(value=client.get("tg_username") or "")
        ctk.CTkEntry(form, textvariable=telegram_var, placeholder_text="username", height=36).pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(form, text=self.tr("bookings.client_telegram_hint"), anchor="w", justify="left",
                     font=("Segoe UI", 10), text_color="gray", wraplength=300).pack(fill="x", pady=(0, 12))

        def on_save():
            self.db.update_client(client_id, name_var.get().strip(), phone_var.get().strip(), telegram_var.get().strip())
            dialog.destroy()
            messagebox.showinfo(self.tr("common.success"), self.tr("bookings.msg_client_updated"))
            self.refresh_bookings()

        btn_row = ctk.CTkFrame(form, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(btn_row, text=self.tr("common.save"), command=on_save,
                      fg_color="#4caf50", hover_color="#388e3c", width=130).pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(btn_row, text=self.tr("common.cancel"), command=dialog.destroy,
                      fg_color="gray", width=130).pack(side=tk.LEFT)


_SINGLE_INSTANCE_MUTEX_NAME = "AutoService_Alexan_SingleInstance_Mutex"


def _activate_existing_window():
    """Находит окно уже запущенного экземпляра приложения и выводит его на передний план."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    current_pid = os.getpid()
    exe_name = os.path.basename(
        sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    ).lower()

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    SW_RESTORE = 9

    found_hwnd = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_handler(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == current_pid:
            return True
        hproc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
        if hproc:
            try:
                buf = ctypes.create_unicode_buffer(260)
                if psapi.GetModuleBaseNameW(hproc, None, buf, 260) and buf.value.lower() == exe_name:
                    found_hwnd.append(hwnd)
                    return False
            finally:
                kernel32.CloseHandle(hproc)
        return True

    user32.EnumWindows(enum_handler, 0)

    if found_hwnd:
        hwnd = found_hwnd[0]
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)


def _ensure_single_instance():
    """Не даёт запустить второй экземпляр приложения: если один уже работает,
    активирует его окно и завершает текущий (новый) процесс."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ERROR_ALREADY_EXISTS = 183

    handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
    already_running = handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    if not already_running:
        # Хендл держим живым до конца процесса (не закрываем) — ОС освободит его сама при выходе
        global _single_instance_mutex_handle
        _single_instance_mutex_handle = handle
        return

    try:
        _activate_existing_window()
    except Exception:
        pass
    sys.exit(0)


def main():
    _ensure_single_instance()

    from license import check_license
    from login_window import LoginWindow
    import tkinter.messagebox as _mb

    # 1. Проверка лицензии
    ok, msg = check_license()
    if not ok:
        import tkinter as _tk
        _r = _tk.Tk()
        _r.withdraw()
        _mb.showerror("Доступ запрещён", msg)
        _r.destroy()
        sys.exit(1)

    # 2. Авторизация + цикл повторного входа
    _db = Database()
    while True:
        login_win = LoginWindow(_db)
        login_win.mainloop()
        user = login_win.logged_user
        login_win.destroy()

        if user is None:
            sys.exit(0)

        # 3. Проверка обновлений — периодическая, работает всё время,
        # пока приложение открыто (не только при входе).
        try:
            from updater import check_for_update, show_update_dialog, apply_update, _log_error
            _updater_available = True
        except Exception as _upd_import_err:
            _updater_available = False
            try:
                import traceback as _tb
                _log_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
                with open(os.path.join(_log_dir, "updater_debug.log"), "a", encoding="utf-8") as _f:
                    _f.write("\n[main] импорт updater.py не удался:\n")
                    _f.write("".join(_tb.format_exception(type(_upd_import_err), _upd_import_err, _upd_import_err.__traceback__)))
            except Exception:
                pass

        # 4. Основное приложение
        root = ctk.CTk()
        # Собираем интерфейс в скрытом окне и показываем его один раз, сразу развёрнутым -
        # иначе видно, как окно открывается маленьким, разворачивается и перерисовывается
        root.withdraw()
        app = AutoServiceApp(root, current_user=user)
        # update() обязателен до показа: при первом update()/mainloop() CustomTkinter перекрашивает
        # заголовок окна и возвращает окну запомненное состояние. Без этого вызова mainloop()
        # снова спрятал бы окно, и программа "не запускалась" бы
        root.update()
        root.state('zoomed')  # Открытие во весь экран (заодно показывает окно)

        if _updater_available:
            # ВРЕМЕННО: 5 минут — для проверки, что механизм работает.
            # После теста поставить обратно 6 часов: 6 * 60 * 60 * 1000
            UPDATE_CHECK_INTERVAL_MS = 5 * 60 * 1000

            def _check_and_offer_update():
                # Запрос к серверу - в фоновом потоке, чтобы интерфейс не замирал на время сети.
                # Окна Tk трогаем только из главного потока, поэтому результат забираем опросом
                result = {}

                def _worker():
                    try:
                        result["upd"] = check_for_update()
                    except Exception as e:
                        result["error"] = e

                thread = threading.Thread(target=_worker, daemon=True)
                thread.start()

                def _wait_result():
                    if thread.is_alive():
                        root.after(200, _wait_result)
                        return
                    try:
                        if "error" in result:
                            _log_error("_check_and_offer_update", result["error"])
                        elif result.get("upd"):
                            upd = result["upd"]
                            if show_update_dialog(upd, parent=root):
                                apply_update(upd["download_url"], parent_widget=root, forced=upd.get("forced", False))
                    except Exception as e:
                        _log_error("_check_and_offer_update", e)
                    finally:
                        root.after(UPDATE_CHECK_INTERVAL_MS, _check_and_offer_update)

                _wait_result()

            root.after(800, _check_and_offer_update)

        # 5. Автоматический бэкап -- проверяем раз в 30 минут, реально
        # бэкапим не чаще раза в сутки (см. backup.py и вкладку настроек
        # "Резервные копии"). Локальная копия в папке Backup рядом с
        # программой делается ВСЕГДА, без какой-либо настройки; облачная
        # папка (Google Диск/Яндекс.Диск) -- дополнительно, только если
        # включена галочка "автобэкап" и папка указана.
        BACKUP_CHECK_INTERVAL_MS = 30 * 60 * 1000

        def _auto_backup_tick():
            try:
                settings = app.load_settings()
                last = settings.get('backup_last')
                need_backup = True
                if last:
                    try:
                        need_backup = (datetime.now() - datetime.fromisoformat(last)) >= timedelta(hours=24)
                    except Exception:
                        need_backup = True
                if need_backup:
                    app._do_backup_now(silent=True, include_cloud=settings.get('backup_auto', True))
            except Exception:
                pass
            finally:
                root.after(BACKUP_CHECK_INTERVAL_MS, _auto_backup_tick)

        root.after(10_000, _auto_backup_tick)

        # 6. Синхронизация с сайтом онлайн-записи (если настроена в config/.env)
        app.start_web_sync()

        root.mainloop()

        # Если нажал «Выйти» — снова показываем логин, иначе выходим
        if not app.logged_out:
            break


if __name__ == "__main__":
    main()