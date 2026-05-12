@echo off
chcp 65001 >NUL
setlocal enabledelayedexpansion

echo ============================================================
echo  B_parser - сборка Windows .exe через PyInstaller
echo ============================================================
echo.

REM --- Шаг 1: активация venv если есть ---
if exist venv\Scripts\activate.bat (
  echo Активирую venv\
  call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
  echo Активирую .venv\
  call .venv\Scripts\activate.bat
) else (
  echo [ВНИМАНИЕ] venv не найден. Использую системный Python.
  echo Если в системе нет нужных пакетов - создай venv:
  echo    python -m venv venv
  echo    venv\Scripts\activate
  echo    pip install -r requirements-build.txt
  echo.
)

REM --- Шаг 2: проверка какой Python будет использован ---
echo Текущий Python:
python -c "import sys; print('  ', sys.executable); print('  Python', sys.version.split()[0])"
if errorlevel 1 (
  echo [ОШИБКА] Python не найден в PATH.
  exit /b 1
)

REM Проверка версии (минимум 3.10 для pandas 2.x)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo [ОШИБКА] Нужен Python 3.10 или новее.
  echo Если у тебя venv с правильной версией - активируй его и запусти build.bat снова.
  exit /b 1
)

REM --- Шаг 3: установка зависимостей В ТЕКУЩИЙ Python ---
echo.
echo Устанавливаю/обновляю зависимости в этот Python...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements-build.txt
if errorlevel 1 (
  echo [ОШИБКА] pip install не удался.
  exit /b 1
)

REM --- Шаг 4: предполётная проверка что всё импортируется ---
echo.
echo Проверяю что все нужные пакеты импортируются из текущего Python...
python -c "import pandas, yaml, tqdm, pyarrow, openpyxl, requests, matplotlib; print('  Все пакеты OK')"
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Какой-то пакет недоступен из текущего Python.
  echo Скорее всего venv не активирован или активирован другой.
  echo.
  echo Сделай вручную:
  echo    venv\Scripts\activate
  echo    pip install -r requirements-build.txt
  echo    python -c "import pandas, yaml, tqdm, pyarrow, openpyxl, requests"
  echo и потом снова запусти build.bat.
  exit /b 1
)

REM --- Шаг 5: чистка прошлых сборок ---
echo.
echo Чищу прошлые сборки...
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist release rd /s /q release
if exist B_parser.spec del /q B_parser.spec

REM --- Шаг 6: сборка через python -m гарантирует, что PyInstaller возьмёт
REM     именно ТОТ Python, где мы только что поставили зависимости ---
echo.
echo Собираю exe (2-5 минут)...
echo.
python -m PyInstaller ^
  --onefile ^
  --name B_parser ^
  --console ^
  --noconfirm ^
  --clean ^
  --add-data "config.yaml;." ^
  --collect-all pyarrow ^
  --collect-all pandas ^
  --collect-all openpyxl ^
  --collect-all yaml ^
  --collect-all tqdm ^
  --collect-all matplotlib ^
  --hidden-import matplotlib.backends.backend_agg ^
  --hidden-import et_xmlfile ^
  --hidden-import requests ^
  --hidden-import urllib3 ^
  --hidden-import charset_normalizer ^
  --hidden-import idna ^
  --hidden-import certifi ^
  main.py
if errorlevel 1 (
  echo.
  echo ============================================================
  echo [ОШИБКА] Сборка не удалась.
  echo Открой build\B_parser\warn-B_parser.txt и пришли разработчику.
  echo ============================================================
  exit /b 1
)

REM --- Шаг 7: smoke-test собранного exe ---
echo.
echo Smoke-test собранного exe...
dist\B_parser.exe --help >NUL 2>&1
if errorlevel 1 (
  echo [ВНИМАНИЕ] exe запустился с ошибкой при --help. Проверь вручную:
  echo    dist\B_parser.exe
  echo Если всё ОК - значит ложная тревога, можно использовать.
) else (
  echo   Запуск exe прошёл успешно.
)

REM --- Шаг 8: сборка папки release/ ---
echo.
echo Собираю release\...
mkdir release
copy /Y dist\B_parser.exe release\B_parser.exe >NUL
copy /Y config.yaml release\config.yaml >NUL
if exist README.md copy /Y README.md release\README.md >NUL

for %%I in (release\B_parser.exe) do set EXESIZE=%%~zI
set /a EXEMB=!EXESIZE! / 1048576

echo.
echo ============================================================
echo  СБОРКА ГОТОВА
echo ============================================================
echo.
echo  release\B_parser.exe   ^(!EXEMB! МБ — программа^)
echo  release\config.yaml    ^(настройки^)
echo  release\README.md      ^(инструкция^)
echo.
echo  Что отдать заказчику: заархивируй папку release\ в zip
echo  и отправь. Заказчик распаковывает в одну папку и запускает .exe.
echo ============================================================
echo.
endlocal
