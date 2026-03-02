# -*- coding: utf-8 -*-
"""
Калькулятор для автосервиса
Приложение для учёта работ сотрудников
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date
from tkcalendar import DateEntry
import json
import qrcode
from PIL import Image, ImageTk
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import tempfile
import re
import requests
import customtkinter as ctk
from dotenv import load_dotenv

# Импорт класса для работы с базой данных
from database import Database


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

# Настройка темы CustomTkinter
ctk.set_appearance_mode("light")  # "dark" или "light"
ctk.set_default_color_theme("blue")  # "blue", "green", "dark-blue"


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

    def __init__(self, treeview, columns=None):
        self.treeview = treeview
        self.columns = columns  # Список колонок для которых показывать tooltip (None = все)
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

        # Преобразуем #1, #2 в индекс колонки
        col_index = int(column.replace('#', '')) - 1
        columns = self.treeview['columns']

        if col_index < 0 or col_index >= len(columns):
            self.hide_tooltip()
            return

        col_name = columns[col_index]

        # Проверяем, нужно ли показывать tooltip для этой колонки
        if self.columns and col_name not in self.columns:
            self.hide_tooltip()
            return

        # Если это тот же элемент и колонка - не обновляем
        if item == self.current_item and column == self.current_column:
            return

        self.current_item = item
        self.current_column = column

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

        # Разбиваем длинный текст на строки
        max_width = 60
        lines = []
        words = text.split()
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


class AutoServiceApp:
    """Главный класс приложения"""

    def __init__(self, root):
        self.root = root
        self.root.title("Калькулятор автосервиса")
        self.root.minsize(800, 600)
        self.root.after(100, lambda: self.root.state('zoomed'))  # Открытие во весь экран

        self.db = Database()

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
            text="Меню",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.sidebar_title.pack(pady=(20, 20))

        # Пункты меню
        self.menu_items = [
            ("Добавить работу", "works"),
            ("Записи", "bookings"),
            ("Склад", "warehouse"),
            ("Отчёты", "reports"),
            ("Финансы", "expenses"),
            ("Настройки", "settings")
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
                fg_color="transparent" if name != "works" else None,
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                anchor="w",
                font=ctk.CTkFont(size=14)
            )
            btn.pack(fill=tk.X, pady=3, padx=10)
            self.menu_buttons[name] = btn

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

        # Вкладка отчётов
        self.reports_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["reports"] = self.reports_frame
        self.setup_reports_tab()

        # Вкладка расходов и доходов
        self.expenses_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["expenses"] = self.expenses_frame
        self.setup_expenses_tab()

        # Вкладка настроек с подвкладками
        self.add_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.content_frames["settings"] = self.add_frame

        # Создаём вложенный Tabview для подвкладок настроек
        self.add_notebook = ctk.CTkTabview(self.add_frame)
        self.add_notebook.pack(fill=tk.BOTH, expand=True)

        # Показываем первую вкладку по умолчанию
        self.works_frame.pack(fill=tk.BOTH, expand=True)

        # Подвкладка работников
        self.add_notebook.add("Мастера")
        self.workers_frame = self.add_notebook.tab("Мастера")
        self.setup_workers_tab()

        # Подвкладка марок и моделей
        self.add_notebook.add("Марки и модели")
        self.cars_frame = self.add_notebook.tab("Марки и модели")
        self.setup_cars_tab()

        # Подвкладка ключевых слов
        self.add_notebook.add("Ключевые слова")
        self.keywords_frame = self.add_notebook.tab("Ключевые слова")
        self.setup_keywords_tab()

        # Загрузка данных
        self.refresh_workers_list()
        self.refresh_workers_combo()
        self.refresh_expenses()
        self.refresh_keywords_list()
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
                btn.configure(fg_color=("gray75", "gray25"))
            else:
                btn.configure(fg_color="transparent")

        self.current_tab = tab_name

        # Вызываем обработчик смены вкладки
        self.on_tab_changed()

    def on_tab_changed(self):
        """Обработчик переключения вкладок"""
        current_tab = self.current_tab
        if current_tab == "reports":
            # Автоматически обновляем отчёт при переключении на вкладку
            self.generate_report(show_empty_message=False)
        elif current_tab == "bookings":
            # Автоматически обновляем записи при переключении на вкладку
            self.refresh_bookings()
        elif current_tab == "works":
            # Автоматически обновляем список записей для выбора клиента
            self.refresh_bookings_combo()
        elif current_tab == "warehouse":
            # Автоматически обновляем список запчастей на складе
            self.refresh_warehouse()

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

    def load_settings(self):
        """Загрузить настройки из JSON файла"""
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'master_percent': 50}

    def save_settings(self, settings):
        """Сохранить настройки в JSON файл"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")

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

        context_menu.add_command(label="Вырезать", command=cut_text)
        context_menu.add_command(label="Копировать", command=copy_text)
        context_menu.add_command(label="Вставить", command=paste_text)
        context_menu.add_separator()
        context_menu.add_command(label="Выделить всё", command=select_all)

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

        ctk.CTkLabel(add_frame, text="ФИО:").pack(side=tk.LEFT, padx=5, pady=5)
        self.worker_name_entry = ctk.CTkEntry(add_frame, width=400, fg_color="white", text_color="black")
        self.worker_name_entry.pack(side=tk.LEFT, padx=5, pady=5)

        ctk.CTkButton(add_frame, text="Добавить", command=self.add_worker, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5, pady=5)

        # Список работников
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(fill=tk.X, pady=10)

        # Таблица работников (без колонки ID) - ширина по родительскому контейнеру
        columns = ("name",)
        self.workers_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.workers_tree.heading("name", text="ФИО мастера")
        self.workers_tree.column("name", width=500, stretch=True, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.workers_tree.yview)
        self.workers_tree.configure(yscrollcommand=scrollbar.set)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.workers_tree.tag_configure('oddrow', background='#ffffff')
        self.workers_tree.tag_configure('evenrow', background='#f0f0f0')

        self.workers_tree.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)

        # Кнопка удаления
        ctk.CTkButton(center_container, text="Удалить выбранного мастера",
                   command=self.delete_worker, width=550, fg_color="red", hover_color="darkred").pack(anchor=tk.CENTER, pady=10)

    def add_worker(self):
        """Добавить работника"""
        name = self.worker_name_entry.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Введите ФИО мастера!")
            return

        if self.db.add_worker(name):
            messagebox.showinfo("Успех", f"Мастер '{name}' добавлен!")
            self.worker_name_entry.delete(0, tk.END)
            self.refresh_workers_list()
            self.refresh_workers_combo()
        else:
            messagebox.showerror("Ошибка", "Мастер с таким ФИО уже существует!")

    def delete_worker(self):
        """Удалить работника"""
        selected = self.workers_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите мастера для удаления!")
            return

        item = self.workers_tree.item(selected[0])
        worker_id = item['tags'][0]  # ID хранится в тегах
        worker_name = item['values'][0]  # Имя в первой колонке

        if messagebox.askyesno("Подтверждение",
                               f"Удалить мастера '{worker_name}'?\n\nВсе записи о его работах также будут удалены!"):
            self.db.delete_worker(worker_id)
            messagebox.showinfo("Успех", "Мастер удалён!")
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

    # ===== ВКЛАДКА ДОБАВЛЕНИЯ РАБОТ =====

    def setup_works_tab(self):
        """Настройка вкладки добавления работ"""
        # Используем прокручиваемый фрейм для поддержки маленьких экранов
        main_frame = ctk.CTkScrollableFrame(self.works_frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Центрированный контейнер для всех элементов
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        title = ctk.CTkLabel(
            center_container,
            text="Добавить запись о работе",
            font=("Segoe UI", 20, "bold"),
            anchor="w"
        )
        title.pack(fill=tk.X, pady=(0, 10))

        # Выбор работника
        row1 = ctk.CTkFrame(center_container)
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text="Мастер:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.worker_combo = ctk.CTkComboBox(row1, width=350, fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.worker_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Номер машины (госномер) - отдельная строка
        row_car_number = ctk.CTkFrame(center_container)
        row_car_number.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_car_number, text="Госномер:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.car_number_entry = ctk.CTkEntry(row_car_number, width=250, fg_color="white", text_color="black")
        self.car_number_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        # Автозаполнение при потере фокуса или нажатии Enter
        self.car_number_entry.bind("<FocusOut>", self.on_car_number_change)
        self.car_number_entry.bind("<Return>", self.on_car_number_change)

        # Марка машины с автокомплитом
        row_car_brand = ctk.CTkFrame(center_container)
        row_car_brand.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_car_brand, text="Марка машины:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.car_brand_entry = ctk.CTkEntry(row_car_brand, width=250, fg_color="white", text_color="black")
        self.car_brand_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.car_brand_entry.bind('<KeyRelease>', self.on_brand_keyrelease)
        self.car_brand_entry.bind('<FocusOut>', self.on_brand_focus_out)

        # Listbox для автокомплита марки
        self.brand_listbox = tk.Listbox(row_car_brand, height=5, width=30, takefocus=False)
        self.brand_listbox_visible = False
        self.brand_listbox.bind('<<ListboxSelect>>', self.on_brand_select)

        # Модель машины с автокомплитом
        row_car_model = ctk.CTkFrame(center_container)
        row_car_model.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_car_model, text="Модель машины:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.car_model_entry = ctk.CTkEntry(row_car_model, width=250, fg_color="white", text_color="black")
        self.car_model_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.car_model_entry.bind('<KeyRelease>', self.on_model_keyrelease)
        self.car_model_entry.bind('<FocusOut>', self.on_model_focus_out)

        # Listbox для автокомплита модели
        self.model_listbox = tk.Listbox(row_car_model, height=5, width=30, takefocus=False)
        self.model_listbox_visible = False
        self.model_listbox.bind('<<ListboxSelect>>', self.on_model_select)

        # VIN номер и пробег
        row_vin = ctk.CTkFrame(center_container)
        row_vin.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_vin, text="VIN:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.vin_entry = ctk.CTkEntry(row_vin, width=200, fg_color="white", text_color="black")
        self.vin_entry.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(row_vin, text="Пробег:", width=80, anchor="w").pack(side=tk.LEFT, padx=(20, 5))
        self.mileage_entry = ctk.CTkEntry(row_vin, width=100, fg_color="white", text_color="black")
        self.mileage_entry.pack(side=tk.LEFT, padx=5)

        # Контекстное меню для VIN (правая кнопка - вставить)
        self.vin_context_menu = tk.Menu(self.root, tearoff=0)
        self.vin_context_menu.add_command(label="Вставить", command=self.paste_to_vin)
        self.vin_entry.bind("<Button-3>", self.show_vin_context_menu)

        # Разделитель - Данные клиента
        separator_client = ctk.CTkFrame(center_container, height=2, fg_color="gray70")
        separator_client.pack(fill=tk.X, pady=10)
        ctk.CTkLabel(center_container, text="Данные клиента", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=5)

        # Выбор записи из bookings
        row_booking = ctk.CTkFrame(center_container)
        row_booking.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_booking, text="Запись:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.booking_combo = ctk.CTkComboBox(row_booking, width=350, fg_color="white", text_color="black",
                                              button_color="#0078d7", button_hover_color="#005a9e",
                                              command=self.on_booking_select)
        self.booking_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.booking_combo.set("")
        self.bookings_data = {}  # Словарь для хранения booking_id по тексту

        ctk.CTkButton(row_booking, text="Обновить", width=80, command=self.refresh_bookings_combo).pack(side=tk.LEFT, padx=5)

        # Имя клиента
        row_client_name = ctk.CTkFrame(center_container)
        row_client_name.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_client_name, text="Имя клиента:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.client_name_entry = ctk.CTkEntry(row_client_name, width=350, fg_color="white", text_color="black")
        self.client_name_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Телефон клиента
        row_client_phone = ctk.CTkFrame(center_container)
        row_client_phone.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_client_phone, text="Телефон клиента:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.client_phone_entry = ctk.CTkEntry(row_client_phone, width=200, fg_color="white", text_color="black")
        self.client_phone_entry.pack(side=tk.LEFT, padx=5)
        # При вводе телефона ищем данные клиента
        self.client_phone_entry.bind('<KeyRelease>', self.on_client_phone_keyrelease)

        # Машины клиента (если клиент уже был в сервисе)
        row_client_cars = ctk.CTkFrame(center_container)
        row_client_cars.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row_client_cars, text="Машины клиента:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.client_cars_combo = ctk.CTkComboBox(row_client_cars, width=350, fg_color="white", text_color="black",
                                                  button_color="#0078d7", button_hover_color="#005a9e",
                                                  command=self.on_client_car_select)
        self.client_cars_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.client_cars_combo.set("")
        self.client_cars_combo.configure(values=["Новая машина"])
        self.client_cars_data = {}  # Словарь для хранения данных машин

        # Храним выбранный booking_id
        self.selected_booking_id = None

        # Секция работ
        separator_works = ctk.CTkFrame(center_container, height=2, fg_color="gray70")
        separator_works.pack(fill=tk.X, pady=(10, 5))
        ctk.CTkLabel(center_container, text="Проделанные работы", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=5)

        works_container = ctk.CTkFrame(center_container)
        works_container.pack(fill=tk.X, pady=5)

        # Таблица работ
        works_table_frame = ctk.CTkFrame(works_container)
        works_table_frame.pack(fill=tk.X, pady=5, padx=5)

        work_columns = ("work_name", "work_price")
        self.works_tree = ttk.Treeview(works_table_frame, columns=work_columns, show="headings", height=4)
        self.works_tree.heading("work_name", text="Название работы")
        self.works_tree.heading("work_price", text="Цена")
        self.works_tree.column("work_name", width=450)
        self.works_tree.column("work_price", width=150, anchor=tk.CENTER)

        scrollbar_works = ttk.Scrollbar(works_table_frame, orient=tk.VERTICAL, command=self.works_tree.yview)
        self.works_tree.configure(yscrollcommand=scrollbar_works.set)
        self.works_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_works.pack(side=tk.RIGHT, fill=tk.Y)

        # Ввод работы
        works_input_frame = ctk.CTkFrame(works_container)
        works_input_frame.pack(fill=tk.X, pady=5, padx=5)

        row_work_name = ctk.CTkFrame(works_input_frame)
        row_work_name.pack(fill=tk.X, pady=2)
        ctk.CTkLabel(row_work_name, text="Название:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.work_name_entry = ctk.CTkEntry(row_work_name, fg_color="white", text_color="black")
        self.work_name_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.work_name_entry.bind('<KeyRelease>', self.on_work_name_keyrelease)
        self.work_name_entry.bind('<FocusOut>', self.on_work_name_focus_out)

        self.work_keyword_listbox = tk.Listbox(row_work_name, height=5, width=40, takefocus=False)
        self.work_keyword_listbox_visible = False
        self.work_keyword_listbox.bind('<Double-Button-1>', self.on_work_keyword_select)
        self.work_keyword_listbox.bind('<Return>', self.on_work_keyword_select)

        row_work_price = ctk.CTkFrame(works_input_frame)
        row_work_price.pack(fill=tk.X, pady=2)
        ctk.CTkLabel(row_work_price, text="Цена:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.work_price_entry = ctk.CTkEntry(row_work_price, width=200, fg_color="white", text_color="black")
        self.work_price_entry.pack(side=tk.LEFT, padx=5)

        # Кнопки работ
        works_buttons_frame = ctk.CTkFrame(works_container)
        works_buttons_frame.pack(fill=tk.X, pady=5, padx=5)
        ctk.CTkButton(works_buttons_frame, text="Добавить работу",
                      command=self.add_work_to_list, width=200).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(works_buttons_frame, text="Удалить выбранную",
                      command=self.remove_work_from_list, width=200, fg_color="red", hover_color="darkred").pack(side=tk.LEFT, padx=5)

        self.works_list = []

        # Разделитель - Запчасти
        separator_parts = ctk.CTkFrame(center_container, height=2, fg_color="gray70")
        separator_parts.pack(fill=tk.X, pady=10)
        ctk.CTkLabel(center_container, text="Запчасти", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=5)

        # Секция запчастей (на всю ширину)
        parts_container = ctk.CTkFrame(center_container)
        parts_container.pack(fill=tk.X, pady=10)

        # Таблица запчастей (на всю ширину)
        parts_table_frame = ctk.CTkFrame(parts_container)
        parts_table_frame.pack(fill=tk.X, pady=5, padx=5)

        columns = ("part_name", "part_price")
        self.parts_tree = ttk.Treeview(parts_table_frame, columns=columns, show="headings", height=4)
        self.parts_tree.heading("part_name", text="Название запчасти")
        self.parts_tree.heading("part_price", text="Цена")

        self.parts_tree.column("part_name", width=450)
        self.parts_tree.column("part_price", width=150, anchor=tk.CENTER)

        scrollbar_parts = ttk.Scrollbar(parts_table_frame, orient=tk.VERTICAL, command=self.parts_tree.yview)
        self.parts_tree.configure(yscrollcommand=scrollbar_parts.set)

        self.parts_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_parts.pack(side=tk.RIGHT, fill=tk.Y)

        # Ввод запчасти
        parts_input_frame = ctk.CTkFrame(parts_container)
        parts_input_frame.pack(fill=tk.X, pady=5, padx=5)

        # Название запчасти
        row_part_name = ctk.CTkFrame(parts_input_frame)
        row_part_name.pack(fill=tk.X, pady=2)
        ctk.CTkLabel(row_part_name, text="Название:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.part_name_entry = ctk.CTkEntry(row_part_name, fg_color="white", text_color="black")
        self.part_name_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Добавляем контекстное меню для вставки
        self.setup_entry_context_menu(self.part_name_entry)

        # Цена запчасти
        row_part_price = ctk.CTkFrame(parts_input_frame)
        row_part_price.pack(fill=tk.X, pady=2)
        ctk.CTkLabel(row_part_price, text="Цена:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.part_price_entry = ctk.CTkEntry(row_part_price, width=200, fg_color="white", text_color="black")
        self.part_price_entry.pack(side=tk.LEFT, padx=5)

        # Кнопки для запчастей в один ряд
        parts_buttons_frame = ctk.CTkFrame(parts_container)
        parts_buttons_frame.pack(fill=tk.X, pady=5, padx=5)

        ctk.CTkButton(parts_buttons_frame, text="Добавить запчасть",
                   command=self.add_part_to_list, width=200).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(parts_buttons_frame, text="Удалить выбранную",
                   command=self.remove_part_from_list, width=200, fg_color="red", hover_color="darkred").pack(side=tk.LEFT, padx=5)

        # Список запчастей (временное хранилище)
        self.parts_list = []

        # Кнопка добавления записи (по центру)
        button_frame = ctk.CTkFrame(center_container, fg_color="transparent")
        button_frame.pack(fill=tk.X, pady=20)
        ctk.CTkButton(button_frame, text="Добавить запись",
                   command=self.add_work, width=300, height=50, fg_color="green", hover_color="darkgreen").pack(anchor=tk.CENTER)

    # Обработчики автокомплита для марки
    def on_brand_keyrelease(self, event):
        """Обработчик ввода текста для марки"""
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
        if not self.brand_listbox_visible:
            self.brand_listbox.pack(side=tk.LEFT, padx=5)
            self.brand_listbox_visible = True

    def hide_brand_listbox(self):
        """Скрыть список марок"""
        if self.brand_listbox_visible:
            self.brand_listbox.pack_forget()
            self.brand_listbox_visible = False

    def show_vin_context_menu(self, event):
        """Показать контекстное меню для поля VIN"""
        self.vin_context_menu.tk_popup(event.x_root, event.y_root)

    def paste_to_vin(self):
        """Вставить текст из буфера обмена в поле VIN"""
        try:
            clipboard_text = self.root.clipboard_get()
            self.vin_entry.insert(tk.END, clipboard_text)
        except tk.TclError:
            pass  # Буфер обмена пуст

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

            display_text = f"{date_str} {booking_time} - {full_name or 'Без имени'} ({phone or 'Без телефона'})"
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
        if choice and choice in self.bookings_data:
            booking_info = self.bookings_data[choice]
            self.selected_booking_id = booking_info['id']
            # Автозаполнение полей клиента
            self.client_name_entry.delete(0, tk.END)
            self.client_name_entry.insert(0, booking_info['name'])
            self.client_phone_entry.delete(0, tk.END)
            self.client_phone_entry.insert(0, booking_info['phone'])
            # Загружаем машины этого клиента (передаём car_id из записи)
            self.load_client_cars(booking_info['phone'], booking_info['name'], booking_info.get('car_id'))
        else:
            self.selected_booking_id = None
            self.client_cars_combo.configure(values=["Новая машина"])
            self.client_cars_combo.set("")
            self.client_cars_data = {}

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
        values = ["Новая машина"]
        selected_car_display = None

        for car in cars:
            car_brand, car_model, car_number = car
            display_text = f"{car_brand or ''} {car_model or ''} {car_number or ''}".strip()
            if display_text:
                values.append(display_text)
                self.client_cars_data[display_text] = {
                    'brand': car_brand or '',
                    'model': car_model or '',
                    'number': car_number or ''
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
                values_with_select = ["Выберите авто"] + values[1:]  # убираем "Новая машина" из начала
                values_with_select.append("Новая машина")  # добавляем в конец
                self.client_cars_combo.configure(values=values_with_select)
                self.client_cars_combo.set("Выберите авто")
                self.client_cars_combo.configure(text_color="#c62828")
                # Очищаем поля машины
                self.car_brand_entry.delete(0, tk.END)
                self.car_model_entry.delete(0, tk.END)
                self.car_number_entry.delete(0, tk.END)
            else:
                # Нет машин
                self.client_cars_combo.set("Новая машина")
        # Если booking_car_id передан - старая логика для редактирования записи
        elif booking_car_id is not None:
            if selected_car_display:
                self.client_cars_combo.set(selected_car_display)
                self.on_client_car_select(selected_car_display)
            elif num_cars > 0:
                self.client_cars_combo.set(values[1])
                self.on_client_car_select(values[1])
            else:
                self.client_cars_combo.set("Новая машина")
        else:
            self.client_cars_combo.set("Новая машина")

    def on_client_phone_keyrelease(self, event):
        """При вводе телефона - искать данные клиента и его машины"""
        phone_raw = self.client_phone_entry.get().strip()
        phone_digits = ''.join(c for c in phone_raw if c.isdigit())

        # Ищем только если введено 10-11 цифр
        if len(phone_digits) >= 10:
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
        else:
            # Если цифр меньше 10 - очищаем список машин
            self.client_cars_combo.configure(values=["Новая машина"])
            self.client_cars_combo.set("Новая машина")
            self.client_cars_data = {}

    def on_car_number_change(self, event=None):
        """Автозаполнение по госномеру"""
        car_number = self.car_number_entry.get().strip()
        if not car_number or len(car_number) < 3:
            return

        # Проверяем, не заполнены ли уже другие поля машины
        if self.car_brand_entry.get().strip() or self.car_model_entry.get().strip():
            return  # Поля уже заполнены, не перезаписываем

        # Ищем всех клиентов по госномеру
        clients = self.db.get_all_clients_by_car_number(car_number)

        if not clients:
            return

        if len(clients) == 1:
            # Только один клиент - заполняем сразу
            self.fill_car_and_client_info(clients[0])
        else:
            # Несколько клиентов - показываем окно выбора
            self.show_client_selection_dialog(clients, car_number)

    def fill_car_and_client_info(self, client_info):
        """Заполнить поля машины и клиента"""
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
            self.client_phone_entry.delete(0, tk.END)
            self.client_phone_entry.insert(0, client_info["client_phone"])

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

    def show_client_selection_dialog(self, clients, car_number):
        """Показать диалог выбора клиента для госномера"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(f"Выбор клиента для {car_number}")
        dialog.geometry("450x300")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=f"Найдено несколько клиентов для госномера {car_number}:",
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
            name = client.get("client_name") or "Без имени"
            phone = client.get("client_phone") or "Без телефона"
            btn_text = f"{name}  |  {phone}"

            btn = ctk.CTkButton(list_frame, text=btn_text, anchor="w",
                               command=lambda c=client: select_client(c),
                               fg_color="#2b2b2b", hover_color="#3b3b3b",
                               height=40, font=("Arial", 12))
            btn.pack(fill=tk.X, pady=3)

        # Кнопка отмены
        ctk.CTkButton(dialog, text="Отмена", command=dialog.destroy,
                     fg_color="#757575", hover_color="#616161", width=100).pack(pady=15)

    def load_client_cars_without_autofill(self, phone, name):
        """Загрузить машины клиента без автозаполнения полей"""
        cars = []
        if phone:
            cars = self.db.get_client_cars_by_phone(phone)
        if not cars and name:
            cars = self.db.get_client_cars_by_name(name)

        self.client_cars_data = {}
        values = ["Новая машина"]

        for car in cars:
            car_brand, car_model, car_number = car
            display_text = f"{car_brand or ''} {car_model or ''} {car_number or ''}".strip()
            if display_text:
                values.append(display_text)
                self.client_cars_data[display_text] = {
                    'brand': car_brand or '',
                    'model': car_model or '',
                    'number': car_number or ''
                }

        self.client_cars_combo.configure(values=values)
        self.client_cars_combo.set("")  # Не выбираем ничего

    def on_client_car_select(self, choice):
        """Обработчик выбора машины клиента"""
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
        elif choice == "Новая машина":
            # Очищаем поля машины для новой
            self.car_brand_entry.delete(0, tk.END)
            self.car_model_entry.delete(0, tk.END)
            self.car_number_entry.delete(0, tk.END)
        elif choice == "Выберите авто":
            # Не делаем ничего, ждём выбора
            self.client_cars_combo.configure(text_color="#c62828")

    # Обработчики автокомплита для модели
    def on_model_keyrelease(self, event):
        """Обработчик ввода текста для модели"""
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
        if not self.model_listbox_visible:
            self.model_listbox.pack(side=tk.LEFT, padx=5)
            self.model_listbox_visible = True

    def hide_model_listbox(self):
        """Скрыть список моделей"""
        if self.model_listbox_visible:
            self.model_listbox.pack_forget()
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
        """Обновить выпадающий список работников"""
        workers = self.db.get_all_workers()
        self.workers_data = {w[1]: w[0] for w in workers}
        worker_names = ["Выберите мастера"] + list(self.workers_data.keys())
        self.worker_combo.configure(values=worker_names)
        self.worker_combo.set("Выберите мастера")

    def add_part_to_list(self):
        """Добавить запчасть в список"""
        part_name = self.part_name_entry.get().strip()
        if not part_name:
            messagebox.showwarning("Внимание", "Введите название запчасти!")
            return

        try:
            part_price = float(self.part_price_entry.get().replace(',', '.'))
            if part_price <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную цену запчасти!")
            return

        # Добавляем в список
        self.parts_list.append((part_name, part_price))

        # Обновляем таблицу
        self.parts_tree.insert("", tk.END, values=(part_name, self.format_currency(part_price)))

        # Очищаем поля ввода
        self.part_name_entry.delete(0, tk.END)
        self.part_price_entry.delete(0, tk.END)

        # Обновляем общую стоимость
        self.update_total_cost()

    def remove_part_from_list(self):
        """Удалить запчасть из списка"""
        selected = self.parts_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите запчасть для удаления!")
            return

        # Получаем индекс выбранного элемента
        item_index = self.parts_tree.index(selected[0])

        # Удаляем из списка
        del self.parts_list[item_index]

        # Удаляем из таблицы
        self.parts_tree.delete(selected[0])

        # Обновляем общую стоимость
        self.update_total_cost()

    def add_work_to_list(self):
        """Добавить работу в список"""
        work_name = self.work_name_entry.get().strip()
        if not work_name:
            messagebox.showwarning("Внимание", "Введите название работы!")
            return
        try:
            work_price = float(self.work_price_entry.get().replace(',', '.'))
            if work_price <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную цену работы!")
            return

        self.works_list.append((work_name, work_price))
        self.works_tree.insert("", tk.END, values=(work_name, self.format_currency(work_price)))
        self.work_name_entry.delete(0, tk.END)
        self.work_price_entry.delete(0, tk.END)

    def remove_work_from_list(self):
        """Удалить работу из списка"""
        selected = self.works_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите работу для удаления!")
            return
        item_index = self.works_tree.index(selected[0])
        del self.works_list[item_index]
        self.works_tree.delete(selected[0])

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
        if not self.work_keyword_listbox_visible:
            self.work_keyword_listbox.pack(side=tk.LEFT, padx=5)
            self.work_keyword_listbox_visible = True

    def hide_work_keyword_listbox(self):
        if self.work_keyword_listbox_visible:
            self.work_keyword_listbox.pack_forget()
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

    def update_total_cost(self):
        """Обновить общую стоимость работы + запчасти"""
        # Метод оставлен для совместимости, но больше ничего не отображает
        pass

    def add_work(self):
        """Добавить или обновить запись о работе"""
        selected_worker = self.worker_combo.get()
        if not selected_worker or selected_worker == "Выберите мастера":
            messagebox.showwarning("Внимание", "Выберите мастера!")
            return

        if not self.works_list:
            messagebox.showwarning("Внимание", "Добавьте хотя бы одну работу!")
            return

        description = "\n".join(name for name, _ in self.works_list)
        amount = sum(price for _, price in self.works_list)

        worker_id = self.workers_data[selected_worker]
        car_brand = self.car_brand_entry.get().strip()
        car_model = self.car_model_entry.get().strip()
        car_number = self.car_number_entry.get().strip().upper()
        mileage = self.mileage_entry.get().strip()
        vin = self.vin_entry.get().strip().upper()

        # Валидация обязательных полей авто
        if not car_brand:
            messagebox.showwarning("Внимание", "Введите марку автомобиля!")
            return
        if not car_model:
            messagebox.showwarning("Внимание", "Введите модель автомобиля!")
            return
        if not car_number:
            messagebox.showwarning("Внимание", "Введите госномер автомобиля!")
            return

        # Данные клиента
        booking_id = getattr(self, 'selected_booking_id', None)
        client_name = self.client_name_entry.get().strip()
        client_phone = self.client_phone_entry.get().strip()

        # Получаем telegram_user_id из записи если есть
        telegram_user_id = None
        if booking_id:
            booking = self.db.get_booking_by_id(booking_id)
            if booking:
                telegram_user_id = booking.get("user_id")

        # Если нет booking_id, но есть телефон - ищем user_id по телефону
        if not telegram_user_id and client_phone:
            telegram_user_id = self.db.get_telegram_user_id_by_phone(client_phone)

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
            client_id = self.db.get_or_create_client(
                telegram_user_id=telegram_user_id,
                full_name=client_name,
                phone=client_phone,
                car_number=car_number
            )
            car_id = self.db.get_or_create_car(client_id, car_brand, car_model, car_number) if client_id else None

            # Обновляем запись
            self.db.update_work(self.editing_work_id, worker_id, description, amount, work_date, mileage, vin, booking_id, car_id)

            # Удаляем старые запчасти и добавляем новые
            self.db.delete_parts_by_work_id(self.editing_work_id)
            if self.parts_list:
                self.db.add_parts(self.editing_work_id, self.parts_list)

            messagebox.showinfo("Успех", "Запись обновлена!")

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
                    # У записи уже есть работа - спрашиваем пользователя
                    desc_preview = (existing_work['description'][:100] + "...") if existing_work['description'] and len(existing_work['description']) > 100 else (existing_work['description'] or "")
                    msg = (f"У этой записи уже есть работа:\n\n"
                           f"{desc_preview}\n\n"
                           f"Добавить новую работу к существующей?")

                    if messagebox.askyesno("Запись уже имеет работу", msg):
                        # Объединяем с существующей работой
                        self.db.append_to_work(existing_work["work_id"], description, amount)

                        # Добавляем запчасти к существующей работе
                        if self.parts_list:
                            self.db.add_parts(existing_work["work_id"], self.parts_list)

                        messagebox.showinfo("Успех", "Работа добавлена к существующей!")

                        # Очищаем форму и выходим
                        self.clear_work_form()
                        return
                    # Если нет - продолжаем создавать новую работу

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
                    msg = (f"Машина {car_number} уже в работе!\n\n"
                           f"Клиент: {active_work['client_name']}\n"
                           f"Телефон: {active_work['client_phone']}\n"
                           f"Дата записи: {date_str} {active_work['booking_time']}\n"
                           f"Текущие работы:\n{desc_preview}\n\n"
                           f"Добавить новую работу к текущей?")

                    if messagebox.askyesno("Машина уже в работе", msg):
                        # Объединяем с существующей работой
                        existing_work_id = active_work["work_id"]
                        self.db.append_to_work(existing_work_id, description, amount)

                        # Добавляем запчасти к существующей работе
                        if self.parts_list:
                            self.db.add_parts(existing_work_id, self.parts_list)

                        messagebox.showinfo("Успех", "Работа добавлена к существующей записи!")

                        # Очищаем форму и выходим
                        self.clear_work_form()
                        return
                    else:
                        # Пользователь отказался - отменяем добавление
                        return

                else:
                    # Машина не в работе - создаём новую запись
                    current_hour = now.hour
                    TIME_SLOTS = ["10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]
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
                    new_client_id = self.db.get_or_create_client(
                        telegram_user_id=tg_user_id if tg_user_id else None,
                        full_name=client_name,
                        phone=client_phone,
                        car_number=car_number
                    )
                    new_car_id = self.db.get_or_create_car(new_client_id, car_brand, car_model, car_number) if new_client_id else None

                    # Создаём запись со статусом "В работе"
                    booking_id = self.db.add_booking(
                        booking_date=now.date(),
                        booking_time=booking_time,
                        client_id=new_client_id,
                        car_id=new_car_id,
                        status="in_progress"
                    )

            # Создаём/находим клиента и машину для работы
            client_id = self.db.get_or_create_client(
                telegram_user_id=telegram_user_id,
                full_name=client_name,
                phone=client_phone,
                car_number=car_number
            )
            car_id = self.db.get_or_create_car(client_id, car_brand, car_model, car_number) if client_id else None

            # Добавляем работу и получаем ID
            work_id = self.db.add_work(worker_id, description, amount, work_date, mileage, vin, booking_id, car_id)

            # Если есть запчасти - сохраняем их
            if self.parts_list:
                self.db.add_parts(work_id, self.parts_list)

            # Меняем статус записи на "В работе"
            if booking_id:
                self.db.update_booking_status(booking_id, "in_progress")

            messagebox.showinfo("Успех", "Запись добавлена!")

        # Очищаем форму
        self.clear_work_form()

    def clear_work_form(self):
        """Очистить форму добавления работы"""
        self.works_list = []
        for item in self.works_tree.get_children():
            self.works_tree.delete(item)
        self.car_brand_entry.delete(0, tk.END)
        self.car_model_entry.delete(0, tk.END)
        self.car_number_entry.delete(0, tk.END)
        self.mileage_entry.delete(0, tk.END)
        self.vin_entry.delete(0, tk.END)
        self.client_name_entry.delete(0, tk.END)
        self.client_phone_entry.delete(0, tk.END)
        self.booking_combo.set("")
        self.selected_booking_id = None
        self.client_cars_combo.configure(values=["Новая машина"])
        self.client_cars_combo.set("")
        self.client_cars_data = {}

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
        ctk.CTkLabel(top_frame, text="Склад запчастей", font=ctk.CTkFont(size=20, weight="bold")).pack(side=tk.LEFT, padx=10)

        # Кнопка заказать запчасть
        ctk.CTkButton(top_frame, text="Заказать запчасть", command=self.show_add_part_form,
                     fg_color="#1565c0", hover_color="#0d47a1", width=160).pack(side=tk.RIGHT, padx=10)

        # Кнопка обновить
        ctk.CTkButton(top_frame, text="Обновить", command=self.refresh_warehouse,
                     width=100).pack(side=tk.RIGHT, padx=5)

        # Фильтр по статусу
        filter_frame = ctk.CTkFrame(self.warehouse_frame)
        filter_frame.pack(fill=tk.X, padx=10, pady=5)

        ctk.CTkLabel(filter_frame, text="Статус:").pack(side=tk.LEFT, padx=5)
        self.warehouse_status_var = tk.StringVar(value="Все")
        status_combo = ctk.CTkComboBox(filter_frame, variable=self.warehouse_status_var,
                                        values=["Все", "В пути", "На складе", "Выдано"],
                                        width=140, command=lambda x: self.refresh_warehouse())
        status_combo.pack(side=tk.LEFT, padx=5)

        # Поиск по госномеру
        ctk.CTkLabel(filter_frame, text="Госномер:").pack(side=tk.LEFT, padx=(20, 5))
        self.warehouse_search_entry = ctk.CTkEntry(filter_frame, width=150, placeholder_text="Поиск...")
        self.warehouse_search_entry.pack(side=tk.LEFT, padx=5)
        self.warehouse_search_entry.bind("<Return>", lambda e: self.refresh_warehouse())
        ctk.CTkButton(filter_frame, text="✕", command=self.clear_warehouse_search,
                     width=30, fg_color="#c62828", hover_color="#b71c1c").pack(side=tk.LEFT, padx=2)

        # Таблица запчастей
        table_frame = ctk.CTkFrame(self.warehouse_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("id", "car_info", "client", "part_name", "quantity", "price", "status", "order_date", "received_date", "notes")
        self.warehouse_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        self.warehouse_tree.heading("id", text="ID")
        self.warehouse_tree.heading("car_info", text="Автомобиль")
        self.warehouse_tree.heading("client", text="Клиент")
        self.warehouse_tree.heading("part_name", text="Запчасть")
        self.warehouse_tree.heading("quantity", text="Кол-во")
        self.warehouse_tree.heading("price", text="Цена")
        self.warehouse_tree.heading("status", text="Статус")
        self.warehouse_tree.heading("order_date", text="Дата заказа")
        self.warehouse_tree.heading("received_date", text="Дата прихода")
        self.warehouse_tree.heading("notes", text="Примечания")

        self.warehouse_tree.column("id", width=0, stretch=False, minwidth=0)
        self.warehouse_tree.column("car_info", width=180)
        self.warehouse_tree.column("client", width=130)
        self.warehouse_tree.column("part_name", width=200)
        self.warehouse_tree.column("quantity", width=50)
        self.warehouse_tree.column("price", width=90)
        self.warehouse_tree.column("status", width=90)
        self.warehouse_tree.column("order_date", width=90)
        self.warehouse_tree.column("received_date", width=90)
        self.warehouse_tree.column("notes", width=120)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.warehouse_tree.yview)
        self.warehouse_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.warehouse_tree.pack(fill=tk.BOTH, expand=True)

        # Настройка цветов для статусов
        self.warehouse_tree.tag_configure("в пути", background="#e3f2fd", foreground="#1565c0")
        self.warehouse_tree.tag_configure("на складе", background="#e8f5e9", foreground="#2e7d32")
        self.warehouse_tree.tag_configure("выдано", background="#f3e5f5", foreground="#7b1fa2")

        # Добавляем tooltip для запчастей
        TreeviewTooltip(self.warehouse_tree, columns=["part_name", "notes"])

        # Контекстное меню для редактирования
        self.warehouse_context_menu = tk.Menu(self.warehouse_tree, tearoff=0)
        self.warehouse_context_menu.add_command(label="Редактировать", command=self.edit_warehouse_part)
        self.warehouse_context_menu.add_separator()
        self.warehouse_context_menu.add_command(label="На склад", command=lambda: self.update_part_status("на складе"))
        self.warehouse_context_menu.add_command(label="Выдано", command=lambda: self.update_part_status("выдано"))
        self.warehouse_context_menu.add_separator()
        self.warehouse_context_menu.add_command(label="Удалить", command=self.delete_warehouse_part)

        def show_warehouse_context_menu(event):
            # Выбираем строку под курсором
            item = self.warehouse_tree.identify_row(event.y)
            if item:
                self.warehouse_tree.selection_set(item)
                self.warehouse_context_menu.tk_popup(event.x_root, event.y_root)

        self.warehouse_tree.bind("<Button-3>", show_warehouse_context_menu)

        # Нижняя панель с кнопками действий
        actions_frame = ctk.CTkFrame(self.warehouse_frame)
        actions_frame.pack(pady=10)

        ctk.CTkButton(actions_frame, text="На склад", command=lambda: self.update_part_status("на складе"),
                     fg_color="#2e7d32", hover_color="#1b5e20", width=100).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(actions_frame, text="Выдано", command=lambda: self.update_part_status("выдано"),
                     fg_color="#7b1fa2", hover_color="#6a1b9a", width=100).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(actions_frame, text="Удалить", command=self.delete_warehouse_part,
                     fg_color="#c62828", hover_color="#b71c1c", width=100).pack(side=tk.LEFT, padx=5)

        # Форма добавления запчасти (скрыта по умолчанию)
        self.add_part_form_frame = ctk.CTkFrame(self.warehouse_frame)
        self.add_part_form_visible = False

    def show_add_part_form(self):
        """Показать форму добавления запчасти"""
        if self.add_part_form_visible:
            self.hide_add_part_form()
            return

        self.add_part_form_frame = ctk.CTkToplevel(self.root)
        self.add_part_form_frame.title("Заказать запчасть")
        self.add_part_form_frame.geometry("550x500")
        self.add_part_form_frame.transient(self.root)
        self.add_part_form_frame.grab_set()

        # Центрируем окно
        self.add_part_form_frame.update_idletasks()
        x = (self.add_part_form_frame.winfo_screenwidth() - 550) // 2
        y = (self.add_part_form_frame.winfo_screenheight() - 500) // 2
        self.add_part_form_frame.geometry(f"+{x}+{y}")

        # Прокручиваемый контейнер
        form_container = ctk.CTkScrollableFrame(self.add_part_form_frame)
        form_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ctk.CTkLabel(form_container, text="Заказ запчасти", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(0, 20))

        # Госномер с поиском
        row1 = ctk.CTkFrame(form_container)
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text="Госномер:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.wh_car_number_entry = ctk.CTkEntry(row1, width=150, fg_color="white", text_color="black")
        self.wh_car_number_entry.pack(side=tk.LEFT, padx=5)
        self.wh_car_number_entry.bind('<FocusOut>', lambda e: self.search_car_for_warehouse())
        self.wh_car_number_entry.bind('<Return>', lambda e: self.search_car_for_warehouse())
        ctk.CTkButton(row1, text="Найти", command=self.search_car_for_warehouse, width=70).pack(side=tk.LEFT, padx=5)

        # Информация о найденной машине
        self.wh_car_info_label = ctk.CTkLabel(form_container, text="", text_color="gray")
        self.wh_car_info_label.pack(fill=tk.X, padx=(10, 10), anchor="w")
        self.wh_selected_car_id = None  # Сохраняем car_id

        # Фрейм для новой машины (скрыт по умолчанию)
        self.wh_new_car_frame = ctk.CTkFrame(form_container, fg_color=("gray90", "gray20"))
        self.wh_new_car_visible = False

        # Поля для новой машины
        ctk.CTkLabel(self.wh_new_car_frame, text="Новая машина и клиент",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5))

        row_brand = ctk.CTkFrame(self.wh_new_car_frame)
        row_brand.pack(fill=tk.X, pady=3, padx=10)
        ctk.CTkLabel(row_brand, text="Марка:", width=100, anchor="w").pack(side=tk.LEFT)
        self.wh_new_brand_entry = ctk.CTkEntry(row_brand, width=200, fg_color="white", text_color="black")
        self.wh_new_brand_entry.pack(side=tk.LEFT, padx=5)
        self.wh_new_brand_entry.bind('<KeyRelease>', self.on_wh_brand_keyrelease)
        self.wh_new_brand_entry.bind('<FocusOut>', self.on_wh_brand_focus_out)

        # Listbox для автокомплита марки (склад)
        self.wh_brand_listbox = tk.Listbox(row_brand, height=5, width=25, takefocus=False)
        self.wh_brand_listbox_visible = False
        self.wh_brand_listbox.bind('<<ListboxSelect>>', self.on_wh_brand_select)

        row_model = ctk.CTkFrame(self.wh_new_car_frame)
        row_model.pack(fill=tk.X, pady=3, padx=10)
        ctk.CTkLabel(row_model, text="Модель:", width=100, anchor="w").pack(side=tk.LEFT)
        self.wh_new_model_entry = ctk.CTkEntry(row_model, width=200, fg_color="white", text_color="black")
        self.wh_new_model_entry.pack(side=tk.LEFT, padx=5)
        self.wh_new_model_entry.bind('<KeyRelease>', self.on_wh_model_keyrelease)
        self.wh_new_model_entry.bind('<FocusOut>', self.on_wh_model_focus_out)

        # Listbox для автокомплита модели (склад)
        self.wh_model_listbox = tk.Listbox(row_model, height=5, width=25, takefocus=False)
        self.wh_model_listbox_visible = False
        self.wh_model_listbox.bind('<<ListboxSelect>>', self.on_wh_model_select)

        row_client = ctk.CTkFrame(self.wh_new_car_frame)
        row_client.pack(fill=tk.X, pady=3, padx=10)
        ctk.CTkLabel(row_client, text="Имя клиента:", width=100, anchor="w").pack(side=tk.LEFT)
        self.wh_new_client_name_entry = ctk.CTkEntry(row_client, width=200, fg_color="white", text_color="black")
        self.wh_new_client_name_entry.pack(side=tk.LEFT, padx=5)

        row_phone = ctk.CTkFrame(self.wh_new_car_frame)
        row_phone.pack(fill=tk.X, pady=3, padx=10)
        ctk.CTkLabel(row_phone, text="Телефон:", width=100, anchor="w").pack(side=tk.LEFT)

        # Валидация телефона: +7 и только 10 цифр после
        def validate_wh_phone(new_value):
            if len(new_value) < 2:
                return False
            if not new_value.startswith("+7"):
                return False
            if new_value == "+7":
                return True
            after_prefix = new_value[2:]
            if not after_prefix.isdigit():
                return False
            if len(after_prefix) > 10:
                return False
            return True

        vcmd_phone = (self.add_part_form_frame.register(validate_wh_phone), '%P')
        self.wh_new_phone_entry = ctk.CTkEntry(row_phone, width=200, fg_color="white", text_color="black",
                                                validate="key", validatecommand=vcmd_phone)
        self.wh_new_phone_entry.pack(side=tk.LEFT, padx=5, pady=(0, 10))
        self.wh_new_phone_entry.insert(0, "+7")

        # Название запчасти
        row2 = ctk.CTkFrame(form_container)
        row2.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row2, text="Запчасть:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.wh_part_name_entry = ctk.CTkEntry(row2, width=300, fg_color="white", text_color="black")
        self.wh_part_name_entry.pack(side=tk.LEFT, padx=5)

        # Количество
        row3 = ctk.CTkFrame(form_container)
        row3.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row3, text="Количество:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.wh_quantity_entry = ctk.CTkEntry(row3, width=100, fg_color="white", text_color="black")
        self.wh_quantity_entry.pack(side=tk.LEFT, padx=5)
        self.wh_quantity_entry.insert(0, "1")

        # Цена
        row4 = ctk.CTkFrame(form_container)
        row4.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row4, text="Цена:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.wh_price_entry = ctk.CTkEntry(row4, width=150, fg_color="white", text_color="black")
        self.wh_price_entry.pack(side=tk.LEFT, padx=5)

        # Примечания
        row5 = ctk.CTkFrame(form_container)
        row5.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row5, text="Примечания:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.wh_notes_entry = ctk.CTkEntry(row5, width=300, fg_color="white", text_color="black")
        self.wh_notes_entry.pack(side=tk.LEFT, padx=5)

        # Кнопки
        buttons_frame = ctk.CTkFrame(form_container, fg_color="transparent")
        buttons_frame.pack(pady=20)

        ctk.CTkButton(buttons_frame, text="Заказать", command=self.add_warehouse_part,
                     fg_color="#2e7d32", hover_color="#1b5e20", width=120).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(buttons_frame, text="Отмена", command=self.hide_add_part_form,
                     fg_color="#757575", hover_color="#616161", width=120).pack(side=tk.LEFT, padx=10)

        self.add_part_form_visible = True

    def search_car_for_warehouse(self):
        """Поиск машины по госномеру для склада"""
        car_number = self.wh_car_number_entry.get().strip()
        if not car_number:
            self.wh_car_info_label.configure(text="Введите госномер", text_color="orange")
            self.wh_selected_car_id = None
            self.hide_new_car_form()
            return

        car_info = self.db.get_car_info_by_number(car_number)
        if car_info:
            self.wh_selected_car_id = car_info.get("car_id")
            info_text = f"{car_info.get('car_brand', '')} {car_info.get('car_model', '')} | {car_info.get('client_name', 'Без имени')} | {car_info.get('client_phone', '')}"
            self.wh_car_info_label.configure(text=info_text, text_color="green")
            self.hide_new_car_form()
        else:
            self.wh_selected_car_id = None
            self.wh_car_info_label.configure(text="Машина не найдена — заполните данные ниже", text_color="orange")
            self.show_new_car_form()

    def show_new_car_form(self):
        """Показать форму для новой машины"""
        if not self.wh_new_car_visible:
            self.wh_new_car_frame.pack(fill=tk.X, pady=10, after=self.wh_car_info_label)
            self.wh_new_car_visible = True
            # Автоматически заполняем госномер
            car_number = self.wh_car_number_entry.get().strip().upper()
            # Увеличиваем окно
            self.add_part_form_frame.geometry("550x620")

    def hide_new_car_form(self):
        """Скрыть форму для новой машины"""
        if self.wh_new_car_visible:
            self.wh_new_car_frame.pack_forget()
            self.wh_new_car_visible = False
            self.add_part_form_frame.geometry("550x500")

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
        if not self.wh_brand_listbox_visible:
            self.wh_brand_listbox.pack(side=tk.LEFT, padx=5)
            self.wh_brand_listbox_visible = True

    def hide_wh_brand_listbox(self):
        """Скрыть список марок (склад)"""
        if self.wh_brand_listbox_visible:
            self.wh_brand_listbox.pack_forget()
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
        if not self.wh_model_listbox_visible:
            self.wh_model_listbox.pack(side=tk.LEFT, padx=5)
            self.wh_model_listbox_visible = True

    def hide_wh_model_listbox(self):
        """Скрыть список моделей (склад)"""
        if self.wh_model_listbox_visible:
            self.wh_model_listbox.pack_forget()
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

        if hasattr(self, 'add_part_form_frame') and self.add_part_form_frame:
            self.add_part_form_frame.destroy()
        self.add_part_form_visible = False

    def add_warehouse_part(self):
        """Добавить запчасть на склад"""
        car_number = self.wh_car_number_entry.get().strip().upper()
        part_name = self.wh_part_name_entry.get().strip()
        quantity_str = self.wh_quantity_entry.get().strip()
        price_str = self.wh_price_entry.get().strip()
        notes = self.wh_notes_entry.get().strip()

        if not part_name:
            messagebox.showwarning("Внимание", "Введите название запчасти!")
            return

        try:
            quantity = int(quantity_str) if quantity_str else 1
        except ValueError:
            messagebox.showwarning("Внимание", "Количество должно быть числом!")
            return

        try:
            price = float(price_str.replace(",", ".")) if price_str else None
        except ValueError:
            messagebox.showwarning("Внимание", "Цена должна быть числом!")
            return

        # Используем car_id если машина найдена
        car_id = self.wh_selected_car_id if hasattr(self, 'wh_selected_car_id') else None

        # Если госномер введён, но машина не найдена — пробуем найти автоматически
        if car_number and car_id is None:
            car_info = self.db.get_car_info_by_number(car_number)
            if car_info:
                car_id = car_info.get("car_id")
                self.wh_selected_car_id = car_id

        # Если машина не найдена и форма новой машины видна — создаём клиента и машину
        if car_id is None and self.wh_new_car_visible and car_number:
            brand = self.wh_new_brand_entry.get().strip()
            model = self.wh_new_model_entry.get().strip()
            client_name = self.wh_new_client_name_entry.get().strip()
            phone = self.wh_new_phone_entry.get().strip()

            if not brand:
                messagebox.showwarning("Внимание", "Введите марку машины!")
                return

            # Проверка телефона: должен быть +7 и 10 цифр
            if phone == "+7" or len(phone) < 12:
                messagebox.showwarning("Внимание", "Введите номер телефона полностью!\nПример: +79091234567")
                return

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
                "Внимание",
                f"Госномер '{car_number}' не найден в базе.\n\n"
                "Добавить запчасть без привязки к машине?"
            )
            if not result:
                return

        self.db.add_warehouse_part(
            car_id=car_id,
            part_name=part_name,
            quantity=quantity,
            price=price,
            notes=notes if notes else None
        )

        messagebox.showinfo("Успех", "Запчасть добавлена в заказы!")
        self.hide_add_part_form()
        self.refresh_warehouse()

    def refresh_warehouse(self):
        """Обновить список запчастей на складе"""
        # Очистка таблицы
        for item in self.warehouse_tree.get_children():
            self.warehouse_tree.delete(item)

        # Получение фильтра по статусу
        status_filter = self.warehouse_status_var.get() if hasattr(self, 'warehouse_status_var') else "Все"
        status_map = {"Все": None, "В пути": "в пути", "На складе": "на складе", "Выдано": "выдано"}
        status = status_map.get(status_filter, None)

        # Поиск по госномеру
        search_query = self.warehouse_search_entry.get().strip().upper() if hasattr(self, 'warehouse_search_entry') else ""

        # Получение данных (новая структура с JOIN)
        parts = self.db.get_all_warehouse_parts(status=status)

        for part in parts:
            # Новая структура: id, car_number, car_brand, car_model, client_name, client_phone,
            #                  part_name, quantity, price, status, order_date, received_date, notes, car_id
            part_id, car_number, car_brand, car_model, client_name, client_phone, \
                part_name, quantity, price, part_status, order_date, received_date, notes, car_id = part

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

            self.warehouse_tree.insert("", tk.END, values=(
                part_id,
                car_info,
                client_info,
                part_name,
                quantity,
                price_str,
                part_status,
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
            messagebox.showwarning("Внимание", "Выберите запчасть из списка!")
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])

        # Если статус "на складе", устанавливаем дату прихода
        received_date = None
        if new_status == "на складе":
            from datetime import date
            received_date = date.today()

        self.db.update_warehouse_part_status(part_id, new_status, received_date)
        self.refresh_warehouse()

    def edit_warehouse_part(self):
        """Редактировать выбранную запчасть"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запчасть из списка!")
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])

        # Получаем данные запчасти из БД
        part_data = self.db.get_warehouse_part_by_id(part_id)
        if not part_data:
            messagebox.showerror("Ошибка", "Запчасть не найдена!")
            return

        # Создаём окно редактирования
        edit_window = ctk.CTkToplevel(self.root)
        edit_window.title("Редактировать запчасть")
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

        ctk.CTkLabel(form_frame, text="Редактирование запчасти",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(0, 15))

        # Информация о машине (только для чтения)
        car_info = f"{part_data.get('car_number', '')} {part_data.get('car_brand', '')} {part_data.get('car_model', '')}".strip()
        if car_info:
            ctk.CTkLabel(form_frame, text=f"Авто: {car_info}", text_color="gray").pack(anchor="w", pady=(0, 10))

        # Название запчасти
        row1 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text="Запчасть:", width=100, anchor="w").pack(side=tk.LEFT)
        part_name_entry = ctk.CTkEntry(row1, width=280, fg_color="white", text_color="black")
        part_name_entry.pack(side=tk.LEFT)
        part_name_entry.insert(0, part_data.get('part_name', ''))

        # Количество
        row2 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row2.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row2, text="Количество:", width=100, anchor="w").pack(side=tk.LEFT)
        quantity_entry = ctk.CTkEntry(row2, width=100, fg_color="white", text_color="black")
        quantity_entry.pack(side=tk.LEFT)
        quantity_entry.insert(0, str(part_data.get('quantity', 1)))

        # Цена
        row3 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row3.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row3, text="Цена:", width=100, anchor="w").pack(side=tk.LEFT)
        price_entry = ctk.CTkEntry(row3, width=150, fg_color="white", text_color="black")
        price_entry.pack(side=tk.LEFT)
        if part_data.get('price'):
            price_entry.insert(0, str(part_data.get('price')))

        # Статус
        row4 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row4.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row4, text="Статус:", width=100, anchor="w").pack(side=tk.LEFT)
        status_var = tk.StringVar(value=part_data.get('status', 'в пути'))
        status_combo = ctk.CTkComboBox(row4, variable=status_var,
                                        values=["в пути", "на складе", "выдано"], width=150)
        status_combo.pack(side=tk.LEFT)

        # Примечания
        row5 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row5.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row5, text="Примечания:", width=100, anchor="w").pack(side=tk.LEFT)
        notes_entry = ctk.CTkEntry(row5, width=280, fg_color="white", text_color="black")
        notes_entry.pack(side=tk.LEFT)
        if part_data.get('notes'):
            notes_entry.insert(0, part_data.get('notes'))

        def save_changes():
            new_part_name = part_name_entry.get().strip()
            if not new_part_name:
                messagebox.showwarning("Внимание", "Введите название запчасти!")
                return

            try:
                new_quantity = int(quantity_entry.get().strip()) if quantity_entry.get().strip() else 1
            except ValueError:
                messagebox.showwarning("Внимание", "Количество должно быть числом!")
                return

            try:
                price_str = price_entry.get().strip().replace(",", ".")
                new_price = float(price_str) if price_str else None
            except ValueError:
                messagebox.showwarning("Внимание", "Цена должна быть числом!")
                return

            new_status = status_var.get()
            new_notes = notes_entry.get().strip() or None

            self.db.update_warehouse_part(part_id, new_part_name, new_quantity, new_price, new_status, new_notes)
            edit_window.destroy()
            self.refresh_warehouse()
            messagebox.showinfo("Успех", "Запчасть обновлена!")

        # Кнопки
        buttons_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        buttons_frame.pack(pady=20)

        ctk.CTkButton(buttons_frame, text="Сохранить", command=save_changes,
                     fg_color="#2e7d32", hover_color="#1b5e20", width=120).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(buttons_frame, text="Отмена", command=edit_window.destroy,
                     fg_color="#757575", hover_color="#616161", width=120).pack(side=tk.LEFT, padx=10)

    def delete_warehouse_part(self):
        """Удалить выбранную запчасть"""
        selection = self.warehouse_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запчасть из списка!")
            return

        values = self.warehouse_tree.item(selection[0], "values")
        part_id = int(values[0])
        part_name = values[3]

        if messagebox.askyesno("Подтверждение", f"Удалить запчасть '{part_name}'?"):
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
            text="Выберите период",
            font=("Segoe UI", 20, "bold"),
            anchor="center"
        )

        title.pack(fill=tk.X, pady=(0, 10))

        dates_frame = ctk.CTkFrame(period_frame)
        dates_frame.pack()

        ctk.CTkLabel(dates_frame, text="С:").pack(side=tk.LEFT, padx=5)
        self.date_from = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy',
                                    locale='ru_RU')
        self.date_from.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(dates_frame, text="По:").pack(side=tk.LEFT, padx=15)
        self.date_to = DateEntry(dates_frame, width=15, date_pattern='dd.mm.yyyy',
                                  locale='ru_RU')
        self.date_to.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(dates_frame, text="% мастеру:").pack(side=tk.LEFT, padx=(20, 5))
        settings = self.load_settings()
        self.percent_var = tk.StringVar(value=str(settings.get('master_percent', 50)))
        self.percent_var.trace_add('write', self.on_percent_changed)
        self.percent_entry = ctk.CTkEntry(dates_frame, width=80,
                                          textvariable=self.percent_var, fg_color="white", text_color="black")
        self.percent_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkLabel(dates_frame, text="%").pack(side=tk.LEFT)

        ctk.CTkButton(dates_frame, text="Сформировать отчёт",
                   command=self.generate_report).pack(side=tk.LEFT, padx=20)

        # Сводка по работникам
        summary_frame = ctk.CTkFrame(self.reports_frame)
        summary_frame.pack(fill=tk.X, padx=10, pady=10)
        title_masters = ctk.CTkLabel(
            summary_frame,
            text="Сводка по мастерам",
            font=("Segoe UI", 20, "bold"),
            anchor="center")
        title_masters.pack(fill=tk.X, pady=(0, 10))

        columns = ("name", "count", "total", "percent")
        self.summary_tree = ttk.Treeview(summary_frame, columns=columns, show="headings", height=4)
        self.summary_tree.heading("name", text="ФИО мастера")
        self.summary_tree.heading("count", text="Кол-во работ")
        self.summary_tree.heading("total", text="Итого заработано")
        self.summary_tree.heading("percent", text="% мастеру")

        self.summary_tree.column("name", width=200)
        self.summary_tree.column("count", width=200, anchor=tk.CENTER)
        self.summary_tree.column("total", width=230, anchor=tk.CENTER)
        self.summary_tree.column("percent", width=210, anchor=tk.CENTER)

        # Настройка цветов для чередующихся строк (zebra stripes)
        self.summary_tree.tag_configure('oddrow', background='#ffffff')
        self.summary_tree.tag_configure('evenrow', background='#f0f0f0')

        self.summary_tree.pack()

        # Общая сумма - фрейм с разноцветными label-ами
        self.total_frame = ctk.CTkFrame(summary_frame)
        self.total_frame.pack(pady=10)

        # Зелёный цвет для доходов/прибыли, красный для расходов
        green_color = "#2e7d32"
        red_color = "#c62828"

        # Загружаем процент из настроек для начального отображения
        settings = self.load_settings()
        initial_percent = settings.get('master_percent', 50)

        self.income_label = ctk.CTkLabel(self.total_frame, text="ДОХОД (работы): 0,00 руб.",
                                        font=("Arial", 12, "bold"), text_color=green_color)
        self.income_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.other_income_label = ctk.CTkLabel(self.total_frame, text="Прочий доход: 0,00 руб.",
                                              font=("Arial", 12, "bold"), text_color=green_color)
        self.other_income_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.expenses_label = ctk.CTkLabel(self.total_frame, text="РАСХОДЫ: 0,00 руб.",
                                          font=("Arial", 12, "bold"), text_color=red_color)
        self.expenses_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.masters_label = ctk.CTkLabel(self.total_frame, text=f"Мастерам ({initial_percent:.0f}%): 0,00 руб.",
                                         font=("Arial", 12, "bold"), text_color=red_color)
        self.masters_label.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(self.total_frame, text="|", font=("Arial", 12)).pack(side=tk.LEFT, padx=2)

        self.profit_label = ctk.CTkLabel(self.total_frame, text="ЧИСТАЯ ПРИБЫЛЬ: 0,00 руб.",
                                        font=("Arial", 12, "bold"), text_color=green_color)
        self.profit_label.pack(side=tk.LEFT, padx=5)

        # Tooltip для "Прочий доход" и "РАСХОДЫ"
        self.other_income_tooltip = LabelTooltip(self.other_income_label, self.format_currency, is_expense=False)
        self.expenses_tooltip = LabelTooltip(self.expenses_label, self.format_currency, is_expense=True)

    def generate_report(self, show_empty_message=True):
        """Сформировать отчёт за период"""
        date_from = self.date_from.get_date().strftime('%Y-%m-%d')
        date_to = self.date_to.get_date().strftime('%Y-%m-%d')

        if date_from > date_to:
            messagebox.showwarning("Внимание", "Дата 'С' не может быть больше даты 'По'!")
            return

        # Получаем процент
        try:
            percent = float(self.percent_var.get().replace(',', '.'))
            if percent < 0 or percent > 100:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректный процент (0-100)!")
            return

        # Очистка таблицы
        for item in self.summary_tree.get_children():
            self.summary_tree.delete(item)

        # Сводка
        summary = self.db.get_summary_by_period(date_from, date_to)
        grand_total = 0
        total_percent_sum = 0
        summary_row_index = 0
        for row in summary:
            name, total, count = row
            total = float(total)  # MariaDB возвращает Decimal
            grand_total += total
            worker_share = total * percent / 100
            total_percent_sum += worker_share

            # Определяем тег для чередующихся строк
            row_tag = 'oddrow' if summary_row_index % 2 == 0 else 'evenrow'

            self.summary_tree.insert("", tk.END, values=(
                name,
                count,
                self.format_currency(total),
                self.format_currency(worker_share)
            ), tags=(row_tag,))

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
        self.income_label.configure(text=f"ДОХОД (работы): {self.format_currency(grand_total)}")
        self.other_income_label.configure(text=f"Прочий доход: {self.format_currency(other_income)}")
        self.expenses_label.configure(text=f"РАСХОДЫ: {self.format_currency(total_expenses)}")
        self.masters_label.configure(text=f"Мастерам ({percent:.0f}%): {self.format_currency(total_percent_sum)}")

        # Цвет прибыли зависит от значения
        profit_color = "#2e7d32" if net_profit >= 0 else "#c62828"  # Зелёный если >= 0, красный если < 0
        self.profit_label.configure(text=f"ЧИСТАЯ ПРИБЫЛЬ: {self.format_currency(net_profit)}", text_color=profit_color)

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

        ctk.CTkLabel(import_frame, text="Формат JSON: {\"Марка\": [\"Модель1\", \"Модель2\"]}", anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text="Импортировать из файла JSON",
                   command=self.import_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление марки
        brand_frame = ctk.CTkFrame(center_container)
        brand_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(brand_frame, text="Название марки:").pack(side=tk.LEFT, padx=5)
        self.brand_name_entry = ctk.CTkEntry(brand_frame, width=300, fg_color="white", text_color="black")
        self.brand_name_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(brand_frame, text="Добавить марку", command=self.add_brand, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Добавление модели
        model_frame = ctk.CTkFrame(center_container)
        model_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(model_frame, text="Марка:").pack(side=tk.LEFT, padx=5)
        self.brand_combo = ctk.CTkComboBox(model_frame, width=250, fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.brand_combo.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(model_frame, text="Модель:").pack(side=tk.LEFT, padx=5)
        self.model_name_entry = ctk.CTkEntry(model_frame, width=200, fg_color="white", text_color="black")
        self.model_name_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(model_frame, text="Добавить модель", command=self.add_model, fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список марок и моделей
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        # Две колонки: марки и модели
        left_frame = ctk.CTkFrame(list_frame)
        left_frame.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(left_frame, text="Марки:", anchor="w").pack(anchor=tk.W)
        self.brands_listbox = tk.Listbox(left_frame, height=15, width=35)
        self.brands_listbox.pack()
        self.brands_listbox.bind('<<ListboxSelect>>', self.on_brand_listbox_select)
        ctk.CTkButton(left_frame, text="Удалить марку", command=self.delete_brand, width=250, fg_color="red", hover_color="darkred").pack(pady=5)

        right_frame = ctk.CTkFrame(list_frame)
        right_frame.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(right_frame, text="Модели выбранной марки:", anchor="w").pack(anchor=tk.W)
        self.models_listbox = tk.Listbox(right_frame, height=15, width=35)
        self.models_listbox.pack()
        ctk.CTkButton(right_frame, text="Удалить модель", command=self.delete_model, width=250, fg_color="red", hover_color="darkred").pack(pady=5)

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
            messagebox.showwarning("Внимание", "Введите название марки!")
            return

        if self.db.add_car_brand(brand_name):
            messagebox.showinfo("Успех", f"Марка '{brand_name}' добавлена!")
            self.brand_name_entry.delete(0, tk.END)
            self.refresh_brands_list()
        else:
            messagebox.showerror("Ошибка", "Такая марка уже существует!")

    def add_model(self):
        """Добавить модель"""
        if not self.brand_combo.get():
            messagebox.showwarning("Внимание", "Выберите марку!")
            return

        model_name = self.model_name_entry.get().strip()
        if not model_name:
            messagebox.showwarning("Внимание", "Введите название модели!")
            return

        brand_id = self.brands_data[self.brand_combo.get()]

        if self.db.add_car_model(brand_id, model_name):
            messagebox.showinfo("Успех", f"Модель '{model_name}' добавлена!")
            self.model_name_entry.delete(0, tk.END)
            # Обновляем список моделей если выбрана эта марка
            selection = self.brands_listbox.curselection()
            if selection and self.brands_listbox.get(selection[0]) == self.brand_combo.get():
                self.on_brand_listbox_select(None)
        else:
            messagebox.showerror("Ошибка", "Такая модель для этой марки уже существует!")

    def delete_brand(self):
        """Удалить марку"""
        selection = self.brands_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите марку для удаления!")
            return

        brand_name = self.brands_listbox.get(selection[0])
        brand_id = self.brands_data[brand_name]

        if messagebox.askyesno("Подтверждение",
                               f"Удалить марку '{brand_name}'?\n\nВсе модели этой марки также будут удалены!"):
            self.db.delete_car_brand(brand_id)
            messagebox.showinfo("Успех", "Марка удалена!")
            self.refresh_brands_list()
            self.models_listbox.delete(0, tk.END)

    def delete_model(self):
        """Удалить модель"""
        selection = self.models_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите модель для удаления!")
            return

        model_name = self.models_listbox.get(selection[0])
        model_id = self.models_data[model_name]

        if messagebox.askyesno("Подтверждение", f"Удалить модель '{model_name}'?"):
            self.db.delete_car_model(model_id)
            messagebox.showinfo("Успех", "Модель удалена!")
            # Обновляем список моделей
            brand_selection = self.brands_listbox.curselection()
            if brand_selection:
                self.on_brand_listbox_select(None)

    def import_from_file(self):
        """Импорт марок и моделей из JSON файла"""
        file_path = filedialog.askopenfilename(
            title="Выберите JSON файл",
            filetypes=[("JSON файлы", "*.json"), ("Все файлы", "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                messagebox.showerror("Ошибка", "Неверный формат файла! Ожидается словарь {\"Марка\": [\"Модель1\", ...]}")
                return

            added_brands, added_models = self.db.import_brands_models_from_dict(data)
            messagebox.showinfo("Успех",
                              f"Импорт завершён!\n\nДобавлено марок: {added_brands}\nДобавлено моделей: {added_models}")
            self.refresh_brands_list()

        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Ошибка чтения JSON файла!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка импорта: {str(e)}")

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
        ctk.CTkLabel(center_container, text="Ключевые слова для автодополнения",
                    font=("Segoe UI", 16, "bold")).pack(pady=10)

        # Импорт из файла
        import_frame = ctk.CTkFrame(center_container)
        import_frame.pack(pady=10)

        ctk.CTkLabel(import_frame, text="Формат: текстовый файл (каждое слово на новой строке) или JSON (список слов)", anchor="w").pack(anchor=tk.W, pady=5)
        ctk.CTkButton(import_frame, text="Импортировать из файла",
                   command=self.import_keywords_from_file, width=400, fg_color="green", hover_color="darkgreen").pack(anchor=tk.W, pady=5)

        # Добавление ключевого слова
        add_frame = ctk.CTkFrame(center_container)
        add_frame.pack(fill=tk.X, pady=10)

        ctk.CTkLabel(add_frame, text="Ключевое слово:", width=120, anchor="w").pack(side=tk.LEFT, padx=5)
        self.keyword_entry = ctk.CTkEntry(add_frame, width=350, fg_color="white", text_color="black")
        self.keyword_entry.pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(add_frame, text="Добавить", command=self.add_keyword_action,
                     fg_color="green", hover_color="darkgreen").pack(side=tk.LEFT, padx=5)

        # Список ключевых слов
        list_frame = ctk.CTkFrame(center_container)
        list_frame.pack(pady=10)

        ctk.CTkLabel(list_frame, text="Список ключевых слов:", anchor="w").pack(anchor=tk.W)

        # Treeview для ключевых слов
        columns = ("id", "keyword")
        self.keywords_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.keywords_tree.heading("id", text="ID")
        self.keywords_tree.heading("keyword", text="Ключевое слово")
        self.keywords_tree.column("id", width=50, anchor=tk.CENTER)
        self.keywords_tree.column("keyword", width=450, anchor=tk.W)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.keywords_tree.yview)
        self.keywords_tree.configure(yscrollcommand=scrollbar.set)

        self.keywords_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        ctk.CTkButton(center_container, text="Удалить выбранное ключевое слово",
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
            messagebox.showwarning("Внимание", "Введите ключевое слово!")
            return

        if self.db.add_keyword(keyword):
            messagebox.showinfo("Успех", f"Ключевое слово '{keyword}' добавлено!")
            self.keyword_entry.delete(0, tk.END)
            self.refresh_keywords_list()
        else:
            messagebox.showerror("Ошибка", "Такое ключевое слово уже существует!")

    def delete_keyword_action(self):
        """Удалить ключевое слово"""
        selected = self.keywords_tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите ключевое слово для удаления!")
            return

        item = self.keywords_tree.item(selected[0])
        keyword_id = item['values'][0]
        keyword = item['values'][1]

        if messagebox.askyesno("Подтверждение", f"Удалить ключевое слово '{keyword}'?"):
            self.db.delete_keyword(keyword_id)
            messagebox.showinfo("Успех", "Ключевое слово удалено!")
            self.refresh_keywords_list()

    def import_keywords_from_file(self):
        """Импорт ключевых слов из файла (TXT или JSON)"""
        file_path = filedialog.askopenfilename(
            title="Выберите файл",
            filetypes=[("Текстовые файлы", "*.txt"), ("JSON файлы", "*.json"), ("Все файлы", "*.*")]
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
                    messagebox.showerror("Ошибка", "Неверный формат JSON! Ожидается список слов: ['слово1', 'слово2']")
                    return
            else:
                # Текстовый файл - каждое слово на новой строке
                keywords = content.strip().splitlines()

            if not keywords:
                messagebox.showwarning("Внимание", "Файл пустой или не содержит ключевых слов!")
                return

            added = self.db.import_keywords_from_list(keywords)
            messagebox.showinfo("Успех", f"Импорт завершён! Добавлено ключевых слов: {added}")
            self.refresh_keywords_list()

        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Ошибка чтения JSON файла!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка импорта: {str(e)}")

    # ===== ВКЛАДКА РАСХОДОВ =====

    def setup_expenses_tab(self):
        """Настройка вкладки расходов"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self.expenses_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Центрированный контейнер
        center_container = ctk.CTkFrame(main_frame)
        center_container.pack(anchor=tk.CENTER, pady=10)

        # Переключатель Расход/Доход
        switch_row = ctk.CTkFrame(center_container)
        switch_row.pack(fill=tk.X, pady=10)

        self.expense_type_label = ctk.CTkLabel(switch_row, text="Расход", width=80, anchor="e",
                                                font=("Segoe UI", 14, "bold"), text_color="#d32f2f")
        self.expense_type_label.pack(side=tk.LEFT, padx=5)

        self.is_income_var = tk.BooleanVar(value=False)
        self.income_switch = ctk.CTkSwitch(switch_row, text="", variable=self.is_income_var,
                                           command=self.on_income_switch_changed,
                                           width=50, height=26,
                                           progress_color="#4caf50", button_color="white",
                                           fg_color="#d32f2f", button_hover_color="#f0f0f0")
        self.income_switch.pack(side=tk.LEFT, padx=10)

        self.income_type_label = ctk.CTkLabel(switch_row, text="Доход", width=80, anchor="w",
                                               font=("Segoe UI", 14), text_color="gray")
        self.income_type_label.pack(side=tk.LEFT, padx=5)

        # Категория
        row1 = ctk.CTkFrame(center_container)
        row1.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row1, text="Категория:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_category_combo = ctk.CTkComboBox(row1, width=350,
                                                    values=["Аренда", "Налоги", "Коммунальные услуги", "Закупка запчастей",
                                                            "Инструменты", "Реклама", "Прочее", "Доход"],
                                                    fg_color="white", text_color="black", button_color="#0078d7", button_hover_color="#005a9e")
        self.expense_category_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.expense_category_combo.set("Аренда")

        # Описание
        row2 = ctk.CTkFrame(center_container)
        row2.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row2, text="Описание:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_desc_entry = ctk.CTkEntry(row2, width=400, fg_color="white", text_color="black")
        self.expense_desc_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Сумма
        row3 = ctk.CTkFrame(center_container)
        row3.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row3, text="Сумма (руб.):", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_amount_entry = ctk.CTkEntry(row3, width=200, fg_color="white", text_color="black")
        self.expense_amount_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Дата
        row4 = ctk.CTkFrame(center_container)
        row4.pack(fill=tk.X, pady=5)
        ctk.CTkLabel(row4, text="Дата:", width=150, anchor="w").pack(side=tk.LEFT, padx=5)
        self.expense_date_entry = DateEntry(row4, width=30, date_pattern='dd.mm.yyyy',
                                             locale='ru_RU')
        self.expense_date_entry.pack(side=tk.LEFT, padx=5)

        # Кнопка добавления
        self.add_expense_btn = ctk.CTkButton(center_container, text='Добавить расход',
                   command=self.add_expense, width=550, height=50, fg_color="#d32f2f", hover_color="#b71c1c")
        self.add_expense_btn.pack(anchor=tk.CENTER, pady=20)

        # История расходов и доходов
        history_frame = ctk.CTkFrame(center_container)
        history_frame.pack(pady=10)

        columns = ("id", "type", "category", "desc", "amount", "date")
        self.expenses_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=12)
        self.expenses_tree.heading("id", text="ID")
        self.expenses_tree.heading("type", text="Тип")
        self.expenses_tree.heading("category", text="Категория")
        self.expenses_tree.heading("desc", text="Описание")
        self.expenses_tree.heading("amount", text="Сумма")
        self.expenses_tree.heading("date", text="Дата")

        self.expenses_tree.column("id", width=50, anchor=tk.CENTER)
        self.expenses_tree.column("type", width=80, anchor=tk.CENTER)
        self.expenses_tree.column("category", width=150, anchor=tk.W)
        self.expenses_tree.column("desc", width=250, anchor=tk.W)
        self.expenses_tree.column("amount", width=100, anchor=tk.CENTER)
        self.expenses_tree.column("date", width=100, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=self.expenses_tree.yview)
        self.expenses_tree.configure(yscrollcommand=scrollbar.set)

        # Настройка цветов для строк
        self.expenses_tree.tag_configure('oddrow', background='#ffffff')
        self.expenses_tree.tag_configure('evenrow', background='#f0f0f0')
        self.expenses_tree.tag_configure('income', background='#e8f5e9')
        self.expenses_tree.tag_configure('expense', background='#ffebee')

        self.expenses_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Кнопка удаления
        self.delete_expense_btn = ctk.CTkButton(center_container, text="Удалить выбранную запись",
                   command=self.delete_expense, width=550, fg_color="red", hover_color="#555555")
        self.delete_expense_btn.pack(anchor=tk.CENTER, pady=10)

    def on_income_switch_changed(self):
        """Обработчик переключения расход/доход"""
        is_income = self.is_income_var.get()
        if is_income:
            self.expense_type_label.configure(text_color="gray", font=("Segoe UI", 14))
            self.income_type_label.configure(text_color="#4caf50", font=("Segoe UI", 14, "bold"))
            self.add_expense_btn.configure(text="Добавить доход", fg_color="#4caf50", hover_color="#388e3c")
        else:
            self.expense_type_label.configure(text_color="#d32f2f", font=("Segoe UI", 14, "bold"))
            self.income_type_label.configure(text_color="gray", font=("Segoe UI", 14))
            self.add_expense_btn.configure(text="Добавить расход", fg_color="#d32f2f", hover_color="#b71c1c")

    def add_expense(self):
        """Добавить расход или доход"""
        category = self.expense_category_combo.get().strip()
        if not category:
            messagebox.showwarning("Внимание", "Выберите категорию!")
            return

        description = self.expense_desc_entry.get().strip()
        is_income = self.is_income_var.get()
        if not description:
            messagebox.showwarning("Внимание", f"Введите описание {'дохода' if is_income else 'расхода'}!")
            return

        try:
            amount = float(self.expense_amount_entry.get().replace(',', '.'))
            if amount <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Внимание", "Введите корректную сумму!")
            return

        expense_date = self.expense_date_entry.get_date().strftime('%Y-%m-%d')

        self.db.add_expense(description, amount, expense_date, category, is_income)

        messagebox.showinfo("Успех", f"{'Доход' if is_income else 'Расход'} добавлен!")
        self.expense_desc_entry.delete(0, tk.END)
        self.expense_amount_entry.delete(0, tk.END)
        self.refresh_expenses()

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
            type_text = "Доход" if is_income else "Расход"
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
            messagebox.showwarning("Внимание", "Выберите запись для удаления!")
            return

        item = self.expenses_tree.item(selected[0])
        expense_id = item['values'][0]
        type_text = item['values'][1]
        description = item['values'][3]

        if messagebox.askyesno("Подтверждение", f"Удалить {type_text.lower()} '{description}'?"):
            self.db.delete_expense(expense_id)
            messagebox.showinfo("Успех", f"{type_text} удалён!")
            self.refresh_expenses()

    # ===== QR-КОД С ТЕКСТОМ =====

    def _generate_work_order(self, tree):
        """Общая функция формирования листа наряда"""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите запись для формирования листа наряда!")
            return

        # Получаем данные из выбранной строки
        item = tree.item(selected[0])

        # Если выбрана запчасть (дочерний элемент), получаем родительскую запись
        parent = tree.parent(selected[0])
        if parent:
            # Это запчасть, берем данные из родительской записи
            item = tree.item(parent)

        values = item['values']
        order_num = values[0]
        worker_name = values[1]
        car_info = values[2]
        client_info = values[3]
        description = values[4]
        amount_str = values[5]
        parts_str = values[6]
        parts_price_str = values[7]
        date_str = values[8]

        # Находим работу в базе данных по этим параметрам
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Преобразуем дату обратно в формат БД
        work_date = datetime.strptime(date_str, '%d.%m.%Y').strftime('%Y-%m-%d')

        # Извлекаем сумму из форматированной строки
        amount = float(amount_str.replace(' руб.', '').replace('.', '').replace(',', '.'))

        # Разбираем информацию о машине
        car_parts = car_info.split() if car_info else []
        car_brand = car_parts[0] if len(car_parts) > 0 else ""
        car_model = car_parts[1] if len(car_parts) > 1 else ""
        car_number = car_parts[2] if len(car_parts) > 2 else ""

        cursor.execute('''
            SELECT wk.id
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE w.full_name = %s AND wk.description = %s AND wk.amount = %s AND wk.work_date = %s
            ORDER BY wk.created_at DESC
            LIMIT 1
        ''', (worker_name, description, amount, work_date))

        result = cursor.fetchone()
        conn.close()

        if not result:
            messagebox.showerror("Ошибка", "Не удалось найти работу в базе данных!")
            return

        work_id = result[0]

        # Получаем полную информацию о работе
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT w.full_name, wk.description, wk.amount, wk.work_date, wk.car_brand, wk.car_model, wk.car_number, wk.order_number, wk.client_name, wk.client_phone
            FROM works wk
            JOIN workers w ON wk.worker_id = w.id
            WHERE wk.id = %s
        ''', (work_id,))
        work = cursor.fetchone()
        conn.close()

        if not work:
            messagebox.showerror("Ошибка", "Запись не найдена!")
            return

        worker_name, description, work_amount, work_date, car_brand, car_model, car_number, order_number, client_name, client_phone = work
        work_amount = float(work_amount)  # MariaDB возвращает Decimal
        # MariaDB возвращает даты как объекты date, а не строки
        if isinstance(work_date, str):
            display_date = datetime.strptime(work_date, '%Y-%m-%d').strftime('%d.%m.%Y')
        else:
            display_date = work_date.strftime('%d.%m.%Y')

        # Получаем запчасти
        parts = self.db.get_parts_by_work_id(work_id)

        # Формируем текст листа наряда
        # Загружаем информацию о компании из настроек
        settings = self.load_settings()
        company_info = settings.get('company_info', '')

        order_text = ""
        if company_info:
            order_text += company_info + "\n\n"
        order_text += "=" * 60 + "\n"
        order_num_str = f" № {order_number}" if order_number else ""
        order_text += f"                      ЛИСТ НАРЯД{order_num_str}\n"
        order_text += "=" * 60 + "\n\n"
        order_text += f"Дата: {display_date}\n"
        order_text += f"Автомобиль: {car_brand} {car_model} {car_number}\n"
        # Данные клиента
        if client_name or client_phone:
            client_str = ""
            if client_name:
                client_str += client_name
            if client_phone:
                if client_str:
                    client_str += f", тел.: {client_phone}"
                else:
                    client_str = f"тел.: {client_phone}"
            order_text += f"Клиент: {client_str}\n"
        order_text += f"Мастер: {worker_name}\n"
        order_text += "\n" + "-" * 60 + "\n"
        order_text += "ЗАПЧАСТИ:\n"
        order_text += "-" * 60 + "\n"

        parts_total = 0
        if parts:
            for part_name, part_price in parts:
                part_price = float(part_price)
                parts_total += part_price
                # Разбиваем длинное название на строки
                if len(part_name) <= 40:
                    order_text += f"  {part_name:<40} {self.format_currency(part_price):>15}\n"
                else:
                    # Разбиваем название на части по 40 символов
                    lines = []
                    remaining = part_name
                    while remaining:
                        lines.append(remaining[:40])
                        remaining = remaining[40:]

                    # Выводим все строки кроме последней без цены
                    for line in lines[:-1]:
                        order_text += f"  {line:<40}\n"

                    # Последняя строка с ценой
                    order_text += f"  {lines[-1]:<40} {self.format_currency(part_price):>15}\n"
        else:
            order_text += "  Нет запчастей\n"

        order_text += "\n" + "-" * 60 + "\n"
        order_text += "РАБОТЫ:\n"
        order_text += "-" * 60 + "\n"
        # Разбиваем длинное название работы на строки
        if len(description) <= 40:
            order_text += f"  {description:<40} {self.format_currency(work_amount):>15}\n"
        else:
            # Разбиваем название на части по 40 символов
            lines = []
            remaining = description
            while remaining:
                lines.append(remaining[:40])
                remaining = remaining[40:]

            # Выводим все строки кроме последней без цены
            for line in lines[:-1]:
                order_text += f"  {line:<40}\n"

            # Последняя строка с ценой
            order_text += f"  {lines[-1]:<40} {self.format_currency(work_amount):>15}\n"

        order_text += "\n" + "=" * 60 + "\n"
        order_text += "ИТОГО:\n"
        order_text += "=" * 60 + "\n"
        order_text += f"  {'Работы:':<33} {self.format_currency(work_amount):>23}\n"
        order_text += f"  {'Запчасти:':<33} {self.format_currency(parts_total):>23}\n"
        order_text += "-" * 60 + "\n"
        order_text += f"  {'ИТОГО:':<33} {self.format_currency(work_amount + parts_total):>23}\n"
        order_text += "=" * 60 + "\n"

        # Создаем QR-код с текстом листа наряда напрямую (минимальный размер)
        # Используем UTF-8 кодировку для правильного отображения кириллицы
        qr = qrcode.QRCode(version=1, box_size=2, border=1)
        qr.add_data(order_text.encode('utf-8'))
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")

        # Показываем QR-код в новом окне
        self.show_qr_window(qr_image, order_text, car_number, order_number)

    def save_work_order_to_pdf(self, qr_image, order_text, car_number="", order_number=""):
        """Сохранить лист наряд в PDF файл"""
        # Формируем имя файла по умолчанию из номера машины
        default_filename = f"{car_number}.pdf" if car_number else "лист_наряд.pdf"

        # Запрашиваем у пользователя где сохранить файл
        file_path = filedialog.asksaveasfilename(
            title="Сохранить лист наряд как PDF",
            initialfile=default_filename,
            defaultextension=".pdf",
            filetypes=[("PDF файлы", "*.pdf"), ("Все файлы", "*.*")]
        )

        if not file_path:
            return

        try:
            # Создаем PDF
            c = canvas.Canvas(file_path, pagesize=A4)
            width, height = A4

            # Регистрируем шрифт с поддержкой кириллицы
            try:
                font_path = "C:\\Windows\\Fonts\\arial.ttf"
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('Arial', font_path))
                    font_name = "Arial"
                else:
                    font_name = "Courier"
            except:
                font_name = "Courier"

            # Сохраняем QR-код во временный файл
            temp_qr_path = tempfile.mktemp(suffix=".png")
            qr_image.save(temp_qr_path)

            # Параметры форматирования
            margin_left = 50
            margin_right = 50
            margin_top = 50
            margin_bottom = 50

            # Загружаем информацию о компании
            settings = self.load_settings()
            company_info = settings.get('company_info', '')

            # Добавляем информацию о компании в начало
            current_y = height - margin_top
            if company_info:
                c.setFont(font_name, 11)
                for line in company_info.split('\n'):
                    c.drawCentredString(width / 2, current_y, line)
                    current_y -= 16
                current_y -= 10  # Отступ после информации о компании

            # Добавляем заголовок
            c.setFont(font_name, 16)
            title_y = current_y
            title_text = f"ЛИСТ НАРЯД № {order_number}" if order_number else "ЛИСТ НАРЯД"
            c.drawCentredString(width / 2, title_y, title_text)

            # Добавляем QR-код
            qr_size = 150
            qr_x = (width - qr_size) / 2
            qr_y = title_y - qr_size - 20
            c.drawImage(temp_qr_path, qr_x, qr_y, qr_size, qr_size)

            # Добавляем текст листа наряда с увеличенным шрифтом
            c.setFont(font_name, 12)
            text_y = qr_y - 30
            line_height = 18
            max_width = width - margin_left - margin_right

            for line in order_text.split('\n'):
                if text_y < margin_bottom:  # Если место заканчивается, создаем новую страницу
                    c.showPage()
                    c.setFont(font_name, 12)
                    text_y = height - margin_top

                # Если строка слишком длинная, разбиваем её
                if c.stringWidth(line, font_name, 12) > max_width:
                    words = line.split()
                    current_line = ""
                    for word in words:
                        test_line = current_line + " " + word if current_line else word
                        if c.stringWidth(test_line, font_name, 12) <= max_width:
                            current_line = test_line
                        else:
                            if current_line:
                                c.drawString(margin_left, text_y, current_line)
                                text_y -= line_height
                                if text_y < margin_bottom:
                                    c.showPage()
                                    c.setFont(font_name, 12)
                                    text_y = height - margin_top
                            current_line = word
                    if current_line:
                        c.drawString(margin_left, text_y, current_line)
                        text_y -= line_height
                else:
                    c.drawString(margin_left, text_y, line)
                    text_y -= line_height

            # Сохраняем PDF
            c.save()

            # Удаляем временный файл QR-кода
            try:
                os.remove(temp_qr_path)
            except:
                pass

            messagebox.showinfo("Успех", f"Лист наряд сохранён в:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать PDF:\n{str(e)}")

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
                alignment=TA_CENTER,
                spaceAfter=5
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
                alignment=TA_CENTER,
                spaceAfter=15
            )
            elements.append(Paragraph("ЛИСТ НАРЯД", title_style))

            # ═══════════════════════════════════════════════════════
            # ИНФОРМАЦИЯ О КЛИЕНТЕ И АВТОМОБИЛЕ
            # ═══════════════════════════════════════════════════════
            info_data = [
                [Paragraph("<b>Дата:</b>", style_normal), Paragraph(display_date, style_normal),
                 Paragraph("<b>Клиент:</b>", style_normal), Paragraph(client_name or "-", style_normal)],
                [Paragraph("<b>Телефон:</b>", style_normal), Paragraph(client_phone or "-", style_normal),
                 Paragraph("<b>Автомобиль:</b>", style_normal), Paragraph(car_info or "-", style_normal)],
            ]

            col_widths = [content_width * 0.12, content_width * 0.28, content_width * 0.15, content_width * 0.45]
            info_table = Table(info_data, colWidths=col_widths)
            info_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 15))

            # ═══════════════════════════════════════════════════════
            # РАБОТЫ
            # ═══════════════════════════════════════════════════════
            grand_total_works = 0
            grand_total_parts = 0

            for i, work in enumerate(works, 1):
                work_id, _, worker_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, _, _, _, order_number, _ = work

                work_amount = float(amount or 0)
                grand_total_works += work_amount

                if hasattr(work_date, 'strftime'):
                    work_date_str = work_date.strftime('%d.%m.%Y')
                else:
                    work_date_str = str(work_date) if work_date else "-"

                # Заголовок работы
                order_num_str = f"№{order_number}" if order_number else f"#{i}"
                work_header = f"РАБОТА {order_num_str}  |  Дата: {work_date_str}  |  Мастер: {worker_name or '-'}"

                # Информация об авто для этой работы
                work_car_info = f"{car_brand or ''} {car_model or ''} {car_number or ''}".strip()
                if mileage:
                    work_car_info += f"  |  Пробег: {mileage} км"

                # Заголовок работы (серый фон)
                header_data = [[Paragraph(f"<b>{work_header}</b>", style_normal)]]
                if work_car_info:
                    header_data.append([Paragraph(f"Авто: {work_car_info}", style_normal)])

                header_table = Table(header_data, colWidths=[content_width])
                header_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ]))
                elements.append(header_table)

                # Таблица работ
                works_table_data = [[
                    Paragraph("<b>Наименование</b>", style_bold),
                    Paragraph("<b>Сумма</b>", style_bold)
                ]]

                # Описание работ (разбиваем по запятой)
                if description:
                    work_items = [item.strip() for item in description.split(',') if item.strip()]
                    for item in work_items:
                        works_table_data.append([
                            Paragraph(f"• {item}", style_normal),
                            Paragraph("", style_normal)
                        ])
                else:
                    works_table_data.append([
                        Paragraph("Работы не указаны", style_normal),
                        Paragraph("", style_normal)
                    ])

                # Итого работы
                works_table_data.append([
                    Paragraph("<b>Итого работы:</b>", style_bold),
                    Paragraph(f"<b>{self.format_currency(work_amount)}</b>", style_bold)
                ])

                works_table = Table(works_table_data, colWidths=[content_width * 0.75, content_width * 0.25])
                works_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.grey),
                    ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.grey),
                ]))
                elements.append(works_table)

                # Запчасти
                parts = self.db.get_parts_by_work_id(work_id)
                parts_total = 0

                if parts:
                    parts_table_data = [[
                        Paragraph("<b>Запчасти</b>", style_bold),
                        Paragraph("<b>Цена</b>", style_bold)
                    ]]

                    for part_name, part_price in parts:
                        part_price = float(part_price)
                        parts_total += part_price
                        parts_table_data.append([
                            Paragraph(f"• {part_name}", style_normal),
                            Paragraph(self.format_currency(part_price), style_normal)
                        ])

                    parts_table_data.append([
                        Paragraph("<b>Итого запчасти:</b>", style_bold),
                        Paragraph(f"<b>{self.format_currency(parts_total)}</b>", style_bold)
                    ])

                    parts_table = Table(parts_table_data, colWidths=[content_width * 0.75, content_width * 0.25])
                    parts_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.grey),
                        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.grey),
                    ]))
                    elements.append(parts_table)

                grand_total_parts += parts_total
                elements.append(Spacer(1, 15))

            # ═══════════════════════════════════════════════════════
            # ИТОГО
            # ═══════════════════════════════════════════════════════
            grand_total = grand_total_works + grand_total_parts

            # Линия
            line_table2 = Table([['']], colWidths=[content_width])
            line_table2.setStyle(TableStyle([
                ('LINEABOVE', (0, 0), (-1, 0), 1.5, colors.black),
            ]))
            elements.append(line_table2)
            elements.append(Spacer(1, 10))

            # Таблица итогов
            totals_data = [
                [Paragraph("Работы:", style_normal), Paragraph(self.format_currency(grand_total_works), style_normal)],
                [Paragraph("Запчасти:", style_normal), Paragraph(self.format_currency(grand_total_parts), style_normal)],
                [Paragraph("<b>ИТОГО К ОПЛАТЕ:</b>", style_bold), Paragraph(f"<b>{self.format_currency(grand_total)}</b>", style_bold)],
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

    def show_qr_window(self, qr_image, order_text, car_number="", order_number=""):
        """Показать окно с QR-кодом"""
        qr_window = tk.Toplevel(self.root)
        qr_window.title("QR-код листа наряда")
        qr_window.geometry("600x700")

        # Заголовок
        title_label = ctk.CTkLabel(qr_window, text="Лист наряд сформирован!",
                                font=("Arial", 14, "bold"))
        title_label.pack(pady=10)

        # Инструкция
        info_label = ctk.CTkLabel(qr_window,
                               text="Отсканируйте QR-код для просмотра текста листа наряда",
                               justify=tk.CENTER)
        info_label.pack(pady=5)

        # QR-код
        qr_frame = ctk.CTkFrame(qr_window)
        qr_frame.pack(pady=10)

        # Конвертируем QR-код в формат для Tkinter
        qr_photo = ImageTk.PhotoImage(qr_image)
        qr_label = ctk.CTkLabel(qr_frame, image=qr_photo)
        qr_label.image = qr_photo  # Сохраняем ссылку
        qr_label.pack()

        # Предпросмотр текста
        preview_frame = ctk.CTkFrame(qr_window)
        preview_frame.pack(fill=tk.Y, expand=True, padx=10, pady=10)

        # Вычисляем максимальную ширину строки в тексте
        max_line_length = max(len(line) for line in order_text.split('\n'))
        # Добавляем небольшой запас (2 символа)
        text_width = max_line_length + 2

        text_widget = tk.Text(preview_frame, height=15, width=text_width, font=("Courier New", 9), wrap=tk.NONE)
        text_widget.pack(fill=tk.Y, expand=True)
        text_widget.insert(1.0, order_text)
        text_widget.config(state=tk.DISABLED)

        # Кнопки
        buttons_frame = ctk.CTkFrame(qr_window)
        buttons_frame.pack(pady=10)

        ctk.CTkButton(buttons_frame, text="Сохранить PDF",
                   command=lambda: self.save_work_order_to_pdf(qr_image, order_text, car_number, order_number)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(buttons_frame, text="Закрыть", command=qr_window.destroy).pack(side=tk.LEFT, padx=5)

    # --- Методы для вкладки Записи ---

    def setup_bookings_tab(self):
        """Настройка вкладки записей из Telegram"""
        # Верхняя панель с фильтрами
        filter_frame = ctk.CTkFrame(self.bookings_frame)
        filter_frame.pack(fill=tk.X, padx=10, pady=10)

        # Фильтр по статусу
        ctk.CTkLabel(filter_frame, text="Статус:").pack(side=tk.LEFT, padx=5)
        self.bookings_status_var = tk.StringVar(value="Все")
        status_combo = ctk.CTkComboBox(filter_frame, variable=self.bookings_status_var,
                                        values=["Все", "В ожидании", "В работе", "Выполненные", "Отменённые"],
                                        width=140)
        status_combo.pack(side=tk.LEFT, padx=5)

        # Кнопки
        ctk.CTkButton(filter_frame, text="Обновить", command=self.refresh_bookings,
                     width=100).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(filter_frame, text="Только сегодня", command=self.show_today_bookings,
                     width=120).pack(side=tk.LEFT, padx=5)

        # Поле поиска
        ctk.CTkLabel(filter_frame, text="  🔍").pack(side=tk.LEFT, padx=(20, 0))
        self.bookings_search_entry = ctk.CTkEntry(filter_frame,
                                                   placeholder_text="госномер или телефон",
                                                   placeholder_text_color="gray", width=180)
        self.bookings_search_entry.pack(side=tk.LEFT, padx=5)
        self.bookings_search_entry.bind("<Return>", lambda e: self.refresh_bookings())
        ctk.CTkButton(filter_frame, text="✕", command=self.clear_bookings_search,
                     width=30, fg_color="#c62828", hover_color="#b71c1c").pack(side=tk.LEFT, padx=2)

        # Таблица записей
        table_frame = ctk.CTkFrame(self.bookings_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("id", "order_number", "date", "time", "name", "phone", "username", "car", "status")
        self.bookings_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        # Настройка колонок
        self.bookings_tree.heading("id", text="ID")
        self.bookings_tree.heading("order_number", text="№ заказа")
        self.bookings_tree.heading("date", text="Дата")
        self.bookings_tree.heading("time", text="Время")
        self.bookings_tree.heading("name", text="Имя")
        self.bookings_tree.heading("phone", text="Телефон")
        self.bookings_tree.heading("username", text="Telegram")
        self.bookings_tree.heading("car", text="Автомобиль")
        self.bookings_tree.heading("status", text="Статус")

        self.bookings_tree.column("id", width=0, stretch=False, minwidth=0)
        self.bookings_tree.column("order_number", width=80)
        self.bookings_tree.column("date", width=100)
        self.bookings_tree.column("time", width=70)
        self.bookings_tree.column("name", width=150)
        self.bookings_tree.column("phone", width=120)
        self.bookings_tree.column("username", width=120)
        self.bookings_tree.column("car", width=180)
        self.bookings_tree.column("status", width=100)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.bookings_tree.yview)
        self.bookings_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.bookings_tree.pack(fill=tk.BOTH, expand=True)

        # Настройка цветов для статусов
        self.bookings_tree.tag_configure("waiting", background="#fff3e0", foreground="#e65100")      # Оранжевый - В ожидании
        self.bookings_tree.tag_configure("in_progress", background="#e3f2fd", foreground="#1565c0")  # Синий - В работе
        self.bookings_tree.tag_configure("completed", background="#e8f5e9", foreground="#2e7d32")    # Зелёный - Выполнена
        self.bookings_tree.tag_configure("cancelled", background="#ffebee", foreground="#c62828")   # Красный - Отменена

        # Контекстное меню для записей
        self.bookings_context_menu = tk.Menu(self.bookings_tree, tearoff=0)
        self.bookings_context_menu.add_command(label="Начать работу", command=self.start_work_from_booking)
        self.bookings_context_menu.add_command(label="Редактировать", command=self.edit_booking_in_add_work)
        self.bookings_context_menu.add_separator()
        self.bookings_context_menu.add_command(label="Информация", command=self.show_booking_info)
        self.bookings_context_menu.add_command(label="О клиенте", command=self.show_client_info)
        self.bookings_tree.bind("<Button-3>", self.show_bookings_context_menu)

        # Нижняя панель с кнопками действий (по центру)
        actions_frame = ctk.CTkFrame(self.bookings_frame)
        actions_frame.pack(pady=10)

        ctk.CTkButton(actions_frame, text="Записать клиента", command=self.show_add_booking_window,
                     fg_color="#1565c0", hover_color="#0d47a1", width=140).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(actions_frame, text="Выполнено", command=self.mark_booking_completed,
                     fg_color="#2e7d32", hover_color="#1b5e20", width=120).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(actions_frame, text="Отменено", command=self.mark_booking_cancelled,
                     fg_color="#f57c00", hover_color="#e65100", width=120).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(actions_frame, text="Удалить", command=self.delete_selected_booking,
                     fg_color="#c62828", hover_color="#b71c1c", width=120).pack(side=tk.LEFT, padx=5)

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
        status_map = {"Все": None, "В ожидании": "waiting", "В работе": "in_progress", "Выполненные": "completed", "Отменённые": "cancelled"}
        status = status_map.get(status_filter, None)

        # Получение поискового запроса
        search_query = self.bookings_search_entry.get().strip().lower() if hasattr(self, 'bookings_search_entry') else ""

        # Получение данных (от сегодня и далее)
        bookings = self.db.get_all_bookings(status=status)

        # Заполнение таблицы
        for booking in bookings:
            booking_id, user_id, username, full_name, phone, booking_date, booking_time, status, car_info, client_id, car_id, order_number = booking

            # Фильтрация по поисковому запросу (телефон или госномер)
            if search_query:
                phone_str = (phone or "").lower()
                car_str = (car_info or "").lower()
                # Убираем лишние символы из телефона для поиска
                phone_digits = ''.join(c for c in phone_str if c.isdigit())
                search_digits = ''.join(c for c in search_query if c.isdigit())

                # Проверяем совпадение
                match = False
                if search_digits and search_digits in phone_digits:
                    match = True
                elif search_query in phone_str or search_query in car_str:
                    match = True

                if not match:
                    continue

            # Форматирование даты
            if isinstance(booking_date, date):
                date_str = booking_date.strftime("%d.%m.%Y")
            else:
                date_str = str(booking_date)

            # Статус на русском
            status_ru = {"waiting": "В ожидании", "in_progress": "В работе", "completed": "Выполнена", "cancelled": "Отменена"}.get(status, status)

            # Вставка с тегом для цвета
            self.bookings_tree.insert("", tk.END, values=(
                booking_id, order_number or "-", date_str, booking_time, full_name or "-",
                phone or "-", f"@{username}" if username else "-",
                car_info or "-", status_ru
            ), tags=(status,))

    def show_today_bookings(self):
        """Показать записи на сегодня"""
        # Очистка таблицы
        for item in self.bookings_tree.get_children():
            self.bookings_tree.delete(item)

        bookings = self.db.get_today_bookings()

        for booking in bookings:
            booking_id, user_id, username, full_name, phone, booking_date, booking_time, status, car_info, client_id, car_id, order_number = booking

            if isinstance(booking_date, date):
                date_str = booking_date.strftime("%d.%m.%Y")
            else:
                date_str = str(booking_date)

            status_ru = {"waiting": "В ожидании", "in_progress": "В работе", "completed": "Выполнена", "cancelled": "Отменена"}.get(status, status)

            # Вставка с тегом для цвета
            self.bookings_tree.insert("", tk.END, values=(
                booking_id, order_number or "-", date_str, booking_time, full_name or "-",
                phone or "-", f"@{username}" if username else "-",
                car_info or "-", status_ru
            ), tags=(status,))

    def get_selected_booking_id(self):
        """Получить ID выбранной записи"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запись из списка")
            return None
        values = self.bookings_tree.item(selection[0], "values")
        return int(values[0])

    def mark_booking_completed(self):
        """Отметить запись как выполненную"""
        booking_id = self.get_selected_booking_id()
        if booking_id:
            # Получаем данные записи для уведомления
            booking = self.db.get_booking_by_id(booking_id)

            self.db.update_booking_status(booking_id, "completed")
            self.refresh_bookings()

            # Отправляем уведомление в Telegram
            if booking and booking.get("user_id"):
                # Получаем данные работы по этой записи
                work = self.db.get_work_by_booking_id(booking_id)

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
                    if car_info or car_number:
                        message += f"🚙 Авто: {car_info}"
                        if car_number:
                            message += f" ({car_number})"
                        message += "\n"

                    # Выполненные работы со стоимостью
                    if description:
                        message += f"\n📝 <b>Работы:</b>\n"
                        # Разбиваем по запятой
                        work_items = [item.strip() for item in description.split(',') if item.strip()]
                        for work_item in work_items:
                            message += f"  • {work_item}\n"
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

                if send_telegram_notification(booking["user_id"], message, with_menu=True):
                    messagebox.showinfo("Успех", "Запись отмечена как выполненная.\nКлиент уведомлён в Telegram.")
                else:
                    messagebox.showinfo("Успех", "Запись отмечена как выполненная.\n(Не удалось отправить уведомление в Telegram)")
            else:
                messagebox.showinfo("Успех", "Запись отмечена как выполненная")

    def mark_booking_cancelled(self):
        """Отметить запись как отменённую"""
        booking_id = self.get_selected_booking_id()
        if booking_id:
            self.db.update_booking_status(booking_id, "cancelled")
            self.refresh_bookings()
            messagebox.showinfo("Успех", "Запись отмечена как отменённая")

    def delete_selected_booking(self):
        """Удалить выбранную запись"""
        booking_id = self.get_selected_booking_id()
        if booking_id:
            if messagebox.askyesno("Подтверждение", "Удалить выбранную запись?"):
                self.db.delete_booking(booking_id)
                self.refresh_bookings()
                messagebox.showinfo("Успех", "Запись удалена")

    def show_add_booking_window(self):
        """Показать окно для записи клиента"""
        # Слоты времени: каждые 2 часа с 10:00 до 20:00
        TIME_SLOTS = ["10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]

        # Создаём затемняющий оверлей поверх главного окна
        self.root.update_idletasks()
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.geometry(f"{self.root.winfo_width()}x{self.root.winfo_height()}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        overlay.configure(bg="black")
        overlay.attributes("-alpha", 0.5)
        overlay.attributes("-topmost", True)
        overlay.update()

        add_window = ctk.CTkToplevel(self.root)
        add_window.title("Записать клиента")
        add_window.transient(self.root)
        add_window.attributes("-topmost", True)

        # Центрируем окно
        window_width = 450
        window_height = 620
        screen_width = add_window.winfo_screenwidth()
        screen_height = add_window.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        add_window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        add_window.update()
        add_window.grab_set()
        add_window.focus_force()

        def on_close():
            overlay.destroy()
            add_window.destroy()

        add_window.protocol("WM_DELETE_WINDOW", on_close)

        # Основной фрейм
        main_frame = ctk.CTkFrame(add_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Флаг: авто найдено по госномеру
        car_found_by_number = [False]
        found_car_id = [None]

        # === ГОСНОМЕР (первым) ===
        ctk.CTkLabel(main_frame, text="Госномер:", font=("Arial", 15)).pack(anchor="w", pady=(0, 5))
        car_number_entry = ctk.CTkEntry(main_frame, width=200, font=("Arial", 14), placeholder_text="А123БВ777")
        car_number_entry.pack(anchor="w", pady=(0, 5))
        car_status_label = ctk.CTkLabel(main_frame, text="", font=("Arial", 13))
        car_status_label.pack(anchor="w", pady=(0, 5))

        # === Фрейм для марки/модели (показывается динамически если авто не найдено) ===
        car_details_frame = ctk.CTkFrame(main_frame, fg_color="#e8f5e9", corner_radius=8, border_width=2, border_color="#4caf50")
        car_details_visible = [False]

        # Флаги видимости listbox
        brand_listbox_visible = [False]
        model_listbox_visible = [False]

        # Марка с автокомплитом
        brand_row = ctk.CTkFrame(car_details_frame, fg_color="transparent")
        brand_row.pack(fill=tk.X, pady=5, padx=10)
        ctk.CTkLabel(brand_row, text="Марка:", width=80, anchor="w", font=("Arial", 14)).pack(side=tk.LEFT)
        brand_entry = ctk.CTkEntry(brand_row, width=200, font=("Arial", 14))
        brand_entry.pack(side=tk.LEFT)
        brand_listbox = tk.Listbox(brand_row, height=5, width=25, font=("Arial", 12))

        def show_brand_list(brands_list):
            brand_listbox.delete(0, tk.END)
            for b in brands_list:
                brand_listbox.insert(tk.END, b)
            if not brand_listbox_visible[0]:
                brand_listbox.pack(side=tk.LEFT, padx=5)
                brand_listbox_visible[0] = True

        def hide_brand_list():
            if brand_listbox_visible[0]:
                brand_listbox.pack_forget()
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

        # Модель с автокомплитом
        model_row = ctk.CTkFrame(car_details_frame, fg_color="transparent")
        model_row.pack(fill=tk.X, pady=5, padx=10)
        ctk.CTkLabel(model_row, text="Модель:", width=80, anchor="w", font=("Arial", 14)).pack(side=tk.LEFT)
        model_entry = ctk.CTkEntry(model_row, width=200, font=("Arial", 14))
        model_entry.pack(side=tk.LEFT)
        model_listbox = tk.Listbox(model_row, height=5, width=25, font=("Arial", 12))

        def show_model_list(models_list):
            model_listbox.delete(0, tk.END)
            for m in models_list:
                model_listbox.insert(tk.END, m)
            if not model_listbox_visible[0]:
                model_listbox.pack(side=tk.LEFT, padx=5)
                model_listbox_visible[0] = True

        def hide_model_list():
            if model_listbox_visible[0]:
                model_listbox.pack_forget()
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

        model_entry.bind('<KeyRelease>', on_model_key)
        model_entry.bind('<FocusIn>', on_model_key)
        model_listbox.bind('<<ListboxSelect>>', on_model_select)

        # === ТЕЛЕФОН ===
        ctk.CTkLabel(main_frame, text="Телефон:", font=("Arial", 15)).pack(anchor="w", pady=(10, 5))

        def validate_phone(new_value):
            if len(new_value) < 2:
                return False
            if not new_value.startswith("+7"):
                return False
            if new_value == "+7":
                return True
            after_prefix = new_value[2:]
            if not after_prefix.isdigit():
                return False
            if len(after_prefix) > 10:
                return False
            return True

        vcmd = (add_window.register(validate_phone), '%P')
        phone_entry = ctk.CTkEntry(main_frame, width=220, font=("Arial", 14), validate="key", validatecommand=vcmd)
        phone_entry.pack(anchor="w", pady=(0, 10))
        phone_entry.insert(0, "+7")

        # === ИМЯ КЛИЕНТА ===
        ctk.CTkLabel(main_frame, text="Имя клиента:", font=("Arial", 15)).pack(anchor="w", pady=(0, 5))
        name_entry = ctk.CTkEntry(main_frame, width=220, font=("Arial", 14))
        name_entry.pack(anchor="w", pady=(0, 10))

        def check_car_number(*args):
            """Проверка госномера - ищем существующее авто и владельца"""
            car_num = car_number_entry.get().strip().upper()
            if len(car_num) >= 6:
                car_info = self.db.get_car_info_by_number(car_num)
                if car_info:
                    car_found_by_number[0] = True
                    found_car_id[0] = car_info.get('car_id')
                    owner_name = car_info.get('client_name', '')
                    owner_phone = car_info.get('client_phone', '')
                    car_brand = car_info.get('car_brand', '')
                    car_model = car_info.get('car_model', '')

                    # Показываем информацию
                    info_text = f"✓ Найдено: {car_brand} {car_model}"
                    if owner_name:
                        info_text += f" ({owner_name})"
                    car_status_label.configure(text=info_text, text_color="#2e7d32")

                    # Скрываем поля марки/модели
                    if car_details_visible[0]:
                        car_details_frame.pack_forget()
                        car_details_visible[0] = False
                        add_window.geometry(f"{window_width}x{window_height}")

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
                            # Временно отключаем валидацию для вставки
                            phone_entry.configure(validate="none")
                            phone_entry.delete(0, tk.END)
                            phone_entry.insert(0, f"+7{phone_digits[-10:]}")
                            phone_entry.configure(validate="key", validatecommand=vcmd)
                else:
                    # Авто не найдено - показываем поля марки/модели, сбрасываем данные
                    car_found_by_number[0] = False
                    found_car_id[0] = None
                    car_status_label.configure(text="Новое авто - введите марку и модель:", text_color="#f57c00")
                    if not car_details_visible[0]:
                        car_details_frame.pack(fill=tk.X, pady=(0, 10), after=car_status_label)
                        car_details_visible[0] = True
                        add_window.geometry(f"{window_width}x{window_height + 100}")
                    # Сбрасываем поля марки/модели
                    brand_entry.delete(0, tk.END)
                    model_entry.delete(0, tk.END)
            else:
                car_found_by_number[0] = False
                found_car_id[0] = None
                car_status_label.configure(text="")
                if car_details_visible[0]:
                    car_details_frame.pack_forget()
                    car_details_visible[0] = False
                    add_window.geometry(f"{window_width}x{window_height}")
                # Сбрасываем поля марки/модели
                brand_entry.delete(0, tk.END)
                model_entry.delete(0, tk.END)

        car_number_entry.bind("<KeyRelease>", check_car_number)
        car_number_entry.bind("<FocusOut>", check_car_number)

        # Дата
        ctk.CTkLabel(main_frame, text="Дата:", font=("Arial", 15)).pack(anchor="w", pady=(0, 5))
        date_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        date_frame.pack(anchor="w", pady=(0, 5))

        # Календарь для выбора даты
        date_entry = DateEntry(
            date_frame,
            width=18,
            background='#1f538d',
            foreground='white',
            borderwidth=2,
            date_pattern='dd.mm.yyyy',
            locale='ru_RU',
            mindate=datetime.now().date(),
            font=("Arial", 12)
        )
        date_entry.pack(side=tk.LEFT)

        # Время
        ctk.CTkLabel(main_frame, text="Время:", font=("Arial", 15)).pack(anchor="w", pady=(0, 5))
        time_combo = ctk.CTkComboBox(main_frame, values=TIME_SLOTS, width=150, font=("Arial", 14))
        time_combo.pack(anchor="w", pady=(0, 5))

        # Статус (показывает если нет свободных слотов)
        slot_status_label = ctk.CTkLabel(main_frame, text="", font=("Arial", 13))
        slot_status_label.pack(anchor="w", pady=(0, 5))

        def update_available_times(*args):
            """Обновить список доступных слотов времени"""
            try:
                booking_date = date_entry.get_date()

                # Показываем все слоты времени (не фильтруем занятые)
                time_combo.configure(values=TIME_SLOTS)
                time_combo.set(TIME_SLOTS[0])
                slot_status_label.configure(text="", text_color="#2e7d32")
            except:
                time_combo.configure(values=TIME_SLOTS)
                time_combo.set(TIME_SLOTS[0])

        date_entry.bind("<<DateEntrySelected>>", update_available_times)
        update_available_times()

        def save_booking():
            """Сохранить запись"""
            name = name_entry.get().strip()
            phone_raw = phone_entry.get().strip()
            date_str = date_entry.get_date().strftime("%d.%m.%Y")
            time_str = time_combo.get()

            # Получаем информацию об авто
            number = car_number_entry.get().strip().upper()
            brand = brand_entry.get().strip()
            model = model_entry.get().strip()
            existing_car_id = found_car_id[0]  # ID найденного авто или None

            if not name:
                messagebox.showwarning("Внимание", "Введите имя клиента!", parent=add_window)
                return

            # Валидация госномера - обязательно
            if not number:
                messagebox.showwarning("Внимание", "Введите госномер автомобиля!", parent=add_window)
                return

            # Если авто не найдено - нужны марка и модель
            if not car_found_by_number[0]:
                if not brand:
                    messagebox.showwarning("Внимание", "Введите марку автомобиля!", parent=add_window)
                    return
                if not model:
                    messagebox.showwarning("Внимание", "Введите модель автомобиля!", parent=add_window)
                    return

            # Валидация телефона - должен быть +7 и 10 цифр после
            phone_digits = ''.join(c for c in phone_raw if c.isdigit())
            if len(phone_digits) != 11 or not phone_digits.startswith('7'):
                messagebox.showwarning("Внимание", "Введите номер телефона после +7\nПример: +79091234567", parent=add_window)
                return

            # Телефон уже в нужном формате
            phone = phone_raw

            # Парсим дату
            try:
                from datetime import datetime
                booking_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            except:
                messagebox.showerror("Ошибка", "Неверный формат даты!", parent=add_window)
                return

            # Проверяем доступность
            if not self.db.is_time_slot_available(booking_date, time_str):
                # Получаем список машин на это время
                existing_bookings = self.db.get_bookings_at_time(booking_date, time_str)
                num_cars = len(existing_bookings)

                # Формируем сообщение
                message = f"На это время записано машин: {num_cars}\n\nГосномера:\n"
                for booking in existing_bookings:
                    car_info = f"{booking['brand']} {booking['model']}" if booking['brand'] else ""
                    message += f"• {booking['car_number']}"
                    if car_info:
                        message += f" ({car_info})"
                    message += f" - {booking['client_name']}\n"

                message += "\nЗаписать клиента на это время?"

                # Спрашиваем пользователя
                result = messagebox.askyesno("Время занято", message, parent=add_window)
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

            # Создаём/находим клиента
            client_id = self.db.get_or_create_client(
                telegram_user_id=tg_user_id if tg_user_id else None,
                full_name=name,
                phone=phone,
                car_number=number
            )

            # Создаём/находим машину
            car_id = existing_car_id  # Используем ID существующей машины если выбрана
            if not car_id and client_id and brand and number:
                # Создаём новую машину только если не выбрана существующая
                car_id = self.db.get_or_create_car(client_id, brand, model, number)

            # Сохраняем запись
            booking_id = self.db.add_booking(
                booking_date=booking_date,
                booking_time=time_str,
                client_id=client_id,
                car_id=car_id
            )
            if booking_id:
                messagebox.showinfo("Успех", f"Клиент записан на {date_str} в {time_str}", parent=add_window)
                on_close()
                self.refresh_bookings()
            else:
                messagebox.showerror("Ошибка", "Не удалось создать запись", parent=add_window)

        # Кнопки (в отдельном фрейме внизу окна, чтобы всегда были под всеми полями)
        btn_frame = ctk.CTkFrame(add_window, fg_color="transparent")
        btn_frame.pack(side=tk.BOTTOM, pady=15)

        ctk.CTkButton(btn_frame, text="Записать", command=save_booking,
                     fg_color="#2e7d32", hover_color="#1b5e20", width=130, height=36, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(btn_frame, text="Отмена", command=on_close,
                     fg_color="#757575", hover_color="#616161", width=130, height=36, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)

    def show_bookings_context_menu(self, event):
        """Показать контекстное меню для записи"""
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
            self.bookings_context_menu.post(event.x_root, event.y_root)

    def start_work_from_booking(self):
        """Начать работу по выбранной записи - переход на вкладку добавления работы"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запись!")
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
            messagebox.showerror("Ошибка", "Запись не найдена!")
            return

        # Проверяем статус
        if booking.get("status") != "waiting":
            messagebox.showwarning("Внимание", "Начать работу можно только для записей в статусе 'В ожидании'!")
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

        full_name = booking.get("full_name") or "Без имени"
        phone = booking.get("phone") or "Без телефона"
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
            messagebox.showwarning("Внимание", "Выберите запись!")
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
            messagebox.showerror("Ошибка", "Запись не найдена!")
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
        self.client_phone_entry.delete(0, tk.END)
        self.client_phone_entry.insert(0, phone)

        # Загружаем машины клиента
        self.load_client_cars(phone, full_name, car_id)

        # Если есть связанная работа - загружаем её данные
        work = self.db.get_work_by_booking_id(int(booking_id))
        if work:
            # work: (id, worker_id, full_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, booking_id, client_name, client_phone, order_number, car_id)
            work_id = work[0]
            worker_id = work[1]
            description = work[3] or ""
            amount = work[4] or 0
            work_date = work[5]
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
            if description:
                lines = [l.strip() for l in description.split("\n") if l.strip()]
                if len(lines) > 1:
                    # Несколько строк — каждая строка отдельная работа, цена распределяется поровну
                    price_each = float(amount or 0) / len(lines)
                    for line in lines:
                        self.works_list.append((line, price_each))
                        self.works_tree.insert("", tk.END, values=(line, self.format_currency(price_each)))
                else:
                    # Одна строка — одна работа с полной ценой
                    self.works_list.append((description, float(amount or 0)))
                    self.works_tree.insert("", tk.END, values=(description, self.format_currency(float(amount or 0))))

            # Выбираем мастера
            if worker_id:
                for name, wid in self.workers_data.items():
                    if wid == worker_id:
                        self.worker_combo.set(name)
                        break

            # Заполняем дату
            if work_date:
                if hasattr(work_date, 'strftime'):
                    self.work_date_entry.set_date(work_date)

            # Загружаем запчасти
            self.parts_list = []
            # Очищаем таблицу запчастей
            for item in self.parts_tree.get_children():
                self.parts_tree.delete(item)

            parts = self.db.get_parts_by_work_id(work_id)
            if parts:
                for part_name, part_price in parts:
                    self.parts_list.append((part_name, float(part_price)))
                    self.parts_tree.insert("", tk.END, values=(part_name, self.format_currency(float(part_price))))

            self.update_total_cost()

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

    def show_booking_info(self):
        """Показать окно с информацией о записи и работе"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запись!")
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
            messagebox.showerror("Ошибка", "Запись не найдена!")
            return

        # Ищем ВСЕ связанные работы
        works = self.db.get_all_works_by_booking_id(int(booking_id))

        # Создаём окно информации
        info_window = ctk.CTkToplevel(self.root)
        info_window.title("Информация о записи")
        info_window.geometry("600x700")
        info_window.transient(self.root)
        info_window.grab_set()

        # Цвета для статусов
        status_colors = {
            "waiting": ("#f59e0b", "#78350f"),      # Оранжевый
            "in_progress": ("#3b82f6", "#1e3a8a"),  # Синий
            "completed": ("#22c55e", "#14532d"),    # Зелёный
            "cancelled": ("#ef4444", "#7f1d1d")     # Красный
        }
        status_map = {
            "waiting": "⏳ В ожидании",
            "in_progress": "🔧 В работе",
            "completed": "✅ Выполнена",
            "cancelled": "❌ Отменена"
        }

        booking_status = booking.get("status", "waiting")
        status_bg, status_fg = status_colors.get(booking_status, ("#6b7280", "#1f2937"))
        status_text = status_map.get(booking_status, booking_status)

        # Основной фрейм с прокруткой
        main_frame = ctk.CTkScrollableFrame(info_window, fg_color="transparent")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ═══════════════════════════════════════════════════════
        # КАРТОЧКА: Информация о записи
        # ═══════════════════════════════════════════════════════
        booking_card = ctk.CTkFrame(main_frame, corner_radius=12)
        booking_card.pack(fill="x", pady=(0, 15))

        # Заголовок карточки с иконкой
        header_frame = ctk.CTkFrame(booking_card, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header_frame,
            text="📋  Информация о записи",
            font=("Arial", 18, "bold")
        ).pack(side="left")

        # Бейдж статуса
        status_badge = ctk.CTkLabel(
            header_frame,
            text=f"  {status_text}  ",
            font=("Arial", 13, "bold"),
            fg_color=status_bg,
            text_color="white",
            corner_radius=8
        )
        status_badge.pack(side="right")

        # Разделитель
        ctk.CTkFrame(booking_card, height=1, fg_color="gray70").pack(fill="x", padx=15)

        # Контент карточки
        content_frame = ctk.CTkFrame(booking_card, fg_color="transparent")
        content_frame.pack(fill="x", padx=15, pady=15)

        # Форматируем дату
        booking_date = booking.get("booking_date")
        if hasattr(booking_date, 'strftime'):
            date_str = booking_date.strftime('%d.%m.%Y')
        else:
            date_str = str(booking_date)

        # Telegram info
        tg_username = booking.get('username') or '-'
        tg_user_id = booking.get('user_id') or 0
        car_info = booking.get('car_info') or '-'

        # Двухколоночная раскладка
        info_data = [
            ("📅 Дата:", date_str),
            ("🕐 Время:", booking.get('booking_time', '-')),
            ("👤 Клиент:", booking.get('full_name') or 'Не указано'),
            ("📞 Телефон:", booking.get('phone') or 'Не указан'),
            ("💬 Telegram:", f"@{tg_username}" if tg_username != '-' else '-'),
            ("🚗 Автомобиль:", car_info),
        ]

        for i, (label, value) in enumerate(info_data):
            row = ctk.CTkFrame(content_frame, fg_color="transparent")
            row.pack(fill="x", pady=4)

            ctk.CTkLabel(
                row,
                text=label,
                font=("Arial", 14),
                text_color=("gray30", "gray70"),
                width=140,
                anchor="w"
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=value,
                font=("Arial", 14),
                anchor="w"
            ).pack(side="left", fill="x", expand=True)

        # ═══════════════════════════════════════════════════════
        # КАРТОЧКА: Работы
        # ═══════════════════════════════════════════════════════

        # Заголовок в зависимости от статуса
        if booking_status == "completed":
            works_icon = "✅"
            works_title = "Выполненные работы"
        elif booking_status == "in_progress":
            works_icon = "🔧"
            works_title = "Работы в процессе"
        else:
            works_icon = "📝"
            works_title = "Работы"

        works_card = ctk.CTkFrame(main_frame, corner_radius=12)
        works_card.pack(fill="x", pady=(0, 15))

        # Заголовок
        works_header = ctk.CTkFrame(works_card, fg_color="transparent")
        works_header.pack(fill="x", padx=15, pady=(15, 10))

        works_count = f" ({len(works)} шт.)" if works else ""
        ctk.CTkLabel(
            works_header,
            text=f"{works_icon}  {works_title}{works_count}",
            font=("Arial", 18, "bold")
        ).pack(side="left")

        # Разделитель
        ctk.CTkFrame(works_card, height=1, fg_color="gray70").pack(fill="x", padx=15)

        # Контент работ
        works_content = ctk.CTkFrame(works_card, fg_color="transparent")
        works_content.pack(fill="x", padx=15, pady=15)

        if not works:
            ctk.CTkLabel(
                works_content,
                text="Работы ещё не добавлены",
                text_color=("gray40", "gray60"),
                font=("Arial", 14)
            ).pack(anchor="w")
        else:
            grand_total = 0

            for i, work in enumerate(works, 1):
                work_id, _, worker_name, description, amount, work_date, car_brand, car_model, car_number, mileage, vin, _, client_name, client_phone, order_number, car_id = work

                # Карточка отдельной работы
                work_frame = ctk.CTkFrame(works_content, corner_radius=8, fg_color=("gray90", "gray20"))
                work_frame.pack(fill="x", pady=(0, 10) if i < len(works) else 0)

                work_inner = ctk.CTkFrame(work_frame, fg_color="transparent")
                work_inner.pack(fill="x", padx=12, pady=12)

                # Заголовок работы
                work_header_row = ctk.CTkFrame(work_inner, fg_color="transparent")
                work_header_row.pack(fill="x", pady=(0, 8))

                ctk.CTkLabel(
                    work_header_row,
                    text=f"🔹 Работа #{i}",
                    font=("Arial", 15, "bold")
                ).pack(side="left")

                if order_number:
                    ctk.CTkLabel(
                        work_header_row,
                        text=f"Наряд №{order_number}",
                        font=("Arial", 13),
                        text_color=("gray40", "gray60")
                    ).pack(side="right")

                # Форматируем дату работы
                if hasattr(work_date, 'strftime'):
                    work_date_str = work_date.strftime('%d.%m.%Y')
                else:
                    work_date_str = str(work_date) if work_date else "-"

                # Информация о работе (компактно)
                work_info_row = ctk.CTkFrame(work_inner, fg_color="transparent")
                work_info_row.pack(fill="x", pady=(0, 8))

                info_items = [
                    f"📅 {work_date_str}",
                    f"👨‍🔧 {worker_name or '-'}",
                    f"🚗 {car_brand or '-'} {car_model or ''} ({car_number or '-'})",
                ]
                if mileage:
                    info_items.append(f"📊 {mileage} км")

                ctk.CTkLabel(
                    work_info_row,
                    text="  •  ".join(info_items),
                    font=("Arial", 13),
                    text_color=("gray30", "gray70")
                ).pack(anchor="w")

                # Считаем суммы
                work_amount = float(amount or 0)
                work_parts = self.db.get_parts_by_work_id(work_id)
                parts_total = sum(float(p[1]) for p in work_parts) if work_parts else 0
                work_total = work_amount + parts_total
                grand_total += work_total

                # Описание работ
                if description:
                    desc_frame = ctk.CTkFrame(work_inner, fg_color="transparent")
                    desc_frame.pack(fill="x", pady=(0, 5))

                    ctk.CTkLabel(
                        desc_frame,
                        text=f"Услуги ({self.format_currency(work_amount)}):",
                        font=("Arial", 14, "bold")
                    ).pack(anchor="w")

                    work_items = [item.strip() for item in description.split(',') if item.strip()]
                    for work_item in work_items:
                        ctk.CTkLabel(
                            desc_frame,
                            text=f"   • {work_item}",
                            font=("Arial", 13),
                            anchor="w"
                        ).pack(anchor="w")

                # Запчасти
                if work_parts:
                    parts_frame = ctk.CTkFrame(work_inner, fg_color="transparent")
                    parts_frame.pack(fill="x", pady=(5, 0))

                    ctk.CTkLabel(
                        parts_frame,
                        text=f"Запчасти ({self.format_currency(parts_total)}):",
                        font=("Arial", 14, "bold")
                    ).pack(anchor="w")

                    for part_name, part_price in work_parts:
                        ctk.CTkLabel(
                            parts_frame,
                            text=f"   • {part_name} — {self.format_currency(float(part_price))}",
                            font=("Arial", 13),
                            anchor="w"
                        ).pack(anchor="w")

                # Итог по работе
                work_total_row = ctk.CTkFrame(work_inner, fg_color="transparent")
                work_total_row.pack(fill="x", pady=(8, 0))

                ctk.CTkLabel(
                    work_total_row,
                    text=f"Итого: {self.format_currency(work_total)}",
                    font=("Arial", 14, "bold"),
                    text_color="#3b82f6"
                ).pack(side="right")

            # ═══════════════════════════════════════════════════════
            # КАРТОЧКА: Общий итог
            # ═══════════════════════════════════════════════════════
            total_card = ctk.CTkFrame(main_frame, corner_radius=12, fg_color=("#d1fae5", "#064e3b"))
            total_card.pack(fill="x", pady=(0, 10))

            total_inner = ctk.CTkFrame(total_card, fg_color="transparent")
            total_inner.pack(fill="x", padx=20, pady=15)

            ctk.CTkLabel(
                total_inner,
                text="💰  ОБЩИЙ ИТОГ",
                font=("Arial", 16, "bold"),
                text_color=("#065f46", "#a7f3d0")
            ).pack(side="left")

            ctk.CTkLabel(
                total_inner,
                text=self.format_currency(grand_total),
                font=("Arial", 24, "bold"),
                text_color=("#065f46", "#a7f3d0")
            ).pack(side="right")

        # ═══════════════════════════════════════════════════════
        # Кнопки внизу
        # ═══════════════════════════════════════════════════════
        buttons_frame = ctk.CTkFrame(info_window, fg_color="transparent")
        buttons_frame.pack(pady=15)

        if works:
            ctk.CTkButton(
                buttons_frame,
                text="📄  Сохранить в PDF",
                command=lambda: self.save_booking_to_pdf(booking, works),
                width=160,
                height=40,
                font=("Arial", 13)
            ).pack(side=tk.LEFT, padx=5)

        ctk.CTkButton(
            buttons_frame,
            text="Закрыть",
            command=info_window.destroy,
            width=120,
            height=40,
            font=("Arial", 13),
            fg_color="gray50",
            hover_color="gray40"
        ).pack(side=tk.LEFT, padx=5)

    def show_client_info(self):
        """Показать окно с информацией о клиенте: машины и история"""
        selection = self.bookings_tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запись!")
            return

        values = self.bookings_tree.item(selection[0], "values")
        if not values:
            return

        # values: (id, order_number, date, time, name, phone, username, car_info, status)
        booking_id = values[0] if len(values) > 0 else None
        client_name = values[4] if len(values) > 4 else None
        client_phone = values[5] if len(values) > 5 else None
        client_telegram = values[6] if len(values) > 6 else None

        # Получаем user_id (telegram_user_id) из записи
        telegram_user_id = None
        if booking_id:
            booking = self.db.get_booking_by_id(int(booking_id))
            if booking:
                telegram_user_id = booking.get("user_id")

        if not telegram_user_id and not client_phone and not client_name:
            messagebox.showwarning("Внимание", "Нет данных о клиенте!")
            return

        # Получаем машины и историю клиента (приоритет по telegram_user_id)
        cars = []
        history = []

        if telegram_user_id:
            cars = self.db.get_client_cars_by_telegram_user_id(telegram_user_id)
            history = self.db.get_client_history(telegram_user_id=telegram_user_id)

        # Если по telegram_user_id ничего не нашли — ищем по телефону/имени
        if not cars and client_phone:
            cars = self.db.get_client_cars_by_phone(client_phone)
        if not cars and client_name:
            cars = self.db.get_client_cars_by_name(client_name)

        if not history:
            history = self.db.get_client_history(phone=client_phone, name=client_name)

        # Создаём окно
        client_window = ctk.CTkToplevel(self.root)
        client_window.title(f"Клиент: {client_name or client_phone}")
        client_window.geometry("700x700")
        client_window.transient(self.root)
        client_window.grab_set()

        # Основной фрейм с прокруткой
        main_frame = ctk.CTkScrollableFrame(client_window, fg_color="transparent")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ═══════════════════════════════════════════════════════
        # КАРТОЧКА: Информация о клиенте
        # ═══════════════════════════════════════════════════════
        client_card = ctk.CTkFrame(main_frame, corner_radius=12)
        client_card.pack(fill="x", pady=(0, 15))

        # Заголовок
        header_frame = ctk.CTkFrame(client_card, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header_frame,
            text="👤  Информация о клиенте",
            font=("Arial", 18, "bold")
        ).pack(side="left")

        # Разделитель
        ctk.CTkFrame(client_card, height=1, fg_color="gray70").pack(fill="x", padx=15)

        # Контент
        content_frame = ctk.CTkFrame(client_card, fg_color="transparent")
        content_frame.pack(fill="x", padx=15, pady=15)

        client_data = [
            ("👤 Имя:", client_name or "Не указано"),
            ("📞 Телефон:", client_phone or "Не указан"),
            ("💬 Telegram:", client_telegram if client_telegram and client_telegram != '-' else "Не указан"),
        ]

        for label, value in client_data:
            row = ctk.CTkFrame(content_frame, fg_color="transparent")
            row.pack(fill="x", pady=4)

            ctk.CTkLabel(
                row,
                text=label,
                font=("Arial", 14),
                text_color=("gray30", "gray70"),
                width=120,
                anchor="w"
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=value,
                font=("Arial", 14),
                anchor="w"
            ).pack(side="left", fill="x", expand=True)

        # ═══════════════════════════════════════════════════════
        # КАРТОЧКА: Автомобили
        # ═══════════════════════════════════════════════════════
        cars_card = ctk.CTkFrame(main_frame, corner_radius=12)
        cars_card.pack(fill="x", pady=(0, 15))

        # Заголовок
        cars_header = ctk.CTkFrame(cars_card, fg_color="transparent")
        cars_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            cars_header,
            text=f"🚗  Автомобили ({len(cars)})",
            font=("Arial", 18, "bold")
        ).pack(side="left")

        # Разделитель
        ctk.CTkFrame(cars_card, height=1, fg_color="gray70").pack(fill="x", padx=15)

        # Контент
        cars_content = ctk.CTkFrame(cars_card, fg_color="transparent")
        cars_content.pack(fill="x", padx=15, pady=15)

        if not cars:
            ctk.CTkLabel(
                cars_content,
                text="Нет данных об автомобилях",
                text_color=("gray40", "gray60"),
                font=("Arial", 14)
            ).pack(anchor="w")
        else:
            for i, (car_brand, car_model, car_number) in enumerate(cars):
                car_frame = ctk.CTkFrame(cars_content, corner_radius=8, fg_color=("gray90", "gray20"))
                car_frame.pack(fill="x", pady=(0, 8) if i < len(cars) - 1 else 0)

                car_inner = ctk.CTkFrame(car_frame, fg_color="transparent")
                car_inner.pack(fill="x", padx=12, pady=10)

                car_text = f"{car_brand or ''} {car_model or ''}".strip()
                ctk.CTkLabel(
                    car_inner,
                    text=f"🚗  {car_text}" if car_text else "🚗  Не указано",
                    font=("Arial", 14, "bold"),
                    anchor="w"
                ).pack(side="left")

                if car_number:
                    ctk.CTkLabel(
                        car_inner,
                        text=car_number,
                        font=("Arial", 13),
                        text_color=("gray30", "gray70"),
                        anchor="e"
                    ).pack(side="right")

        # ═══════════════════════════════════════════════════════
        # КАРТОЧКА: История работ
        # ═══════════════════════════════════════════════════════
        history_card = ctk.CTkFrame(main_frame, corner_radius=12)
        history_card.pack(fill="x", pady=(0, 15))

        # Заголовок
        history_header = ctk.CTkFrame(history_card, fg_color="transparent")
        history_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            history_header,
            text=f"📜  История работ ({len(history)})",
            font=("Arial", 18, "bold")
        ).pack(side="left")

        # Разделитель
        ctk.CTkFrame(history_card, height=1, fg_color="gray70").pack(fill="x", padx=15)

        # Контент
        history_content = ctk.CTkFrame(history_card, fg_color="transparent")
        history_content.pack(fill="x", padx=15, pady=15)

        if not history:
            ctk.CTkLabel(
                history_content,
                text="История пуста",
                text_color=("gray40", "gray60"),
                font=("Arial", 14)
            ).pack(anchor="w")
        else:
            total_spent = 0

            for i, work in enumerate(history):
                # work: (id, work_date, order_number, worker, car_brand, car_model, car_number, mileage, description, amount, client_name, client_phone)
                work_id, work_date, order_number, worker, car_brand, car_model, car_number, mileage, description, amount, work_client_name, work_client_phone = work

                # Получаем запчасти
                work_parts = self.db.get_parts_by_work_id(work_id)
                parts_total = sum(float(p[1]) for p in work_parts) if work_parts else 0
                work_total = float(amount or 0) + parts_total
                total_spent += work_total

                # Форматируем дату
                if hasattr(work_date, 'strftime'):
                    date_str = work_date.strftime('%d.%m.%Y')
                else:
                    date_str = str(work_date) if work_date else "-"

                # Карточка работы
                work_frame = ctk.CTkFrame(history_content, corner_radius=8, fg_color=("gray90", "gray20"))
                work_frame.pack(fill="x", pady=(0, 10) if i < len(history) - 1 else 0)

                work_inner = ctk.CTkFrame(work_frame, fg_color="transparent")
                work_inner.pack(fill="x", padx=12, pady=12)

                # Заголовок работы
                work_header_row = ctk.CTkFrame(work_inner, fg_color="transparent")
                work_header_row.pack(fill="x", pady=(0, 8))

                ctk.CTkLabel(
                    work_header_row,
                    text=f"📅 {date_str}",
                    font=("Arial", 15, "bold")
                ).pack(side="left")

                if order_number:
                    ctk.CTkLabel(
                        work_header_row,
                        text=f"Наряд №{order_number}",
                        font=("Arial", 13),
                        text_color=("gray40", "gray60")
                    ).pack(side="right")

                # Информация о работе
                work_info_row = ctk.CTkFrame(work_inner, fg_color="transparent")
                work_info_row.pack(fill="x", pady=(0, 8))

                info_items = []
                if worker:
                    info_items.append(f"👨‍🔧 {worker}")
                car_info = f"{car_brand or ''} {car_model or ''} {car_number or ''}".strip()
                if car_info:
                    info_items.append(f"🚗 {car_info}")
                if mileage:
                    info_items.append(f"📊 {mileage} км")

                if info_items:
                    ctk.CTkLabel(
                        work_info_row,
                        text="  •  ".join(info_items),
                        font=("Arial", 13),
                        text_color=("gray30", "gray70")
                    ).pack(anchor="w")

                # Описание работ
                if description:
                    work_amount = float(amount or 0)
                    desc_frame = ctk.CTkFrame(work_inner, fg_color="transparent")
                    desc_frame.pack(fill="x", pady=(0, 5))

                    ctk.CTkLabel(
                        desc_frame,
                        text=f"Услуги ({self.format_currency(work_amount)}):",
                        font=("Arial", 14, "bold")
                    ).pack(anchor="w")

                    work_items = [item.strip() for item in description.split(',') if item.strip()]
                    for work_item in work_items:
                        ctk.CTkLabel(
                            desc_frame,
                            text=f"   • {work_item}",
                            font=("Arial", 13),
                            anchor="w",
                            wraplength=580
                        ).pack(anchor="w")

                # Запчасти
                if work_parts:
                    parts_frame = ctk.CTkFrame(work_inner, fg_color="transparent")
                    parts_frame.pack(fill="x", pady=(5, 0))

                    ctk.CTkLabel(
                        parts_frame,
                        text=f"Запчасти ({self.format_currency(parts_total)}):",
                        font=("Arial", 14, "bold")
                    ).pack(anchor="w")

                    for part_name, part_price in work_parts:
                        ctk.CTkLabel(
                            parts_frame,
                            text=f"   • {part_name} — {self.format_currency(float(part_price))}",
                            font=("Arial", 13),
                            anchor="w"
                        ).pack(anchor="w")

                # Итого по работе
                work_total_row = ctk.CTkFrame(work_inner, fg_color="transparent")
                work_total_row.pack(fill="x", pady=(8, 0))

                ctk.CTkLabel(
                    work_total_row,
                    text=f"Итого: {self.format_currency(work_total)}",
                    font=("Arial", 14, "bold"),
                    text_color="#3b82f6"
                ).pack(side="right")

            # ═══════════════════════════════════════════════════════
            # КАРТОЧКА: Общий итог
            # ═══════════════════════════════════════════════════════
            total_card = ctk.CTkFrame(main_frame, corner_radius=12, fg_color=("#dbeafe", "#1e3a8a"))
            total_card.pack(fill="x", pady=(0, 10))

            total_inner = ctk.CTkFrame(total_card, fg_color="transparent")
            total_inner.pack(fill="x", padx=20, pady=15)

            ctk.CTkLabel(
                total_inner,
                text="💳  ВСЕГО ОПЛАЧЕНО",
                font=("Arial", 16, "bold"),
                text_color=("#1e40af", "#93c5fd")
            ).pack(side="left")

            ctk.CTkLabel(
                total_inner,
                text=self.format_currency(total_spent),
                font=("Arial", 24, "bold"),
                text_color=("#1e40af", "#93c5fd")
            ).pack(side="right")

        # ═══════════════════════════════════════════════════════
        # Кнопка закрыть
        # ═══════════════════════════════════════════════════════
        buttons_frame = ctk.CTkFrame(client_window, fg_color="transparent")
        buttons_frame.pack(pady=15)

        ctk.CTkButton(
            buttons_frame,
            text="Закрыть",
            command=client_window.destroy,
            width=120,
            height=40,
            font=("Arial", 13),
            fg_color="gray50",
            hover_color="gray40"
        ).pack()


def main():
    root = ctk.CTk()  # Используем CustomTkinter вместо Tkinter
    app = AutoServiceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()