from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ClientResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}
