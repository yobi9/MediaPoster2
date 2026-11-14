@echo off
setlocal
cd /d "%~dp0"

rem Builds ONE executable: the GUI, with the CLI mode (--cli) inside it.
rem There is no separate CLI release to build, keep, or publish.
rem
rem The output name is fixed by MediaArtAutoSync.spec (MediaArtAutoSync.exe),
rem so the version is appended afterwards by renaming the built file.
rem
rem The version comes from ONE source: app\config.py (VERSION).
rem --clean removes only the per-project cache (build\MediaArtAutoSync), not build\ as a whole.
rem A single build also removes the old shared-workpath problem: two
rem BUILD_MODE values no longer write into the same build directory.

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

echo [1/5] قراءة رقم الإصدار من app\config.py ...
set "APPVER="
"%PY%" -c "print('VER=' + __import__('app.config',fromlist=['VERSION']).VERSION)" > "%TEMP%\mediaart-version.txt"
for /f "usebackq tokens=2 delims==" %%v in ("%TEMP%\mediaart-version.txt") do set "APPVER=%%v"
del "%TEMP%\mediaart-version.txt" >nul 2>nul
if not defined APPVER (
    echo [X] تعذّر قراءة رقم الإصدار من app\config.py
    exit /b 1
)
echo     الإصدار: %APPVER%

echo [2/5] تشغيل الاختبارات (بوابة قبل البناء) ...
"%PY%" -m pytest -q
if errorlevel 1 (
    echo.
    echo [X] الاختبارات فشلت - تم إيقاف البناء.
    exit /b 1
)

echo [3/5] تنظيف dist\*.exe ...
del /q dist\*.exe 2>nul

echo [4/5] بناء الملف التنفيذي (واجهة رسومية + --cli مدمج) ...
set "BUILD_MODE=gui"
"%PY%" -m PyInstaller --noconfirm --clean MediaArtAutoSync.spec
if errorlevel 1 goto :failed

echo [5/5] تسمية الملف التنفيذي بالإصدار ...
if not exist "dist\MediaArtAutoSync.exe" (
    echo [X] لم يُنتَج dist\MediaArtAutoSync.exe
    goto :failed
)
move /y "dist\MediaArtAutoSync.exe" "dist\MediaArtAutoSync-v%APPVER%.exe" >nul
if errorlevel 1 goto :failed

echo.
echo [OK] تم البناء بنجاح:
echo     dist\MediaArtAutoSync-v%APPVER%.exe   (واجهة رسومية، و--cli داخلها)
echo.
exit /b 0

:failed
echo.
echo [X] فشل البناء. راجع الرسائل أعلاه.
exit /b 1
