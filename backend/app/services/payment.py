import uuid
from decimal import Decimal
from sqlalchemy.orm import Session
from yookassa import Configuration, Payment as YKPayment

from app.config import settings
from app.models.subscription import PaymentHistory
from app.services.subscription import SUBSCRIPTION_PLANS, create_subscription, get_active_subscription


def _configure_yookassa():
    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY


def process_payment(db: Session, client_id: int, plan: str) -> dict:
    if plan not in SUBSCRIPTION_PLANS:
        raise ValueError(f"Неизвестный план: {plan}")

    active = get_active_subscription(db, client_id)
    if active:
        raise ValueError("У вас уже есть активная подписка. Дождитесь её окончания.")

    plan_info = SUBSCRIPTION_PLANS[plan]
    amount = Decimal(str(plan_info["price"]))

    _configure_yookassa()

    payment = YKPayment.create({
        "amount": {
            "value": str(amount),
            "currency": "RUB",
        },
        "confirmation": {
            "type": "redirect",
            "return_url": settings.YOOKASSA_RETURN_URL,
        },
        "capture": True,
        "description": f"Подписка {plan_info['name']} — автосервис",
        "metadata": {
            "client_id": str(client_id),
            "plan": plan,
        },
    }, str(uuid.uuid4()))

    # Сохраняем ожидающий платёж — подписка активируется после подтверждения
    history = PaymentHistory(
        client_id=client_id,
        subscription_id=None,
        amount=amount,
        payment_id=payment.id,
        status="pending",
    )
    db.add(history)
    db.commit()

    return {
        "payment_id": payment.id,
        "amount": amount,
        "status": "pending",
        "confirmation_url": payment.confirmation.confirmation_url,
        "subscription_id": None,
    }


def check_payment_status(db: Session, client_id: int, payment_id: str) -> dict:
    """Проверяет статус платежа в ЮКасса и активирует подписку при успехе."""
    _configure_yookassa()

    payment = YKPayment.find_one(payment_id)

    history = db.query(PaymentHistory).filter(
        PaymentHistory.payment_id == payment_id,
        PaymentHistory.client_id == client_id,
    ).first()

    if not history:
        raise ValueError("Платёж не найден")

    if payment.status == "succeeded" and history.status != "succeeded":
        plan = payment.metadata.get("plan") if payment.metadata else None
        if not plan:
            raise ValueError("Некорректные данные платежа")

        sub = create_subscription(
            db, client_id, plan, payment_id, float(payment.amount.value)
        )
        history.status = "succeeded"
        history.subscription_id = sub.id
        db.commit()
        return {"status": "succeeded", "subscription_id": sub.id}

    if payment.status == "succeeded" and history.status == "succeeded":
        return {"status": "succeeded", "subscription_id": history.subscription_id}

    if payment.status == "canceled":
        history.status = "canceled"
        db.commit()

    return {"status": payment.status, "subscription_id": None}


def get_payment_history(db: Session, client_id: int) -> list:
    return (
        db.query(PaymentHistory)
        .filter(PaymentHistory.client_id == client_id)
        .order_by(PaymentHistory.created_at.desc())
        .all()
    )
