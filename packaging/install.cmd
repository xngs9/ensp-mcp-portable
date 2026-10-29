@echo off
setlocal EnableExtensions
title eNSP MCP portable installer
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\eNSP-MCP"
set "DESTJSON=%DEST:\=\\%"

echo ============================================================
echo   eNSP MCP portable installer
echo ============================================================
echo.
echo Source : %SRC%
echo Install: %DEST%
echo Upstream: https://github.com/llz-2002/ensptomcpfortrae (author llz-2002)
echo.

if not exist "%SRC%eNSP-MCP.exe" (
    echo [ERROR] eNSP-MCP.exe was not found next to install.cmd.
    echo Keep all package files in the same folder and run install.cmd again.
    echo.
    pause
    exit /b 1
)

if not exist "%DEST%" mkdir "%DEST%"
if errorlevel 1 (
    echo [ERROR] Cannot create %DEST%
    echo.
    pause
    exit /b 1
)

copy /Y "%SRC%eNSP-MCP.exe" "%DEST%\eNSP-MCP.exe" >nul
if errorlevel 1 goto :copyfail
copy /Y "%SRC%ensp-mcp.cmd" "%DEST%\ensp-mcp.cmd" >nul
if errorlevel 1 goto :copyfail
if exist "%SRC%diagnose.cmd" copy /Y "%SRC%diagnose.cmd" "%DEST%\diagnose.cmd" >nul
if exist "%SRC%uninstall.cmd" copy /Y "%SRC%uninstall.cmd" "%DEST%\uninstall.cmd" >nul
if exist "%SRC%install.ps1" copy /Y "%SRC%install.ps1" "%DEST%\install.ps1" >nul
if exist "%SRC%README.md" copy /Y "%SRC%README.md" "%DEST%\README.md" >nul
if exist "%SRC%AI-*.md" copy /Y "%SRC%AI-*.md" "%DEST%\" >nul
if exist "%SRC%NOTICE.txt" copy /Y "%SRC%NOTICE.txt" "%DEST%\NOTICE.txt" >nul
if exist "%SRC%mcp-trae.json" copy /Y "%SRC%mcp-trae.json" "%DEST%\mcp-trae.json" >nul
if exist "%SRC%mcp-cursor.json" copy /Y "%SRC%mcp-cursor.json" "%DEST%\mcp-cursor.json" >nul
if exist "%SRC%mcp-generic.json" copy /Y "%SRC%mcp-generic.json" "%DEST%\mcp-generic.json" >nul
if exist "%SRC%claude-code-command.txt" copy /Y "%SRC%claude-code-command.txt" "%DEST%\claude-code-command.txt" >nul
if exist "%SRC%SHA256.txt" copy /Y "%SRC%SHA256.txt" "%DEST%\SHA256.txt" >nul

echo [OK] Files copied to %DEST%
echo.

if defined ENSP_MCP_ADD_PATH goto :add_path
if defined ENSP_MCP_NO_PROMPT goto :no_path
choice /C YN /N /M "Add %DEST% to your user PATH (recommended)? [Y/N] "
if errorlevel 2 goto :no_path

:add_path
if exist "%SRC%install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%install.ps1" -AddPath -Dir "%DEST%"
) else (
    echo [WARN] install.ps1 not found; add %DEST% to PATH manually if needed.
)
echo.
echo [NOTE] Restart Trae / Claude Code / Cursor so they see the new PATH.
goto :config

:no_path
echo.
echo [INFO] User PATH was not changed. Use the full exe path in your MCP config.

:config
echo.
echo ============================================================
echo   MCP config: merge this into your AI client's mcpServers
echo ============================================================
echo.
echo Option A - short command (requires PATH + client restart):
echo {
echo   "mcpServers": {
echo     "ensp": {
echo       "command": "ensp-mcp",
echo       "args": ["--mcp"]
echo     }
echo   }
echo }
echo.
echo Option B - full path (always works, no PATH needed):
echo {
echo   "mcpServers": {
echo     "ensp": {
echo       "command": "%DESTJSON%\\eNSP-MCP.exe",
echo       "args": ["--mcp"]
echo     }
echo   }
echo }
echo.
echo Claude Code, Option A:
echo   claude mcp add ensp --scope user ensp-mcp
echo.
echo Claude Code, Option B:
echo   claude mcp add ensp --scope user "%DEST%\eNSP-MCP.exe"
echo.
echo Before first use: open eNSP and start the devices.
echo Self check: double-click diagnose.cmd.
echo Uninstall : run uninstall.cmd.
echo.
if not defined ENSP_MCP_NO_PROMPT pause
endlocal
exit /b 0

:copyfail
echo [ERROR] Copy failed. Close any running eNSP-MCP.exe and try again.
echo.
pause
exit /b 1
