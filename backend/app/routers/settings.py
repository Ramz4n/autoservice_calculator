from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_login
from app.models.client import ClientLogin
from app.services.auth import hash_password, verify_password, normalize_phone

router = APIRouter(prefix="/settings", tags=["settings"])


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None

    def model_post_init(self, __context):
        if self.full_name is not None and len(self.full_name) > 255:
            raise ValueError("Имя слишком длинное")
        if self.phone is not None and len(self.phone) > 20:
            raise ValueError("Телефон слишком длинный")


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    def model_post_init(self, __context):
        if len(self.new_password) > 128:
            raise ValueError("Пароль слишком длинный")


class ChangeEmailRequest(BaseModel):
    email: EmailStr
    current_password: str


@router.put("/profile", summary="Обновить имя и телефон")
def update_profile(
    data: UpdateProfileRequest,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    if data.full_name is None and data.phone is None:
        raise HTTPException(status_code=400, detail="Нет данных для обновления")

    if data.full_name is not None and data.phone is not None:
        db.execute(
            text("UPDATE clients SET full_name = :n, phone = :p WHERE id = :id"),
            {"n": data.full_name.strip(), "p": normalize_phone(data.phone.strip()),
             "id": current_login.client_id},
        )
    elif data.full_name is not None:
        db.execute(
            text("UPDATE clients SET full_name = :n WHERE id = :id"),
            {"n": data.full_name.strip(), "id": current_login.client_id},
        )
    else:
        db.execute(
            text("UPDATE clients SET phone = :p WHERE id = :id"),
            {"p": normalize_phone(data.phone.strip()), "id": current_login.client_id},
        )
    db.commit()
    return {"ok": True}


@router.put("/password", summary="Изменить пароль")
def change_password(
    data: ChangePasswordRequest,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, current_login.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Пароль должен быть минимум 6 символов")

    db.execute(
        text("UPDATE clients_login SET password_hash = :h, token_version = token_version + 1 WHERE id = :id"),
        {"h": hash_password(data.new_password), "id": current_login.id},
    )
    db.commit()
    return {"ok": True}


@router.put("/email", summary="Изменить email")
def change_email(
    data: ChangeEmailRequest,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, current_login.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")

    existing = db.execute(
        text("SELECT id FROM clients_login WHERE email = :email AND id != :id"),
        {"email": data.email, "id": current_login.id},
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Этот email уже занят")

    db.execute(
        text("UPDATE clients_login SET email = :email, token_version = token_version + 1 WHERE id = :id"),
        {"email": data.email, "id": current_login.id},
    )
    db.commit()
    return {"ok": True}
