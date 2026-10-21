@echo off
title HTE Sync Agent v3.0 — Bundle Build
color 0A

echo.
echo  ============================================
echo    HTE Sync Agent — Building Bundle
echo  ============================================
echo.

:: ── Detect Python ────────────────────────────
py --version >nul 2>&1
IF NOT ERRORLEVEL 1 ( SET PY=py ) ELSE ( SET PY=python )
echo [OK] Using: %PY%
echo.

:: ── Install dependencies ─────────────────────
echo [1/5] Installing dependencies...
%PY% -m pip install --upgrade pip --quiet
%PY% -m pip install ^
    rich ^
    watchdog ^
    pystray ^
    pillow ^
    plyer ^
    boto3 ^
    pyinstaller ^
    --quiet
echo [OK] All packages installed.
echo.

:: ── Clean previous build ─────────────────────
echo [2/5] Cleaning previous build...
IF EXIST dist        rmdir /s /q dist
IF EXIST build       rmdir /s /q build
IF EXIST HTESync.spec del /q HTESync.spec
echo [OK] Cleaned.
echo.

:: ── Create version info ───────────────────────
echo [3/5] Creating version info...
echo VSVersionInfo( > version_info.txt
echo   ffi=FixedFileInfo( >> version_info.txt
echo     filevers=(3,0,0,0), >> version_info.txt
echo     prodvers=(3,0,0,0), >> version_info.txt
echo     mask=0x3f,flags=0x0,OS=0x4, >> version_info.txt
echo     fileType=0x1,subtype=0x0,date=(0,0) >> version_info.txt
echo   ), >> version_info.txt
echo   kids=[ >> version_info.txt
echo     StringFileInfo([StringTable(u'040904B0',[ >> version_info.txt
echo       StringStruct(u'CompanyName',u'Clariant'), >> version_info.txt
echo       StringStruct(u'FileDescription',u'HTE Sync Agent'), >> version_info.txt
echo       StringStruct(u'FileVersion',u'3.0.0.0'), >> version_info.txt
echo       StringStruct(u'ProductName',u'HTE Sync Agent'), >> version_info.txt
echo       StringStruct(u'ProductVersion',u'3.0.0.0'), >> version_info.txt
echo       StringStruct(u'LegalCopyright',u'Clariant 2026'), >> version_info.txt
echo       StringStruct(u'OriginalFilename',u'HTESync.exe')])]), >> version_info.txt
echo     VarFileInfo([VarStruct(u'Translation',[0x0409,1200])]) >> version_info.txt
echo   ] >> version_info.txt
echo ) >> version_info.txt
echo [OK] version_info.txt created.
echo.

:: ── Compile bundle ────────────────────────────
echo [4/5] Compiling bundle...
echo       This may take 2-3 minutes...
echo.

%PY% -m PyInstaller ^
    --onedir ^
    --console ^
    --name "HTESync" ^
    --version-file "version_info.txt" ^
    --hidden-import "watchdog.observers.winapi" ^
    --hidden-import "plyer.platforms.win.notification" ^
    --hidden-import "pystray._win32" ^
    --hidden-import "rich.console" ^
    --hidden-import "rich.panel" ^
    --hidden-import "rich.prompt" ^
    --collect-all "rich" ^
    --collect-all "pystray" ^
    --collect-all "plyer" ^
    --noupx ^
    hte_sync.py

IF ERRORLEVEL 1 (
    echo [ERROR] Build failed.
    pause & exit /b 1
)
echo.

:: ── Verify ────────────────────────────────────
echo [5/5] Verifying...
IF EXIST dist\HTESync\HTESync.exe (
    echo.
    echo  ============================================
    echo   SUCCESS  -  Bundle ready at dist\HTESync\
    echo  ============================================
    echo.
    echo   Next step: Run install.bat as Administrator
    echo              to deploy to Program Files.
    echo.
) ELSE (
    echo [ERROR] Bundle not found. Check errors above.
)

pause
