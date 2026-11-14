@echo off
setlocal
cd /d "%~dp0.."

rem Builds the Windows installer (Next -> Next -> Finish) with Inno Setup 6.
rem The application version is read from app\config.py (VERSION) - the same
rem source build.bat uses - and passed to the .iss script as /D defines, so
rem the version is never written twice.
rem
rem The executable and the README are taken from dist\ (built by build.bat);
rem this script never builds them itself.

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [X] لم يتم العثور على البيئة الافتراضية .venv
    echo     شغّل setup.bat أولاً.
    exit /b 1
)

set "ISCC="
if defined ISCC_PATH (
    set "ISCC=%ISCC_PATH%"
) else if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else (
    set "ISCC=ISCC.exe"
)

echo [1/6] قراءة رقم الإصدار من app\config.py ...
set "APPVER="
"%PY%" -c "print('VER=' + __import__('app.config',fromlist=['VERSION']).VERSION)" > "%TEMP%\mediaart-version.txt"
for /f "usebackq tokens=2 delims==" %%v in ("%TEMP%\mediaart-version.txt") do set "APPVER=%%v"
del "%TEMP%\mediaart-version.txt" >nul 2>nul
if not defined APPVER (
    echo [X] تعذّر قراءة رقم الإصدار من app\config.py
    exit /b 1
)
set "EXENAME=MediaArtAutoSync-v%APPVER%.exe"
set "SETUPNAME=MediaArtAutoSync-Setup-%APPVER%"
echo     الإصدار: %APPVER%

echo [2/6] بوابة الإصدار: تشغيل الاختبارات ...
"%PY%" -m pytest -q
if errorlevel 1 (
    echo.
    echo [X] الاختبارات فشلت - تم إيقاف الإصدار.
    exit /b 1
)

echo [3/6] التحقق من مخرجات البناء ...
if not exist "dist\%EXENAME%" (
    echo [X] لم يُنتَج dist\%EXENAME% - شغّل build.bat أولاً
    exit /b 1
)
if not exist "dist\MediaArtAutoSync-v%APPVER%-portable.zip" (
    echo [X] لم يُنتَج حزمة Portable - شغّل build_release.bat أولاً
    exit /b 1
)

echo [4/6] بناء المعالج (ISCC) ...
"%ISCC%" /DAppVersion=%APPVER% /DAppExe=%EXENAME% /DOutputBase=%SETUPNAME% "installer\mediaart.iss"
if errorlevel 1 (
    echo.
    echo [X] فشل بناء المعالج.
    exit /b 1
)

echo [5/6] التحقق من المخرج ...
set "SETUP=installer\Output\%SETUPNAME%.exe"
if not exist "%SETUP%" (
    echo [X] لم يُنتَج %SETUP%
    exit /b 1
)

echo [6/6] حساب البصمة ...
call :hash "%SETUP%"
if not defined HASH goto :failed

for %%i in ("%SETUP%") do set "SETUPSIZE=%%~zi"

echo.
echo [OK] تم بناء معالج التثبيت:
echo     %SETUP%   (%SETUPSIZE% بايت)
echo     SHA256: %HASH%
echo.
exit /b 0

rem SHA256 of one file into %HASH% (empty on failure).
:hash
set "HASH="
"%PY%" -c "print(__import__('hashlib').sha256(open(__import__('sys').argv[1],'rb').read()).hexdigest())" "%~1" > "%TEMP%\mediaart-hash.txt"
for /f "usebackq delims=" %%h in ("%TEMP%\mediaart-hash.txt") do set "HASH=%%h"
del "%TEMP%\mediaart-hash.txt" >nul 2>nul
exit /b 0

:failed
echo.
echo [X] فشل بناء معالج التثبيت. راجع الرسائل أعلاه.
exit /b 1
