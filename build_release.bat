@echo off
setlocal
cd /d "%~dp0"

rem Release pipeline for the Portable distribution:
rem   release gate (pytest) -> build (call build.bat) -> assemble the Portable
rem   folder -> verify the SHA256 of the copied exe -> zip -> SHA256SUMS.txt
rem
rem build.bat stays the single source of truth for the build itself; this
rem script never duplicates the build steps.
rem
rem The version is read from app\config.py (VERSION) - the same constant and
rem the same method build.bat uses, so both scripts agree on one version.
rem
rem No backticks and no for /f ('...') command capture: both are unreliable
rem in this environment. Command output is always bridged through a
rem temporary file in %TEMP% and read with for /f "usebackq".

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [X] لم يتم العثور على البيئة الافتراضية .venv
    echo     شغّل setup.bat أولاً.
    exit /b 1
)

echo [1/9] قراءة رقم الإصدار من app\config.py ...
set "APPVER="
"%PY%" -c "print('VER=' + __import__('app.config',fromlist=['VERSION']).VERSION)" > "%TEMP%\mediaart-version.txt"
for /f "usebackq tokens=2 delims==" %%v in ("%TEMP%\mediaart-version.txt") do set "APPVER=%%v"
del "%TEMP%\mediaart-version.txt" >nul 2>nul
if not defined APPVER (
    echo [X] تعذّر قراءة رقم الإصدار من app\config.py
    exit /b 1
)
set "EXENAME=MediaArtAutoSync-v%APPVER%.exe"
set "PORTABLE_EXE=MediaArtAutoSync-v%APPVER%-portable.exe"
set "PORTABLE_NAME=MediaArtAutoSync-v%APPVER%"
set "PORTABLE_DIR=dist\portable\%PORTABLE_NAME%"
set "ZIPNAME=MediaArtAutoSync-v%APPVER%-portable.zip"
echo     الإصدار: %APPVER%

echo [2/9] بوابة الإصدار: تشغيل الاختبارات ...
"%PY%" -m pytest -q
if errorlevel 1 (
    echo.
    echo [X] الاختبارات فشلت - تم إيقاف الإصدار.
    exit /b 1
)

echo [3/9] بناء الملف التنفيذي (build.bat) ...
call build.bat
if errorlevel 1 (
    echo.
    echo [X] فشل البناء - تم إيقاف الإصدار.
    exit /b 1
)

echo [4/9] التحقق من مخرجات البناء ...
if not exist "dist\%EXENAME%" (
    echo [X] لم يُنتَج dist\%EXENAME%
    exit /b 1
)
if exist "dist\MediaArtAutoSync-cli.exe" (
    echo [X] يوجد dist\MediaArtAutoSync-cli.exe - لا إصدار CLI منفصل في v1.0.1
    exit /b 1
)

echo [5/9] تجهيز مجلد Portable ...
if exist "%PORTABLE_DIR%" rmdir /s /q "%PORTABLE_DIR%"
mkdir "%PORTABLE_DIR%"
if errorlevel 1 (
    echo [X] تعذّر إنشاء %PORTABLE_DIR%
    exit /b 1
)

echo [6/9] نسخ الملفات إلى مجلد Portable ...
copy /y "dist\%EXENAME%" "%PORTABLE_DIR%\%PORTABLE_EXE%" >nul
if errorlevel 1 goto :failed
copy /y "README.md" "%PORTABLE_DIR%\" >nul
if errorlevel 1 goto :failed

echo [7/9] التحقق من تطابق البصمة (المصدر مقابل Portable) ...
call :hash "dist\%EXENAME%"
set "H_SRC=%HASH%"
call :hash "%PORTABLE_DIR%\%PORTABLE_EXE%"
set "H_PORT=%HASH%"
if not defined H_SRC goto :failed
if not defined H_PORT goto :failed
if not "%H_SRC%"=="%H_PORT%" (
    echo [X] بصمة الـexe لا تطابق نسخة Portable
    exit /b 1
)
echo     البصمة: %H_SRC%

echo [8/9] ضغط Portable إلى zip ...
powershell -NoProfile -Command "Compress-Archive -Path '%CD%\%PORTABLE_DIR%' -DestinationPath '%CD%\dist\%ZIPNAME%' -Force"
if errorlevel 1 goto :failed
if not exist "dist\%ZIPNAME%" (
    echo [X] لم يُنتَج dist\%ZIPNAME%
    exit /b 1
)

echo [9/9] كتابة بصمات SHA256 ...
call :hash "dist\%ZIPNAME%"
set "H_ZIP=%HASH%"
if not defined H_ZIP goto :failed
>"dist\SHA256SUMS.txt" echo %H_SRC%  %EXENAME%
>>"dist\SHA256SUMS.txt" echo %H_ZIP%  %ZIPNAME%
>>"dist\SHA256SUMS.txt" echo %H_PORT%  portable\%PORTABLE_NAME%\%PORTABLE_EXE%

set "EXESIZE=0"
for %%i in ("dist\%EXENAME%") do set "EXESIZE=%%~zi"
set "ZIPSIZE=0"
for %%i in ("dist\%ZIPNAME%") do set "ZIPSIZE=%%~zi"
set "FOLDERSIZE=0"
for %%f in ("%PORTABLE_DIR%\*") do set /a FOLDERSIZE+=%%~zf

echo.
echo [OK] تم تجهيز نسخة Portable:
echo     dist\%EXENAME%            (%EXESIZE% بايت)
echo     %PORTABLE_DIR%\           (%FOLDERSIZE% بايت)
echo     dist\%ZIPNAME%            (%ZIPSIZE% بايت)
echo     dist\SHA256SUMS.txt
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
echo [X] فشل تجهيز نسخة Portable. راجع الرسائل أعلاه.
exit /b 1
