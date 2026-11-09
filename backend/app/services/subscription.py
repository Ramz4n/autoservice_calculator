from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.subscription import Subscription

SUBSCRIPTION_PLANS: dict = {
    "basic": {
        "name": "Basic (масляная)",
        "price": 9900.00,
        "features": [
            "2 замены масла (работа бесплатно)",
            "Диагностика ходовой 2 раза",
            "Проверка АКБ",
            "Проверка тормозов",
            "Проверка жидкостей",
            "Скидка 10% на работу",
        ],
    },
    "premium": {
        "name": "Premium",
        "price": 23900.00,
        "features": [
            "2 замены масла (всё включено)",
            "Эвакуатор 1 раз",
            "Диагностика 3 раза",
            "Проверка подвески",
            "Проверка тормозов",
            "Проверка АКБ",
            "Проверка кондиционера",
            "Приоритетная запись",
            "Скидка 15% на работу",
        ],
    },
    "vip": {
        "name": "VIP",
        "price": 39900.00,
        "features": [
            "2 замены масла (всё включено)",
            "Эвакуатор 2 раза",
            "Диагностика без ограничений",
            "Проверка подвески",
            "Проверка тормозов",
            "Проверка АКБ",
            "Проверка кондиционера",
            "Скидка 20% на работу",
            "Приоритетная запись",
            "Сезонная подготовка авто",
        ],
    },
}


def get_active_subscription(db: Session, client_id: int) -> Optional[Subscription]:
    now = datetime.now(timezone.utc)

    # Автоматически гасим просроченные активные подписки
    expired_subs = (
        db.query(Subscription)
        .filter(
            Subscription.client_id == client_id,
            Subscription.status == "active",
            Subscription.expires_at <= now,
        )
        .all()
    )
    if expired_subs:
        for sub in expired_subs:
            sub.status = "expired"
        db.commit()

    return (
        db.query(Subscription)
        .filter(
            Subscription.client_id == client_id,
            Subscription.status == "active",
            Subscription.expires_at > now,
        )
        .first()
    )


def get_subscription_services(plan: str) -> list:
    return SUBSCRIPTION_PLANS.get(plan, {}).get("features", [])


def create_subscription(
    db: Session,
    client_id: int,
    plan: str,
    payment_id: str,
    amount: float,
) -> Subscription:
    # Гасим все существующие активные подписки клиента
    old_subs = (
        db.query(Subscription)
        .filter(Subscription.client_id == client_id, Subscription.status == "active")
        .all()
    )
    for old in old_subs:
        old.status = "expired"

    now = datetime.now(timezone.utc)
    sub = Subscription(
        client_id=client_id,
        plan=plan,
        status="active",
        started_at=now,
        expires_at=now + timedelta(days=365),
        payment_id=payment_id,
        amount=amount,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_all_subscriptions(db: Session) -> list:
    return db.query(Subscription).order_by(Subscription.created_at.desc()).all()


def expire_all_outdated(db: Session) -> int:
    """Принудительно гасим все просроченные подписки. Возвращает кол-во обновлённых."""
    now = datetime.now(timezone.utc)
    subs = (
        db.query(Subscription)
        .filter(Subscription.status == "active", Subscription.expires_at <= now)
        .all()
    )
    for sub in subs:
        sub.status = "expired"
    db.commit()
    return len(subs)
