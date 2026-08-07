# -*- coding: utf-8 -*-
"""
Окно авторизации и управление пользователями.

Использование в main():
    from login_window import LoginWindow
    win = LoginWindow(db)
    win.mainloop()
    if win.logged_user is None:
        sys.exit(0)
    # далее открывать основное окно
"""

import sys
import os
import json
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from i18n import I18n, SUPPORTED_LANGUAGES


def _get_base_path():
    """Получить базовый путь приложения (работает и для PyInstaller)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


SETTINGS_FILE = os.path.join(_get_base_path(), 'config', 'settings.json')
LOCALES_DIR = os.path.join(_get_base_path(), 'config', 'locales')


def _load_settings():
    """Загрузить настройки приложения из JSON файла"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_settings(settings):
    """Сохранить настройки приложения в JSON файл"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")


def _get_i18n():
    """Создать I18n на текущем сохранённом языке интерфейса."""
    lang = _load_settings().get('language', 'ru')
    return I18n(LOCALES_DIR, lang)


class LoginWindow(ctk.CTk):
    """Окно входа в систему."""

    DEFAULT_ADMIN = "admin"
    DEFAULT_PASS  = "admin"

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.logged_user = None  # dict: {id, username, full_name, role}

        self.i18n = _get_i18n()
        self.tr = self.i18n.t

        # Создаём дефолтного админа если таблица пуста
        self._first_run = self.db.ensure_default_admin()

        self._setup_window()
        self._build_ui()

        if self._first_run:
            self.after(400, self._show_first_run_notice)

    # ──────── Настройка окна ────────

    def _setup_window(self):
        self.title(self.tr("login.window_title"))
        self.resizable(False, False)
        w, h = 420, 460
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────── UI ────────

    def _build_ui(self):
        # Выбор языка интерфейса (правый верхний угол)
        current_lang = _load_settings().get('language', 'ru')
        self.lang_var = tk.StringVar(value=current_lang)
        self.lang_menu = ctk.CTkOptionMenu(
            self, values=list(SUPPORTED_LANGUAGES.keys()),
            variable=self.lang_var, width=70, height=28,
            command=self._on_language_change
        )
        self.lang_menu.place(relx=1.0, x=-14, y=14, anchor="ne")

        # Версия приложения (левый нижний угол)
        try:
            from updater import APP_VERSION as _app_version
        except Exception:
            _app_version = "?"
        ctk.CTkLabel(
            self, text=f"v{_app_version}",
            font=ctk.CTkFont(size=10), text_color="gray"
        ).place(x=10, rely=1.0, y=-8, anchor="sw")

        # Заголовок
        ctk.CTkLabel(
            self, text=self.tr("login.brand"),
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(44, 4))
        ctk.CTkLabel(
            self, text=self.tr("login.subtitle"),
            font=ctk.CTkFont(size=14), text_color="gray"
        ).pack(pady=(0, 28))

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(padx=44, fill="x")

        # Логин (подставляем логин, использованный при последнем входе)
        ctk.CTkLabel(frame, text=self.tr("login.username_label"), anchor="w").pack(fill="x", pady=(0, 2))
        last_username = _load_settings().get('last_username', '')
        self.username_var = tk.StringVar(value=last_username)
        self.username_entry = ctk.CTkEntry(
            frame, textvariable=self.username_var,
            placeholder_text=self.tr("login.username_placeholder"), height=40
        )
        self.username_entry.pack(fill="x", pady=(0, 14))

        # Пароль
        ctk.CTkLabel(frame, text=self.tr("login.password_label"), anchor="w").pack(fill="x", pady=(0, 2))
        self.password_var = tk.StringVar()
        self.password_entry = ctk.CTkEntry(
            frame, textvariable=self.password_var,
            show="•", placeholder_text=self.tr("login.password_placeholder"), height=40
        )
        self.password_entry.pack(fill="x", pady=(0, 6))

        # Показать пароль
        self.show_pass_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            frame, text=self.tr("login.show_password"),
            variable=self.show_pass_var,
            command=self._toggle_password, height=22
        ).pack(anchor="w", pady=(0, 22))

        # Кнопка входа
        ctk.CTkButton(
            frame, text=self.tr("login.submit"), height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._do_login
        ).pack(fill="x")

        # Ошибка
        self.error_label = ctk.CTkLabel(
            self, text="", text_color="red",
            font=ctk.CTkFont(size=12)
        )
        self.error_label.pack(pady=(12, 0))

        # Enter → войти
        self.bind("<Return>", lambda _e: self._do_login())
        # Если логин уже подставлен из прошлого раза — сразу фокус на пароль
        if last_username:
            self.password_entry.focus()
        else:
            self.username_entry.focus()

    # ──────── Логика входа ────────

    def _on_language_change(self, value):
        """Сохранить выбранный язык интерфейса (применится после входа)"""
        settings = _load_settings()
        settings['language'] = value
        _save_settings(settings)

    def _toggle_password(self):
        self.password_entry.configure(
            show="" if self.show_pass_var.get() else "•"
        )

    def _do_login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get()

        if not username or not password:
            self.error_label.configure(text=self.tr("login.error_empty"))
            return

        user = self.db.verify_user(username, password)
        if user is None:
            self.error_label.configure(text=self.tr("login.error_invalid"))
            self.password_var.set("")
            self.password_entry.focus()
            return

        settings = _load_settings()
        settings['last_username'] = username
        _save_settings(settings)

        self.logged_user = user
        self.quit()   # выходим из mainloop; destroy() вызывается в main()

    def _show_first_run_notice(self):
        messagebox.showinfo(
            self.tr("login.first_run_title"),
            self.tr("login.first_run_body",
                    username=self.DEFAULT_ADMIN, password=self.DEFAULT_PASS),
            parent=self
        )

    def _on_close(self):
        self.destroy()
        sys.exit(0)


# ══════════════════════════════════════════════════════
# Диалог управления пользователями (для вызова из app)
# ══════════════════════════════════════════════════════

class UserManagementDialog(ctk.CTkToplevel):
    """
    Диалог управления пользователями. Открывается из основного окна.

        dlg = UserManagementDialog(parent_widget, db, current_user)
    """

    def __init__(self, parent, db, current_user: dict):
        super().__init__(parent)
        self.db = db
        self.current_user = current_user

        self.i18n = _get_i18n()
        self.tr = self.i18n.t

        self.title(self.tr("users.window_title"))
        self.resizable(False, False)
        w, h = 620, 520
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.grab_set()
        self.focus()

        self._build_ui()
        self._load_users()

    # ──────── UI ────────

    def _build_ui(self):
        # Заголовок + кнопка добавить
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            top, text=self.tr("users.title"),
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            top, text=self.tr("users.add_button"), width=110,
            command=self._open_add_dialog
        ).pack(side="right")

        # Таблица
        cols = ("username", "full_name", "role", "is_active")
        self.tree = tk.ttk.Treeview(
            self, columns=cols, show="headings", height=12
        )
        self.tree.heading("username",  text=self.tr("users.col_username"))
        self.tree.heading("full_name", text=self.tr("users.col_fullname"))
        self.tree.heading("role",      text=self.tr("users.col_role"))
        self.tree.heading("is_active", text=self.tr("users.col_status"))
        self.tree.column("username",  width=140)
        self.tree.column("full_name", width=180)
        self.tree.column("role",      width=90, anchor="center")
        self.tree.column("is_active", width=90, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Кнопки действий
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=20, pady=(0, 16), fill="x")

        ctk.CTkButton(
            btn_frame, text=self.tr("users.change_password"), width=160,
            command=self._change_password
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text=self.tr("users.toggle_active"), width=150,
            fg_color="orange", hover_color="#e65100",
            command=self._toggle_active
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text=self.tr("users.delete"), width=110,
            fg_color="#c62828", hover_color="#b71c1c",
            command=self._delete_user
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame, text=self.tr("common.close"), width=110,
            fg_color="gray", hover_color="gray40",
            command=self.destroy
        ).pack(side="right")

    # ──────── Данные ────────

    def _load_users(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for u in self.db.get_all_users():
            role_label = self.tr("users.role_admin") if u["role"] == "admin" else self.tr("users.role_user")
            status = self.tr("users.status_active") if u["is_active"] else self.tr("users.status_blocked")
            self.tree.insert("", "end", iid=str(u["id"]),
                             values=(u["username"], u["full_name"] or "", role_label, status))

    def _selected_user_id(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    # ──────── Действия ────────

    def _open_add_dialog(self):
        AddUserDialog(self, self.db, on_saved=self._load_users)

    def _change_password(self):
        uid = self._selected_user_id()
        if uid is None:
            messagebox.showwarning(self.tr("users.select_title"), self.tr("users.select_body"), parent=self)
            return
        ChangePasswordDialog(self, self.db, uid, on_saved=self._load_users)

    def _toggle_active(self):
        uid = self._selected_user_id()
        if uid is None:
            messagebox.showwarning(self.tr("users.select_title"), self.tr("users.select_body"), parent=self)
            return
        if uid == self.current_user["id"]:
            messagebox.showwarning(self.tr("common.error"), self.tr("users.cant_block_self"), parent=self)
            return
        users = {u["id"]: u for u in self.db.get_all_users()}
        u = users.get(uid)
        if u:
            self.db.set_user_active(uid, not u["is_active"])
            self._load_users()

    def _delete_user(self):
        uid = self._selected_user_id()
        if uid is None:
            messagebox.showwarning(self.tr("users.select_title"), self.tr("users.select_body"), parent=self)
            return
        if uid == self.current_user["id"]:
            messagebox.showwarning(self.tr("common.error"), self.tr("users.cant_delete_self"), parent=self)
            return
        if messagebox.askyesno(self.tr("users.delete_confirm_title"), self.tr("users.delete_confirm_body"), parent=self):
            self.db.delete_user(uid)
            self._load_users()


# ──────── Вспомогательные диалоги ────────

class AddUserDialog(ctk.CTkToplevel):
    def __init__(self, parent, db, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.on_saved = on_saved
        self.i18n = _get_i18n()
        self.tr = self.i18n.t
        self.title(self.tr("users.add_dialog_title"))
        self.resizable(False, False)
        self.geometry("380x460+{}+{}".format(
            self.winfo_screenwidth() // 2 - 190,
            self.winfo_screenheight() // 2 - 230
        ))
        self.grab_set()
        self._build()

    def _build(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(padx=30, pady=20, fill="x")

        fields = [
            (self.tr("users.field_username"), "username"),
            (self.tr("users.field_password"), "password"),
            (self.tr("users.field_fullname"), "full_name"),
        ]
        self._vars = {}
        for label, key in fields:
            ctk.CTkLabel(f, text=label, anchor="w").pack(fill="x", pady=(0, 2))
            var = tk.StringVar()
            entry = ctk.CTkEntry(f, textvariable=var,
                                 show="•" if key == "password" else "", height=36)
            entry.pack(fill="x", pady=(0, 10))
            self._vars[key] = var

        ctk.CTkLabel(f, text=self.tr("users.field_role"), anchor="w").pack(fill="x", pady=(0, 2))
        self._role_var = tk.StringVar(value="user")
        role_frame = ctk.CTkFrame(f, fg_color="transparent")
        role_frame.pack(fill="x", pady=(0, 16))
        ctk.CTkRadioButton(role_frame, text=self.tr("users.role_user"),
                           variable=self._role_var, value="user").pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(role_frame, text=self.tr("users.role_admin"),
                           variable=self._role_var, value="admin").pack(side="left")

        self.err = ctk.CTkLabel(f, text="", text_color="red", font=ctk.CTkFont(size=12))
        self.err.pack()

        ctk.CTkButton(f, text=self.tr("common.save"), height=42, command=self._save).pack(fill="x", pady=(10, 0))

    def _save(self):
        username  = self._vars["username"].get().strip()
        password  = self._vars["password"].get()
        full_name = self._vars["full_name"].get().strip()
        role      = self._role_var.get()

        if not username or not password:
            self.err.configure(text=self.tr("users.error_required"))
            return

        ok = self.db.create_user(username, password, full_name, role)
        if not ok:
            self.err.configure(text=self.tr("users.error_exists"))
            return

        if self.on_saved:
            self.on_saved()
        self.destroy()


class ChangePasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, db, user_id: int, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.user_id = user_id
        self.on_saved = on_saved
        self.i18n = _get_i18n()
        self.tr = self.i18n.t
        self.title(self.tr("users.change_password_title"))
        self.resizable(False, False)
        self.geometry("340x260+{}+{}".format(
            self.winfo_screenwidth() // 2 - 170,
            self.winfo_screenheight() // 2 - 130
        ))
        self.grab_set()
        self._build()

    def _build(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(padx=30, pady=20, fill="both", expand=True)

        ctk.CTkLabel(f, text=self.tr("users.field_new_password"), anchor="w").pack(fill="x", pady=(0, 2))
        self.pwd1 = tk.StringVar()
        ctk.CTkEntry(f, textvariable=self.pwd1, show="•", height=36).pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(f, text=self.tr("users.field_repeat_password"), anchor="w").pack(fill="x", pady=(0, 2))
        self.pwd2 = tk.StringVar()
        ctk.CTkEntry(f, textvariable=self.pwd2, show="•", height=36).pack(fill="x", pady=(0, 14))

        self.err = ctk.CTkLabel(f, text="", text_color="red", font=ctk.CTkFont(size=12))
        self.err.pack()

        ctk.CTkButton(f, text=self.tr("common.save"), height=38, command=self._save).pack(fill="x", pady=(6, 0))

    def _save(self):
        p1 = self.pwd1.get()
        p2 = self.pwd2.get()
        if not p1:
            self.err.configure(text=self.tr("users.error_enter_password"))
            return
        if p1 != p2:
            self.err.configure(text=self.tr("users.error_mismatch"))
            return
        self.db.change_password(self.user_id, p1)
        messagebox.showinfo(self.tr("users.done_title"), self.tr("users.password_changed"), parent=self)
        if self.on_saved:
            self.on_saved()
        self.destroy()
