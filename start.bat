@echo off
title AutoService Launcher

start "Backend" cmd /k "cd /d C:\Users\RAMZ\PycharmProjects\Alexan\backend && call ..\.venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak >nul

start "Flutter" cmd /k "cd /d C:\Users\RAMZ\PycharmProjects\Alexan\app_mobile && C:\Users\RAMZ\PycharmProjects\flutter\bin\flutter.bat run"
