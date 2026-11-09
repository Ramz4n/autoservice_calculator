from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.models import Client, ClientLogin, Subscription, PaymentHistory  # noqa: F401
from app.routers import auth, clients, subscriptions, payments, cars, bookings, settings

# Создаём только новые таблицы (clients_login, payment_history).
# Существующие (clients, subscriptions и др.) не трогаются благодаря checkfirst=True.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AutoService API",
    version="1.0.0",
    description="Backend для мобильного приложения автосервиса с подписочной моделью",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(subscriptions.router)
app.include_router(payments.router)
app.include_router(cars.router)
app.include_router(bookings.router)
app.include_router(settings.router)


@app.get("/payment/return")
def payment_return():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;text-align:center;padding:60px">
    <h2>✅ Оплата завершена</h2>
    <p>Вернитесь в приложение — подписка будет активирована автоматически.</p>
    </body></html>
    """)


@app.get("/")
def root():
    from fastapi.responses import Response
    return Response(status_code=404)


@app.post("/test-post")
def test_post():
    return {"ok": True}
