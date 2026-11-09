from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from decimal import Decimal


class SubscriptionPlanInfo(BaseModel):
    plan: str
    name: str
    price: Decimal
    features: List[str]


class SubscriptionResponse(BaseModel):
    id: int
    plan: str
    status: str
    started_at: Optional[datetime]
    expires_at: Optional[datetime]
    amount: Optional[Decimal]
    created_at: datetime

    model_config = {"from_attributes": True}


class ActiveSubscriptionResponse(BaseModel):
    has_active: bool
    subscription: Optional[SubscriptionResponse]
    services: List[str]
