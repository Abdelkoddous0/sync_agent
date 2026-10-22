@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
where py >nul 2>&1
if errorlevel 1 (set "PY=python") else (set "PY=py -3")
%PY% -m venv .venv-build
if errorlevel 1 exit /b 1
set "BPY=%CD%\.venv-build\Scripts\python.exe"
rem requirements-dev.txt includes requirements.txt plus test dependencies.
"%BPY%" -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1
"%BPY%" -m pytest tests -q
if errorlevel 1 exit /b 1
"%BPY%" -m compileall -q main.py aws_cli.py ui.py installer.py
if errorlevel 1 exit /b 1
"%BPY%" -m PyInstaller --noconfirm --clean --onedir --console --noupx --name SyncAgent --hidden-import watchdog.observers.winapi --hidden-import pystray._win32 --hidden-import plyer.platforms.win.notification --collect-all rich --collect-all pystray --collect-all plyer --add-data "ensure_aws_cli.ps1;." --add-data "install.ps1;." --add-data "uninstall.ps1;." main.py
if errorlevel 1 exit /b 1
if not exist "dist\SyncAgent\SyncAgent.exe" exit /b 1
for %%F in (install.ps1 uninstall.ps1 ensure_aws_cli.ps1 install.bat uninstall.bat) do (
    copy /y "%%F" "dist\SyncAgent\%%F" >nul
    if errorlevel 1 exit /b 1
)
rem One-file installer: embeds the complete bundle, installs it, then runs setup.
"%BPY%" -m PyInstaller --noconfirm --clean --onefile --console --noupx --name SyncAgentSetup --collect-all rich --add-data "dist\SyncAgent;payload" installer.py
if errorlevel 1 exit /b 1
if not exist "dist\SyncAgentSetup.exe" exit /b 1
echo Build ready: dist\SyncAgent\SyncAgent.exe
echo Installer ready: dist\SyncAgentSetup.exe  (single file; double-click to install and configure)
exit /b 0
