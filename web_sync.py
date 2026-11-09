# -*- coding: utf-8 -*-
"""
Синхронизация с сайтом онлайн-записи (Cloudflare Worker, папка autoservice_site).

Сайт работает круглосуточно, даже когда этот компьютер выключен. Программа раз в минуту:
  1. отправляет на сайт настройки слотов и предстоящие записи (только когда они изменились) -
     по ним сайт считает свободное время, а владелец видит расписание в панели /admin на телефоне;
     и список марок и моделей авто, когда он изменился, - клиент на сайте выбирает машину только из него;
  2. забирает с сайта новые онлайн-записи и записи, добавленные в панели, и сохраняет их в MariaDB;
  3. выполняет действия из панели (отмена записи);
  4. подтверждает сайту, что всё сохранено и выполнено, — сайт это у себя удаляет.

База MariaDB при этом наружу не открывается: связь идёт только отсюда на сайт по HTTPS.
Адрес сайта и секретный ключ — в config/.env: WEB_SYNC_URL и WEB_SYNC_KEY.
Если их нет — синхронизация выключена.
"""

import hashlib
import json
import os
import re
import time

import requests

from db_config import get_base_path

SETTINGS_FILE = os.path.join(get_base_path(), 'config', 'settings.json')
ACTIVE_STATUSES = ('waiting', 'in_progress')
TIMEOUT = 20  # секунд на запрос к сайту


def _url():
    return os.getenv('WEB_SYNC_URL', '').strip().rstrip('/')


def _key():
    return os.getenv('WEB_SYNC_KEY', '').strip()


def enabled():
    """Синхронизация настроена (есть адрес сайта и ключ)"""
    return bool(_url() and _key())


def _settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    return {
        "start": int(s.get("working_hours_start", 10)),
        "end": int(s.get("working_hours_end", 20)),
        "slot": int(s.get("slot_duration_minutes", 120)),
        "capacity": int(s.get("max_cars_per_slot", 1)),
        "perPhone": int(s.get("max_bookings_per_user", 2)),
    }


def _hhmm(value):
    """'9:00' / '09:00' / '09:00:00' -> '09:00'"""
    m = re.match(r'^\s*(\d{1,2}):(\d{2})', str(value or ''))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _appts(db):
    """Предстоящие активные записи - для расписания в панели и подсчёта свободного времени на сайте"""
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.booking_date, b.booking_time, b.status, c.full_name, c.phone,
                   car.car_number, car.car_brand, car.car_model, b.notes, b.web_id
            FROM bookings b
            LEFT JOIN clients c ON c.id = b.client_id
            LEFT JOIN client_cars car ON car.id = b.car_id
            WHERE b.booking_date >= CURDATE() AND b.status IN ('waiting', 'in_progress')
            ORDER BY b.booking_date, b.booking_time, b.id
            LIMIT 3000
        """)
        out = []
        for (bid, d, t, status, name, phone, plate, brand, model, notes, web_id) in cursor.fetchall():
            t = _hhmm(t)
            if t:
                out.append({"id": bid, "date": d.isoformat(), "time": t, "status": status,
                            "name": name or "", "phone": phone or "", "plate": plate or "",
                            "car": f"{brand or ''} {model or ''}".strip(), "notes": notes or "",
                            "web": bool(web_id), "web_id": web_id})
        return out
    finally:
        conn.close()


def _brands(db):
    """Марки и модели авто из программы: {"Toyota": ["Camry", ...], ...}"""
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.brand_name, m.model_name
            FROM car_brands b
            LEFT JOIN car_models m ON m.brand_id = b.id
            ORDER BY b.brand_name, m.model_name
        """)
        out = {}
        for brand, model in cursor.fetchall():
            brand = (brand or '').strip()
            if not brand:
                continue
            models = out.setdefault(brand, [])
            if model and model.strip():
                models.append(model.strip())
        return out
    finally:
        conn.close()


# Расписание отправляем только когда оно изменилось (и для надёжности раз в 30 минут) -
# каждая отправка - это запись в базу сайта, а у бесплатного Cloudflare дневной лимит
_sent = {"hash": None, "at": 0.0}
RESEND_EVERY = 30 * 60
# список марок большой, поэтому шлём его, только когда он отличается от того, что на сайте:
# сайт в каждом ответе сообщает, какой список у него сохранён (brands_hash)
_site_brands = {"hash": None}


def _post(db, ack, ack_commands):
    appts = _appts(db)
    digest = hashlib.sha256(json.dumps([_settings(), appts], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    send = digest != _sent["hash"] or time.time() - _sent["at"] > RESEND_EVERY
    payload = {"settings": _settings(), "ack": ack, "ack_commands": ack_commands}
    if send:
        payload["appts"] = appts
    brands = _brands(db)
    brands_hash = hashlib.sha256(json.dumps(brands, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if brands and _site_brands["hash"] is not None and _site_brands["hash"] != brands_hash:
        payload["brands"], payload["brands_hash"] = brands, brands_hash
    r = requests.post(
        f"{_url()}/api/sync",
        json=payload,
        headers={"Authorization": f"Bearer {_key()}"},
        timeout=TIMEOUT,
    )
    if r.status_code == 401:
        raise RuntimeError("Сайт не принял ключ WEB_SYNC_KEY (config/.env)")
    r.raise_for_status()
    if send:
        _sent.update(hash=digest, at=time.time())
    data = r.json()
    _site_brands["hash"] = data.get("brands_hash")  # нет у старой версии сайта - тогда список не шлём
    return data.get("requests", []), data.get("commands", [])


def _apply_command(db, cmd):
    """Действие из панели на телефоне. Возвращает True, если что-то изменилось."""
    if cmd.get("type") != "cancel":
        return False
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = %s AND status IN ('waiting', 'in_progress')",
                       (int(cmd["local_id"]),))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# латинские буквы, которые выглядят как буквы госномера: A123BC77 и А123ВС77 - один и тот же номер
_PLATE_LATIN = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")


def _plate_key(plate):
    """Госномер для сравнения: без пробелов и дефисов, заглавными, латиница -> кириллица"""
    return re.sub(r'[\s\-]', '', str(plate or '')).upper().translate(_PLATE_LATIN)


def _plate_save(plate):
    """Госномер для базы: заглавными, без пробелов. Российский номер, набранный латиницей (A123BC77),
    переводим в кириллицу, а номера других стран (35OL123, 1234AB-7) оставляем как написаны."""
    plate = re.sub(r'\s', '', str(plate or '')).upper()
    ru = plate.translate(_PLATE_LATIN)
    return ru if re.fullmatch(r'[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}', ru) else plate


def _phone_key(phone):
    return re.sub(r'\D', '', str(phone or ''))[-10:]


def _save_request(db, req):
    """Сохранить онлайн-запись в MariaDB. Возвращает словарь новой записи или None, если она уже была сохранена.

    Клиента ищем сначала по госномеру (машина обычно та же, а телефон и написание имени могут отличаться),
    потом по телефону. Данные в базе с сайта не перезаписываем: имя и телефон клиента остаются как у вас,
    а если на сайте указано другое - это пишется в примечании к записи."""
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, booking_date, booking_time FROM bookings WHERE web_id = %s", (req["id"],))
        row = cursor.fetchone()
        if row:
            same = row[1].isoformat() == req["date"] and _hhmm(row[2]) == req["time"]
            if same:
                return None  # уже сохранена в прошлый раз, сайт просто ещё не получил подтверждение
            # номер занят записью из прежней базы сайта (если её пересоздавали) - эта заявка новая,
            # а у старой записи номер убираем, чтобы не было совпадения
            cursor.execute("UPDATE bookings SET web_id = NULL WHERE id = %s", (row[0],))

        phone, name = req["phone"], req["name"]
        plate = _plate_key(req.get("plate"))  # только для поиска машины
        # запись с сайта или добавленная владельцем в панели на телефоне
        notes = [f"📱 С телефона: {req['service']}" if req.get("source") == "admin" else f"🌐 Сайт: {req['service']}"]

        # 1. машина по госномеру (сравниваем в Python - номера в базе бывают записаны по-разному)
        cursor.execute("SELECT id, client_id, car_number FROM client_cars")
        car = next((r for r in cursor.fetchall() if _plate_key(r[2]) == plate), None)
        car_id, client_id = (car[0], car[1]) if car else (None, None)

        # 2. клиент: владелец машины, иначе по телефону, иначе новый
        if not client_id:
            cursor.execute("SELECT id FROM clients WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s LIMIT 1",
                           (_phone_key(phone),))
            row = cursor.fetchone()
            client_id = row[0] if row else None
        if client_id:
            cursor.execute("SELECT full_name, phone FROM clients WHERE id = %s", (client_id,))
            db_name, db_phone = cursor.fetchone() or ("", "")
            if _phone_key(db_phone) != _phone_key(phone):
                notes.append(f"📞 На сайте указан другой телефон: {phone}")
            if (db_name or "").strip().lower() != name.strip().lower():
                notes.append(f"👤 На сайте указано имя: {name}")
        else:
            cursor.execute("INSERT INTO clients (full_name, phone) VALUES (%s, %s)", (name, phone))
            client_id = cursor.lastrowid
            db_name = name

        # 3. машина: найденная (если была без владельца - теперь его), иначе новая
        if car_id:
            if car[1] is None:
                cursor.execute("UPDATE client_cars SET client_id = %s WHERE id = %s", (client_id, car_id))
        else:
            cursor.execute("""
                INSERT INTO client_cars (client_id, car_brand, car_model, car_number) VALUES (%s, %s, %s, %s)
            """, (client_id, req.get("brand", ""), req.get("model", ""), _plate_save(req.get("plate"))))
            car_id = cursor.lastrowid
        if req.get("comment"):
            notes.append(req["comment"])

        cursor.execute("""
            INSERT INTO bookings (client_id, car_id, booking_date, booking_time, status, notes, web_id)
            VALUES (%s, %s, %s, %s, 'waiting', %s, %s)
        """, (client_id, car_id, req["date"], req["time"], "\n".join(notes), req["id"]))
        conn.commit()
        return {"date": req["date"], "time": req["time"], "name": db_name or name, "phone": phone,
                "service": req["service"], "car": f"{req.get('brand', '')} {req.get('model', '')} {_plate_save(req.get('plate'))}".strip()}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sync_once(db):
    """Один обмен с сайтом. Возвращает {"new": новые записи с сайта, "cancelled": сколько записей отменено с телефона}."""
    new, cancelled, ack, ack_commands = [], 0, [], []
    for _ in range(5):  # за раз до 5 пачек по 100 записей
        requests_, commands = _post(db, ack, ack_commands)
        ack, ack_commands = [], []
        if not requests_ and not commands:
            break
        for req in requests_:
            saved = _save_request(db, req)
            if saved:
                new.append(saved)
            ack.append(req["id"])
        for cmd in commands:
            cancelled += _apply_command(db, cmd)
            ack_commands.append(cmd["id"])
    if ack or ack_commands:  # последняя пачка: подтверждаем, что сохранили и выполнили
        _post(db, ack, ack_commands)
    return {"new": new, "cancelled": cancelled}
