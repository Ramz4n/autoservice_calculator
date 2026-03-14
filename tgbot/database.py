import aiomysql
import re
from datetime import date, datetime
from config import DB_CONFIG


class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        """Создание пула соединений с БД"""
        self.pool = await aiomysql.create_pool(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            db=DB_CONFIG["database"],
            autocommit=True
        )

    async def close(self):
        """Закрытие пула соединений"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def init_tables(self):
        """Создание таблиц если не существуют"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Таблица клиентов (центральная таблица)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS clients (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        telegram_user_id BIGINT UNIQUE,
                        tg_username VARCHAR(255),
                        full_name VARCHAR(255),
                        phone VARCHAR(50),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_phone (phone)
                    ) ENGINE=InnoDB
                """)

                # Таблица записей (данные клиента через client_id -> clients)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS bookings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        client_id INT,
                        car_id INT,
                        booking_date DATE NOT NULL,
                        booking_time VARCHAR(10) NOT NULL,
                        status VARCHAR(20) DEFAULT 'waiting',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_booking_datetime (booking_date, booking_time)
                    ) ENGINE=InnoDB
                """)

                # Таблица для хранения Telegraph страниц клиентов
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS telegraph_pages (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL UNIQUE,
                        page_path VARCHAR(255),
                        access_token VARCHAR(255),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                """)

                # Добавляем колонки если их нет (для существующих баз)
                try:
                    await cur.execute("ALTER TABLE bookings ADD COLUMN status VARCHAR(20) DEFAULT 'waiting'")
                except:
                    pass
                try:
                    await cur.execute("ALTER TABLE bookings ADD COLUMN client_id INT AFTER id")
                except:
                    pass
                try:
                    await cur.execute("ALTER TABLE bookings ADD COLUMN car_id INT AFTER client_id")
                except:
                    pass
                try:
                    await cur.execute("ALTER TABLE bookings ADD COLUMN reminder_sent BOOLEAN DEFAULT FALSE")
                except:
                    pass
                try:
                    await cur.execute("ALTER TABLE bookings ADD COLUMN reminder_1h_sent BOOLEAN DEFAULT FALSE")
                except:
                    pass

                # Удаляем уникальный ключ, чтобы разрешить несколько записей на одно время
                try:
                    await cur.execute("ALTER TABLE bookings DROP INDEX unique_booking")
                except:
                    pass

                # Таблица автомобилей клиентов (данные клиента через client_id -> clients)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS client_cars (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        client_id INT,
                        car_brand VARCHAR(100),
                        car_model VARCHAR(100),
                        car_number VARCHAR(20),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_car_number (car_number)
                    ) ENGINE=InnoDB
                """)

                # Добавляем client_id в client_cars если нет
                try:
                    await cur.execute("ALTER TABLE client_cars ADD COLUMN client_id INT AFTER id")
                except:
                    pass

                # Добавляем индексы
                try:
                    await cur.execute("CREATE INDEX idx_bookings_client_id ON bookings(client_id)")
                except:
                    pass
                try:
                    await cur.execute("CREATE INDEX idx_client_cars_client_id ON client_cars(client_id)")
                except:
                    pass

    # --- Методы для работы с клиентами ---

    def _normalize_phone(self, phone: str) -> str | None:
        """Нормализовать телефон в формат +79051234567"""
        if not phone:
            return None
        digits = re.sub(r'\D', '', phone)
        if len(digits) == 11 and digits.startswith('8'):
            digits = '7' + digits[1:]
        if len(digits) == 11 and digits.startswith('7'):
            return '+' + digits
        if len(digits) == 10:
            return '+7' + digits
        return '+' + digits if digits else None

    async def get_or_create_client(self, telegram_user_id: int, full_name: str = None, phone: str = None, tg_username: str = None) -> int:
        """Найти или создать клиента по telegram_user_id или телефону. Возвращает client_id"""
        # Нормализуем телефон
        normalized_phone = self._normalize_phone(phone)

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Сначала ищем по telegram_user_id
                if telegram_user_id:
                    await cur.execute(
                        "SELECT id FROM clients WHERE telegram_user_id = %s",
                        (telegram_user_id,)
                    )
                    result = await cur.fetchone()
                    if result:
                        # Обновляем данные если переданы
                        if full_name or normalized_phone or tg_username:
                            await cur.execute("""
                                UPDATE clients SET
                                    tg_username = COALESCE(%s, tg_username),
                                    full_name = COALESCE(%s, full_name),
                                    phone = COALESCE(%s, phone)
                                WHERE id = %s
                            """, (tg_username, full_name, normalized_phone, result[0]))
                        return result[0]

                # Если не нашли по telegram_user_id - ищем по телефону (последние 10 цифр)
                if normalized_phone and len(normalized_phone) >= 10:
                    phone_suffix = normalized_phone[-10:]
                    await cur.execute(
                        "SELECT id FROM clients WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s",
                        (phone_suffix,)
                    )
                    result = await cur.fetchone()
                    if result:
                        # Обновляем telegram_user_id и другие данные
                        await cur.execute("""
                            UPDATE clients SET
                                telegram_user_id = COALESCE(%s, telegram_user_id),
                                tg_username = COALESCE(%s, tg_username),
                                full_name = COALESCE(%s, full_name),
                                phone = COALESCE(%s, phone)
                            WHERE id = %s
                        """, (telegram_user_id, tg_username, full_name, normalized_phone, result[0]))
                        return result[0]

                # Создаём нового клиента
                await cur.execute("""
                    INSERT INTO clients (telegram_user_id, tg_username, full_name, phone)
                    VALUES (%s, %s, %s, %s)
                """, (telegram_user_id, tg_username, full_name, normalized_phone))
                return cur.lastrowid

    async def get_client_by_telegram_id(self, telegram_user_id: int) -> dict | None:
        """Получить клиента по telegram_user_id"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM clients WHERE telegram_user_id = %s",
                    (telegram_user_id,)
                )
                return await cur.fetchone()

    async def get_or_create_car(self, client_id: int, car_brand: str, car_model: str, car_number: str) -> int | None:
        """Найти или создать авто. Возвращает car_id"""
        if not car_number:
            return None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Ищем авто по госномеру
                await cur.execute(
                    "SELECT id FROM client_cars WHERE UPPER(car_number) = UPPER(%s)",
                    (car_number,)
                )
                result = await cur.fetchone()

                if result:
                    # Обновляем client_id
                    if client_id:
                        await cur.execute(
                            "UPDATE client_cars SET client_id = %s WHERE id = %s",
                            (client_id, result[0])
                        )
                    return result[0]

                # Создаём новое авто
                await cur.execute("""
                    INSERT INTO client_cars (client_id, car_brand, car_model, car_number)
                    VALUES (%s, %s, %s, %s)
                """, (client_id, car_brand, car_model, car_number.upper()))
                return cur.lastrowid

    # --- Методы для работы с записями ---

    async def is_slot_available(self, booking_date: date, booking_time: str) -> bool:
        """Проверка доступности слота (учитываем записи в ожидании и в работе)"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM bookings WHERE booking_date = %s AND booking_time = %s AND status IN ('waiting', 'in_progress')",
                    (booking_date, booking_time)
                )
                result = await cur.fetchone()
                return result[0] == 0

    async def get_booked_slots(self, booking_date: date) -> list:
        """Получение занятых слотов на дату (записи в ожидании и в работе)"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT booking_time FROM bookings WHERE booking_date = %s AND status IN ('waiting', 'in_progress')",
                    (booking_date,)
                )
                result = await cur.fetchall()
                return [row[0] for row in result]

    async def create_booking(self, booking_date: date, booking_time: str,
                            client_id: int, car_id: int = None) -> bool:
        """Создание записи. Данные клиента берутся из таблицы clients по client_id."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Удаляем старые неактивные записи на это время (cancelled/completed)
                    await cur.execute(
                        """DELETE FROM bookings
                           WHERE booking_date = %s AND booking_time = %s AND status NOT IN ('waiting', 'in_progress')""",
                        (booking_date, booking_time)
                    )
                    # Создаём новую запись с client_id и car_id
                    await cur.execute(
                        """INSERT INTO bookings
                           (client_id, car_id, booking_date, booking_time, status)
                           VALUES (%s, %s, %s, %s, 'waiting')""",
                        (client_id, car_id, booking_date, booking_time)
                    )
                    return True
        except Exception as e:
            print(f"Ошибка создания записи: {e}")
            return False

    async def get_user_bookings(self, user_id: int) -> list:
        """Получение активных записей пользователя (в ожидании и в работе)"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Сначала находим client_id по telegram_user_id
                await cur.execute(
                    "SELECT id FROM clients WHERE telegram_user_id = %s",
                    (user_id,)
                )
                client_row = await cur.fetchone()
                if not client_row:
                    return []

                client_id = client_row['id']

                await cur.execute(
                    """SELECT b.id, b.booking_date, b.booking_time, b.status, b.created_at,
                       c.full_name as client_name,
                       c.phone as client_phone,
                       CONCAT(cc.car_brand, ' ', cc.car_model, ' ', cc.car_number) as car_display
                       FROM bookings b
                       JOIN clients c ON b.client_id = c.id
                       LEFT JOIN client_cars cc ON b.car_id = cc.id
                       WHERE b.client_id = %s AND b.booking_date >= CURDATE() AND b.status IN ('waiting', 'in_progress')
                       ORDER BY b.booking_date, b.booking_time""",
                    (client_id,)
                )
                return await cur.fetchall()

    async def cancel_booking(self, booking_id: int, user_id: int) -> bool:
        """Отмена записи (меняем статус на cancelled). user_id - telegram_user_id"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Находим client_id по telegram_user_id
                await cur.execute(
                    "SELECT id FROM clients WHERE telegram_user_id = %s",
                    (user_id,)
                )
                client_row = await cur.fetchone()
                if not client_row:
                    return False

                await cur.execute(
                    "UPDATE bookings SET status = 'cancelled' WHERE id = %s AND client_id = %s",
                    (booking_id, client_row[0])
                )
                return cur.rowcount > 0

    async def count_user_active_bookings(self, user_id: int) -> int:
        """Подсчёт активных записей пользователя"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM clients WHERE telegram_user_id = %s",
                    (user_id,)
                )
                client_row = await cur.fetchone()
                if not client_row:
                    return 0

                await cur.execute(
                    """SELECT COUNT(*) FROM bookings
                       WHERE client_id = %s
                       AND booking_date >= CURDATE()
                       AND status IN ('waiting', 'in_progress')""",
                    (client_row[0],)
                )
                result = await cur.fetchone()
                return result[0] if result else 0

    async def get_user_phone(self, user_id: int) -> str | None:
        """Получить телефон пользователя из clients"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT phone FROM clients WHERE telegram_user_id = %s AND phone IS NOT NULL",
                    (user_id,)
                )
                result = await cur.fetchone()
                return result[0] if result and result[0] else None

    async def get_client_cars(self, user_id: int) -> list[tuple]:
        """Получить список автомобилей клиента через clients -> client_cars"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Получаем client_id по telegram_user_id
                await cur.execute(
                    "SELECT id FROM clients WHERE telegram_user_id = %s",
                    (user_id,)
                )
                client_row = await cur.fetchone()

                if not client_row:
                    return []

                client_id = client_row[0]

                # Ищем машины по client_id
                await cur.execute("""
                    SELECT DISTINCT car_brand, car_model, car_number
                    FROM client_cars
                    WHERE client_id = %s
                    AND car_brand IS NOT NULL AND car_brand != ''
                    ORDER BY car_brand, car_model
                """, (client_id,))

                return list(await cur.fetchall())

    async def get_user_phones(self, user_id: int) -> list[str]:
        """Получить телефон пользователя из clients"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT phone FROM clients WHERE telegram_user_id = %s AND phone IS NOT NULL",
                    (user_id,)
                )
                result = await cur.fetchone()
                if result and result[0]:
                    return [result[0]]
                return []

    async def get_car_history_by_user_id(self, telegram_user_id: int) -> list:
        """Получить историю работ по telegram_user_id через clients -> client_cars -> works"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Получаем client_id
                await cur.execute(
                    "SELECT id FROM clients WHERE telegram_user_id = %s",
                    (telegram_user_id,)
                )
                client_row = await cur.fetchone()

                if not client_row:
                    return []

                client_id = client_row['id']

                # Ищем работы через client_cars
                await cur.execute(
                    """SELECT w.id as work_id, w.work_date,
                              cc.car_brand, cc.car_model, cc.car_number,
                              w.description, w.amount, w.order_number, cc.mileage,
                              (SELECT COALESCE(SUM(p.part_price), 0) FROM parts p WHERE p.work_id = w.id) as parts_total
                       FROM works w
                       JOIN client_cars cc ON w.car_id = cc.id
                       WHERE cc.client_id = %s
                       ORDER BY w.work_date DESC, w.id DESC
                       LIMIT 20""",
                    (client_id,)
                )
                return await cur.fetchall()

    async def get_parts_by_work_id(self, work_id: int) -> list:
        """Получить запчасти по work_id"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT part_name, part_price FROM parts WHERE work_id = %s",
                    (work_id,)
                )
                return await cur.fetchall()

    async def get_telegraph_page(self, user_id: int) -> dict | None:
        """Получить Telegraph страницу пользователя"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT page_path, access_token FROM telegraph_pages WHERE user_id = %s",
                    (user_id,)
                )
                return await cur.fetchone()

    async def save_telegraph_page(self, user_id: int, page_path: str, access_token: str):
        """Сохранить или обновить Telegraph страницу"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO telegraph_pages (user_id, page_path, access_token)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE page_path = %s, access_token = %s""",
                    (user_id, page_path, access_token, page_path, access_token)
                )

    # --- Методы для напоминаний ---

    async def get_tomorrow_bookings_for_reminder(self) -> list:
        """Получить записи на завтра, которым ещё не отправлено напоминание"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT b.id, b.booking_date, b.booking_time, c.telegram_user_id, c.full_name
                    FROM bookings b
                    JOIN clients c ON b.client_id = c.id
                    WHERE b.booking_date = DATE_ADD(CURDATE(), INTERVAL 1 DAY)
                      AND b.status = 'waiting'
                      AND (b.reminder_sent IS NULL OR b.reminder_sent = FALSE)
                      AND c.telegram_user_id IS NOT NULL
                """)
                return await cur.fetchall()

    async def mark_reminder_sent(self, booking_id: int):
        """Отметить что напоминание накануне отправлено"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE bookings SET reminder_sent = TRUE WHERE id = %s",
                    (booking_id,)
                )

    async def get_bookings_for_1h_reminder(self) -> list:
        """Получить записи на ближайший час, которым ещё не отправлено напоминание за 1 час"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Выбираем записи на сегодня, где время записи через 1 час (+/- 30 минут)
                await cur.execute("""
                    SELECT b.id, b.booking_date, b.booking_time, c.telegram_user_id, c.full_name
                    FROM bookings b
                    JOIN clients c ON b.client_id = c.id
                    WHERE b.booking_date = CURDATE()
                      AND b.status = 'waiting'
                      AND (b.reminder_1h_sent IS NULL OR b.reminder_1h_sent = FALSE)
                      AND c.telegram_user_id IS NOT NULL
                      AND TIME(CONCAT(b.booking_time, ':00')) BETWEEN
                          ADDTIME(CURTIME(), '00:30:00') AND ADDTIME(CURTIME(), '01:30:00')
                """)
                return await cur.fetchall()

    async def mark_reminder_1h_sent(self, booking_id: int):
        """Отметить что напоминание за 1 час отправлено"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE bookings SET reminder_1h_sent = TRUE WHERE id = %s",
                    (booking_id,)
                )


db = Database()
