from sqlalchemy import (
    Column, Integer, String, BigInteger, TIMESTAMP, ForeignKey, Boolean, text
)
from sqlalchemy.orm import relationship
from app.database import Base


class Client(Base):
    """Основная таблица клиентов (существует в db_schema.py)."""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=True)
    tg_username = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    login = relationship("ClientLogin", back_populates="client", uselist=False)
    subscriptions = relationship("Subscription", back_populates="client")
    payments = relationship("PaymentHistory", back_populates="client")


class ClientLogin(Base):
    """Таблица авторизации клиентов мобильного приложения (новая)."""
    __tablename__ = "clients_login"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), server_default="user")  # user / admin
    is_active = Column(Boolean, server_default="1")
    token_version = Column(Integer, server_default="0")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    client = relationship("Client", back_populates="login")
