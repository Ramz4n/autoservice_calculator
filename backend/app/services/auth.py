from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.models.client import Client, ClientLogin
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def normalize_phone(phone: str | None) -> str | None:
    """Приводит номер к формату +7XXXXXXXXXX как в БД."""
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    # Если уже начинается с +7 — оставляем как есть
    if phone.startswith("+"):
        return phone
    return phone


def register_client(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
    phone: str | None = None,
) -> ClientLogin:
    existing = db.query(ClientLogin).filter(ClientLogin.email == email).first()
    if existing:
        raise ValueError("Email уже зарегистрирован")

    normalized_phone = normalize_phone(phone)

    # Ищем существующего клиента по номеру телефона (например, уже есть в боте)
    existing_client = None
    if normalized_phone:
        existing_client = (
            db.query(Client).filter(Client.phone == normalized_phone).first()
        )

    if existing_client:
        # Привязываемся к существующему клиенту — все его авто и записи становятся доступны
        client = existing_client
        if full_name and not existing_client.full_name:
            existing_client.full_name = full_name
    else:
        client = Client(full_name=full_name, phone=normalized_phone)
        db.add(client)
        db.flush()

    login = ClientLogin(
        client_id=client.id,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(login)
    db.commit()
    db.refresh(login)
    return login


def authenticate_client(db: Session, email: str, password: str) -> ClientLogin | None:
    login = db.query(ClientLogin).filter(ClientLogin.email == email).first()
    if not login or not verify_password(password, login.password_hash):
        return None
    return login
