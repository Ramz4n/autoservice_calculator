@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "SRC=dist\autoservice_calculator"
set "STAGE=%TEMP%\autoservice_release_stage"
set "OUT=release"

rem --- Поднимаем patch-версию в VERSION (1.0.1 -> 1.0.2), чтобы не забыть
rem     это сделать руками -- иначе свежая сборка продолжает считать себя
rem     старой версией и приложение зацикливается на предложении обновиться.
if not exist VERSION (
    echo 1.0.0> VERSION
)
set /p CURVER=<VERSION
for /f "tokens=1,2,3 delims=." %%a in ("%CURVER%") do (
    set "VMAJOR=%%a"
    set "VMINOR=%%b"
    set "VPATCH=%%c"
)
set /a VPATCH=%VPATCH%+1
set "NEWVER=%VMAJOR%.%VMINOR%.%VPATCH%"
echo %NEWVER%> VERSION
echo === Версия поднята: %CURVER% -^> %NEWVER% ===

rem --- Пересобираем -- build.bat заодно скопирует уже поднятый VERSION
rem     в dist\, иначе в архиве могла бы остаться версия от прошлой сборки.
call build.bat
if errorlevel 1 (
    echo.
    echo === СБОРКА НЕ УДАЛАСЬ ===
    exit /b 1
)

if not exist "%SRC%\autoservice_calculator.exe" (
    echo.
    echo === "%SRC%" не найдена после сборки ===
    exit /b 1
)

echo === Готовлю чистую копию для релиза (без .env, лицензии разработчика и его локальных тестовых бэкапов) ===
if exist "%STAGE%" rmdir /S /Q "%STAGE%"
robocopy "%SRC%" "%STAGE%" /E /XD Backup /XF .env license.key license_cache.json >nul

rem --- settings.json тащит personal backup_folder разработчика (путь на его
rem     диске к синхронизируемой папке) -- если не стереть, каждый клиент
rem     получит его как якобы "свою" облачную папку и бэкап будет падать
rem     с "Отказано в доступе". Обнуляем перед архивацией.
rem     Пишем через .NET File::WriteAllText с UTF8Encoding($false) -- обычный
rem     Set-Content -Encoding UTF8 в Windows PowerShell 5.1 добавляет BOM, а
rem     приложение читает settings.json как plain utf-8 (open(..., encoding=
rem     'utf-8')) и на BOM тихо теряет все настройки (json.JSONDecodeError
rem     ловится и подставляется дефолт).
if exist "%STAGE%\config\settings.json" (
    powershell -NoProfile -Command ^
        "$p = '%STAGE%\config\settings.json'; $j = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json; $j.backup_folder = ''; $j.PSObject.Properties.Remove('backup_last'); $text = $j | ConvertTo-Json -Depth 10; [System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($false)))"
)

if not exist "%OUT%" mkdir "%OUT%"
set "ZIP=%OUT%\autoservice_calculator_v%NEWVER%.zip"
if exist "%ZIP%" del /Q "%ZIP%"

echo === Архивирую в %ZIP% ===
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ZIP%'"
if errorlevel 1 (
    echo.
    echo === АРХИВАЦИЯ НЕ УДАЛАСЬ ===
    exit /b 1
)

rmdir /S /Q "%STAGE%"

echo.
echo === Готово: %ZIP% ===
echo === Проверь перед заливкой на GitHub: unzip и убедись, что там НЕТ .env и license.key ===
echo.
echo === На GitHub -^> Releases -^> Draft a new release: ===
echo ===   тег:   v%NEWVER%           (или v%NEWVER%-force для обязательного) ===
echo ===   asset: %ZIP% ===

endlocal
