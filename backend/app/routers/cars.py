from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_login
from app.models.client import ClientLogin
from app.schemas.car import CarResponse, WorkHistoryItem, PartResponse

router = APIRouter(prefix="/cars", tags=["cars"])


@router.get("/my", response_model=list[CarResponse], summary="Мои автомобили")
def get_my_cars(
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT id, car_brand, car_model, car_number, vin, mileage
            FROM client_cars
            WHERE client_id = :client_id
              AND car_brand IS NOT NULL AND car_brand != ''
            ORDER BY car_brand, car_model
        """),
        {"client_id": current_login.client_id},
    ).fetchall()

    return [
        CarResponse(
            id=r[0],
            car_brand=r[1],
            car_model=r[2],
            car_number=r[3],
            vin=r[4],
            mileage=r[5],
        )
        for r in rows
    ]


@router.delete("/{car_id}", summary="Удалить авто (история сохраняется)")
def delete_car(
    car_id: int,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    car = db.execute(
        text("SELECT id FROM client_cars WHERE id = :car_id AND client_id = :client_id"),
        {"car_id": car_id, "client_id": current_login.client_id},
    ).fetchone()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    # Отвязываем авто от клиента, но не удаляем — история работ сохраняется
    db.execute(
        text("UPDATE client_cars SET client_id = NULL WHERE id = :car_id"),
        {"car_id": car_id},
    )
    db.commit()
    return {"ok": True}


@router.get("/{car_id}/history", response_model=list[WorkHistoryItem], summary="История работ по авто")
def get_car_history(
    car_id: int,
    current_login: ClientLogin = Depends(get_current_login),
    db: Session = Depends(get_db),
):
    # Проверяем что авто принадлежит клиенту
    car = db.execute(
        text("SELECT id FROM client_cars WHERE id = :car_id AND client_id = :client_id"),
        {"car_id": car_id, "client_id": current_login.client_id},
    ).fetchone()
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")

    rows = db.execute(
        text("""
            SELECT w.id, w.work_date,
                   cc.car_brand, cc.car_model, cc.car_number,
                   w.description, w.amount, w.order_number, w.mileage,
                   COALESCE((SELECT SUM(p.part_price) FROM parts p WHERE p.work_id = w.id), 0) AS parts_total
            FROM works w
            JOIN client_cars cc ON w.car_id = cc.id
            WHERE cc.id = :car_id
            ORDER BY w.work_date DESC, w.id DESC
            LIMIT 50
        """),
        {"car_id": car_id},
    ).fetchall()

    result = []
    for r in rows:
        parts_rows = db.execute(
            text("SELECT part_name, part_price FROM parts WHERE work_id = :wid"),
            {"wid": r[0]},
        ).fetchall()
        result.append(
            WorkHistoryItem(
                work_id=r[0],
                work_date=r[1],
                car_brand=r[2],
                car_model=r[3],
                car_number=r[4],
                description=r[5],
                amount=r[6],
                order_number=r[7],
                mileage=r[8],
                parts_total=r[9],
                parts=[PartResponse(part_name=p[0], part_price=p[1]) for p in parts_rows],
            )
        )
    return result
