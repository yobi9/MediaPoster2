@echo off
setlocal
cd /d "%~dp0"

rem Builds both executables from one spec file:
rem   BUILD_MODE=gui -> dist\MediaArtAutoSync.exe      (windowed)
rem   BUILD_MODE=cli -> dist\MediaArtAutoSync-cli.exe  (console)

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [X] لم يتم العثور على البيئة الافتراضية .venv
    echo     شغّل setup.bat أولاً.
    exit /b 1
)

"%PY%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [X] PyInstaller غير مثبّت. ثبّته بالأمر:
    echo     .venv\Scripts\python.exe -m pip install pyinstaller
    exit /b 1
)

echo [1/2] بناء نسخة الواجهة (GUI) - MediaArtAutoSync.exe ...
set "BUILD_MODE=gui"
"%PY%" -m PyInstaller --noconfirm --clean MediaArtAutoSync.spec
if errorlevel 1 goto :failed

echo [2/2] بناء نسخة سطر الأوامر (CLI) - MediaArtAutoSync-cli.exe ...
set "BUILD_MODE=cli"
"%PY%" -m PyInstaller --noconfirm --clean MediaArtAutoSync.spec
if errorlevel 1 goto :failed

echo.
echo [OK] تم البناء بنجاح:
echo     dist\MediaArtAutoSync.exe       (واجهة رسومية)
echo     dist\MediaArtAutoSync-cli.exe   (سطر أوامر - للأتمتة و NAS)
echo.
exit /b 0

:failed
echo.
echo [X] فشل البناء. راجع الرسائل أعلاه.
exit /b 1
