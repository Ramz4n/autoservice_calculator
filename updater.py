# -*- coding: utf-8 -*-
"""
Модуль авто-обновления приложения.

Формат JSON на сервере (добавить в тот же jsonbin):
{
  "licenses": { ... },
  "update": {
    "latest_version": "1.0.1",
    "min_version":    "1.0.0",
    "download_url":   "https://ваш-хостинг/app.exe",
    "changelog":      "— Исправлены ошибки\n— Новые функции"
  }
}

Логика:
  - версия клиента < min_version  → принудительное обновление (нельзя отказаться)
  - версия клиента < latest_version → предлагает обновление (Да / Нет)
  - иначе → ничего не происходит

ВАЖНО: меняй APP_VERSION при каждой новой сборке PyInstaller.
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

import requests

# ─────────────────────────────────────────
# Текущая версия — меняй при каждом релизе
APP_VERSION = "1.0.0"
# ─────────────────────────────────────────


def _parse_version(v: str) -> tuple:
    """'1.2.3' → (1, 2, 3)"""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


def check_for_update() -> dict | None:
    """
    Проверяет наличие обновления через jsonbin.
    Возвращает dict с ключами:
        latest_version, min_version, download_url, changelog, forced
    или None если обновлений нет / сервер недоступен.
    """
    try:
        from license import LICENSE_URL, API_KEY
        r = requests.get(LICENSE_URL, headers={"X-Access-Key": API_KEY}, timeout=5)
        if r.status_code != 200:
            return None
        body = r.json()
        data = body.get("record", body)
        update = data.get("update")
        if not update:
            return None

        latest  = update.get("latest_version", "")
        minimum = update.get("min_version", "0.0.0")
        url     = update.get("download_url", "")

        if not latest or not url:
            return None

        current = _parse_version(APP_VERSION)

        # Версия ниже минимально допустимой — принудительное обновление
        if current < _parse_version(minimum):
            return {
                "latest_version": latest,
                "min_version":    minimum,
                "download_url":   url,
                "changelog":      update.get("changelog", ""),
                "forced":         True,
            }

        # Есть новая версия — обычное предложение
        if current < _parse_version(latest):
            return {
                "latest_version": latest,
                "min_version":    minimum,
                "download_url":   url,
                "changelog":      update.get("changelog", ""),
                "forced":         False,
            }

    except Exception:
        pass
    return None


def show_update_dialog(update_info: dict, parent=None) -> bool:
    """
    Показывает диалог обновления.
    Принудительное: только кнопка «Обновить».
    Обычное: кнопки «Да» / «Нет».
    Возвращает True если нужно качать.
    """
    import customtkinter as ctk

    forced  = update_info.get("forced", False)
    latest  = update_info["latest_version"]
    changes = update_info.get("changelog", "")

    win = ctk.CTkToplevel(parent)
    win.resizable(False, False)
    win.grab_set()
    win.focus()

    if forced:
        win.title("Требуется обновление")
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # нельзя закрыть
    else:
        win.title("Доступно обновление")

    win.geometry("420x{}+{}+{}".format(
        280 if changes else 200,
        win.winfo_screenwidth()  // 2 - 210,
        win.winfo_screenheight() // 2 - 140,
    ))

    f = ctk.CTkFrame(win, fg_color="transparent")
    f.pack(padx=30, pady=20, fill="both", expand=True)

    if forced:
        ctk.CTkLabel(f, text="Требуется обязательное обновление",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#c62828").pack(anchor="w", pady=(0, 6))
    else:
        ctk.CTkLabel(f, text="Доступна новая версия",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(0, 6))

    ctk.CTkLabel(f, text=f"Версия {latest}  (у вас {APP_VERSION})",
                 font=ctk.CTkFont(size=13), text_color="gray").pack(anchor="w", pady=(0, 10))

    if changes:
        ctk.CTkLabel(f, text="Что нового:", font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(f, text=changes, font=ctk.CTkFont(size=12),
                     anchor="w", justify="left", wraplength=360).pack(fill="x", pady=(2, 14))

    result = [False]

    btn_frame = ctk.CTkFrame(f, fg_color="transparent")
    btn_frame.pack(fill="x", pady=(6, 0))

    def on_yes():
        result[0] = True
        win.destroy()

    def on_no():
        win.destroy()

    ctk.CTkButton(btn_frame, text="Обновить", height=38, width=140,
                  command=on_yes).pack(side="left")

    if not forced:
        ctk.CTkButton(btn_frame, text="Не сейчас", height=38, width=120,
                      fg_color="gray", hover_color="gray40",
                      command=on_no).pack(side="left", padx=(10, 0))

    win.wait_window()
    return result[0]


def _current_exe() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(__file__)


def apply_update(download_url: str, parent_widget=None) -> None:
    """
    Скачивает новый .exe и запускает bat-установщик.
    После запуска bat — завершает текущий процесс.
    """
    import customtkinter as ctk

    win = ctk.CTkToplevel(parent_widget)
    win.title("Загрузка обновления")
    win.resizable(False, False)
    win.protocol("WM_DELETE_WINDOW", lambda: None)  # нельзя закрыть
    win.geometry("380x130+{}+{}".format(
        win.winfo_screenwidth()  // 2 - 190,
        win.winfo_screenheight() // 2 - 65,
    ))
    win.grab_set()

    ctk.CTkLabel(win, text="Загрузка обновления...",
                 font=ctk.CTkFont(size=13)).pack(pady=(20, 8))

    progress = ctk.CTkProgressBar(win, width=320)
    progress.set(0)
    progress.pack(pady=(0, 8))

    size_label = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=11), text_color="gray")
    size_label.pack()

    error_holder = [None]

    def do_download():
        try:
            exe_path = _current_exe()
            exe_dir  = os.path.dirname(exe_path)
            new_exe  = os.path.join(exe_dir, "_update_new.exe")
            bat_path = os.path.join(exe_dir, "_updater.bat")

            r = requests.get(download_url, stream=True, timeout=60)
            r.raise_for_status()

            total      = int(r.headers.get("Content-Length", 0))
            downloaded = 0

            with open(new_exe, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            win.after(0, lambda p=downloaded/total: progress.set(p))
                        mb = downloaded / 1024 / 1024
                        win.after(0, lambda m=mb: size_label.configure(
                            text=f"{m:.1f} МБ" + (f" / {total/1024/1024:.1f} МБ" if total else "")
                        ))

            bat_content = (
                "@echo off\n"
                "timeout /t 2 /nobreak >nul\n"
                f'copy /y "{new_exe}" "{exe_path}"\n'
                f'start "" "{exe_path}"\n'
                f'del "{new_exe}"\n'
                '(goto) 2>nul & del "%~f0"\n'
            )
            with open(bat_path, "w", encoding="cp866") as f:
                f.write(bat_content)

            win.after(0, _launch_and_exit, bat_path)

        except Exception as e:
            error_holder[0] = str(e)
            win.after(0, win.destroy)

    def _launch_and_exit(bat_path):
        win.destroy()
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        sys.exit(0)

    threading.Thread(target=do_download, daemon=True).start()
    win.wait_window()

    if error_holder[0]:
        messagebox.showerror(
            "Ошибка обновления",
            f"Не удалось скачать обновление:\n{error_holder[0]}\n\nПопробуйте позже.",
            parent=parent_widget,
        )
