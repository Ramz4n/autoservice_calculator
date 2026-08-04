# -*- coding: utf-8 -*-
"""Отправка SMS-уведомлений клиентам через SMSC.ru (https://smsc.ru/api/http/send/)"""

import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', '.env'))

SMSC_API_KEY = os.getenv('SMSC_API_KEY')
SMSC_LOGIN = os.getenv('SMSC_LOGIN')
SMSC_PASSWORD = os.getenv('SMSC_PASSWORD')
SMSC_SENDER = os.getenv('SMSC_SENDER', '')  # имя отправителя, если подключено у SMSC

SMSC_URL = "https://smsc.ru/sys/send.php"


def send_sms_notification(phone, message):
    """Отправить SMS клиенту. Возвращает True при успехе, False при ошибке."""
    if not phone:
        return False

    if not (SMSC_API_KEY or (SMSC_LOGIN and SMSC_PASSWORD)):
        print("SMS не отправлено: не заданы SMSC_API_KEY или SMSC_LOGIN/SMSC_PASSWORD в config/.env")
        return False

    params = {
        "phones": phone,
        "mes": message,
        "charset": "utf-8",
        "fmt": 3,  # ответ в формате JSON
    }
    if SMSC_API_KEY:
        params["apikey"] = SMSC_API_KEY
    else:
        params["login"] = SMSC_LOGIN
        params["psw"] = SMSC_PASSWORD
    if SMSC_SENDER:
        params["sender"] = SMSC_SENDER

    try:
        response = requests.post(SMSC_URL, data=params, timeout=10)
        result = response.json()
        if "error" in result:
            print(f"Ошибка отправки SMS ({phone}): {result['error']} (код {result.get('error_code')})")
            return False
        return True
    except Exception as e:
        print(f"Ошибка отправки SMS ({phone}): {e}")
        return False
