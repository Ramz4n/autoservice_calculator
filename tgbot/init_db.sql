-- Создание базы данных для бота автосервиса
CREATE DATABASE IF NOT EXISTS autoservice_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE autoservice_bot;

-- Таблица записей
CREATE TABLE IF NOT EXISTS bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    username VARCHAR(255),
    full_name VARCHAR(255),
    phone VARCHAR(50),
    booking_date DATE NOT NULL,
    booking_time VARCHAR(10) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_booking_datetime (booking_date, booking_time),
    INDEX idx_user_id (user_id),
    INDEX idx_booking_date (booking_date)
);
