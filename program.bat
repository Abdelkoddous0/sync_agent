@echo off
rem Compatibility entry point: there is only one build implementation.
call "%~dp0build.bat" %*
exit /b %errorlevel%
