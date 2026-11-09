from sqlalchemy import Column, Integer, String, Date, DECIMAL, ForeignKey, TEXT, TIMESTAMP, text
from sqlalchemy.orm import relationship
from app.database import Base


class ClientCar(Base):
    """Автомобили клиентов (существующая таблица)."""
    __tablename__ = "client_cars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    car_brand = Column(String(100), nullable=True)
    car_model = Column(String(100), nullable=True)
    car_number = Column(String(20), nullable=True, unique=True)
    vin = Column(String(20), nullable=True)
    mileage = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    works = relationship("Work", back_populates="car")
    bookings = relationship("Booking", back_populates="car")


class Work(Base):
    """Выполненные работы (существующая таблица)."""
    __tablename__ = "works"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(Integer, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    car_id = Column(Integer, ForeignKey("client_cars.id"), nullable=True)
    booking_id = Column(Integer, nullable=True)
    description = Column(TEXT, nullable=False)
    amount = Column(DECIMAL(12, 2), nullable=False)
    work_date = Column(Date, nullable=False)
    mileage = Column(Integer, nullable=True)
    order_number = Column(String(20), unique=True, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    car = relationship("ClientCar", back_populates="works")
    parts = relationship("Part", back_populates="work")


class Part(Base):
    """Запчасти к работам (существующая таблица)."""
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_id = Column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    part_name = Column(TEXT, nullable=False)
    part_price = Column(DECIMAL(12, 2), nullable=False)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    work = relationship("Work", back_populates="parts")


class Booking(Base):
    """Записи на сервис (существующая таблица)."""
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    car_id = Column(Integer, ForeignKey("client_cars.id"), nullable=True)
    booking_date = Column(Date, nullable=False)
    booking_time = Column(String(10), nullable=False)
    status = Column(String(20), server_default="waiting")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    car = relationship("ClientCar", back_populates="bookings")
