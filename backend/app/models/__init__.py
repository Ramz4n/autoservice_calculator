# Импортируем все модели, чтобы Base.metadata знал о них при create_all
from app.models.client import Client, ClientLogin
from app.models.subscription import Subscription, PaymentHistory
from app.models.car import ClientCar, Work, Part, Booking

__all__ = ["Client", "ClientLogin", "Subscription", "PaymentHistory", "ClientCar", "Work", "Part", "Booking"]
