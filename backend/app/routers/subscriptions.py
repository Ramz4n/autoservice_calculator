from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_login, require_admin
from app.models.client import ClientLogin
from app.schemas.subscription import (
    SubscriptionResponse,
    ActiveSubscriptionResponse,
    SubscriptionPlanInfo,
)
from app.services.subscription import (
    get_active_subscription,
    get_subscription_services,
    get_all_subscriptions,
    expire_all_outdated,
    SUBSCRIPTION_PLANS,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=list[SubscriptionPlanInfo], summary="Список доступных планов")
def get_plans():
    return [
        SubscriptionPlanInfo(
            plan=key,
            name=info["name"],
            price=Decimal(str(info["price"])),
            features=info["features"],
        )
        for key, info in SUBSCRIPTION_PLANS.items()
    ]


@router.get("/my", response_model=ActiveSubscriptionResponse, summary="Моя активная подписка")
def get_my_subscription(
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    sub = get_active_subscription(db, current_login.client_id)
    if not sub:
        return ActiveSubscriptionResponse(has_active=False, subscription=None, services=[])

    return ActiveSubscriptionResponse(
        has_active=True,
        subscription=SubscriptionResponse.model_validate(sub),
        services=get_subscription_services(sub.plan),
    )


@router.get(
    "/admin/all",
    response_model=list[SubscriptionResponse],
    summary="[Admin] Все подписки",
)
def admin_get_all(
    current_login: ClientLogin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return get_all_subscriptions(db)


@router.post("/admin/expire", summary="[Admin] Принудительно погасить просроченные подписки")
def admin_expire(
    current_login: ClientLogin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    count = expire_all_outdated(db)
    return {"expired_count": count}
