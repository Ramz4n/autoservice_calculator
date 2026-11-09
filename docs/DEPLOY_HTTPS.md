# Переход на HTTPS (nginx) — что нужно сделать

## 1. Flutter — изменить baseUrl

Файл: `app_mobile/lib/services/api_service.dart`, строка ~14

Сейчас:
```dart
static const String baseUrl = 'http://192.168.31.154:8000';
```

Заменить на:
```dart
static const String baseUrl = 'https://твой-домен.ru';
```

---

## 2. Flutter — убрать разрешение HTTP

Файл: `app_mobile/android/app/src/main/AndroidManifest.xml`

Убрать атрибут `android:usesCleartextTraffic="true"` из тега `<application>`.

Он нужен только для HTTP. При HTTPS Android разрешает трафик по умолчанию.

---

## 3. Nginx — конфиг reverse proxy

Установить certbot + nginx на сервере, затем создать конфиг:

```nginx
server {
    listen 80;
    server_name твой-домен.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name твой-домен.ru;

    ssl_certificate     /etc/letsencrypt/live/твой-домен.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/твой-домен.ru/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

---

## 4. Backend — запуск на сервере

На сервере uvicorn запускать только на localhost (nginx сам проксирует):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Или через systemd/supervisor для автозапуска.

---

## 5. Backend — .env на сервере

Поменять `DB_HOST` если БД на том же сервере:
```
DB_HOST=localhost
```

---

## 6. CORS в backend (если нужно ограничить)

Файл: `backend/app/main.py`

Сейчас стоит `allow_origins=["*"]` — для продакшена лучше указать конкретный домен:
```python
allow_origins=["https://твой-домен.ru"],
```

---

---

## 7. Безопасность — отключить Swagger в продакшене

Файл: `backend/app/main.py`

Сейчас `/docs` и `/redoc` открыты для всех — посторонний видит всю структуру API.

Заменить строку создания приложения:
```python
# Было:
app = FastAPI(title="AutoService API", version="1.0.0", ...)

# Стало:
app = FastAPI(title="AutoService API", version="1.0.0", docs_url=None, redoc_url=None)
```

---

## 8. Безопасность — rate limiting на /auth/login

Без ограничений можно брутфорсить пароли неограниченно.

Установить:
```bash
pip install slowapi
```

Добавить в `backend/requirements.txt`:
```
slowapi==0.1.9
```

Добавить в `backend/app/main.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Добавить в `backend/app/routers/auth.py` на эндпоинт логина:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

limiter = Limiter(key_func=get_remote_address)

@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # не более 10 попыток в минуту с одного IP
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    ...
```

---

---

## 9. Безопасность — инвалидация токена при смене пароля/email

Сейчас старый JWT продолжает работать даже после смены пароля.
Решение: добавить поле `token_version INT DEFAULT 0` в таблицу `clients_login`
и при смене пароля/email инкрементировать его.
В JWT включать это значение и проверять при каждом запросе.

Файлы для изменения:
- `backend/app/models/client.py` — добавить поле `token_version`
- `backend/app/services/auth.py` — включать `token_version` в JWT
- `backend/app/dependencies.py` — проверять `token_version` из JWT vs БД
- `backend/app/routers/settings.py` — инкрементировать при смене пароля/email

---

---

## 10. ЮКасса — изменить return_url и включить вебхук

### 10.1 Return URL

Файл: `backend/app/config.py`

Сейчас:
```
YOOKASSA_RETURN_URL=http://192.168.31.154:8000/payment/return
```

Заменить в `.env` на:
```
YOOKASSA_RETURN_URL=https://твой-домен.ru/payment/return
```

### 10.2 Вебхук для автоматического подтверждения

В продакшене ЮКасса сама отправляет уведомление о платеже на вебхук.
В личном кабинете ЮКасса → Настройки → HTTP-уведомления → добавить URL:
```
https://твой-домен.ru/payments/webhook
```

Добавить обработчик в `backend/app/routers/payments.py`:
```python
from fastapi import Request

@router.post("/webhook", include_in_schema=False)
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    if body.get("event") == "payment.succeeded":
        obj = body.get("object", {})
        payment_id = obj.get("id")
        metadata = obj.get("metadata", {})
        client_id = int(metadata.get("client_id", 0))
        plan = metadata.get("plan")
        amount = float(obj.get("amount", {}).get("value", 0))
        if client_id and plan:
            try:
                check_payment_status(db, client_id, payment_id)
            except Exception:
                pass
    return {"ok": True}
```

### 10.3 Тестовые ключи → боевые

В `.env` поменять на боевые ключи:
```
YOOKASSA_SHOP_ID=твой_реальный_shop_id
YOOKASSA_SECRET_KEY=live_твой_ключ
```

---

## Итого — файлы которые нужно изменить:

| Файл | Что менять |
|------|------------|
| `app_mobile/lib/services/api_service.dart` | `baseUrl` → `https://домен` |
| `app_mobile/android/app/src/main/AndroidManifest.xml` | убрать `usesCleartextTraffic` |
| `backend/app/main.py` | `docs_url=None, redoc_url=None` + slowapi + `allow_origins` → домен |
| `backend/app/routers/auth.py` | `@limiter.limit("10/minute")` на `/login` |
| `backend/app/routers/payments.py` | добавить `/webhook` эндпоинт |
| `backend/requirements.txt` | добавить `slowapi==0.1.9` |
| `backend/.env` | `YOOKASSA_RETURN_URL` → https домен, боевые ключи ЮКасса |
| nginx config (новый файл на сервере) | создать конфиг reverse proxy |
| ЮКасса личный кабинет | добавить вебхук URL |
