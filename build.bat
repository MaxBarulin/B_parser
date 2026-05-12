@echo off
chcp 65001 >NUL
setlocal enabledelayedexpansion

echo ============================================================
echo  B_parser - сборка Windows .exe через PyInstaller
echo ============================================================
echo.

REM --- Шаг 1: Python в PATH ---
where python >NUL 2>&1
if errorlevel 1 (
  echo [ОШИБКА] Python не найден в PATH.
  echo Скачай Python 3.10+ с https://python.org и поставь галочку
  echo "Add Python to PATH" при установке.
  exit /b 1
)

REM --- Шаг 2: активация venv если есть ---
if exist venv\Scripts\activate.bat (
  echo Активирую venv\
  call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
  echo Активирую .venv\
  call .venv\Scripts\activate.bat
)

REM --- Шаг 3: установка зависимостей ---
echo.
echo Устанавливаю/обновляю зависимости...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements-build.txt
if errorlevel 1 (
  echo [ОШИБКА] Не удалось установить зависимости.
  echo Открой требования: requirements-build.txt
  exit /b 1
)

REM --- Шаг 4: чистка прошлых сборок ---
echo.
echo Чищу прошлые сборки...
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist release rd /s /q release
if exist B_parser.spec del /q B_parser.spec

REM --- Шаг 5: сборка ---
echo.
echo Собираю exe (2-5 минут, зависит от диска)...
echo.
pyinstaller ^
  --onefile ^
  --name B_parser ^
  --console ^
  --noconfirm ^
  --clean ^
  --collect-all pyarrow ^
  --collect-data openpyxl ^
  --hidden-import et_xmlfile ^
  --hidden-import openpyxl ^
  --hidden-import openpyxl.cell._writer ^
  --hidden-import yaml ^
  --hidden-import pandas ^
  --hidden-import requests ^
  --hidden-import tqdm ^
  --hidden-import urllib3 ^
  --hidden-import charset_normalizer ^
  --hidden-import idna ^
  --hidden-import certifi ^
  main.py
if errorlevel 1 (
  echo.
  echo ============================================================
  echo [ОШИБКА] Сборка не удалась.
  echo Открой папку build\B_parser\warn-B_parser.txt — там подсказки
  echo о ненайденных модулях. Допиши их в build.bat через --hidden-import.
  echo ============================================================
  exit /b 1
)

REM --- Шаг 6: сборка папки release/ ---
echo.
echo Собираю release\ для отправки заказчику...
mkdir release
copy /Y dist\B_parser.exe release\B_parser.exe >NUL
copy /Y config.yaml release\config.yaml >NUL
if exist README.md copy /Y README.md release\README.md >NUL

REM --- Финал ---
for %%I in (release\B_parser.exe) do set EXESIZE=%%~zI
set /a EXEMB=!EXESIZE! / 1048576

echo.
echo ============================================================
echo  СБОРКА ГОТОВА
echo ============================================================
echo.
echo  Файлы для отправки заказчику в папке: release\
echo.
echo    release\B_parser.exe      ^(!EXEMB! МБ — программа^)
echo    release\config.yaml       ^(настройки^)
echo    release\README.md         ^(инструкция^)
echo.
echo  Заархивируй папку release\ в zip и отправь заказчику.
echo  Заказчику нужно распаковать всё в одну папку и запустить .exe.
echo ============================================================
echo.
endlocal
