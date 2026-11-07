@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python غير مثبت أو غير مضاف إلى PATH.
    echo     ثبّت Python 3.10 أو أحدث من https://www.python.org/downloads/
    echo     ولا تنسَ تفعيل خيار "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo [1/3] إنشاء البيئة الافتراضية .venv ...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :failed
)

echo [2/3] تحديث pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo [3/3] تثبيت المتطلبات ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo [OK] تم التثبيت بنجاح. شغّل run.bat الآن.
echo.
pause
exit /b 0

:failed
echo.
echo [X] فشل التثبيت. تحقق من اتصال الإنترنت ورسالة الخطأ أعلاه.
echo.
pause
exit /b 1
