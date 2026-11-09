from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError

from app.database import get_db
from app.services.auth import decode_token
from app.models.client import ClientLogin

bearer_scheme = HTTPBearer()


def get_current_login(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ClientLogin:
    try:
        payload = decode_token(credentials.credentials)
        client_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Невалидный токен")

    login = db.query(ClientLogin).filter(ClientLogin.client_id == client_id).first()
    if not login or not login.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден или неактивен")

    # Проверяем версию токена — если пароль/email менялся, старый токен не пройдёт
    token_version = payload.get("tv", 0)
    if token_version != (login.token_version or 0):
        raise HTTPException(status_code=401, detail="Токен устарел, войдите заново")

    return login


def require_admin(
    current_login: ClientLogin = Depends(get_current_login),
) -> ClientLogin:
    if current_login.role != "admin":
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return current_login
