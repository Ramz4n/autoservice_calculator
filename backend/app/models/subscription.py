from sqlalchemy import (
    Column, Integer, String, DateTime, DECIMAL, ForeignKey, Enum, TIMESTAMP, text
)
from sqlalchemy.orm import relationship
from app.database import Base


class Subscription(Base):
    """Таблица подписок (существует в db_schema.py)."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    plan = Column(Enum("basic", "premium", "vip"), nullable=False)
    status = Column(Enum("active", "expired", "pending"), server_default="pending")
    started_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    payment_id = Column(String(100), unique=True, nullable=True)
    amount = Column(DECIMAL(10, 2), nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    client = relationship("Client", back_populates="subscriptions")
    payment_record = relationship("PaymentHistory", back_populates="subscription", uselist=False)


class PaymentHistory(Base):
    """История платежей (новая таблица)."""
    __tablename__ = "payment_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    amount = Column(DECIMAL(10, 2), nullable=False)
    payment_id = Column(String(100), unique=True, nullable=False)
    status = Column(String(30), server_default="pending")  # pending / succeeded / canceled
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    client = relationship("Client", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payment_record")
