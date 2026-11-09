from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.client import ClientResponse
from app.models.client import Client, ClientLogin
from app.dependencies import get_current_login

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/me", response_model=ClientResponse, summary="Профиль текущего пользователя")
def get_me(
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == current_login.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден")

    return ClientResponse(
        id=client.id,
        email=current_login.email,
        full_name=client.full_name,
        phone=client.phone,
        role=current_login.role,
        created_at=current_login.created_at,
    )
