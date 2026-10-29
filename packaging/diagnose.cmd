@echo off
setlocal EnableExtensions
title eNSP MCP self check
set "EXE=%~dp0eNSP-MCP.exe"
if not exist "%EXE%" set "EXE=%LOCALAPPDATA%\eNSP-MCP\eNSP-MCP.exe"

if not exist "%EXE%" (
    echo [ERROR] eNSP-MCP.exe was not found.
    echo Put diagnose.cmd next to eNSP-MCP.exe, or run install.cmd first.
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo   eNSP MCP self check
echo ============================================================
echo.
echo Exe: %EXE%
echo.
"%EXE%" --selftest
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
    echo [OK] eNSP devices were found. You can configure your AI client now.
) else if "%CODE%"=="2" (
    echo [INFO] The server works, but no eNSP device was found on ports 2000-2050.
    echo        Open eNSP and start the devices, then run this check again.
) else (
    echo [ERROR] The self check failed. Read the messages above.
    echo        If the port is busy, another program may be using it.
)
echo.
pause
endlocal
exit /b %CODE%
