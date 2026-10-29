@echo off
setlocal EnableExtensions
title eNSP MCP portable uninstaller
set "DEST=%LOCALAPPDATA%\eNSP-MCP"

echo ============================================================
echo   eNSP MCP portable uninstaller
echo ============================================================
echo.
echo This will remove %DEST% from your user PATH and delete:
echo   %DEST%
echo.
echo It will NOT touch your AI client config files. Remove the
echo "ensp" MCP entry there yourself if you no longer need it.
echo.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 exit /b 0

tasklist /FI "IMAGENAME eq eNSP-MCP.exe" 2>nul | find /I "eNSP-MCP.exe" >nul
if not errorlevel 1 (
    echo.
    echo [ERROR] eNSP-MCP.exe is still running.
    echo Close the AI client or end eNSP-MCP.exe in Task Manager, then run this again.
    echo.
    pause
    exit /b 1
)

if exist "%~dp0install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -RemovePath -Dir "%DEST%"
) else (
    echo [WARN] install.ps1 not found; remove %DEST% from PATH manually.
)

if exist "%DEST%" rmdir /S /Q "%DEST%"
if exist "%DEST%" (
    echo [ERROR] Could not delete %DEST%
) else (
    echo [OK] Removed %DEST%
)
echo.
echo Remember to delete the "ensp" MCP entry in your AI client.
echo.
pause
endlocal
exit /b 0
