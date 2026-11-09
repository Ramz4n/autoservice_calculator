from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_login
from app.models.client import ClientLogin
from app.schemas.booking import AvailableSlotsResponse, CreateBookingRequest, BookingResponse

router = APIRouter(prefix="/bookings", tags=["bookings"])

# Рабочие часы (те же дефолты что в боте)
WORKING_HOURS_START = 10
WORKING_HOURS_END = 20
SLOT_DURATION_MINUTES = 120  # 2 часа


def _generate_slots() -> list[str]:
    slots = []
    current = WORKING_HOURS_START * 60
    end = WORKING_HOURS_END * 60
    while current <= end:
        h, m = divmod(current, 60)
        slots.append(f"{h:02d}:{m:02d}")
        current += SLOT_DURATION_MINUTES
    return slots


ALL_SLOTS = _generate_slots()


@router.get("/slots", response_model=AvailableSlotsResponse, summary="Доступные слоты на дату")
def get_slots(
    booking_date: date,
    db: Session = Depends(get_db),
):
    if booking_date < date.today():
        raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшую дату")
    if booking_date > date.today() + timedelta(days=60):
        raise HTTPException(status_code=400, detail="Запись доступна не более чем на 60 дней вперёд")

    booked = db.execute(
        text("""
            SELECT booking_time FROM bookings
            WHERE booking_date = :d AND status IN ('waiting', 'in_progress')
        """),
        {"d": booking_date},
    ).fetchall()
    booked_times = {r[0] for r in booked}

    available = [s for s in ALL_SLOTS if s not in booked_times]
    return AvailableSlotsResponse(date=booking_date, slots=available)


@router.post("/create", response_model=BookingResponse, summary="Записаться в сервис")
def create_booking(
    data: CreateBookingRequest,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    if data.booking_date < date.today():
        raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшую дату")
    if data.booking_time not in ALL_SLOTS:
        raise HTTPException(status_code=400, detail="Недопустимое время")

    # Проверяем доступность слота
    busy = db.execute(
        text("""
            SELECT COUNT(*) FROM bookings
            WHERE booking_date = :d AND booking_time = :t AND status IN ('waiting', 'in_progress')
        """),
        {"d": data.booking_date, "t": data.booking_time},
    ).scalar()
    if busy:
        raise HTTPException(status_code=409, detail="Это время уже занято")

    # Проверяем что car_id принадлежит клиенту
    car_id = None
    if data.car_id:
        car = db.execute(
            text("SELECT id FROM client_cars WHERE id = :cid AND client_id = :uid"),
            {"cid": data.car_id, "uid": current_login.client_id},
        ).fetchone()
        if not car:
            raise HTTPException(status_code=404, detail="Автомобиль не найден")
        car_id = data.car_id

    db.execute(
        text("""
            INSERT INTO bookings (client_id, car_id, booking_date, booking_time, status)
            VALUES (:client_id, :car_id, :d, :t, 'waiting')
        """),
        {
            "client_id": current_login.client_id,
            "car_id": car_id,
            "d": data.booking_date,
            "t": data.booking_time,
        },
    )
    db.commit()

    booking = db.execute(
        text("""
            SELECT b.id, b.booking_date, b.booking_time, b.status,
                   CONCAT(COALESCE(cc.car_brand,''), ' ', COALESCE(cc.car_model,''), ' ', COALESCE(cc.car_number,'')) as car_display
            FROM bookings b
            LEFT JOIN client_cars cc ON b.car_id = cc.id
            WHERE b.client_id = :cid
            ORDER BY b.id DESC LIMIT 1
        """),
        {"cid": current_login.client_id},
    ).fetchone()

    return BookingResponse(
        id=booking[0],
        booking_date=booking[1],
        booking_time=booking[2],
        status=booking[3],
        car_display=booking[4].strip() if booking[4] else None,
    )


@router.post("/{booking_id}/cancel", summary="Отменить запись")
def cancel_booking(
    booking_id: int,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    booking = db.execute(
        text("""
            SELECT id, status FROM bookings
            WHERE id = :bid AND client_id = :cid
        """),
        {"bid": booking_id, "cid": current_login.client_id},
    ).fetchone()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if booking[1] not in ("waiting",):
        raise HTTPException(status_code=400, detail="Отменить можно только запись со статусом 'Ожидает'")

    db.execute(
        text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"),
        {"bid": booking_id},
    )
    db.commit()
    return {"ok": True}


@router.get("/my", response_model=list[BookingResponse], summary="Мои записи")
def get_my_bookings(
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT b.id, b.booking_date, b.booking_time, b.status,
                   CONCAT(COALESCE(cc.car_brand,''), ' ', COALESCE(cc.car_model,''), ' ', COALESCE(cc.car_number,'')) as car_display
            FROM bookings b
            LEFT JOIN client_cars cc ON b.car_id = cc.id
            WHERE b.client_id = :cid
            ORDER BY b.booking_date DESC, b.booking_time DESC
            LIMIT 20
        """),
        {"cid": current_login.client_id},
    ).fetchall()

    return [
        BookingResponse(
            id=r[0],
            booking_date=r[1],
            booking_time=r[2],
            status=r[3],
            car_display=r[4].strip() if r[4] else None,
        )
        for r in rows
    ]
