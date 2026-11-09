# AutoService — система с подписочной моделью

Полная система для автосервиса: FastAPI backend + Flutter мобильное приложение.

## Структура проекта

```
.
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── dependencies.py
│   │   ├── models/           # SQLAlchemy ORM модели
│   │   │   ├── client.py     # clients, clients_login
│   │   │   └── subscription.py # subscriptions, payment_history
│   │   ├── schemas/          # Pydantic схемы
│   │   ├── routers/          # FastAPI роутеры
│   │   └── services/         # Бизнес-логика
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── app_mobile/               # Flutter приложение
│   ├── lib/
│   │   ├── main.dart
│   │   ├── models/           # user.dart, subscription.dart
│   │   ├── services/         # api_service.dart, storage_service.dart
│   │   └── screens/          # login, register, profile, subscriptions, purchase
│   └── pubspec.yaml
├── docker-compose.yml
└── README.md
```

## Запуск через Docker (рекомендуется)

### 1. Подготовка .env

```bash
cp backend/.env.example backend/.env
# Отредактируйте backend/.env — задайте DB_PASSWORD и SECRET_KEY
```

### 2. Запуск

```bash
docker-compose up --build
```

API будет доступно на http://localhost:8000
Swagger документация: http://localhost:8000/docs

---

## Запуск backend локально (без Docker)

### Требования
- Python 3.12+
- MariaDB 10.6+

### 1. Создать базу данных и пользователя

```sql
CREATE DATABASE autoservice CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'autoservice_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON autoservice.* TO 'autoservice_user'@'localhost';
FLUSH PRIVILEGES;
```

### 2. Создать основные таблицы из db_schema.py

```python
# Из корня проекта:
python -c "
import mysql.connector, sys
sys.path.insert(0, '.')
from db_schema import TABLES, INDEXES
conn = mysql.connector.connect(host='localhost', user='autoservice_user', password='your_password', database='autoservice')
cur = conn.cursor()
for name, sql in TABLES.items():
    cur.execute(sql)
conn.commit()
conn.close()
print('Done')
"
```

### 3. Установить зависимости и запустить

```bash
cd backend
cp .env.example .env
# Отредактируйте .env — укажите DB_HOST=localhost

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> При первом запуске SQLAlchemy автоматически создаст таблицы `clients_login` и `payment_history`.

---

## Запуск Flutter приложения

### Требования
- Flutter SDK 3.22+
- Android Studio / Xcode (для эмулятора)

```bash
cd app_mobile
flutter pub get
flutter run
```

> По умолчанию в `api_service.dart` адрес сервера — `http://10.0.2.2:8000` (Android эмулятор).
> Для реального устройства замените на IP вашего компьютера в локальной сети.

---

## Планы подписок

| План    | Цена       | Ключевые услуги                              |
|---------|------------|----------------------------------------------|
| Basic   | 9 900 ₽/г  | 2 замены масла (работа), диагностика x2, скидка 10% |
| Premium | 23 900 ₽/г | 2 замены масла (all-in), эвакуатор x1, диагностика x3, скидка 15% |
| VIP     | 39 900 ₽/г | 2 замены масла (all-in), эвакуатор x2, неогр. диагностика, скидка 20%, сезонная подготовка |

---

## Примеры API запросов

### Регистрация
```http
POST /auth/register
Content-Type: application/json

{
  "email": "client@example.com",
  "password": "securepassword",
  "full_name": "Иван Иванов",
  "phone": "+7 900 123 4567"
}
```

### Логин
```http
POST /auth/login
Content-Type: application/json

{
  "email": "client@example.com",
  "password": "securepassword"
}
```

Ответ:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

### Профиль пользователя
```http
GET /clients/me
Authorization: Bearer eyJ...
```

### Список планов подписок
```http
GET /subscriptions/plans
```

### Моя активная подписка
```http
GET /subscriptions/my
Authorization: Bearer eyJ...
```

### Купить подписку (mock YooKassa)
```http
POST /payments/purchase
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "plan": "premium"
}
```

### История платежей
```http
GET /payments/history
Authorization: Bearer eyJ...
```

### [Admin] Все подписки
```http
GET /subscriptions/admin/all
Authorization: Bearer eyJ...
```

### [Admin] Погасить просроченные подписки
```http
POST /subscriptions/admin/expire
Authorization: Bearer eyJ...
```

---

## Назначение администратора

Напрямую в БД:
```sql
UPDATE clients_login SET role = 'admin' WHERE email = 'admin@example.com';
```

---

## Архитектура БД

- **clients** — базовая информация о клиентах (существующая таблица, совместима с Telegram ботом)
- **clients_login** — email/пароль для авторизации в мобильном приложении (новая, FK → clients)
- **subscriptions** — подписки клиентов (существующая таблица, FK → clients)
- **payment_history** — история платежей (новая, FK → clients + subscriptions)
