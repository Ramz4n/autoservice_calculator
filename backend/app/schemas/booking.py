from pydantic import BaseModel
from datetime import date
from typing import Optional, List


class AvailableSlotsResponse(BaseModel):
    date: date
    slots: List[str]


class CreateBookingRequest(BaseModel):
    booking_date: date
    booking_time: str
    car_id: Optional[int] = None


class BookingResponse(BaseModel):
    id: int
    booking_date: date
    booking_time: str
    status: str
    car_display: Optional[str]

    model_config = {"from_attributes": True}
