@echo off
rem Builds dist\SyncAgentSetup.exe (single-file installer) and dist\SyncAgent\ (application folder).
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
set "ROOT=%CD%"
rem Prefer the CI-tested Python 3.12, then any Python 3 from the launcher, then PATH.
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "" >nul 2>&1
    if not errorlevel 1 (set "PY=py -3.12") else (set "PY=py -3")
)
if not defined PY set "PY=python"
%PY% -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 and sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
    echo Build requires 64-bit Python 3.10 or newer ^(3.12 recommended^): https://www.python.org/downloads/windows/
    exit /b 1
)
%PY% -m venv .venv-build
if errorlevel 1 exit /b 1
set "BPY=%ROOT%\.venv-build\Scripts\python.exe"
rem requirements-dev.txt includes requirements.txt plus test and packaging tools.
"%BPY%" -m pip install --disable-pip-version-check -r requirements-dev.txt
if errorlevel 1 exit /b 1
"%BPY%" -m pytest tests -q
if errorlevel 1 exit /b 1
"%BPY%" -m compileall -q src
if errorlevel 1 exit /b 1
rem Application icon (exe, Start Menu shortcut, Installed apps) drawn by src\icons.py.
if not exist build mkdir build
"%BPY%" src\icons.py build\SyncAgent.ico
if errorlevel 1 exit /b 1
rem Generated .spec files go to build\ so the repository root stays clean.
"%BPY%" -m PyInstaller --noconfirm --clean --onedir --console --noupx --specpath build --paths "%ROOT%\src" --icon "%ROOT%\build\SyncAgent.ico" --name SyncAgent --hidden-import watchdog.observers.winapi --hidden-import pystray._win32 --hidden-import plyer.platforms.win.notification --collect-all rich --collect-all pystray --collect-all plyer --add-data "%ROOT%\scripts\ensure_aws_cli.ps1;." --add-data "%ROOT%\scripts\install.ps1;." --add-data "%ROOT%\scripts\uninstall.ps1;." "%ROOT%\src\main.py"
if errorlevel 1 exit /b 1
if not exist "dist\SyncAgent\SyncAgent.exe" exit /b 1
rem Optional code signing: set SYNC_AGENT_SIGN_PFX (+ SYNC_AGENT_SIGN_PASSWORD) or SYNC_AGENT_SIGN_THUMBPRINT.
set "SIGN="
if defined SYNC_AGENT_SIGN_PFX set "SIGN=-PfxPath "%SYNC_AGENT_SIGN_PFX%""
if defined SYNC_AGENT_SIGN_THUMBPRINT set "SIGN=-Thumbprint %SYNC_AGENT_SIGN_THUMBPRINT%"
set "SIGNPS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\sign.ps1""
rem Sign the application before it is embedded in the installer.
if defined SIGN (
    %SIGNPS% %SIGN% %SYNC_AGENT_SIGN_EXTRA% -Path "dist\SyncAgent\SyncAgent.exe"
    if errorlevel 1 exit /b 1
) else (
    echo Code signing skipped: no certificate configured ^(see docs\development.md^).
)
for %%F in (install.ps1 uninstall.ps1 ensure_aws_cli.ps1 install.bat uninstall.bat) do (
    copy /y "scripts\%%F" "dist\SyncAgent\%%F" >nul
    if errorlevel 1 exit /b 1
)
rem One-file installer: embeds the complete bundle, installs it, then runs setup.
"%BPY%" -m PyInstaller --noconfirm --clean --onefile --console --noupx --specpath build --paths "%ROOT%\src" --icon "%ROOT%\build\SyncAgent.ico" --name SyncAgentSetup --collect-all rich --add-data "%ROOT%\dist\SyncAgent;payload" "%ROOT%\src\installer.py"
if errorlevel 1 exit /b 1
if not exist "dist\SyncAgentSetup.exe" exit /b 1
if defined SIGN (
    %SIGNPS% %SIGN% %SYNC_AGENT_SIGN_EXTRA% -Path "dist\SyncAgentSetup.exe"
    if errorlevel 1 exit /b 1
)
rem Ship the one-command acceptance test beside the installer.
copy /y "scripts\acceptance-test.ps1" "dist\acceptance-test.ps1" >nul
if errorlevel 1 exit /b 1
echo Build ready: dist\SyncAgent\SyncAgent.exe
echo Installer ready: dist\SyncAgentSetup.exe  (single file; double-click to install and configure)
exit /b 0
