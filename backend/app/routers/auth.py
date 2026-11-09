from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.services.auth import register_client, authenticate_client, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, summary="Регистрация")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    try:
        login = register_client(db, data.email, data.password, data.full_name, data.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = create_access_token(
        {"sub": str(login.client_id), "email": login.email, "role": login.role, "tv": login.token_version or 0}
    )
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse, summary="Вход")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    login = authenticate_client(db, data.email, data.password)
    if not login:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    token = create_access_token(
        {"sub": str(login.client_id), "email": login.email, "role": login.role, "tv": login.token_version or 0}
    )
    return TokenResponse(access_token=token)
