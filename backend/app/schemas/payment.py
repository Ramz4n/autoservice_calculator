from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional


class PurchaseRequest(BaseModel):
    plan: str  # basic / premium / vip


class PaymentResponse(BaseModel):
    payment_id: str
    amount: Decimal
    status: str
    confirmation_url: str
    subscription_id: Optional[int] = None


class PaymentHistoryResponse(BaseModel):
    id: int
    amount: Decimal
    payment_id: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
