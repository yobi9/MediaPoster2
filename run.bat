@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [X] لم يتم العثور على البيئة الافتراضية .venv
    echo     شغّل setup.bat أولاً لتثبيت المتطلبات.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open when launched by double-click and something failed.
if not "%EXIT_CODE%"=="0" if "%~1"=="" pause
exit /b %EXIT_CODE%
