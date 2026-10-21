@echo off
title HTE Sync Agent v3.3 — Build
color 0A

py --version >nul 2>&1
IF NOT ERRORLEVEL 1 ( SET PY=py ) ELSE ( SET PY=python )

echo [1/4] Installing packages...
%PY% -m pip install --upgrade pip --quiet
%PY% -m pip install -r requirements.txt --quiet
echo [OK] Done.

echo [2/4] Cleaning...
IF EXIST dist        rmdir /s /q dist
IF EXIST build       rmdir /s /q build
IF EXIST HTESync.spec del /q HTESync.spec

echo [3/4] Compiling...
%PY% -m PyInstaller ^
    --onedir ^
    --console ^
    --name "HTESync" ^
    --hidden-import "watchdog.observers.winapi" ^
    --hidden-import "plyer.platforms.win.notification" ^
    --hidden-import "pystray._win32" ^
    --collect-all "rich" ^
    --collect-all "pystray" ^
    --collect-all "plyer" ^
    --noupx ^
    main.py

echo [4/4] Checking...
IF EXIST dist\HTESync\HTESync.exe (
    echo.
    echo  SUCCESS - dist\HTESync\HTESync.exe is ready
    echo  Run install.bat as Admin to deploy.
) ELSE (
    echo [ERROR] Build failed.
)
pause
