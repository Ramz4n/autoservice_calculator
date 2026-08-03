# -*- coding: utf-8 -*-
"""
Простой загрузчик переводов интерфейса (JSON-словари в config/locales/)...
"""


import json
import os

SUPPORTED_LANGUAGES = {
    "ru": "Русский",
    "en": "English",
    "ka": "ქართული",
    "hy": "Հայերեն",
}


class I18n:
    """Хранит переводы текущего языка и отдаёт их по ключу через t()/tr()."""

    def __init__(self, locales_dir, lang="ru"):
        self.locales_dir = locales_dir
        self.lang = lang
        self.strings = {}
        self.load(lang)

    def load(self, lang):
        path = os.path.join(self.locales_dir, f"{lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.strings = json.load(f)
            self.lang = lang
        except (FileNotFoundError, json.JSONDecodeError):
            self.strings = {}
            self.lang = lang

    def t(self, key, **kwargs):
        """Вернуть перевод по ключу. Если перевода нет — вернуть сам ключ (заметно в UI)."""
        text = self.strings.get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return text
