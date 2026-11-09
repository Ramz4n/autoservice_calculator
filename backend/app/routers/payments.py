from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_login
from app.models.client import ClientLogin
from app.schemas.payment import PurchaseRequest, PaymentResponse, PaymentHistoryResponse
from app.services.payment import process_payment, get_payment_history, check_payment_status

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/purchase", response_model=PaymentResponse, summary="Купить подписку")
def purchase_subscription(
    data: PurchaseRequest,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    try:
        result = process_payment(db, current_login.client_id, data.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PaymentResponse(**result)


@router.get("/status/{payment_id}", summary="Проверить статус платежа")
def payment_status(
    payment_id: str,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    try:
        result = check_payment_status(db, current_login.client_id, payment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get(
    "/history",
    response_model=list[PaymentHistoryResponse],
    summary="История платежей",
)
def payment_history(
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    return get_payment_history(db, current_login.client_id)
