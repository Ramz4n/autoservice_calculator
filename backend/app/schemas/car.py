from pydantic import BaseModel
from datetime import date
from typing import Optional, List
from decimal import Decimal


class CarResponse(BaseModel):
    id: int
    car_brand: Optional[str]
    car_model: Optional[str]
    car_number: Optional[str]
    vin: Optional[str]
    mileage: Optional[str]

    model_config = {"from_attributes": True}


class PartResponse(BaseModel):
    part_name: str
    part_price: Decimal


class WorkHistoryItem(BaseModel):
    work_id: int
    work_date: date
    car_brand: Optional[str]
    car_model: Optional[str]
    car_number: Optional[str]
    description: str
    amount: Decimal
    parts_total: Decimal
    order_number: Optional[str]
    mileage: Optional[int]
    parts: List[PartResponse] = []
