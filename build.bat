@echo off
setlocal

cd /d "%~dp0"

set "OUT=dist\autoservice_calculator"
set "BACKUP=%TEMP%\autoservice_build_backup"

rem PyInstaller wipes %OUT% on every build, but main\ and .env only
rem live inside %OUT% (not tracked in the project root) -- stash them first.
if exist "%BACKUP%" rmdir /S /Q "%BACKUP%"
mkdir "%BACKUP%"
if exist "%OUT%\main" xcopy /E /I /Y "%OUT%\main" "%BACKUP%\main" >nul
if exist "%OUT%\.env" copy /Y "%OUT%\.env" "%BACKUP%\.env" >nul

echo === Building autoservice_calculator (onedir, via .spec) ===
call .venv\Scripts\activate
pyinstaller autoservice_calculator.spec --noconfirm
if errorlevel 1 (
    echo.
    echo === BUILD FAILED ===
    exit /b 1
)

echo === Restoring runtime files next to the exe ===
if exist config (
    xcopy /E /I /Y config "%OUT%\config" >nul
)
if exist license.key (
    copy /Y license.key "%OUT%\license.key" >nul
)
if exist license_cache.json (
    copy /Y license_cache.json "%OUT%\license_cache.json" >nul
)
if exist "%BACKUP%\main" (
    xcopy /E /I /Y "%BACKUP%\main" "%OUT%\main" >nul
)
if exist "%BACKUP%\.env" (
    copy /Y "%BACKUP%\.env" "%OUT%\.env" >nul
)

echo.
echo === Done. Exe: %OUT%\autoservice_calculator.exe ===
echo === Ship the whole "%OUT%" folder, not just the exe. ===

endlocal
