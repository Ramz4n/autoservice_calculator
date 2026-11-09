# autoservice-license-worker

Бессерверная (Cloudflare Workers) замена self-hosted backend из
`docs/LICENSE_PAYMENT_PLAN.md` — не нужен свой VPS/сервер. Делает две вещи:

- `GET /pay/{license_key}` — создаёт платёж в ЮKassa и редиректит клиента на оплату
  (эту ссылку кодирует QR на экране входа в приложение).
- `POST /webhook/yookassa` — принимает уведомление об оплате, сам перепроверяет
  статус через API ЮKassa и, если оплата реально прошла, ставит `active: true`
  этому ключу в jsonbin.

Про клиента с разовой пожизненной оплатой ("lifetime") — см. комментарии в
начале `src/worker.js`: воркер физически не создаст для него платёж (вы
просто не генерируете для него `/pay/{key}` ссылку) и дополнительно
проверяет `billing_provider !== "lifetime"` перед любой записью в jsonbin.

## Что нужно перед деплоем

1. **Аккаунт ЮKassa** (shopId + секретный ключ, Настройки → API).
2. **Бесплатный аккаунт Cloudflare** + установленный `wrangler`:
   ```
   npm install -g wrangler
   wrangler login
   ```
3. **Отдельный jsonbin-ключ с правом записи**, отличный от того, что сейчас
   лежит в `license.py`. Зайдите на jsonbin.io → API Keys → создайте новый
   ключ с доступом только к этому бину. Этот новый ключ живёт ТОЛЬКО в
   воркере (см. ниже) — в клиентское приложение он не попадёт.
   Ключ, который сейчас в `license.py` (`API_KEY`), после этого стоит
   заменить на **read-only** ключ (создать отдельно в jsonbin с правами
   только на чтение) — см. TODO в конце.

## Деплой

Из папки `license-worker/`:

```
wrangler secret put YOOKASSA_SHOP_ID
wrangler secret put YOOKASSA_SECRET_KEY
wrangler secret put JSONBIN_BIN_ID          # сейчас "69a7fe29ae596e708f5df259"
wrangler secret put JSONBIN_WRITE_KEY       # новый ключ с правом записи (см. выше)
wrangler secret put LICENSE_PRICE_RUB       # например "5000"

wrangler deploy
```

После `deploy` Cloudflare выдаст адрес вида
`https://autoservice-license-worker.<ваш-субдомен>.workers.dev` — это и есть
базовый URL. Полные пути:

- `https://.../pay/{license_key}`
- `https://.../webhook/yookassa`

## Настройка ЮKassa

В личном кабинете ЮKassa → Настройки → HTTP-уведомления — укажите:

```
https://autoservice-license-worker.<ваш-субдомен>.workers.dev/webhook/yookassa
```

и подпишитесь минимум на событие `payment.succeeded`.

## Проверка

```
curl https://autoservice-license-worker.<ваш-субдомен>.workers.dev/
```

должно вернуть `autoservice-license-worker: ok`.

Реальный платёж проверяется так: открыть в браузере
`.../pay/<любой существующий license_key из jsonbin>` — должно
перекинуть на страницу оплаты ЮKassa. После тестовой оплаты в jsonbin
у этого ключа должно появиться `active: true`.

## Дальнейшие шаги (после того как воркер задеплоен и проверен)

- В `login_window.py` — сгенерировать QR (библиотека `qrcode` уже в проекте),
  который кодирует `.../pay/{license_key}` текущего клиента, и кнопку
  "Я оплатил, проверить снова" → повторный вызов `check_license()`.
- В `license.py` — заменить `API_KEY` на новый **read-only** ключ jsonbin
  (создать отдельно в jsonbin.io, права только на чтение этого бина).
