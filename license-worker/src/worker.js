/**
 * Cloudflare Worker — бессерверная замена self-hosted backend для оплаты
 * лицензии (см. docs/LICENSE_PAYMENT_PLAN.md, раздел "Serverless-вариант").
 *
 * Два публичных пути:
 *   GET  /pay/{license_key}    -- создаёт платёж в ЮKassa, редиректит на оплату
 *   POST /webhook/yookassa     -- принимает уведомление, САМ проверяет статус
 *                                  через API ЮKassa (телу webhook не доверяем)
 *                                  и, если оплата прошла, ставит active=true
 *                                  этому license_key в jsonbin.
 *
 * ВАЖНО про lifetime-клиентов ("заплатил один раз -- пользуется всегда"):
 *   - Их license_key никогда не передаётся сюда через /pay -- ссылку на оплату
 *     для них вы просто не генерируете, поэтому воркер в принципе не создаст
 *     для них платёж.
 *   - Дополнительно (defense in depth): перед тем как ставить active=true,
 *     воркер проверяет billing_provider записи в jsonbin -- если там уже
 *     "lifetime", запись НЕ трогается, даже если платёж почему-то пришёл.
 */

const JSONBIN_BASE = "https://api.jsonbin.io/v3/b";
const YOOKASSA_BASE = "https://api.yookassa.ru/v3";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname.startsWith("/pay/")) {
      const licenseKey = decodeURIComponent(url.pathname.slice("/pay/".length));
      return handlePay(licenseKey, env);
    }

    if (request.method === "POST" && url.pathname === "/webhook/yookassa") {
      return handleWebhook(request, env);
    }

    if (request.method === "GET" && url.pathname === "/") {
      return new Response("autoservice-license-worker: ok", { status: 200 });
    }

    return new Response("Not found", { status: 404 });
  },
};

// ──────────────────────────────────────────────────────────
// GET /pay/{license_key} -- создать платёж и отправить на оплату
// ──────────────────────────────────────────────────────────
async function handlePay(licenseKey, env) {
  if (!licenseKey) {
    return new Response("Не указан license_key", { status: 400 });
  }

  const record = await jsonbinRead(env);
  const licenses = record.licenses || {};
  if (!licenses[licenseKey]) {
    return new Response("Лицензия не найдена", { status: 404 });
  }
  if (licenses[licenseKey].billing_provider === "lifetime") {
    // На lifetime-ключ платёжную ссылку никто не должен генерировать,
    // но если это всё же произошло -- отказываем явно, а не создаём платёж.
    return new Response("Эта лицензия оплачена бессрочно, оплата не требуется", { status: 400 });
  }

  const idempotenceKey = crypto.randomUUID();
  const priceRub = env.LICENSE_PRICE_RUB || "5000";

  const paymentRes = await fetch(`${YOOKASSA_BASE}/payments`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotence-Key": idempotenceKey,
      "Authorization": "Basic " + btoa(`${env.YOOKASSA_SHOP_ID}:${env.YOOKASSA_SECRET_KEY}`),
    },
    body: JSON.stringify({
      amount: { value: Number(priceRub).toFixed(2), currency: "RUB" },
      confirmation: { type: "redirect", return_url: "https://t.me/" },
      capture: true,
      description: `Лицензия автосервис-приложения (${licenseKey})`,
      metadata: { license_key: licenseKey },
    }),
  });

  if (!paymentRes.ok) {
    const errText = await paymentRes.text();
    return new Response(`Ошибка создания платежа: ${errText}`, { status: 502 });
  }

  const payment = await paymentRes.json();
  const confirmationUrl = payment?.confirmation?.confirmation_url;
  if (!confirmationUrl) {
    return new Response("ЮKassa не вернула ссылку на оплату", { status: 502 });
  }

  return Response.redirect(confirmationUrl, 302);
}

// ──────────────────────────────────────────────────────────
// POST /webhook/yookassa -- подтверждение оплаты
// ──────────────────────────────────────────────────────────
async function handleWebhook(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }

  const paymentId = body?.object?.id;
  const event = body?.event;
  if (event !== "payment.succeeded" || !paymentId) {
    // Другие события (waiting_for_capture, canceled и т.д.) нам не интересны.
    return new Response("ignored", { status: 200 });
  }

  // Телу webhook НЕ доверяем -- перезапрашиваем реальный статус у ЮKassa.
  const paymentRes = await fetch(`${YOOKASSA_BASE}/payments/${paymentId}`, {
    headers: {
      "Authorization": "Basic " + btoa(`${env.YOOKASSA_SHOP_ID}:${env.YOOKASSA_SECRET_KEY}`),
    },
  });
  if (!paymentRes.ok) {
    return new Response("payment lookup failed", { status: 502 });
  }
  const payment = await paymentRes.json();

  if (payment.status !== "succeeded") {
    return new Response("payment not succeeded", { status: 200 });
  }

  const licenseKey = payment?.metadata?.license_key;
  if (!licenseKey) {
    return new Response("no license_key in metadata", { status: 200 });
  }

  const record = await jsonbinRead(env);
  const licenses = record.licenses || {};
  const entry = licenses[licenseKey];

  if (!entry) {
    return new Response("license_key not found in jsonbin", { status: 200 });
  }
  if (entry.billing_provider === "lifetime") {
    // Защита от случайного затрагивания lifetime-клиента -- такой платёж
    // в принципе не должен был возникнуть (см. handlePay), но перестраховываемся.
    return new Response("lifetime license -- not touched", { status: 200 });
  }

  entry.active = true;
  entry.billing_provider = entry.billing_provider || "ru_yookassa";
  entry.last_payment_id = paymentId;
  entry.activated_at = new Date().toISOString();
  licenses[licenseKey] = entry;
  record.licenses = licenses;

  await jsonbinWrite(env, record);

  return new Response("ok", { status: 200 });
}

// ──────────────────────────────────────────────────────────
// jsonbin.io helpers
// ──────────────────────────────────────────────────────────
async function jsonbinRead(env) {
  const res = await fetch(`${JSONBIN_BASE}/${env.JSONBIN_BIN_ID}/latest`, {
    headers: { "X-Access-Key": env.JSONBIN_WRITE_KEY },
  });
  if (!res.ok) {
    throw new Error(`jsonbin read failed: ${res.status}`);
  }
  const body = await res.json();
  return body.record || body;
}

async function jsonbinWrite(env, record) {
  const res = await fetch(`${JSONBIN_BASE}/${env.JSONBIN_BIN_ID}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Access-Key": env.JSONBIN_WRITE_KEY,
      "X-Bin-Versioning": "false",
    },
    body: JSON.stringify(record),
  });
  if (!res.ok) {
    throw new Error(`jsonbin write failed: ${res.status}`);
  }
}
