@echo off
REM Build a single-file Windows .exe from main.py via PyInstaller.
REM Output: dist\B_parser.exe  (ship this + config.yaml together)

setlocal
where pyinstaller >NUL 2>&1
if errorlevel 1 (
  echo Installing build deps...
  python -m pip install -q -r requirements-build.txt || goto :fail
)

rd /s /q build 2>NUL
rd /s /q dist 2>NUL
del /q B_parser.spec 2>NUL

pyinstaller ^
  --onefile ^
  --name B_parser ^
  --console ^
  --collect-data pyarrow ^
  --collect-submodules pyarrow ^
  --hidden-import openpyxl ^
  --hidden-import pandas ^
  --hidden-import requests ^
  main.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo Build OK:  dist\B_parser.exe
echo Ship together: dist\B_parser.exe  +  config.yaml
echo ============================================================
goto :eof

:fail
echo BUILD FAILED
exit /b 1
