# -*- coding: utf-8 -*-
"""
Схема базы данных MariaDB для автосервиса

Содержит SQL-запросы для создания таблиц и индексов.
"""

# SQL для создания таблиц
TABLES = {
    'workers': '''
        CREATE TABLE IF NOT EXISTS workers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    ''',

    'car_brands': '''
        CREATE TABLE IF NOT EXISTS car_brands (
            id INT AUTO_INCREMENT PRIMARY KEY,
            brand_name VARCHAR(255) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    ''',

    'car_models': '''
        CREATE TABLE IF NOT EXISTS car_models (
            id INT AUTO_INCREMENT PRIMARY KEY,
            brand_id INT NOT NULL,
            model_name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (brand_id) REFERENCES car_brands(id) ON DELETE CASCADE,
            UNIQUE KEY unique_brand_model (brand_id, model_name)
        ) ENGINE=InnoDB
    ''',

    'works': '''
        CREATE TABLE IF NOT EXISTS works (
            id INT AUTO_INCREMENT PRIMARY KEY,
            worker_id INT NOT NULL,
            car_id INT,
            booking_id INT,
            description TEXT NOT NULL,
            amount DECIMAL(12,2) NOT NULL,
            work_date DATE NOT NULL,
            mileage INT DEFAULT NULL,
            order_number VARCHAR(20) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    ''',

    'expenses': '''
        CREATE TABLE IF NOT EXISTS expenses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            description TEXT NOT NULL,
            amount DECIMAL(12,2) NOT NULL,
            expense_date DATE NOT NULL,
            category VARCHAR(255) NOT NULL,
            is_income TINYINT(1) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    ''',

    'parts': '''
        CREATE TABLE IF NOT EXISTS parts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            work_id INT NOT NULL,
            part_name TEXT NOT NULL,
            part_price DECIMAL(12,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    ''',

    'keywords': '''
        CREATE TABLE IF NOT EXISTS keywords (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL UNIQUE,
            interval_km_min INT DEFAULT NULL,
            interval_km_max INT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    ''',

    'clients': '''
        CREATE TABLE IF NOT EXISTS clients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            telegram_user_id BIGINT UNIQUE,
            tg_username VARCHAR(255),
            full_name VARCHAR(255),
            phone VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_phone (phone)
        ) ENGINE=InnoDB
    ''',

    'bookings': '''
        CREATE TABLE IF NOT EXISTS bookings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT,
            car_id INT,
            booking_date DATE NOT NULL,
            booking_time VARCHAR(10) NOT NULL,
            status VARCHAR(20) DEFAULT 'waiting',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_booking_datetime (booking_date, booking_time)
        ) ENGINE=InnoDB
    ''',

    'client_cars': '''
        CREATE TABLE IF NOT EXISTS client_cars (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT,
            car_brand VARCHAR(100),
            car_model VARCHAR(100),
            car_number VARCHAR(20),
            vin VARCHAR(20),
            mileage VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_car_number (car_number)
        ) ENGINE=InnoDB
    ''',

    'telegraph_pages': '''
        CREATE TABLE IF NOT EXISTS telegraph_pages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL UNIQUE,
            page_path VARCHAR(255),
            access_token VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    ''',

    'warehouse_parts': '''
        CREATE TABLE IF NOT EXISTS warehouse_parts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            car_id INT,
            part_name TEXT NOT NULL,
            quantity INT DEFAULT 1,
            price DECIMAL(12,2),
            status VARCHAR(30) DEFAULT 'в пути',
            is_paid TINYINT(1) DEFAULT 0,
            order_date DATE NOT NULL,
            received_date DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_warehouse_car_id (car_id),
            INDEX idx_warehouse_status (status),
            FOREIGN KEY (car_id) REFERENCES client_cars(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    ''',

    'users': '''
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(64) NOT NULL,
            salt VARCHAR(64) NOT NULL,
            full_name VARCHAR(255) DEFAULT '',
            role ENUM('admin', 'user') DEFAULT 'user',
            is_active TINYINT(1) DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    ''',

    'subscriptions': '''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            client_id       INT NOT NULL,
            plan            ENUM('basic','premium','vip') NOT NULL,
            status          ENUM('active','expired','pending') DEFAULT 'pending',
            started_at      DATETIME,
            expires_at      DATETIME,
            payment_id      VARCHAR(100) UNIQUE,
            amount          DECIMAL(10,2),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        ) ENGINE=InnoDB
    ''',
}

# Индексы для быстрого поиска
INDEXES = [
    "CREATE INDEX idx_works_work_date ON works(work_date)",
    "CREATE INDEX idx_works_car_id ON works(car_id)",
    "CREATE INDEX idx_bookings_booking_date ON bookings(booking_date)",
    "CREATE INDEX idx_bookings_status ON bookings(status)",
    "CREATE INDEX idx_bookings_client_id ON bookings(client_id)",
    "CREATE INDEX idx_client_cars_client_id ON client_cars(client_id)",
]

# Миграции для существующей БД
MIGRATIONS = [
    # Добавление полей интервалов ТО в keywords
    "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS interval_km_min INT DEFAULT NULL",
    "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS interval_km_max INT DEFAULT NULL",
    # Добавление пробега на момент работы в works
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS mileage INT DEFAULT NULL",
    # Хранение отдельных позиций работы (название+цена) для корректного восстановления при редактировании
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS items_json TEXT DEFAULT NULL",
    # Отметка "уже оплачено" для складских позиций (например, платное хранение шин) --
    # чтобы при выдаче со склада в работу сумма не добавлялась в счёт повторно
    "ALTER TABLE warehouse_parts ADD COLUMN IF NOT EXISTS is_paid TINYINT(1) DEFAULT 0",
    # Привязка складской позиции к конкретному наряду (works.id), в который она была установлена --
    # чтобы из "Склада" переходить именно к той работе, а не к последней записи машины
    "ALTER TABLE warehouse_parts ADD COLUMN IF NOT EXISTS work_id INT DEFAULT NULL",
    "ALTER TABLE warehouse_parts ADD INDEX IF NOT EXISTS idx_warehouse_work_id (work_id)",
    # Дата фактического завершения наряда (когда запись переведена в статус "завершён") --
    # зарплата мастера в отчётах считается по этой дате, а не по дате создания наряда
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS completed_at DATE DEFAULT NULL",
]
